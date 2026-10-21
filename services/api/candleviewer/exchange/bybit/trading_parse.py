"""Strict parsers of the trading endpoints' replies (G-8, #2877; E08 control E8-8, ruling R7).

Each venue model is `strict=True, extra="ignore"`: a field of the wrong JSON type, a value
outside its documented set or a bound fails the whole reply as `UnknownStateError`, raised
with no cause or context so no traceback holds reply content. A field the documentation does
not list is ignored and counted in `cv_bybit_unknown_fields_total{model}`, so silent drift
shows; a documented field the port does not read is known, not counted. Decimals are the
venue's decimal text, bounded (`frame_guard`). Every row takes its account from the call that
produced it, never from the payload (SR-E29-02), and its `order_link_id` normalised (24 §14.2
rule 11); a row carrying one of our ids of another environment or account is dropped and
counted in `bybit_rows_refused_total{reason}`, never raised (ruling R12). Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Final, Literal

import structlog
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from candleviewer.domain.order_link import ENV_LETTER, OUR_ID, account_tag, ext_key, link_owner
from candleviewer.domain.primitives import OrderLinkId, Symbol, TsUs
from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.base.frame_guard import MAX_PRICE, MAX_QTY, MAX_TS_MS
from candleviewer.exchange.base.models import (
    AccountInfo,
    AccountRef,
    ClosedPnl,
    Execution,
    FeeRate,
    Order,
    OrderKind,
    Position,
    Wallet,
)
from candleviewer.exchange.bybit.metrics import (
    bybit_rows_refused_total,
    cv_bybit_unknown_fields_total,
)

__all__ = [
    "MODEL_LABELS",
    "AccountInfoResult",
    "BatchReply",
    "CancelAllResult",
    "ClosedPnlPage",
    "ExecutionPage",
    "FeeRatePage",
    "OrderPage",
    "OrderReply",
    "PositionPage",
    "RowRefusal",
    "WalletPage",
    "kept",
    "normalised_link",
    "parse",
    "to_account_info",
    "to_closed_pnl",
    "to_execution",
    "to_fee_rate",
    "to_order",
    "to_position",
    "to_wallet",
]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Decimal text as the venue writes it: no sign but `-`, no exponent, bounded digits.
_DECIMAL: Final = re.compile(r"-?[0-9]{1,24}(?:\.[0-9]{1,18})?")
#: Any signed amount (PnL, fees, balances) is bounded too: no account comes near it.
_MAX_ABS: Final = Decimal("1e15")
#: Plausible exchange clock (ms): 2018-01-01 to 2100-01-01.
_MS_MIN: Final = 1_514_764_800_000
_MS_DIGITS: Final = re.compile(r"[0-9]{1,19}")
#: The longest cursor the port passes back: the documented ones are well under it.
MAX_CURSOR_LEN: Final = 512


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError("not the venue's decimal text")
    number = Decimal(value)
    if abs(number) > _MAX_ABS:
        raise ValueError("amount out of bounds")
    return number


def _price(value: object) -> Decimal:
    number = _decimal(value)
    if not 0 < number <= MAX_PRICE:
        raise ValueError("price out of bounds")
    return number


def _optional_price(value: object) -> Decimal | None:
    """The venue writes "" or a zero (`"0"`, `"0.00"`) for a price that is not set."""
    if value == "":
        return None
    number = _decimal(value)
    if number == 0:
        return None
    if not 0 < number <= MAX_PRICE:
        raise ValueError("price out of bounds")
    return number


def _qty(value: object) -> Decimal:
    number = _decimal(value)
    if not 0 <= number <= MAX_QTY:
        raise ValueError("quantity out of bounds")
    return number


def _optional_amount(value: object) -> Decimal | None:
    return None if value == "" else _decimal(value)


def _ms(value: object) -> int:
    if not isinstance(value, str) or _MS_DIGITS.fullmatch(value) is None:
        raise ValueError("time must be ms digits")
    millis = int(value)
    if not _MS_MIN <= millis <= MAX_TS_MS:
        raise ValueError("time outside the plausible window")
    return millis


def _integer(value: object) -> int:
    """A JSON integer: a boolean is no integer here, though `True == 1` in Python."""
    if type(value) is not int:
        raise ValueError("not an integer")
    return value


Amount = Annotated[Decimal, BeforeValidator(_decimal)]
Price = Annotated[Decimal, BeforeValidator(_price)]
OptPrice = Annotated[Decimal | None, BeforeValidator(_optional_price)]
OptAmount = Annotated[Decimal | None, BeforeValidator(_optional_amount)]
Quantity = Annotated[Decimal, BeforeValidator(_qty)]
#: A non-negative price, `0` included: a market order's row may carry one.
Unsigned = Annotated[Decimal, BeforeValidator(_qty)]
Millis = Annotated[int, BeforeValidator(_ms)]
VenueId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
RawLink = Annotated[str, StringConstraints(max_length=64)]
Cursor = Annotated[str, StringConstraints(max_length=MAX_CURSOR_LEN)]
Side = Literal["Buy", "Sell"]
PositionIndex = Annotated[Literal[0, 1, 2], BeforeValidator(_integer)]

#: The closed `model` label set of `cv_bybit_unknown_fields_total` (a test pins it).
MODEL_LABELS: Final = frozenset(
    {
        "account_info",
        "batch_code",
        "batch_item",
        "cancel_all",
        "closed_pnl",
        "execution",
        "fee_rate",
        "order",
        "order_reply",
        "page",
        "position",
        "wallet",
        "wallet_coin",
    }
)


class _Venue(BaseModel):
    """A venue reply object: strict, unknown fields ignored and counted (ruling R7)."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore", populate_by_name=False)

    metric_model: ClassVar[str]
    #: Documented fields the port does not read: known, so never counted as drift.
    documented: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _count_unknown(cls, data: object) -> object:
        if isinstance(data, Mapping):
            known = {f.alias or name for name, f in cls.model_fields.items()} | cls.documented
            unknown = sum(1 for key in data if key not in known)
            if unknown:
                cv_bybit_unknown_fields_total.labels(model=cls.metric_model).inc(unknown)
        return data


