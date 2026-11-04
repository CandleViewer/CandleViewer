"""E29-Q03 (#977): a synthetic ticker stream for the dev fixture stack.

On `CV_FEED=synthetic` with no public WS the ingestion module has no ticker stream, so the order
path has no reference price and answers every market order 503 `exchange_unavailable`. With the
account fixture on, `candleviewer.account_fixture_wiring.attach_fixture_tickers` calls
`wiring.attach_tickers`, which checks the handle is this package's door and calls `attach` here:
the ingestion module gets a `SyntheticTickerStream`, which reads the synthetic feed's queue (the
generator's `Ticker` records) and keeps, per symbol, the last price, the bid and ask and their mid
as the mark and index price, restamped on receipt, each event's `source` being `synthetic`.

It answers nothing until the fixture's handle is armed, which only the boot guard does
(`FixtureDoor.arm`). It takes no venue frame, opens no socket, holds its own bus, so no consumer
of the process bus sees a synthetic event, and writes no row. Every log line it writes carries
`source="synthetic"`, and its topic names start with `synthetic.`. Like the rest of `cvdev` it
ships in no wheel, sdist or image.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Final, Protocol

import structlog

from candleviewer.account_fixture_wiring import AccountFixtureRefused
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base import Ticker, Trade
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.base.ticker_delta import TickerDelta
from candleviewer.ingestion.service import PUMP_YIELD_EVERY, IngestionService
from candleviewer.ingestion.ticker_stream import TickerStream, ticker_event
from candleviewer.observability.context import spawn
from candleviewer.settings import FeedMode, Settings

#: The marker on every log line and topic name of this stream.
SOURCE: Final = "synthetic"  # also every event's `MarketEvent.source` (24 §1.4)
TOPIC_PREFIX: Final = "synthetic.tickers."
#: A symbol with no synthetic tick for this long is stale, so it prices no order.
STALE_AFTER_S: Final = 5.0
_REFUSED: Final = "CV_ACCOUNT_FIXTURE refuses boot: "
NOT_SYNTHETIC: Final = _REFUSED + "the synthetic ticker runs on CV_FEED=synthetic, no public WS"
ALREADY_ATTACHED: Final = _REFUSED + "the synthetic ticker never replaces a ticker stream"

FeedQueue = asyncio.Queue[Trade | Ticker]


class Door(Protocol):
    """The fixture's door (`wiring.FixtureDoor`) as this stream reads it: armed or not."""

    @property
    def armed(self) -> object | None: ...


def _log() -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(__name__)
    return logger.bind(source=SOURCE)


def _no_upstream(_topics: set[str]) -> None:
    """There is no venue socket to subscribe on."""


def _no_frame(_frame: str) -> TickerDelta | None:
    """There is no venue frame to parse."""
    return None


def _now_us() -> int:
    return time.time_ns() // 1000


