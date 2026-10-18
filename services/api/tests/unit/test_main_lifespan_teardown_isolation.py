"""#3403: a failed lifespan teardown step never keeps `Supervisor.stop_all`, and with it
`secrets.stop()` zeroing the KEK (C-2.7, C-12.2), from running.

`main.py`'s lifespan teardown stops its runtimes, tasks, pools and drains one after another, then
calls `stop_all`. These tests run the real `_lifespan` over a fake for each of those steps and for
every supervised module, each recording its stop under its name, and make one step raise, or hang
until the task running the teardown is cancelled, or make `stop_all` itself raise. Nothing sleeps
or reads a clock: the fakes never suspend, except the hung one, which is cancelled once it has
started. Each test compares the stops
with those of a teardown in which nothing failed, so the order the teardown's comments name
(`audit_budget_flush` and `account_health` before the modules, `stop_all` last) is kept as it is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, MutableMapping
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from candleviewer import main
from candleviewer.app import _SUPERVISOR_ORDER, Supervisor
from candleviewer.main import _lifespan
from candleviewer.settings import TEARDOWN_BUDGET_S

#: Every step the teardown runs before `stop_all`, in that order, by its `app.state` attribute,
#: or the lifespan's own name for the metrics runtime and the mesh self-check. A failure is logged
#: under that name, except for the five tasks in `_ALERT_TASKS`.
_STEPS = (
    "ws_runtime",
    "user_disable",
    "feature_flags",
    "metrics_runtime",
    "health_registry",
    "disk_budget",
    "health_pg",
    "kline_boundary_pg",
    "log_level_overrides",
    "kline_boundary_refresh",
    "rule_prune_task",
    "funding_refresh_task",
    "alert_purge_task",
    "alert_gauge_task",
    "drawings_purge_task",
    "workspaces_purge_task",
    "incidents_purge_task",
    "scrub_task",
    "audit_verify_job",
    "admin_jobs",
    "bars_runtime",
    "mesh_self_check",
    "account_access_service",
    "csrf_refusal_audits",
    "audit_budget_flush",
    "account_health",
)
#: The steps whose `start()` the lifespan awaits.
_ASYNC_START = ("feature_flags", "bars_runtime")
#: The five tasks the lifespan starts and stops as one list: a failed stop is logged under the
#: task's class name, so each fake is a class of its own, named like the real one.
_ALERT_TASKS = {
    "alert_purge_task": "AlertDeliveriesPurgeTask",
    "alert_gauge_task": "AlertGaugeTask",
    "drawings_purge_task": "DrawingsPurgeTask",
    "workspaces_purge_task": "WorkspacesPurgeTask",
    "incidents_purge_task": "IncidentsPurgeTask",
}


def _logged_as(step: str) -> str:
    """The name a failure of `step` is logged under."""
    return _ALERT_TASKS.get(step, step)


class _Step:
    """One teardown step: its stop, drain or dispose records its name, then hangs until it is
    cancelled when `hang` is set, or raises `fail` when that is set."""

    def __init__(self, name: str, ran: list[str]) -> None:
        self.name, self.ran = name, ran
        self.fail: BaseException | None = None
        self.hang: asyncio.Event | None = None

    async def load_now(self) -> None:  # the kline boundary refresh's first load
        return None

    async def run_once(self) -> None:  # the mesh self-check's boot run
        return None

    async def _end(self) -> int:
        self.ran.append(self.name)
        if self.hang is not None:
            self.hang.set()
            await asyncio.Event().wait()
        if self.fail is not None:
            raise self.fail
        return 0  # nothing left in flight, for the drains that count

    stop = drain = dispose = _end


class _SyncStart(_Step):
    def start(self) -> None:
        return None


class _AsyncStart(_Step):
    async def start(self) -> None:
        return None


def _step_class(name: str) -> type[_Step]:
    """The fake's class: one of its own, named like the real one, for an alert task."""
    if name not in _ALERT_TASKS:
        return _AsyncStart if name in _ASYNC_START else _SyncStart

    class _AlertTask(_SyncStart):
        pass

    _AlertTask.__name__ = _ALERT_TASKS[name]
    return _AlertTask


class _Module:
    """A supervised module: its stop records `module:<name>`."""

    def __init__(self, name: str, ran: list[str]) -> None:
        self.name, self.ran = name, ran

    async def start(self, ctx: object) -> None:
        return None

    async def stop(self, grace_s: float) -> None:
        self.ran.append(f"module:{self.name}")


