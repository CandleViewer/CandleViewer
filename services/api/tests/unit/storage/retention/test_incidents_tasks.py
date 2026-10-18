"""E42-T05: the resolved-incidents purge (`21-database-schema.md` §7: a `resolved` incident is
dropped 24 months after its `last_seen_at`; open and acknowledged rows are kept), its schedule
entry and its wiring."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer import app as appmod
from candleviewer.settings import Settings
from candleviewer.storage.repositories.incidents_sqlalchemy import (
    MAX_PURGE_BATCH,
    SqlAlchemyIncidents,
    purge_statement,
)
from candleviewer.storage.retention import policy
from candleviewer.storage.retention.incidents_tasks import (
    MAX_BATCHES_PER_RUN,
    IncidentsPurgeTask,
)
from candleviewer.storage.retention.schedule import RetentionSchedule

_ON = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"})
_OFF = RetentionSchedule.from_env({})


class _Repo:
    def __init__(self, results: list[int | Exception]) -> None:
        self.results = results
        self.calls: list[tuple[int, int]] = []

    async def purge_resolved(self, older_than_months: int, limit: int) -> int:
        self.calls.append((older_than_months, limit))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_the_schedule_entry_follows_the_retention_flag() -> None:
    assert _OFF.incidents_jobs() == {}
    assert _ON.incidents_jobs() == {"incidents_purge": "0 3 * * *"}
    assert policy.INCIDENTS_RESOLVED_MONTHS == 24


async def test_a_run_drains_batches_until_a_short_one_and_logs_counts_only() -> None:
    repo = _Repo([MAX_PURGE_BATCH, MAX_PURGE_BATCH, 7])
    with capture_logs() as logs:
        await IncidentsPurgeTask(repo, _ON).run_once()
    assert repo.calls == [(24, MAX_PURGE_BATCH)] * 3
    assert logs == [
        {"event": "incidents_purged", "deleted": n, "log_level": "info"}
        for n in (MAX_PURGE_BATCH, MAX_PURGE_BATCH, 7)
    ]


async def test_a_run_is_bounded_by_its_batch_cap() -> None:
    repo = _Repo([MAX_PURGE_BATCH] * (MAX_BATCHES_PER_RUN + 5))
    await IncidentsPurgeTask(repo, _ON).run_once()
    assert len(repo.calls) == MAX_BATCHES_PER_RUN  # the next run continues the backlog


async def test_a_failed_batch_is_logged_by_class_and_the_loop_survives() -> None:
    repo = _Repo([RuntimeError("postgresql://cv:" + "hunter2" + "@db/cv"), 3])
    ticks, done = 0, asyncio.Event()

    async def sleep(_: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            done.set()
        await asyncio.sleep(0)

    task = IncidentsPurgeTask(repo, _ON, sleep=sleep)
    with capture_logs() as logs:
        task.start()
        task.start()  # idempotent: one loop
        await asyncio.wait_for(done.wait(), 2)
        await task.stop()
    assert logs[:2] == [
        {"event": "incidents_purge_failed", "error": "RuntimeError", "log_level": "error"},
        {"event": "incidents_purged", "deleted": 3, "log_level": "info"},
    ]
    assert not task.running and "hunter2" not in repr(logs)
    await task.stop()  # stopped: a no-op


async def test_a_disabled_schedule_never_starts() -> None:
    task = IncidentsPurgeTask(_Repo([]), _OFF)
    task.start()
    assert not task.running


def test_the_purge_is_built_on_the_real_backend_only() -> None:
    dsn = SecretStr("postgresql+asyncpg://cv@db/cv")
    real = Settings(storage_backend="real", retention_enabled=True, pg_dsn=dsn)
    fake = Settings(storage_backend="fake", retention_enabled=True, pg_dsn=dsn)
    task = appmod._build_incidents_purge(real)
    assert isinstance(task, IncidentsPurgeTask) and isinstance(task._repo, SqlAlchemyIncidents)
    assert appmod._build_incidents_purge(fake) is None


def test_create_app_assigns_the_purge_task_on_the_real_backend_and_none_on_the_fake() -> None:
    real = Settings(  # test-only values, not credentials
        storage_backend="real",
        retention_enabled=True,
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("pepper"),
    )
    task = appmod.create_app(real).state.incidents_purge_task
    assert isinstance(task, IncidentsPurgeTask) and task._enabled  # the lifespan starts it
    assert appmod.create_app(Settings(retention_enabled=True)).state.incidents_purge_task is None


def test_the_purge_picks_old_resolved_rows_and_rechecks_them_as_it_deletes() -> None:
    compiled = purge_statement(24, 500).compile()
    expired = (
        "incidents.status = :status_1 AND incidents.last_seen_at < "
        "now() - make_interval(:make_interval_1, :make_interval_2)"
    )
    sql = " ".join(str(compiled).split())
    head = "DELETE FROM incidents WHERE incidents.id IN (SELECT incidents.id FROM incidents WHERE "
    assert sql.startswith(head) and sql.count(expired) == 2
    assert " ORDER BY incidents.last_seen_at LIMIT :param_1) AND " in sql
    assert sql.endswith(expired)  # a row reopened meanwhile fails the outer predicate: kept
    assert {k: compiled.params[k] for k in ("status_1", "make_interval_2", "param_1")} == {
        "status_1": "resolved",
        "make_interval_2": 24,  # months
        "param_1": 500,
    }


class _Rel:
    def __init__(self) -> None:
        self.ended: list[str] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(_: Any) -> Any:
            return SimpleNamespace(rowcount=3)

        async def commit() -> None:
            self.ended.append("commit")

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


async def test_purge_resolved_commits_one_batch_and_returns_its_count() -> None:
    rel = _Rel()
    assert await SqlAlchemyIncidents(cast(Any, rel)).purge_resolved(24, MAX_PURGE_BATCH) == 3
    assert rel.ended == ["commit"]


@pytest.mark.parametrize(("months", "limit"), [(0, 1), (24, 0), (24, MAX_PURGE_BATCH + 1)])
async def test_purge_resolved_refuses_an_unbounded_or_empty_batch(months: int, limit: int) -> None:
    with pytest.raises(ValueError, match="older_than_months >= 1"):
        await SqlAlchemyIncidents(cast(Any, _Rel())).purge_resolved(months, limit)
