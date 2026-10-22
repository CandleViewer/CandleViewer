"""The private stream's frames, read (G-8b, #3963; 24 §14.2 rule 13). Pure: no I/O and no clock.

`classify(frame)` reads one frame into a `Reply` (`auth`, `subscribe` or a pong) or a `Push` of a
subscribed topic. Nesting is checked before `json.loads` (`frame_guard`), and a frame that is
malformed, too deep, holds more than `FRAME_ROWS_MAX` rows, or is neither raises
`FrameRejected`: no event of it is yielded, and the stream follows it with `resyncing`. A reply's
`ret_msg`, `conn_id` and `req_id` are never read.

`read_push(push, account, now_us=...)` maps a push's rows to `PrivateEvent`s of the stream's
account, never the payload's (SR-E29-02). Each row is checked before it is parsed: a category
other than `linear`, a symbol outside USDT linear perpetuals (C-1.2, as the REST reads' settle
coin), one of our ids of another environment or account (G-8's `owner_refusal`), an execution
that fills no order or has no `exec_type` (G-8's `set_aside`), an account type other than
`UNIFIED`, and a wallet account with no USDT row are dropped, counted in
`bybit_private_rows_refused_total{topic,reason}` and logged with our id or the type, never
raised. A row that passes but fails its strict model rejects the whole frame (`malformed`). The
row models extend G-8's (strict, unknown fields counted in `cv_bybit_unknown_fields_total`
under `PUSH_MODEL_LABELS`), and G-8's mappers build the payloads, so an order or a fill reads
the same on the stream as over REST. Order, execution and fast-execution events carry the row's
allow-listed record (`record.push_record`, SR-E29-08).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal

import structlog
from pydantic import BeforeValidator, Field

from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import Symbol, TsUs
from candleviewer.exchange.base.frame_guard import MAX_TS_MS, json_depth_exceeds
from candleviewer.exchange.base.models import (
    AccountRef,
    FastExecution,
    Order,
    PrivateEvent,
)
from candleviewer.exchange.bybit import record as rec
from candleviewer.exchange.bybit.metrics import bybit_private_rows_refused_total
from candleviewer.exchange.bybit.trading_parse import (
    ExecutionRow,
    Millis,
    OptPrice,
    OrderRow,
    PositionRow,
    Price,
    Quantity,
    RawLink,
    VenueId,
    WalletAccount,
    WalletPage,
    _Venue,
    normalised_link,
    owner_refusal,
    set_aside,
    to_execution,
    to_order,
    to_position,
    to_wallet,
    validated,
)

__all__ = [
    "FRAME_ROWS_MAX",
    "PUSH_MODEL_LABELS",
    "TOPICS",
    "FrameRejected",
    "FrameRejection",
    "Push",
    "PushRefusal",
    "PushTopic",
    "Reply",
    "classify",
    "read_push",
]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Rows one frame may hold (G-8b ruling 9); a frame with more is rejected whole.
FRAME_ROWS_MAX: Final = 1000
#: The closed `model` label set of the push models in `cv_bybit_unknown_fields_total` (a test
#: pins it); the wallet's coin rows count under G-8's `wallet_coin`.
PUSH_MODEL_LABELS: Final = frozenset(
    {
        "push_envelope",
        "order_push",
        "execution_push",
        "fast_execution",
        "position_push",
        "wallet_push",
    }
)

type PushTopic = Literal["order", "execution", "execution.fast", "position", "wallet"]
type FrameRejection = Literal["malformed", "depth_limit", "too_many_rows", "unknown_frame"]
type PushRefusal = Literal[
    "environment",
    "account",
    "category",
    "symbol",
    "account_type",
    "not_a_fill",
    "unmapped_type",
    "no_settle_coin",
]

#: The private topics, as the categorised and the all-in-one names carry them, to the neutral
#: topic (the `topic` label). The adapter subscribes the categorised ones; a row's own category
#: is checked either way.
TOPICS: Final[Mapping[str, PushTopic]] = MappingProxyType(
    {
        "order": "order",
        "order.linear": "order",
        "execution": "execution",
        "execution.linear": "execution",
        "execution.fast": "execution.fast",
        "execution.fast.linear": "execution.fast",
        "position": "position",
        "position.linear": "position",
        "wallet": "wallet",
    }
)
#: A USDT linear perpetual's symbol, the only ones the product trades (C-1.2), no longer than a
#: `Symbol` (20): linear USDC perpetuals and dated futures are another product, and a longer
#: symbol is dropped as one, never a frame its model would reject (CR-G8B-B-06).
_USDT_PERPETUAL: Final = re.compile(r"[A-Z0-9]{2,16}USDT")
_SETTLE: Final = "USDT"
#: Plausible exchange clock (ms) for a push's `creationTime`: 2018-01-01 to 2100-01-01.
_MS_MIN: Final = 1_514_764_800_000
_SIDE: Final[Mapping[str, Literal["buy", "sell"]]] = MappingProxyType(
    {"Buy": "buy", "Sell": "sell"}
)


class FrameRejected(ValueError):
    """A frame the stream cannot read whole: no event of it is yielded (24 §14.2 rule 13)."""

    def __init__(self, reason: FrameRejection) -> None:
        super().__init__(f"private frame rejected: {reason}")
        self.reason: FrameRejection = reason


@dataclass(frozen=True, slots=True)
class Reply:
    """A reply on the private stream. `granted` is `auth`'s or `subscribe`'s `success` when it is a
    boolean, `None` for a pong or a verdict the reply does not state."""

    op: Literal["auth", "subscribe", "pong"]
    granted: bool | None


@dataclass(frozen=True, slots=True)
class Push:
    """One push of a subscribed topic: its topic as received, the neutral topic, the push's
    creation time (ms) and its raw rows, each checked and parsed by `read_push`."""

    topic: str
    label: PushTopic
    created_ms: int
    rows: tuple[Mapping[str, Any], ...]


def _created(value: object) -> int:
    if type(value) is not int or not _MS_MIN <= value <= MAX_TS_MS:
        raise ValueError("creation time outside the plausible window")
    return value


def _push_seq(value: object) -> int | None:
    """A position's cross sequence: `-1` (or `"-1"`) means the symbol never traded, so none."""
    if (type(value) is int and value == -1) or value == "-1":
        return None
    if type(value) is not int or value < 0:
        raise ValueError("not a cross sequence")
    return value


