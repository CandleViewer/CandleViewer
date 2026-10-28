"""Live ticker stream: subscribe once, fan out, delta-merge, reconnect (E08-S03).

the exchange's linear ticker stream is a *delta* stream: absent fields mean unchanged,
not null (`docs/plan/24-internal-schemas.md` §2.3). `TickerMerger` keeps a
per-symbol last-known state and only ever yields fully populated `TickerEvent`s
(`is_delta=False`), so no consumer implements merge logic. Until a complete
state exists the topic reports `warming` instead of publishing a half ticker.

Plain code, never a statechart (catalogue §1.2 hot-path exclusion). Venue
parsing is injected (C-2.2): this module sees only neutral `TickerDelta`s.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from typing import Protocol

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, TopicPattern
from candleviewer.domain.events import uuid7  # re-exported in __all__ for its importers
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.base.ticker_delta import TICKER_FIELDS, TickerDelta
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.metrics import (
    count_event,
    ingest_lag_seconds,
    symbol_label,
    ticker_merge_incomplete_total,
    ticker_writes_dropped_total,
    ws_topic_staleness_seconds,
)
from candleviewer.ingestion.planner import DEFAULT_GRACE_S, DemandTracker
from candleviewer.ingestion.rejection import RejectionLog
from candleviewer.ingestion.watchdog import FeedHealthEvent, feed_health, prune_unlisted
from candleviewer.observability.context import spawn

#: A merged ticker is publishable only once these are all known: a named list (24 §2.3), not
#: every field a delta can carry. The optional remainder (`open_interest_value`,
#: `next_funding_time`, `high_24h`, `low_24h`) may legitimately stay absent and is carried
#: forward when it does arrive.
REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "last_price", "mark_price", "index_price", "bid1_price", "bid1_qty", "ask1_price",
        "ask1_qty", "open_interest", "turnover_24h", "volume_24h", "price_24h_pcnt",
        "funding_rate",
    }
)  # fmt: skip
WRITE_QUEUE_MAXSIZE = 1024  # bounded write-behind (C-2.18); drop-oldest, counted


class UnknownSymbolError(ValueError):
    """Raised when a consumer asks for a symbol the catalogue does not list."""


class TickerWriter(Protocol):
    async def write_ticker(self, event: TickerEvent) -> None: ...


class TickerMerger:
    """Per-symbol last-known state; mutated in place, frozen on emit."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Decimal | int]] = {}

    def invalidate(self, symbol: str | None = None) -> None:
        """Drop merged state (reconnect): rebuilt from the next full push."""
        if symbol is None:
            self._state.clear()
        else:
            self._state.pop(symbol, None)

    def apply(self, delta: TickerDelta, *, ts_ingest_us: int) -> TickerEvent | None:
        """Fold `delta`; the complete event, or `None` while still warming."""
        if delta.is_snapshot:
            self._state[delta.symbol] = {}
        state = self._state.setdefault(delta.symbol, {})
        state.update(delta.fields)  # present keys only; absent == unchanged
        if not REQUIRED_FIELDS <= state.keys():
            ticker_merge_incomplete_total.labels(symbol=symbol_label(delta.symbol)).inc()
            return None
        return ticker_event(
            delta.symbol, state, ts_event_us=delta.ts_event_us, ts_ingest_us=ts_ingest_us
        )


