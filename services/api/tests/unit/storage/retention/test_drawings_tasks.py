"""E14-T01 (C4): drawings purge job, schedule entry and wiring."""

from __future__ import annotations

import asyncio

import structlog
from prometheus_client import generate_latest
from pydantic import SecretStr

from candleviewer.app import create_app
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.settings import Settings
from candleviewer.storage.repositories.drawings_sqlalchemy import MAX_PURGE_BATCH
from candleviewer.storage.retention import policy
from candleviewer.storage.retention.drawings_tasks import MAX_BATCHES_PER_RUN, DrawingsPurgeTask
from candleviewer.storage.retention.schedule import RetentionSchedule

_ON = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"})
_OFF = RetentionSchedule.from_env({})


TOOLS3 = ("trendline", "rectangle", "text")


class _Repo:
    def __init__(
        self, results: list[int | Exception], counts: dict[str, int] | Exception | None = None
    ) -> None:
        self.results = results
        self.counts: dict[str, int] | Exception = counts or {}
        self.calls: list[tuple[int, int]] = []

    async def count_live_by_tool(self) -> dict[str, int]:
        if isinstance(self.counts, Exception):
            raise self.counts
        return self.counts

    async def purge_deleted(self, older_than_days: int, limit: int) -> int:
        self.calls.append((older_than_days, limit))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _counter() -> tuple[Metrics, BoundedMetric, BoundedMetric]:
    m = Metrics("demo")
    return m, m.counter("cv_drawings_purged_total", "x"), _gauge(m)


def _gauge(m: Metrics) -> BoundedMetric:
    return m.gauge("cv_drawings_rows", "x", ("tool",), max_series=25)


def _value(m: Metrics) -> float:
    return float(m.snapshot(["cv_drawings_purged"]).get("cv_drawings_purged_total", 0))


def test_schedule_on_and_off() -> None:
    assert _OFF.drawings_jobs() == {}
    assert _ON.drawings_jobs() == {"drawings_purge": "0 3 * * *"}
    assert policy.DRAWINGS_SOFT_DELETE_DAYS == 90


async def test_run_once_loops_until_short_batch_and_counts_total() -> None:
    m, c, g = _counter()
    repo = _Repo([MAX_PURGE_BATCH, MAX_PURGE_BATCH, 7])
    task = DrawingsPurgeTask(repo, _ON, c, g, TOOLS3)
    with structlog.testing.capture_logs() as logs:
        await task.run_once()
    assert repo.calls == [(90, MAX_PURGE_BATCH)] * 3
    assert _value(m) == 2 * MAX_PURGE_BATCH + 7
    assert [e["deleted"] for e in logs] == [MAX_PURGE_BATCH, MAX_PURGE_BATCH, 7]


async def test_run_once_zero_rows_logs_and_leaves_counter() -> None:
    m, c, g = _counter()
    task = DrawingsPurgeTask(_Repo([0]), _ON, c, g, TOOLS3)
    with structlog.testing.capture_logs() as logs:
        await task.run_once()
    assert _value(m) == 0
    assert [e["event"] for e in logs] == ["drawings_purged"]


async def test_later_batch_failure_keeps_count_of_purged_rows() -> None:
    m, c, g = _counter()
    repo = _Repo([MAX_PURGE_BATCH, RuntimeError("boom")])
    task = DrawingsPurgeTask(repo, _ON, c, g, TOOLS3)
    with structlog.testing.capture_logs() as logs:
        await task.run_once()
    assert _value(m) == MAX_PURGE_BATCH
    assert [e["event"] for e in logs] == ["drawings_purged", "drawings_purge_failed"]


async def test_run_is_bounded_by_max_batches() -> None:
    m, c, g = _counter()
    repo = _Repo([MAX_PURGE_BATCH] * (MAX_BATCHES_PER_RUN + 5))
    await DrawingsPurgeTask(repo, _ON, c, g, TOOLS3).run_once()
    assert len(repo.calls) == MAX_BATCHES_PER_RUN
    assert _value(m) == MAX_BATCHES_PER_RUN * MAX_PURGE_BATCH


