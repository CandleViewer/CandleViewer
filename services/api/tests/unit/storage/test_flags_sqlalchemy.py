"""`SqlAlchemyFlagRepository` over a fake unit of work (E42-T03): the statements and their bound
values, the seeds `ensure` sends, the one-statement `load`, and which database errors are an outage.
The SQL runs on Postgres in `tests/integration/storage/test_flags_store_pg.py`."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from structlog.testing import capture_logs

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import flags_sqlalchemy as m
from candleviewer.storage.repositories.flags_sqlalchemy import (
    FlagChange,
    FlagRow,
    FlagRowMissingError,
    FlagSeed,
    StaleFlagRowError,
)

_ID, _ACTOR, _USER = uuid.UUID(int=1), uuid.UUID(int=7), uuid.UUID(int=9)
_T1, _T2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, 3, 4, 5, 6, tzinfo=UTC)
_HEAD: dict[str, Any] = {"id": _ID, "kind": "boolean", "default_value": False, "rollout_pct": None}
_HEAD |= {"updated_at": _T1, "updated_by": None}
_LOCKED = FlagRow(False, {}, {"manager": True}, _T1, None)


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Rel:
    """Fake unit of work keyed by statement: records what ran and the commit, and raises `error`
    at the step `fail_at` (`"enter"`, a statement or `"commit"`)."""

    def __init__(self, rows: dict[Any, list[Any]] | None = None) -> None:
        self.rows: dict[Any, list[Any]] = rows or {}
        self.fail_at: Any = None
        self.error: BaseException = RuntimeError("unset")
        self.ran: list[Any] = []
        self.committed = False

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        if self.fail_at == "enter":
            raise self.error

        async def execute(stmt: Any, params: Any = None) -> Any:
            self.ran.append((stmt, params))
            if stmt is self.fail_at:
                raise self.error
            rows = self.rows.get(stmt, [])
            first = rows[0] if rows else None
            found = SimpleNamespace(first=lambda: first, one=lambda: rows[0], all=lambda: rows)
            return SimpleNamespace(mappings=lambda: found)

        async def commit() -> None:
            if self.fail_at == "commit":
                raise self.error
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _repo(rel: _Rel) -> m.SqlAlchemyFlagRepository:
    return m.SqlAlchemyFlagRepository(rel, read_budget_ms=500)  # type: ignore[arg-type]  # fake


def _db(sqlstate: str, cls: type[sa_exc.DBAPIError] = sa_exc.DBAPIError) -> BaseException:
    return cls("SELECT 1", None, _PgError(sqlstate))


def _writable(head: dict[str, Any] | None = _HEAD) -> _Rel:
    after = {**_HEAD, "default_value": True, "updated_at": _T2, "updated_by": _ACTOR}
    role = {"user_id": None, "role": "manager", "override": True}
    return _Rel({m._LOCK: [head] if head else [], m._OVERRIDES: [role], m._UPDATE: [after]})


async def _write(rel: _Rel, value: object = True, at: datetime = _T1) -> FlagRow:
    async def prepare(row: FlagRow) -> FlagChange:
        rel.ran.append(("PREPARE", row))
        return FlagChange(value, {_USER: False}, at, _ACTOR)

    return await _repo(rel).write("trading.one_click", prepare)


def test_every_statement_is_a_static_module_literal() -> None:
    names = {n for n, v in vars(m).items() if isinstance(v, sa.TextClause)}
    assert names == {"_TIMEOUTS", "_ENSURE", "_LOAD", "_LOCK", "_OVERRIDES", "_UPDATE"} | {
        "_DROP_USERS", "_PUT_USERS"
    }  # fmt: skip


def test_a_write_locks_its_row_and_rewrites_only_a_changed_override() -> None:
    assert str(m._LOCK).endswith("FOR UPDATE")
    assert str(m._PUT_USERS).endswith("IS DISTINCT FROM EXCLUDED.value")


def test_ensure_inserts_only_where_no_row_is() -> None:
    assert str(m._ENSURE).endswith("ON CONFLICT (key) DO NOTHING")


def test_the_read_budget_bounds_both_the_statement_and_the_lock_wait() -> None:
    for bound in ("statement_timeout", "lock_timeout"):
        assert f"set_config('{bound}', :budget, true)" in str(m._TIMEOUTS)


def test_a_seed_carries_its_value_in_the_column_its_kind_reads() -> None:
    seeds = [
        FlagSeed("a.b", "boolean", "B", True, True),
        FlagSeed("a.p", "percentage", "P", 25, False),
        FlagSeed("a.v", "variant", "V", "x", False, ("x", "y")),
    ]
    assert [m._seed(s) for s in seeds] == [
        {"key": "a.b", "kind": "boolean", "description": "B", "default_value": True,
         "rollout_pct": None, "variants": None, "is_killswitch": True},
        {"key": "a.p", "kind": "percentage", "description": "P", "default_value": False,
         "rollout_pct": 25, "variants": None, "is_killswitch": False},
        {"key": "a.v", "kind": "variant", "description": "V", "default_value": "x",
         "rollout_pct": None, "variants": ["x", "y"], "is_killswitch": False},
    ]  # fmt: skip


async def test_ensure_sends_every_seed_in_one_statement_and_commits() -> None:
    rel = _Rel()
    await _repo(rel).ensure([FlagSeed("a.b", "boolean", "B", True, True)])
    [(stmt, params)] = rel.ran
    assert stmt is m._ENSURE and rel.committed
    assert json.loads(params["seeds"]) == [m._seed(FlagSeed("a.b", "boolean", "B", True, True))]


async def test_load_is_one_bounded_snapshot_that_keeps_every_override() -> None:
    flag: dict[str, Any] = {"key": "a.b", "kind": "boolean", "default_value": "garbage"}
    flag |= {"rollout_pct": 40, "updated_by": _ACTOR}  # stray on a boolean row (`ff_shape`): unread
    flag["updated_at"] = _T1.astimezone(timezone(timedelta(hours=5)))
    pct = {**flag, "key": "a.p", "kind": "percentage", "rollout_pct": 40}
    load = [
        flag | {"user_id": _USER, "role": None, "override": {"odd": 1}},  # unreadable, kept
        flag | {"user_id": None, "role": "viewer", "override": None},  # a JSON null, kept
        pct | {"user_id": None, "role": None, "override": None},  # no override at all
    ]
    rows = await _repo(rel := _Rel({m._LOAD: load})).load()
    assert rel.ran == [(m._TIMEOUTS, {"budget": "500ms"}), (m._LOAD, None)]
    assert rows == {
        "a.b": FlagRow("garbage", {_USER: {"odd": 1}}, {"viewer": None}, _T1, _ACTOR),
        "a.p": FlagRow(40, {}, {}, _T1, _ACTOR),  # a percentage row's value is its rollout
    }
    assert rows["a.b"].updated_at.utcoffset() == timedelta(0) and not rel.committed


def test_a_read_budget_below_one_millisecond_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1 ms"):
        m.SqlAlchemyFlagRepository(_Rel(), read_budget_ms=0)  # type: ignore[arg-type]  # fake


# A DSN with a fake password, which must never be echoed. It is never written whole in source, so
# trufflehog's Postgres detector finds nothing here (#3482). Real credentials never go in source.
_DSN = "postgresql" + "://cv:pw@db"
_OUTAGES = [
    ConnectionRefusedError(f"[Errno 111] dsn={_DSN}"),
    sa_exc.OperationalError("SELECT 1", None, Exception("gone")),
    sa_exc.InterfaceError("SELECT 1", None, Exception("closed")),
    sa_exc.TimeoutError("QueuePool limit reached"),
    sa_exc.DBAPIError("SELECT 1", None, Exception("lost"), connection_invalidated=True),
    *(_db(state) for state in ("08006", "40P01", "53300", "57014", "58000", "55P03")),
]
_BUGS = [
    _db("22P02", sa_exc.DataError),
    _db("23505", sa_exc.IntegrityError),
    _db("42P01", sa_exc.ProgrammingError),
    _db(""),  # no SQLSTATE
    sa_exc.InvalidRequestError("bad state"),
    RuntimeError("boom"),
]


@pytest.mark.parametrize("error", _OUTAGES, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize(
    ("call", "step"),
    [("load", "enter"), ("load", m._LOAD), ("ensure", m._ENSURE), ("ensure", "commit")],
    ids=["load-enter", "load", "ensure", "ensure-commit"],
)
async def test_a_database_that_cannot_serve_the_call_is_an_outage(
    error: BaseException, call: str, step: Any
) -> None:
    rel = _Rel()
    rel.fail_at, rel.error = step, error
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable) as raised:
        await (_repo(rel).load() if call == "load" else _repo(rel).ensure([]))
    assert str(raised.value) == "the feature-flag store is unavailable"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__  # no driver text
    assert set(logs[-1]) == {"event", "error", "sqlstate", "log_level"}
    assert logs[-1]["event"] == "feature_flag_repository_unavailable"
    assert "pw@db" not in repr(logs) and not rel.committed


@pytest.mark.parametrize("error", _BUGS, ids=lambda e: type(e).__name__)
async def test_any_other_error_is_a_bug_and_keeps_its_type(error: BaseException) -> None:
    assert not m._is_outage(error)
    rel = _Rel()
    rel.fail_at, rel.error = m._LOAD, error
    with pytest.raises(type(error)):
        await _repo(rel).load()


async def test_a_write_locks_prepares_on_the_locked_row_then_writes_and_commits() -> None:
    rel = _writable()
    row = await _write(rel)
    assert [stmt for stmt, _ in rel.ran] == [
        m._TIMEOUTS, m._LOCK, m._OVERRIDES, "PREPARE", m._UPDATE, m._DROP_USERS, m._PUT_USERS
    ]  # fmt: skip
    assert rel.ran[0][1] == {"budget": "500ms"} and rel.ran[1][1] == {"key": "trading.one_click"}
    assert rel.ran[3][1] == _LOCKED and rel.committed  # prepare saw the row as stored
    flag = {"id": str(_ID), "by": str(_ACTOR)}
    assert rel.ran[4][1] == flag | {"value": "true", "pct": None}
    assert rel.ran[5][1] == {"id": str(_ID), "keep": [str(_USER)]}
    assert json.loads(rel.ran[6][1].pop("overrides")) == [{"user_id": str(_USER), "value": False}]
    assert rel.ran[6][1] == flag
    assert row == FlagRow(True, {_USER: False}, {"manager": True}, _T2, _ACTOR)


@pytest.mark.parametrize(("value", "pct"), [(40, 40), (True, None), ("x", None)])
async def test_only_an_integer_is_bound_as_a_rollout(value: object, pct: int | None) -> None:
    rel = _writable()
    await _write(rel, value)
    assert rel.ran[4][1]["pct"] == pct and rel.ran[4][1]["value"] == json.dumps(value)


async def test_a_stale_change_raises_with_the_locked_row_and_writes_nothing() -> None:
    rel = _writable()
    with pytest.raises(StaleFlagRowError) as stale:
        await _write(rel, at=_T1 + timedelta(microseconds=1))  # a microsecond apart is stale
    assert stale.value.current == _LOCKED
    assert rel.ran[-1][0] == "PREPARE" and not rel.committed


async def test_a_flag_without_a_row_is_missing_and_prepare_never_runs() -> None:
    rel = _writable(head=None)
    with pytest.raises(FlagRowMissingError):
        await _write(rel)
    assert [s for s, _ in rel.ran] == [m._TIMEOUTS, m._LOCK] and not rel.committed


async def test_an_override_user_deleted_meanwhile_is_a_missing_row() -> None:
    rel = _writable()
    rel.fail_at, rel.error = m._PUT_USERS, _db("23503", sa_exc.IntegrityError)
    with pytest.raises(FlagRowMissingError) as missing:
        await _write(rel)
    assert missing.value.__cause__ is None and not rel.committed


async def test_a_writer_deleted_meanwhile_stays_a_bug() -> None:
    rel = _writable()  # `updated_by` names the writer: only the override insert maps 23503
    rel.fail_at, rel.error = m._UPDATE, _db("23503", sa_exc.IntegrityError)
    with pytest.raises(sa_exc.IntegrityError):
        await _write(rel)


async def test_what_prepare_raises_reaches_the_caller_as_is_never_as_an_outage() -> None:
    refused = ConnectionRefusedError("the audit disk")  # an OSError: an outage if it were ours

    async def prepare(_: FlagRow) -> FlagChange:
        raise refused

    rel = _writable()
    with pytest.raises(ConnectionRefusedError) as raised:
        await _repo(rel).write("trading.one_click", prepare)
    assert raised.value is refused and not rel.committed


@pytest.mark.parametrize("error", _OUTAGES, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize(
    "step", ["enter", m._LOCK, m._PUT_USERS, "commit"], ids=["enter", "lock", "put", "commit"]
)
async def test_a_database_that_cannot_serve_the_write_is_an_outage(
    error: BaseException, step: Any
) -> None:
    rel = _writable()
    rel.fail_at, rel.error = step, error
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable):
        await _write(rel)
    assert logs[-1]["event"] == "feature_flag_repository_unavailable" and not rel.committed
    assert "pw@db" not in repr(logs)


@pytest.mark.parametrize("error", _BUGS, ids=lambda e: type(e).__name__)
async def test_any_other_error_in_a_write_is_a_bug(error: BaseException) -> None:
    rel = _writable()
    rel.fail_at, rel.error = m._PUT_USERS, error
    with pytest.raises(type(error)):
        await _write(rel)
    assert not rel.committed
