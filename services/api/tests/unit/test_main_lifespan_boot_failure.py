"""#3446: a boot step that fails after `Supervisor.start_all` never leaves the modules running:
the lifespan stops what has started, `secrets` and with it the KEK zeroing included (C-2.7,
C-12.2), before the exception leaves it.

These tests run the real `_lifespan` over #3403's fakes (`test_main_lifespan_teardown_isolation`):
one for each step the lifespan starts or stops, and one for each supervised module, each recording
its stop. One call of the boot is made to raise. The lifespan then runs the teardown it runs at
shutdown, with the same order and bounds: the steps the boot had reached, the failing one included
(its start may have got half-way), stop in the teardown's order, with the steps the teardown always
runs; a step the boot never reached does not stop, so `WsRuntime.stop()` never waits out its grace
for a server that never served; then `stop_all`, with the teardown's grace, stops every module in
reverse. The exception leaves unchanged. Nothing sleeps or reads a clock: no fake suspends.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from candleviewer import main
from candleviewer.app import Supervisor
from candleviewer.settings import TEARDOWN_BUDGET_S
from tests.unit.test_main_lifespan_teardown_isolation import (
    _app,
    _failed_steps,
    _run,
    _Step,
    _unfailed,
)

#: Every call the boot makes after `start_all`, in the lifespan's order: `<object>.<method>`, the
#: object a step or the metrics facade, or the name of one of `main`'s own (the two boot records,
#: the metrics runtime's class).
_BOOT = (
    "audit_test_clock_boot",
    "account_fixture_record",
    "feature_flags.start",
    "mesh_self_check.run_once",
    "mesh_self_check.start",
    "scrub_task.start",
    "audit_verify_job.start",
    "disk_budget.start",
    "rule_prune_task.start",
    "funding_refresh_task.start",
    "bars_runtime.start",
    "kline_boundary_refresh.load_now",
    "kline_boundary_refresh.start",
    "alert_purge_task.start",
    "alert_gauge_task.start",
    "drawings_purge_task.start",
    "workspaces_purge_task.start",
    "incidents_purge_task.start",
    "audit_budget_flush.start",
    "log_level_overrides.start",
    "health_registry.start",
    "account_health.start",
    "metrics_facade.add_process_collectors",
    "MetricsRuntime",
    "metrics_runtime.start",
    "ws_runtime.start",
)
#: The teardown steps the lifespan never starts: it stops them however far the boot got.
_ALWAYS = frozenset(
    {
        "user_disable",
        "health_pg",
        "kline_boundary_pg",
        "admin_jobs",
        "mesh_self_check",
        "account_access_service",
        "csrf_refusal_audits",
    }
)


def _raiser(original: Callable[..., object], exc: BaseException) -> Callable[..., object]:
    """A stand-in for `original` that raises `exc`: awaited if `original` is."""
    if inspect.iscoroutinefunction(original):

        async def _raise_async(*args: object) -> None:
            raise exc

        return _raise_async

    def _raise(*args: object) -> None:
        raise exc

    return _raise


def _fail(
    call: str,
    exc: BaseException,
    app: FastAPI,
    steps: dict[str, _Step],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make `call`, one of `_BOOT`, raise `exc`."""
    name, _, method = call.partition(".")
    if not method:
        monkeypatch.setattr(main, name, _raiser(getattr(main, name), exc))
        return
    target: Any = steps[name] if name in steps else getattr(app.state, name)
    setattr(target, method, _raiser(getattr(target, method), exc))


