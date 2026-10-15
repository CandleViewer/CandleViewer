"""Production composition over the stub exchange: `app.wire_public_ws`, in its order.

`IngestionService` is started through `start(ctx)`, as the module supervisor starts it, and
owns everything: the instrument catalogue (attached as `wire_instrument_catalogue` attaches
it), the `ClockGuard` (as `wire_clock_offset` attaches it), the public WS `ConnectionManager`
(B13 chart via the factory), `TradeStream`, `BookStream` (supervised by `B14BookSupervisor`),
`TickerStream`, the per-topic frame router and the pump, all on one `Bus`. The stub exchange
is the socket factory and the REST transport of a real `BybitRestClient`.

Deviations from the composition root (keep in sync with SCENARIOS.md):

* Virtual clock, seeded RNG and the stub transport replace the real ones, through the seams
  the production classes expose (`clock=`, `now_us=`, `sleep=`, `rand=`, `transport=`, ...).
* Storage is outside the seam: `FlakyWriter` stands in for the hot-tier writers (s11's outage
  switch) and `_NullRepo` for the catalogue's Postgres repository. Not composed, as neither
  touches the feed path: `_wire_klines`' request-path kline service and
  `wire_instrument_catalogue`'s `instruments.*.updated` bus publisher.
* s08's signed client wires `on_signature_failure=ClockGuard.resync_after_signature_failure`
  although production has no signed-client composition yet (#1949 / #1911): s08 proves
  client + guard, not the app.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, TypeVar

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.bus.bus import Bus, Subscription
from candleviewer.bus.models import QueuePolicy
from candleviewer.domain.events import Instrument
from candleviewer.exchange.base.models import BookDelta, BookSnapshot, TickerEvent

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import RestClientConfig

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.instruments import make_instruments_info_fetcher

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.public_ws import frame_route, topic_kind

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rest import BybitRestClient

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame, recent_trades_fetcher, trade_topic
from candleviewer.ingestion.book_supervisor import B14BookSupervisor
from candleviewer.ingestion.clock import ClockGuard, rest_client_fetcher
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.metrics import ingest_enabled
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.rejection import EventWindow, corrected_now_us
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import GapEvent, TradeStream
from candleviewer.ingestion.watchdog import FeedHealthEvent, StalenessWatchdog
from candleviewer.observability.context import spawn
from candleviewer.orderbook_wiring import BookStream
from candleviewer.settings import FeedMode
from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ingestion._stub_exchange import StubExchange

#: The stub's REST base URL. Allow-listed host string only: `MockTransport`
#: answers in-process, nothing is ever dialled (network guard stays armed).
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
STUB_BASE_URL = "https://api.bybit.com"
T = TypeVar("T")
#: All `IngestionService.start(ctx)` reads is `ctx.settings.feed`: a non-synthetic feed, so
#: the E02-T12 replay generator stays off and the attached public stack is what starts.
LIVE_FEED_CTX: Any = SimpleNamespace(settings=SimpleNamespace(feed=FeedMode.LIVE))
#: `IngestionService.stop(grace_s)`: a real-time guard around the WS stop only.
STOP_GRACE_S = 5.0


@dataclass
class Observed:
    """The user-visible signals, in publish order (what SCR-152 / panels read)."""

    feed: list[FeedHealthEvent] = field(default_factory=list)
    book_status: list[BookStatus] = field(default_factory=list)
    book_events: list[BookSnapshot | BookDelta] = field(default_factory=list)
    gaps: list[GapEvent] = field(default_factory=list)
    tickers: list[TickerEvent] = field(default_factory=list)
    trades: list[Any] = field(default_factory=list)
    order: list[str] = field(default_factory=list)  # "status:desynced", "delta:42", ...


class FlakyWriter:
    """Hot-tier writer double: `down=True` models a QuestDB/Postgres outage."""

    def __init__(self) -> None:
        self.down = False
        self.persisted_trades: list[Any] = []
        self.persisted_tickers: list[Any] = []
        self.persisted_book_rows = 0
        self.failed_batches = 0

    def _check(self) -> None:
        if self.down:
            self.failed_batches += 1
            raise ConnectionError("hot tier unavailable")

    async def write_trades(self, events: Any) -> None:
        self._check()
        self.persisted_trades.extend(events)

    async def write_ticker(self, event: Any) -> None:
        self._check()
        self.persisted_tickers.append(event)

    async def write_book_deltas(self, rows: Any) -> None:
        self._check()
        self.persisted_book_rows += len(rows)

    async def write_book_snapshot(self, row: Any) -> None:
        self._check()
        self.persisted_book_rows += 1


class _NullRepo:
    """Instrument repository double (Postgres is out of this suite's seam)."""

    async def upsert_snapshot(self, rows: Any) -> None:
        return None

    async def record_version(self, row: Any, *, changed_fields: Any) -> None:
        return None

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> list[Any]:
        return []


class Rig:
    """One env's public ingestion stack wired to the stub exchange."""

    def __init__(
        self,
        *,
        seed: int,
        symbols: tuple[str, ...] = ("BTCUSDT",),
        conn_limit: int = 480,
    ) -> None:
        self.seed = seed
        self.clock = VirtualClock()
        self.rng = random.Random(seed)  # noqa: S311  (deterministic jitter)
        self.ex = StubExchange(self.clock, seed=seed)
        self.host_skew_s = 0.0  # market-data host clock skew (WSL sleep)
        self.bus = Bus()
        self.env = "live"
        self.symbols = symbols
        self.writer = FlakyWriter()
        self.seen = Observed()
        # `build_app_context`: the module; its health reads these clocks.
        self.svc = IngestionService(clock=self.clock, now_us=self.clock.now_us)
        # `adapter.public_rest_client(env)`: the default client and governor.
        config = RestClientConfig(base_url=STUB_BASE_URL)
        self.governor = TokenBucketGovernor(
            ip_budget_per_5s=config.ip_budget_per_5s,
            clock=self.clock,
            sleep=self.clock.sleep,  # 10018 IP hold (#1908) runs on virtual time
        )
        self.rest = BybitRestClient(
            config,
            governor=self.governor,
            transport=self.ex.transport,
            sleep=self.clock.sleep,
            random_fn=self.rng.random,
            wall_clock=self.host_wall_s,
        )
        # `wire_instrument_catalogue`: the catalogue gates every topic (E08-S03).
        self.instruments = InstrumentsRefreshScheduler(
            fetch_instruments_info=make_instruments_info_fetcher(self.rest),
            repository=_NullRepo(),
            now_us=self.clock.now_us,
            sleep=self.clock.sleep,
            random_fn=self.rng.random,
        )
        self.svc.attach_instruments(self.instruments)

        # ---- `app.wire_public_ws` --------------------------------------------------------
        self.watchdog = StalenessWatchdog(self.clock, lambda _e: None, kind_of=topic_kind)
        self.guard = ConnectionRateGuard(self.clock, limit=conn_limit)
        self.ws = ConnectionManager(
            self.ex.socket_factory,
            SubscriptionPlanner(),
            self.watchdog,
            ReconnectPolicy(rng=random.Random(seed + 1)),  # noqa: S311
            self.guard,
            self.svc.offer_frame,
            sleep=self.clock.sleep,
            bus=self.bus,
            env=self.env,
            clock=self.clock,
        )
        self.svc.attach_ws(self.ws)
        ingest_enabled.set(1.0)  # silent-death meta-alert keys on this (E08-T06)
        # `wire_clock_offset`: started and stopped with ingestion. The guard sees the
        # (skewable) host wall clock and the virtual monotonic clock.
        self.clock_guard = ClockGuard(
            rest_client_fetcher(self.rest, wall_clock=self.host_wall_s, monotonic=self.clock),
            clock=self.clock,
            sleep=self.clock.sleep,
            random_fn=self.rng.random,
            wall_ns=lambda: self.host_now_us() * 1_000,
            mono_ns=lambda: int(self.clock.now * 1_000_000_000),
        )
        self.svc.attach_clock(self.clock_guard)
        self.svc.attach_closer(self.rest.aclose)
        # Each stream owns a slice of the upstream topic set; the socket gets the union.
        self._demand: dict[str, set[str]] = {}
        # #1892/#1912: wall clock (not the monotonic demand clock) bounds event time,
        # shifted by ClockGuard's measured offset so the exchange clock is truth.
        window = EventWindow(
            corrected_now_us(self.clock_guard.offset_us, self.host_now_us), self._launch_us
        )
        self.trades = TradeStream(
            bus=self.bus,
            env=self.env,
            set_desired=lambda t: self._set_desired("trade", t),
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=self.is_listed,
            touch=self.watchdog.touch,
            fetch_recent=recent_trades_fetcher(self.rest.get_public),
            tick_size=self._tick_size,
            clock=self.clock,
            now_us=self.clock.now_us,
            event_window=window,
            writer=self.writer,
            write_sleep=self.clock.sleep,  # #1918 write-behind backoff on virtual time
            write_rand=self.rng.random,
        )
        self.svc.attach_trades(self.trades)
        self.book_supervisor = B14BookSupervisor()
        self.books = BookStream(
            bus=self.bus,
            env=self.env,
            set_desired=lambda t: self._set_desired("book", t),
            parse_frame=lambda f: parse_book_frame(f, self._tick_size),
            topic_for=book_topic,
            resubscribe=self.ws.resubscribe_topic,
            is_listed=self.is_listed,
            touch=self.watchdog.touch,
            clock=self.clock,
            now_us=self.clock.now_us,
            writer=self.writer,
            supervisor=self.book_supervisor,
            rand=self.rng.random,
            write_sleep=self.clock.sleep,
            sleep=self.clock.sleep,  # the SNAPSHOT_TIMEOUT tick on virtual time
        )
        self.svc.attach_books(self.books)
        self.tickers = TickerStream(
            bus=self.bus,
            env=self.env,
            set_desired=lambda t: self._set_desired("ticker", t),
            parse_frame=parse_ticker_frame,
            topic_for=ticker_topic,
            is_listed=self.is_listed,
            touch=self.watchdog.touch,
            clock=self.clock,
            now_us=self.clock.now_us,
            event_window=window,
            writer=self.writer,
            sleep=self.clock.sleep,
        )
        self.svc.attach_tickers(self.tickers)
        # #1916/#1905: per-topic dispatch lanes behind the pump; the pump touches
        # the watchdog on routing, so freshness reflects the venue.
        self.svc.attach_router(frame_route, self.watchdog.touch)
        # ---- end of `app.wire_public_ws` -------------------------------------------------

        self._ui: Subscription = self.bus.subscribe(
            "chaos-ui", f"{self.env}.*.*.*", QueuePolicy.NEVER_DROP, maxsize=1_000_000
        )

    # ---- composition-root callbacks (`app.wire_public_ws`) --------------------------
    def _instrument(self, symbol: str) -> Instrument | None:
        scheduler = self.svc.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        return snap.get(symbol) if snap is not None else None

    def is_listed(self, symbol: str) -> bool:
        """`_is_listed`: only catalogue symbols may become topics (E08-S03 security note)."""
        inst = self._instrument(symbol)
        return inst is not None and inst.status == "trading"

    def _tick_size(self, symbol: str) -> Decimal | None:
        inst = self._instrument(symbol)
        return None if inst is None else inst.tick_size

    def _launch_us(self, symbol: str) -> int | None:
        inst = self._instrument(symbol)
        return None if inst is None else int(inst.launch_time)

    def _set_desired(self, stream: str, topics: set[str]) -> None:
        self._demand[stream] = set(topics)
        self.ws.set_desired(set().union(*self._demand.values()))

    def host_now_us(self) -> int:
        """The host wall clock: venue time plus every injected host jump."""
        skew_s = self.host_skew_s + self.ex.host_skew_s
        return self.clock.now_us() + int(skew_s * 1_000_000)

    def host_wall_s(self) -> float:
        return self.host_now_us() / 1_000_000

    # ---- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        """Start ingestion as the module supervisor does, then the scenario's chart
        demand (book + tape) on every symbol."""
        await self.svc.start(LIVE_FEED_CTX)
        for sym in self.symbols:
            self.trades.acquire("chaos", sym)
            self.books.acquire("chaos", sym)
        await self.clock.settle()

    async def stop(self) -> None:
        await self.svc.stop(grace_s=STOP_GRACE_S)
        await self.clock.settle()  # `B14BookSupervisor.detach` stops each chart in a task

    # ---- observation -----------------------------------------------------------
    def observe(self) -> Observed:
        """Drain what a UI subscriber would have received since the last call."""
        while not self._ui.queue.empty():
            ev = self._ui.get_nowait()
            if isinstance(ev, BookStatus):
                self.seen.book_status.append(ev)
                self.seen.order.append(f"status:{ev.state}")
            elif isinstance(ev, BookDelta):
                self.seen.book_events.append(ev)
                self.seen.order.append(f"delta:{ev.update_id}")
            elif isinstance(ev, BookSnapshot):
                self.seen.book_events.append(ev)
                self.seen.order.append(f"snapshot:{ev.update_id}")
            elif isinstance(ev, GapEvent):
                self.seen.gaps.append(ev)
            elif isinstance(ev, FeedHealthEvent):
                self.seen.feed.append(ev)
                self.seen.order.append(f"feed:{ev.state}")
            elif isinstance(ev, TickerEvent):
                self.seen.tickers.append(ev)
            else:
                self.seen.trades.append(ev)
        return self.seen

    def book_phase(self, symbol: str = "BTCUSDT") -> BookPhase | None:
        return self.books.phase(symbol)

    def book_levels(self, symbol: str = "BTCUSDT") -> tuple[dict[Decimal, Decimal], ...]:
        view = self.books.view(symbol, 200)
        if view is None:
            return ({}, {})
        snap = view.snapshot
        return ({lv.price: lv.qty for lv in snap.bids}, {lv.price: lv.qty for lv in snap.asks})

    def health_report(self) -> str:
        """What `/readyz` reads: the ingestion module's own `health()`."""
        return str(self.svc.health().status)

    async def call(self, aw: Awaitable[T], *, within_s: float = 120.0) -> T:
        """Run a REST call to completion on virtual time (its retries sleep on it)."""

        async def _run() -> T:
            return await aw

        task = spawn(_run(), name="chaos-call")
        await self.clock.run_until(task.done, within_s=within_s, what="rest call")
        return task.result()


def metric(m: Any, **labels: str) -> float:
    """Current value of a prometheus child (counters/gauges on the default registry)."""
    child = m.labels(**labels) if labels else m
    return float(child._value.get())