class OrderReply(_Venue):
    """`result` of create, amend and cancel: the order the call named."""

    metric_model = "order_reply"

    orderId: VenueId
    orderLinkId: RawLink


class CancelAllResult(_Venue):
    """`result` of `cancel-all`: the orders it cancelled; `success` is "1" or "0"."""

    metric_model = "cancel_all"

    cancelled: Annotated[list[OrderReply], Field(max_length=10_000)] = Field(alias="list")
    success: Literal["0", "1"] | None = None


class BatchItem(_Venue):
    """One order of a `create-batch` reply; a refused item carries an empty `orderId`."""

    metric_model = "batch_item"
    documented = frozenset({"category", "createAt"})

    symbol: Symbol
    orderId: Annotated[str, StringConstraints(max_length=64)]
    orderLinkId: RawLink


class BatchCode(_Venue):
    """One item's code of a `create-batch` reply (`retExtInfo.list`)."""

    metric_model = "batch_code"

    code: int
    msg: Annotated[str, StringConstraints(max_length=2048)]


class _BatchItems(_Venue):
    metric_model = "page"

    items: Annotated[list[BatchItem], Field(max_length=20)] = Field(alias="list")


class _BatchCodes(_Venue):
    metric_model = "page"

    codes: Annotated[list[BatchCode], Field(max_length=20)] = Field(alias="list")


