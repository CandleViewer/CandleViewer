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
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

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
    "ExchangeOrderId",
    "ExchangeRecord",
    "ExchangeRecordFields",
    "ExecType",
    "Execution",
    "FeeRate",
    "FeeRateValue",
    "FundingEvent",
    "Instrument",
    "KlineEvent",
    "LiquidationEvent",
    "OpenInterestEvent",
    "Order",
    "OrderAck",
    "OrderKind",
    "OrderLane",
    "PlaceOrderRequest",
    "Position",
    "PrivateEvent",
    "RateHeadroom",
    "RateLane",
    "RiskLimitTier",
    "Ticker",
    "TickerEvent",
    "Trade",
    "TradeEvent",
    "TradeSide",
    "TradingStopRequest",
    "Wallet",
]

type RateLane = Literal["critical", "entry", "poll"]
"""The rate lane of one exchange request (`20-architecture.md` §4.3, 24 §8.7): `critical` for
exits and stop writes, `entry` for new exposure and amends, `poll` for reads."""

type OrderLane = Literal["critical", "entry"]
"""The lanes a create or an amend may take: the OMS sets it by the order's effect (SR-E29-01)."""

type OrderKind = Literal[
    "order",
    "conditional",
    "take_profit",
    "stop_loss",
    "partial_take_profit",
    "partial_stop_loss",
    "trailing_stop",
    "mm_rate_close",
]
"""What an exchange order is: a plain order, a conditional order, or one of the take-profit,
stop-loss and trailing orders the exchange holds for a position."""

type ExecType = Literal[
    "trade", "funding", "adl_trade", "bust_trade", "settle", "session_settle_pnl"
]
"""What an execution is (24 §8.1's five, and `21-database-schema.md` §3.3.6's `SessionSettlePnl`,
which §8.1 does not list): a `trade` fills an order; the others are the venue's own (a funding
fee, auto-deleveraging, a takeover liquidation, a settlement) and fill none."""

ExchangeOrderId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
"""The exchange's own id of an order, never empty: every order and execution a read returns
carries it (24 §14.2 rule 11)."""

FeeRateValue = Annotated[Decimal, Field(max_digits=18, decimal_places=10)]
"""A fee rate as `21-database-schema.md` §3.3.6 stores it, numeric(18,10)."""


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
    notes, ticket body). Fields describe the venue (`20-architecture.md` §9
    rule 7): `supports_ws_order_entry` says what the exchange offers, not
    that a trade socket exists; v1 sends every order over REST (SR-040a)."""

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
    key itself (C-2.7, C-12.2): the string form of the `api_keys.id` of the
    account's active key (SR-E27-21). An adapter refuses any other shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    uid: str
    environment: Environment
    key_ref: str


class PlaceOrderRequest(BaseModel):
    """§14.4 / §8.9 exchange request mapping. `lane` is the rate lane the OMS
    chose by the order's effect (SR-E29-01, 24 §8.7)."""

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
    lane: OrderLane = "entry"


class AmendOrderRequest(BaseModel):
    """Amend an open order in place. Declared alongside `TradingPort`
    (§14.1) so E29 (OMS) is authored against a merged signature; the field
    set mirrors `PlaceOrderRequest`'s amendable subset per the exchange
    `POST /v5/order/amend`. An `ext-` order is amended by `exchange_order_id`
    alone (§14.2 rule 11); `lane` is chosen as on a create."""

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
    lane: OrderLane = "entry"


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


