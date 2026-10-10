"""Exchange adapter ports (`docs/plan/24-internal-schemas.md` §14.1).

Verbatim transcription of the `MarketDataPort`/`TradingPort` protocol
signatures. Structural typing (`Protocol`, not `ABC`) is deliberate: a fake
in-memory adapter (`FakeExchange`, `exchange/base/fakes.py`) and the real
the exchange adapter (E08-T02+) both satisfy these protocols
without sharing a base class or importing each other (C-2.2).

`TradingPort` is declared here so its shape is fixed and reviewable now, but
it is **not implemented** in this ticket (E08-T01) — the concrete OMS-facing
implementation is E29's scope. `MarketDataPort` is `@runtime_checkable` so
`isinstance(adapter, MarketDataPort)` is a valid structural check (used by
the acceptance test and downstream consumers that want a cheap sanity check
before wiring a fake into a unit test).
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
    RiskLimitTier,
    TickerEvent,
    TradeEvent,
    TradingStopRequest,
    Wallet,
)

__all__ = ["MarketDataPort", "TradingPort"]


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


@runtime_checkable
class TradingPort(Protocol):
    """§14.1. Account-scoped order entry and reads. **Declared only** in
    this ticket (E08-T01 scope, ticket body "Out of scope") — building a
    conforming implementation, the exchange or otherwise, is E29's job. Declaring
    it now lets E29 be authored against a signature that has already been
    reviewed rather than inventing one under deadline."""

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
        self, account: AccountRef, symbol: Symbol | None = None
    ) -> Sequence[Order]: ...

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
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

    async def subscribe_private(self, account: AccountRef) -> AsyncIterator[PrivateEvent]: ...
