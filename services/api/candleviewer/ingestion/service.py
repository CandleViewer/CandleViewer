"""Lifecycle contract for the ingestion module (M6).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. The module
starts the *synthetic* feed (`CV_FEED=synthetic`, E02-T12) and whatever E08
exchange components the composition root attached: the instrument catalogue,
the clock guard, the public WS and its streams.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from candleviewer.exchange.base import Ticker, Trade
from candleviewer.exchange.base.frame_guard import FrameRejectedError, json_depth_exceeds
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.ingestion.connection import PHASE_OPEN, ConnectionManager
from candleviewer.ingestion.dispatch import FrameRoute, LaneSet
from candleviewer.ingestion.instruments import utc_now_us
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_read import KlineReadService
from candleviewer.ingestion.rejection import RejectionLog
from candleviewer.ingestion.synthetic_feed import (
    SyntheticFeedGenerator,
    SyntheticFeedMetrics,
    load_sample_records,
)
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.observability.context import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.observability.latency import StageRecorder
from candleviewer.settings import FeedMode

if TYPE_CHECKING:
    from candleviewer.app import AppContext

_QUEUE_MAXSIZE = 256
#: E08-T04: bounded raw-frame buffer between the WS reader and parsers (C-2.18).
#: Overflow policy: drop-newest and count (`ws_frames_dropped`); the
#: staleness watchdog recycles the socket if consumers fall behind for long.
WS_FRAME_QUEUE_MAXSIZE = 4096
#: #1889: this many consecutive frames failing inside the pump trip a resync.
PUMP_BREAKER_TRIPS = 32
#: #1919: health stays DEGRADED this long after a pump breaker trip.
PUMP_BREAKER_WINDOW_S = 30.0
#: #1919: WS may be non-open this long (reconnect backoff) before health degrades.
WS_GRACE_S = 5.0


class HealthReason(StrEnum):
    """#1919: stable, enumerable `HealthReport.detail` tokens (24-internal-schemas.md)."""

    WS_NOT_OPEN = "ws_not_open"
    BOOK_OUT_OF_LIVE = "book_out_of_live"
    TRADE_GAP_UNRECOVERED = "trade_gap_unrecovered"
    CATALOGUE_STALE = "catalogue_stale"
    PUMP_BREAKER_OPEN = "pump_breaker_open"


