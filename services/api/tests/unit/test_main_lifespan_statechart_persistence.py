"""E50-T63: the statechart persistence bundle (the `machine_events` sink and its pool) is up before
the modules and drained after them. `Supervisor.start_all` runs machines (replay revives sessions
through `Restorer.restore`) and `stop_all` persists them, so the bundle starts immediately before
`start_all` and is the last teardown step, after `stop_all`; if `start_all` raises, it is still
stopped, after the modules `start_all` stopped. A raising bundle stop is isolated like every other
step. The fake app is the stop-order suite's."""

from __future__ import annotations

from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.main import _lifespan
from tests.unit.test_main_lifespan_stop_order import _MODULES, _app, _Stops


class _Persistence:
    """The bundle's `start()`/`stop()`, recorded in the shared lists."""

    def __init__(self, stops: _Stops, *, fail_stop: bool = False) -> None:
        self.stops, self.fail_stop = stops, fail_stop

    async def start(self) -> None:
        self.stops.started.append("statechart_persistence")

    async def stop(self) -> None:
        self.stops.order.append("statechart_persistence")
        if self.fail_stop:
            raise RuntimeError("the pool would not close")


class _FailingModule:
    def __init__(self, stops: _Stops) -> None:
        self.stops = stops

    async def start(self, ctx: object) -> None:
        raise RuntimeError("a module refused to start")

    async def stop(self, grace_s: float) -> None:
        self.stops.order.append("module:replay")


def _with_bundle(stops: _Stops, **kw: Any) -> Any:
    app = _app(stops)
    app.state.statechart_persistence = _Persistence(stops, **kw)
    return app


async def test_the_bundle_starts_before_start_all_and_stops_after_stop_all() -> None:
    stops = _Stops()
    async with _lifespan(_with_bundle(stops)):
        assert stops.started[0] == "statechart_persistence"
        assert stops.started.count("statechart_persistence") == 1
    assert stops.order[-1] == "statechart_persistence"
    assert stops.order.count("statechart_persistence") == 1
    last_module = max(stops.order.index(f"module:{name}") for name in _MODULES)
    assert last_module < stops.order.index("statechart_persistence")


async def test_the_bundle_is_stopped_when_start_all_raises() -> None:
    stops = _Stops()
    app = _with_bundle(stops)
    app.state.app_context.replay = _FailingModule(stops)
    with pytest.raises(RuntimeError, match="refused to start"):
        async with _lifespan(app):
            pass
    assert stops.order[-1] == "statechart_persistence"  # after the modules start_all stopped
    assert "module:storage" in stops.order


async def test_a_raising_bundle_stop_is_isolated_and_logged() -> None:
    stops = _Stops()
    with capture_logs() as logs:
        async with _lifespan(_with_bundle(stops, fail_stop=True)):
            pass
    failed = [e for e in logs if e["event"] == "lifespan: teardown step failed"]
    assert [(e["step"], e["exc_type"]) for e in failed] == [
        ("statechart_persistence", "RuntimeError")
    ]
    assert {f"module:{name}" for name in _MODULES} <= set(stops.order)


async def test_no_bundle_means_no_step() -> None:
    stops = _Stops()
    async with _lifespan(_app(stops)):
        pass
    assert "statechart_persistence" not in stops.started + stops.order
