"""E15-T01 spec Sec.7 in the drawings repository (#402): the layout share-lock comes first in
every write transaction, a missing layout refuses the whole write with its request fields, the
0022 FK backstop maps to the same error, and a deadlock reruns the transaction once, then 503.

Stub units of work (one per attempt) replay a script of results or driver errors; the real lock
semantics are raced by the CI-only `test_drawings_layout_race.py`, added with the router change.
"""

from __future__ import annotations

import traceback
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from structlog.testing import capture_logs

from candleviewer.storage.errors import (
    StorageConstraintViolated,
    StorageQueryFailed,
    StorageTierUnavailable,
)
from candleviewer.storage.repositories import drawings_sqlalchemy as mod
from candleviewer.storage.repositories.drawings import (
    CreateOp,
    DeleteOp,
    DrawingFields,
    DrawingIdUnavailableError,
    DrawingLayoutNotFoundError,
    UpdateOp,
)

_T = datetime(2026, 10, 15, tzinfo=UTC)
_NAMES = {id(v): k for k, v in vars(mod).items() if isinstance(v, sa.TextClause)}
Step = list[dict[str, object]] | BaseException
_ROW = "canary-2748-row"  # a value the server's DETAIL would quote


class _Driver(Exception):
    def __init__(self, sqlstate: str, constraint: str | None = None) -> None:
        super().__init__(f"Failing row contains ({_ROW})")
        self.sqlstate, self.constraint_name = sqlstate, constraint


def _unchained(err: BaseException) -> bool:
    """Raised after its handler (#2748): no cause, no context, no text of the driver's."""
    text = "".join(traceback.format_exception(err))
    return err.__cause__ is None and err.__context__ is None and _ROW not in text


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def one(self) -> dict[str, object]:
        (row,) = self._rows
        return row

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[tuple[object, ...]]:
        return [tuple(r.values()) for r in self._rows]

    def __iter__(self) -> Any:
        return iter(self._rows)


class _Rel:
    """`unit_of_work()` factory: every unit shares one script, so attempts run in sequence."""

    def __init__(self, *script: Step) -> None:
        self.script, self.calls = list(script), list[tuple[str, dict[str, Any]]]()
        self.opened = self.commits = 0
        self.session = self

    def unit_of_work(self) -> _Rel:
        return self

    async def __aenter__(self) -> _Rel:
        self.opened += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, stmt: sa.TextClause, params: dict[str, Any]) -> _Result:
        self.calls.append((_NAMES[id(stmt)], params))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return _Result(step)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _repo(rel: _Rel) -> mod.SqlAlchemyDrawingRepository:
    return mod.SqlAlchemyDrawingRepository(rel)  # type: ignore[arg-type]  # stub UoW factory


def _f(layout: str | None) -> DrawingFields:
    return DrawingFields("BTCUSDT", layout, "trendline", {}, {}, None, False, True, 0, None, None)


def _row(i: str = "d", layout: str | None = "l1") -> dict[str, object]:
    return {"id": i, "owner_user_id": "o", "symbol": "BTCUSDT", "layout_id": layout,
            "tool": "trendline", "geometry": {}, "style": {}, "label": None, "locked": False,
            "visible": True, "z_index": 0, "created_at": _T, "updated_at": _T}  # fmt: skip


def _deadlock() -> DBAPIError:
    return DBAPIError("stmt", {}, _Driver("40P01"))


def _fk(name: str = mod.LAYOUT_FK) -> IntegrityError:
    return IntegrityError("stmt", {}, _Driver("23503", name))


async def _write(rel: _Rel, call: str, layout: str | None = "l1") -> Any:
    repo = _repo(rel)
    if call == "create":
        return await repo.create("o", "d", _f(layout))
    if call == "update":
        return await repo.update("o", "d", _f(layout), if_match=None)
    if call == "batch_update":
        return await repo.apply_batch("o", [UpdateOp("d", _T, _f(layout))])
    return await repo.apply_batch("o", [CreateOp("d", _f(layout))])


CALLS = ["create", "update", "batch", "batch_update"]  # POST, PUT, batch create, batch update
_OP = "operations.0.drawing.layout_id"
_FIELD = {"create": "layout_id", "update": "layout_id", "batch": _OP, "batch_update": _OP}
_WRITE = {"create": "_INSERT", "update": "_UPDATE", "batch": "_SNAPSHOT",
          "batch_update": "_SNAPSHOT"}  # fmt: skip
#: The batch snapshot of drawing "d" as the update op expects it (live, own, token `_T`); the
#: columns of the owner-scoped `_SNAPSHOT`, so "own" is its presence in the snapshot.
_SNAP = {"id": "d", "symbol": "BTCUSDT", "tool": "trendline", "deleted_at": None,
         "updated_at": _T}  # fmt: skip


def _ok(call: str) -> list[Step]:
    """One successful attempt: the layout lock, the batch snapshot, the write."""
    snapshot = {"batch": [[]], "batch_update": [[_SNAP]]}.get(call, [])
    return [[{"id": "l1"}], *snapshot, [_row()]]


def test_the_layout_lock_is_owner_scoped_live_and_in_id_order() -> None:
    tail = "owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL ORDER BY id FOR SHARE"
    assert str(mod._LAYOUTS_SHARE).endswith(tail)


@pytest.mark.parametrize("call", CALLS)
async def test_the_layout_lock_comes_before_any_drawings_statement(call: str) -> None:
    rel = _Rel(*_ok(call))
    await _write(rel, call)
    assert rel.names()[:2] == ["_LAYOUTS_SHARE", _WRITE[call]]
    assert rel.calls[0][1] == {"ids": ["l1"], "owner": "o"} and rel.commits == 1