def _app(ran: list[str], monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, dict[str, _Step]]:
    """The app with every teardown step and every supervised module faked; returns the steps."""
    steps = {name: _step_class(name)(name, ran) for name in _STEPS}
    app = FastAPI()
    app.state.app_context = SimpleNamespace(
        settings=SimpleNamespace(
            metrics_enabled=True,
            metrics_bind="127.0.0.1:0",
            test_clock=False,
            account_fixture=None,
        ),
        mesh_self_check=steps["mesh_self_check"],
        oms_read_only_gate=SimpleNamespace(is_read_only=False, reason_code=None, reason_text=None),
        **{name: _Module(name, ran) for name in _SUPERVISOR_ORDER},
    )
    for name, step in steps.items():
        if name not in ("metrics_runtime", "mesh_self_check"):
            setattr(app.state, name, step)
    app.state.metrics_facade = SimpleNamespace(add_process_collectors=lambda: None)
    monkeypatch.setattr(main, "MetricsRuntime", lambda facade, bind: steps["metrics_runtime"])
    return app, steps


async def _run(app: FastAPI) -> None:
    async with _lifespan(app):
        pass


async def _unfailed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The stops of a teardown in which nothing fails: every step once, then every module."""
    ran: list[str] = []
    await _run(_app(ran, monkeypatch)[0])
    assert sorted(ran[: len(_STEPS)]) == sorted(_STEPS)  # every step is faked, so each is covered
    assert ran[len(_STEPS) :] == [f"module:{name}" for name in reversed(_SUPERVISOR_ORDER)]
    return ran


def _failed_steps(logs: list[MutableMapping[str, Any]]) -> list[tuple[object, ...]]:
    """The step, exception type, level and traceback flag of each failed-step line, in order."""
    return [
        (e["step"], e["exc_type"], e["log_level"], e.get("exc_info"))
        for e in logs
        if e["event"] == "lifespan: teardown step failed"
    ]


@pytest.mark.parametrize("step", _STEPS)
async def test_lifespan_teardown_after_a_raising_step_still_runs_every_later_step_and_stop_all(
    monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """The failure is logged with the step's name and type and goes no further: every later step
    still runs, in the same order, and then `stop_all`, which stops `secrets`. The step awaited
    bare, or its error caught nowhere, fails it."""
    unfailed = await _unfailed(monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    steps[step].fail = RuntimeError(f"{step} failed")
    with capture_logs() as logs:
        await _run(app)
    assert ran == unfailed
    assert _failed_steps(logs) == [(_logged_as(step), "RuntimeError", "error", True)]


class _Fatal(BaseException):
    """Neither an `Exception`, nor a cancellation, nor a process exit: a library's own
    `BaseException` subclass, for one."""


@pytest.mark.parametrize(
    "make",
    [
        asyncio.CancelledError,
        KeyboardInterrupt,
        lambda: SystemExit(3),
        lambda: _Fatal("a library's own BaseException"),
        lambda: BaseExceptionGroup("unhandled errors in a TaskGroup", [KeyboardInterrupt()]),
    ],
    ids=["cancelled-error", "keyboard-interrupt", "system-exit", "base-exception", "group"],
)
async def test_lifespan_teardown_after_a_step_raised_a_base_exception_reraises_it_once_stop_all_ran(
    monkeypatch: pytest.MonkeyPatch, make: Callable[[], BaseException]
) -> None:
    """The first step raises it. It is logged, every later step and `stop_all` still run, and
    then the same object leaves the lifespan. Re-raised at once, or never, or caught only as an
    `Exception`, it fails."""
    unfailed = await _unfailed(monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    exc = steps["ws_runtime"].fail = make()
    with capture_logs() as logs, pytest.raises(type(exc)) as raised:
        await _run(app)
    assert raised.value is exc
    assert ran == unfailed
    assert _failed_steps(logs) == [("ws_runtime", type(exc).__name__, "error", True)]


async def test_lifespan_teardown_with_two_steps_raising_reraises_the_first_and_logs_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first held exception wins; the later one is logged, not lost and not re-raised."""
    unfailed = await _unfailed(monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    first = steps["ws_runtime"].fail = KeyboardInterrupt()
    steps["account_health"].fail = SystemExit(3)
    with capture_logs() as logs, pytest.raises(KeyboardInterrupt) as raised:
        await _run(app)
    assert raised.value is first
    assert ran == unfailed
    assert _failed_steps(logs) == [
        ("ws_runtime", "KeyboardInterrupt", "error", True),
        ("account_health", "SystemExit", "error", True),
    ]


async def test_lifespan_teardown_cancelled_in_a_hung_step_runs_every_later_step_then_ends_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An outside cancellation ends the hung step, and is held, never uncancelled: every later
    step and `stop_all` still run, and the task running the teardown then ends cancelled."""
    unfailed = await _unfailed(monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    hung = steps["bars_runtime"].hang = asyncio.Event()
    lifespan = _lifespan(app)
    await lifespan.__aenter__()
    with capture_logs() as logs:
        teardown = asyncio.create_task(lifespan.__aexit__(None, None, None))
        await hung.wait()
        teardown.cancel()
        done, _ = await asyncio.wait({teardown}, timeout=5)  # bounds the test; times nothing
    assert teardown in done and teardown.cancelled()
    assert ran == unfailed
    assert _failed_steps(logs) == [("bars_runtime", "CancelledError", "error", True)]


class _BrokenLog:
    """A logger whose failure line itself raises."""

    def exception(self, event: str, **fields: object) -> None:
        raise RuntimeError("log sink down")


async def test_lifespan_teardown_when_a_failure_cannot_be_logged_still_runs_stop_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `finally` around the steps: the isolation's own log line fails, its error leaves the
    steps, and `stop_all` still stops every module, `secrets` included, before it propagates."""
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    steps["ws_runtime"].fail = RuntimeError("ws_runtime failed")
    lifespan = _lifespan(app)
    await lifespan.__aenter__()
    monkeypatch.setattr(main, "logger", _BrokenLog)  # the boot lines were written by now
    with pytest.raises(RuntimeError, match="log sink down"):
        await lifespan.__aexit__(None, None, None)
    modules = [r for r in ran if r.startswith("module:")]
    assert modules == [f"module:{name}" for name in reversed(_SUPERVISOR_ORDER)]


def _stop_all_raising(fail: BaseException) -> type[Supervisor]:
    """The real supervisor, whose `stop_all` raises `fail` once it has stopped every module."""

    class _Supervisor(Supervisor):
        async def stop_all(self, grace_s: float = TEARDOWN_BUDGET_S) -> None:
            await super().stop_all(grace_s)
            raise fail

    return _Supervisor


async def test_lifespan_teardown_when_stop_all_raises_after_a_held_exception_reraises_the_held_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`stop_all` runs through the same isolation: its own failure is logged, and the exception a
    step raised first still wins. `stop_all` awaited bare fails it."""
    unfailed = await _unfailed(monkeypatch)
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    first = steps["ws_runtime"].fail = KeyboardInterrupt()
    monkeypatch.setattr(main, "Supervisor", _stop_all_raising(SystemExit(3)))
    with capture_logs() as logs, pytest.raises(KeyboardInterrupt) as raised:
        await _run(app)
    assert raised.value is first
    assert ran == unfailed
    assert _failed_steps(logs) == [
        ("ws_runtime", "KeyboardInterrupt", "error", True),
        ("supervisor.stop_all", "SystemExit", "error", True),
    ]


async def test_lifespan_teardown_when_stop_all_raises_an_error_logs_it_and_goes_no_further(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An `Exception` out of `stop_all` is logged like a step's and ends there."""
    unfailed = await _unfailed(monkeypatch)
    ran: list[str] = []
    app, _ = _app(ran, monkeypatch)
    monkeypatch.setattr(main, "Supervisor", _stop_all_raising(RuntimeError("stop_all failed")))
    with capture_logs() as logs:
        await _run(app)
    assert ran == unfailed
    assert _failed_steps(logs) == [("supervisor.stop_all", "RuntimeError", "error", True)]


async def test_lifespan_teardown_after_a_step_raised_generator_exit_skips_later_steps_not_stop_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `GeneratorExit` means the coroutine is being closed, so no later step may await: it
    leaves at once, unlogged and unchanged, and only the `finally` still runs `stop_all`. Held
    like any other `BaseException`, it fails."""
    ran: list[str] = []
    app, steps = _app(ran, monkeypatch)
    exc = steps["ws_runtime"].fail = GeneratorExit()
    with capture_logs() as logs, pytest.raises(GeneratorExit) as raised:
        await _run(app)
    assert raised.value is exc
    assert ran == ["ws_runtime", *(f"module:{name}" for name in reversed(_SUPERVISOR_ORDER))]
    assert _failed_steps(logs) == []