class BatchReply(BaseModel):
    """A `create-batch` reply: the orders and their codes, pairwise."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    result: _BatchItems
    retExtInfo: _BatchCodes


class OrderRow(_Venue):
    """A row of `order/realtime` or `order/history`."""

    metric_model = "order"
    documented = frozenset(
        {
            "parentOrderLinkId", "blockTradeId", "isLeverage", "createType", "cancelType",
            "rejectReason", "leavesValue", "cumExecValue", "cumExecFee", "orderIv", "marketUnit",
            "slippageToleranceType", "slippageTolerance", "ocoTriggerBy", "tpLimitPrice",
            "slLimitPrice", "tpTriggerBy", "slTriggerBy", "triggerDirection", "triggerBy",
            "lastPriceOnCreated", "basePrice", "closeOnTrigger", "placeType", "smpType",
            "smpGroup", "smpOrderId", "extraFees", "cumFeeDetail", "rpiTakerAccess",
            "rpiMatchedQty",
        }
    )  # fmt: skip

    orderId: VenueId
    orderLinkId: RawLink
    symbol: Symbol
    price: Unsigned
    qty: Quantity
    side: Side
    positionIdx: PositionIndex
    orderStatus: Literal[
        "New",
        "PartiallyFilled",
        "Untriggered",
        "Rejected",
        "PartiallyFilledCanceled",
        "Filled",
        "Cancelled",
        "Triggered",
        "Deactivated",
    ]
    avgPrice: OptPrice
    leavesQty: Quantity
    cumExecQty: Quantity
    timeInForce: Literal["GTC", "IOC", "FOK", "PostOnly", "RPI"]
    orderType: Literal["Market", "Limit"]
    stopOrderType: Literal[
        "",
        "UNKNOWN",
        "Stop",
        "TakeProfit",
        "StopLoss",
        "PartialTakeProfit",
        "PartialStopLoss",
        "TrailingStop",
        "MmRateClose",
    ]
    triggerPrice: OptPrice
    takeProfit: OptPrice
    stopLoss: OptPrice
    tpslMode: Literal["Full", "Partial", "", "UNKNOWN"]
    reduceOnly: bool
    createdTime: Millis
    updatedTime: Millis


class ExecutionRow(_Venue):
    """A row of `execution/list`: one fill of one order."""

    metric_model = "execution"
    documented = frozenset(
        {
            "orderPrice", "orderQty", "leavesQty", "createType", "orderType", "stopOrderType",
            "execFeeV2", "execValue", "feeRate", "tradeIv", "markIv", "markPrice", "indexPrice",
            "underlyingPrice", "blockTradeId", "closedSize", "extraFees",
        }
    )  # fmt: skip

    symbol: Symbol
    orderId: VenueId
    orderLinkId: RawLink
    side: Side
    execFee: Amount
    execId: VenueId
    execPrice: Price
    execQty: Quantity
    execType: Literal[
        "Trade", "AdlTrade", "BustTrade", "Delivery", "BlockTrade", "MovePosition",
        "FutureSpread",
    ]  # fmt: skip
    execTime: Millis
    feeCurrency: Annotated[str, StringConstraints(max_length=16)]
    isMaker: bool
    seq: Annotated[int, Field(ge=0)]


class PositionRow(_Venue):
    """A row of `position/list`."""

    metric_model = "position"
    documented = frozenset(
        {
            "riskId", "riskLimitValue", "positionValue", "autoAddMargin", "positionStatus",
            "breakEvenPrice", "positionIM", "positionIMByMp", "positionMM", "positionMMByMp",
            "sessionAvgPrice", "delta", "gamma", "vega", "theta", "netDeltaRatio",
            "curRealisedPnl", "adlRankIndicator", "createdTime", "openTime", "seq",
            "isReduceOnly", "mmrSysUpdatedTime", "mmrSysUpdateTime", "leverageSysUpdatedTime",
            "tpslMode", "bustPrice", "positionBalance", "tradeMode",
        }
    )  # fmt: skip

    positionIdx: PositionIndex
    symbol: Symbol
    side: Literal["Buy", "Sell", ""]
    size: Quantity
    avgPrice: OptPrice
    markPrice: OptPrice
    liqPrice: OptPrice
    leverage: Amount
    unrealisedPnl: Amount
    cumRealisedPnl: Amount
    takeProfit: OptPrice
    stopLoss: OptPrice
    trailingStop: OptPrice
    updatedTime: Millis


class ClosedPnlRow(_Venue):
    """A row of `position/closed-pnl`: one closing order's realised PnL."""

    metric_model = "closed_pnl"
    documented = frozenset(
        {
            "orderId", "qty", "orderPrice", "orderType", "execType", "cumEntryValue",
            "cumExitValue", "fillCount", "openFee", "closeFee",
        }
    )  # fmt: skip

    symbol: Symbol
    side: Side
    closedSize: Quantity
    avgEntryPrice: Price
    avgExitPrice: Price
    closedPnl: Amount
    leverage: Amount
    createdTime: Millis
    updatedTime: Millis


