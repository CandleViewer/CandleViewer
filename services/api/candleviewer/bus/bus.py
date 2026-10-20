"""In-process topic bus (M5) — `docs/plan/20-architecture.md` §3/§4.

`Bus.publish(topic, event)` fans out synchronously to the pre-resolved
subscriber list for that topic (hot path: no string matching, O(number of
subscribers of that topic)). `Bus.subscribe(pattern, policy)` returns a
`Subscription` wrapping a bounded `asyncio.Queue` governed by one of the
three `QueuePolicy` values.

Ordering guarantee: single producer per topic (callers must not publish the
same topic concurrently from two tasks) plus FIFO delivery per subscriber
queue gives deterministic per-topic, per-subscriber ordering.

Replay traffic (E26-T03, 24 §2.9): a replay session's topics (`is_replay_env`)
move none of `bus_published_total`, `bus_delivered_total`, `bus_subscriber_lag`
or `ingest_queue_full_total`, and log no "bus subscriber lagging" warning. Their
labels name no env and a replay lane reuses its live twin's subscriber name, so
replay's designed backpressure would fire the live ingest alert, overwrite live
lag gauges and log a warning per event into the live logs; the replay clock's own
`replay_*` series measure it.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

from candleviewer.bus.errors import BusShuttingDownError
from candleviewer.bus.metrics import (
    bus_conflated_total,
    bus_delivered_total,
    bus_published_total,
    bus_stream_invalidated_total,
    bus_subscriber_lag,
    ingest_queue_full_total,
)
from candleviewer.bus.models import (
    LIVE_ENVS,
    QueuePolicy,
    StreamInvalidated,
    Topic,
    TopicPattern,
    is_replay_env,
)


def _log() -> structlog.stdlib.BoundLogger:
    """Resolved per call: a module-level logger cached under
    `cache_logger_on_first_use=True` keeps a stale processor chain once any test or
    `configure_logging()` ran first, so warnings escape `capture_logs()` (#1979; same
    pitfall as ingestion/rejection.py and ingestion/clock.py)."""
    return structlog.get_logger("candleviewer.bus")  # type: ignore[no-any-return]  # structlog returns Any


DEFAULT_QUEUE_SIZE = 4096
DEFAULT_LAG_WARN_THRESHOLD = 512
"""Queue depth at which a slow-consumer warning is logged (configurable per
subscription via `Bus.subscribe(..., lag_warn_threshold=...)`)."""


@dataclass
class Subscription:
    """One subscriber's queue plus its policy and bookkeeping."""

    name: str
    pattern: TopicPattern
    policy: QueuePolicy
    queue: asyncio.Queue[Any]
    maxsize: int
    lag_warn_threshold: int
    _high_water: int = field(default=0, init=False)

    async def get(self) -> Any:
        """Await the next item. For `CONFLATE_LATEST` subscribers the bus
        already collapses the queue down to the newest item on delivery
        (see `Bus._deliver`), so this is a plain queue `get`."""
        item = await self.queue.get()
        self.queue.task_done()
        return item

    def get_nowait(self) -> Any:
        item = self.queue.get_nowait()
        self.queue.task_done()
        return item

    def qsize(self) -> int:
        return self.queue.qsize()


# Ingest-class label values the tickets/dashboards name (E08-S04: class="trade").
_QUEUE_FULL_CLASS = {"md.trade": "trade"}