def ticker_event(
    symbol: str, state: Mapping[str, Decimal | int], *, ts_event_us: int, ts_ingest_us: int
) -> TickerEvent:
    """A fully-populated `TickerEvent` of `state` (`is_delta=False`; a field it lacks is `None`):
    the merger's, and each row of the venue-wide snapshot's (`ticker_bulk`, E08-T08)."""
    values: dict[str, Decimal | int | None] = {f: state.get(f) for f in TICKER_FIELDS}
    return TickerEvent.model_validate(
        {
            "event_id": EventId(uuid7(ts_event_us // 1000)),
            "ts_event": ts_event_us,
            "ts_ingest": ts_ingest_us,
            "source": "live",
            "symbol": symbol,
            "is_delta": False,
            **values,
        }
    )


def _now_us() -> int:
    return time.time_ns() // 1000


class TickerStream:
    """Refcounted `tickers.{symbol}` demand + merge + bus publication."""

    def __init__(
        self,
        *,
        bus: Bus,
        env: str,
        set_desired: Callable[[set[str]], None],
        parse_frame: Callable[[str], TickerDelta | None],
        topic_for: Callable[[str], str],
        is_listed: Callable[[str], bool],
        touch: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        event_window: Callable[[str, int], None] | None = None,
        grace_s: float = DEFAULT_GRACE_S,
        raw_sink: Callable[[TickerDelta], None] | None = None,
        writer: TickerWriter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._bus, self._env = bus, env
        self._set_desired = set_desired
        self._parse, self._topic_for, self._is_listed = parse_frame, topic_for, is_listed
        self._touch, self._clock, self._now_us = touch, clock, now_us
        self._demand = DemandTracker(clock, grace_s)
        self._rejects = RejectionLog("ticker", clock)
        #: #1892: clock/listing-relative plausibility (`ingestion.rejection.EventWindow`).
        self._window = event_window
        self._merger = TickerMerger()
        self._raw_sink, self._writer, self._sleep = raw_sink, writer, sleep
        self._latest: dict[str, TickerEvent] = {}
        self._phase: dict[str, str] = {}  # symbol -> warming | live | stale
        self._last_msg: dict[str, float] = {}
        self._writes: asyncio.Queue[TickerEvent] = asyncio.Queue(maxsize=WRITE_QUEUE_MAXSIZE)
        self._tasks: list[asyncio.Task[None]] = []
        self._health = bus.subscribe(
            "ticker-stream-health",
            TopicPattern(env=env, domain="health", detail="feed"),
            QueuePolicy.NEVER_DROP,
            maxsize=1024,
        )

    # ---- demand ---------------------------------------------------------
    def acquire(self, consumer: str, symbol: str) -> None:
        if not self._is_listed(symbol):  # crafted/unknown symbols never reach a topic
            raise UnknownSymbolError(symbol)
        self._demand.acquire(consumer, symbol)
        self.sync()

    def release(self, consumer: str, symbol: str) -> None:
        self._demand.release(consumer, symbol)
        self.sync()

    def sync(self) -> None:
        """Push the desired upstream set (live demand + inside-grace) to the socket."""
        wanted = self._demand.desired()
        self._set_desired({self._topic_for(s) for s in wanted})
        for gone in set(self._phase) - wanted:
            self._merger.invalidate(gone)
            for d in (self._latest, self._phase, self._last_msg):
                d.pop(gone, None)
        now = self._clock()
        for sym, at in self._last_msg.items():
            ws_topic_staleness_seconds.labels(topic=self._topic_for(sym)).set(now - at)

    async def prune_unlisted(self) -> list[str]:
        """#1913: drop + unsubscribe symbols that left the catalogue."""
        health = Topic(env=self._env, domain="health", detail="feed")

        async def publish(ev: FeedHealthEvent) -> None:
            await self._bus.publish(health, ev)

        return await prune_unlisted(
            self._demand, self._is_listed, self.sync, publish, self._topic_for, now_us=self._now_us
        )

    # ---- reads ----------------------------------------------------------
    def latest(self, symbol: str) -> TickerEvent | None:
        return self._latest.get(symbol)

    def phase(self, symbol: str) -> str | None:
        return self._phase.get(symbol)

    def is_stale(self, symbol: str) -> bool:
        return self._phase.get(symbol) == "stale"

    def is_listed(self, symbol: str) -> bool:
        return self._is_listed(symbol)

    # ---- frames ---------------------------------------------------------
    async def handle_frame(self, frame: str) -> None:
        try:
            delta = self._parse(frame)
            if delta is not None and self._window is not None:
                self._window(delta.symbol, delta.ts_event_us)
        except (ValueError, RecursionError) as exc:
            # Dropped whole: merged state keeps the last plausible values.
            self._rejects.record(exc)
            return
        if delta is None or delta.symbol not in self._demand.desired():
            return
        sym = delta.symbol
        self._touch(self._topic_for(sym))
        self._last_msg[sym] = self._clock()
        count_event("ticker", sym)
        if self._raw_sink is not None:
            self._raw_sink(delta)  # raw delta for the recorder, never the merged view
        was = self._phase.get(sym)
        event: TickerEvent | None = self._merger.apply(delta, ts_ingest_us=self._now_us())
        if event is None:
            if was is None or was == "stale":
                self._phase[sym] = "warming"
                await self._health_event(sym, "warming")
            return
        ingest_lag_seconds.labels(stream="ticker").set(
            max(0.0, (event.ts_ingest - event.ts_event) / 1e6)
        )
        self._latest[sym] = event
        self._phase[sym] = "live"
        if was != "live":
            await self._health_event(sym, "healthy")
        await self._bus.publish(
            Topic(env=self._env, domain="md", symbol=sym, detail="ticker"), event
        )
        self._enqueue_write(event)

    def _enqueue_write(self, event: TickerEvent) -> None:
        if self._writer is None:
            return
        if self._writes.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._writes.get_nowait()
            ticker_writes_dropped_total.inc()
        self._writes.put_nowait(event)

    async def _health_event(self, symbol: str, state: str) -> None:
        topic = Topic(env=self._env, domain="health", detail="feed")
        ev = feed_health(self._topic_for(symbol), state, 0.0, now_us=self._now_us())
        await self._bus.publish(topic, ev)

    # ---- feed health (reconnect / stale) ---------------------------------
    async def process_health(self, event: FeedHealthEvent) -> None:
        if event.state in ("resubscribing", "degraded"):
            # Never present pre-drop values as live: rebuild from the next push.
            self._merger.invalidate()
            for sym in [s for s, ph in self._phase.items() if ph != "warming"]:
                self._latest.pop(sym, None)
                self._phase[sym] = "warming"
                await self._health_event(sym, "reconnecting")
            return
        prefix = self._topic_for("")
        if event.state == "stale" and event.topic.startswith(prefix):
            sym = event.topic[len(prefix) :]
            if sym in self._phase:
                self._phase[sym] = "stale"  # next message republishes `healthy`

    async def _health_loop(self) -> None:
        while True:
            ev = await self._health.get()
            # Only upstream-origin events: our own `reconnecting`/`warming` are ignored.
            if isinstance(ev, FeedHealthEvent) and ev.state in (
                "resubscribing",
                "degraded",
                "stale",
            ):
                await self.process_health(ev)

    async def _sync_loop(self) -> None:
        while True:
            await self._sleep(1.0)
            self.sync()

    async def _write_loop(self) -> None:
        while True:
            event = await self._writes.get()
            try:
                if self._writer is not None:
                    await self._writer.write_ticker(event)
            except Exception:  # write-behind must never take ingest down
                get_logger(__name__).warning("ticker write-behind failed", symbol=event.symbol)

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        self._tasks = [
            spawn(self._health_loop(), name="ticker-health"),
            spawn(self._sync_loop(), name="ticker-sync"),
            spawn(self._write_loop(), name="ticker-write-behind"),
        ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._bus.unsubscribe(self._health)


__all__ = [
    "REQUIRED_FIELDS",
    "TickerMerger",
    "TickerStream",
    "TickerWriter",
    "UnknownSymbolError",
    "ticker_event",
    "uuid7",
]
