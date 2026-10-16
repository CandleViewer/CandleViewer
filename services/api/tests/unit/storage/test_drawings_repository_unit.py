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
        "_PURGE", "_COUNT_LIVE", "_INSERT_MANY", "_UPDATE_MANY", "_SOFT_DELETE_MANY",
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_every_statement_is_owner_scoped_except_the_unscoped_ones(name: str) -> None:
    text = str(_STATEMENTS[name])
    if name in {
        "_INSERT",
        "_INSERT_MANY",
    }:  # no WHERE clause: the owner is written as a bound value
        assert "CAST(:owner AS uuid)" in text
    elif name not in mod.UNSCOPED:
        assert "owner_user_id = CAST(:owner AS uuid)" in text


def test_only_three_statements_are_unscoped() -> None:
    assert mod.UNSCOPED == frozenset({"_EXISTS_OTHER", "_PURGE", "_COUNT_LIVE"})
    assert set(mod.UNSCOPED) <= set(_STATEMENTS)


def test_purge_deletes_only_soft_deleted_rows_past_the_bounded_cutoff() -> None:
    """The one DELETE no owner filter scopes: these two guards are all that protects live rows."""
    text = str(_STATEMENTS["_PURGE"])
    assert "deleted_at IS NOT NULL" in text
    assert "deleted_at < now() - make_interval(days => CAST(:days AS integer))" in text


def test_snapshot_locks_rows_in_a_deterministic_order() -> None:
    assert "ORDER BY id FOR UPDATE" in str(_STATEMENTS["_SNAPSHOT"])


def test_snapshot_locks_only_the_callers_rows() -> None:
    """The owner filter is in the locking statement's own WHERE (#357 R1): a batch naming a
    foreign id must never take a row lock on, or wait for, another user's drawing."""
    text = str(_STATEMENTS["_SNAPSHOT"])
    where = text.split(" WHERE ", 1)[1].split(" ORDER BY ", 1)[0]
    assert "AND owner_user_id = CAST(:owner AS uuid)" in where and "FOR UPDATE" in text


def test_read_allow_list_excludes_internal_columns() -> None:
    for hidden in ("deleted_at", "anchor_", "alert_id", "interval_scope"):
        assert hidden not in mod.DRAWING_COLUMNS


@pytest.mark.parametrize("name", ["_UPDATE", "_SOFT_DELETE", "_UPDATE_MANY", "_SOFT_DELETE_MANY"])
def test_updates_bump_the_token_monotonically(name: str) -> None:
    assert "greatest(clock_timestamp(), updated_at + interval '1 microsecond')" in str(
        _STATEMENTS[name]
    )


def test_list_uses_the_index_friendly_shape() -> None:
    text = str(_STATEMENTS["_LIST"])
    assert "symbol = :symbol" in text and "ORDER BY id LIMIT :limit" in text


@pytest.mark.parametrize(
    "name", ["_INSERT", "_INSERT_MANY", "_GET", "_LIST", "_UPDATE", "_UPDATE_MANY"]
)
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


def test_target_not_owned_is_an_internal_batch_rule() -> None:
    from candleviewer.storage.repositories.drawings import BATCH_RULES

    assert "target_not_owned" in BATCH_RULES
    assert BatchOpFailed(1, "target_not_owned").rule == "target_not_owned"
    assert "target_not_owned" in (mod.__doc__ or "")


def test_batch_op_failed_rejects_an_unknown_rule() -> None:
    with pytest.raises(ValueError, match="unknown batch rule"):
        BatchOpFailed(0, "made_up")


def test_update_many_never_writes_the_immutable_columns() -> None:
    set_clause = str(_STATEMENTS["_UPDATE_MANY"]).split(" FROM ")[0]
    assert "symbol" not in set_clause and "tool" not in set_clause


# --- fail-closed branches of the set-based apply_batch (stub unit of work) ---------------


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)

    def all(self) -> list[Any]:
        return [tuple(r.values()) for r in self._rows]


class _Session:
    def __init__(self, script: list[list[dict[str, object]]]) -> None:
        self._script = script
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []

    async def execute(self, stmt: sa.TextClause, params: dict[str, Any]) -> _Result:
        self.statements.append(str(stmt)[:20])
        self.params.append(params)
        return _Result(self._script.pop(0))


class _Uow:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.commits = 0

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class _Rel:
    def __init__(self, script: list[list[dict[str, object]]]) -> None:
        self.uow = _Uow(_Session(script))

    def unit_of_work(self) -> _Uow:
        return self.uow


def _snap_row(i: str) -> dict[str, object]:  # the columns of `_SNAPSHOT`: the caller's rows only
    return {"id": i, "symbol": "BTCUSDT", "tool": "trendline", "deleted_at": None,
            "updated_at": _T}  # fmt: skip


async def _run(script: list[list[dict[str, object]]], ops: list[Any]) -> tuple[_Rel, BatchOpFailed]:
    rel = _Rel(script)
    repo = mod.SqlAlchemyDrawingRepository(rel)  # type: ignore[arg-type]  # stub UoW factory
    with pytest.raises(BatchOpFailed) as err:
        await repo.apply_batch("o", ops)
    return rel, err.value


