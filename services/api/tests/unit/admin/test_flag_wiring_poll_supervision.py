"""The maintenance poll's supervision (#4973, C-2.21): a poll that ends other than through
`FeatureFlagsRuntime.stop()` (an error, a return or a stray cancel) latches the gate engaged until a
restart, so no later write's hook opens it, counts `cv_order_entry_gate_poll_dead_total` and logs
CRITICAL by the error's class alone; `stop()`'s own cancel is none of these. Deterministic: the poll
is a fake driven by an `asyncio.Event`, and each test waits on the task itself."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.admin.flags import MAINTENANCE_MODE, StoredFlag
from candleviewer.flags_wiring import FeatureFlagsRuntime
from tests.unit.admin.test_flag_wiring import _runtime

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