class WalletCoin(_Venue):
    metric_model = "wallet_coin"
    documented = frozenset(
        {
            "usdValue", "locked", "spotHedgingQty", "borrowAmount", "accruedInterest",
            "totalOrderIM", "totalPositionIM", "totalPositionMM", "bonus", "marginCollateral",
            "collateralSwitch", "colRes", "spotBorrow", "free", "availableToBorrow",
        }
    )  # fmt: skip

    coin: Annotated[str, StringConstraints(min_length=1, max_length=16)]
    equity: Amount
    walletBalance: Amount
    availableToWithdraw: OptAmount = None
    unrealisedPnl: Amount
    cumRealisedPnl: Amount


class WalletAccount(_Venue):
    metric_model = "wallet"
    documented = frozenset(
        {
            "totalEquity", "totalWalletBalance", "totalMarginBalance", "totalPerpUPL",
            "totalMaintenanceMargin", "accountIMRateByMp", "accountMMRateByMp",
            "totalInitialMarginByMp", "totalMaintenanceMarginByMp", "accountLTV",
        }
    )  # fmt: skip

    accountType: Literal["UNIFIED"]
    accountIMRate: Amount
    accountMMRate: Amount
    totalAvailableBalance: Amount
    totalInitialMargin: Amount
    coins: Annotated[list[WalletCoin], Field(max_length=200)] = Field(alias="coin")


class FeeRateRow(_Venue):
    metric_model = "fee_rate"
    documented = frozenset({"baseCoin", "rpiMakerFeeRate"})

    symbol: Symbol
    takerFeeRate: Amount
    makerFeeRate: Amount


class AccountInfoResult(_Venue):
    """`result` of `account/info`."""

    metric_model = "account_info"
    documented = frozenset(
        {"isMasterTrader", "spotHedgingStatus", "dcpStatus", "timeWindow", "smpGroup"}
    )

    unifiedMarginStatus: Annotated[Literal[1, 3, 4, 5, 6], BeforeValidator(_integer)]
    marginMode: Literal["ISOLATED_MARGIN", "REGULAR_MARGIN", "PORTFOLIO_MARGIN"]
    updatedTime: Millis


class _Page(_Venue):
    """A cursor page of a linear read: the category it answered and the next cursor."""

    metric_model = "page"

    category: Literal["linear"]
    nextPageCursor: Cursor = ""


class OrderPage(_Page):
    rows: Annotated[list[OrderRow], Field(max_length=50)] = Field(alias="list")


class ExecutionPage(_Page):
    """Raw rows: a funding row is no fill, so it is set aside before the strict parse."""

    rows: Annotated[list[dict[str, Any]], Field(max_length=100)] = Field(alias="list")


class PositionPage(_Page):
    rows: Annotated[list[PositionRow], Field(max_length=200)] = Field(alias="list")


class ClosedPnlPage(_Page):
    rows: Annotated[list[ClosedPnlRow], Field(max_length=100)] = Field(alias="list")


class WalletPage(_Venue):
    metric_model = "page"

    accounts: Annotated[list[WalletAccount], Field(max_length=4)] = Field(alias="list")


class FeeRatePage(_Venue):
    """Derivatives carry no `category` here; a reply for another product names one."""

    metric_model = "page"

    category: Literal["linear"] | None = None
    rows: Annotated[list[FeeRateRow], Field(max_length=1)] = Field(alias="list")


def parse[M: BaseModel](model: type[M], data: object, what: str) -> M:
    """`data` as `model`, or `UnknownStateError` with no cause or context (no reply content)."""
    try:
        parsed: M | None = model.model_validate(data)
    except (ValidationError, TypeError, ValueError, RecursionError):
        parsed = None
    if parsed is None:
        raise UnknownStateError(f"malformed {what} reply")
    return parsed


# -- normalisation (24 §14.2 rule 11) and the per-row check (SR-E29-02) ------------------------

type RowRefusal = Literal["environment", "account", "not_a_fill"]

