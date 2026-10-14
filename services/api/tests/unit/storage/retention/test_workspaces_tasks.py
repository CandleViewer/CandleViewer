"""E15-T01 (S6): workspaces purge job, schedule entry, users gauge and wiring."""

from __future__ import annotations

import asyncio

import pytest
import structlog
from prometheus_client import generate_latest

from candleviewer.app import create_app
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.storage.repositories.workspaces_sqlalchemy import MAX_PURGE_BATCH
from candleviewer.storage.retention import policy
from candleviewer.storage.retention.schedule import RetentionSchedule
from candleviewer.storage.retention.workspaces_tasks import (
    MAX_BATCHES_PER_RUN,
    USER_BUCKETS,
    WorkspacesPurgeTask,
)

_ON = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"})
_OFF = RetentionSchedule.from_env({})


class _Repo:
    def __init__(
        self,
        results: list[tuple[int, int] | Exception],
        counts: dict[str, int] | Exception | None = None,
    ) -> None:
        self.results = results
        self.counts: dict[str, int] | Exception = counts or {}
        self.calls: list[tuple[int, int]] = []

    async def count_users_by_workspace_bucket(self) -> dict[str, int]:
        if isinstance(self.counts, Exception):
            raise self.counts
        return self.counts

    async def purge_deleted_counts(self, older_than_days: int, limit: int) -> tuple[int, int]:
        self.calls.append((older_than_days, limit))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _metrics() -> tuple[Metrics, BoundedMetric, BoundedMetric]:
    m = Metrics("demo")
    purged = m.counter("cv_workspaces_purged_total", "x", ("kind",), max_series=2)
    users = m.gauge("cv_workspace_users", "x", ("bucket",), max_series=5)
    return m, purged, users


def _snap(m: Metrics, name: str) -> dict[str, float]:
    text = generate_latest(m.registry).decode()
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith(name + "{"):
            k, _, v = line.rpartition(" ")
            out[k[len(name) + 1 : -1]] = float(v)
    return out


def test_schedule_on_and_off() -> None:
    assert _OFF.workspaces_jobs() == {}
    assert _ON.workspaces_jobs() == {"workspaces_purge": "0 3 * * *"}
    assert policy.WORKSPACES_SOFT_DELETE_DAYS == 90


async def test_run_once_drains_until_short_and_counts_per_kind() -> None:
    m, p, g = _metrics()
    full = MAX_PURGE_BATCH
    repo = _Repo([(full, 0), (0, full), (3, 4)])
    with structlog.testing.capture_logs() as logs:
        await WorkspacesPurgeTask(repo, _ON, p, g).run_once()
    assert repo.calls == [(90, full)] * 3
    assert _snap(m, "cv_workspaces_purged_total") == {
        'kind="layout"': float(full + 3),
        'kind="workspace"': float(full + 4),
    }
    assert [(e["layouts"], e["workspaces"]) for e in logs if e["event"] == "workspaces_purged"] == [
        (full, 0),
        (0, full),
        (3, 4),
    ]


async def test_run_is_capped_per_run() -> None:
    _, p, g = _metrics()
    repo = _Repo([(MAX_PURGE_BATCH, 0)] * (MAX_BATCHES_PER_RUN + 5))
    await WorkspacesPurgeTask(repo, _ON, p, g).run_once()
    assert len(repo.calls) == MAX_BATCHES_PER_RUN


async def test_users_gauge_covers_the_closed_set_and_zero_fills() -> None:
    m, p, g = _metrics()
    await WorkspacesPurgeTask(_Repo([(0, 0)], {"1": 4, "9-16": 1}), _ON, p, g).run_once()
    got = _snap(m, "cv_workspace_users")
    assert got == {f'bucket="{b}"': float({"1": 4, "9-16": 1}.get(b, 0)) for b in USER_BUCKETS}


async def test_unknown_bucket_from_the_store_is_never_exported() -> None:
    m, p, g = _metrics()
    await WorkspacesPurgeTask(_Repo([(0, 0)], {"99": 1}), _ON, p, g).run_once()
    assert all("99" not in k for k in _snap(m, "cv_workspace_users"))


async def test_purge_failure_keeps_rows_counted_and_still_samples_gauge() -> None:
    m, p, g = _metrics()
    repo = _Repo([(MAX_PURGE_BATCH, 0), RuntimeError("boom")], {"1": 2})
    with structlog.testing.capture_logs() as logs:
        await WorkspacesPurgeTask(repo, _ON, p, g).run_once()
    assert _snap(m, "cv_workspaces_purged_total") == {'kind="layout"': float(MAX_PURGE_BATCH)}
    assert _snap(m, "cv_workspace_users")['bucket="1"'] == 2
    assert "workspaces_purge_failed" in [e["event"] for e in logs]


async def test_gauge_failure_never_stops_the_purge() -> None:
    m, p, g = _metrics()
    repo = _Repo([(2, 1)], RuntimeError("down"))
    with structlog.testing.capture_logs() as logs:
        await WorkspacesPurgeTask(repo, _ON, p, g).run_once()
    assert _snap(m, "cv_workspaces_purged_total")['kind="workspace"'] == 1
    assert "workspace_users_sample_failed" in [e["event"] for e in logs]


async def test_logs_carry_counts_only_never_the_error_payload_or_ids() -> None:
    _, p, g = _metrics()
    with structlog.testing.capture_logs() as logs:
        await WorkspacesPurgeTask(_Repo([(1, 1)], {"1": 1}), _ON, p, g).run_once()
    assert {k for e in logs for k in e} <= {"event", "log_level", "layouts", "workspaces"}


class _Clock:
    """A fake sleep: records each interval and parks until released (no real waiting)."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self.gate = asyncio.Event()

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        await self.gate.wait()


async def test_start_runs_once_then_waits_the_interval_and_stop_cancels() -> None:
    _, p, g = _metrics()
    clock, repo = _Clock(), _Repo([(0, 0), (0, 0)])
    task = WorkspacesPurgeTask(repo, _ON, p, g, interval_s=7.0, sleep=clock.sleep)
    task.start()
    task.start()  # idempotent
    for _ in range(50):
        if clock.waits:
            break
        await asyncio.sleep(0)
    assert clock.waits == [7.0] and len(repo.calls) == 1 and task.running
    await task.stop()
    assert not task.running
    await task.stop()  # second stop is a no-op


async def test_cancellation_during_a_batch_propagates_and_is_not_swallowed() -> None:
    _, p, g = _metrics()

    class _Hang(_Repo):
        async def purge_deleted_counts(self, older_than_days: int, limit: int) -> tuple[int, int]:
            await asyncio.Event().wait()
            return (0, 0)

    task = WorkspacesPurgeTask(_Hang([]), _ON, p, g)
    task.start()
    await asyncio.sleep(0)
    await task.stop()  # cancel mid-purge: stop() returns cleanly, nothing left running
    assert not task.running


async def test_disabled_schedule_never_starts() -> None:
    _, p, g = _metrics()
    task = WorkspacesPurgeTask(_Repo([]), _OFF, p, g)
    task.start()
    assert not task.running


@pytest.mark.parametrize("enabled", [True, False])
def test_create_app_wires_the_task_and_metrics(enabled: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_RETENTION_ENABLED", "true" if enabled else "false")
    app = create_app()
    assert app.state.workspaces_metrics.users.name == "cv_workspace_users"
    # fake storage backend: no repository, so no purge task to start
    assert app.state.workspaces_purge_task is None
