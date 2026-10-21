"""Domain models for the exchange.base module (M3).

`Trade` and `Ticker` are the normalised domain events named in C-2.3
("Ingestion converts exchange payloads into normalised domain events") —
exchange-neutral shapes with no exchange-specific field names, symbols, or
error codes (C-2.2). The synthetic feed generator (`candleviewer.ingestion`,
E02-T12) publishes these same shapes so downstream consumers (bus fan-out,
dashboards, E08's real exchange adapter) share one contract regardless of
which feed produced the event.

The rest of this module (E08-T01) is a verbatim transcription of
`docs/plan/24-internal-schemas.md` §2 (normalised market-data events), §14.1
(`ExchangeCapabilities`) and the request/response DTOs referenced by
`TradingPort` in §14.4. Nothing here is exchange-specific (C-2.2): field names
and types are the neutral vocabulary every module downstream of the adapter
consumes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from candleviewer.domain.events import Instrument, MarketEvent
from candleviewer.domain.primitives import (
    AccountId,
    Environment,
    Exchange,
    Notional,
    OrderId,
    OrderLinkId,
    Px,
    Qty,
    Side,
    Symbol,
    TsUs,
)

__all__ = [
    "AccountInfo",
    "AccountRef",
    "AmendOrderRequest",
    "BookDelta",
    "BookLevel",
    "BookSnapshot",
    "CancelOrderRequest",
    "ClosedPnl",
    "ExchangeCapabilities",
    "Execution",
    "FeeRate",
    "FundingEvent",
    "Instrument",
    "KlineEvent",
    "LiquidationEvent",
    "OpenInterestEvent",
    "Order",
    "OrderAck",
    "PlaceOrderRequest",
    "Position",
    "PrivateEvent",
    "RiskLimitTier",
    "Ticker",
    "TickerEvent",
    "Trade",
    "TradeEvent",
    "TradeSide",
    "TradingStopRequest",
    "Wallet",
]


class TradeSide(StrEnum):
    """Aggressor side of a trade print (E02-T12 synthetic feed shape)."""

    BUY = "buy"
    SELL = "sell"


class Trade(BaseModel):
    """A single normalised trade print (E02-T12 synthetic feed shape).

    `price`/`size` are `Decimal` (never `float`) per the coding standard for
    money/quantity fields. `ts` is the exchange/source event time, tz-aware
    UTC — never `datetime.now()`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    price: Decimal
    size: Decimal
    side: TradeSide
    ts: datetime


class Ticker(BaseModel):
    """A normalised best-bid/ask + last-price snapshot (E02-T12 synthetic
    feed shape)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    last_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    ts: datetime


class TradeEvent(MarketEvent):
    """The tape (§2.1). The exchange gives the aggressor side directly — no
    tick-rule reconstruction needed."""

    trade_id: str
    price: Px
    qty: Qty
    side: Side
    is_block_trade: bool
    price_ticks: int
    notional: Notional
    seq: int


class BookLevel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    price: Px
    qty: Qty
    price_ticks: int


class BookSnapshot(MarketEvent):
    """§2.2. Sent on subscribe and after any server-side reset."""

    depth: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    update_id: int
    cross_seq: int
    ts_match: TsUs
    reason: Literal["subscribe", "resync", "server_reset", "replay_seek"]


class BookDelta(MarketEvent):
    """§2.2. `prev_update_id` gap ⇒ resync (no exchange checksum exists)."""

    depth: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    update_id: int
    prev_update_id: int
    cross_seq: int
    ts_match: TsUs


class TickerEvent(MarketEvent):
    """§2.3. the exchange's linear ticker stream is delta-encoded at the wire, but
    the adapter always emits a fully-populated snapshot (`is_delta=False`)
    downstream so no consumer implements merge logic."""

    last_price: Px | None
    mark_price: Px | None
    index_price: Px | None
    bid1_price: Px | None
    bid1_qty: Qty | None
    ask1_price: Px | None
    ask1_qty: Qty | None
    open_interest: Qty | None
    open_interest_value: Notional | None
    turnover_24h: Notional | None
    volume_24h: Qty | None
    price_24h_pcnt: Decimal | None
    funding_rate: Decimal | None
    next_funding_time: TsUs | None
    is_delta: bool


class KlineEvent(MarketEvent):
    """§2.4. A cross-check/backfill source — bars are built from trades, not
    from this event. `confirmed=False` MUST NOT be treated as bar-closed."""

    interval: Literal["1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"]
    start: TsUs
    end: TsUs
    open: Px
    high: Px
    low: Px
    close: Px
    volume: Qty
    turnover: Notional
    confirmed: bool

    @model_validator(mode="after")
    def _ohlc_plausible(self) -> KlineEvent:
        """#1892: `0 < low <= open, close <= high`; volume/turnover `>= 0`, finite."""
        values = (self.open, self.high, self.low, self.close, self.volume, self.turnover)
        if not all(v.is_finite() for v in values):
            raise ValueError("kline carries a non-finite value")
        if self.low <= 0 or not self.low <= min(self.open, self.close):
            raise ValueError("kline low is not the bar minimum")
        if max(self.open, self.close) > self.high:
            raise ValueError("kline high is not the bar maximum")
        if self.volume < 0 or self.turnover < 0:
            raise ValueError("kline volume/turnover is negative")
        if self.end < self.start:
            raise ValueError("kline ends before it starts")
        return self


