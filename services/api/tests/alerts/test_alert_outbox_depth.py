"""#1016 (E40-T04): the dispatcher samples the `alert.deliver` backlog onto `cv_outbox_depth`,
the gauge `AlertOutboxBacklog` reads: throttled by an injected clock, kept going while a backlog
keeps every poll full, and never a reason to stop dispatching."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _dispatch_env import Clock, Job, MemStore
from prometheus_client import generate_latest
from structlog.testing import capture_logs
from test_alert_dispatcher import Metrics, _disp

from candleviewer.alerts.dispatcher import DEPTH_EVERY_S, AlertDispatcher, default_adapters
from candleviewer.observability.metrics import Metrics as Facade

_GAUGE = "cv_outbox_depth"
_TOPIC = ("alert.deliver",)


class DepthStore(MemStore):
    """`MemStore` that records each depth read and raises `error` from it; `idle` is set by the
    first poll that claims nothing, the point where the loop has drained and is about to wait."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(clock)
        self.asked: list[str] = []
        self.error: BaseException | None = None
        self.idle = asyncio.Event()

    async def depth(self, topic: str) -> int:
        self.asked.append(topic)
        if self.error is not None:
            raise self.error
        return await super().depth(topic)

    async def claim(self, **kw: Any) -> list[Job]:
        jobs = await super().claim(**kw)
        if not jobs:
            self.idle.set()
        return jobs


def _gauge(metrics: Metrics) -> list[float]:
    return [value for name, _, value in metrics.seen if name == _GAUGE]


async def test_the_gauge_is_the_alert_deliver_backlog_without_processed_or_dead_rows() -> None:
    clock, metrics = Clock(), Metrics()
    store = DepthStore(clock)
    store.fire(["in_app", "email", "email", "desktop"])
    store.outbox[1].processed, store.outbox[2].dead = True, True
    d = _disp(store, clock, metric=metrics)
    await d._sample_depth()
    assert store.asked == ["alert.deliver"]
    assert metrics.seen == [(_GAUGE, _TOPIC, 2)]


async def test_the_sample_is_taken_at_most_every_fifteen_seconds_of_the_injected_clock() -> None:
    clock, metrics = Clock(), Metrics()
    store, now = DepthStore(clock), [100.0]
    store.fire(["in_app"])
    d = _disp(store, clock, metric=metrics, monotonic=lambda: now[0])
    await d._sample_depth()
    await d._sample_depth()  # the same instant: no second read
    assert DEPTH_EVERY_S == 15.0 and len(store.asked) == 1
    now[0] += DEPTH_EVERY_S - 1
    await d._sample_depth()
    assert len(store.asked) == 1  # a second short of the interval
    store.outbox[1].processed = True
    now[0] += 1
    await d._sample_depth()
    assert len(store.asked) == 2 and _gauge(metrics) == [1, 0]  # due exactly at the interval


async def test_a_failing_read_is_logged_by_type_keeps_the_last_value_and_waits_its_turn() -> None:
    clock, metrics = Clock(), Metrics()
    store, now = DepthStore(clock), [0.0]
    store.fire(["in_app"])
    d = _disp(store, clock, metric=metrics, monotonic=lambda: now[0], depth_every_s=10)
    await d._sample_depth()
    store.error, now[0] = OSError("connection to db-7 refused"), 10.0
    with capture_logs() as logs:
        await d._sample_depth()
        await d._sample_depth()  # still 10.0: no retry per poll, a failure too waits its turn
    assert logs == [{"event": "alert_outbox_depth_failed", "error": "OSError",
                     "log_level": "warning"}]  # fmt: skip
    assert _gauge(metrics) == [1] and len(store.asked) == 2
    store.error, now[0] = None, 20.0
    await d._sample_depth()
    assert _gauge(metrics) == [1, 1] and len(store.asked) == 3  # and recovers on the next turn


async def test_a_gauge_that_raises_is_contained_like_a_failed_read() -> None:
    def broken(_name: str, _labels: tuple[str, ...]) -> Any:
        raise KeyError("cv_outbox_depth")

    clock = Clock()
    store = DepthStore(clock)
    with capture_logs() as logs:
        await _disp(store, clock, metric=broken)._sample_depth()
    assert [(e["event"], e["error"]) for e in logs] == [("alert_outbox_depth_failed", "KeyError")]


async def test_cancellation_is_not_a_failed_read() -> None:
    clock = Clock()
    store = DepthStore(clock)
    store.error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await _disp(store, clock)._sample_depth()


async def test_the_loop_samples_while_a_backlog_keeps_every_poll_full() -> None:
    """With a batch of 1 and six rows, each of the first six polls is full and loops on at once;
    a sample placed after that `continue` would be taken only by the seventh, empty poll."""
    clock, metrics = Clock(), Metrics()
    store, ticks = DepthStore(clock), iter(range(0, 10**6, 15))  # every read of the clock is due
    store.fire(["in_app"] * 6)
    d = _disp(store, clock, metric=metrics, batch=1, interval_s=3600,
              monotonic=lambda: float(next(ticks)))  # fmt: skip
    d.start()
    async with asyncio.timeout(5):
        await store.idle.wait()
    await d.stop()
    assert _gauge(metrics)[:6] == [5, 4, 3, 2, 1, 0]


async def test_a_failing_read_never_stops_the_loop_dispatching() -> None:
    clock = Clock()
    store = DepthStore(clock)
    store.fire(["in_app"] * 3)
    store.error = OSError("db down")
    d = _disp(store, clock, batch=1, interval_s=3600, monotonic=lambda: 0.0)
    with capture_logs() as logs:
        d.start()
        async with asyncio.timeout(5):
            await store.idle.wait()
        await d.stop()
    assert [r.status for r in store.rows.values()] == ["sent"] * 3
    assert store.asked == ["alert.deliver"]  # one failed attempt, then its turn is 15 s on
    assert [e["event"] for e in logs] == ["alert_outbox_depth_failed"]


async def test_the_app_sink_serves_the_gauge_the_dispatcher_sets() -> None:
    """Through the facade `create_app` builds: the gauge is registered under `topic`, and what the
    dispatcher sets is what a scrape reads."""
    from candleviewer.app import _alert_delivery_sink

    facade, clock = Facade("dev"), Clock()
    store = DepthStore(clock)
    store.fire(["in_app", "email", "email"])
    d = AlertDispatcher(store, default_adapters(None), worker="w", now=clock,
                        metric=_alert_delivery_sink(facade))  # fmt: skip
    await d._sample_depth()
    assert (
        'cv_outbox_depth{env="dev",topic="alert.deliver"} 3.0'
        in generate_latest(facade.registry).decode()
    )