async def test_rows_gauge_is_set_per_tool_and_zero_filled() -> None:
    m, c, g = _counter()
    task = DrawingsPurgeTask(_Repo([0], {"trendline": 4, "text": 1}), _ON, c, g, TOOLS3)
    await task.run_once()
    out = generate_latest(m.registry).decode()
    for tool, n in (("trendline", 4), ("rectangle", 0), ("text", 1)):
        assert f'cv_drawings_rows{{env="demo",tool="{tool}"}} {float(n)}' in out


async def test_rows_gauge_resets_to_zero_when_a_tool_disappears() -> None:
    m, c, g = _counter()
    repo = _Repo([0, 0], {"trendline": 4})
    task = DrawingsPurgeTask(repo, _ON, c, g, TOOLS3)
    await task.run_once()
    repo.counts = {}
    await task.run_once()
    assert (
        'cv_drawings_rows{env="demo",tool="trendline"} 0.0' in generate_latest(m.registry).decode()
    )


async def test_count_failure_never_stops_the_purge() -> None:
    m, c, g = _counter()
    repo = _Repo([MAX_PURGE_BATCH, 2], RuntimeError("count down"))
    task = DrawingsPurgeTask(repo, _ON, c, g, TOOLS3)
    with structlog.testing.capture_logs() as logs:
        await task.run_once()
    assert _value(m) == MAX_PURGE_BATCH + 2  # the purge ran fully before the sample
    assert [e["event"] for e in logs][-1] == "drawings_rows_sample_failed"


async def test_purge_failure_still_samples_rows() -> None:
    m, c, g = _counter()
    task = DrawingsPurgeTask(_Repo([RuntimeError("x")], {"text": 3}), _ON, c, g, TOOLS3)
    await task.run_once()
    assert 'cv_drawings_rows{env="demo",tool="text"} 3.0' in generate_latest(m.registry).decode()


async def test_failure_is_logged_and_loop_survives() -> None:
    _, c, g = _counter()
    repo = _Repo([RuntimeError("db down"), 3])
    ticks = 0
    done = asyncio.Event()

    async def sleep(_: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            done.set()
        await asyncio.sleep(0)

    task = DrawingsPurgeTask(repo, _ON, c, g, TOOLS3, sleep=sleep)
    with structlog.testing.capture_logs() as logs:
        task.start()
        await asyncio.wait_for(done.wait(), 2)
        await task.stop()
    events = [e["event"] for e in logs]
    assert events[:2] == ["drawings_purge_failed", "drawings_purged"]


async def test_start_is_idempotent_and_stop_cancels() -> None:
    _, c, g = _counter()
    gate = asyncio.Event()

    async def sleep(_: float) -> None:
        await gate.wait()

    task = DrawingsPurgeTask(_Repo([0] * 5), _ON, c, g, TOOLS3, sleep=sleep)
    await task.stop()  # not started: no-op
    task.start()
    task.start()
    task.start()
    assert task.running
    await asyncio.sleep(0)
    await task.stop()
    assert not task.running


async def test_disabled_schedule_never_starts() -> None:
    _, c, g = _counter()
    task = DrawingsPurgeTask(_Repo([]), _OFF, c, g, TOOLS3)
    task.start()
    assert not task.running


def test_create_app_wires_task_and_metrics() -> None:
    s = Settings(
        retention_enabled=True,
        pg_owner_dsn=SecretStr("postgresql+asyncpg://cv_owner:x@localhost:5432/candleviewer"),
    )
    app = create_app(s)
    assert app.state.drawings_purge_task is not None
    assert app.state.drawings_metrics.purged is not None
    # Disabled schedule: start() is a no-op.
    off = create_app(Settings(retention_enabled=False)).state.drawings_purge_task
    off.start()
    assert not off.running
