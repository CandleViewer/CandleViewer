"""`_first_failure` against a model of the former per-op loop (E14-T01, slice C5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, assert_never

import pytest
from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from candleviewer.storage.repositories.drawings import (
    BatchOp,
    BatchOpFailed,
    CreateOp,
    DeleteOp,
    DrawingFields,
    UpdateOp,
)
from candleviewer.storage.repositories.drawings_sqlalchemy import _first_failure

_T = datetime(2026, 10, 1, tzinfo=UTC)
_OWNER = "owner-a"
_ids = [f"id-{n}" for n in range(4)]


def _fields(symbol: str, tool: str) -> DrawingFields:
    return DrawingFields(symbol, None, tool, {}, {}, None, False, True, 0, None, None)


def _reference(
    owner: str, ops: list[BatchOp], snap: dict[str, dict[str, Any]]
) -> tuple[int, str] | None:
    """Model of the pre-C5 per-op loop (rules + simulated write-time outcomes).

    Each op's snapshot checks, then a simulated write against the live row state: the old
    `_UPDATE` matched only on the original token and a live row (0 rows -> target_unavailable),
    `_SOFT_DELETE` matched only a live row, and a create INSERT hit the PK of an earlier create.
    """
    live: dict[str, dict[str, Any]] = {k: dict(v) for k, v in snap.items()}
    version: dict[str, int] = {k: 0 for k in snap}  # bumped by each simulated UPDATE
    inserted: set[str] = set()
    try:
        for i, op in enumerate(ops):
            existing = snap.get(op.id)
            if isinstance(op, CreateOp):
                if existing is not None or op.id in inserted:
                    raise BatchOpFailed(i, "id_unavailable")
                inserted.add(op.id)
                continue
            if existing is None or existing["owner_user_id"] != owner or existing["deleted_at"]:
                raise BatchOpFailed(i, "target_unavailable")
            if existing["updated_at"] != op.if_match:
                raise BatchOpFailed(i, "version_conflict")
            row = live[op.id]
            if isinstance(op, UpdateOp):
                if op.fields.symbol != existing["symbol"] or op.fields.tool != existing["tool"]:
                    raise BatchOpFailed(i, "immutable_field")
                if row["deleted_at"] or version[op.id] != 0:  # token moved on / row gone
                    raise BatchOpFailed(i, "target_unavailable")
                version[op.id] += 1
            elif isinstance(op, DeleteOp):
                if row["deleted_at"]:
                    raise BatchOpFailed(i, "target_unavailable")
                row["deleted_at"] = _T
            else:
                assert_never(op)
    except BatchOpFailed as exc:
        return exc.index, exc.rule
    return None


_row = st.fixed_dictionaries(
    {
        "owner_user_id": st.sampled_from([_OWNER, _OWNER, _OWNER, "owner-b"]),
        "symbol": st.sampled_from(["BTCUSDT", "ETHUSDT"]),
        "tool": st.sampled_from(["trendline", "rectangle"]),
        "deleted_at": st.sampled_from([None, None, None, _T]),
        "updated_at": st.sampled_from([_T, _T + timedelta(microseconds=1)]),
    }
)
_T1 = _T + timedelta(microseconds=1)


@st.composite
def _case(draw: st.DrawFn) -> tuple[list[BatchOp], dict[str, dict[str, Any]]]:
    """A snapshot plus ops that usually carry the snapshot row's token, symbol and tool, so
    repeated ids reach the write-time rules instead of failing the first checks."""
    snap = draw(st.dictionaries(st.sampled_from(_ids), _row, max_size=8))
    ops: list[BatchOp] = []
    for op_id in draw(st.lists(st.sampled_from(_ids), max_size=8)):
        row = snap.get(op_id)
        kind = draw(st.sampled_from(["create", "update", "update", "delete", "delete"]))
        faithful = draw(st.sampled_from([True, True, True, False]))
        if row is not None and faithful:
            token, symbol, tool = row["updated_at"], row["symbol"], row["tool"]
        else:
            token = draw(st.sampled_from([_T, _T1]))
            symbol = draw(st.sampled_from(["BTCUSDT", "ETHUSDT"]))
            tool = draw(st.sampled_from(["trendline", "rectangle"]))
        f = _fields(symbol, tool)
        if draw(st.integers(0, 9)) == 0:
            ops.append(CreateOp(op_id, f))
        elif kind == "update":
            ops.append(UpdateOp(op_id, token, f))
        else:
            ops.append(DeleteOp(op_id, token))
    return ops, snap


@seed(20261014)
@settings(max_examples=1000, deadline=None, derandomize=True,
          suppress_health_check=[HealthCheck.too_slow])  # fmt: skip
@given(case=_case())
def test_first_failure_agrees_with_the_modelled_per_op_loop(
    case: tuple[list[BatchOp], dict[str, dict[str, Any]]],
) -> None:
    ops, snap = case
    assert _first_failure(_OWNER, ops, snap) == _reference(_OWNER, ops, snap)


def _live(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"owner_user_id": _OWNER, "symbol": "BTCUSDT", "tool": "trendline",
                           "deleted_at": None, "updated_at": _T}  # fmt: skip
    row.update(over)
    return row


_F = _fields("BTCUSDT", "trendline")
_MOVED = _fields("ETHUSDT", "trendline")
_X = "x"


@pytest.mark.parametrize(
    ("ops", "expected"),
    [
        ([UpdateOp(_X, _T, _F), UpdateOp(_X, _T, _F)], (1, "target_unavailable")),
        ([DeleteOp(_X, _T), UpdateOp(_X, _T, _F)], (1, "target_unavailable")),
        ([DeleteOp(_X, _T), DeleteOp(_X, _T)], (1, "target_unavailable")),
        ([UpdateOp(_X, _T, _F), DeleteOp(_X, _T)], None),
        ([UpdateOp(_X, _T, _F), UpdateOp(_X, _T1, _F)], (1, "version_conflict")),
        ([UpdateOp(_X, _T, _F), UpdateOp(_X, _T, _MOVED)], (1, "immutable_field")),
    ],
)
def test_repeated_live_id_follows_the_old_write_time_outcome(
    ops: list[BatchOp], expected: tuple[int, str] | None
) -> None:
    assert _first_failure(_OWNER, ops, {_X: _live()}) == expected
    assert _reference(_OWNER, ops, {_X: _live()}) == expected


@pytest.mark.parametrize(
    "snap",
    [{}, {_X: _live(owner_user_id="owner-b")}, {_X: _live(deleted_at=_T)}],
    ids=["missing", "foreign", "deleted"],
)
@pytest.mark.parametrize("second", [UpdateOp(_X, _T, _F), DeleteOp(_X, _T)])
def test_repeated_unavailable_id_fails_at_the_first_occurrence(
    snap: dict[str, dict[str, Any]], second: BatchOp
) -> None:
    ops: list[BatchOp] = [UpdateOp(_X, _T, _F), second]
    assert _first_failure(_OWNER, ops, snap) == (0, "target_unavailable")


def test_repeated_create_id_collides_at_the_second_create() -> None:
    ops: list[BatchOp] = [CreateOp("c", _F), CreateOp("c", _F)]
    assert _first_failure(_OWNER, ops, {}) == (1, "id_unavailable")


def test_first_failure_none_for_clean_batch() -> None:
    ops: list[BatchOp] = [CreateOp("c", _F), UpdateOp(_X, _T, _F)]
    assert _first_failure(_OWNER, ops, {_X: _live()}) is None
