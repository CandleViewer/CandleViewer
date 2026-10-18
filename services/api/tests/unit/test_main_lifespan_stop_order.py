"""#2484 gap 3 (E17-S01 lifespan, `23-ws-protocol.md` §9.4): on shutdown the client gateway
stops FIRST, so clients get `shutdown_notice`, the grace period and `bye` 1001 before any
module or runtime they read from goes away."""

from __future__ import annotations

from types import SimpleNamespace

import structlog
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
    """Every fake appends its name to `order` when it stops, and to `started` when it starts."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.started: list[str] = []


class _Module:
    def __init__(self, name: str, stops: _Stops) -> None:
        self.name, self.stops = name, stops

    async def start(self, ctx: object) -> None:
        self.stops.started.append(f"module:{self.name}")

    async def stop(self, grace_s: float) -> None:
        self.stops.order.append(f"module:{self.name}")


class _Task:
    """`start()` sync, `stop()` async: the ws runtime and the periodic tasks."""

    def __init__(self, name: str, stops: _Stops) -> None:
        self.name, self.stops = name, stops

    def start(self) -> None:
        self.stops.started.append(self.name)

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


class _Cascades(_Audits):
    async def drain(self) -> int:
        self.stops.order.append("user_disable")
        return 0


class _SelfCheck(_Task):
    async def run_once(self) -> None:
        return None


def _app(stops: _Stops) -> FastAPI:
    app = FastAPI()
    app.state.app_context = SimpleNamespace(
        settings=SimpleNamespace(metrics_enabled=False, test_clock=False, account_fixture=None),
        mesh_self_check=_SelfCheck("mesh_self_check", stops),
        oms_read_only_gate=SimpleNamespace(is_read_only=False, reason_code=None, reason_text=None),
        **{name: _Module(name, stops) for name in _MODULES},
    )
    for attr in (
        "ws_runtime",
        "health_registry",
        "scrub_task",
        "audit_verify_job",
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
    app.state.user_disable = _Cascades(stops)
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


async def test_lifespan_drains_the_user_disable_cascades_before_the_modules_they_use_stop() -> None:
    """E42-T04 S6 (#965): a cascade's steps use the sessions, audit and rules `stop_all` stops."""
    stops = _Stops()
    async with _lifespan(_app(stops)):
        pass
    used = (stops.order.index(f"module:{name}") for name in ("auth", "audit", "rules"))
    assert 0 < stops.order.index("user_disable") < min(used)  # after the gateway, before them


async def test_lifespan_starts_the_audit_verify_job_once_after_the_audit_module() -> None:
    """#2111: a run writes its records through the audit writer, which `start_all` brings up."""
    stops = _Stops()
    async with _lifespan(_app(stops)):
        assert stops.started.index("module:audit") < stops.started.index("audit_verify_job")
        assert stops.started.count("audit_verify_job") == 1


async def test_lifespan_stops_the_audit_verify_job_before_the_audit_module() -> None:
    """#2111: a verify run writes its records through the audit writer, so it ends first."""
    stops = _Stops()
    with structlog.testing.capture_logs() as logs:
        async with _lifespan(_app(stops)):
            pass
    assert stops.order.index("audit_verify_job") < stops.order.index("module:audit")
    assert "audit.verify_job_not_wired" not in [e["event"] for e in logs]  # a job is wired


async def test_lifespan_logs_at_boot_that_no_audit_verify_job_is_wired() -> None:
    """#2111: an audit chain that nothing verifies is visible in the boot log."""
    app = _app(_Stops())
    app.state.audit_verify_job = None
    with structlog.testing.capture_logs() as logs:
        async with _lifespan(app):
            pass
    assert {"event": "audit.verify_job_not_wired", "log_level": "warning"} in logs
