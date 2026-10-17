"""ASGI entrypoint (`uvicorn candleviewer.main:app`).

Wires the module supervisor into the FastAPI lifespan so `start_all()`/
`stop_all()` run around the server's lifetime (Sec.6.2). Not exercised by
unit tests (which call `create_app()` directly with fakes); covered by
E02-T08's compose smoke test.

E09-T04: the boot binding self-check (AC1/AC3) and the hourly re-check
scheduler (AC5) are started here, not in `create_app()`, so a unit test that
only calls `create_app()` (E02-T05 acceptance criterion 3: no I/O) never
enumerates real sockets — only the ASGI lifespan, which is this module's own
concern, does that.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI

from candleviewer.account_fixture_wiring import account_fixture_boot
from candleviewer.app import AppContext, Supervisor, audit_test_clock_boot, create_app
from candleviewer.observability.logging import configure_logging
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_server import MetricsRuntime
from candleviewer.settings import Settings

# E04-T01: logging must be configured before anything else logs a line, and
# exactly once per process (`configure_logging()`'s own docstring). Every
# worker entrypoint (ingestion/recorder/replay) added by later tickets must
# call this the same way, at the top of its own `main.py`.
_settings = Settings()
configure_logging(
    env=_settings.environment.value,
    level=_settings.log_level,
    fmt=_settings.log_format,
)


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx: AppContext = app.state.app_context
    supervisor = Supervisor(ctx)
    await supervisor.start_all()
    try:
        await audit_test_clock_boot(ctx)  # #2728: before serving; a failed write fails boot
        await account_fixture_boot(ctx)  # #2893 S8: a stored non-fixture key refuses boot
    except BaseException:
        await supervisor.stop_all(1.0)  # as `start_all` does: never leave modules running
        raise

    # Boot self-check (AC1 "safe binding passes", AC3 "public binding
    # degrades"): run once, synchronously, before serving so `net_binding_safe`
    # and the read-only gate reflect reality from the very first request.
    await ctx.mesh_self_check.run_once()
    if ctx.oms_read_only_gate.is_read_only:
        logger().error(
            "starting in read-only mode (%s): %s",
            ctx.oms_read_only_gate.reason_code,
            ctx.oms_read_only_gate.reason_text,
        )
    else:
        logger().info("boot binding self-check passed; all listening sockets are mesh-only")

    # Hourly re-check (AC5 "drift after resume is caught").
    ctx.mesh_self_check.start()
    scrub_task = getattr(app.state, "scrub_task", None)
    if scrub_task is not None:
        scrub_task.start()
    audit_verify = getattr(app.state, "audit_verify_job", None)
    if audit_verify is not None:  # #2111: after `start_all`, so the audit writer is up
        audit_verify.start()
    else:  # #2111: no verify runner is wired (#2966), so nothing checks the audit chain
        logger().warning("audit.verify_job_not_wired")
    disk_budget = getattr(app.state, "disk_budget", None)
    if disk_budget is not None:  # E16-T07: one supervised sampling task
        disk_budget.start()
    rule_prune = getattr(app.state, "rule_prune_task", None)
    if rule_prune is not None:
        rule_prune.start()
    funding_task = getattr(app.state, "funding_refresh_task", None)
    if funding_task is not None:
        funding_task.start()
    bars_runtime = getattr(app.state, "bars_runtime", None)
    if bars_runtime is not None:
        await bars_runtime.start()
    kline_refresh = getattr(app.state, "kline_boundary_refresh", None)
    if kline_refresh is not None:  # #2060: initial load, then periodic (rules are editable)
        await kline_refresh.load_now()
        kline_refresh.start()
    alert_tasks = [
        t
        for t in (
            getattr(app.state, "alert_purge_task", None),
            getattr(app.state, "alert_gauge_task", None),
            getattr(app.state, "drawings_purge_task", None),
            getattr(app.state, "workspaces_purge_task", None),
        )
        if t is not None
    ]
    for t in alert_tasks:
        t.start()
    overrides = getattr(app.state, "log_level_overrides", None)
    if overrides is not None:
        overrides.start()
    health_registry = getattr(app.state, "health_registry", None)
    if health_registry is not None:
        health_registry.start()
    metrics_runtime: MetricsRuntime | None = None
    if ctx.settings.metrics_enabled:
        # E04-T06: create_app() owns the single facade (telemetry series hang
        # off it); fall back for apps built without one.
        facade = getattr(app.state, "metrics_facade", None)
        if facade is None:
            facade = Metrics(
                ctx.settings.environment.value,
                registry=ctx.metrics,
                process_collectors=True,
            )
        facade.add_process_collectors()
        metrics_runtime = MetricsRuntime(facade, ctx.settings.metrics_bind)
        metrics_runtime.start()
    ws_runtime = getattr(app.state, "ws_runtime", None)
    if ws_runtime is not None:
        ws_runtime.start()
    try:
        yield
    finally:
        # §9.4: the client gateway stops FIRST. Under `candleviewer.server` the notice, grace and
        # bye already ran before uvicorn's shutdown (#2546); this call then stops the sweeper.
        if ws_runtime is not None:
            await ws_runtime.stop()
        if metrics_runtime is not None:
            await metrics_runtime.stop()
        if health_registry is not None:
            await health_registry.stop()
        if disk_budget is not None:  # before the PG engines its repository uses
            await disk_budget.stop()
        health_pg = getattr(app.state, "health_pg", None)
        if health_pg is not None:
            await health_pg.dispose()
        kline_pg = getattr(app.state, "kline_boundary_pg", None)
        if kline_pg is not None:
            await kline_pg.dispose()
        if overrides is not None:
            await overrides.stop()
        if kline_refresh is not None:
            await kline_refresh.stop()
        if rule_prune is not None:
            await rule_prune.stop()
        if funding_task is not None:
            await funding_task.stop()
        for t in alert_tasks:
            await t.stop()
        if scrub_task is not None:
            await scrub_task.stop()
        if audit_verify is not None:  # #2111: a run writes through the audit writer (stop_all)
            await audit_verify.stop()
        admin_jobs = getattr(app.state, "admin_jobs", None)
        if admin_jobs is not None:
            await admin_jobs.stop()  # E16-T05: tracked compaction tasks never outlive the app
        if bars_runtime is not None:
            await bars_runtime.stop()  # set before writer; both before storage stops
        await ctx.mesh_self_check.stop()
        csrf_audits = getattr(app.state, "csrf_refusal_audits", None)
        if csrf_audits is not None:
            # #2090: let in-flight CSRF-refusal audits land (bounded) before audit stops.
            left = await csrf_audits.drain()
            if left:
                logger().warning("shutdown with %d CSRF-refusal audit(s) still in flight", left)
        await supervisor.stop_all()


app = create_app()
app.router.lifespan_context = _lifespan