_SIDE: Final[Mapping[str, Literal["buy", "sell"]]] = {"Buy": "buy", "Sell": "sell"}
_STATE: Final[Mapping[str, str]] = {
    "New": "new",
    "PartiallyFilled": "partially_filled",
    "Untriggered": "untriggered",
    "Rejected": "rejected",
    "PartiallyFilledCanceled": "partially_filled_canceled",
    "Filled": "filled",
    "Cancelled": "cancelled",
    "Triggered": "triggered",
    "Deactivated": "deactivated",
}
_TERMINAL: Final = frozenset(
    {"Rejected", "PartiallyFilledCanceled", "Filled", "Cancelled", "Deactivated"}
)
_KIND: Final[Mapping[str, OrderKind]] = {
    "": "order",
    "UNKNOWN": "order",
    "Stop": "conditional",
    "TakeProfit": "take_profit",
    "StopLoss": "stop_loss",
    "PartialTakeProfit": "partial_take_profit",
    "PartialStopLoss": "partial_stop_loss",
    "TrailingStop": "trailing_stop",
    "MmRateClose": "mm_rate_close",
}
_TPSL: Final[Mapping[str, Literal["full", "partial"] | None]] = {
    "Full": "full",
    "Partial": "partial",
    "": None,
    "UNKNOWN": None,
}
_TIF: Final[Mapping[str, Literal["gtc", "ioc", "fok", "post_only", "rpi"]]] = {
    "GTC": "gtc",
    "IOC": "ioc",
    "FOK": "fok",
    "PostOnly": "post_only",
    "RPI": "rpi",
}
_MARGIN: Final[Mapping[str, Literal["regular", "portfolio", "isolated"]]] = {
    "REGULAR_MARGIN": "regular",
    "PORTFOLIO_MARGIN": "portfolio",
    "ISOLATED_MARGIN": "isolated",
}
#: `unifiedMarginStatus` values of a unified trading account; `1` is classic.
_UNIFIED: Final = frozenset({3, 4, 5, 6})


def normalised_link(raw: str, exchange_order_id: str) -> OrderLinkId:
    """Ours when it is a generated id, else the `ext-` key of the exchange order (rule 11)."""
    return raw if OUR_ID.fullmatch(raw) is not None else ext_key(exchange_order_id)


def owner_refusal(link: str, account: AccountRef) -> RowRefusal | None:
    """Why a row under `link` is not this account's: one of our ids naming another
    environment or account (`acct4`). An `ext-` key names no account of ours."""
    owner = link_owner(link)
    if owner is None:
        return None
    letter, tag = owner
    if letter != ENV_LETTER[account.environment]:
        return "environment"
    if tag != account_tag(account.account_id):
        return "account"
    return None


def refuse_row(reason: RowRefusal, link: str) -> None:
    bybit_rows_refused_total.labels(reason=reason).inc()
    logger().warning("bybit_row_refused", reason=reason, order_link_id=link)


def kept[T](rows: Sequence[T], link_of: Callable[[T], str], account: AccountRef) -> list[T]:
    """The rows whose id does not name another environment or account; the rest are dropped
    and counted (ruling R12), never raised."""
    out: list[T] = []
    for row in rows:
        link = link_of(row)
        reason = owner_refusal(link, account)
        if reason is None:
            out.append(row)
        else:
            refuse_row(reason, link)
    return out


def to_order(row: OrderRow, account: AccountRef) -> Order:
    if row.orderType == "Limit" and row.price <= 0:
        raise UnknownStateError("malformed order row: a limit order without a price")
    return Order(
        order_link_id=normalised_link(row.orderLinkId, row.orderId),
        exchange_order_id=row.orderId,
        account_id=account.account_id,
        symbol=row.symbol,
        side=_SIDE[row.side],
        order_type="limit" if row.orderType == "Limit" else "market",
        qty=row.qty,
        price=row.price if row.orderType == "Limit" else None,
        state=_STATE[row.orderStatus],
        filled_qty=row.cumExecQty,
        leaves_qty=row.leavesQty,
        avg_fill_price=row.avgPrice,
        created_at=row.createdTime * 1000,
        terminal_at=row.updatedTime * 1000 if row.orderStatus in _TERMINAL else None,
        reduce_only=row.reduceOnly,
        trigger_price=row.triggerPrice,
        stop_loss=row.stopLoss,
        take_profit=row.takeProfit,
        tpsl_mode=_TPSL[row.tpslMode],
        order_kind=_KIND[row.stopOrderType],
        position_idx=row.positionIdx,
        time_in_force=_TIF[row.timeInForce],
    )


