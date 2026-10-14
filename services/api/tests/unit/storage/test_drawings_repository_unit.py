"""Pure parts of the drawings repository (E14-T01): tokens, rows, ops, SQL scoping.

Real-DB behaviour lives in `tests/integration/storage/test_drawings_repository.py` (CI-only).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import drawings_sqlalchemy as mod
from candleviewer.storage.repositories.drawings import (
    BatchOpFailed,
    BatchResult,
    CreateOp,
    DeleteOp,
    DrawingFields,
    UpdateOp,
    format_token,
)

_T = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _fields() -> DrawingFields:
    return DrawingFields(
        "BTCUSDT", None, "trendline", {"points": []}, {}, None, False, True, 0, _T, _T
    )


def _mapping(**over: object) -> dict[str, object]:
    d: dict[str, object] = {
        "id": "i", "owner_user_id": "o", "symbol": "BTCUSDT", "layout_id": None,
        "tool": "trendline", "geometry": '{"points":[{"p":"1.10","t":"x"}]}', "style": {},
        "label": None, "locked": False, "visible": True, "z_index": 0,
        "created_at": _T, "updated_at": _T,
    }  # fmt: skip
    d.update(over)
    return d


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_T, "2026-10-01T12:00:00.000000Z"),
        (_T.replace(microsecond=5), "2026-10-01T12:00:00.000005Z"),
        (_T.replace(microsecond=123456), "2026-10-01T12:00:00.123456Z"),
        (_T.astimezone(timezone(timedelta(hours=2))), "2026-10-01T12:00:00.000000Z"),
    ],
)
def test_format_token_always_six_fractional_digits_and_z(value: datetime, expected: str) -> None:
    assert format_token(value) == expected


def test_row_token_uses_updated_at() -> None:
    row = mod._to_row(_mapping())
    expected = "2026-10-01T12:00:00.000000Z"
    assert row.token == expected


def test_to_row_decodes_json_text_and_keeps_decimal_strings_verbatim() -> None:
    row = mod._to_row(_mapping())
    assert row.geometry == {"points": [{"p": "1.10", "t": "x"}]}
    assert row.style == {}


def test_to_row_accepts_already_decoded_json() -> None:
    assert mod._to_row(_mapping(geometry={"points": []})).geometry == {"points": []}


def test_json_is_canonical() -> None:
    assert mod._json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'
    assert json.loads(mod._json({"p": "0.10"})) == {"p": "0.10"}


def test_params_cover_every_writable_column() -> None:
    assert set(mod._params(_fields())) == {
        "symbol", "layout", "tool", "geometry", "style", "label", "locked", "visible",
        "z_index", "anchor_start", "anchor_end",
    }  # fmt: skip


def test_ops_and_results_are_frozen_value_objects() -> None:
    f = _fields()
    assert CreateOp("a", f) == CreateOp("a", f)
    assert UpdateOp("a", _T, f).if_match == _T
    assert DeleteOp("a", _T).id == "a"
    assert BatchResult((), (), ()).deleted == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        frozen: Any = DeleteOp("a", _T)  # Any: assigning to a frozen field is the point
        frozen.id = "b"


def test_batch_op_failed_carries_index_and_rule() -> None:
    err = BatchOpFailed(3, "target_unavailable")
    assert (err.index, err.rule) == (3, "target_unavailable")
    assert "operations.3" in str(err)


# Self-discovering: a statement added later cannot dodge the owner-filter guard.
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}


def test_the_statement_set_is_pinned() -> None:
    assert set(_STATEMENTS) == {
        "_INSERT", "_GET", "_EXISTS_OTHER", "_LIST", "_UPDATE", "_SOFT_DELETE", "_SNAPSHOT",
        "_PURGE",
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_every_statement_is_owner_scoped_except_the_unscoped_ones(name: str) -> None:
    text = str(_STATEMENTS[name])
    if name == "_INSERT":  # no WHERE clause: the owner is written as a bound value
        assert "CAST(:owner AS uuid)" in text
    elif name not in mod.UNSCOPED:
        assert "owner_user_id = CAST(:owner AS uuid)" in text


def test_only_three_statements_are_unscoped() -> None:
    assert mod.UNSCOPED == frozenset({"_EXISTS_OTHER", "_SNAPSHOT", "_PURGE"})
    assert set(mod.UNSCOPED) <= set(_STATEMENTS)


def test_snapshot_locks_rows_in_a_deterministic_order() -> None:
    assert "ORDER BY id FOR UPDATE" in str(_STATEMENTS["_SNAPSHOT"])


def test_read_allow_list_excludes_internal_columns() -> None:
    for hidden in ("deleted_at", "anchor_", "alert_id", "interval_scope"):
        assert hidden not in mod.DRAWING_COLUMNS


@pytest.mark.parametrize("name", ["_UPDATE", "_SOFT_DELETE"])
def test_updates_bump_the_token_monotonically(name: str) -> None:
    assert "greatest(clock_timestamp(), updated_at + interval '1 microsecond')" in str(
        _STATEMENTS[name]
    )


def test_list_uses_the_index_friendly_shape() -> None:
    text = str(_STATEMENTS["_LIST"])
    assert "symbol = :symbol" in text and "ORDER BY id LIMIT :limit" in text


@pytest.mark.parametrize("name", ["_INSERT", "_GET", "_LIST", "_UPDATE"])
def test_literal_column_lists_match_the_allow_list(name: str) -> None:
    assert mod.DRAWING_COLUMNS in str(_STATEMENTS[name])


def test_json_refuses_nan_and_infinity() -> None:
    with pytest.raises(ValueError, match="Out of range"):
        mod._json({"p": float("nan")})


def test_pk_collision_needs_sqlstate_23505_and_the_pk_constraint() -> None:
    from sqlalchemy.exc import IntegrityError

    class _Orig(Exception):
        def __init__(self, sqlstate: str, constraint: str) -> None:
            super().__init__("boom")
            self.sqlstate = sqlstate
            self.constraint_name = constraint

    def err(state: str, name: str) -> IntegrityError:
        return IntegrityError("s", {}, _Orig(state, name))

    assert mod._is_pk_collision(err("23505", "drawings_pkey"))
    assert not mod._is_pk_collision(err("23505", "other_key"))
    assert not mod._is_pk_collision(err("23503", "drawings_pkey"))


@pytest.mark.parametrize(
    ("days", "limit"),
    [(0, 10), (-1, 10), (90, 0), (90, -5), (90, mod.MAX_PURGE_BATCH + 1)],
)
async def test_purge_rejects_unsafe_arguments_before_touching_the_database(
    days: int, limit: int
) -> None:
    unused: Any = object()  # never touched: the ValueError fires first
    repo = mod.SqlAlchemyDrawingRepository(unused)
    with pytest.raises(ValueError, match="purge needs"):
        await repo.purge_deleted(days, limit)


def test_pk_collision_reads_the_constraint_from_the_driver_exception_cause() -> None:
    from sqlalchemy.exc import IntegrityError

    class _Driver(Exception):
        constraint_name = "drawings_pkey"

    class _Wrapper(Exception):
        sqlstate = "23505"

    wrapper = _Wrapper("dup")
    wrapper.__cause__ = _Driver()
    assert mod._is_pk_collision(IntegrityError("s", {}, wrapper))
    bare = _Wrapper("dup")  # no constraint anywhere: fail closed
    assert not mod._is_pk_collision(IntegrityError("s", {}, bare))


def test_immutable_field_is_a_known_batch_rule() -> None:
    from candleviewer.storage.repositories.drawings import BATCH_RULES

    assert "immutable_field" in BATCH_RULES
    assert BatchOpFailed(2, "immutable_field").rule in BATCH_RULES
    assert "immutable_field" in (mod.__doc__ or "")


def test_snapshot_selects_symbol_and_tool_for_the_immutability_check() -> None:
    text = str(_STATEMENTS["_SNAPSHOT"])
    assert "symbol" in text and "tool" in text