class PushEnvelope(_Venue):
    """A push: its topic, creation time and rows (`id` is documented, never read)."""

    metric_model = "push_envelope"
    documented = frozenset({"id"})

    topic: Annotated[str, Field(max_length=64)]
    creationTime: Annotated[int, BeforeValidator(_created)]
    data: list[Any]


class OrderPushRow(OrderRow):
    """A row of the `order` topic: G-8's order row and its category; the push's own fields are
    documented, never read."""

    metric_model = "order_push"
    documented = OrderRow.documented | frozenset({"brokerOrderPrice", "closedPnl", "feeCurrency"})

    category: Literal["linear"]


class ExecutionPushRow(ExecutionRow):
    """A row of the `execution` topic: G-8's execution row and its category."""

    metric_model = "execution_push"
    documented = ExecutionRow.documented | frozenset({"isLeverage", "marketUnit", "execPnl"})

    category: Literal["linear"]


class FastExecutionRow(_Venue):
    """A row of the `execution.fast` topic: a trade fill, with no fee, fee rate or type."""

    metric_model = "fast_execution"

    category: Literal["linear"]
    symbol: Symbol
    execId: VenueId
    execPrice: Price
    execQty: Quantity
    orderId: VenueId
    isMaker: bool
    orderLinkId: RawLink
    side: Literal["Buy", "Sell"]
    execTime: Millis
    seq: Annotated[int, Field(ge=0)]