def is_fill(raw: Mapping[str, Any]) -> bool:
    """A funding settlement is listed with the fills but fills no order."""
    return raw.get("execType") != "Funding"


def to_execution(row: ExecutionRow, account: AccountRef, ts_ingest: TsUs) -> Execution:
    return Execution(
        exec_id=row.execId,
        order_link_id=normalised_link(row.orderLinkId, row.orderId),
        account_id=account.account_id,
        symbol=row.symbol,
        side=_SIDE[row.side],
        price=row.execPrice,
        qty=row.execQty,
        fee=row.execFee,
        fee_currency=row.feeCurrency,
        is_maker=row.isMaker,
        closed_pnl=None,
        ts_exec=row.execTime * 1000,
        ts_ingest=ts_ingest,
        seq=row.seq,
    )


def to_position(row: PositionRow, account: AccountRef) -> Position:
    return Position(
        account_id=account.account_id,
        symbol=row.symbol,
        position_idx=row.positionIdx,
        side=_SIDE.get(row.side),
        qty=row.size,
        avg_entry_price=row.avgPrice,
        mark_price=row.markPrice,
        liq_price=row.liqPrice,
        leverage=row.leverage,
        unrealised_pnl=row.unrealisedPnl,
        cum_realised_pnl=row.cumRealisedPnl,
        take_profit=row.takeProfit,
        stop_loss=row.stopLoss,
        trailing_stop_distance=row.trailingStop,
        updated_at=row.updatedTime * 1000,
    )


def to_closed_pnl(row: ClosedPnlRow, account: AccountRef) -> ClosedPnl:
    return ClosedPnl(
        account_id=account.account_id,
        symbol=row.symbol,
        side=_SIDE[row.side],
        qty=row.closedSize,
        avg_entry_price=row.avgEntryPrice,
        avg_exit_price=row.avgExitPrice,
        closed_pnl=row.closedPnl,
        leverage=row.leverage,
        opened_at=row.createdTime * 1000,
        closed_at=row.updatedTime * 1000,
    )


def to_wallet(page: WalletPage, account: AccountRef, coin: str, at_ms: int) -> Wallet:
    """The unified account's figures and its `coin` row; either missing is malformed."""
    accounts = [a for a in page.accounts if a.accountType == "UNIFIED"]
    rows = [c for a in accounts for c in a.coins if c.coin == coin]
    if len(accounts) != 1 or len(rows) != 1:
        raise UnknownStateError(f"malformed wallet reply: no single unified {coin} row")
    unified, row = accounts[0], rows[0]
    return Wallet(
        account_id=account.account_id,
        coin=coin,
        equity=row.equity,
        wallet_balance=row.walletBalance,
        available_to_withdraw=row.availableToWithdraw,
        available_margin=unified.totalAvailableBalance,
        used_margin=unified.totalInitialMargin,
        unrealised_pnl=row.unrealisedPnl,
        cum_realised_pnl=row.cumRealisedPnl,
        account_im_rate=unified.accountIMRate,
        account_mm_rate=unified.accountMMRate,
        updated_at=at_ms * 1000,
    )


def to_fee_rate(page: FeeRatePage, symbol: Symbol, fetched_at: TsUs) -> FeeRate:
    rows = [r for r in page.rows if r.symbol == symbol]
    if len(rows) != 1:
        raise UnknownStateError("malformed fee-rate reply: not the one symbol asked")
    return FeeRate(
        symbol=symbol,
        maker=rows[0].makerFeeRate,
        taker=rows[0].takerFeeRate,
        fetched_at=fetched_at,
    )


def to_account_info(result: AccountInfoResult, account: AccountRef) -> AccountInfo:
    return AccountInfo(
        account_id=account.account_id,
        uid=account.uid,
        margin_mode=_MARGIN[result.marginMode],
        position_mode=None,
        unified_margin=result.unifiedMarginStatus in _UNIFIED,
    )
