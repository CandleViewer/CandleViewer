"""The OMS's command port: B1's `CommandPort` (E29-T04 #913; 24-internal-schemas.md Sec.8.3,
Sec.8.4, Sec.8.6, Sec.8.8).

B1's services call it (`statechart/bindings/b01_order.py`, `_dispatch`): `place` in `submitting`,
`lookup` before a create this process did not begin, `attach_stop` in `sl_pending`, and `cancel`
and `amend`, which go to slice 3's services. Every call reaches the exchange through
`routing.TradingRouter`, so it is signed for its account's own environment (C-2.11), and every
answer is a mapping B1's guards read (24 Sec.14.4 `OrderAck`), never the exchange's text
(SR-E29-09). Logs carry ids, codes and state names, never a price or a size (21 Sec.12).

**place.** The request is built from the stored order only: the `NewOrder` the pipeline
registered (`expect`), else the stored row, so a retry sends the same `order_link_id` and the same
native stop (C-2.10, C-2.6). A stop or take-profit that is not a finite price above zero is
refused before anything is sent, whatever the exchange port checks (#2877 ruling 2), and so is an
order that is not reduce-only and names no stop (C-2.6, SEC-2B1-04), which `FirstPersist.check`
and B1's gate already refuse upstream. A reduce-only order with a reducing intent takes the
`critical` lane, any other the `entry` lane (SR-E29-01, 24 Sec.8.7). A registered order is a first
send (`place_or_adopt`). One not registered is a create a restart resumes (SR-E29-15, [LANE-26]),
in this order:

1. the id is looked up first, whatever the switches say, as reading is never an order: an order
   found is adopted and nothing is sent (C-2.10);
2. the synchronous switches, then the clock halt, are asked (C-2.21): a refusal is
   `ResendRefused`, nothing sent, so no create is re-sent under a clock a `10002` tripped
   (SEC-2B1-01). A clock not composed or not measured yet is a third outcome: the halt lets
   `OmsNotReady` through (ruling Q8), logged as a refusal is (`oms_resend_refused`, with its
   code) and raised as it is, nothing sent, so B1 lands the order in `unknown` all the same;
3. where history never expires (`order_retention_days` None: live), a create older than
   `LIVE_RESEND_MAX_AGE_S` is never re-sent. Within the venue's history span
   (`LIVE_HISTORY_SPAN_S`, 24 h) the miss means it never landed: it ends `rejected` with
   `b01.EXPIRED_UNSENT`, its `oms.resend_refused` record (its age and the bound) written ahead
   and the user alerted (`OrderNotices`, `alert` `order_never_sent`, "not found within the
   venue's 24 h history"). At or past the span the miss proves nothing (24 Sec.14.1): it is
   answered as an empty lookup, so B1 lands it in `unknown` for reconciliation, and its entry's
   attach rows are never voided blind (SEC-2B1-02);
4. otherwise `adopt_or_resend` looks once more and re-sends the same request while history still
   covers the id (Sec.8.3 rule 6: demo keeps its 6 days).

One `SUBMIT_TIMEOUT_S` deadline bounds all of `place` (CR-2B1-04): the stored row's and the
account's reads, the exchange calls, and the answer's record, hand-over, credential report or
alert each end by it, each within its own bound too, so a best-effort one cut by it is logged and
the answer stands, as on its own timeout.

The answer: an accepted create names its exchange order id, text of 1 to `b01.MAX_TEXT`
characters, printable, with no whitespace (#4020 Low 1), else `AckWithoutOrderId`, an ambiguous
outcome (ruling 3 on #3972). A refusal carries the code and the exchange's return code, never its
message (SR-E29-09), with the call's allow-listed record (SR-E29-08). An order found under the id
is answered as a duplicate with what the lookup found and no top-level id, so B1 binds it only on
its own full match (SR-E29-03, #4020 Low 3); the port runs the same `full_match` first: a match is
audited ahead (`orders.submit`, `adopted_after_lookup`, C-2.9), and an order that does not match is
handed to the next reconciliation pass before the answer (`OrderHandovers`), the answer an empty
lookup when that fails (S2-Q3: `unknown`, never `held` with nothing handed over). An id no lookup
settles is an empty lookup (`unknown`), except a re-send the venue may hold (`resend_unconfirmed`:
a duplicate, an ambiguous answer or a refused token), a duplicate with no lookup, so B1 looks the
id up at once (Sec.8.3 rule 3) and never sends it under a new id. A refused rate token is
`RATE_BUDGET_EXCEEDED` with its `retry_after_s` (nothing left, so `rejected`, never `unknown`).
Anything else raised is raised, the venue's outage (`SERVICE_UNAVAILABLE`, #2863) included, so B1
lands the order in `unknown` (S1): no call is repeated because an error says `retryable`.

The records written for a registered order carry the correlation id of the request that
registered it (`expect(..., request_id=)`, #3990), never one from the context the call runs in,
which is B1's; a resumed create's and an attach's carry none (21 Sec.3.10.1).

**24 Sec.8.6, before any answer.** An `AUTH_ERROR` that carries the exchange's return code, answered
or raised, goes to `CredentialRejections` as it came (the orchestrator's Q-I ruling: `oms` holds no
exchange code, C-2.2); a `CLOCK_DRIFT` trips the clock halt, which refuses order entry until a fresh
measurement clears it, and starts one resync of the clock at a time, which `aclose()` cancels at
shutdown.

**lookup.** The id in open orders, then in history: the order found, else an empty mapping, on
which B1 sends. A found order is audited as above when it matches, and handed over first when it
does not; a hand-over that fails raises, as an empty answer would send the order.

**attach_stop** (24 Sec.8.8 rules 2 and 6). The position is read first. One that shows the
requested stop is answered with that reading and audited (`sl.attached`, `already_set`), and
nothing is recorded or sent (the orchestrator's Q-E ruling). Otherwise the gate clears the
position's key (21 Sec.3.3.11, bounded as every other call), the request is recorded ahead
(`trading_stop`, audited `sl.attached` in the insert's transaction), and one `trading-stop` call
sends the stop with the take-profit the position shows (24 Sec.8.9: both sides), that side left
out when the reading shows no finite price above zero, so nothing is removed by implication. Its
answer settles the row (`answered`, or `refused` with its void audited `sl.modified`), and a
read-back answers B1. A send that raises leaves the row in flight, for the complete read. A
Partial-mode stop is refused, audited, before anything is sent (Q-F: no stop size can be sent
until G-8b's `sl_size`, #3963), so B1 goes to `sl_missing` and B8. The kill switch, the switches
and the clock halt never gate it: a protective write, which 24 Sec.8.10 carves out (C-2.6,
C-4.14).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal
from uuid import UUID, uuid4

import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import (
    AuthError,
    ClockDriftError,
    ExchangeError,
    OmsErrorCode,
    RateBudgetExceededError,
)
from candleviewer.exchange.base.models import (
    AccountRef,
    Order,
    OrderAck,
    OrderLane,
    PlaceOrderRequest,
    Position,
    TradingStopRequest,
)
from candleviewer.observability import spawn
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.orders import NewOrder, OrderRow
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, RecordedStopRow

from .classify import REDUCING_INTENTS
from .clock_halt import ClockHalt
from .errors import (
    AckWithoutOrderId,
    HandoverUnavailable,
    OmsNotReady,
    OrderRefused,
    ResendRefused,
    problem_for,
)
from .order_link_resolution import (
    Adopted,
    HistoryRetentionPolicy,
    PlaceOutcome,
    Sent,
    Unresolved,
    adopt_or_resend,
    find_by_link_id,
    place_or_adopt,
)
from .order_machine import OrderAudit, OrderAuditRecord, OrderNotice, OrderNotices
from .ports import (
    AuditOutcome,
    AuditSeverity,
    CredentialRejections,
    KeyedRecord,
    OrderHandovers,
    PositionKey,
    StopRequestGate,
    SubmitAudit,
    TradingAccounts,
    TradingSwitches,
)
from .repository import OrderRepository, RecordedStopRepository
from .routing import RoutedPort, TradingRouter, read_position, retry_after

__all__ = [
    "ALREADY_SET",
    "EXPIRED_UNSENT_REASON",
    "LIVE_HISTORY_SPAN_S",
    "LIVE_RESEND_MAX_AGE_S",
    "MAX_WATCHES",
    "NEVER_SENT_ALERT",
    "PARTIAL_STOP_UNSUPPORTED",
    "PORT_TIMEOUT_S",
    "RESEND_REFUSED",
    "SUBMIT_TIMEOUT_S",
    "CommandHandler",
    "OmsCommandPort",
    "PlaceWatch",
    "found_view",
    "order_id_kept",
    "place_request",
]

#: The bound on one `place` as a whole, in seconds (CR-2B1-04): one deadline that the stored
#: row's and the account's reads, the exchange calls (the create and, after a duplicate, its
#: lookups; or a resumed create's lookups and re-send) and the answer's record, hand-over,
#: credential report or alert all end by. So an entry's stop request is answered within
#: `CV_PERSIST_TIMEOUT` + this + `CV_PERSIST_TIMEOUT` ([LANE-25]), inside the stop request's
#: bound (`oms_wiring.OmsBounds`) and B1's own `CV_COMMAND_TIMEOUT`. It also bounds `attach_stop`'s
#: one `trading-stop` call.
SUBMIT_TIMEOUT_S: Final = 5.0
#: The bound on each other call (a read, the store, an audit, a notice, a hand-over, the stop
#: gate), in seconds; inside `place` its deadline may end one sooner.
PORT_TIMEOUT_S: Final = 5.0
#: How old a create a restart resumes may be and still be re-sent where history never expires
#: (`order_retention_days` None: live), in seconds ([LANE-26], binding). Tighten it, never raise
#: it: a resumed send survives a restart or a dropped connection measured in seconds, and after
#: minutes the market and the trader's intent have moved. It also sits far inside
#: `LIVE_HISTORY_SPAN_S`, so a miss in open orders and history within it means the create never
#: landed. At exactly the bound the create is still re-sent; a microsecond past it, never. The
#: constructor refuses a larger figure.
LIVE_RESEND_MAX_AGE_S: Final = 120.0
#: How far back live's history read shows every order the venue took, in seconds: a `Cancelled`,
#: `Rejected` or `Deactivated` order for 24 hours only, one with no fill for 7 days only (24
#: Sec.14.1, assumed pending E29-K01). Read against the stored `created_ts`, which no order of the
#: row can predate: a resumed create younger than it that no lookup found never landed, and ends
#: unsent ([LANE-26]); from it on a miss proves nothing, and the create is answered as an empty
#: lookup, `unknown` for reconciliation (SEC-2B1-02). At exactly the span a miss proves nothing.
LIVE_HISTORY_SPAN_S: Final = 86_400.0
_LIVE_HISTORY_SPAN_US: Final = round(LIVE_HISTORY_SPAN_S * 1_000_000)
#: Registered orders not yet sent (C-2.18): past it the oldest is dropped, its watch answered None.
MAX_WATCHES: Final = 1024
#: `attach_stop`'s audit reasons and its local refusal's code.
ALREADY_SET: Final = "already_set"
STOP_REQUESTED: Final = "first_fill_attach"
STOP_REFUSED: Final = "trading_stop_refused"
PARTIAL_STOP_UNSUPPORTED: Final = "PARTIAL_STOP_UNSUPPORTED"
ADOPTED: Final = "adopted_after_lookup"
SL_ATTACHED: Final = "sl.attached"
SL_MODIFIED: Final = "sl.modified"
#: [LANE-26]: a resumed create that ends unsent, its record's action and reason, and its alert.
RESEND_REFUSED: Final = "oms.resend_refused"
EXPIRED_UNSENT_REASON: Final = "expired_unsent"
NEVER_SENT_ALERT: Final = "order_never_sent"
CLOCK_RESYNC_REASON: Final = "order_10002"
_DUPLICATE: Final = OmsErrorCode.DUPLICATE_CLIENT_ID.value
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: The stored vocabulary (21 Sec.3.3.4) as the trading port takes it (24 Sec.14.4).
_SIDES: Final[Mapping[str, Literal["buy", "sell"]]] = {"Buy": "buy", "Sell": "sell"}
_TYPES: Final[Mapping[str, Literal["market", "limit"]]] = {"Market": "market", "Limit": "limit"}
_TIFS: Final[Mapping[str, Literal["gtc", "ioc", "fok", "post_only"]]] = {
    "GTC": "gtc",
    "IOC": "ioc",
    "FOK": "fok",
    "PostOnly": "post_only",
}
_TRIGGERS: Final[Mapping[str, Literal["last", "mark", "index"]]] = {
    "LastPrice": "last",
    "MarkPrice": "mark",
    "IndexPrice": "index",
}
_DIRECTIONS: Final[Mapping[int, Literal["rise", "fall"]]] = {1: "rise", 2: "fall"}
_MODES: Final[Mapping[str, Literal["full", "partial"]]] = {"Full": "full", "Partial": "partial"}
_POSITION_IDX: Final[Mapping[int, Literal[0, 1, 2]]] = {0: 0, 1: 1, 2: 2}

#: A slice 3 service B1's `cancel` or `amend` goes to.
type CommandHandler = Callable[[b01.Command], Awaitable[Mapping[str, Any]]]
type StoredOrder = NewOrder | OrderRow


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _log_resend_refused(link: str, refusal: OrderRefused) -> None:
    """A resumed create that was not re-sent, and why: the refusal's class and its problem code."""
    _log().warning(
        "oms_resend_refused",
        order_link_id=link,
        refusal=type(refusal).__name__,
        code=problem_for(refusal).code,
    )