class LiquidationEvent(MarketEvent):
    """§2.5. `side` is the CLOSING order side; consumers outside the adapter
    must read `liquidated_side`, never `side` (lint-enforced at the source)."""

    price: Px
    qty: Qty
    side: Side
    liquidated_side: Literal["long", "short"]
    notional: Notional
    batch_index: int
    ts_estimated: bool


class OpenInterestEvent(MarketEvent):
    """§2.6. `open_interest` is base-coin denominated for linear;
    `open_interest_value` is already USD."""

    open_interest: Qty
    open_interest_value: Notional
    interval: Literal["tick", "5min", "15min", "30min", "1h", "4h", "1d"]
    origin: Literal["ws_ticker", "rest_history"]


class FundingEvent(MarketEvent):
    """§2.7."""

    funding_rate: Decimal
    funding_interval_min: int
    next_funding_time: TsUs
    settled: bool
    annualized_rate: Decimal


class RiskLimitTier(BaseModel):
    """§14.4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier_id: int
    risk_limit_value: Notional
    maintenance_margin_rate: Decimal
    initial_margin_rate: Decimal
    max_leverage: Decimal


class ExchangeCapabilities(BaseModel):
    """§14.1. **Data, never branching** (adapter rule 3, §14.2): consumers
    read fields off this record; they never test `exchange == "<venue>"` or
    `env == "demo"`. Constructed once per `(exchange, environment)` at
    adapter-instance startup — zero runtime cost thereafter (performance
    notes, ticket body)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange: Exchange
    environment: Environment
    supports_ws_order_entry: bool
    supports_native_oco: bool
    supports_native_iceberg: bool
    supports_native_twap: bool
    supports_native_chase: bool
    supports_native_trailing: bool
    supports_native_conditional: bool
    supports_attached_sl_tp: bool
    supports_batch_orders: bool
    supports_reduce_only: bool
    supports_post_only: bool
    supports_hedge_mode: bool
    supports_dead_mans_switch: bool
    max_batch_size: int
    max_ws_topics_per_request: int
    max_orders_per_symbol: int
    max_conditional_orders_per_symbol: int
    order_link_id_max_len: int
    order_rate_per_uid_per_s: dict[str, int]
    ip_rate_per_5s: int
    book_depths: tuple[int, ...]
    book_cadence_ms: dict[int, int]
    position_modes: tuple[str, ...]
    trigger_sources: tuple[str, ...]
    order_retention_days: int | None
    has_public_ws: bool
    trailing_stop_unit: Literal["price_distance"] = "price_distance"


class AccountRef(BaseModel):
    """§14.4. `key_ref` is an opaque handle into the key vault — NEVER the
    key itself (C-2.7, C-12.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    uid: str
    environment: Environment
    key_ref: str


class PlaceOrderRequest(BaseModel):
    """§14.4 / §8.9 exchange request mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account: AccountRef
    symbol: Symbol
    side: Side
    order_type: Literal["market", "limit"]
    qty: Qty
    price: Px | None = None
    time_in_force: Literal["gtc", "ioc", "fok", "post_only"] = "gtc"
    order_link_id: OrderLinkId
    reduce_only: bool = False
    close_on_trigger: bool = False
    position_idx: Literal[0, 1, 2] = 0
    trigger_price: Px | None = None
    trigger_by: Literal["last", "mark", "index"] | None = None
    trigger_direction: Literal["rise", "fall"] | None = None
    take_profit: Px | None = None
    stop_loss: Px | None = None
    tp_trigger_by: Literal["last", "mark", "index"] = "last"
    sl_trigger_by: Literal["last", "mark", "index"] = "mark"
    tpsl_mode: Literal["full", "partial"] = "full"