async def test_a_write_without_layout_takes_no_layout_lock() -> None:
    rel = _Rel([_row(layout=None)])
    await _write(rel, "create", layout=None)
    assert rel.names() == ["_INSERT"]


async def test_missing_layouts_refuse_the_whole_batch_with_their_request_fields() -> None:
    ops = [CreateOp("a", _f("l2")), UpdateOp("u", _T, _f("gone")), DeleteOp("x", _T),
           CreateOp("b", _f(None)), CreateOp("c", _f("gone"))]  # fmt: skip
    rel = _Rel([{"id": "l2"}])
    with pytest.raises(DrawingLayoutNotFoundError) as err:
        await _repo(rel).apply_batch("o", ops)
    assert err.value.fields == ("operations.1.drawing.layout_id", "operations.4.drawing.layout_id")
    assert rel.calls == [("_LAYOUTS_SHARE", {"ids": ["gone", "l2"], "owner": "o"})]
    assert rel.commits == 0


@pytest.mark.parametrize("call", CALLS)
async def test_a_missing_layout_stops_the_write_before_any_drawings_statement(call: str) -> None:
    rel = _Rel([])
    with pytest.raises(DrawingLayoutNotFoundError) as err:
        await _write(rel, call)
    assert err.value.fields == (_FIELD[call],)
    assert rel.names() == ["_LAYOUTS_SHARE"] and rel.commits == 0


@pytest.mark.parametrize("call", CALLS)
async def test_the_layout_fk_backstop_maps_to_the_same_refusal(call: str) -> None:
    rel = _Rel(*_ok(call)[:-1], _fk())  # the check passed, the write then hit the FK
    with pytest.raises(DrawingLayoutNotFoundError) as err:
        await _write(rel, call)
    assert err.value.fields == (_FIELD[call],) and rel.commits == 0 and _unchained(err.value)


async def test_another_integrity_error_is_not_a_layout_refusal() -> None:
    fk = "fk_drawings_owner_user_id_users"
    rel = _Rel([{"id": "l1"}], _fk(fk))
    with pytest.raises(StorageConstraintViolated) as err:
        await _write(rel, "create")
    assert (err.value.sqlstate, err.value.constraint, rel.opened) == ("23503", fk, 1)
    assert _unchained(err.value)


async def test_a_primary_key_collision_is_id_unavailable() -> None:
    rel = _Rel([{"id": "l1"}], IntegrityError("stmt", {}, _Driver("23505", "drawings_pkey")))
    with pytest.raises(DrawingIdUnavailableError) as err:
        await _write(rel, "create")
    assert err.value.args == ("d",) and rel.opened == 1 and _unchained(err.value)


@pytest.mark.parametrize("call", CALLS)
async def test_a_deadlock_reruns_the_whole_transaction_once(call: str) -> None:
    rel = _Rel([{"id": "l1"}], _deadlock(), *_ok(call))
    await _write(rel, call)
    assert rel.opened == 2 and rel.commits == 1
    assert rel.names()[:3] == ["_LAYOUTS_SHARE", _WRITE[call], "_LAYOUTS_SHARE"]


@pytest.mark.parametrize("call", CALLS)
async def test_a_second_deadlock_is_a_store_outage(call: str) -> None:
    rel = _Rel([{"id": "l1"}], _deadlock(), [{"id": "l1"}], _deadlock())
    with pytest.raises(StorageTierUnavailable) as err:
        await _write(rel, call)
    assert rel.opened == 2 and rel.commits == 0 and _unchained(err.value)
    assert str(err.value) == "drawings write deadlocked twice"  # not the outage arm's message


async def test_a_refusal_on_the_rerun_is_typed_as_on_the_first_run() -> None:
    fk = "fk_drawings_owner_user_id_users"
    rel = _Rel([{"id": "l1"}], _deadlock(), [{"id": "l1"}], _fk(fk))
    with pytest.raises(StorageConstraintViolated) as err:
        await _write(rel, "create")
    assert (err.value.sqlstate, err.value.constraint, rel.opened) == ("23503", fk, 2)
    assert _unchained(err.value)


@pytest.mark.parametrize(
    ("state", "refusal", "sqlstate"),
    [("57014", StorageTierUnavailable, None), ("22P02", StorageQueryFailed, "22P02")],
    ids=["statement-timeout-503", "bad-input-500"],
)
async def test_other_database_errors_are_not_retried(
    state: str, refusal: type[Exception], sqlstate: str | None
) -> None:
    rel = _Rel(DBAPIError("stmt", {}, _Driver(state)))
    with pytest.raises(refusal) as err:
        await _write(rel, "create")
    assert type(err.value) is refusal and getattr(err.value, "sqlstate", None) == sqlstate
    assert rel.opened == 1 and _unchained(err.value)


async def test_an_outage_is_logged_by_its_sqlstate_alone() -> None:
    rel = _Rel(DBAPIError("stmt", {}, _Driver("57014")))
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable):
        await _write(rel, "create")
    assert logs == [
        {"event": "drawings_store_unavailable", "sqlstate": "57014", "log_level": "warning"}
    ]


def test_a_deadlock_is_read_from_the_wrapper_or_the_driver_cause() -> None:
    wrapper = Exception("wrapper")
    wrapper.__cause__ = _Driver("40P01")
    assert mod._is_deadlock(DBAPIError("s", {}, wrapper))
    assert mod._is_deadlock(_deadlock())
    assert not mod._is_deadlock(DBAPIError("s", {}, _Driver("40001")))
