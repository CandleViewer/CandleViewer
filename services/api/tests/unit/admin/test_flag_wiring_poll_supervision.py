"""The supervision of the maintenance poll (#4973) and of the flag views' polls (C-2.21, C-4.14).

A maintenance poll that ends other than through `FeatureFlagsRuntime.stop()` (an error, a return or
a stray cancel) latches the gate engaged until a restart, so no later write's hook opens it, counts
`cv_order_entry_gate_poll_dead_total` and logs CRITICAL by the error's class alone; a view's poll
that so ends latches its view off, counts `cv_flag_view_stopped_total{flag}` and logs the same way.
`stop()`'s own cancel is none of these. Deterministic: each poll is a fake driven by an
`asyncio.Event`, and each test waits on the task itself."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.admin.flags import LIVE_ENABLED, MAINTENANCE_MODE, StoredFlag
from candleviewer.flags_wiring import FeatureFlagsRuntime, FlagView
from tests.unit.admin.test_flag_wiring import _OWNER, _runtime

_ACCOUNT = uuid.uuid4()
_ERROR_TEXT = "the store at db-internal-3 refused row 7"  # an error's text: never logged


def _dead() -> float:
    return REGISTRY.get_sample_value("cv_order_entry_gate_poll_dead_total") or 0.0


def _poll(
    runtime: FeatureFlagsRuntime,
    opened: asyncio.Event,
    release: asyncio.Event,
    end: str,
    ending: asyncio.Event | None = None,
) -> None:
    """The maintenance poll: it opens the gate as a first read does (`opened`), then ends as `end`
    says once `release` is set: `raise`, `return`, or `wait` (until it is cancelled). `ending` is
    set in the poll's last step, so its waiter resumes before the poll's done-callbacks run."""

    async def run() -> None:
        runtime.gate.set(False)
        opened.set()
        await release.wait()
        if ending is not None:
            ending.set()
        if end == "raise":
            raise RuntimeError(_ERROR_TEXT)
        if end == "wait":
            await asyncio.Event().wait()

    runtime.controller.run = run  # type: ignore[method-assign]  # the fake poll replaces it


async def _started(
    end: str, ending: asyncio.Event | None = None
) -> tuple[FeatureFlagsRuntime, asyncio.Event, asyncio.Task[None]]:
    """A started runtime over the fake poll, once that poll has opened the gate."""
    runtime, opened, release = _runtime(), asyncio.Event(), asyncio.Event()
    _poll(runtime, opened, release, end, ending)
    await runtime.start()
    poll = runtime._poll
    assert poll is not None
    await asyncio.wait_for(opened.wait(), 5)  # a bound, never a sleep
    assert runtime.gate.refusal(_ACCOUNT) is None
    return runtime, release, poll


Kill = Callable[[asyncio.Task[None], asyncio.Event], Awaitable[None]]


async def _release(poll: asyncio.Task[None], release: asyncio.Event) -> None:
    release.set()


async def _cancel(poll: asyncio.Task[None], release: asyncio.Event) -> None:
    poll.cancel()  # a cancel that is not `stop()`'s


@pytest.mark.parametrize(
    ("end", "kill", "logged"),
    [
        ("raise", _release, "RuntimeError"),
        ("return", _release, "returned"),
        ("wait", _cancel, "CancelledError"),
    ],
)
async def test_a_poll_that_dies_latches_the_gate_closed_counts_and_logs_its_class(
    end: str, kill: Kill, logged: str
) -> None:
    runtime, release, poll = await _started(end)
    dead = _dead()
    try:
        with capture_logs() as logs:
            await kill(poll, release)
            await asyncio.wait({poll})  # our done-callback, added first, has run
        refusal = runtime.gate.refusal(_ACCOUNT)
        assert refusal is not None and refusal.reason == "maintenance"
        assert _dead() - dead == 1
        (line,) = [log for log in logs if log["event"] == "order_entry_gate_poll_dead"]
        assert (line["log_level"], line["error"], line["cv_page"]) == ("critical", logged, True)
        assert line["task"] == "feature-flag-maintenance-poll" and _ERROR_TEXT not in repr(logs)
        # no later write opens it: the hook a `maintenance.mode = false` write runs, then `set`
        off = StoredFlag(False)
        await runtime.controller.gate_hook(MAINTENANCE_MODE, None, off)
        await runtime.controller.gate_hook("killswitch.order_entry", None, off)
        runtime.gate.set(False)
        assert runtime.gate.engaged and runtime.gate.refusal(_ACCOUNT) is not None
    finally:
        await runtime.stop()
    assert runtime.gate.engaged and _dead() - dead == 1  # the stop counts nothing more


async def test_the_stops_cancel_is_no_death_and_leaves_the_gate_as_the_poll_read_it() -> None:
    runtime, _release_event, poll = await _started("wait")
    dead = _dead()
    with capture_logs() as logs:
        await runtime.stop()
    assert poll.cancelled() and runtime._poll is None
    assert _dead() == dead and [log for log in logs if log["log_level"] == "critical"] == []
    assert runtime.gate.refusal(_ACCOUNT) is None  # not latched: a write's hook still governs
    runtime.gate.set(True)
    runtime.gate.set(False)
    assert not runtime.gate.engaged


async def test_a_poll_dead_before_the_stop_is_still_counted_once_its_callback_runs() -> None:
    ending = asyncio.Event()
    runtime, release, poll = await _started("return", ending)
    dead = _dead()
    with capture_logs() as logs:
        release.set()
        await asyncio.wait_for(ending.wait(), 5)  # the poll has returned; its callback is queued
        assert poll.done()
        await runtime.stop()  # it runs before that callback: the death is not taken for its cancel
        await asyncio.wait({poll})
    assert runtime.gate.engaged and runtime.gate.refusal(_ACCOUNT) is not None
    assert _dead() - dead == 1
    (line,) = [log for log in logs if log["event"] == "order_entry_gate_poll_dead"]
    assert (line["error"], line["cv_page"]) == ("returned", True)


# --- The flag views' polls (C-2.21, C-4.14): a death latches the view off until a restart ---------

_LIVE = LIVE_ENABLED  # the LIVE_GATE flag's view: its stale `True` would keep live orders admitted
_EVIDENCE = "https://github.com/CandleViewer/CandleViewer/issues/412"  # a live-gate write needs it


def _stopped(key: str = _LIVE) -> float:
    return REGISTRY.get_sample_value("cv_flag_view_stopped_total", {"flag": key}) or 0.0


async def _view_started(
    end: str, ending: asyncio.Event | None = None
) -> tuple[FeatureFlagsRuntime, FlagView, asyncio.Event, asyncio.Task[None]]:
    """A started runtime whose live view's poll is a fake: it reads the flag on, as a first read of
    a stored `true` does, then ends as `end` says once `release` is set (see `_poll`)."""
    runtime, opened, release = _runtime(), asyncio.Event(), asyncio.Event()
    view = runtime.live_enabled

    async def run() -> None:
        view._apply(StoredFlag(True))
        opened.set()
        await release.wait()
        if ending is not None:
            ending.set()
        if end == "raise":
            raise RuntimeError(_ERROR_TEXT)
        if end == "wait":
            await asyncio.Event().wait()

    view.run = run  # type: ignore[method-assign]  # the fake poll replaces it
    await runtime.start()
    (poll,) = [task for task in runtime._view_polls if task.get_name().endswith(_LIVE)]
    await asyncio.wait_for(opened.wait(), 5)  # a bound, never a sleep
    assert view() is True
    return runtime, view, release, poll


async def _reads_on_again(runtime: FeatureFlagsRuntime, view: FlagView) -> None:
    """Every path that writes the view's value, each with an on reading: the writer's hook, a
    poll's apply and a refresh of a stored `true`."""
    row = await runtime.service.stored(runtime.registry[_LIVE])
    assert row is not None
    await runtime.writer.set(
        _LIVE, _OWNER, value=True, reason="pen test passed",
        expected_updated_at=row.updated_at, evidence_url=_EVIDENCE,
    )  # fmt: skip
    await view.on_change(_LIVE, None, StoredFlag(True))
    view._apply(StoredFlag(True))
    await view.refresh()