class AmendOrderRequest(BaseModel):
    """Amend an open order in place. Declared alongside `TradingPort`
    (§14.1) so E29 (OMS) is authored against a merged signature; the field
    set mirrors `PlaceOrderRequest`'s amendable subset per the exchange
    `POST /v5/order/amend`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account: AccountRef
    symbol: Symbol
    order_link_id: OrderLinkId
    exchange_order_id: str | None = None
    qty: Qty | None = None
    price: Px | None = None
    trigger_price: Px | None = None
    take_profit: Px | None = None
    stop_loss: Px | None = None


class CancelOrderRequest(BaseModel):
    """Cancel one order by client or exchange id (`POST /v5/order/cancel`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account: AccountRef
    symbol: Symbol
    order_link_id: OrderLinkId | None = None
    exchange_order_id: str | None = None


class TradingStopRequest(BaseModel):
    """§8.9: attach/replace native TP/SL/trailing on an open position via
    `POST /v5/position/trading-stop`. **Always writes both TP and SL sides**
    in one call (one-sided writes break the exchange's OCO pairing, §8.9 caveat)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account: AccountRef
    symbol: Symbol
    position_idx: Literal[0, 1, 2] = 0
    take_profit: Px | None = None
    stop_loss: Px | None = None
    trailing_distance: Px | None = None
    active_price: Px | None = None
    tp_trigger_by: Literal["last", "mark", "index"] = "last"
    sl_trigger_by: Literal["last", "mark", "index"] = "mark"
    tpsl_mode: Literal["full", "partial"] = "full"


class OrderAck(BaseModel):
    """§14.4. `exchange_ret_code`/`exchange_ret_msg` travel beside the internal `error_code` into
    the call's stored record, redacted (§8.6 code-only rule): an order route answers with the code
    and `retCode`, never the exchange's `retMsg`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    order_link_id: OrderLinkId
    exchange_order_id: str | None
    error_code: str | None = None
    exchange_ret_code: int | None = None
    exchange_ret_msg: str | None = None
    retryable: bool = False
    latency_ms: int
    transport: Literal["rest", "ws"]


class Order(BaseModel):
    """§8.2. Minimal shape for `TradingPort` reads (`open_orders`,
    `order_history`); the full OMS aggregate root (mutable, with amend/
    protection tracking) is owned by E29 and defined in
    `candleviewer.oms.models`, not here — this is deliberately a read-only
    subset so this ticket's port compiles without depending on the OMS
    module (M3 may not depend on M-oms per CONSTITUTION.md §3).
    **Deviation, noted in the PR**: §14.4 does not give `Order` a formal
    field list; this shape is the read-facing minimum implied by
    `TradingPort.open_orders`/`order_history`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: OrderId
    order_link_id: OrderLinkId
    exchange_order_id: str | None
    account_id: AccountId
    symbol: Symbol
    side: Side
    order_type: Literal["market", "limit"]
    qty: Qty
    price: Px | None
    state: str
    filled_qty: Qty
    leaves_qty: Qty
    avg_fill_price: Px | None
    created_at: TsUs
    terminal_at: TsUs | None


class Execution(BaseModel):
    """§8.2 immutable fill record. **Deviation, noted in the PR**: read-only
    subset for `TradingPort.executions`; the full record lives with the OMS."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exec_id: str
    order_id: OrderId
    order_link_id: OrderLinkId
    account_id: AccountId
    symbol: Symbol
    side: Side
    price: Px
    qty: Qty
    fee: Notional
    fee_currency: str
    is_maker: bool
    closed_pnl: Notional | None
    ts_exec: TsUs
    ts_ingest: TsUs
    seq: int


class Position(BaseModel):
    """§8.2. **Deviation, noted in the PR**: read-only subset for
    `TradingPort.positions`; the OMS owns the mutable aggregate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    symbol: Symbol
    position_idx: Literal[0, 1, 2]
    side: Side | None
    qty: Qty
    avg_entry_price: Px | None
    mark_price: Px | None
    liq_price: Px | None
    leverage: Decimal
    unrealised_pnl: Notional
    cum_realised_pnl: Notional
    take_profit: Px | None
    stop_loss: Px | None
    trailing_stop_distance: Px | None
    updated_at: TsUs


class ClosedPnl(BaseModel):
    """§14.4 `TradingPort.closed_pnl`. **Deviation, noted in the PR**: no
    formal field list is given in §14.4; this mirrors the exchange's
    `GET /v5/position/closed-pnl` response shape at the neutral-vocabulary
    level (no `retCode`/camelCase, C-2.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    symbol: Symbol
    order_id: OrderId
    side: Side
    qty: Qty
    avg_entry_price: Px
    avg_exit_price: Px
    closed_pnl: Notional
    leverage: Decimal
    opened_at: TsUs
    closed_at: TsUs


class Wallet(BaseModel):
    """§14.4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    coin: str = "USDT"
    equity: Notional
    wallet_balance: Notional
    available_to_withdraw: Notional
    available_margin: Notional
    used_margin: Notional
    unrealised_pnl: Notional
    cum_realised_pnl: Notional
    account_im_rate: Decimal
    account_mm_rate: Decimal
    updated_at: TsUs


class FeeRate(BaseModel):
    """§14.4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: Symbol
    maker: Decimal
    taker: Decimal
    fetched_at: TsUs
    estimated: bool = False


class AccountInfo(BaseModel):
    """§14.4 `TradingPort.account_info`. **Deviation, noted in the PR**: no
    formal field list is given; this is the neutral-vocabulary minimum
    (margin mode, position mode) an OMS needs before placing an order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    uid: str
    margin_mode: Literal["regular", "portfolio"]
    position_mode: Literal["one_way", "hedge"]
    unified_margin: bool


class PrivateEvent(BaseModel):
    """§14.4. `payload` carries one of the read-facing DTOs above rather
    than the OMS's mutable aggregates (see `Order`/`Position` deviation
    notes)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["order", "execution", "position", "wallet"]
    account_id: AccountId
    payload: Order | Execution | Position | Wallet
    ts_event: TsUs
    ts_ingest: TsUs
    seq: int
