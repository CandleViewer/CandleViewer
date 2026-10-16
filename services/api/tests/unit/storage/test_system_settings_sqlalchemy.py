"""`SqlAlchemySystemSettings` over a fake unit of work (E42-T01): the statements, their order and
bound values, the write-ahead hook before the commit, and which database errors are an outage. The
SQL itself runs on Postgres in `tests/integration/storage/test_system_settings_pg.py` (CI lane)."""

from __future__ import annotations

import asyncio
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

from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories import system_settings_sqlalchemy as m
from candleviewer.storage.repositories.system_settings import StoredSetting

_KEY, _ACTOR = "accounts.subaccount_tier", uuid.UUID(int=7)
_T1, _T2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, 3, 4, 5, tzinfo=UTC)
_BEFORE = {"value": "regular", "updated_at": _T1}
# Self-discovering: a statement added later cannot dodge the scope guard.
_STATEMENTS = {n: v for n, v in vars(m).items() if isinstance(v, sa.TextClause)}


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Rel:
    """Fake unit of work keyed by statement: records what ran (and the hook), the commit, and
    raises `error` at the step `fail_at`: `"enter"`, a statement, `"hook"` or `"commit"`."""

    def __init__(self, before: dict[str, Any] | None = _BEFORE) -> None:
        after = {"value": "business_kyc", "updated_at": _T2}
        self.rows = {m._SELECT: before, m._SELECT_LOCKED: before, m._UPSERT: after}
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
            row = self.rows.get(stmt)
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(first=lambda: row, one=lambda: row)
            )

        async def commit() -> None:
            if self.fail_at == "commit":
                raise self.error
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel, **kw: Any) -> m.SqlAlchemySystemSettings:
    return m.SqlAlchemySystemSettings(rel, **kw)  # type: ignore[arg-type]  # structural fake


async def _put(rel: _Rel, hook: Any = None, **kw: Any) -> StoredSetting:
    async def record(before: StoredSetting | None) -> None:
        rel.ran.append(("HOOK", before))
        if rel.fail_at == "hook":  # an `OSError` here is what `WriteAhead` warns hooks not to raise
            raise rel.error

    write_ahead = hook or record
    return await _store(rel, **kw).put_string(
        _KEY, "business_kyc", updated_by=_ACTOR, write_ahead=write_ahead
    )


# -- statements ---------------------------------------------------------------------------------


def test_every_row_statement_is_pinned_to_the_system_scope() -> None:
    assert set(_STATEMENTS) == {"_TIMEOUT", "_LOCK", "_SELECT", "_SELECT_LOCKED", "_UPSERT"}
    for name in ("_SELECT", "_SELECT_LOCKED", "_UPSERT"):
        text = str(_STATEMENTS[name])  # a per-user row of the same key stays out of reach
        assert "scope = 'system'" in text and ("key = :key" in text or "(key) WHERE" in text), name
    assert "'cv.settings.system:' || CAST(:key AS text)" in str(m._LOCK)
    assert "to_jsonb(CAST(:value AS text)), 'string', false" in str(m._UPSERT)
    assert "is_secret = false" in str(m._UPSERT)  # a plain string, never a stale secret flag


# -- reads and writes ---------------------------------------------------------------------------


async def test_a_read_caps_server_work_first_and_binds_the_key() -> None:
    rel = _Rel()
    assert await _store(rel).get_string(_KEY) == StoredSetting("regular", _T1)
    assert rel.ran == [(m._TIMEOUT, {"timeout": m.READ_TIMEOUT}), (m._SELECT, {"key": _KEY})]
    assert await _store(_Rel(before=None)).get_string(_KEY) is None


async def test_a_database_time_in_another_zone_is_read_as_utc() -> None:
    local = datetime(2026, 10, 1, 17, 30, tzinfo=timezone(timedelta(hours=5)))
    got = await _store(_Rel(before={"value": "regular", "updated_at": local})).get_string(_KEY)
    assert got == StoredSetting("regular", datetime(2026, 10, 1, 12, 30, tzinfo=UTC))
    assert got is not None and got.updated_at.utcoffset() == timedelta(0)


async def test_a_stored_json_null_reads_as_its_text_never_as_no_row() -> None:
    got = await _store(_Rel(before={"value": None, "updated_at": _T1})).get_string(_KEY)
    assert got == StoredSetting("null", _T1)  # a row that is no tier: the caller refuses it