def order_id_kept(raw: object) -> str | None:
    """*raw* as the OMS keeps an exchange order id: B1's `text_id` (text of 1 to `b01.MAX_TEXT`
    characters, no control character), printable, and holding no whitespace, as the exchange's
    ids hold none (#4020 Low 1); else None."""
    kept = b01.text_id(raw)
    if kept is None or not kept.isprintable() or any(c.isspace() for c in kept):
        return None
    return kept


def place_request(order: StoredOrder, account: AccountRef) -> PlaceOrderRequest:
    """The create for the stored `order`, in the trading port's vocabulary, for `account`: the same
    id, terms and native stop on every send (C-2.10, C-2.6). `critical` only for a reduce-only order
    whose intent reduces (SR-E29-01; the reserve is the exits', C-12.7), else `entry`."""
    lane: OrderLane = "entry"
    if order.reduce_only and order.intent in REDUCING_INTENTS:
        lane = "critical"
    trigger_by = None if order.trigger_by is None else _TRIGGERS[order.trigger_by]
    direction = order.trigger_direction
    return PlaceOrderRequest(
        account=account,
        symbol=order.symbol,
        side=_SIDES[order.side],
        order_type=_TYPES[order.order_type],
        qty=order.qty,
        price=order.price,
        time_in_force=_TIFS[order.time_in_force],
        order_link_id=order.order_link_id,
        reduce_only=order.reduce_only,
        close_on_trigger=order.close_on_trigger,
        position_idx=_POSITION_IDX[order.position_idx],
        trigger_price=order.trigger_price,
        trigger_by=trigger_by,
        trigger_direction=None if direction is None else _DIRECTIONS[direction],
        take_profit=order.take_profit,
        stop_loss=order.stop_loss,
        tpsl_mode=_MODES[order.tpsl_mode],
        lane=lane,
    )