async def _stopped_after(call: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The stops of a boot that failed at `call`: those of an unfailed teardown, in its order, of
    every step the boot reached up to `call`, of every step the teardown always runs, and of every
    module."""
    reached = {c.partition(".")[0] for c in _BOOT[: _BOOT.index(call) + 1]}
    return [
        r
        for r in await _unfailed(monkeypatch)
        if r.startswith("module:") or r in reached or r in _ALWAYS
    ]


def _recording(graces: list[float]) -> type[Supervisor]:
    """The real supervisor, whose `stop_all` records the grace it was given."""

    class _Supervisor(Supervisor):
        async def stop_all(self, grace_s: float = TEARDOWN_BUDGET_S) -> None:
            graces.append(grace_s)
            await super().stop_all(grace_s)

    return _Supervisor


@pytest.mark.parametrize("call", _BOOT)
async def test_lifespan_boot_failing_after_start_all_stops_what_started_then_reraises(
    monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    """The error leaves the lifespan, the same object, once the teardown has stopped what the boot
    had started and `stop_all`, given the teardown's grace, every module, `secrets` included. A
    boot step outside the guard, or a guard that stops only the modules, or with a grace of its
    own, fails it; so does one that stops a step the boot never reached."""
    stopped = await _stopped_after(call, monkeypatch)
    ran: list[str] = []
    graces: list[float] = []
    app, steps = _app(ran, monkeypatch)
    monkeypatch.setattr(main, "Supervisor", _recording(graces))
    exc = RuntimeError(f"{call} failed")
    _fail(call, exc, app, steps, monkeypatch)
    with pytest.raises(RuntimeError) as raised:
        await _run(app)
    assert raised.value is exc
    assert ran == stopped
    assert graces == [TEARDOWN_BUDGET_S]


@pytest.mark.parametrize(
    "call", ["audit_test_clock_boot", "bars_runtime.start", "ws_runtime.start"]
)
@pytest.mark.parametrize(
    "make",
    [asyncio.CancelledError, KeyboardInterrupt, lambda: SystemExit(3)],
    ids=["cancelled-error", "keyboard-interrupt", "system-exit"],
)
async def test_lifespan_boot_cancelled_or_exiting_after_start_all_stops_what_started_then_reraises(
    monkeypatch: pytest.MonkeyPatch, call: str, make: Callable[[], BaseException]
) -> None:
    """A cancellation or a process exit at the first, an awaited and the last boot call: never
    swallowed, it leaves the lifespan, the same object, once the same teardown has run. Caught
    only as an `Exception`, it skips the teardown, and that fails."""
    stopped = await _stopped_after(call, monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    exc = make()
    _fail(call, exc, app, steps, monkeypatch)
    with pytest.raises(type(exc)) as raised:
        await _run(app)
    assert raised.value is exc
    assert ran == stopped


async def test_lifespan_boot_failure_with_a_failing_stop_still_stops_the_rest_then_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boot's teardown is #3403's, isolated: a stop that raises an error is logged and goes no
    further, every later step and `stop_all` still run, and the boot's own error leaves."""
    stopped = await _stopped_after("bars_runtime.start", monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    exc = RuntimeError("bars_runtime.start failed")
    _fail("bars_runtime.start", exc, app, steps, monkeypatch)
    steps["feature_flags"].fail = RuntimeError("feature_flags failed")
    with capture_logs() as logs, pytest.raises(RuntimeError) as raised:
        await _run(app)
    assert raised.value is exc
    assert ran == stopped
    assert _failed_steps(logs) == [("feature_flags", "RuntimeError", "error", True)]


async def test_lifespan_boot_failure_with_a_stop_held_reraises_the_held_one_after_stop_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop's `KeyboardInterrupt` is held, as at shutdown: every later step and `stop_all` still
    run, and then it leaves the lifespan, the boot's error as its context, so neither is lost."""
    stopped = await _stopped_after("bars_runtime.start", monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    boot = RuntimeError("bars_runtime.start failed")
    _fail("bars_runtime.start", boot, app, steps, monkeypatch)
    held = steps["feature_flags"].fail = KeyboardInterrupt()
    with capture_logs() as logs, pytest.raises(KeyboardInterrupt) as raised:
        await _run(app)
    assert raised.value is held
    assert raised.value.__context__ is boot
    assert ran == stopped
    assert _failed_steps(logs) == [("feature_flags", "KeyboardInterrupt", "error", True)]
