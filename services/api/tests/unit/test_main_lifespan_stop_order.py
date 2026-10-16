"""#2484 gap 3 (E17-S01 lifespan, `23-ws-protocol.md` §9.4): on shutdown the client gateway
stops FIRST, so clients get `shutdown_notice`, the grace period and `bye` 1001 before any
module or runtime they read from goes away."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI

from candleviewer.main import _lifespan

_MODULES = (
    "storage",
    "secrets",
    "auth",
    "admin",
    "bus",
    "exchange_base",
    "exchange_bybit",
    "ingestion",
    "book",
    "bars",
    "orderflow",
    "recorder",
    "accounts",
    "risk",
    "audit",
    "oms",
    "paper",
    "rules",
    "alerts",
    "journal",
    "replay",
    "observability",
    "ws",
)


class _Stops:
    """Every fake appends its name here when it stops."""

    def __init__(self) -> None:
        self.order: list[str] = []


class _Module:
    def __init__(self, name: str, stops: _Stops) -> None:
        self.name, self.stops = name, stops

    async def start(self, ctx: object) -> None:
        return None

    async def stop(self, grace_s: float) -> None:
        self.stops.order.append(f"module:{self.name}")


class _Task:
    """`start()` sync, `stop()` async: the ws runtime and the periodic tasks."""

    def __init__(self, name: str, stops: _Stops) -> None:
        self.name, self.stops = name, stops

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stops.order.append(self.name)


class _AsyncStart:
    """`bars_runtime`: its `start()` is awaited."""

    def __init__(self, name: str, stops: _Stops) -> None:
        self.name, self.stops = name, stops

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stops.order.append(self.name)


class _Kline(_Task):
    async def load_now(self) -> None:
        return None


class _Pool:
    def __init__(self, name: str, stops: _Stops) -> None:
        self.name, self.stops = name, stops

    async def dispose(self) -> None:
        self.stops.order.append(self.name)


class _Audits:
    def __init__(self, stops: _Stops) -> None:
        self.stops = stops

    async def drain(self) -> int:
        self.stops.order.append("csrf_refusal_audits")
        return 0


class _SelfCheck(_Task):
    async def run_once(self) -> None:
        return None


def _app(stops: _Stops) -> FastAPI:
    app = FastAPI()
    app.state.app_context = SimpleNamespace(
        settings=SimpleNamespace(metrics_enabled=False, test_clock=False),
        mesh_self_check=_SelfCheck("mesh_self_check", stops),
        oms_read_only_gate=SimpleNamespace(is_read_only=False, reason_code=None, reason_text=None),
        **{name: _Module(name, stops) for name in _MODULES},
    )
    for attr in (
        "ws_runtime",
        "health_registry",
        "scrub_task",
        "rule_prune_task",
        "funding_refresh_task",
        "alert_purge_task",
        "alert_gauge_task",
        "log_level_overrides",
        "admin_jobs",
    ):
        setattr(app.state, attr, _Task(attr, stops))
    app.state.bars_runtime = _AsyncStart("bars_runtime", stops)
    app.state.kline_boundary_refresh = _Kline("kline_boundary_refresh", stops)
    app.state.health_pg = _Pool("health_pg", stops)
    app.state.kline_boundary_pg = _Pool("kline_boundary_pg", stops)
    app.state.csrf_refusal_audits = _Audits(stops)
    return app


async def test_lifespan_stops_the_ws_gateway_before_anything_else() -> None:
    stops = _Stops()
    async with _lifespan(_app(stops)):
        assert stops.order == []
    assert stops.order[0] == "ws_runtime"
    assert stops.order.count("ws_runtime") == 1
    # Everything else did stop, after it: every runtime, task, pool and supervised module.
    assert {"health_registry", "bars_runtime", "health_pg", "mesh_self_check"} <= set(stops.order)
    assert {f"module:{name}" for name in _MODULES} <= set(stops.order)