class PositionPushRow(PositionRow):
    """A row of the `position` topic: G-8's position row, whose average entry price the push
    names `entryPrice`, with its category and its cross sequence."""

    metric_model = "position_push"

    avgPrice: OptPrice = Field(alias="entryPrice")
    category: Literal["linear"]
    seq: Annotated[int | None, BeforeValidator(_push_seq)] = None


class WalletPushAccount(WalletAccount):
    """A row of the `wallet` topic: G-8's unified account and its coin rows."""

    metric_model = "wallet_push"


def classify(frame: str) -> Reply | Push:
    """One frame as a reply or a push, or `FrameRejected` (no event of it is yielded)."""
    if json_depth_exceeds(frame):
        raise FrameRejected("depth_limit")
    data: object = None
    try:
        data = json.loads(frame)
    except (ValueError, RecursionError):  # a residual recursion is the depth limit's, as G-8's
        pass
    if not isinstance(data, dict):
        raise FrameRejected("malformed")
    topic = data.get("topic")
    if topic is None:
        return _reply(data)
    label = TOPICS.get(topic) if isinstance(topic, str) else None
    if label is None:
        raise FrameRejected("unknown_frame")
    rows = data.get("data")
    if isinstance(rows, list) and len(rows) > FRAME_ROWS_MAX:
        raise FrameRejected("too_many_rows")
    envelope = validated(PushEnvelope, data)
    if envelope is None or not all(isinstance(row, dict) for row in envelope.data):
        raise FrameRejected("malformed")
    return Push(topic, label, envelope.creationTime, tuple(envelope.data))


def _reply(data: Mapping[str, Any]) -> Reply:
    op = data.get("op")
    if op == "pong":
        return Reply("pong", None)
    if op in ("auth", "subscribe"):
        success = data.get("success")
        granted = success if type(success) is bool else None
        return Reply("auth" if op == "auth" else "subscribe", granted)
    raise FrameRejected("unknown_frame")


def read_push(push: Push, account: AccountRef, *, now_us: TsUs) -> tuple[PrivateEvent, ...]:
    """The push's rows as events of `account`; a refused row is dropped and counted, an
    unreadable one rejects the frame (`FrameRejected`)."""
    events: list[PrivateEvent] = []
    for raw in push.rows:
        refusal = _refusal(push.label, raw, account)
        if refusal is not None:
            _refuse(push.label, refusal, raw)
            continue
        event = _event(push, raw, account, now_us)
        if event is not None:
            events.append(event)
    return tuple(events)


def _refusal(label: PushTopic, raw: Mapping[str, Any], account: AccountRef) -> PushRefusal | None:
    """Why a row is not this stream's to deliver, checked before its strict parse; a row that
    does not even state what these checks read is malformed."""
    if label == "wallet":
        kind = raw.get("accountType")
        if not isinstance(kind, str):
            raise FrameRejected("malformed")
        return None if kind == "UNIFIED" else "account_type"
    category, symbol = raw.get("category"), raw.get("symbol")
    if not isinstance(category, str) or not isinstance(symbol, str):
        raise FrameRejected("malformed")
    if category != "linear":
        return "category"
    if _USDT_PERPETUAL.fullmatch(symbol) is None:
        return "symbol"
    if label != "position":
        link = raw.get("orderLinkId")
        if not isinstance(link, str):
            raise FrameRejected("malformed")
        owner = owner_refusal(link, account)
        if owner is not None:
            return owner
    return set_aside(raw) if label == "execution" else None


def _refuse(label: PushTopic, reason: PushRefusal, raw: Mapping[str, Any]) -> None:
    """Count and log a dropped row: one of our ids, or the documented type that set it aside;
    never the venue's other text."""
    bybit_private_rows_refused_total.labels(topic=label, reason=reason).inc()
    link = raw.get("orderLinkId")
    ours = link if isinstance(link, str) and OUR_ID.fullmatch(link) is not None else None
    kind = raw.get("execType") if reason in ("not_a_fill", "unmapped_type") else None
    logger().warning(
        "bybit_private_row_refused", topic=label, reason=reason, order_link_id=ours, exec_type=kind
    )