class BookSink(Protocol):
    """E08-S05 reconstructed-book wiring (composition root; ingestion must not
    import the `book` module, CONSTITUTION 3)."""

    async def handle_frame(self, frame: str) -> None: ...
    async def invalidate(self, reason: str) -> None: ...
    async def invalidate_symbol(self, symbol: str, reason: str) -> None: ...
    def view(self, symbol: str, depth: int) -> Any: ...
    def is_listed(self, symbol: str) -> bool: ...
    def out_of_live(self, slo_s: float = ...) -> tuple[str, ...]: ...
    def acquire(self, consumer: str, symbol: str) -> None: ...
    def release(self, consumer: str, symbol: str) -> None: ...
    async def prune_unlisted(self) -> list[str]: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class IngestionService:
    """M6 `ingestion` module lifecycle: the synthetic feed (E02-T12) and the attached E08
    exchange components."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = utc_now_us,
        ws_grace_s: float = WS_GRACE_S,
        book_slo_s: float | None = None,
    ) -> None:
        self._clock, self._now_us = clock, now_us
        self._ws_grace_s, self._book_slo_s = ws_grace_s, book_slo_s
        self._last_pump_trip: float | None = None
        self._started = False
        self.queue: asyncio.Queue[Trade | Ticker] | None = None
        self._generator: SyntheticFeedGenerator | None = None
        #: E08-S01-2: the instrument catalogue scheduler, attached by the
        #: composition root only when a real exchange + Postgres are wired.
        self.instruments: InstrumentsRefreshScheduler | None = None
        #: E08-T04: public WS connection, attached only when
        #: `ingestion_ws_enabled` is on (composition root, `create_app`).
        self.ws: ConnectionManager | None = None
        self.ws_frames: asyncio.Queue[str] = asyncio.Queue(maxsize=WS_FRAME_QUEUE_MAXSIZE)
        self.ws_frames_dropped = 0
        #: E04-T06: stage-latency recorder + exchange clock-offset provider
        #: (ClockGuard's offset in ms once E08 wires it; None = unmeasured).
        self.latency: StageRecorder | None = None
        self.clock_offset_ms: Callable[[], int | None] = lambda: 0
        self.clock: ClockGuard | None = None
        self._closers: list[Callable[[], Awaitable[None]]] = []
        #: E08-S03: ticker demand/merge/publish, attached with the public WS.
        self.tickers: TickerStream | None = None
        self.klines: KlineReadService | None = None  # E12-S05, set by the composition root
        #: E08-S04: trade tape, attached with the public WS.
        self.trades: TradeStream | None = None
        #: E08-S05: reconstructed L2 book, attached with the public WS.
        self.books: BookSink | None = None
        self._pump: asyncio.Task[None] | None = None
        self._pump_rejects = RejectionLog("pump")
        self.pump_breaker_trips = 0
        self._route: Callable[[str], tuple[str, str, str] | None] | None = None
        self._touch: Callable[[str], None] | None = None
        self.lanes: LaneSet | None = None

    def attach_latency(
        self, recorder: StageRecorder, clock_offset_ms: Callable[[], int | None] | None = None
    ) -> None:
        """Wire the per-stage latency recorder into the publish path."""
        self.latency = recorder
        if clock_offset_ms is not None:
            self.clock_offset_ms = clock_offset_ms
        if self.ws is not None:
            self.ws.attach_latency(recorder, self._ws_clock_offset_ms)

    def attach_clock(self, guard: ClockGuard) -> None:
        """E04-T06: ClockGuard's measured exchange-local offset (REST
        `/v5/market/time`) feeds every `on_event`/`record` call."""
        self.clock = guard
        self.clock_offset_ms = guard.offset_ms_or_none

    def attach_closer(self, closer: Callable[[], Awaitable[None]]) -> None:
        """Resource (e.g. the clock REST client) to close on `stop()`."""
        self._closers.append(closer)

    def _ws_clock_offset_ms(self) -> int | None:
        # Real exchange frames: unmeasured offset => exchange stage unavailable.
        return self.clock.offset_ms_or_none() if self.clock is not None else None

    def offer_frame(self, frame: str) -> None:
        """Reader callback: never blocks the read loop (drop-newest on full)."""
        try:
            self.ws_frames.put_nowait(frame)
        except asyncio.QueueFull:
            self.ws_frames_dropped += 1
            if self.trades is not None:  # a lost frame may hold prints: never hide it
                self.trades.mark_gap("frame_loss")
            if self.books is not None:  # a lost delta is a sequence gap: resync, never patch
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    return
                spawn(self.books.invalidate("frame_loss"), name="book-frame-loss")

    def attach_ws(self, manager: ConnectionManager) -> None:
        """Hand this module ownership of the public WS connection lifecycle."""
        self.ws = manager

    def attach_klines(self, service: KlineReadService, backfill: KlineBackfillService) -> None:
        """E12-S05: kline read path; the backfill's tracked jobs are cancelled on stop."""
        self.klines = service
        # First: cancel backfill jobs before the shared REST client they page through closes.
        self._closers.insert(0, backfill.aclose)

    def attach_tickers(self, stream: TickerStream) -> None:
        self.tickers = stream

    def attach_trades(self, stream: TradeStream) -> None:
        self.trades = stream

    def attach_books(self, stream: BookSink) -> None:
        self.books = stream

    def attach_router(
        self,
        route: Callable[[str], tuple[str, str, str] | None],
        touch: Callable[[str], None],
    ) -> None:
        """#1916: venue frame router (`(topic, kind, symbol)`) + watchdog touch.
        With a router each topic gets its own dispatch lane; without one every
        frame shares the fallback lane (still off the pump task)."""
        self._route, self._touch = route, touch

    async def _pump_frames(self) -> None:
        """Route raw frames into per-topic dispatch lanes (#1916, #1905).

        The pump itself never awaits a stream, a bus subscriber or REST: it
        rejects over-deep frames, touches the watchdog (freshness reflects the
        venue, not a local consumer), and hands the frame to its topic's lane
        (`ingestion.dispatch`), whose worker applies it. The lanes are owned
        by this task: cancelling the pump cancels and awaits every worker
        (queued frames are discarded; streams resync on restart).

        Must never die (#1889): failures are per frame, inside the lanes;
        `PUMP_BREAKER_TRIPS` consecutive failures in one lane trip a resync."""
        lanes = self.lanes = LaneSet(
            self._dispatch,
            self._resync_route,
            self._trip_breaker,
            lambda: PUMP_BREAKER_TRIPS,
        )
        try:
            while True:
                frame = await self.ws_frames.get()
                if json_depth_exceeds(frame):  # once per frame, before any parser
                    self._pump_rejects.record(
                        FrameRejectedError("depth_limit", "frame nests too deep")
                    )
                    continue
                route = self._route_of(frame)
                if route is not None and self._touch is not None:
                    self._touch(route.topic)
                lanes.lane_for(route).offer(frame)
        finally:
            await lanes.aclose()

    def _route_of(self, frame: str) -> FrameRoute | None:
        if self._route is None:
            return None
        try:
            key = self._route(frame)
        except Exception:  # routing is best effort; the lane parser validates
            return None
        return None if key is None else FrameRoute(*key)

    async def _resync_route(self, route: FrameRoute) -> None:
        """A lane dropped frames: resync exactly that symbol's stream."""
        await self._resync_symbol(route, "dispatch_overflow")

    async def _resync_symbol(self, route: FrameRoute, reason: str) -> None:
        if route.stream == "trade" and self.trades is not None:
            self.trades.mark_gap(reason, route.symbol)
        elif route.stream == "book" and self.books is not None:
            await self.books.invalidate_symbol(route.symbol, reason)
        # ticker: snapshot+delta merge, the next full snapshot heals it

    async def _dispatch(self, frame: str) -> bool:
        ok = True
        for stream in (self.trades, self.tickers, self.books):
            if stream is None:
                continue
            try:
                await stream.handle_frame(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # per-frame isolation is the contract (#1889)
                self._pump_rejects.record(exc)
                ok = False
        return ok

    async def _trip_breaker(self, route: FrameRoute | None) -> None:
        """A lane failed `PUMP_BREAKER_TRIPS` frames in a row. Resync only that
        lane's symbol (#1916 blast radius); the unrouted fallback lane cannot
        name one, so it resyncs every symbol as before."""
        self.pump_breaker_trips += 1
        self._last_pump_trip = self._clock()
        if route is None:
            await self._resync_all("pump_breaker")
            return
        try:
            await self._resync_symbol(route, "pump_breaker")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the breaker itself must not kill the lane
            self._pump_rejects.record(exc)

    async def _resync_all(self, reason: str) -> None:
        if self.trades is not None:
            self.trades.mark_gap(reason)
        if self.books is not None:
            try:
                await self.books.invalidate(reason)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the breaker itself must not kill the pump
                self._pump_rejects.record(exc)

    async def prune_unlisted(self) -> None:
        """#1913: after each catalogue swap, every stream drops (and
        unsubscribes) symbols that are no longer `trading`."""
        for stream in (self.trades, self.tickers, self.books):
            if stream is not None:
                await stream.prune_unlisted()

    def attach_instruments(self, scheduler: InstrumentsRefreshScheduler) -> None:
        """Hand this module ownership of the catalogue scheduler's lifecycle."""
        self.instruments = scheduler

    async def start(self, ctx: AppContext) -> None:
        """Start the module.

        `CV_FEED=synthetic` (the dev/CI default) starts the replay generator
        against a bounded queue; `CV_FEED=live` starts no generator (`Settings`
        refuses that mode without credentials, fail-fast). Either way the
        components the composition root attached start next: the instrument
        catalogue (with `CV_FEED=live` or the public WS on the real backend;
        its startup fetch is bounded, so boot never waits long on the exchange,
        #2599), the clock guard, and the public WS with its streams
        (`ingestion_ws_enabled`).
        """
        settings = ctx.settings
        if settings.feed is FeedMode.SYNTHETIC:
            self.queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
            records = load_sample_records(Path(settings.feed_sample_path))
            metrics = SyntheticFeedMetrics(ctx.metrics)
            self._generator = SyntheticFeedGenerator(
                records=records,
                queue=self.queue,
                metrics=metrics,
                rate_hz=settings.feed_rate_hz,
                latency=self.latency,
                clock_offset_ms=lambda: self.clock_offset_ms(),
            )
            await self._generator.start()
        if self.instruments is not None:
            self.instruments.add_listener(self.prune_unlisted)
            await self.instruments.start()
        if self.clock is not None:
            await self.clock.start()
        if self.ws is not None:
            await self.ws.start()
        if self.tickers is not None:
            await self.tickers.start()
        if self.trades is not None:
            await self.trades.start()
        if self.books is not None:
            await self.books.start()
        if self.tickers is not None or self.trades is not None or self.books is not None:
            self._pump = spawn(self._pump_frames(), name="ws-frame-pump")
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. The closers (REST clients,
        pools) and the generator are released even if a stop step raises, each
        best effort: one that raises is logged and the rest still run (#2599)."""
        try:
            await self._stop_components(grace_s)
        finally:
            await self._release()

    async def _release(self) -> None:
        releases, self._closers = self._closers, []
        generator, self._generator = self._generator, None
        if generator is not None:
            releases.append(generator.stop)
        try:
            for release in releases:
                try:
                    await release()
                except Exception:  # never skips the rest; a CancelledError still propagates
                    get_logger(__name__).exception(
                        "ingestion_release_failed",
                        resource=getattr(release, "__qualname__", type(release).__name__),
                    )
        finally:
            self._started = False

    async def _stop_components(self, grace_s: float) -> None:
        pump, self._pump = self._pump, None
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        if self.tickers is not None:
            await self.tickers.stop()
        if self.trades is not None:
            await self.trades.stop()
        if self.books is not None:
            await self.books.stop()
        if self.ws is not None:
            async with asyncio.timeout(grace_s):
                await self.ws.stop()
        if self.clock is not None:
            await self.clock.stop()
        if self.instruments is not None:  # before the closers: it uses their client and pool
            await self.instruments.stop(grace_s)

    def degraded_reasons(self) -> list[HealthReason]:
        """#1919: reasons the feed is impaired, from published plain signals only
        (C-2.20: no interpreter is queried)."""
        now = self._clock()
        reasons: list[HealthReason] = []
        ws = self.ws
        if (
            ws is not None
            and ws.state() != PHASE_OPEN
            and now - ws.phase_since() > self._ws_grace_s
        ):
            reasons.append(HealthReason.WS_NOT_OPEN)
        if self.books is not None:
            slo = {} if self._book_slo_s is None else {"slo_s": self._book_slo_s}
            if self.books.out_of_live(**slo):
                reasons.append(HealthReason.BOOK_OUT_OF_LIVE)
        trades = self.trades  # #2715: an open window, or one that closed unrecovered
        if trades is not None and (trades.open_gaps() or trades.unrecovered_gaps()):
            reasons.append(HealthReason.TRADE_GAP_UNRECOVERED)
        if self.instruments is not None and self.instruments.cache.is_stale(now_us=self._now_us()):
            reasons.append(HealthReason.CATALOGUE_STALE)
        trip = self._last_pump_trip
        if trip is not None and now - trip <= PUMP_BREAKER_WINDOW_S:
            reasons.append(HealthReason.PUMP_BREAKER_OPEN)
        return reasons

    def health(self) -> HealthReport:
        """`stopped` before start/after stop; `degraded` (never down) with a stable
        reason list in `detail` while the feed is impaired (#1919); else `ok`."""
        if not self._started:
            return HealthReport(module="ingestion", status=HealthStatus.STOPPED, detail="")
        reasons = self.degraded_reasons()
        status = HealthStatus.DEGRADED if reasons else HealthStatus.OK
        return HealthReport(
            module="ingestion", status=status, detail=",".join(r.value for r in reasons)
        )
