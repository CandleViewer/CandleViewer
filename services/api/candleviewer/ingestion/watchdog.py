"""Dedicated ping task + per-topic staleness detection (E08-T04, R6 Feed rot).

Plain code (hot-path exclusion). The ping loop is its own task and never runs
inline in the read loop, so a slow consumer cannot starve it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from candleviewer.domain.events import DomainEvent, uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.ingestion.planner import DemandTracker

PING_INTERVAL_S = 20.0
PONG_DEADLINE_S = 10.0
STALENESS_S: dict[str, float] = {"book": 2.0, "trade": 10.0, "ticker": 5.0}


class FeedHealthEvent(DomainEvent):
    """Per-topic feed health on `{env}.health.feed`, with the 24 §1.4 envelope (C6, #3876)."""

    topic: str
    state: str  # "stale" | "healthy" | "resubscribing" | "degraded" | "delisted" | "warming"
    last_msg_age_s: float


def feed_health(topic: str, state: str, last_msg_age_s: float, *, now_us: int) -> FeedHealthEvent:
    """`FeedHealthEvent` observed at `now_us`, the producer's injected wall clock: a local
    observation has no exchange time, so `ts_event` = `ts_ingest` (24 §2.9)."""
    return FeedHealthEvent(
        event_id=EventId(uuid7(now_us // 1000)),
        ts_event=now_us,
        ts_ingest=now_us,
        source="live",
        topic=topic,
        state=state,
        last_msg_age_s=last_msg_age_s,
    )


def _wall_now_us() -> int:
    return time.time_ns() // 1000


def _default_kind(topic: str) -> str:
    """Venue-neutral fallback: the topic's first dotted segment."""
    return topic.split(".", 1)[0]


class StalenessWatchdog:
    def __init__(
        self,
        clock: Callable[[], float],
        on_health: Callable[[FeedHealthEvent], None],
        limits: dict[str, float] | None = None,
        *,
        kind_of: Callable[[str], str] | None = None,
        now_us: Callable[[], int] = _wall_now_us,
    ) -> None:
        self._clock, self._now_us = clock, now_us  # monotonic ages; wall-clock envelopes
        # Exchange-specific topic -> stream-kind mapping is injected by the
        # composition root (C-2.2: venue vocabulary stays in exchange/<venue>/).
        self._kind = kind_of or _default_kind
        self._on_health = on_health
        self._limits = limits or STALENESS_S
        self._last: dict[str, float] = {}
        self._stale: set[str] = set()
        #: stale because a subscribe was refused (#1955), not because of silence
        self._forced: set[str] = set()

    def watch(self, topic: str) -> None:
        self._last[topic] = self._clock()

    def unwatch(self, topic: str) -> None:
        self._last.pop(topic, None)
        self._stale.discard(topic)
        self._forced.discard(topic)

    def touch(self, topic: str) -> None:
        if topic in self._last:
            self._last[topic] = self._clock()
            self._stale.discard(topic)
            self._forced.discard(topic)

    def force_stale(self, topic: str) -> None:
        """#1955: age a watched topic past its limit (its subscribe was refused or went
        unanswered), so the next `check()` reports it stale and the usual per-topic
        resubscribe retries it. No-op for unwatched or limitless topics."""
        limit = self._limits.get(self._kind(topic))
        if topic in self._last and limit is not None:
            if topic not in self._stale:  # genuine silence already counted stays genuine
                self._forced.add(topic)
            self._last[topic] = min(self._last[topic], self._clock() - limit)

    def reset(self) -> None:
        """Restart staleness timers (after a reconnect)."""
        now = self._clock()
        for topic in self._last:
            self._last[topic] = now
        self._stale.clear()
        self._forced.clear()

    def all_stale(self) -> bool:
        """True when every watched topic that has a limit is stale (#1913): only
        then is the shared socket suspect; one silent topic is per-topic. A topic the
        exchange refused (#1955, `force_stale`) says nothing about the socket, so it
        leaves the set judged: it neither recycles the socket nor keeps it alive."""
        limited = {t for t in self._last if self._kind(t) in self._limits} - self._forced
        return bool(limited) and limited <= self._stale

    def check(self) -> list[str]:
        """Emit stale events; returns newly stale topics."""
        now = self._clock()
        fired: list[str] = []
        for topic, last in self._last.items():
            limit = self._limits.get(self._kind(topic))
            if limit is not None and now - last >= limit and topic not in self._stale:
                self._stale.add(topic)
                fired.append(topic)
                self._on_health(feed_health(topic, "stale", now - last, now_us=self._now_us()))
        return fired


async def prune_unlisted(
    demand: DemandTracker,
    is_listed: Callable[[str], bool],
    sync: Callable[[], None],
    publish: Callable[[FeedHealthEvent], Awaitable[None]],
    topic_for: Callable[[str], str],
    *,
    now_us: Callable[[], int],
) -> list[str]:
    """#1913: drop demand for symbols the catalogue no longer lists as trading
    (held topics were only checked on `acquire`), unsubscribe via `sync()`, and
    publish a `delisted` FeedHealthEvent per symbol. Shared by streams."""
    gone = sorted(s for s in demand.desired() if not is_listed(s))
    for sym in gone:
        demand.drop(sym)
    if gone:
        sync()
    for sym in gone:
        await publish(feed_health(topic_for(sym), "delisted", 0.0, now_us=now_us()))
    return gone


async def ping_loop(
    send_ping: Callable[[], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    *,
    interval_s: float = PING_INTERVAL_S,
) -> None:
    """Emit a ping every `interval_s` forever; cancel to stop."""
    while True:
        await sleep(interval_s)
        await send_ping()
