"""`SqlAlchemyUserSettings` over a fake unit of work (E02-T13, #5181): the statements, their scope,
order and bound values, the write-ahead hook before the commit, and which database errors are an
outage. The SQL itself runs on Postgres in `tests/integration/storage/test_user_settings_pg.py`."""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from structlog.testing import capture_logs

from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories import user_settings_sqlalchemy as m
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.user_settings import LeafChange, UserSetting

_USER = uuid.UUID(int=7)
_T1, _T2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, 3, 4, 5, tzinfo=UTC)
_STATEMENTS = {n: v for n, v in vars(m).items() if isinstance(v, sa.TextClause)}


def _row(key: str, value: object, at: datetime = _T1) -> dict[str, Any]:
    return {"key": key, "value": json.dumps(value), "updated_at": at}


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._rows)

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Rel:
    """Fake unit of work: `held` answers both SELECTs, `upserted` the keys an upsert changes,
    `deleted` the keys a delete finds. Records what ran (the hook and the commit too, in order)
    and raises `error` at the step `fail_at`: `"enter"`, a statement, `"hook"` or `"commit"`."""

    def __init__(self, held: list[dict[str, Any]] | None = None) -> None:
        self.held = held if held is not None else [_row("appearance.theme", "dark")]
        self.upserted: dict[str, dict[str, Any]] = {}
        self.deleted: set[str] = set()
        self.fail_at: Any = None
        self.error: BaseException = RuntimeError("unset")
        self.ran: list[Any] = []
        self.committed = False

    def _answer(self, stmt: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        if stmt in (m._SELECT, m._SELECT_LOCKED):
            return self.held
        if stmt is m._UPSERT and params["key"] in self.upserted:
            return [self.upserted[params["key"]]]
        if stmt is m._DELETE and params["key"] in self.deleted:
            return [{"key": params["key"]}]
        return []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        if self.fail_at == "enter":
            raise self.error

        async def execute(stmt: Any, params: Any = None) -> _Result:
            self.ran.append((stmt, params))
            if stmt is self.fail_at:
                raise self.error
            return _Result(self._answer(stmt, params))

        async def commit() -> None:
            self.ran.append(("COMMIT", None))
            if self.fail_at == "commit":
                raise self.error
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel, **kw: Any) -> m.SqlAlchemyUserSettings:
    return m.SqlAlchemyUserSettings(cast(SqlAlchemyRelationalRepository, rel), **kw)


async def _apply(
    rel: _Rel, patch: dict[str, object], hook: Any = None, **kw: Any
) -> tuple[UserSetting, ...]:
    async def record(changes: tuple[LeafChange, ...]) -> None:
        rel.ran.append(("HOOK", changes))
        if rel.fail_at == "hook":
            raise rel.error

    return await _store(rel, **kw).apply(_USER, patch, write_ahead=hook or record)


def test_user_settings_statements_are_each_pinned_to_the_user_scope_and_one_user() -> None:
    assert set(_STATEMENTS) == {
        "_TIMEOUT",
        "_LOCK",
        "_SELECT",
        "_SELECT_LOCKED",
        "_UPSERT",
        "_DELETE",
    }
    for name in ("_SELECT", "_SELECT_LOCKED", "_DELETE"):
        text = str(_STATEMENTS[name])
        assert "scope = 'user' AND user_id = CAST(:user_id AS uuid)" in text, name
    upsert = str(m._UPSERT)
    assert "'user', CAST(:user_id AS uuid), :key" in upsert  # the row it inserts is the user's
    assert "ON CONFLICT (user_id, key) WHERE scope = 'user'" in upsert  # `ux_settings_user`
    assert "jsonb_typeof(v.j), false" in upsert and "is_secret = false" in upsert
    assert "WHERE settings.value IS DISTINCT FROM EXCLUDED.value" in upsert
    assert "'cv.settings.user:' || CAST(:user_id AS text)" in str(m._LOCK)
    assert not any("'system'" in str(stmt) for stmt in _STATEMENTS.values())


async def test_user_settings_read_caps_server_work_first_and_decodes_each_row() -> None:
    rel = _Rel([_row("appearance.theme", "dark"), _row("data.default_depth", 200)])
    rows = await _store(rel).read(_USER)
    assert rows == (
        UserSetting("appearance.theme", "dark", _T1),
        UserSetting("data.default_depth", 200, _T1),
    )
    assert rel.ran == [
        (m._TIMEOUT, {"timeout": m.READ_TIMEOUT}),
        (m._SELECT, {"user_id": str(_USER)}),
    ]


async def test_user_settings_read_takes_a_time_in_another_zone_as_utc() -> None:
    local = datetime(2026, 10, 1, 17, 30, tzinfo=timezone(timedelta(hours=5)))
    (row,) = await _store(_Rel([_row("appearance.theme", "dark", local)])).read(_USER)
    assert row.updated_at == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
    assert row.updated_at.utcoffset() == timedelta(0)


