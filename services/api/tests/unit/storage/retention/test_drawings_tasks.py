"""E14-T01 (C4): drawings purge job, schedule entry and wiring."""

from __future__ import annotations

import asyncio

import structlog
from pydantic import SecretStr

from candleviewer.app import create_app
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.settings import Settings
from candleviewer.storage.repositories.drawings_sqlalchemy import MAX_PURGE_BATCH
from candleviewer.storage.retention import policy
from candleviewer.storage.retention.drawings_tasks import DrawingsPurgeTask
from candleviewer.storage.retention.schedule import RetentionSchedule

_ON = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"})
_OFF = RetentionSchedule.from_env({})


class _Repo:
    def __init__(self, results: list[int | Exception]) -> None:
        self.results = results
        self.calls: list[tuple[int, int]] = []

    async def purge_deleted(self, older_than_days: int, limit: int) -> int:
        self.calls.append((older_than_days, limit))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _counter() -> tuple[Metrics, BoundedMetric]:
    m = Metrics("demo")
    return m, m.counter("cv_drawings_purged_total", "x")


def _value(m: Metrics) -> float:
    return float(m.snapshot(["cv_drawings_purged"]).get("cv_drawings_purged_total", 0))


def test_schedule_on_and_off() -> None:
    assert _OFF.drawings_jobs() == {}
    assert _ON.drawings_jobs() == {"drawings_purge": "0 3 * * *"}
    assert policy.DRAWINGS_SOFT_DELETE_DAYS == 90


async def test_run_once_loops_until_short_batch_and_counts_total() -> None:
    m, c = _counter()
    repo = _Repo([MAX_PURGE_BATCH, MAX_PURGE_BATCH, 7])
    task = DrawingsPurgeTask(repo, _ON, c)
    with structlog.testing.capture_logs() as logs:
        await task.run_once()
    assert repo.calls == [(90, MAX_PURGE_BATCH)] * 3
    assert _value(m) == 2 * MAX_PURGE_BATCH + 7
    assert [e["event"] for e in logs] == ["drawings_purged"]
    assert logs[0]["deleted"] == 2 * MAX_PURGE_BATCH + 7


async def test_run_once_zero_rows_logs_and_leaves_counter() -> None:
    m, c = _counter()
    task = DrawingsPurgeTask(_Repo([0]), _ON, c)
    with structlog.testing.capture_logs() as logs:
        await task.run_once()
    assert _value(m) == 0
    assert [e["event"] for e in logs] == ["drawings_purged"]


async def test_failure_is_logged_and_loop_survives() -> None:
    _, c = _counter()
    repo = _Repo([RuntimeError("db down"), 3])
    ticks = 0
    done = asyncio.Event()

    async def sleep(_: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            done.set()
        await asyncio.sleep(0)

    task = DrawingsPurgeTask(repo, _ON, c, sleep=sleep)
    with structlog.testing.capture_logs() as logs:
        task.start()
        await asyncio.wait_for(done.wait(), 2)
        await task.stop()
    events = [e["event"] for e in logs]
    assert events[:2] == ["drawings_purge_failed", "drawings_purged"]


async def test_start_is_idempotent_and_stop_cancels() -> None:
    _, c = _counter()
    gate = asyncio.Event()

    async def sleep(_: float) -> None:
        await gate.wait()

    task = DrawingsPurgeTask(_Repo([0] * 5), _ON, c, sleep=sleep)
    await task.stop()  # not started: no-op
    task.start()
    first = task._task
    task.start()
    assert task._task is first and task.running
    await asyncio.sleep(0)
    await task.stop()
    assert not task.running and first is not None and first.cancelled()


async def test_disabled_schedule_never_starts() -> None:
    _, c = _counter()
    task = DrawingsPurgeTask(_Repo([]), _OFF, c)
    task.start()
    assert not task.running


def test_create_app_wires_task_and_metrics() -> None:
    s = Settings(
        retention_enabled=True,
        pg_owner_dsn=SecretStr("postgresql+asyncpg://cv_owner:x@localhost:5432/candleviewer"),
    )
    app = create_app(s)
    assert app.state.drawings_purge_task._enabled is True
    dm = app.state.drawings_metrics
    assert dm.purged is app.state.drawings_purge_task._purged
    assert create_app(Settings(retention_enabled=False)).state.drawings_purge_task._enabled is False