_DecimalText = Annotated[str, StringConstraints(pattern=r"^-?[0-9]+(\.[0-9]+)?$")]
_Code64 = Annotated[str, StringConstraints(max_length=64, pattern=r"^[A-Za-z0-9_]{1,64}$")]
_Text64 = Annotated[str, StringConstraints(max_length=64)]
_RestPath = Annotated[str, StringConstraints(max_length=64, pattern=r"^/[A-Za-z0-9/._-]*$")]
_WireName = Annotated[str, StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")]
_TriggerSource = Literal["LastPrice", "MarkPrice", "IndexPrice"]


class _Sparse(BaseModel):
    """A record whose unset fields are absent when dumped, never null: the contract types most
    of them non-nullable (`22-api-openapi.yaml`), so a dump validates against it as it is."""

    @model_serializer(mode="wrap")
    def _without_unset(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        dumped: dict[str, object] = handler(self)
        return {key: value for key, value in dumped.items() if value is not None}


class ExchangeRecordFields(_Sparse):
    """The allow-listed fields of one exchange request, response or push (SR-E29-08), field for
    field the contract's `ExchangeRecordFields` (`22-api-openapi.yaml`, a parity test pins it).
    An adapter keeps no other field: adding one is a contract change. Decimals are C6 text. A
    field the call did not carry is absent from a dump (`_Sparse`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_link_id: Annotated[str, StringConstraints(max_length=36)] | None = None
    exchange_order_id: _Text64 | None = None
    symbol: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2,20}USDT$")] | None = None
    side: Literal["buy", "sell"] | None = None
    order_type: Literal["market", "limit"] | None = None
    qty: _DecimalText | None = None
    price: _DecimalText | None = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    reduce_only: bool | None = None
    close_on_trigger: bool | None = None
    position_idx: Literal[0, 1, 2] | None = None
    trigger_price: _DecimalText | None = None
    trigger_by: _TriggerSource | None = None
    trigger_direction: Literal["rise", "fall"] | None = None
    take_profit: _DecimalText | None = None
    stop_loss: _DecimalText | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    trailing_stop: _DecimalText | None = None
    activation_price: _DecimalText | None = None
    tp_size: _DecimalText | None = None
    sl_size: _DecimalText | None = None
    tp_trigger_by: _TriggerSource | None = None
    sl_trigger_by: _TriggerSource | None = None
    category: Literal["linear"] | None = None
    order_filter: _Text64 | None = None
    leverage: _DecimalText | None = None
    order_status: _Code64 | None = None
    filled_qty: _DecimalText | None = None
    remaining_qty: _DecimalText | None = None
    avg_fill_price: _DecimalText | None = None
    reject_reason: _Code64 | None = None
    exec_id: _Text64 | None = None
    exec_qty: _DecimalText | None = None
    exec_price: _DecimalText | None = None
    fee: _DecimalText | None = None
    is_maker: bool | None = None


class ExchangeRecord(_Sparse):
    """One exchange call as the adapter records it (SR-E29-08, E29 model §6 item 1): the
    contract's `ExchangeCallRecord` without `event_id` and `at`, which the store adds. Built only
    from the request as it went on the wire and the parsed reply, never from headers, a
    signature, an `auth` frame or a URL query; the OMS stores it as it is and never reads into
    it (C-2.3). Its dump leaves out what is unset, as the contract requires (`_Sparse`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transport: Literal["rest", "ws_trade", "ws_private"]
    method: Literal["GET", "POST"] | None = None
    endpoint: _RestPath | None = None
    op: _WireName | None = None
    req_id: _Text64 | None = None
    topic: _WireName | None = None
    http_status: int | None = None
    ret_code: int | None = None
    ret_msg: Annotated[str, StringConstraints(max_length=2048)] | None = None
    latency_ms: Annotated[int, Field(ge=0)] | None = None
    request_redacted: ExchangeRecordFields | None = None
    response_redacted: ExchangeRecordFields | None = None


class OrderAck(BaseModel):
    """§14.4. `exchange_ret_code`/`exchange_ret_msg` travel beside the internal `error_code` into
    the call's stored record, redacted (§8.6 code-only rule): an order route answers with the code
    and `retCode`, never the exchange's `retMsg`. `order_link_id` is `None` only where no order is
    named: a position-level stop write, or a refused `cancel_all`. `record` is the call's
    allow-listed record (SR-E29-08)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    order_link_id: OrderLinkId | None
    exchange_order_id: str | None
    error_code: str | None = None
    exchange_ret_code: int | None = None
    exchange_ret_msg: str | None = None
    retryable: bool = False
    latency_ms: int
    transport: Literal["rest", "ws"]
    record: ExchangeRecord | None = None


class Order(BaseModel):
    """§8.2. Minimal shape for `TradingPort` reads (`open_orders`,
    `order_history`); the full OMS aggregate root (mutable, with amend/
    protection tracking) is owned by E29 and defined in
    `candleviewer.oms.models`, not here — this is deliberately a read-only
    subset so this ticket's port compiles without depending on the OMS
    module (M3 may not depend on M-oms per CONSTITUTION.md §3).
    **Deviation, noted in the PR**: §14.4 does not give `Order` a formal
    field list; this shape is the read-facing minimum implied by
    `TradingPort.open_orders`/`order_history`. `order_id` is the OMS's local
    id, which an adapter cannot know, so a read leaves it `None`;
    `exchange_order_id` is the exchange's, which every order a read returns
    carries (24 §14.2 rule 11). B1's full match (SR-E29-03) reads
    `reduce_only`, `trigger_price` and `stop_loss`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: OrderId | None = None
    order_link_id: OrderLinkId
    exchange_order_id: ExchangeOrderId
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
    reduce_only: bool = False
    trigger_price: Px | None = None
    stop_loss: Px | None = None
    take_profit: Px | None = None
    tpsl_mode: Literal["full", "partial"] | None = None
    order_kind: OrderKind = "order"
    position_idx: Literal[0, 1, 2] = 0
    time_in_force: Literal["gtc", "ioc", "fok", "post_only", "rpi"] = "gtc"


class Execution(BaseModel):
    """§8.2 immutable fill record. **Deviation, noted in the PR**: read-only
    subset for `TradingPort.executions`; the full record lives with the OMS.
    `order_id` is the OMS's local id: an adapter leaves it `None`. The rest
    follows 24 §8.1's `Execution`: `exchange_order_id` is the exchange's id of
    the order the execution fills, which B1 pairs it on (SR-E29-03), and
    `exec_type` and `fee_rate` are as `21-database-schema.md` §3.3.6 stores
    them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exec_id: str
    exchange_order_id: ExchangeOrderId
    order_id: OrderId | None = None
    order_link_id: OrderLinkId
    account_id: AccountId
    symbol: Symbol
    side: Side
    price: Px
    qty: Qty
    fee: Notional
    fee_rate: FeeRateValue
    fee_currency: str
    is_maker: bool
    exec_type: ExecType
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
    level (no `retCode`/camelCase, C-2.2). `order_id` is the OMS's local id:
    an adapter leaves it `None`; `qty` is the size the record closed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    symbol: Symbol
    order_id: OrderId | None = None
    side: Side
    qty: Qty
    avg_entry_price: Px
    avg_exit_price: Px
    closed_pnl: Notional
    leverage: Decimal
    opened_at: TsUs
    closed_at: TsUs


class Wallet(BaseModel):
    """§14.4. `available_to_withdraw` is `None` when the exchange reports no figure (it has
    deprecated the field for unified accounts); this product never withdraws (C-2.8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    coin: str = "USDT"
    equity: Notional
    wallet_balance: Notional
    available_to_withdraw: Notional | None
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
    (margin mode, position mode) an OMS needs before placing an order.
    `position_mode` is `None` when the account read does not report it: the
    exchange reports it per position (`Position.position_idx`), §14.3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    uid: str
    margin_mode: Literal["regular", "portfolio", "isolated"]
    position_mode: Literal["one_way", "hedge"] | None
    unified_margin: bool


class RateHeadroom(BaseModel):
    """§14.1 `RateHeadroomPort`: the local rate budget the next request of one account's lane
    would meet, read without taking a token or sending anything (#2877 ruling 4: B1's `rate`
    verdict reads it until E34-T02's `reserve()`). `tokens` is what the buckets the lane draws
    hold spare now, the fewest of them; `wait_s` is how long that request would wait for its
    token, an IP hold included, 0 when one is spare now. A request whose wait passes its lane's
    wait is refused with nothing sent (24 §8.7). Until E34-T02 every lane is served alike."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lane: RateLane
    tokens: Annotated[float, Field(ge=0)]
    wait_s: Annotated[float, Field(ge=0)]


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