async def test_batch_insert_returning_fewer_rows_is_id_unavailable_at_the_missing_create() -> None:
    ops = [CreateOp("a", _fields()), CreateOp("b", _fields()), CreateOp("c", _fields())]
    # snapshot empty; INSERT returns only a and c (b hit ON CONFLICT)
    script = [[], [_mapping(id="a"), _mapping(id="c")]]
    rel, err = await _run(script, ops)
    assert (err.index, err.rule) == (1, "id_unavailable")
    assert rel.uow.commits == 0


async def test_batch_update_returning_fewer_rows_is_target_unavailable_at_the_missing_op() -> None:
    ops = [CreateOp("n", _fields()), UpdateOp("u1", _T, _fields()), UpdateOp("u2", _T, _fields())]
    script = [[_snap_row("u1"), _snap_row("u2")], [_mapping(id="n")], [_mapping(id="u1")]]
    rel, err = await _run(script, ops)
    assert (err.index, err.rule) == (2, "target_unavailable")
    assert rel.uow.commits == 0


async def test_batch_delete_returning_fewer_ids_is_target_unavailable_at_the_missing_op() -> None:
    ops = [DeleteOp("d1", _T), DeleteOp("d2", _T)]
    script = [[_snap_row("d1"), _snap_row("d2")], [{"id": "d2"}]]
    rel, err = await _run(script, ops)
    assert (err.index, err.rule) == (0, "target_unavailable")
    assert rel.uow.commits == 0


async def test_the_snapshot_is_taken_for_the_caller_alone() -> None:
    rel, err = await _run([[]], [UpdateOp("u", _T, _fields())])
    assert rel.uow.session.params == [{"ids": ["u"], "owner": "o"}]  # the lock stays on own rows
    assert (err.index, err.rule) == (0, "target_not_owned")  # absent from it: foreign or missing
    assert rel.uow.session.statements == [str(_STATEMENTS["_SNAPSHOT"])[:20]]  # and nothing else
    assert rel.uow.commits == 0


@pytest.mark.parametrize("kind", ["update", "delete"])
@pytest.mark.parametrize(
    ("in_snapshot", "rule"), [(True, "target_unavailable"), (False, "target_not_owned")]
)
async def test_only_a_target_missing_from_the_snapshot_is_not_owned(
    kind: str, in_snapshot: bool, rule: str
) -> None:
    """R3/R4: a write that finds no row for a target the caller's snapshot holds fails closed as
    the caller's own `target_unavailable`. The API audits `target_not_owned` as a cross-owner
    probe, so relabelling either branch would audit the caller's own row."""
    op = UpdateOp("t", _T, _fields()) if kind == "update" else DeleteOp("t", _T)
    script: list[list[dict[str, object]]] = [[_snap_row("t")] if in_snapshot else [], []]
    rel, err = await _run(script, [op])
    assert (err.index, err.rule) == (0, rule)
    assert rel.uow.commits == 0


def test_storage_batch_cap_equals_the_api_cap() -> None:
    from candleviewer.api.drawings_models import MAX_BATCH_OPS

    assert mod.MAX_BATCH_OPS_STORAGE == MAX_BATCH_OPS


async def test_apply_batch_refuses_more_ops_than_the_cap_before_touching_the_database() -> None:
    rel = _Rel([])
    repo = mod.SqlAlchemyDrawingRepository(rel)  # type: ignore[arg-type]  # stub UoW factory
    ops = [CreateOp(str(n), _fields()) for n in range(mod.MAX_BATCH_OPS_STORAGE + 1)]
    with pytest.raises(ValueError, match="at most"):
        await repo.apply_batch("o", ops)
    assert rel.uow.session.statements == []


@pytest.mark.parametrize(
    "over", [{"locked": "yes"}, {"visible": 1}, {"z_index": "7"}, {"z_index": True}, {"label": 123}]
)
def test_row_json_refuses_mistyped_fields_instead_of_letting_postgres_coerce(
    over: dict[str, Any],
) -> None:
    with pytest.raises(TypeError, match="mistyped"):
        mod._row_json("i", dataclasses.replace(_fields(), **over))


def test_rows_param_keeps_non_ascii_text_unescaped() -> None:
    out = mod._rows_param([{"n_label": "é"}])
    assert "é" in out and "\\u00e9" not in out


async def test_apply_batch_accepts_exactly_the_cap_and_reaches_the_snapshot() -> None:
    rel = _Rel([[], [_mapping(id=str(n)) for n in range(mod.MAX_BATCH_OPS_STORAGE)]])
    repo = mod.SqlAlchemyDrawingRepository(rel)  # type: ignore[arg-type]  # stub UoW factory
    ops = [CreateOp(str(n), _fields()) for n in range(mod.MAX_BATCH_OPS_STORAGE)]
    result = await repo.apply_batch("o", ops)
    assert len(result.created) == mod.MAX_BATCH_OPS_STORAGE
    assert len(rel.uow.session.statements) == 2  # snapshot + one INSERT
    assert rel.uow.commits == 1