def found_view(order: Order) -> dict[str, Any]:
    """An order a lookup found, as B1's context names an order (`b01.full_match`, 24 Sec.8.1):
    ids and text, `reduce_only`, the order type, and money as canonical decimal text."""
    money = {
        key: None if value is None else _decimal_text(value)
        for key, value in (
            ("qty", order.qty),
            ("price", order.price),
            ("trigger_price", order.trigger_price),
            ("stop_loss", order.stop_loss),
            ("take_profit", order.take_profit),
        )
    }
    return {
        "exchange_order_id": order.exchange_order_id,
        "order_link_id": order.order_link_id,
        "account_id": str(order.account_id),
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "reduce_only": order.reduce_only,
        **money,
    }


def _decimal_text(value: Decimal) -> str:
    """Canonical decimal text, as B1 keeps money: fixed point, no exponent, no trailing zeros."""
    out = format(value, "f")
    out = out.rstrip("0").rstrip(".") if "." in out else out
    return "0" if out == "-0" else out


def _reading(position: Position) -> dict[str, Any]:
    """A protection reading (B1.5 `_reading`): the row's exchange time in ms, its stop, its size."""
    stop = position.stop_loss
    return {
        "updated_time": position.updated_at // 1_000,
        "stop_loss": None if stop is None else _decimal_text(stop),
        "size": _decimal_text(position.qty),
    }


def _shows(position: Position | None, stop: Decimal) -> bool:
    """The reading shows the requested stop on an open position, as B1's `_covers` reads it."""
    return position is not None and position.stop_loss == stop and position.qty > 0


def _record(ack: OrderAck) -> dict[str, Any]:
    """The call's allow-listed record (SR-E29-08) for the step's row; none if the port kept none."""
    return {} if ack.record is None else {"record": ack.record.model_dump(mode="json")}


def _duplicate(found: Mapping[str, Any]) -> dict[str, Any]:
    """A duplicate-id answer (24 Sec.8.3 rule 3): what the lookup found, no top-level id."""
    return {"ok": False, "error_code": _DUPLICATE, "lookup": dict(found)}