@pytest.mark.parametrize(
    ("end", "kill", "logged"),
    [
        ("raise", _release, "RuntimeError"),
        ("return", _release, "returned"),
        ("wait", _cancel, "CancelledError"),
    ],
)
async def test_a_view_poll_that_dies_latches_the_view_off_counts_and_logs_its_class(
    end: str, kill: Kill, logged: str
) -> None:
    runtime, view, release, poll = await _view_started(end)
    stopped = _stopped()
    try:
        with capture_logs() as logs:
            await kill(poll, release)
            await asyncio.wait({poll})  # its done-callback, added first, has run
        assert view() is False and _stopped() - stopped == 1
        (line,) = [log for log in logs if log["event"] == "flag_view_poll_dead"]
        assert (line["log_level"], line["error"], line["cv_page"]) == ("critical", logged, True)
        assert (line["key"], line["task"]) == (_LIVE, f"feature-flag-view-{_LIVE}")
        assert _ERROR_TEXT not in repr(logs)
        await _reads_on_again(runtime, view)  # no later write, apply or refresh reopens it
        assert view() is False and runtime.live_enabled() is False
    finally:
        await runtime.stop()
    assert view() is False and _stopped() - stopped == 1  # the stop counts nothing more


async def test_the_stops_cancel_of_a_view_poll_is_no_death_and_leaves_the_view_open() -> None:
    runtime, view, _release_event, poll = await _view_started("wait")
    stopped = _stopped()
    with capture_logs() as logs:
        await runtime.stop()
    assert poll.cancelled() and runtime._view_polls == [] and runtime._stopped_polls == set()
    assert _stopped() == stopped and [log for log in logs if log["log_level"] == "critical"] == []
    assert view() is True  # not latched: a write's hook still governs it
    await view.on_change(_LIVE, None, StoredFlag(False))
    await view.on_change(_LIVE, None, StoredFlag(True))
    assert view() is True


async def test_a_view_poll_dead_before_the_stop_is_still_counted_once() -> None:
    ending = asyncio.Event()
    runtime, view, release, poll = await _view_started("return", ending)
    stopped = _stopped()
    with capture_logs() as logs:
        release.set()
        await asyncio.wait_for(ending.wait(), 5)  # the poll has returned; its callback is queued
        assert poll.done()
        await runtime.stop()  # it runs before that callback: the death is not taken for its cancel
        await asyncio.wait({poll})
    assert view() is False and _stopped() - stopped == 1
    (line,) = [log for log in logs if log["event"] == "flag_view_poll_dead"]
    assert (line["error"], line["cv_page"], line["key"]) == ("returned", True, _LIVE)