async def test_user_settings_apply_locks_reads_writes_by_key_then_hooks_before_the_commit() -> None:
    rel = _Rel([_row("appearance.theme", "dark"), _row("appearance.density", "compact")])
    rel.upserted["appearance.theme"] = _row("appearance.theme", "light", _T2)
    rel.deleted.add("appearance.density")
    rows = await _apply(rel, {"appearance.theme": "light", "appearance.density": None})
    uid = str(_USER)
    assert [step for step, _ in rel.ran] == [
        m._LOCK,
        m._SELECT_LOCKED,
        m._DELETE,
        m._UPSERT,
        "HOOK",
        "COMMIT",  # the record is written ahead of the commit, never after it
    ]
    assert [params for _, params in rel.ran[:4]] == [
        {"user_id": uid}, {"user_id": uid}, {"user_id": uid, "key": "appearance.density"},
        {"user_id": uid, "key": "appearance.theme", "value": '"light"'},
    ]  # fmt: skip
    assert rel.ran[4][1] == (
        LeafChange("appearance.density", "compact", None),
        LeafChange("appearance.theme", "dark", "light"),
    )
    assert rel.committed and rows == (UserSetting("appearance.theme", "light", _T2),)


async def test_user_settings_apply_that_changes_nothing_runs_no_hook_and_no_commit() -> None:
    rel = _Rel()  # the upsert answers no row (an equal value) and the delete finds none
    rows = await _apply(rel, {"appearance.theme": "dark", "appearance.density": None})
    assert "HOOK" not in [step for step, _ in rel.ran] and not rel.committed
    assert rows == (UserSetting("appearance.theme", "dark", _T1),)


async def test_user_settings_apply_never_binds_a_value_that_is_not_json() -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="JSON"):
        await _apply(rel, {"appearance.font_scale": math.nan})
    assert m._UPSERT not in [step for step, _ in rel.ran] and not rel.committed


async def test_user_settings_a_refusing_hook_stops_before_the_commit_and_reaches_the_caller() -> (
    None
):
    class Refused(Exception):
        pass

    async def refuse(_: tuple[LeafChange, ...]) -> None:
        raise Refused

    rel = _Rel()
    rel.upserted["appearance.theme"] = _row("appearance.theme", "light", _T2)
    with pytest.raises(Refused):
        await _apply(rel, {"appearance.theme": "light"}, refuse)
    assert not rel.committed


async def test_user_settings_a_hook_past_its_bound_is_a_write_ahead_timeout_not_an_outage() -> None:
    async def hang(_: tuple[LeafChange, ...]) -> None:
        await asyncio.Event().wait()

    rel = _Rel()
    rel.upserted["appearance.theme"] = _row("appearance.theme", "light", _T2)
    with pytest.raises(WriteAheadTimeout):
        await _apply(rel, {"appearance.theme": "light"}, hang, audit_timeout_s=0.01)
    assert not rel.committed


class _PgError(Exception):
    """A driver error as asyncpg raises it: a SQLSTATE, and text quoting a row."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__("Failing row contains (canary)")
        self.sqlstate = sqlstate


def _db(sqlstate: str, cls: type[sa_exc.DBAPIError] = sa_exc.DBAPIError) -> BaseException:
    return cls("SELECT 1", None, _PgError(sqlstate))


@pytest.mark.parametrize("step", ["enter", m._LOCK, m._UPSERT, "hook", "commit"])
async def test_user_settings_an_outage_at_any_step_of_a_write_is_a_fixed_store_outage(
    step: Any,
) -> None:
    rel = _Rel()
    rel.upserted["appearance.theme"] = _row("appearance.theme", "light", _T2)
    rel.fail_at, rel.error = step, ConnectionRefusedError("[Errno 111] refused")
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable) as raised:
        await _apply(rel, {"appearance.theme": "light"})
    assert (
        raised.value.__cause__ is None and str(raised.value) == "the settings store is unavailable"
    )
    assert [(log["event"], log["error"]) for log in logs] == [
        ("user_settings_store_unavailable", "ConnectionRefusedError")  # the class, never the text
    ]
    assert not rel.committed


@pytest.mark.parametrize("step", ["enter", m._TIMEOUT, m._SELECT])
async def test_user_settings_an_outage_on_a_read_is_never_read_as_no_rows(step: Any) -> None:
    rel = _Rel()
    rel.fail_at, rel.error = step, _db("57014")
    with capture_logs(), pytest.raises(StorageTierUnavailable):
        await _store(rel).read(_USER)


async def test_user_settings_any_other_database_error_is_a_bug_typed_by_its_facts() -> None:
    rel = _Rel()
    rel.fail_at, rel.error = m._UPSERT, _db("23514", sa_exc.IntegrityError)
    with pytest.raises(StorageQueryFailed) as raised:
        await _apply(rel, {"appearance.theme": "light"})
    assert raised.value.sqlstate == "23514" and raised.value.__cause__ is None
    assert "canary" not in str(raised.value) and not rel.committed


async def test_user_settings_a_cancelled_write_is_never_swallowed() -> None:
    rel = _Rel()
    rel.fail_at, rel.error = m._UPSERT, asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await _apply(rel, {"appearance.theme": "light"})
    assert not rel.committed