async def test_a_write_locks_reads_writes_then_runs_the_hook_before_the_commit() -> None:
    rel = _Rel()
    stored = await _put(rel)
    assert [s for s, _ in rel.ran] == [m._LOCK, m._SELECT_LOCKED, m._UPSERT, "HOOK"]
    assert rel.committed and stored == StoredSetting("business_kyc", _T2)  # the upsert's own row
    assert rel.ran[3][1] == StoredSetting("regular", _T1)  # the hook saw the row under the lock
    assert [p for _, p in rel.ran[:3]] == [
        {"key": _KEY}, {"key": _KEY}, {"key": _KEY, "value": "business_kyc", "by": str(_ACTOR)}
    ]  # fmt: skip


async def test_a_first_write_hands_the_hook_no_row() -> None:
    rel = _Rel(before=None)
    await _put(rel)
    assert rel.ran[3] == ("HOOK", None)


async def test_a_refusing_hook_stops_before_the_commit_and_reaches_the_caller() -> None:
    class Refused(Exception):
        pass

    async def refuse(_: StoredSetting | None) -> None:
        raise Refused

    rel = _Rel()
    with pytest.raises(Refused):
        await _put(rel, refuse)
    assert not rel.committed


async def test_a_hook_that_outlives_its_bound_is_a_write_ahead_timeout_not_an_outage() -> None:
    async def hang(_: StoredSetting | None) -> None:
        await asyncio.Event().wait()

    rel = _Rel()
    with pytest.raises(WriteAheadTimeout):  # a `TimeoutError`, yet not the database's
        await _put(rel, hang, audit_timeout_s=0.01)
    assert not rel.committed


# -- which database errors are an outage ---------------------------------------------------------


def _db(sqlstate: str, cls: type[sa_exc.DBAPIError] = sa_exc.DBAPIError) -> BaseException:
    return cls("SELECT 1", None, _PgError(sqlstate))


_OUTAGES = [
    ConnectionRefusedError("[Errno 111] dsn=postgresql://cv:pw@db"),
    sa_exc.OperationalError("SELECT 1", None, Exception("gone")),
    sa_exc.InterfaceError("SELECT 1", None, Exception("closed")),
    sa_exc.TimeoutError("QueuePool limit reached"),
    sa_exc.DBAPIError("SELECT 1", None, Exception("lost"), connection_invalidated=True),
    *(_db(state) for state in ("08006", "40P01", "53300", "57014", "58000", "55P03")),
]
_BUGS = [
    _db("23505", sa_exc.IntegrityError),
    _db("42P01", sa_exc.ProgrammingError),
    _db(""),  # no SQLSTATE
    sa_exc.InvalidRequestError("bad state"),
    RuntimeError("boom"),
]


@pytest.mark.parametrize("error", _OUTAGES, ids=lambda e: type(e).__name__)
def test_a_database_that_cannot_serve_the_call_is_an_outage(error: BaseException) -> None:
    assert m._is_outage(error)


@pytest.mark.parametrize("error", _BUGS, ids=lambda e: type(e).__name__)
async def test_any_other_error_is_a_bug_and_keeps_its_type(error: BaseException) -> None:
    assert not m._is_outage(error)
    rel = _Rel()
    rel.fail_at, rel.error = m._UPSERT, error
    with pytest.raises(type(error)):
        await _put(rel)
    assert not rel.committed


@pytest.mark.parametrize("step", ["enter", m._LOCK, m._UPSERT, "hook", "commit"])
async def test_an_outage_at_any_step_of_a_write_is_a_fixed_store_outage(step: Any) -> None:
    rel = _Rel()
    rel.fail_at, rel.error = step, _OUTAGES[0]
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable) as raised:
        await _put(rel)
    assert raised.value.__cause__ is None and "postgresql" not in str(raised.value)
    assert [(log["event"], log["error"]) for log in logs] == [
        ("settings_store_unavailable", "ConnectionRefusedError")  # the class, never its message
    ]
    assert "pw" not in str(logs) and not rel.committed


@pytest.mark.parametrize("step", ["enter", m._TIMEOUT, m._SELECT])
async def test_an_outage_on_a_read_is_never_read_as_no_row(step: Any) -> None:
    rel = _Rel(before=None)
    rel.fail_at, rel.error = step, _db("57014")
    with pytest.raises(StorageTierUnavailable):
        await _store(rel).get_string(_KEY)


async def test_a_cancelled_write_is_never_swallowed() -> None:
    rel = _Rel()
    rel.fail_at, rel.error = m._UPSERT, asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await _put(rel)
