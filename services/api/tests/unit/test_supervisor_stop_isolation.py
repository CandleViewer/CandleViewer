"""#3346, #3361: one failed module `stop()` never keeps `Supervisor._stop_each` from the next one.

`_stop_each` promises that a raising or hanging `stop()` never prevents a later one, such as
`secrets.stop()` zeroing the KEK (C-2.7, C-12.2). These tests run the real `_stop_each` over
`audit` then `secrets`, with an `audit` stop that hangs or raises, and read the bound each stop is
given instead of timing it (#3342): `asyncio.timeout` is replaced by a recorder that cuts the
guarded stop at once, so nothing sleeps and no assertion depends on elapsed time. `_stop_each`
stops the names it is given in that order; the reverse start order `stop_all` gives it is pinned
by `tests/unit/credentials_m2/test_degraded_wiring.py`.

#3361 holds that promise for every `BaseException`, not only an `Exception`: one that is neither a
cancellation nor a process exit is logged as a failed stop, and a cancellation, `KeyboardInterrupt`
or `SystemExit` still propagates, unchanged, but only once every later stop has run. The test of
an outside cancellation gives each stop an unbounded `asyncio.timeout(None)` instead, so only the
cancellation can end the hung stop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from types import SimpleNamespace
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.app import _SUPERVISOR_ORDER, AppContext, Supervisor

_GRACE_S = 0.05
#: Patched over `STOP_SLACK_S` (1.0), so a literal 1 s slack in `_stop_each` would ask for 1.05.
_SLACK_S = 0.1


async def _hang() -> None:
    await asyncio.Event().wait()


async def _raise() -> None:
    raise RuntimeError("audit stop failed")  # before any wait, so the cut cannot land first


class _Audit:
    """The first module: records its `stop()`, then hangs or raises, and records how it ended."""

    def __init__(self, events: list[str], fail: Callable[[], Awaitable[None]]) -> None:
        self._events, self._fail = events, fail

    async def stop(self, grace_s: float) -> None:
        self._events.append(f"audit.stop({grace_s:g})")
        try:
            await self._fail()
        except asyncio.CancelledError:  # the bound's cut, re-raised for the timeout to absorb
            self._events.append("audit cut")
            raise
        except RuntimeError:
            self._events.append("audit raised")
            raise


class _Secrets:
    """The later module: records its `stop()` and returns without yielding, before any cut."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def stop(self, grace_s: float) -> None:
        self._events.append(f"secrets.stop({grace_s:g})")


