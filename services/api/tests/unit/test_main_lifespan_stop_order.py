"""#2484 gap 3 (E17-S01 lifespan, `23-ws-protocol.md` §9.4): on shutdown the client gateway
stops FIRST, so clients get `shutdown_notice`, the grace period and `bye` 1001 before any
module or runtime they read from goes away."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
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


class _LostJobs:
    """E42-T05: the lost-jobs count, loaded at boot and saved at a clean stop."""

    def __init__(self, stops: _Stops) -> None:
        self.stops = stops

    async def load(self) -> None:
        self.stops.started.append("admin_jobs_lost")

    async def save(self) -> None:
        self.stops.order.append("admin_jobs_lost")


class _FailingStart(_AsyncStart):
    async def start(self) -> None:
        raise RuntimeError("a boot step failed")


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
        "account_health",
        "rule_prune_task",
        "funding_refresh_task",
        "alert_purge_task",
        "alert_gauge_task",
        "log_level_overrides",
        "admin_jobs",
    ):
        setattr(app.state, attr, _Task(attr, stops))
    app.state.bars_runtime = _AsyncStart("bars_runtime", stops)
    app.state.feature_flags = _AsyncStart("feature_flags", stops)  # E42-T03: a maintenance poll
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
    assert stops.order.index("feature_flags") < stops.order.index("module:audit")  # its poll audits


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


async def test_lifespan_runs_account_health_between_the_modules_start_and_stop() -> None:
    """E27-T04 (#837): started after `start_all`, stopped (its calls drained) before `stop_all`."""
    stops = _Stops()
    async with _lifespan(_app(stops)):
        pass
    started = [stops.started.index(f"module:{name}") for name in _MODULES]
    stopped = [stops.order.index(f"module:{name}") for name in _MODULES]
    assert max(started) < stops.started.index("account_health")
    assert stops.order.index("account_health") < min(stopped)
    assert stops.started.count("account_health") == stops.order.count("account_health") == 1


async def test_lifespan_logs_at_boot_that_no_audit_verify_job_is_wired() -> None:
    """#2111: an audit chain that nothing verifies is visible in the boot log."""
    app = _app(_Stops())
    app.state.audit_verify_job = None
    with structlog.testing.capture_logs() as logs:
        async with _lifespan(app):
            pass
    assert {"event": "audit.verify_job_not_wired", "log_level": "warning"} in logs


async def test_lifespan_counts_the_lost_jobs_at_boot_and_saves_them_once_the_store_stopped() -> (
    None
):
    """E42-T05 (#966 Q10): the last clean stop's count is added before serving; this stop's is
    saved right after the job store stops, so it holds every job the restart loses."""
    stops = _Stops()
    app = _app(stops)
    app.state.admin_jobs_lost = _LostJobs(stops)
    async with _lifespan(app):
        assert stops.started.count("admin_jobs_lost") == 1
    assert stops.order.index("admin_jobs") + 1 == stops.order.index("admin_jobs_lost")


async def test_a_boot_that_fails_before_the_count_is_loaded_never_saves_over_it() -> None:
    """E42-T05: the count is bound only once the boot reaches it, so a boot step that raised
    earlier never writes this process's empty store over the last clean stop's count."""
    stops = _Stops()
    app = _app(stops)
    app.state.admin_jobs_lost = _LostJobs(stops)
    app.state.feature_flags = _FailingStart("feature_flags", stops)
    with pytest.raises(RuntimeError, match="boot step"):
        async with _lifespan(app):
            pass
    assert "admin_jobs" in stops.order and "admin_jobs_lost" not in stops.started + stops.order
