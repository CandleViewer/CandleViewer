"""Exchange adapter ports (`docs/plan/24-internal-schemas.md` §14.1).

Verbatim transcription of the `MarketDataPort`/`TradingPort` protocol
signatures. Structural typing (`Protocol`, not `ABC`) is deliberate: a fake
in-memory adapter (`FakeExchange`, `exchange/base/fakes.py`) and the real
the exchange adapter (E08-T02+) both satisfy these protocols
without sharing a base class or importing each other (C-2.2).

`TradingPort` was declared by E08-T01 so its shape was fixed before the OMS;
G-8 (#2877, E29-X01) implements it in the exchange adapter's package and in
memory (`FakeTradingPort`, `exchange/base/fakes.py`), and G-8b (#3963) its
private stream (24 §14.2 rule 13). Both ports are
`@runtime_checkable`, so `isinstance(adapter, MarketDataPort)` is a valid
structural check (used by the acceptance test and downstream consumers that
want a cheap sanity check before wiring a fake into a unit test).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import OrderLinkId, Symbol, TsUs

from .models import (
    AccountInfo,
    AccountRef,
    AmendOrderRequest,
    BookDelta,
    BookSnapshot,
    CancelOrderRequest,
    ClosedPnl,
    ExchangeCapabilities,
    Execution,
    FeeRate,
    FundingEvent,
    KlineEvent,
    LiquidationEvent,
    OpenInterestEvent,
    Order,
    OrderAck,
    PlaceOrderRequest,
    Position,
    PrivateEvent,
    PrivateStreamStatus,
    RateHeadroom,
    RateLane,
    RiskLimitTier,
    TickerEvent,
    TradeEvent,
    TradingStopRequest,
    Wallet,
)

__all__ = ["MarketDataPort", "PrivateStream", "RateHeadroomPort", "TradingPort"]


@runtime_checkable
class MarketDataPort(Protocol):
    """§14.1. Public market data: instrument metadata, live subscriptions and
    REST history/backfill reads. No account/credential concept — this port
    is safe to construct with no key material at all."""

    async def instruments(self) -> Sequence[Instrument]: ...

    async def instrument(self, symbol: Symbol) -> Instrument: ...

    async def subscribe_trades(self, symbols: Sequence[Symbol]) -> AsyncIterator[TradeEvent]: ...

    async def subscribe_book(
        self, symbols: Sequence[Symbol], depth: int
    ) -> AsyncIterator[BookSnapshot | BookDelta]: ...

    async def subscribe_ticker(self, symbols: Sequence[Symbol]) -> AsyncIterator[TickerEvent]: ...

    async def subscribe_klines(
        self, symbols: Sequence[Symbol], interval: str
    ) -> AsyncIterator[KlineEvent]: ...

    async def subscribe_liquidations(
        self, symbols: Sequence[Symbol]
    ) -> AsyncIterator[LiquidationEvent]: ...

    async def fetch_klines(
        self,
        symbol: Symbol,
        interval: str,
        start: TsUs,
        end: TsUs,
        limit: int = 1000,
    ) -> Sequence[KlineEvent]: ...

    async def fetch_recent_trades(
        self, symbol: Symbol, limit: int = 1000
    ) -> Sequence[TradeEvent]: ...

    async def fetch_orderbook(self, symbol: Symbol, depth: int = 200) -> BookSnapshot: ...

    async def fetch_open_interest(
        self, symbol: Symbol, interval: str, start: TsUs, end: TsUs
    ) -> Sequence[OpenInterestEvent]: ...

    async def fetch_funding_history(
        self, symbol: Symbol, start: TsUs, end: TsUs
    ) -> Sequence[FundingEvent]: ...

    async def fetch_risk_limits(self, symbol: Symbol) -> Sequence[RiskLimitTier]: ...

    async def server_time_us(self) -> TsUs: ...


class StreamForTopic(Protocol):
    """E16-T04: normalise a venue feed topic (as carried by `FeedHealthEvent.topic`) to
    `(symbol | None, stream_kind names)`. `symbol=None` means "every symbol" (a socket-wide
    event, topic `*`); an unknown topic maps to no streams. Implemented by each adapter
    so venue vocabulary never leaves the adapter (C-2.2)."""

    def __call__(self, topic: str) -> tuple[str | None, tuple[str, ...]]: ...


class PrivateStream(Protocol):
    """What `TradingPort.subscribe_private` returns (24 §14.1, §14.2 rule 13): the account's
    events and statuses in arrival order, ending after a `closed` status. It raises nothing once
    returned; the consumer closes it (`contextlib.aclosing`), which closes its socket."""

    def __aiter__(self) -> PrivateStream: ...

    async def __anext__(self) -> PrivateEvent | PrivateStreamStatus: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class TradingPort(Protocol):
    """§14.1. Account-scoped order entry and reads, every call on the account's own
    environment (C-2.11). The id filters of `open_orders` and `order_history` are
    keyword-only (#846 ruling Q5, §8.5): an implementation sends them and filters the
    rows again itself, and an `ext-` key never goes on the wire (§14.2 rule 11)."""

    capabilities: ExchangeCapabilities

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck: ...

    async def place_batch(self, reqs: Sequence[PlaceOrderRequest]) -> Sequence[OrderAck]: ...

    async def amend_order(self, req: AmendOrderRequest) -> OrderAck: ...

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck: ...

    async def cancel_all(
        self, account: AccountRef, symbol: Symbol | None
    ) -> Sequence[OrderAck]: ...

    async def set_trading_stop(self, req: TradingStopRequest) -> OrderAck: ...

    async def set_leverage(
        self, account: AccountRef, symbol: Symbol, leverage: Decimal
    ) -> None: ...

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]: ...

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        exchange_order_id: str | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]: ...

    async def positions(self, account: AccountRef) -> Sequence[Position]: ...

    async def executions(
        self, account: AccountRef, start: TsUs, end: TsUs
    ) -> Sequence[Execution]: ...

    async def closed_pnl(
        self, account: AccountRef, start: TsUs, end: TsUs
    ) -> Sequence[ClosedPnl]: ...

    async def wallet(self, account: AccountRef) -> Wallet: ...

    async def fee_rate(self, account: AccountRef, symbol: Symbol) -> FeeRate: ...

    async def account_info(self, account: AccountRef) -> AccountInfo: ...

    async def subscribe_private(self, account: AccountRef) -> PrivateStream: ...


@runtime_checkable
class RateHeadroomPort(Protocol):
    """§14.1, beside `TradingPort` and not part of it: the local rate budget of an account's lane,
    read without taking a token or sending anything (#2877 ruling 4). It reads no exchange, so
    it is no `TradingPort` call; the OMS's own `RateHeadroom` port binds to it (E29-T04), so B1's
    `rate` verdict needs no governor of its own (C-2.2), until E34-T02's `reserve()`."""

    def headroom(self, account: AccountRef, lane: RateLane) -> RateHeadroom: ...