class Bus:
    """The in-process pub/sub bus (M5). One instance per process, injected
    into `AppContext` and every module that needs to publish or subscribe."""

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self._resolved_cache: dict[str, list[Subscription]] = {}
        self._accepting = True
        self._pending_never_drop = 0

    def subscribe(
        self,
        name: str,
        pattern: str | TopicPattern,
        policy: QueuePolicy,
        *,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        lag_warn_threshold: int = DEFAULT_LAG_WARN_THRESHOLD,
    ) -> Subscription:
        """Register a subscriber. `pattern` may be a dotted string (parsed via
        `TopicPattern.parse`) or a `TopicPattern`. Must be called before the
        matching topics are published so the resolved-subscriber cache for
        those topics is correct (subscriptions are not expected to churn on
        the hot path)."""
        if isinstance(pattern, str):
            pattern = TopicPattern.parse(pattern)
        sub = Subscription(
            name=name,
            pattern=pattern,
            policy=policy,
            queue=asyncio.Queue(maxsize=maxsize),
            maxsize=maxsize,
            lag_warn_threshold=lag_warn_threshold,
        )
        self._subscriptions.append(sub)
        self._resolved_cache.clear()
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscriptions.remove(sub)
        self._resolved_cache.clear()

    def _resolve(self, topic: Topic) -> list[Subscription]:
        cached = self._resolved_cache.get(topic.key)
        if cached is not None:
            return cached
        matched = [s for s in self._subscriptions if s.pattern.matches(topic)]
        self._resolved_cache[topic.key] = matched
        return matched

    async def publish(self, topic: Topic, event: Any) -> None:
        """Fan out `event` to every subscriber whose pattern matches `topic`,
        per each subscriber's own `QueuePolicy`. The only await point is a
        full `NEVER_DROP` queue (§4.1 rule 1: bus is otherwise synchronous).
        A replay session's topic is not counted (module doc)."""
        if not self._accepting:
            raise BusShuttingDownError("Bus.drain() has stopped accepting publishes")
        # The set lookup keeps the live hot path off the replay env's regex.
        counted = topic.env in LIVE_ENVS or not is_replay_env(topic.env)
        if counted:
            bus_published_total.labels(topic_class=topic.topic_class).inc()
        for sub in self._resolve(topic):
            await self._deliver(sub, topic, event, counted)

    async def _deliver(self, sub: Subscription, topic: Topic, event: Any, counted: bool) -> None:
        if sub.policy is QueuePolicy.NEVER_DROP:
            if sub.queue.full():
                if counted:
                    ingest_queue_full_total.labels(
                        **{"class": _QUEUE_FULL_CLASS.get(topic.topic_class, topic.topic_class)}
                    ).inc()
                self._pending_never_drop += 1
                try:
                    await sub.queue.put(event)
                finally:
                    self._pending_never_drop -= 1
            else:
                await sub.queue.put(event)
        elif sub.policy is QueuePolicy.INVALIDATE_ON_FULL:
            if sub.queue.full():
                self._drain_queue_nowait(sub.queue)
                marker = StreamInvalidated(topic=topic.key, ts_event=getattr(event, "ts_event", 0))
                sub.queue.put_nowait(marker)
                bus_stream_invalidated_total.labels(topic_class=topic.topic_class).inc()
            else:
                sub.queue.put_nowait(event)
        elif sub.policy is QueuePolicy.CONFLATE_LATEST:
            # Keep newest only: drop whatever is already queued (0 or more
            # items), regardless of whether the queue happens to be full,
            # so a paused subscriber never accumulates stale backlog.
            drained = self._drain_queue_nowait(sub.queue)
            if drained:
                bus_conflated_total.labels(topic_class=topic.topic_class).inc()
            sub.queue.put_nowait(event)
        else:  # pragma: no cover - exhaustive enum guarded by mypy
            raise AssertionError(f"unhandled policy {sub.policy!r}")

        depth = sub.qsize()
        if depth > sub._high_water:
            sub._high_water = depth
        if counted:
            bus_delivered_total.labels(subscriber=sub.name).inc()
            bus_subscriber_lag.labels(subscriber=sub.name).set(depth)
        # A replay lane sits at depth by design (its publisher waits), so at 100x this would be
        # a warning per event, named for its live twin, in the live logs.
        if counted and depth >= sub.lag_warn_threshold:
            _log().warning(
                "bus subscriber lagging",
                subscriber=sub.name,
                topic=topic.key,
                queue_depth=depth,
            )

    @staticmethod
    def _drain_queue_nowait(queue: asyncio.Queue[Any]) -> int:
        """Drain and discard every currently-queued item. Returns the count
        of items removed."""
        drained: deque[Any] = deque()
        while True:
            try:
                drained.append(queue.get_nowait())
                queue.task_done()
            except asyncio.QueueEmpty:
                break
        return len(drained)

    async def drain(self, grace_s: float) -> dict[str, int]:
        """Stop accepting new publishes, then wait up to `grace_s` seconds
        for every `NEVER_DROP` subscriber queue to empty. Returns the
        outstanding item count per subscriber name that did not drain in
        time (empty dict means nothing was lost)."""
        self._accepting = False
        never_drop = [s for s in self._subscriptions if s.policy is QueuePolicy.NEVER_DROP]
        deadline = asyncio.get_event_loop().time() + grace_s
        outstanding: dict[str, int] = {}
        for sub in never_drop:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                if sub.qsize() or self._pending_never_drop:
                    outstanding[sub.name] = sub.qsize()
                continue
            try:
                await asyncio.wait_for(sub.queue.join(), timeout=max(remaining, 0))
            except TimeoutError:
                pass
            if sub.qsize():
                outstanding[sub.name] = sub.qsize()
        if outstanding:
            _log().warning("bus drain: outstanding never-drop events", outstanding=outstanding)
        return outstanding