class SyntheticTickerStream(TickerStream):
    """A `TickerStream` whose reads come from the synthetic feed's queue, never from a venue."""

    def __init__(
        self,
        door: Door,
        queue_of: Callable[[], FeedQueue | None],
        *,
        env: str,
        monotonic: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
    ) -> None:
        self._door, self._queue_of = door, queue_of
        self._monotonic, self._stamp_us = monotonic, now_us
        self._seen: dict[str, tuple[TickerEvent, float]] = {}
        self._drain: asyncio.Task[None] | None = None
        super().__init__(
            bus=Bus(),  # its own: no subscriber of the process bus sees a synthetic event
            env=env,
            set_desired=_no_upstream,
            parse_frame=_no_frame,
            topic_for=lambda symbol: TOPIC_PREFIX + symbol,
            is_listed=lambda symbol: symbol in self._seen,
            touch=lambda _topic: None,
            clock=monotonic,
            now_us=now_us,
        )

    async def handle_frame(self, frame: str) -> None:
        """A venue frame is never taken: this stream reads the synthetic feed alone."""

    def offer(self, record: Trade | Ticker) -> None:
        """One record of the feed: a ticker with a bid and ask above zero, once the door is
        armed, becomes the symbol's reading; anything else is passed over."""
        if self._door.armed is None or not isinstance(record, Ticker):
            return
        bid, ask = record.bid_price, record.ask_price
        if not (_priced(bid) and _priced(ask) and _priced(record.last_price)) or ask < bid:
            return
        mid = (bid + ask) / 2
        stamp = self._stamp_us()
        state: dict[str, Decimal | int] = {
            "last_price": record.last_price,
            "bid1_price": bid,
            "ask1_price": ask,
            "mark_price": mid,
            "index_price": mid,
        }
        event = ticker_event(
            record.symbol, state, ts_event_us=stamp, ts_ingest_us=stamp, source=SOURCE
        )
        if record.symbol not in self._seen:
            _log().info("ingestion.synthetic_ticker_symbol", symbol=record.symbol)
        self._seen[record.symbol] = (event, self._monotonic())

    def latest(self, symbol: str) -> TickerEvent | None:
        seen = self._seen.get(symbol)
        return None if seen is None or self._door.armed is None else seen[0]

    def phase(self, symbol: str) -> str | None:
        if symbol not in self._seen:
            return None
        return "stale" if self.is_stale(symbol) else "live"

    def is_stale(self, symbol: str) -> bool:
        seen = self._seen.get(symbol)
        return seen is not None and self._monotonic() - seen[1] > STALE_AFTER_S

    async def start(self) -> None:
        await super().start()
        queue = self._queue_of()
        if self._door.armed is None or queue is None:
            reason = "fixture_not_armed" if self._door.armed is None else "no_synthetic_feed"
            _log().warning("ingestion.synthetic_ticker_idle", reason=reason)
            return
        self._drain = spawn(self._run(queue), name="synthetic-ticker")
        _log().warning(
            "ingestion.synthetic_ticker_started",
            detail="synthetic prices from the dev feed stand in for a venue ticker",
        )

    async def stop(self) -> None:
        drain, self._drain = self._drain, None
        if drain is not None:
            drain.cancel()
            await asyncio.gather(drain, return_exceptions=True)
        await super().stop()

    async def _run(self, queue: FeedQueue) -> None:
        """Every `PUMP_YIELD_EVERY` records it gives the loop a turn, as the WS pump does (#1893):
        `queue.get()` on a full queue never suspends, so a backlog would otherwise hold it."""
        since_yield = 0
        while True:
            if since_yield >= PUMP_YIELD_EVERY:
                since_yield = 0
                await asyncio.sleep(0)
            record = await queue.get()
            since_yield += 1
            try:
                self.offer(record)
            except Exception:  # one bad record never ends the drain; CancelledError is not caught
                _log().warning("ingestion.synthetic_ticker_record_refused")


def _priced(price: Decimal) -> bool:
    return price.is_finite() and price > 0


def attach(settings: Settings, door: Door, ingestion: IngestionService) -> None:
    """Hand `ingestion` the synthetic ticker stream on `door` (`wiring.attach_tickers` checked
    it is this package's). Re-checks the dev/test gate and the feed; refuses boot rather than
    replace a stream or run beside a public WS."""
    refusal = settings.account_fixture_refusal()
    if refusal is not None:
        raise AccountFixtureRefused(refusal)
    if settings.feed is not FeedMode.SYNTHETIC or settings.ingestion_ws_enabled:
        raise AccountFixtureRefused(NOT_SYNTHETIC)
    if ingestion.tickers is not None:
        raise AccountFixtureRefused(ALREADY_ATTACHED)
    ingestion.attach_tickers(
        SyntheticTickerStream(door, lambda: ingestion.queue, env=settings.environment.value)
    )
    _log().warning(
        "ingestion.synthetic_ticker_attached",
        environment=settings.environment.value,
        detail="the dev fixture stack prices orders from the synthetic feed once armed",
    )
