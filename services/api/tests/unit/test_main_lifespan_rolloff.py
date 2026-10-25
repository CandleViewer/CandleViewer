"""E16-F01 S4c: the nightly roll-off runs under the lifespan, behind `retention_enabled`
(C-4.13), tracked and stopped before the Postgres engine its run lock holds (C-2.18)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer import main
from candleviewer.main import _lifespan
from tests.unit.test_main_lifespan_stop_order import _app, _Stops


class _Job:
    def __init__(self, stops: _Stops) -> None:
        self.stops = stops

    async def run(self) -> None:
        self.stops.started.append("rolloff_run")


class _FakeTask:
    def __init__(self, job: _Job) -> None:
        self.job = job

    def start(self) -> None:
        self.job.stops.started.append("rolloff_task")

    async def stop(self) -> None:
        self.job.stops.order.append("rolloff_task")


def _wired(stops: _Stops, *, enabled: bool) -> Any:
    app = _app(stops)
    app.state.rolloff_job = _Job(stops)
    app.state.app_context.settings = SimpleNamespace(
        metrics_enabled=False, test_clock=False, account_fixture=None, retention_enabled=enabled
    )
    return app


async def test_lifespan_starts_the_rolloff_task_when_retention_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "RollOffTask", _FakeTask)
    stops = _Stops()
    async with _lifespan(_wired(stops, enabled=True)):
        assert "rolloff_task" in stops.started


async def test_lifespan_does_not_start_the_rolloff_task_when_retention_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "RollOffTask", _FakeTask)
    stops = _Stops()
    async with _lifespan(_wired(stops, enabled=False)):
        pass
    assert "rolloff_task" not in stops.started + stops.order


async def test_lifespan_stops_the_rolloff_task_before_the_postgres_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "RollOffTask", _FakeTask)
    stops = _Stops()
    async with _lifespan(_wired(stops, enabled=True)):
        pass
    assert stops.order.count("rolloff_task") == 1
    assert stops.order.index("rolloff_task") < stops.order.index("kline_boundary_pg")
    assert stops.order.index("rolloff_task") < stops.order.index("health_pg")