@pytest.fixture
def bounds(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """Every bound `_stop_each` asks `asyncio.timeout` for, in call order. Each guarded stop is
    cut at once (`timeout(0)`): a hung stop ends at its first wait instead of after its bound."""
    monkeypatch.setattr("candleviewer.app.STOP_SLACK_S", _SLACK_S)
    asked: list[float | None] = []
    real_timeout = asyncio.timeout

    def _cut_at_once(delay: float | None) -> asyncio.Timeout:
        asked.append(delay)
        return real_timeout(0)

    monkeypatch.setattr(asyncio, "timeout", _cut_at_once)
    return asked


@pytest.mark.parametrize(
    ("fail", "ended"), [(_hang, "audit cut"), (_raise, "audit raised")], ids=["hung", "raising"]
)
async def test_stop_each_after_a_hung_or_raising_stop_still_stops_secrets_with_its_own_bound(
    bounds: list[float | None], fail: Callable[[], Awaitable[None]], ended: str
) -> None:
    """`secrets` stops once `audit`'s stop was cut or raised, with the same grace and a bound of
    its own: the grace plus the slack, not what `audit` left of one. A `return` or `break` after
    the failure log, a reversed loop, one deadline for all stops or concurrent stops (in the hung
    case) each fail it."""
    events: list[str] = []
    ctx = SimpleNamespace(audit=_Audit(events, fail), secrets=_Secrets(events))
    supervisor = Supervisor(cast(AppContext, ctx))
    # `wait_for` bounds the test itself through `asyncio.timeouts`, which the patch leaves alone.
    await asyncio.wait_for(supervisor._stop_each(["audit", "secrets"], _GRACE_S), 5)
    assert events == ["audit.stop(0.05)", ended, "secrets.stop(0.05)"]
    assert bounds == [pytest.approx(0.15), pytest.approx(0.15)]  # 0.05 grace + 0.1 slack, each


# --- #3361: a stop that raises a `BaseException` which is not an `Exception` ------------------


class _Fatal(BaseException):
    """Neither an `Exception`, nor a cancellation, nor a process exit: a library's own
    `BaseException` subclass, for one."""


def _group(*leaves: BaseException) -> BaseExceptionGroup[BaseException]:
    """A group in the shape a `TaskGroup` raises once a child raised a `BaseException` that is
    not an `Exception`. A `TaskGroup` re-raises a `KeyboardInterrupt` or `SystemExit` bare, but
    other code can group one."""
    return BaseExceptionGroup("unhandled errors in a TaskGroup", list(leaves))


class _Raising:
    """An earlier module: records its `stop()`, then raises before any wait, so no cut lands."""

    def __init__(self, events: list[str], name: str, exc: BaseException) -> None:
        self._events, self._name, self._exc = events, name, exc

    async def stop(self, grace_s: float) -> None:
        self._events.append(f"{self._name}.stop({grace_s:g})")
        raise self._exc


def _failed_stops(logs: list[MutableMapping[str, Any]]) -> list[tuple[object, ...]]:
    """The module, level, traceback flag and exception type of every failed-stop log line, in
    order: the type tells a cancellation or an exit request passing through a stop from the
    module's own failure (#3403)."""
    return [
        (e["module"], e["log_level"], e.get("exc_info"), e.get("exc_type"))
        for e in logs
        if e["event"] == "supervisor: module stop failed"
    ]


@pytest.mark.parametrize(
    "make",
    [
        lambda: _Fatal("audit stop failed"),
        lambda: _group(_Fatal("a child of the audit stop failed")),
        GeneratorExit,
    ],
    ids=["base-exception-subclass", "base-exception-group", "generator-exit"],
)
async def test_stop_each_logs_a_base_exception_that_is_not_an_exception_and_still_stops_secrets(
    bounds: list[float | None], make: Callable[[], BaseException]
) -> None:
    """Logged as `audit`'s failed stop, with its traceback, and `secrets` stops after it with
    its own bound. An `except Exception` lets each of these leave the loop before
    `secrets.stop()`, and fails it."""
    exc = make()
    events: list[str] = []
    ctx = SimpleNamespace(audit=_Raising(events, "audit", exc), secrets=_Secrets(events))
    supervisor = Supervisor(cast(AppContext, ctx))
    with capture_logs() as logs:
        await asyncio.wait_for(supervisor._stop_each(["audit", "secrets"], _GRACE_S), 5)
    assert events == ["audit.stop(0.05)", "secrets.stop(0.05)"]
    assert bounds == [pytest.approx(0.15), pytest.approx(0.15)]
    assert _failed_stops(logs) == [("audit", "error", True, type(exc).__name__)]


@pytest.mark.parametrize(
    "make",
    [
        KeyboardInterrupt,
        lambda: SystemExit(3),
        asyncio.CancelledError,
        lambda: _group(_Fatal("a child failed"), KeyboardInterrupt()),
    ],
    ids=["keyboard-interrupt", "system-exit", "cancelled-error", "group-holding-one"],
)
async def test_stop_each_reraises_a_cancellation_or_process_exit_once_secrets_has_stopped(
    bounds: list[float | None], make: Callable[[], BaseException]
) -> None:
    """Never swallowed, and never at the KEK's expense: `audit`'s failure is logged, `secrets`
    still stops with its own bound, and only then does the same exception propagate. An
    `except BaseException` that logs it and moves on (DID NOT RAISE), and a re-raise before the
    later stops (no `secrets.stop`), each fail it."""
    exc = make()
    events: list[str] = []
    ctx = SimpleNamespace(audit=_Raising(events, "audit", exc), secrets=_Secrets(events))
    supervisor = Supervisor(cast(AppContext, ctx))
    with capture_logs() as logs, pytest.raises(type(exc)) as raised:
        await asyncio.wait_for(supervisor._stop_each(["audit", "secrets"], _GRACE_S), 5)
    assert raised.value is exc
    assert events == ["audit.stop(0.05)", "secrets.stop(0.05)"]
    assert bounds == [pytest.approx(0.15), pytest.approx(0.15)]
    assert _failed_stops(logs) == [("audit", "error", True, type(exc).__name__)]


async def test_stop_each_reraises_the_first_of_two_and_logs_both(
    bounds: list[float | None],
) -> None:
    """Two earlier stops raise one each: both are logged, `secrets` still stops, and the first
    propagates, while the later one is only logged."""
    first, later = KeyboardInterrupt(), SystemExit(3)
    events: list[str] = []
    ctx = SimpleNamespace(
        ws=_Raising(events, "ws", first),
        oms=_Raising(events, "oms", later),
        secrets=_Secrets(events),
    )
    supervisor = Supervisor(cast(AppContext, ctx))
    with capture_logs() as logs, pytest.raises(KeyboardInterrupt) as raised:
        await asyncio.wait_for(supervisor._stop_each(["ws", "oms", "secrets"], _GRACE_S), 5)
    assert raised.value is first
    assert events == ["ws.stop(0.05)", "oms.stop(0.05)", "secrets.stop(0.05)"]
    assert bounds == [pytest.approx(0.15)] * 3
    assert _failed_stops(logs) == [
        ("ws", "error", True, "KeyboardInterrupt"),
        ("oms", "error", True, "SystemExit"),
    ]


# --- #3361: an outside cancellation of the task running `stop_all` ---------------------------


@pytest.fixture
def unbounded(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """Every bound `_stop_each` asks `asyncio.timeout` for, in call order, while no guarded stop
    is ever cut (`timeout(None)`): only an outside cancellation can end a hung stop."""
    monkeypatch.setattr("candleviewer.app.STOP_SLACK_S", _SLACK_S)
    asked: list[float | None] = []
    real_timeout = asyncio.timeout

    def _never_cut(delay: float | None) -> asyncio.Timeout:
        asked.append(delay)
        return real_timeout(None)

    monkeypatch.setattr(asyncio, "timeout", _never_cut)
    return asked


async def test_an_outside_cancellation_of_stop_all_propagates_once_every_later_module_stopped(
    unbounded: list[float | None],
) -> None:
    """The task running `stop_all` is cancelled while the first module it stops hangs. The
    cancellation ends that stop, which is logged; every later module still stops, `secrets`
    included, each with its own bound; then the task ends cancelled. An `except BaseException`
    that logs the cancellation and moves on (the task ends normally), and a re-raise before the
    later stops, each fail it."""
    order = list(reversed(_SUPERVISOR_ORDER))  # the order `stop_all` stops the modules in
    assert "secrets" in order[1:]  # stopped after the module the cancellation lands in
    events: list[str] = []
    hanging = asyncio.Event()

    class _Module:
        def __init__(self, name: str) -> None:
            self._name = name

        async def stop(self, grace_s: float) -> None:
            events.append(self._name)
            if self._name != order[0]:
                return
            hanging.set()
            try:
                await asyncio.Event().wait()  # until the outside cancellation
            except asyncio.CancelledError:
                events.append("cancelled")
                raise

    ctx = SimpleNamespace(**{name: _Module(name) for name in order})
    with capture_logs() as logs:
        task = asyncio.create_task(Supervisor(cast(AppContext, ctx)).stop_all(_GRACE_S))
        await hanging.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            # `wait_for` bounds the test itself through `asyncio.timeouts`, left unpatched.
            await asyncio.wait_for(task, 5)
    assert task.cancelled()
    assert events == [order[0], "cancelled", *order[1:]]
    assert unbounded == [pytest.approx(0.15)] * len(order)
    assert _failed_stops(logs) == [(order[0], "error", True, "CancelledError")]