def _us(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


def _at(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


def _uuid(raw: object) -> UUID:
    if not isinstance(raw, str):
        raise ValueError("the command does not name its order")
    return UUID(raw)


def _stop_of(terms: Mapping[str, Any]) -> Decimal:
    """The stop an attach asks for: decimal text above zero (B1 stamps it so), else `ValueError`."""
    raw = terms.get("stop_loss")
    if not isinstance(raw, str):
        raise ValueError("the attach names no stop")
    try:
        stop = Decimal(raw)
    except InvalidOperation:
        raise ValueError("the attach's stop is not decimal text") from None
    if not stop.is_finite() or stop <= 0:
        raise ValueError("the attach's stop is not a price above zero")
    return stop


def _price(value: Decimal) -> bool:
    """A finite price above zero (finite first: ordering a NaN raises)."""
    return value.is_finite() and value > 0


def _check_stops(order: StoredOrder) -> None:
    """C-2.6, checked here before anything is sent, whatever the callers and the exchange port
    check: an order that is not reduce-only carries its native stop (SEC-2B1-04; `FirstPersist`
    and B1's gate refuse one without it upstream), and its stop and take-profit, where it names
    one, are finite prices above zero (#2877 ruling 2), as a zero or a negative could remove a
    protection by implication. `ValueError` otherwise, logged CRITICAL, so B1 lands the order in
    `unknown` with nothing sent."""
    link = order.order_link_id
    if not order.reduce_only and order.stop_loss is None:
        _log().critical("oms_create_stop_missing", order_link_id=link)
        raise ValueError("an order that is not reduce-only carries its native stop (C-2.6)")
    for name, value in (("stop_loss", order.stop_loss), ("take_profit", order.take_profit)):
        if value is not None and not _price(value):
            _log().critical("oms_create_price_refused", order_link_id=link, side=name)
            raise ValueError(f"the order's {name} is not a price above zero")


def _kept_take_profit(position: Position | None) -> Decimal | None:
    """The take-profit the position shows, sent back with the stop (24 Sec.8.9: one call writes
    both sides); a reading that shows no finite price above zero leaves that side out, so the venue
    keeps what it holds and nothing is removed by implication (#2877 ruling 2)."""
    take_profit = None if position is None else position.take_profit
    return take_profit if take_profit is not None and _price(take_profit) else None


def _seconds(us: int) -> str:
    """Microseconds as exact decimal seconds text: `121`, `120.000001`."""
    return _decimal_text(Decimal(us).scaleb(-6))


@dataclass(frozen=True, slots=True)
class _Expired:
    """A resumed live create no lookup found, older than the live re-send bound and younger than
    the venue's history span ([LANE-26], SEC-2B1-02)."""

    age_us: int


@dataclass(eq=False, slots=True)
class PlaceWatch:
    """The pipeline's wait on one order's create (`OmsCommandPort.expect`). `answer()` resolves once
    `place` answered B1, with the answer it gave; with None when the call raised (B1 then lands the
    order in `unknown`) or when the registration was dropped unspent (`MAX_WATCHES`). `request_id`
    is the registering HTTP request's correlation id, which the order's records carry (#3990)."""

    order: NewOrder
    _future: asyncio.Future[Mapping[str, Any] | None] = field(repr=False)
    request_id: UUID | None = None

    @property
    def answered(self) -> bool:
        return self._future.done()

    async def answer(self) -> Mapping[str, Any] | None:
        """The answer; a waiter's own cancellation never cancels it."""
        return await asyncio.shield(self._future)

    def resolve(self, answer: Mapping[str, Any] | None) -> None:
        if not self._future.done():
            self._future.set_result(answer)


class OmsCommandPort:
    """B1's `CommandPort` (module docstring), one per process with the facade it is wired into."""

    def __init__(
        self,
        *,
        router: TradingRouter,
        accounts: TradingAccounts,
        orders: OrderRepository,
        stops: RecordedStopRepository,
        handovers: OrderHandovers,
        credentials: CredentialRejections,
        clock_halt: ClockHalt,
        switches: TradingSwitches,
        audit: OrderAudit,
        submit_audit: SubmitAudit,
        gate: StopRequestGate,
        notices: OrderNotices,
        now_us: Callable[[], int],
        cancels: CommandHandler | None = None,
        amends: CommandHandler | None = None,
        submit_timeout_s: float = SUBMIT_TIMEOUT_S,
        port_timeout_s: float = PORT_TIMEOUT_S,
        live_resend_max_age_s: float = LIVE_RESEND_MAX_AGE_S,
        max_watches: int = MAX_WATCHES,
    ) -> None:
        if max_watches < 1:
            raise ValueError("max_watches holds at least one registration")
        if not 0 <= live_resend_max_age_s <= LIVE_RESEND_MAX_AGE_S:  # NaN fails it too
            raise ValueError("the live re-send bound is only ever tightened, never raised")
        self._router = router
        self._accounts = accounts
        self._orders = orders
        self._stops = stops
        self._handovers = handovers
        self._credentials = credentials
        self._clock_halt = clock_halt
        self._switches = switches
        self._audit = audit
        self._submit_audit = submit_audit
        self._gate = gate
        self._notices = notices
        self._now_us = now_us
        self._cancels = cancels
        self._amends = amends
        self._submit_timeout_s = submit_timeout_s
        self._port_timeout_s = port_timeout_s
        self._live_resend_max_age_us = round(live_resend_max_age_s * 1_000_000)
        self._max_watches = max_watches
        self._watches: OrderedDict[UUID, PlaceWatch] = OrderedDict()
        self._resync: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def resync_task(self) -> asyncio.Task[None] | None:
        """The clock resync the last `CLOCK_DRIFT` started, while one runs or has run."""
        return self._resync

    @property
    def submit_timeout_s(self) -> float:
        """The one deadline on all of a `place` (`SUBMIT_TIMEOUT_S`, CR-2B1-04), as this port
        applies it: the pipeline's wait for a create's answer must outlast it, as its default does
        with B1's turn added (`OrderSubmission`, D-2B2-01)."""
        return self._submit_timeout_s

    async def aclose(self) -> None:
        """At shutdown (slice 3's lifecycle; every task owned, C-2.18): no `CLOCK_DRIFT` starts a
        resync from here on, and the one running is cancelled and awaited. The halt stays as it
        is. A second call does nothing more."""
        self._closed = True
        task = self._resync
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.wait([task])  # its cancellation is its end; the caller's own propagates

    # --- place -----------------------------------------------------------------------------

    def expect(self, order: NewOrder, *, request_id: UUID | None = None) -> PlaceWatch:
        """Register the order the pipeline is about to send (`SEND`): its `place` builds the create
        from `order` and sends it as a first send, and the watch answers what B1 was answered. A
        second registration of the order replaces the first, which is answered None. `request_id`
        is the correlation id of the HTTP request submitting it (#3990): the order's records carry
        it, as B1's calls run in its own task, outside the request's context."""
        watch = PlaceWatch(order, asyncio.get_running_loop().create_future(), request_id)
        replaced = self._watches.pop(order.id, None)
        if replaced is not None:
            replaced.resolve(None)
        self._watches[order.id] = watch
        while len(self._watches) > self._max_watches:
            _, dropped = self._watches.popitem(last=False)
            _log().error("oms_place_watch_dropped", order_link_id=dropped.order.order_link_id)
            dropped.resolve(None)
        return watch

    def forget(self, order_id: UUID) -> None:
        """Drop the order's registration while `place` has not spent it: the pipeline's `SEND` did
        not commit, so no create leaves for it (S2-Q5). Its watch answers None."""
        watch = self._watches.pop(order_id, None)
        if watch is not None:
            watch.resolve(None)

    async def place(self, command: b01.Command) -> Mapping[str, Any]:
        """B1's create (module docstring); the order's registration, if any, is spent here."""
        watch = self._watches.pop(_uuid(command.order.get("order_id")), None)
        try:
            answer = await self._place(command, watch)
        except BaseException:
            if watch is not None:
                watch.resolve(None)
            raise
        if watch is not None:
            watch.resolve(answer)
        return answer

    async def _place(self, command: b01.Command, watch: PlaceWatch | None) -> dict[str, Any]:
        if watch is None:
            return await self._resume(command)
        _check_names(command, watch.order)
        order = watch.order
        _check_stops(order)
        by = self._deadline(self._submit_timeout_s)  # all of `place` ends by it (CR-2B1-04)
        account = await self._account(order, by=by)
        port = self._router.port_for(account.environment)
        request = place_request(order, account)
        try:
            outcome = await self._venue_gated(account, place_or_adopt(port, request), by=by)
        except RateBudgetExceededError as exc:
            _log().warning("oms_create_rate_refused", order_link_id=order.order_link_id)
            return {
                "ok": False,
                "error_code": OmsErrorCode.RATE_BUDGET_EXCEEDED.value,
                "retry_after_s": retry_after(exc.retry_after_s),
            }
        return await self._answer(command, account, outcome, watch.request_id, by=by)

    async def _resume(self, command: b01.Command) -> dict[str, Any]:
        """A create a restart resumes (module docstring, [LANE-26]), all of it by one deadline. No
        refused rate token is answered as a rejection here: the earlier create may have landed
        (`adopt_or_resend`)."""
        by = self._deadline(self._submit_timeout_s)
        row = await self._stored(command, by=by)
        account = await self._account(row, by=by)
        port = self._router.port_for(account.environment)
        request = place_request(row, account)
        resumed = self._resumed(account, port, request, row)
        outcome = await self._venue_gated(account, resumed, by=by)
        if isinstance(outcome, _Expired):
            return await self._expire(account, row, outcome.age_us, by=by)
        return await self._answer(command, account, outcome, None, by=by)

    async def _resumed(
        self, account: AccountRef, port: RoutedPort, request: PlaceOrderRequest, row: OrderRow
    ) -> PlaceOutcome | _Expired:
        """[LANE-26]'s order: the lookup whatever the switches say, the switches and the clock
        halt, the live bounds, then `adopt_or_resend`, which looks once more just before its one
        re-send (SR-E29-15) and applies rule 6 from the port's own retention (24 Sec.8.3: demo's 6
        days). A refusal is `ResendRefused`; a clock not measured yet raises `OmsNotReady` as it
        is (`ClockHalt.refusal`): both are logged `oms_resend_refused`, and nothing is sent."""
        link = request.order_link_id
        try:
            found = await find_by_link_id(port, request)
        except (AuthError, ClockDriftError):
            raise
        except ExchangeError:  # a failed read is never the order's outcome (Sec.8.3 rule 3)
            _log().warning("oms_resend_lookup_failed", order_link_id=link)
            return Unresolved(order_link_id=link, reason="lookup_failed")
        if found is not None:
            return Adopted(order=found[0], source=found[1])
        refusal: OrderRefused | None = self._switches.refusal(
            account.account_id, account.environment
        )
        if refusal is None:  # SEC-2B1-01: never a re-send under a clock a `10002` tripped
            try:
                refusal = self._clock_halt.refusal()
            except OmsNotReady as not_ready:  # no clock composed, or none measured yet (Q8)
                _log_resend_refused(link, not_ready)
                raise  # as it is: B1 lands the order in `unknown` (S1), nothing was sent
        if refusal is not None:
            _log_resend_refused(link, refusal)
            raise ResendRefused(refusal)
        retention = HistoryRetentionPolicy.from_capabilities(port.capabilities)
        created, now = _us(row.created_ts), self._now_us()
        age = now - created
        if retention.retention_days is None and age > self._live_resend_max_age_us:
            if age >= _LIVE_HISTORY_SPAN_US:  # SEC-2B1-02: a miss there proves nothing
                _log().warning("oms_resend_past_history", order_link_id=link, age_s=_seconds(age))
                return Unresolved(order_link_id=link, reason="history_expired")
            return _Expired(age_us=age)
        _check_stops(row)
        return await adopt_or_resend(
            port, request, retention=retention, created_at=created, now=now
        )

    async def _expire(
        self, account: AccountRef, row: OrderRow, age_us: int, *, by: float
    ) -> dict[str, Any]:
        """[LANE-26]: a resumed create past the live bound that no lookup found within the venue's
        history span ends unsent, through `submitting`'s last arm (`rejected`,
        `b01.EXPIRED_UNSENT`). Its record is written ahead (C-2.9: one that does not land raises,
        so B1 lands the order in `unknown`), then the user is alerted that the order was not found
        within the venue's 24 h history; an alert that does not land, by `place`'s deadline or at
        all, is logged CRITICAL, never dropped silently: the order's end and its record stand."""
        link = row.order_link_id
        age_s, bound_s = _seconds(age_us), _seconds(self._live_resend_max_age_us)
        detail = {"order_link_id": link, "age_s": age_s, "bound_s": bound_s}
        reason = EXPIRED_UNSENT_REASON
        await self._audit_order(
            row.id, account.account_id, RESEND_REFUSED, "denied", "warning", reason, detail, by=by
        )
        _log().warning("oms_resend_expired", order_link_id=link, age_s=age_s, bound_s=bound_s)
        when = row.created_ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        alert = {"alert": NEVER_SENT_ALERT, "created_at": row.created_ts.isoformat()}
        alert["message"] = (
            f"an order from {when} was not found within the venue's 24 h history and was not "
            "placed; re-enter it if still wanted"
        )
        notice = OrderNotice("alert", row.id, row.exchange_account_id, link, alert)
        try:
            await self._bounded(self._notices.notify(notice), by=by)
        except Exception as exc:  # the alert is lost, never the order's end or its record
            lost = type(exc).__name__
            _log().critical("oms_never_sent_alert_lost", order_link_id=link, failure=lost)
        return {"ok": False, "error_code": b01.EXPIRED_UNSENT}

    async def _answer(
        self,
        command: b01.Command,
        account: AccountRef,
        outcome: PlaceOutcome,
        request_id: UUID | None,
        *,
        by: float,
    ) -> dict[str, Any]:
        if isinstance(outcome, Sent):
            return await self._sent(account, outcome.ack, by=by)
        if isinstance(outcome, Adopted):
            found = found_view(outcome.order)
            order, source = outcome.order, outcome.source
            if await self._settled_found(command, account, order, found, source, request_id, by=by):
                return _duplicate(found)
            return _duplicate({})
        _log().warning(
            "oms_create_unresolved", order_link_id=outcome.order_link_id, reason=outcome.reason
        )
        if outcome.reason == "resend_unconfirmed":
            # The venue may hold the order under the id (a duplicate, an ambiguous re-send, a
            # refused token): a duplicate with no lookup, so B1 looks the id up at once (24 Sec.8.3
            # rule 3) and binds it only on its full match, never under a new id ([LANE-26]).
            return {"ok": False, "error_code": _DUPLICATE}
        return _duplicate({})

    async def _sent(self, account: AccountRef, ack: OrderAck, *, by: float) -> dict[str, Any]:
        if ack.ok:
            kept = order_id_kept(ack.exchange_order_id)
            if kept is None:
                _log().error("oms_ack_without_order_id", order_link_id=ack.order_link_id)
                raise AckWithoutOrderId(
                    "an accepted create names no exchange order id the OMS keeps"
                )
            return {"ok": True, "exchange_order_id": kept, **_record(ack)}
        await self._venue(account, ack.error_code, ack.exchange_ret_code, by=by)
        refused = {"ok": False, "error_code": ack.error_code}
        return {**refused, "exchange_ret_code": ack.exchange_ret_code, **_record(ack)}

    async def _settled_found(
        self,
        command: b01.Command,
        account: AccountRef,
        order: Order,
        found: Mapping[str, Any],
        source: str,
        request_id: UUID | None,
        *,
        by: float | None = None,
    ) -> bool:
        """What a lookup found under the row's id, settled before the answer: a full match is
        audited as adopted (C-2.9), with the registering request's id when there is one, and True;
        another order is handed to reconciliation first, True once it is, False when it cannot be
        (S2-Q3). Each call ends by `by`, `place`'s deadline, when there is one."""
        try:
            match = b01.full_match(command.order, found)
        except ValueError:  # malformed money, which B1's guards deny too
            match = False
        link = order.order_link_id
        if match:
            detail = {"order_link_id": link, "exchange_order_id": order.exchange_order_id}
            detail |= {"source": source, "exchange_state": order.state}
            order_id = _uuid(command.order.get("order_id"))
            await self._audit_order(
                order_id,
                account.account_id,
                "orders.submit",
                "success",
                "warning",
                ADOPTED,
                detail,
                request_id=request_id,
                by=by,
            )
            _log().info("oms_create_adopted", order_link_id=link, source=source)
            return True
        _log().error("oms_link_id_held_by_another_order", order_link_id=link, source=source)
        try:
            await self._bounded(self._handovers.hand_over_order(account.account_id, order), by=by)
        except Exception as exc:  # S2-Q3: nothing handed over, so nothing is held on it
            _log().error("oms_handover_failed", order_link_id=link, failure=type(exc).__name__)
            return False
        return True

    # --- lookup ----------------------------------------------------------------------------

    async def lookup(self, command: b01.Command) -> Mapping[str, Any]:
        """The id in open orders, then in history (24 Sec.8.3 rule 3): the order found, or an
        empty mapping, on which B1 sends the create. A found order is settled as `place` settles
        it; one not handed over raises `HandoverUnavailable`, so B1 sends nothing. A failed read
        raises, the venue's outage included (#2863), and is never repeated here."""
        order, request_id = await self._order_of(command)
        account = await self._account(order)
        port = self._router.port_for(account.environment)
        request = place_request(order, account)
        by = self._deadline(self._port_timeout_s)
        found = await self._venue_gated(account, find_by_link_id(port, request), by=by)
        if found is None:
            return {}
        exchange_order, source = found
        view = found_view(exchange_order)
        settled = await self._settled_found(
            command, account, exchange_order, view, source, request_id
        )
        if not settled:
            raise HandoverUnavailable("the order found under the id was not handed over")
        return view

    # --- attach_stop -----------------------------------------------------------------------

    async def attach_stop(self, command: b01.Command) -> Mapping[str, Any]:
        """The stop B1 asks for after the first fill (24 Sec.8.8 rule 2), read back afresh on
        every call (INV-B1-f; module docstring)."""
        stop = _stop_of(command.terms)
        account_id, order_id = (
            _uuid(command.order.get("account_id")),
            _uuid(command.order.get("order_id")),
        )
        row = await self._bounded(self._orders.get(account_id, order_id))
        if row is None:
            raise ValueError("no stored order of the account has the command's id")
        detail = {"order_link_id": row.order_link_id, "symbol": row.symbol}
        detail["position_idx"] = str(row.position_idx)
        if row.tpsl_mode != "Full":  # Q-F: no stop size until G-8b's `sl_size` (#3963; 24 Sec.8.9)
            await self._audit_order(
                order_id, account_id, SL_ATTACHED, "denied", "error", "partial_mode", detail
            )
            _log().error("oms_partial_stop_refused", order_link_id=row.order_link_id)
            return {"ok": False, "error_code": PARTIAL_STOP_UNSUPPORTED}
        account = await self._account(row)
        port = self._router.port_for(account.environment)
        before = await self._position(account, port, row)
        if before is not None and _shows(before, stop):  # Q-E: no call, but the trail (C-2.9)
            await self._audit_order(
                order_id, account_id, SL_ATTACHED, "success", "info", ALREADY_SET, detail
            )
            return {"ok": True, "position": _reading(before)}
        key = PositionKey(account.account_id, row.symbol, row.position_idx)
        await self._bounded(self._gate.clear(key))  # whatever the gate bounds itself (C-2.18)
        recorded = await self._record_stop(row, stop, detail)
        request = TradingStopRequest(
            account=account,
            symbol=row.symbol,
            position_idx=_POSITION_IDX[row.position_idx],
            stop_loss=stop,
            take_profit=_kept_take_profit(before),
        )
        by = self._deadline(self._submit_timeout_s)  # a raise leaves the row in flight
        ack = await self._venue_gated(account, port.set_trading_stop(request), by=by)
        if not ack.ok:
            await self._venue(account, ack.error_code, ack.exchange_ret_code)
        await self._settle_stop(recorded, ack, detail)
        after = await self._position(account, port, row)
        answer: dict[str, Any] = {"ok": ack.ok}
        if not ack.ok:
            answer |= {"error_code": ack.error_code, "exchange_ret_code": ack.exchange_ret_code}
        if after is not None:
            answer["position"] = _reading(after)
        return answer

    async def _record_stop(
        self, row: OrderRow, stop: Decimal, detail: Mapping[str, str | None]
    ) -> tuple[RecordedStopRow, ...]:
        """The request's stop-loss row, written ahead with its `sl.attached` record in the insert's
        transaction (21 Sec.3.3.11), which the row names (`audit_record_id`)."""
        stop_id = uuid4()
        new = NewRecordedStop(
            id=stop_id,
            exchange_account_id=row.exchange_account_id,
            symbol=row.symbol,
            position_idx=_POSITION_IDX[row.position_idx],
            position_side=row.side,
            kind="stop_loss",
            source="trading_stop",
            order_id=None,
            tpsl_mode="Full",
            trigger_price=stop,
            size=None,
            audit_record_id=self._submit_audit.record_id(SL_ATTACHED, str(stop_id)),
            actor_user_id=None,
        )
        record = _stop_record(SL_ATTACHED, new, "success", "info", STOP_REQUESTED, detail)

        async def requested(_rows: tuple[RecordedStopRow, ...]) -> None:
            await self._submit_audit.write(record)

        return await self._bounded(self._stops.record([new], write_ahead=requested))

    async def _settle_stop(
        self, recorded: tuple[RecordedStopRow, ...], ack: OrderAck, detail: Mapping[str, str | None]
    ) -> None:
        """The request's answer on its rows: `answered`, or `refused`, its void audited
        `sl.modified` ahead. A settle that fails leaves the rows in flight, for the complete read
        (21 Sec.3.3.11), and is logged: the exchange's answer stands."""
        ids = [row.id for row in recorded]
        account_id, at = recorded[0].exchange_account_id, _at(self._now_us())
        try:
            if ack.ok:
                await self._bounded(self._stops.settle(account_id, ids, "answered", at=at))
                return
            voided = {**detail, "error_code": ack.error_code}
            records = [
                _stop_record(SL_MODIFIED, row, "denied", "warning", STOP_REFUSED, voided)
                for row in recorded
            ]

            async def void(_rows: tuple[RecordedStopRow, ...]) -> None:
                for record in records:
                    await self._submit_audit.write(record)

            await self._bounded(
                self._stops.settle(account_id, ids, "refused", at=at, write_ahead=void)
            )
        except Exception as exc:  # the rows stay in flight, which only the complete read ends
            _log().error("oms_stop_settle_failed", answered=ack.ok, failure=type(exc).__name__)

    # --- cancel and amend: slice 3's services ----------------------------------------------

    async def cancel(self, command: b01.Command) -> Mapping[str, Any]:
        """A cancel, or a KILL's (`kill_cancel`), through slice 3's audited service (SR-E29-06)."""
        if self._cancels is None:
            raise b01.PortMissingError("no cancel service is wired yet (slice 3)")
        return await self._cancels(command)

    async def amend(self, command: b01.Command) -> Mapping[str, Any]:
        """An amend, through slice 3's audited service."""
        if self._amends is None:
            raise b01.PortMissingError("no amend service is wired yet (slice 3)")
        return await self._amends(command)

    # --- the rest ----------------------------------------------------------------------------

    async def _stored(self, command: b01.Command, *, by: float | None = None) -> OrderRow:
        """The command's order as stored: by its account and `order_link_id`, and the same id."""
        link = b01.text_id(command.order.get("order_link_id"))
        if link is None:
            raise ValueError("the command names no order_link_id")
        account_id = _uuid(command.order.get("account_id"))
        row = await self._bounded(self._orders.get_by_link_id(account_id, link), by=by)
        if row is None:
            raise ValueError("no stored order of the account holds the command's id")
        _check_names(command, row)
        return row

    async def _order_of(self, command: b01.Command) -> tuple[StoredOrder, UUID | None]:
        """The registered order (unspent) and its request's id, else the stored one and None;
        either named as the command is."""
        watch = self._watches.get(_uuid(command.order.get("order_id")))
        if watch is None:
            return await self._stored(command), None
        _check_names(command, watch.order)
        return watch.order, watch.request_id

    async def _account(self, order: StoredOrder, *, by: float | None = None) -> AccountRef:
        """The order's account as the trading port takes it, with its own key (SR-E27-21)."""
        account_id = AccountId(order.exchange_account_id)
        account = await self._bounded(self._accounts.trading_account(account_id), by=by)
        if account.account_id != order.exchange_account_id:
            raise ValueError("the trading account resolved is another account's")
        return account

    async def _position(
        self, account: AccountRef, port: RoutedPort, row: OrderRow
    ) -> Position | None:
        read = read_position(port, account, row.symbol, row.position_idx)
        return await self._venue_gated(account, read, by=self._deadline(self._port_timeout_s))

    def _deadline(self, seconds: float) -> float:
        """The loop's time `seconds` from now: a deadline one call, or all of `place`, ends by."""
        return asyncio.get_running_loop().time() + seconds

    async def _bounded[T](self, call: Awaitable[T], *, by: float | None = None) -> T:
        """`call` within `PORT_TIMEOUT_S`, and by `by` (`place`'s deadline, CR-2B1-04) when that
        comes first: each call keeps a timeout of its own, so a caller that catches one (a
        best-effort report, a hand-over, an alert) still catches it at the deadline."""
        when = self._deadline(self._port_timeout_s)
        async with asyncio.timeout_at(when if by is None else min(when, by)):
            return await call

    async def _venue_gated[T](self, account: AccountRef, call: Awaitable[T], *, by: float) -> T:
        """The exchange `call`, by `by`; then, out of its window, 24 Sec.8.6's branch for a
        raised `AuthError` or `ClockDriftError`, its report bounded on its own (and by `by`)."""
        try:
            async with asyncio.timeout_at(by):
                return await call
        except (AuthError, ClockDriftError) as exc:
            await self._venue(account, exc.code.value, exc.exchange_ret_code, by=by)
            raise

    async def _venue(
        self,
        account: AccountRef,
        code: str | None,
        ret_code: int | None,
        *,
        by: float | None = None,
    ) -> None:
        """24 Sec.8.6, before the answer (module docstring). Its own failures are logged, never
        raised: the exchange's answer stands."""
        if code == OmsErrorCode.CLOCK_DRIFT:
            self._clock_halt.trip()
            _log().critical("oms_clock_drift_halt", environment=account.environment)
            if not self._closed and (self._resync is None or self._resync.done()):
                resync = self._clock_halt.resync(reason=CLOCK_RESYNC_REASON)
                self._resync = spawn(resync, name="oms-clock-resync")
        elif code == OmsErrorCode.AUTH_ERROR and ret_code is not None:
            try:  # the call too: a port that raises before awaiting loses only the report
                refused = self._credentials.refused(
                    account.account_id, error_code=code, exchange_ret_code=ret_code
                )
                await self._bounded(refused, by=by)
            except Exception as exc:  # the rejection is lost, never the order's answer
                _log().critical("oms_auth_rejection_lost", failure=type(exc).__name__)

    async def _audit_order(
        self,
        order_id: UUID,
        account_id: UUID,
        action: str,
        outcome: AuditOutcome,
        severity: AuditSeverity,
        reason: str,
        detail: Mapping[str, str | None],
        *,
        request_id: UUID | None = None,
        by: float | None = None,
    ) -> None:
        """A record about the order, written ahead of its answer (C-2.9): one that does not land,
        by `by` when given, raises, so nothing is answered unrecorded. `request_id` is the
        registering request's (#3990), never read from the context the call runs in."""
        record = OrderAuditRecord(
            action, order_id, account_id, outcome, severity, reason, detail, request_id
        )
        await self._bounded(self._audit.write(record), by=by)


def _check_names(command: b01.Command, order: StoredOrder) -> None:
    """The command names `order` (its id, `order_link_id` and account), else `ValueError`."""
    named = tuple(command.order.get(key) for key in ("order_id", "order_link_id", "account_id"))
    if named != (str(order.id), order.order_link_id, str(order.exchange_account_id)):
        raise ValueError("the command names another order than the stored one")


def _stop_record(
    action: str,
    row: NewRecordedStop | RecordedStopRow,
    outcome: AuditOutcome,
    severity: AuditSeverity,
    reason: str,
    detail: Mapping[str, str | None],
) -> KeyedRecord:
    """A stop request's record, the row its object and the row's id its name (21 Sec.3.3.11)."""
    return KeyedRecord(
        action=action,
        name=str(row.id),
        account_id=row.exchange_account_id,
        object_kind="recorded_stop",
        object_id=row.id,
        outcome=outcome,
        severity=severity,
        reason=reason,
        actor_user_id=None,
        detail={**detail, "kind": row.kind, "source": row.source},
    )
