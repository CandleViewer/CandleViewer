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

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI

from candleviewer.account_fixture_wiring import account_fixture_guard, account_fixture_record
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


class _Teardown:
    """Runs the lifespan teardown's steps one by one, each isolated (#3403): a step that raises
    never keeps a later one, or `Supervisor.stop_all` and with it `secrets.stop()` zeroing the
    KEK (C-2.7, C-12.2), from running. A failed step is logged with its name and exception type.
    An `Exception` goes no further. Anything else, a cancellation, `KeyboardInterrupt` or
    `SystemExit` included, is never swallowed: the first one is held, before its log line is
    written, and re-raised, unchanged, once `stop_all` has run, even over whatever else left the
    steps meanwhile (that log line's own error, say), as `Supervisor.start_all` re-raises only
    after its stops. Only a `GeneratorExit` leaves at once: the coroutine is being closed, so the
    later steps are skipped and only the `finally` still tries `stop_all`.

    A boot step that raises after `start_all` reaches this teardown as well (#3446). Its exception
    leaves unchanged once `stop_all` has run, unless a step held one: the held one then wins, and
    the boot's exception survives as its `__context__`.

    No step gets a new time bound. The two that can run long, `BarsRuntime` and the metrics
    listener's drain, are #2878's to bound together with the stop budget (see
    `Settings._refuse_unfittable_stop_budget`); one bound on every step here would cut the WS
    grace and the bars drain short. The others bound themselves, cancel their own task or are
    short closes; one that hangs still holds `stop_all` until the SIGKILL (WS-D17)."""

    def __init__(self) -> None:
        self._held: BaseException | None = None

    async def run[T](self, step: str, stop: Callable[[], Awaitable[T]]) -> T | None:
        """Await one step. A failure is logged and returns None; the first one that is not an
        `Exception` is held as well."""
        try:
            return await stop()
        except GeneratorExit:
            raise
        except BaseException as exc:  # an `Exception` ends here; anything else is held as well
            if self._held is None and not isinstance(exc, Exception):
                self._held = exc  # first: a log line that raises must not lose it
            logger().exception(
                "lifespan: teardown step failed", step=step, exc_type=type(exc).__name__
            )
            return None

    def raise_held(self) -> None:
        """Re-raise the first held exception, if any: call it once `stop_all` has run."""
        held, self._held = self._held, None
        if held is not None:
            try:
                raise held
            finally:
                del held  # its traceback holds this frame: no reference cycle back to it


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx: AppContext = app.state.app_context
    fixture_boot = await account_fixture_guard(ctx.settings)  # #2893 S8: before any module starts
    supervisor = Supervisor(ctx)
    await supervisor.start_all()
    # #3446: the boot after `start_all` runs in the `try` whose `finally` is the teardown, so what a
    # boot step raises leaves the lifespan only once what has started is stopped, as at shutdown.
    # Each step is bound as the boot reaches it, before its start: one that raised half-way is
    # stopped, and one never reached stays None, which the teardown skips; `WsRuntime.stop()`, for
    # one, would otherwise wait out its grace for a server that never served.
    feature_flags = scrub_task = audit_verify = disk_budget = rule_prune = funding_task = None
    bars_runtime = kline_refresh = audit_flush = overrides = health_registry = None
    account_health = ws_runtime = lost_jobs = None
    alert_tasks: list[Any] = []
    metrics_runtime: MetricsRuntime | None = None
    try:
        await audit_test_clock_boot(ctx)  # #2728: before serving; a failed write fails boot
        await account_fixture_record(fixture_boot, ctx.audit)  # #2893 S8: its record, likewise
        feature_flags = getattr(app.state, "feature_flags", None)
        if feature_flags is not None:  # E42-T03: a bad `flags.read_budget_ms` refuses boot
            await feature_flags.start()

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
        alert_candidates = (  # bound by name: E49-K01-F4's guard reads only assignments
            getattr(app.state, "alert_purge_task", None),
            getattr(app.state, "alert_gauge_task", None),
            getattr(app.state, "drawings_purge_task", None),
            getattr(app.state, "workspaces_purge_task", None),
            getattr(app.state, "incidents_purge_task", None),  # E42-T05
        )
        for t in alert_candidates:
            if t is not None:
                alert_tasks.append(t)
                t.start()
        audit_flush = getattr(app.state, "audit_budget_flush", None)
        if audit_flush is not None:
            audit_flush.start()
        overrides = getattr(app.state, "log_level_overrides", None)
        if overrides is not None:
            overrides.start()
        health_registry = getattr(app.state, "health_registry", None)
        if health_registry is not None:
            health_registry.start()
        account_health = getattr(app.state, "account_health", None)
        if account_health is not None:  # E27-T04 (#837): once `start_all` has brought modules up
            account_health.start()
        lost_jobs = getattr(app.state, "admin_jobs_lost", None)
        if lost_jobs is not None:  # E42-T05 (#966 Q10): the jobs the last clean stop left behind
            await lost_jobs.load()
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
        yield
    finally:
        # #3403: each step below is isolated (`_Teardown.run`), so whatever one raises, the later
        # ones still run; `stop_all`, and with it the KEK zeroing, runs in a `finally`, so not
        # even an error outside a step's isolation can skip it, and the held exception leaves
        # only after it.
        teardown = _Teardown()
        try:
            # §9.4: the client gateway stops FIRST. Under `candleviewer.server` the notice, grace
            # and bye already ran before uvicorn's shutdown (#2546); this call then stops the
            # sweeper.
            if ws_runtime is not None:
                await teardown.run("ws_runtime", ws_runtime.stop)
            user_disable = getattr(app.state, "user_disable", None)
            if user_disable is not None:  # E42-T04 S6: steps in flight use what `stop_all` stops
                await teardown.run("user_disable", user_disable.drain)  # each ends by its deadline
            key_imports = getattr(app.state, "key_imports", None)
            if key_imports is not None:  # #836: an import in flight writes through audit and M2
                # bounded; then it releases the import's Postgres pool
                await teardown.run("key_imports", key_imports.drain)
            if feature_flags is not None:  # its maintenance poll, before the audit writer stops
                await teardown.run("feature_flags", feature_flags.stop)
            if metrics_runtime is not None:
                await teardown.run("metrics_runtime", metrics_runtime.stop)
            if health_registry is not None:
                await teardown.run("health_registry", health_registry.stop)
            if disk_budget is not None:  # before the PG engines its repository uses
                await teardown.run("disk_budget", disk_budget.stop)
            health_pg = getattr(app.state, "health_pg", None)
            if health_pg is not None:
                await teardown.run("health_pg", health_pg.dispose)
            kline_pg = getattr(app.state, "kline_boundary_pg", None)
            if kline_pg is not None:
                await teardown.run("kline_boundary_pg", kline_pg.dispose)
            if overrides is not None:
                await teardown.run("log_level_overrides", overrides.stop)
            if kline_refresh is not None:
                await teardown.run("kline_boundary_refresh", kline_refresh.stop)
            if rule_prune is not None:
                await teardown.run("rule_prune_task", rule_prune.stop)
            if funding_task is not None:
                await teardown.run("funding_refresh_task", funding_task.stop)
            for t in alert_tasks:  # each is its own class, so its class name names the step
                await teardown.run(type(t).__name__, t.stop)
            if scrub_task is not None:
                await teardown.run("scrub_task", scrub_task.stop)
            if audit_verify is not None:  # #2111: a run writes through the audit writer (stop_all)
                await teardown.run("audit_verify_job", audit_verify.stop)
            admin_jobs = getattr(app.state, "admin_jobs", None)
            if admin_jobs is not None:  # E16-T05: tracked compaction tasks never outlive the app
                await teardown.run("admin_jobs", admin_jobs.stop)
                if lost_jobs is not None:  # E42-T05: what the stopped store held, for next boot
                    await teardown.run("admin_jobs_lost", lost_jobs.save)
            if bars_runtime is not None:  # set before writer; both before storage stops
                await teardown.run("bars_runtime", bars_runtime.stop)
            await teardown.run("mesh_self_check", ctx.mesh_self_check.stop)
            access = getattr(app.state, "account_access_service", None)
            if access is not None:
                # #2648: wait (bounded) for grant pushes before audit stops: they write WS
                # audit rows
                await teardown.run("account_access_service", access.drain)
            csrf_audits = getattr(app.state, "csrf_refusal_audits", None)
            if csrf_audits is not None:
                # #2090: let in-flight CSRF-refusal audits land (bounded) before audit stops.
                left = await teardown.run("csrf_refusal_audits", csrf_audits.drain)
                if left:
                    logger().warning("shutdown with %d CSRF-refusal audit(s) still in flight", left)
            if audit_flush is not None:
                # Budgeted audit counts are written (bounded) before the audit module stops.
                await teardown.run("audit_budget_flush", audit_flush.stop)
            if account_health is not None:  # its hook calls drain before `stop_all` stops modules
                await teardown.run("account_health", account_health.stop)
        finally:
            await teardown.run("supervisor.stop_all", supervisor.stop_all)
            teardown.raise_held()


app = create_app()
app.router.lifespan_context = _lifespan