def _event(
    push: Push, raw: Mapping[str, Any], account: AccountRef, now_us: TsUs
) -> PrivateEvent | None:
    """The row's event, or `None` for a wallet row with no USDT (counted); `FrameRejected` when
    the row fails its strict model."""
    ts_event = push.created_ms * 1000
    if push.label == "order":
        order = _order(raw, account)
        record = rec.push_record(push.topic, rec.push_fields(raw))
        return PrivateEvent(
            kind="order",
            account_id=account.account_id,
            payload=order,
            ts_event=ts_event,
            ts_ingest=now_us,
            record=record,
        )
    if push.label == "execution":
        execution = _parse(ExecutionPushRow, raw)
        return PrivateEvent(
            kind="execution",
            account_id=account.account_id,
            payload=to_execution(execution, account, now_us),
            ts_event=ts_event,
            ts_ingest=now_us,
            seq=execution.seq,
            record=rec.push_record(push.topic, rec.push_fields(raw)),
        )
    if push.label == "execution.fast":
        fast = _parse(FastExecutionRow, raw)
        return PrivateEvent(
            kind="execution_fast",
            account_id=account.account_id,
            payload=_fast(fast, account),
            ts_event=ts_event,
            ts_ingest=now_us,
            seq=fast.seq,
            record=rec.push_record(push.topic, rec.push_fields(raw)),
        )
    if push.label == "position":
        position = _parse(PositionPushRow, raw)
        return PrivateEvent(
            kind="position",
            account_id=account.account_id,
            payload=to_position(position, account),
            ts_event=ts_event,
            ts_ingest=now_us,
            seq=position.seq,
        )
    return _wallet(push, raw, account, now_us)


def _parse[M: _Venue](model: type[M], raw: Mapping[str, Any]) -> M:
    parsed = validated(model, raw)
    if parsed is None:
        raise FrameRejected("malformed")
    return parsed


def _order(raw: Mapping[str, Any], account: AccountRef) -> Order:
    row = _parse(OrderPushRow, raw)
    # A limit order without a price is a malformed push, refused here before G-8's mapper,
    # which would count it as a REST reply of unknown outcome (SEC-G8B-B-01).
    if row.orderType == "Limit" and row.price <= 0:
        raise FrameRejected("malformed")
    return to_order(row, account)


def _fast(row: FastExecutionRow, account: AccountRef) -> FastExecution:
    return FastExecution(
        exec_id=row.execId,
        exchange_order_id=row.orderId,
        order_link_id=normalised_link(row.orderLinkId, row.orderId),
        account_id=account.account_id,
        symbol=row.symbol,
        side=_SIDE[row.side],
        price=row.execPrice,
        qty=row.execQty,
        is_maker=row.isMaker,
        ts_exec=row.execTime * 1000,
        seq=row.seq,
    )


def _wallet(
    push: Push, raw: Mapping[str, Any], account: AccountRef, now_us: TsUs
) -> PrivateEvent | None:
    """The unified account's USDT figures; an account with no USDT row is dropped and counted
    (`no_settle_coin`), one with two is malformed. Only the USDT rows are read: the push carries
    every coin, and an odd row of another coin never rejects the account (CR-G8B-B-03)."""
    coins = raw.get("coin")
    if not isinstance(coins, list):
        raise FrameRejected("malformed")
    settle = [coin for coin in coins if isinstance(coin, dict) and coin.get("coin") == _SETTLE]
    unified = _parse(WalletPushAccount, {**raw, "coin": settle})
    rows = list(unified.coins)
    if not rows:
        _refuse("wallet", "no_settle_coin", raw)
        return None
    if len(rows) > 1:
        raise FrameRejected("malformed")
    page = WalletPage.model_construct(accounts=[unified])  # already validated, never re-counted
    return PrivateEvent(
        kind="wallet",
        account_id=account.account_id,
        payload=to_wallet(page, account, _SETTLE, push.created_ms),
        ts_event=push.created_ms * 1000,
        ts_ingest=now_us,
    )
