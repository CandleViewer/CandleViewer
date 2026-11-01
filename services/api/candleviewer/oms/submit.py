"""The order submission pipeline (E29-T04 #913; 24-internal-schemas.md Sec.8.4, 22 `placeOrder`).

`OrderSubmission.submit(request, context)` takes one `placeOrder` request the route has admitted
(slice 3: authentication, CSRF, the session, RBAC and account scope, the arm token, the replay
lookup and the first `trading_disabled` checks, 24 Sec.8.4 point 1; a viewing session's write is
refused before the pipeline by `view_as_guard`, #4040). It answers a `SubmitOutcome`, a 202, 429
or 502, once the order is recorded and sent, or raises the refusal the route renders
(`errors.PROBLEMS`), nothing sent. The steps, each refusing before the next runs:

1. the clock halt (503 `clock_drift` with `Retry-After`, counted in
   `oms_clock_drift_blocked_total`), then the read-only gate (403 `trading_disabled`);
2. the account the order is signed for, by its id alone (`TradingAccounts`, SR-E27-21), the route
   of its environment (C-2.11: a miswired one is a 500 that pages), the instrument (400 for a
   symbol none lists) and the effective profile (a named one the account does not hold, another
   account's, a deleted or a missing one alike, is 404 `not_found`; with none named and no
   default, an entry is refused at step 4, D11); a read that fails or does not answer within
   `store_timeout_s` is 503 `store_unavailable`;
3. the size step (24 Sec.8.4 item 2, #913 S4-S): 3a the market read and the price band, 3b the
   reference price (24 Sec.9.3 step 2), 3c the size: an entry by its effective profile's sizer
   (`oms.sizing`, which answers each outcome but `ok` as 22 maps it, `figure_unknown` 503
   `sizing_unavailable`, and refuses whole a request's sizing, stop or take-profit that goes past
   the profile), a reduce-only order by its request's qty (`RequestQtySizer`); 3d the effect on the
   exchange-truth position (SR-E29-01, read for a reduce-only order only, within
   `position_timeout_s`), the native stop and the intent (`NativeStopGuard`, C-2.6, over the
   sizer's own stop for an entry), the take-profit (S2-Q6), then the `SizedOrder`. A reduce-only
   close its route marked `SubmitContext.protective` that this read does not show reducing its
   position (flat, on the other side, or smaller than the close) is refused here,
   `PositionChanged` naming `position_flat` or `exceeds_position`, never re-sized (E29-S03 BQ-7):
   the close routes answer it 422, as their own step 13 does. Two entries on
   one account are sized in turn: each holds the account's turn (`ENTRY_TURNS`) through its
   answer, and once its order is recorded the account's figures are dropped
   (`OrderFigures.invalidate`), so the next one is sized against the room this one took. A stop or a
   take-profit that is no finite price above zero is refused here, before anything is recorded,
   whatever the command port and the exchange port check later (#2877 ruling 2). A reduce-only
   order carries neither where the route's venue sets none on one
   (`ExchangeCapabilities.supports_reduce_only_tpsl`, C-2.2): one that names either is refused
   first, before any read, and one the profile's offset would give a stop (not shown to reduce,
   so an entry) after the guard, both `reduce_only_tpsl`, never a late rejection at the venue.
   A read this step needs that fails is 503 `exchange_unavailable` with `Retry-After` (Q-B);
4. `Validator.check_order` on the sized, rounded order (SR-E29-04): 400, or 403 for the profile;
   a reduce-only close of the whole position step 3d's read showed is exempt from `min_order_qty`
   (the orchestrator's ruling (a) of 2026-11-01, C-2.6), and its `orders.submit` record names the
   exemption (`exemption: min_order_qty_whole_close`);
5. the risk gate on that order (403 `risk_limit_breached`);
6. the synchronous switches (live trading, the B18 kill switch, the order-entry gate), ruling R1's
   second check, just before anything is recorded (403 `trading_disabled`, the gate's with its
   `reason`); a reduce-only order whose route marked it `SubmitContext.protective` (a close, the
   C-2.6 carve-out of 24 Sec.8.10) passes those three here and at `SEND`, never the fence;
7. rate point 1: the account's headroom in the order's lane, which takes no token (429
   `exchange_rate_limited` with `Retry-After`, nothing recorded and no key bound);
8. the `order_link_id` (24 Sec.8.3 rules 1 and 5; spent: 500, which pages);
9. the first persist, B1's `VALIDATE`: one transaction (`SubmissionRepository.create_first`,
   through B1's step writer) of an entry's one-leg group and leg, the `validated` row and its
   event, the entry's recorded stops and the replay anchor, with the request's records written
   ahead of the commit (C-2.9: `orders.submit`, `trade_group.submit`, and `sl.attached`, or
   `tp.modified` for a take-profit side, keyed by the row each names). For an entry the
   stop-request gate clears the position's key first (21 Sec.3.3.11: a row waiting for the
   complete read is 409 `stop_request_in_flight`, `Retry-After` 5, at once), and a stop request
   in flight is tried again twice (Q-D: after 0.1 s, then 0.25 s), then 409 with `Retry-After` 1,
   the key unbound. A taken `order_link_id` is allocated again from the same candidate (rule 5);
   a held key is answered as a repeat (`AnchorService.after_taken`), a `202` one with its order's
   reconciled state, `reconciling` while B1 has not resolved it (never an assumed success); the
   share-locked re-check's refusals are 403; an audit that does not land is 503
   `audit_unavailable`; any other refusal 503 `store_unavailable`; a write whose outcome is
   unknown goes on only when the rebuilt order is `validated`, else it is 503 too, paged when no
   machine holds the order (a `validated` row it may have left has no owner until the startup
   sweep);
10. `SEND`, once the command port holds the order (`OmsCommandPort.expect`, with the request's
   correlation id). A `SEND` that did not commit sent nothing: the order is abandoned (S2-Q5, a
   KILL from `validated`, tried twice, paged when it fails) and the request is refused, 503 (or
   the switch that refuses it now). One whose outcome is unknown is followed once the rebuilt
   order has left `validated`; an order still `validated`, or with no machine, is answered 503 as
   one refused: this request sends nothing and leaves its anchor undecided (C-2.10: a repeat
   within `CV_OMS_INFLIGHT_STUCK_S` is 409 in flight, a later one the reconciled state), and a
   `submitting` row whose commit was lost is resumed by a restart's hydration (#4006), under its
   persisted id: looked up first, sent again only within 24 Sec.8.3 rule 6's re-send bound;
11. the answer, once B1 has the create's outcome: `submitted`, `held` and `unknown` (the venue's
   outage among them, #2863) are 202; `rejected` with `RATE_BUDGET_EXCEEDED` is 429 (rate point
   2); any other `rejected` is 502 `exchange_error` with the exchange's return code only
   (SR-E29-09), `10002` included, which the command port has made halt order entry. Then, best
   effort and never turning the answer into a 503: the anchor's outcome by compare-and-set, the
   leg's and the group's status by compare-and-set (S2-Q4: `submitted`, or `rejected` and
   `failed`; a `held` order's leg is left as it is), the outcome's record and the metrics.

Every refusal is audited (`orders.submit`, outcome `denied`, its problem code) before it is
raised; one whose record does not land is answered 503 `audit_unavailable` instead (C-2.9). Each
record names the requesting principal and carries the request's correlation id ([AUDIT-REQUEST-ID],
#3990). Once the anchor exists, the bounds (`SEND`'s write, `place_wait_s`, `result_wait_s`, then
the anchor's, the leg's and the group's compare-and-sets and the outcome's record, each
`store_timeout_s`) total 17 s by default; the pipeline refuses to be built with bounds that total
the anchor service's `stuck_after_s` (`CV_OMS_INFLIGHT_STUCK_S`, 30 s by default) or more, the
threshold a repeat meets, so a repeat meets the outcome this request records, or with a
`place_wait_s` that does not outlast the command port's deadline (`submit_timeout_s`; the default
adds B1's turn to it), so the first answer can be the create's own (D-2B2-01).
Logs carry ids, codes and state names, never a price, a size, the key or the fingerprint (21
Sec.12, C-12.6).
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, localcontext
from types import MappingProxyType
from typing import Any, Final, Literal
from uuid import UUID, uuid4, uuid5

import structlog
from pydantic import ValidationError

from candleviewer.accounts.errors import (
    AccountNotFoundError,
    ProfileUnavailableError,
    TradeGroupStaleError,
)
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.sizer_metrics import SizerMetrics
from candleviewer.accounts.trade_group_repository import TradeGroupRepository
from candleviewer.accounts.trade_groups import (
    GroupUpdate,
    LegDraft,
    LegUpdate,
    TradeGroupDraft,
    group_values,
    leg_values,
)
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import (
    AccountId,
    Environment,
    GroupId,
    Px,
    Qty,
    Side,
    Symbol,
    UserId,
)
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.models import AccountRef, OrderLane
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.tracing import inject_context, span
from candleviewer.settings import OMS_PRICE_BAND_DEFAULT, OMS_PRICE_BAND_MAX, OMS_PRICE_BAND_MIN
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_PERSIST_TIMEOUT
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.idempotency_anchors import (
    MAX_RET_CODE,
    MIN_RET_CODE,
    AnchorOperation,
    AnchorOutcome,
    AnchorStatus,
    NewAnchor,
)
from candleviewer.storage.repositories.orders import (
    NewOrder,
    OrderSide,
    OrderStoreError,
    TimeInForce,
    TpslMode,
    TriggerBy,
)
from candleviewer.storage.repositories.orders import OrderType as ColumnOrderType
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, StopKind
from candleviewer.storage.repositories.submissions import FirstPersist, FirstPersisted
from candleviewer.storage.repositories.trade_groups import NewTradeGroup, NewTradeGroupLeg

from .classify import (
    REDUCING_INTENTS,
    ExchangePosition,
    NativeStopGuard,
    position_effect,
    take_profit_errors,
)
from .clock_halt import ClockHalt
from .commands import SUBMIT_TIMEOUT_S, OmsCommandPort, PlaceWatch
from .errors import (
    INTERNAL_ERROR,
    PROBLEMS,
    RULE_EXCEEDS_POSITION,
    RULE_POSITION_FLAT,
    RULE_PRICE_BAND,
    RULE_REDUCE_ONLY_TPSL,
    AnchorTaken,
    AuditNotDurable,
    DuplicateOrderLinkId,
    ExchangeUnavailable,
    FieldError,
    OmsError,
    OrderInvalid,
    OrderLinkIdExhausted,
    OrderStepRefused,
    OrderStepUnknown,
    PositionChanged,
    ProfileNotFound,
    RateBudgetExceeded,
    RiskRefused,
    SizingUnavailable,
    StopRequestInFlight,
    StopRequestPending,
    StopUnitUnsupported,
    StoreUnavailable,
    SubmissionRefused,
    TradingDisabled,
    problem_for,
)
from .idempotency import AnchorService, InFlight, KeyReuse, Replay
from .order_link import OrderLinkIdParts, OrderPurpose
from .order_link_allocator import MAX_SEQ_INCREMENTS, OrderLinkIdAllocator
from .order_machine import OrderMachines
from .ports import (
    NO_TIER_REQUESTS,
    AuditOutcome,
    AuditSeverity,
    Instruments,
    KeyedRecord,
    MarketReading,
    OrderEffect,
    OrderFigures,
    OrderType,
    PositionKey,
    Profiles,
    ReferencePrices,
    RequestObject,
    RequestQtySizer,
    RequestRecord,
    SizedOrder,
    SizingRequest,
    StopOffset,
    StopRequestGate,
    SubmissionPorts,
    SubmitActor,
    SubmitAudit,
    TierRequests,
    TradingAccounts,
    TradingSwitches,
)
from .routing import RoutedPositions, TradingRouter, Transport
from .sizing import SIZING_RETRY_AFTER_S, EntryIntent, EntrySize, EntrySizer
from .validator import EXEMPT_WHOLE_CLOSE, Validator, closes_whole

__all__ = [
    "EXCHANGE_ERROR", "PLACE_WAIT_S", "POSITION_TIMEOUT_S", "RATE_LIMITED", "READ_RETRY_AFTER_S",
    "RECONCILING", "RESULT_WAIT_S", "STOP_RETRIES_S", "STOP_RETRY_AFTER_S", "STORE_TIMEOUT_S",
    "OrderRequest", "OrderSubmission", "OrderTrigger", "SubmissionDeps", "SubmitActor",
    "SubmitContext", "SubmitOutcome", "WrittenRows", "entry_order_id",
]  # fmt: skip

#: The bound on each store read and write of the pipeline, in seconds: the account, the
#: instrument, the profile, the allocation's lookups, the stop-request gate's read, each audit
#: record and each compare-and-set after the send.
STORE_TIMEOUT_S: Final = 2.0
#: The bound on each exchange read before the persist, in seconds: a reduce-only order's position
#: and a market order's reference price.
POSITION_TIMEOUT_S: Final = 2.0
#: The orchestrator's Q-D ruling: a first persist that met a stop request in flight on its
#: position (`ux_rs_in_flight`) is tried again after these waits, in seconds, then refused 409
#: `stop_request_in_flight` with `STOP_RETRY_AFTER_S`.
STOP_RETRIES_S: Final = (0.1, 0.25)
STOP_RETRY_AFTER_S: Final = 1
#: The `Retry-After` of a read the order needed that failed (Q-B), in seconds: a position or a
#: reference price is read again at the next request. The orchestrator's ruling of 2026-10-22
#: keeps it 1 s, under this one name, which every such refusal answers.
READ_RETRY_AFTER_S: Final = 1
#: How long the pipeline waits for B1's answer to the create once `SEND` committed, in seconds, by
#: default (`place_wait_s`): the command port's one deadline on all of `place`, its reads, calls
#: and answer (`commands.SUBMIT_TIMEOUT_S`, CR-2B1-04), and one second for B1's own turn. Past it
#: the outcome is not known yet: 202, as `unknown` is.
PLACE_WAIT_S: Final = SUBMIT_TIMEOUT_S + 1.0
#: How long it then waits for the order to leave `submitting`, in seconds, by default
#: (`result_wait_s`): the result step's write (`CV_PERSIST_TIMEOUT`) and one second for the
#: facade's turn.
RESULT_WAIT_S: Final = CV_PERSIST_TIMEOUT + 1.0
#: The problem code of each answer the anchor records (21 Sec.3.3.10, `AnchorOutcome.code`).
RATE_LIMITED: Final = "exchange_rate_limited"
EXCHANGE_ERROR: Final = "exchange_error"
#: A `202` repeat's state while B1 has not resolved its order (the orchestrator's ruling of
#: 2026-10-22, C-2.10): the answer says so rather than assume a success.
RECONCILING: Final = "reconciling"
#: `oms.submit`'s `result` for a 202 (20 Sec.12.3); a 429 or a 502 is its own code, a refusal its
#: problem's.
_ACCEPTED: Final = "accepted"
#: The states whose create has no known outcome yet: `validated` was never sent (slice 3's
#: startup kills it), `submitting` is in flight or lost (a restart's hydration resumes it under its
#: id, within 24 Sec.8.3 rule 6), `unknown` and `quarantined` wait for reconciliation (24 Sec.8.5).
_UNRESOLVED: Final = frozenset({"validated", "submitting", "unknown", "quarantined"})
#: An entry's order is its one-leg group's only order, its id named from the group's under this
#: namespace (fixed for good), so a repeat holding the group's anchor finds the order with no
#: group read (`entry_order_id`).
_ENTRY_ORDERS: Final = UUID("0973ace5-8b31-4bc2-9a01-6d69961a0f75")
#: The sides a reduce-only order may not carry where its venue sets neither on one, and their
#: sentences (one rule, one shape).
_REDUCE_ONLY_SIDES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "stop_loss": "A reduce-only order carries no stop-loss.",
        "take_profit": "A reduce-only order carries no take-profit.",
    }
)
_CODES: Final[Mapping[int, str | None]] = MappingProxyType(
    {202: None, 429: RATE_LIMITED, 502: EXCHANGE_ERROR}
)
#: Every synchronous check ran and passed before `VALIDATE`, which records the verdicts and
#: decides none of them (C-2.21, B1's `passes_all_gates`).
_PASSED: Final[Mapping[str, str]] = MappingProxyType(dict.fromkeys(b01.GATES, b01.PASSED))
#: The records the pipeline writes (`audit.actions`; 24 Sec.15.5) and their reasons.
SUBMIT_ACTION: Final = "orders.submit"
GROUP_ACTION: Final = "trade_group.submit"
_STOP_ACTIONS: Final[Mapping[StopKind, str]] = MappingProxyType(
    {"stop_loss": "sl.attached", "take_profit": "tp.modified"}
)
_ENTRY_ATTACH: Final = "entry_attach"
#: A protective close the venue's read does not show reducing (E29-S03 BQ-7): its sentences.
_NOW_FLAT: Final = "The position is flat now, so the close was not sent."
_NOW_SMALLER: Final = "The position is now smaller than the close, so it was not sent."
_ABANDONED: Final = "send_refused"
_AUDIT_UNAVAILABLE: Final = PROBLEMS[AuditNotDurable].code
_RATE_CODE: Final = OmsErrorCode.RATE_BUDGET_EXCEEDED.value
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: 22's vocabulary as the columns store it (21 Sec.3.3.4) and as a group's draft takes it.
_SIDES: Final[Mapping[Side, OrderSide]] = MappingProxyType({"buy": "Buy", "sell": "Sell"})
_TYPES: Final[Mapping[OrderType, ColumnOrderType]] = MappingProxyType(
    {"market": "Market", "limit": "Limit"}
)
_DIRECTIONS: Final[Mapping[str, Literal[1, 2]]] = MappingProxyType({"rise": 1, "fall": 2})
_GROUP_TRIGGERS: Final[Mapping[TriggerBy, Literal["last", "mark", "index"]]] = MappingProxyType(
    {"LastPrice": "last", "MarkPrice": "mark", "IndexPrice": "index"}
)
#: The striped turns of the size step (#913 S4-S): two entries on one account whose size steps
#: overlap are judged one after the other, each holding its account's turn from the size step
#: through its send's answer and the figures' `invalidate`. A fixed set: two accounts may share a
#: turn, which only orders them.
ENTRY_TURNS: Final = 64


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _seconds(name: str, value: float) -> float:
    """A bound in seconds: a finite number above zero (C-2.18)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} is a number of seconds")
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a finite number of seconds above zero")
    return float(value)


def _delay(value: float) -> float:
    """A wait before a retry, in seconds: a finite number, 0 or more."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("a retry's wait is a number of seconds")
    if not (math.isfinite(value) and value >= 0):
        raise ValueError("a retry's wait is a finite number of seconds, 0 or more")
    return float(value)


def _us(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


def _after_anchor_s(*, store_timeout_s: float, place_wait_s: float, result_wait_s: float) -> float:
    """The request's bounds once its anchor exists, in seconds (module docstring): `SEND`'s write
    (`CV_PERSIST_TIMEOUT`), the create's answer, its result step, then the anchor's, the leg's and
    the group's compare-and-sets and the outcome's record, each `store_timeout_s`."""
    return CV_PERSIST_TIMEOUT + place_wait_s + result_wait_s + 4 * store_timeout_s


# --- The request, its context and its answer ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderTrigger:
    """22 `TriggerSpec`: a conditional order's trigger price, the price it watches (22 `TriggerBy`,
    as the column stores it) and the direction that fires it."""

    price: Px
    direction: Literal["rise", "fall"]
    trigger_by: TriggerBy = "LastPrice"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """A `placeOrder` body (22 `PlaceOrderRequest`) once the route has parsed it, in 22's
    vocabulary: the account, the symbol, the side, the type, the sizing and the intent, the price,
    the time in force, the flags, the trigger, the stop-loss and take-profit offsets and their
    mode, the profile override and the note. No field selects a key, an environment, a group or an
    id: the server resolves and mints them (SR-E27-21, 24 Sec.8.3 rule 1). No emulated algo is
    placed through it yet (`algo`)."""

    account_id: AccountId
    symbol: Symbol
    side: Side
    order_type: OrderType
    sizing: SizingRequest
    intent: OrderPurpose = "entry"
    price: Px | None = None
    time_in_force: TimeInForce = "GTC"
    reduce_only: bool = False
    close_on_trigger: bool = False
    position_idx: Literal[0, 1, 2] = 0
    trigger: OrderTrigger | None = None
    stop_loss: StopOffset | None = None
    take_profit: StopOffset | None = None
    tpsl_mode: TpslMode = "Full"
    profile_id: UUID | None = None
    note: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class SubmitContext:
    """The admitted request around an `OrderRequest`, as the route hands it on: who sends it
    (`SubmitActor`), its `Idempotency-Key` as the anchor keeps it (`client_ref`) with the request's
    fingerprint (`request_sha256`), neither ever logged (C-12.6), and the correlation id of the
    HTTP request (`X-Correlation-Id`, #3990), which every record the pipeline writes carries, and
    the order's records through the command port too; None for a job ([AUDIT-REQUEST-ID])."""

    actor: SubmitActor
    client_ref: UUID = field(repr=False)
    request_sha256: str = field(repr=False)
    request_id: UUID | None = None
    #: The operation the anchor is kept under (21 Sec.3.3.10, `ia_operation`), and the anchor's
    #: own ref when it is not the key: a reversal's `uuid5(key, "close" | "open")` (E29-T07 #915).
    #: An entry's group keeps the raw key (`client_ref`) as its `client_group_ref` either way.
    operation: AnchorOperation = "placeOrder"
    anchor_ref: UUID | None = field(default=None, repr=False)
    #: The C-2.6 carve-out (24 Sec.8.10, 22 `Forbidden`): set only by the `closePosition` and
    #: `closeAllPositions` routes, in code, for their reduce-only flatten, never from request data.
    #: On a reduce-only order it lets live trading not enabled, the B18 kill switch and the
    #: order-entry gate pass at step 6 and at `SEND` (`_switched_off`); the environment lock's
    #: fence, the serving loop's stall, RBAC, scope and every other step still refuse.
    protective: bool = False

    @property
    def anchored_ref(self) -> UUID:
        """The ref the anchor is written and found under: `anchor_ref`, else the key."""
        return self.client_ref if self.anchor_ref is None else self.anchor_ref


@dataclass(frozen=True, slots=True)
class WrittenRows:
    """What a request's first persist wrote, as the pipeline built it (24 Sec.8.4 step 5): the
    order, and for an entry its one-leg group and that leg, each in the status the persist gave it
    (`validated`, `submitting`, `pending`). Slice 3's route renders the first `202` from them and
    the answer's `lifecycle`, with no read after the send, where a store failure is never a 503 (24
    Sec.8.4). Its repr shows none of the rows: they hold prices, sizes and stops (C-12.6)."""

    order: NewOrder = field(repr=False)
    group: NewTradeGroup | None = field(default=None, repr=False)
    legs: tuple[NewTradeGroupLeg, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    """What a recorded request answers (24 Sec.8.4 point 6): 202 with the order's B1 state after
    its create (`lifecycle`), 429 `exchange_rate_limited` with `Retry-After` on the first answer
    only, or 502 `exchange_error` with the exchange's return code and never its text (SR-E29-09).
    A first answer carries the rows its persist wrote (`written`). `replayed` marks the repeat of
    a decided anchor (`OrderSubmission.answer_replay`), which carries none, as the route reads its
    rows in their current state: a `202` repeat carries its order's reconciled state in
    `lifecycle`, or `RECONCILING` while B1 has not resolved the order (C-2.10, never an assumed
    success). The ids name the rows the request created: the order and, for an entry, its group (a
    replay names what its anchor names)."""

    status: AnchorStatus
    anchor_id: UUID
    order_id: UUID | None = None
    trade_group_id: UUID | None = None
    lifecycle: str | None = None
    code: str | None = None
    ret_code: int | None = None
    retry_after_s: int | None = None
    replayed: bool = False
    written: WrittenRows | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.status not in _CODES or self.code != _CODES[self.status]:
            raise ValueError("an outcome is 202 with no code, or a 429 or 502 with its own")
        ret = self.ret_code
        if ret is not None and (
            self.status != 502 or isinstance(ret, bool) or not MIN_RET_CODE <= ret <= MAX_RET_CODE
        ):
            raise ValueError("a return code comes with a 502 only, as the anchor holds one")
        delay = self.retry_after_s
        if delay is not None and (self.status != 429 or self.replayed or delay < 1):
            raise ValueError("a first 429, and only one, carries its Retry-After")
        if self.order_id is None and self.trade_group_id is None:
            raise ValueError("an outcome names the rows its request created")
        rows = self.written
        if rows is not None:
            group_id = None if rows.group is None else rows.group.id
            if self.replayed or (rows.order.id, group_id) != (self.order_id, self.trade_group_id):
                raise ValueError("a first answer carries the rows it names, a replay none")

    def anchor_outcome(self, decided_at: datetime) -> AnchorOutcome:
        """The answer as the anchor records it (21 Sec.3.3.10 "Writes")."""
        return AnchorOutcome(
            status=self.status, decided_at=decided_at, code=self.code, ret_code=self.ret_code
        )


@dataclass(frozen=True, slots=True)
class SubmissionDeps:
    """The pipeline's collaborators beside its four R4 ports (`SubmissionPorts`), each bound by
    slice 3's wiring: the account a request is signed for, the instruments, the market's
    reference prices, the effective profiles, the synchronous switches, the stop-request gate,
    the audit writer, the trade-group facade the leg's and the group's status go through
    (S2-Q4, a system surface no route reaches, C-12.4) and the account's figures the size step
    reads (24 Sec.9.3.6). `tier_requests` is the catalogue's tier bridge (S4-S-d), which the size
    step calls on a `figure_unknown` caused by missing tiers (S4-S-b2a), never awaiting it."""

    accounts: TradingAccounts
    instruments: Instruments
    prices: ReferencePrices
    profiles: Profiles
    switches: TradingSwitches
    gate: StopRequestGate
    audit: SubmitAudit
    groups: TradeGroupRepository
    figures: OrderFigures
    tier_requests: TierRequests = NO_TIER_REQUESTS


@dataclass(frozen=True, slots=True)
class _Rows:
    """One request's rows: the order and its first persist, the ids the answer names, and the
    candidate its `order_link_id` was allocated from (24 Sec.8.3 rule 5)."""

    order: NewOrder
    first: FirstPersist
    anchor_id: UUID
    group_id: GroupId | None
    leg_id: UUID | None
    candidate: OrderLinkIdParts


@dataclass(slots=True)
class _Trace:
    """One request's progress, for its refusal's record, its log lines and its spans (20
    Sec.12.3): `validating` holds `oms.validate` open through step 8, and `result` is the code
    `oms.submit` ends with."""

    request: OrderRequest
    context: SubmitContext
    started: float
    step: str = "clock"
    environment: Environment | None = None
    order: NewOrder | None = None
    persisted: bool = False
    size: EntrySize | None = None
    #: The size of the position the order's side closes, as step 3d's read showed it, and
    #: whether the whole close's `min_order_qty` exemption let the order through (ruling (a)).
    closable: Qty | None = None
    exempt: bool = False
    validating: ExitStack = field(default_factory=ExitStack)
    result: str | None = None

    def attributes(self) -> dict[str, str]:
        """`oms.submit`'s attributes, ids and codes only, each once the request reached it."""
        link = None if self.order is None else self.order.order_link_id
        named: dict[str, str | None] = {
            "symbol": self.request.symbol,
            "env": self.environment,
            "order_link_id": link,
            "result": self.result,
        }
        return {key: value for key, value in named.items() if value is not None}


#: A decided anchor's status as an answer's (`AnchorStatus`).
_STATUSES: Final[Mapping[int, AnchorStatus]] = MappingProxyType({202: 202, 429: 429, 502: 502})


def _lane(request: OrderRequest) -> OrderLane:
    """The order's rate lane, as the command port sends the create (`commands.place_request`):
    `critical` only for a reduce-only order whose intent reduces (SR-E29-01; the reserve is the
    exits', C-12.7), else `entry`."""
    return "critical" if request.reduce_only and request.intent in REDUCING_INTENTS else "entry"


def entry_order_id(group_id: UUID) -> UUID:
    """An entry's order id, named from its one-leg group's (`_ENTRY_ORDERS`): the anchor names the
    group alone (21 Sec.3.3.10 `ia_target`), and a repeat reads the order's state by this id."""
    return uuid5(_ENTRY_ORDERS, str(group_id))


def _reduce_only_errors(**sides: Px | StopOffset | None) -> list[FieldError]:
    """`reduce_only_tpsl` for each side a reduce-only order would carry where its venue sets
    neither on one (the ruling of 2026-10-22), the stop's first."""
    return [
        FieldError(side, RULE_REDUCE_ONLY_TPSL, message)
        for side, message in _REDUCE_ONLY_SIDES.items()
        if sides.get(side) is not None
    ]


def _position_changed(side: Side, position: ExchangePosition | None) -> PositionChanged:
    """BQ-7 (E29-S03): a protective close the venue's read does not show reducing is refused by
    that read, as the close route's step 13 names it: `position_flat` when no position of the side
    it closes is held there, else `exceeds_position`, the position smaller than the close."""
    if (
        position is None
        or position.side in (None, side)
        or not (position.qty.is_finite() and position.qty > 0)
    ):
        error = FieldError("positionId", RULE_POSITION_FLAT, _NOW_FLAT)
    else:
        error = FieldError("qty", RULE_EXCEEDS_POSITION, _NOW_SMALLER)
    return PositionChanged(error.message, errors=(error,))


def _invalid(errors: Sequence[FieldError]) -> OrderInvalid:
    """`validation_failed` listing every rule that failed, its detail the one rule's sentence or
    the count."""
    detail = errors[0].message if len(errors) == 1 else f"{len(errors)} rules failed."
    return OrderInvalid(detail, errors=errors)


def _entry_intent(request: OrderRequest) -> EntryIntent:
    """What the size step reads of an entry's request (`oms.sizing`)."""
    return EntryIntent(
        symbol=request.symbol, side=request.side, order_type=request.order_type,
        price=request.price, sizing=request.sizing, stop_loss=request.stop_loss,
        take_profit=request.take_profit, time_in_force=request.time_in_force,
        tpsl_mode=request.tpsl_mode, position_idx=request.position_idx,
    )  # fmt: skip


def _price_errors(price: Px, instrument: Instrument) -> list[FieldError]:
    """A request's own price that no step can judge: not finite, or not above zero (its compare
    would raise, or the stop would be judged against nothing). Named as the validator names them."""
    if not price.is_finite():
        return [FieldError("price", "finite", "The price must be a finite number.")]
    if price <= 0:
        message = f"Price must be at least {instrument.min_price}."
        return [FieldError("price", "min_price", message)]
    return []


_EXACT: Final = Context(prec=100)  # as `accounts/sizer.py`: the edge products are not rounded


def _judged(price: Px) -> bool:
    """A price the band can judge or judge against: finite and above zero."""
    return price.is_finite() and price > 0


def _within(price: Px, reference: Px, band: Decimal) -> bool:
    """`price` within `reference x (1 -/+ band)`, edges included; one no step can judge passes."""
    if not _judged(price):
        return True
    with localcontext(_EXACT):
        return reference * (1 - band) <= price <= reference * (1 + band)


def _band_message(name: str, band: Decimal, of: str) -> str:
    return f"The {name} must lie within {(band * 100).normalize():f}% of {of}."


def _retry_after(answer: Mapping[str, Any] | None) -> int:
    """A refused rate token's `Retry-After`, as the command port answered it (a whole number of
    seconds, at least 1), else 1."""
    raw = None if answer is None else answer.get("retry_after_s")
    return raw if type(raw) is int and raw >= 1 else 1


def _ret_code(answer: Mapping[str, Any] | None) -> int | None:
    """The exchange's return code the command port answered, when the anchor can hold it."""
    raw = None if answer is None else answer.get("exchange_ret_code")
    return raw if type(raw) is int and MIN_RET_CODE <= raw <= MAX_RET_CODE else None


def _reject_code(answer: Mapping[str, Any] | None) -> str:
    """The rejection's OMS code for the leg (24 Sec.8.6), as B1 keeps it: one it knows, else
    `EXCHANGE_UNKNOWN`."""
    raw = None if answer is None else answer.get("error_code")
    known = raw in {code.value for code in OmsErrorCode}
    return raw if isinstance(raw, str) and known else OmsErrorCode.EXCHANGE_UNKNOWN.value


class OrderSubmission:
    """The `placeOrder` pipeline (module docstring): one per process, with the OMS facade and the
    command port it drives. Its bounds after the anchor must total under the anchor service's
    `stuck_after_s` (`CV_OMS_INFLIGHT_STUCK_S`), and its wait for a create's answer
    (`place_wait_s`) must outlast the command port's deadline (`submit_timeout_s`; the default adds
    B1's turn to it): bounds that do not are refused with `ValueError` (D-2B2-01)."""

    def __init__(
        self,
        ports: SubmissionPorts,
        deps: SubmissionDeps,
        *,
        machines: OrderMachines,
        commands: OmsCommandPort,
        allocator: OrderLinkIdAllocator,
        validator: Validator,
        router: TradingRouter,
        anchors: AnchorService,
        clock_halt: ClockHalt,
        metrics: Metrics,
        now: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        pager: Pager | None = None,
        store_timeout_s: float = STORE_TIMEOUT_S,
        position_timeout_s: float = POSITION_TIMEOUT_S,
        place_wait_s: float = PLACE_WAIT_S,
        result_wait_s: float = RESULT_WAIT_S,
        stop_retries: Sequence[float] = STOP_RETRIES_S,
        price_band: Decimal = OMS_PRICE_BAND_DEFAULT,
    ) -> None:
        if (  # no off value (C-4.14); a float or a NaN is no band
            not isinstance(price_band, Decimal)
            or not price_band.is_finite()
            or not OMS_PRICE_BAND_MIN <= price_band <= OMS_PRICE_BAND_MAX
        ):
            raise ValueError("price_band must lie within CV_OMS_PRICE_BAND_PCT's bounds")
        self._price_band = price_band
        self._ports = ports
        self._deps = deps
        self._machines = machines
        self._commands = commands
        self._allocator = allocator
        self._validator = validator
        self._router = router
        self._anchors = anchors
        self._clock_halt = clock_halt
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        self._pager: Pager = pager if pager is not None else LogPager()
        self._store_timeout_s = _seconds("store_timeout_s", store_timeout_s)
        self._position_timeout_s = _seconds("position_timeout_s", position_timeout_s)
        self._place_wait_s = _seconds("place_wait_s", place_wait_s)
        self._result_wait_s = _seconds("result_wait_s", result_wait_s)
        after_anchor = _after_anchor_s(
            store_timeout_s=self._store_timeout_s,
            place_wait_s=self._place_wait_s,
            result_wait_s=self._result_wait_s,
        )
        # D-2B2-01: under the threshold the anchor service applies, the one a repeat meets: past
        # it a repeat decides the anchor while this request still runs. The service's own value
        # is the whole rule (`CV_OMS_INFLIGHT_STUCK_S`), with no ceiling of this module's.
        stuck_after_s = anchors.stuck_after_s
        if after_anchor >= stuck_after_s:
            raise ValueError(
                f"the bounds after the anchor total {after_anchor} s, not under "
                f"CV_OMS_INFLIGHT_STUCK_S ({stuck_after_s} s)"
            )
        # D-2B2-01: the wait for the create's answer must outlast the command port's one deadline
        # on all of `place` (the default adds B1's turn, which the wait spans before the deadline
        # starts), or a 429 or 502 answered in time could be given up into a 202. A NaN deadline
        # is refused too.
        if not self._place_wait_s > commands.submit_timeout_s:
            raise ValueError(
                f"place_wait_s ({self._place_wait_s} s) does not outlast the command port's "
                f"submit_timeout_s ({commands.submit_timeout_s} s)"
            )
        self._stop_retries = tuple(_delay(wait) for wait in stop_retries)
        self._guard = NativeStopGuard(ports.stop_resolver)
        self._sizer = EntrySizer(
            deps.figures, SizerMetrics.register(metrics), tier_requests=deps.tier_requests
        )
        self._request_qty = RequestQtySizer()
        self._turns = tuple(asyncio.Lock() for _ in range(ENTRY_TURNS))
        self._turn_wait_s = stuck_after_s
        self._positions = RoutedPositions(router, deps.accounts)
        specs = {spec.name: spec for spec in CATALOGUE}

        def counter(name: str) -> BoundedMetric:
            spec = specs[name]
            return metrics.counter(name, spec.help, spec.labels, max_series=spec.max_series)

        latency = specs["order_submit_seconds"]
        self._latency = metrics.histogram(
            latency.name,
            latency.help,
            latency.labels,
            buckets=latency.buckets or (),
            max_series=latency.max_series,
        )
        self._rejected = counter("oms_submit_rejected_total")
        self._clock_blocked = counter("oms_clock_drift_blocked_total").child()
        self._rate_rejected = counter("oms_rate_reject_total").child()

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        """The request's answer (module docstring), or its refusal, recorded first (C-2.9). It is
        one `oms.submit` span, whose children each start at their first step (20 Sec.12.3):
        `oms.validate` here, ended at step 8 (`_placed`) or by its refusal, so a refusal's record
        is written outside it; `oms.persist` and `oms.send` in `_placed`."""
        trace = _Trace(request, context, self._monotonic())
        with span("oms.submit") as traced:
            try:
                with trace.validating:
                    trace.validating.enter_context(span("oms.validate"))
                    outcome = await self._submit(trace)
                trace.result = outcome.code or _ACCEPTED
                return outcome
            # an OMS refusal, or a defect answered as an internal error: recorded, then raised
            except Exception as refusal:
                await self._refused(trace, refusal)
                raise
            finally:
                traced.set_attributes(trace.attributes())

    # --- Steps 1 to 8: nothing recorded, nothing sent ----------------------------------------

    async def _submit(self, trace: _Trace) -> SubmitOutcome:
        request = trace.request
        halted = self._clock_halt.refusal()
        if halted is not None:
            self._clock_blocked.inc()
            raise halted
        self._validator.assert_order_placement_allowed()
        trace.step = "resolve"
        account = await self._account(request.account_id)
        trace.environment = account.environment
        transport = self._router.transport_for(account.environment)  # C-2.11, or a page
        # The venue's own rule, read off its capability record, never a constant here (C-2.2).
        venue = self._router.port_for(account.environment).capabilities
        instrument = await self._instrument(request.symbol)
        profile = await self._profile(request)
        bare = request.reduce_only and not venue.supports_reduce_only_tpsl
        turn = None if request.reduce_only else await self._turn(account)
        try:
            return await self._placed(trace, account, transport, instrument, profile, bare=bare)
        finally:
            try:
                if trace.persisted:  # sent, or may be: the next entry reads the venue again
                    self._sizer.invalidate(account)
            finally:  # the turn is freed even when the drop raises
                if turn is not None:
                    turn.release()

    async def _turn(self, account: AccountRef) -> asyncio.Lock:
        """The account's turn of the size step (`ENTRY_TURNS`), held by the caller until its
        answer; one not had within the anchor service's `stuck_after_s` is 503
        `sizing_unavailable`, nothing recorded or sent."""
        turn = self._turns[hash(account.account_id) % len(self._turns)]
        try:
            async with asyncio.timeout(self._turn_wait_s):
                await turn.acquire()
        except TimeoutError:
            _log().warning("oms_submit_turn_unheld", account_id=str(account.account_id))
            raise SizingUnavailable(retry_after_s=SIZING_RETRY_AFTER_S) from None
        return turn

    async def _placed(
        self,
        trace: _Trace,
        account: AccountRef,
        transport: Transport,
        instrument: Instrument,
        profile: AccountProfile | None,
        *,
        bare: bool,
    ) -> SubmitOutcome:
        """Steps 3 to 11, once the order's account, instrument and profile are resolved."""
        request = trace.request
        trace.step = "classify"
        sized = await self._sized(trace, account, instrument, profile, bare=bare)
        trace.step = "validate"
        self._validator.check_order(
            sized, instrument=instrument, profile=profile, position_qty=trace.closable
        )
        whole = closes_whole(sized, trace.closable)
        trace.exempt = whole and sized.qty < instrument.min_order_qty
        trace.step = "risk"
        decision = self._ports.risk_gate.check(sized, profile=profile)
        if not decision.allowed:
            _log().info(
                "oms_submit_risk_refused", account_id=str(request.account_id), code=decision.code
            )
            raise RiskRefused()
        trace.step = "switches"
        switched_off = self._switched_off(trace, account)
        if switched_off is not None:
            raise switched_off
        trace.step = "rate"
        reading = self._router.headroom(account, _lane(request))
        if not reading.available:
            self._rate_rejected.inc()
            raise RateBudgetExceeded(retry_after_s=reading.retry_after_s or 1)
        trace.step = "allocate"
        rows = await self._rows(trace, account, sized, profile)
        trace.validating.close()  # step 8 done: `oms.validate` ends (`submit`)
        trace.step = "persist"
        with span("oms.persist"):
            persisted = await self._persist(trace, rows, account.environment)
        if isinstance(persisted, SubmitOutcome):
            return persisted  # the key's earlier request answers this one: no `oms.send`
        trace.persisted = True
        with span("oms.send"):
            trace.step = "send"
            watch = await self._send(trace, persisted, account)
            trace.step = "answer"
            return await self._answer(trace, persisted, watch, transport)

    async def _account(self, account_id: AccountId) -> AccountRef:
        """The account the order is signed for, by its id alone (SR-E27-21)."""
        account = await self._store_read(self._deps.accounts.trading_account(account_id))
        if account.account_id != account_id:
            raise ValueError("the trading account resolved is another account's")
        return account

    async def _instrument(self, symbol: Symbol) -> Instrument:
        instrument = await self._store_read(self._deps.instruments.instrument(symbol))
        if instrument is None or instrument.symbol != symbol:
            message = "No instrument is listed under this symbol."
            raise OrderInvalid(message, errors=(FieldError("symbol", "listed", message),))
        return instrument

    async def _profile(self, request: OrderRequest) -> AccountProfile | None:
        """The effective profile (24 Sec.9.3). A named `profile_id` the account does not hold,
        another account's, a deleted one or one that does not exist, is 404 `not_found`, the same
        answer for each (22 `PlaceOrderRequest`), whatever the order's kind. With none named, an
        account with no default answers None: an entry is then refused at the check (D11), never
        sized from a default (SR-E28-24)."""
        try:
            async with asyncio.timeout(self._store_timeout_s):
                return await self._deps.profiles.get_effective_profile(
                    request.account_id, request.profile_id
                )
        except AccountNotFoundError:
            if request.profile_id is not None:
                raise ProfileNotFound from None
            return None
        except (TimeoutError, ProfileUnavailableError, StorageError) as exc:
            _log().warning("oms_submit_profile_unread", failure=type(exc).__name__)
            raise StoreUnavailable from None

    async def _sized(
        self,
        trace: _Trace,
        account: AccountRef,
        instrument: Instrument,
        profile: AccountProfile | None,
        *,
        bare: bool,
    ) -> SizedOrder:
        """Step 3 (24 Sec.8.4 item 2): 3a the market read and the band, 3b the reference, 3c the
        size, 3d the effect, the native stop and the intent (`NativeStopGuard`, C-2.6), then the
        take-profit (S2-Q6), then the `SizedOrder`. An entry is sized by its profile, whose stop it
        carries (`oms.sizing`); a reduce-only order by its request's qty (`RequestQtySizer`). A
        `bare` order (reduce-only, on a venue that sets no take-profit or stop-loss on one) that
        names either is refused first, before any read: it could only meet a late rejection."""
        request = trace.request
        if bare:
            refused = _reduce_only_errors(
                stop_loss=request.stop_loss, take_profit=request.take_profit
            )
            if refused:
                raise _invalid(refused)
        reading = await self._banded(request)  # the one market read of step 3a, shared below
        if request.reduce_only:
            qty = self._size(request, instrument)
            effect = await self._effect(trace, qty)
            reference = await self._reference(request, instrument, reading)
            stop_offset = request.stop_loss
        else:
            if request.price is not None:
                errors = _price_errors(request.price, instrument)
                if errors:
                    raise OrderInvalid(errors=errors)
            if reading is None:
                reading, _ = await self._market_reading(request.symbol)
            intent = _entry_intent(request)
            size = await self._sizer.size(
                intent, account=account, instrument=instrument, profile=profile,
                mid=reading.mid, last=reading.last,
            )  # fmt: skip
            trace.size, qty, reference = size, size.qty, size.reference
            effect = await self._effect(trace, qty)
            stop_offset = StopOffset(unit="price", value=size.stop)  # the sizer's one stop
        stop, take_profit = self._protection(
            request, effect, reference, instrument, profile, bare=bare, stop=stop_offset
        )
        if trace.size is not None:  # an overlaid entry, judged once its take-profit is known
            judged = _entry_intent(request)
            self._sizer.judge(trace.size, judged, take_profit=take_profit, instrument=instrument)
        return SizedOrder(
            account_id=request.account_id,
            environment=account.environment,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            qty=qty,
            price=request.price,
            trigger_price=None if request.trigger is None else request.trigger.price,
            reference_price=reference,
            reduce_only=request.reduce_only,
            intent=request.intent,
            effect=effect,
            stop_loss=stop,
            take_profit=take_profit,
        )

    async def _banded(self, request: OrderRequest) -> MarketReading | None:
        """Step 3a (24 Sec.8.4; 22 `placeOrder`), before sizing: a limit or conditional entry, not
        reduce-only, is judged against the band around mid, else last (Q3): a trigger against it,
        a limit behind a trigger against that trigger (Q4); a price no step can judge is left to
        the later checks. A per-profile band waits for its column (Q3). Returns the market read
        made, None when nothing was judged and nothing read."""
        trigger = None if request.trigger is None else request.trigger.price
        limit = request.price if request.order_type == "limit" else None
        if request.reduce_only or (limit is None and trigger is None):
            return None
        reading, reference = await self._market_reading(request.symbol)
        band, errors = self._price_band, list[FieldError]()
        if trigger is not None and not _within(trigger, reference, band):
            message = _band_message("trigger price", band, "the market price")
            errors.append(FieldError("trigger.price", RULE_PRICE_BAND, message))
        if trigger is None:
            anchor, of = reference, "the market price"
        else:
            anchor, of = trigger, "its trigger price"
        if limit is not None and _judged(anchor) and not _within(limit, anchor, band):
            errors.append(FieldError("price", RULE_PRICE_BAND, _band_message("price", band, of)))
        if errors:
            raise _invalid(errors)
        return reading

    async def _market_reading(self, symbol: Symbol) -> tuple[MarketReading, Px]:
        """The market read (a price at zero or below taken as none) and its reference, the mid else
        the last price; with neither, or a read that fails or does not answer in time, 503
        `exchange_unavailable` (the binding has taken the ticker demand, so the retry finds one)."""
        try:
            async with asyncio.timeout(self._position_timeout_s):
                reading = await self._deps.prices.market(symbol)
        except Exception as exc:
            _log().warning("oms_submit_price_unread", symbol=symbol, failure=type(exc).__name__)
            raise ExchangeUnavailable(retry_after_s=READ_RETRY_AFTER_S) from None
        mid, last = (
            p if p is not None and _judged(p) else None for p in (reading.mid, reading.last)
        )
        reference = mid if mid is not None else last
        if reference is None:
            _log().warning("oms_submit_price_unread", symbol=symbol, failure="no_price")
            raise ExchangeUnavailable(retry_after_s=READ_RETRY_AFTER_S)
        return MarketReading(mid=mid, last=last), reference

    def _size(self, request: OrderRequest, instrument: Instrument) -> Qty:
        try:
            return self._request_qty.size(request.sizing, instrument)
        except ArithmeticError:  # a quantity no step can round (`decimal.DivisionImpossible`)
            raise OrderInvalid("The quantity cannot be sized.") from None

    async def _effect(self, trace: _Trace, qty: Qty) -> OrderEffect:
        """SR-E29-01: the effect on the exchange-truth position, read for a reduce-only order
        only. A read that fails or does not answer in time is no answer (Q-B): 503
        `exchange_unavailable`, nothing recorded or sent. A protective close the read does not
        show reducing is `PositionChanged` (BQ-7, module docstring), never re-sized."""
        request = trace.request
        try:
            effect, position = await position_effect(
                account_id=request.account_id,
                symbol=request.symbol,
                position_idx=request.position_idx,
                side=request.side,
                qty=qty,
                reduce_only=request.reduce_only,
                positions=self._positions,
                timeout_s=self._position_timeout_s,
            )
        except OmsError:
            raise  # the route (C-2.11) or the account (SR-E27-21) refused, as itself
        except Exception as exc:
            _log().warning(
                "oms_submit_position_unread",
                account_id=str(request.account_id),
                symbol=request.symbol,
                failure=type(exc).__name__,
            )
            raise ExchangeUnavailable(retry_after_s=READ_RETRY_AFTER_S) from None
        if trace.context.protective and request.reduce_only and effect is not OrderEffect.REDUCE:
            raise _position_changed(request.side, position)
        if position is not None and position.side not in (None, request.side):
            trace.closable = position.qty  # the whole close's size, for the validator (ruling (a))
        return effect

    async def _reference(
        self, request: OrderRequest, instrument: Instrument, reading: MarketReading | None
    ) -> Px:
        """24 Sec.9.3 step 2: the order's own price, else the market's reference: the band step's
        read when it made one (24 Sec.8.4 step 3b), else a read of its own; a market whose price
        cannot be read is no answer (Q-B: 503 `exchange_unavailable`)."""
        own = request.price
        if own is not None:
            errors = _price_errors(own, instrument)
            if errors:
                raise OrderInvalid(errors=errors)
            return own
        if reading is not None and reading.reference is not None:
            return reading.reference
        try:
            async with asyncio.timeout(self._position_timeout_s):
                market = await self._deps.prices.reference_price(request.symbol)
        except Exception as exc:
            _log().warning(
                "oms_submit_price_unread", symbol=request.symbol, failure=type(exc).__name__
            )
            raise ExchangeUnavailable(retry_after_s=READ_RETRY_AFTER_S) from None
        if market is None or not market.is_finite() or market <= 0:
            _log().warning("oms_submit_price_unread", symbol=request.symbol, failure="no_price")
            raise ExchangeUnavailable(retry_after_s=READ_RETRY_AFTER_S)
        return market

    def _protection(
        self,
        request: OrderRequest,
        effect: OrderEffect,
        reference: Px,
        instrument: Instrument,
        profile: AccountProfile | None,
        *,
        bare: bool,
        stop: StopOffset | None,
    ) -> tuple[Px | None, Px | None]:
        """The stop (`NativeStopGuard`: an entry's is mandatory, C-2.6), the intent, then the
        take-profit (S2-Q6): `errors[]` lists every rule that fails, the stop's first. A `bare`
        order names neither side (`_sized`), so a side resolved here is the profile's: one not
        shown to reduce is an entry, whose stop it cannot carry, so it is refused all the same."""
        errors: list[FieldError] = []
        price: Px | None = None
        try:
            price = self._guard.admit(
                stop=stop,
                side=request.side,
                reference_price=reference,
                effect=effect,
                intent=request.intent,
                instrument=instrument,
                profile=profile,
            )
        except OrderInvalid as refused:
            errors.extend(refused.errors)
        take_profit: Px | None = None
        try:
            take_profit = self._ports.stop_resolver.resolve_take_profit(
                request.take_profit,
                side=request.side,
                reference_price=reference,
                instrument=instrument,
                profile=profile,
            )
        except StopUnitUnsupported as unsupported:
            errors.extend(unsupported.errors)
        else:
            errors.extend(
                take_profit_errors(
                    side=request.side, reference_price=reference, take_profit=take_profit
                )
            )
        if bare:
            errors.extend(_reduce_only_errors(stop_loss=price, take_profit=take_profit))
        if errors:
            raise _invalid(errors)
        return price, take_profit

    # --- Steps 8 and 9: the id and the first persist ------------------------------------------

    async def _rows(
        self,
        trace: _Trace,
        account: AccountRef,
        sized: SizedOrder,
        profile: AccountProfile | None,
    ) -> _Rows:
        """The order's ids, its `order_link_id` (24 Sec.8.3: an entry's from its new group, a
        reduce-only order's from its own id) and the rows its first persist writes. An entry's
        order id is named from its group's (`entry_order_id`)."""
        request = trace.request
        group_id = None if request.reduce_only else GroupId(uuid4())
        order_id = uuid4() if group_id is None else entry_order_id(group_id)
        anchor_id = uuid4()
        leg_id = None if group_id is None else uuid4()
        candidate = OrderLinkIdParts.generate(
            mode="exchange",
            environment=account.environment,
            group_id=group_id if group_id is not None else GroupId(order_id),
            account_id=request.account_id,
            seq=0,
            purpose=request.intent,
        )
        link = await self._allocate(candidate)
        trigger = request.trigger
        order = NewOrder(
            id=order_id,
            exchange_account_id=request.account_id,
            order_link_id=link,
            symbol=request.symbol,
            side=_SIDES[request.side],
            intent=request.intent,
            order_type=_TYPES[request.order_type],
            qty=sized.qty,
            price=request.price,
            trigger_price=None if trigger is None else trigger.price,
            trigger_by=None if trigger is None else trigger.trigger_by,
            trigger_direction=None if trigger is None else _DIRECTIONS[trigger.direction],
            take_profit=sized.take_profit,
            stop_loss=sized.stop_loss,
            tpsl_mode=request.tpsl_mode,
            time_in_force=request.time_in_force,
            reduce_only=request.reduce_only,
            close_on_trigger=request.close_on_trigger,
            position_idx=request.position_idx,
            state="pending_submit",
            lifecycle_state="validated",
            trade_group_leg_id=leg_id,
        )
        trace.order = order
        first = self._first_persist(trace, account, sized, profile, order, anchor_id, group_id)
        return _Rows(order, first, anchor_id, group_id, leg_id, candidate)

    def _first_persist(
        self,
        trace: _Trace,
        account: AccountRef,
        sized: SizedOrder,
        profile: AccountProfile | None,
        order: NewOrder,
        anchor_id: UUID,
        group_id: GroupId | None,
    ) -> FirstPersist:
        """The rows written with the order (24 Sec.8.4 step 5): for an entry its one-leg group,
        the leg sized from the profile, its stop-loss and take-profit requests and the anchor
        naming the group; for a reduce-only order the anchor naming the order alone, as 2a's
        first persist records no stop for it (Q-O)."""
        context = trace.context
        hook = self._write_ahead(trace, sized.effect)
        if group_id is None:
            anchor = _anchor(context, anchor_id, order_id=order.id)
            return FirstPersist(anchor=anchor, write_ahead=hook)
        if profile is None or order.trade_group_leg_id is None:  # the check refused it already
            raise ValueError("an entry is recorded with its profile and its leg")
        request, size = trace.request, trace.size
        trigger = request.trigger
        if size is None:  # the size step sized every entry
            raise ValueError("an entry is recorded with its size")
        try:
            draft = TradeGroupDraft(
                group_id=group_id,
                client_group_ref=context.client_ref,
                client_body_sha256=context.request_sha256,
                created_by=UserId(context.actor.user_id),
                environment=account.environment,
                symbol=request.symbol,
                side=request.side,
                status="submitting",
                leg_failure_policy="best_effort",
                algo="none",
                algo_params=None,
                note=request.note,
                origin="manual",
                rule_id=None,
                rule_run_id=None,
                definition_id=None,
                requested_qty_mode=size.mode,
                requested_qty_value=size.value,
                entry_type="conditional" if trigger is not None else request.order_type,
                entry_price=request.price,
                trigger_price=None if trigger is None else trigger.price,
                trigger_by=None if trigger is None else _GROUP_TRIGGERS[trigger.trigger_by],
                sl_price_hint=sized.stop_loss,
                tp_price_hint=sized.take_profit,
                is_paper=False,
            )
            leg = LegDraft(
                leg_id=order.trade_group_leg_id,
                profile=profile,
                status="pending",
                sequence_no=0,
                target_qty=sized.qty,
                resolved_leverage=profile.leverage,
                resolved_sl_price=sized.stop_loss,
                resolved_tp_price=sized.take_profit,
                risk_usd=size.risk_usd,
                rejection_code=None,
                rejection_message=None,
            )
        except ValidationError:  # a value its column cannot store (the note, the requested qty)
            raise OrderInvalid("The order holds a value that cannot be recorded.") from None
        sides: tuple[tuple[StopKind, Px | None], ...] = (
            ("stop_loss", order.stop_loss),
            ("take_profit", order.take_profit),
        )
        stops = tuple(self._stop_row(trace, order, k, p) for k, p in sides if p is not None)
        return FirstPersist(
            anchor=_anchor(context, anchor_id, trade_group_id=group_id),
            group=group_values(draft),
            legs=(leg_values(leg),),
            recorded_stops=stops,
            write_ahead=hook,
        )

    def _stop_row(
        self, trace: _Trace, order: NewOrder, kind: StopKind, price: Px
    ) -> NewRecordedStop:
        """One side of the entry's attach, recorded ahead of its request (21 Sec.3.3.11): the row
        names the record its request is audited by (`sl.attached`, `tp.modified`), keyed by the
        row's id, and the requesting principal."""
        row_id = uuid4()
        return NewRecordedStop(
            id=row_id,
            exchange_account_id=order.exchange_account_id,
            symbol=order.symbol,
            position_idx=order.position_idx,
            position_side=order.side,
            kind=kind,
            source="entry_attach",
            order_id=order.id,
            tpsl_mode=order.tpsl_mode,
            trigger_price=price,
            size=order.qty if order.tpsl_mode == "Partial" else None,
            audit_record_id=self._deps.audit.record_id(_STOP_ACTIONS[kind], str(row_id)),
            actor_user_id=trace.context.actor.user_id,
        )

    async def _allocate(self, candidate: OrderLinkIdParts) -> str:
        """24 Sec.8.3 rule 5 from `candidate`, within `store_timeout_s`; spent, the allocator's
        `OrderLinkIdExhausted` (500, which pages)."""
        try:
            async with asyncio.timeout(self._store_timeout_s):
                allocated = await self._allocator.allocate(candidate)
        except OrderLinkIdExhausted:
            _log().critical("oms_order_link_id_exhausted", order_link_id=candidate.value)
            raise
        except (TimeoutError, StorageError, OrderStoreError) as exc:
            _log().warning("oms_submit_allocation_unread", failure=type(exc).__name__)
            raise StoreUnavailable from None
        return allocated.order_link_id

    async def _persist(
        self, trace: _Trace, rows: _Rows, environment: Environment
    ) -> _Rows | SubmitOutcome:
        """B1's `VALIDATE` with the first persist, under the Q4 loop (module docstring, step 9).
        Answers the rows as written, or the outcome of the key's earlier request."""
        request = trace.request
        key = None
        if rows.group_id is not None:  # an entry records its stop request: its key must be clear
            key = PositionKey(request.account_id, request.symbol, request.position_idx)
        waits = iter(self._stop_retries)
        violations = 0
        while True:
            if key is not None:  # a row waiting for the complete read: 409; bounded (C-2.18)
                await self._store_read(self._deps.gate.clear(key))
            try:
                state = await self._machines.start(
                    rows.order, environment=environment, gates=_PASSED, first=rows.first
                )
            except OrderStepRefused as refused:
                cause = refused.__cause__
                if isinstance(cause, StopRequestInFlight):
                    wait = next(waits, None)
                    if wait is None:
                        _log().info("oms_submit_stop_request_in_flight", symbol=request.symbol)
                        raise StopRequestPending(retry_after_s=STOP_RETRY_AFTER_S) from None
                    await self._sleep(wait)
                    continue
                if isinstance(cause, DuplicateOrderLinkId):  # rule 5's race: allocate again
                    violations += 1
                    if violations > MAX_SEQ_INCREMENTS:
                        last = rows.order.order_link_id
                        raise OrderLinkIdExhausted(first=rows.candidate.value, last=last) from None
                    order = replace(rows.order, order_link_id=await self._allocate(rows.candidate))
                    rows = replace(rows, order=order)
                    trace.order = order
                    continue
                if isinstance(cause, AnchorTaken):
                    return await self._repeat(trace, cause)
                raise _persist_refusal(refused) from None
            except OrderStepUnknown:
                # The facade rebuilt the order from its events, where the row decides.
                live = self._machines.state(rows.order.id)
                if live is None or live[0] != "validated":
                    _log().error(
                        "oms_submit_persist_unknown", order_link_id=rows.order.order_link_id
                    )
                    if live is None:  # a `validated` row it may have left has no owner: paged
                        self._page("oms_submit_persist_unknown")
                    raise StoreUnavailable from None
                state = live[0]
            if state != "validated":  # a verdict refused it, nothing written: none can here
                _log().critical("oms_submit_not_validated", state=state)
                raise OmsError(f"the order was not recorded as validated ({state})")
            return rows

    async def _repeat(self, trace: _Trace, taken: AnchorTaken) -> SubmitOutcome:
        """The key is held by an earlier request (21 Sec.3.3.10): its decided outcome is the
        answer, nothing sent (`answer_replay`); a request still in flight, or another body, is
        refused."""
        context = trace.context
        lookup = await self._anchors.after_taken(
            taken.constraint, context.actor.user_id, context.anchored_ref, context.request_sha256,
            operation=context.operation,
        )  # fmt: skip
        if isinstance(lookup, InFlight | KeyReuse):
            raise lookup.refusal()
        if not isinstance(lookup, Replay):  # a held key is never fresh
            raise StoreUnavailable
        return await self.answer_replay(trace.request.account_id, lookup)

    async def answer_replay(self, account_id: AccountId, replay: Replay) -> SubmitOutcome:
        """A decided anchor's answer to a repeat (21 Sec.3.3.10 "Repeats"), nothing sent: the
        outcome it recorded, a `202` carrying its order's reconciled state (`reconciled_state`),
        never an assumed success. The pipeline answers a held key with it, and slice 3's route its
        own lookup's `Replay` (`AnchorService.lookup`), so both read the same state. An anchor
        whose outcome no answer can hold is 503 `store_unavailable`."""
        anchor = replay.anchor
        status = _STATUSES.get(anchor.outcome_status or 0)
        lifecycle = None
        if status == 202:
            order_id = anchor.order_id
            if order_id is None and anchor.trade_group_id is not None:
                order_id = entry_order_id(anchor.trade_group_id)
            lifecycle = await self.reconciled_state(account_id, order_id)
        try:
            if status is None:
                raise ValueError("a decided anchor holds 202, 429 or 502")
            return SubmitOutcome(
                status=status,
                anchor_id=anchor.id,
                order_id=anchor.order_id,
                trade_group_id=anchor.trade_group_id,
                lifecycle=lifecycle,
                code=anchor.outcome_code,
                ret_code=anchor.outcome_ret_code,
                replayed=True,
            )
        except ValueError:
            _log().error("oms_anchor_outcome_unreadable", anchor_id=str(anchor.id))
            raise StoreUnavailable from None

    async def reconciled_state(self, account_id: AccountId, order_id: UUID | None) -> str:
        """A `202` repeat's state (the orchestrator's ruling of 2026-10-22, C-2.10): the state B1
        resolved the order to, else `RECONCILING`, while it is `_UNRESOLVED`, or its state cannot
        be read within `store_timeout_s` (an in-flight create is waited for that long); never
        an assumed success. It reads the facade's plain view, else the row, never an interpreter."""
        if order_id is None:  # an anchor naming neither row breaks `ia_target`: nothing to read
            return RECONCILING
        try:
            state = await self._machines.settled(
                account_id, order_id, leaving="submitting", timeout_s=self._store_timeout_s
            )
        except Exception as exc:  # not known in time, no such order, or a store that failed
            _log().warning(
                "oms_replay_state_unread", order_id=str(order_id), failure=type(exc).__name__
            )
            return RECONCILING
        return RECONCILING if state in _UNRESOLVED else state

    def _write_ahead(
        self, trace: _Trace, effect: OrderEffect
    ) -> Callable[[FirstPersisted], Awaitable[None]]:
        """The first persist's write-ahead hook (C-2.9): the request's records, written in the
        persist's transaction before its commit, from the rows as stored. A record that does not
        land raises `AuditNotDurable`, so the persist writes nothing (503 `audit_unavailable`)."""

        async def write_ahead(persisted: FirstPersisted) -> None:
            records = self._intent_records(trace, persisted, effect)
            try:
                for record in records:
                    await self._deps.audit.write(record)
            except Exception as exc:  # the writer refused or failed: nothing is committed
                link = persisted.order.order_link_id
                _log().error(
                    "oms_submit_intent_unrecorded", order_link_id=link, failure=type(exc).__name__
                )
                raise AuditNotDurable("the order's write-ahead audit did not land") from None

        return write_ahead

    def _intent_records(
        self, trace: _Trace, persisted: FirstPersisted, effect: OrderEffect
    ) -> list[RequestRecord | KeyedRecord]:
        """`orders.submit` for the order, `trade_group.submit` for an entry's group, and each
        recorded stop's request (`sl.attached`, `tp.modified`), keyed by its row, which names the
        record (21 Sec.3.3.11 "Audit"). Ids, names and states only (C-12.6)."""
        row, group, context = persisted.order, persisted.group, trace.context
        group_id = None if group is None else str(group.group.id)
        detail: dict[str, str | None] = {
            "order_link_id": row.order_link_id,
            "symbol": row.symbol,
            "side": row.side,
            "order_type": row.order_type,
            "intent": row.intent,
            "effect": effect.value,
            "reduce_only": str(row.reduce_only).lower(),
            "environment": trace.environment,
            "trade_group_id": group_id,
            "anchor_id": str(persisted.anchor_id),
        }
        if trace.exempt:  # ruling (a): the record names the whole close's exemption
            detail["exemption"] = EXEMPT_WHOLE_CLOSE
        records: list[RequestRecord | KeyedRecord] = [
            self._request_record(
                trace, SUBMIT_ACTION, "order", row.id, "success", "validated", detail
            )
        ]
        if group is not None:
            legs = ",".join(str(leg.id) for leg in group.legs)
            grouped: dict[str, str | None] = {"order_id": str(row.id), "legs": legs}
            grouped |= {"order_link_id": row.order_link_id}
            grouped |= {"symbol": row.symbol, "side": row.side, "environment": trace.environment}
            if trace.size is not None:  # SR-E28-13: how the leg was sized, its figures included
                grouped["sizing_explanation"] = trace.size.leg.render()
            records.append(
                self._request_record(
                    trace,
                    GROUP_ACTION,
                    "trade_group",
                    group.group.id,
                    "success",
                    "submitting",
                    grouped,
                )
            )
        for stop in persisted.recorded_stops:
            records.append(
                KeyedRecord(
                    action=_STOP_ACTIONS[stop.kind],
                    name=str(stop.id),
                    account_id=stop.exchange_account_id,
                    object_kind="recorded_stop",
                    object_id=stop.id,
                    outcome="success",
                    severity="info",
                    reason=_ENTRY_ATTACH,
                    actor_user_id=context.actor.user_id,
                    detail={
                        "order_id": str(row.id),
                        "order_link_id": row.order_link_id,
                        "kind": stop.kind,
                        "source": stop.source,
                    },
                    request_id=context.request_id,
                    actor=context.actor,
                )
            )
        return records

    # --- Steps 10 and 11: the send and its answer ---------------------------------------------

    async def _send(self, trace: _Trace, rows: _Rows, account: AccountRef) -> PlaceWatch:
        """`SEND` once the command port holds the order. One that did not commit sent nothing: the
        order is abandoned and the request refused; one whose outcome is unknown is followed once
        the rebuilt order has left `validated` (module docstring, step 10). The step's actor
        (`user`) and the group draft's origin (`manual`, `_first_persist`) are manual-only until
        M15 (`rules`) submits through the pipeline, as `SubmitActor` already allows."""
        order = rows.order
        carrier = inject_context({})  # `oms.send`'s, which B1's invoke runs outside (20 Sec.12.3)
        watch = self._commands.expect(order, request_id=trace.context.request_id, carrier=carrier)
        try:
            await self._machines.command(order.exchange_account_id, order.id, "SEND", actor="user")
        except OrderStepUnknown:
            live = self._machines.state(order.id)
            if live is None or live[0] == "validated":
                raise await self._unsent(trace, order, account) from None
            _log().warning(
                "oms_submit_send_followed", order_link_id=order.order_link_id, state=live[0]
            )
        except Exception as exc:  # refused, or never admitted: the step did not commit (S7)
            _log().warning(
                "oms_submit_send_refused",
                order_link_id=order.order_link_id,
                failure=type(exc).__name__,
            )
            raise await self._unsent(trace, order, account) from None
        return watch

    async def _unsent(self, trace: _Trace, order: NewOrder, account: AccountRef) -> OmsError:
        """A recorded order this request did not send: its registration dropped, the order
        abandoned, and the refusal to answer, the switch that refuses it now if one does (the kill
        switch engaged since step 6; a protective close's carve-out applies here too), else 503
        `store_unavailable`."""
        self._commands.forget(order.id)
        await self._abandon(order)
        switched_off = self._switched_off(trace, account)
        return switched_off if switched_off is not None else StoreUnavailable()

    def _switched_off(self, trace: _Trace, account: AccountRef) -> OmsError | None:
        """The synchronous switches' refusal (step 6, and at `SEND`), or None. The C-2.6 carve-out
        (24 Sec.8.10): for a reduce-only order whose route marked it `protective` (a close or a
        close-all leg), live trading not enabled, the kill switch and the order-entry gate
        (`TradingDisabled`, the gate's `OrderEntryRefused` among them) do not refuse; the fence
        (`OmsNotReady`, returned or raised) still does, so a lane that lost its lock sends
        nothing."""
        refusal = self._deps.switches.refusal(account.account_id, account.environment)
        carved = trace.context.protective and trace.request.reduce_only
        if carved and isinstance(refusal, TradingDisabled):
            _log().info(
                "oms_submit_protective_close_admitted",
                account_id=str(account.account_id),
                code=problem_for(refusal).code,
            )
            return None
        return refusal

    async def _abandon(self, order: NewOrder) -> None:
        """S2-Q5: a `validated` order no request will send is killed, never sent (`abandon`): tried
        twice, then paged; slice 3's startup kills what is left before order entry opens."""
        failure = ""
        for _ in range(2):
            live = self._machines.state(order.id)
            if live is None or live[0] != "validated":
                return  # gone, or moved on: nothing here to abandon
            try:
                await self._machines.abandon(order.exchange_account_id, order.id, _ABANDONED)
                return
            except Exception as exc:  # tried once more, then paged
                failure = type(exc).__name__
        _log().critical(
            "oms_unsent_order_not_abandoned", order_link_id=order.order_link_id, failure=failure
        )
        self._page("oms_unsent_order_not_abandoned")

    async def _answer(
        self, trace: _Trace, rows: _Rows, watch: PlaceWatch, transport: Transport
    ) -> SubmitOutcome:
        """Step 11: the outcome B1 recorded, then the best-effort records (never a 503)."""
        order = rows.order
        answer: Mapping[str, Any] | None = None
        lifecycle = "submitting"
        try:
            async with asyncio.timeout(self._place_wait_s):
                answer = await watch.answer()
        except TimeoutError:  # the create has not answered yet: its outcome is not known
            _log().warning("oms_submit_answer_late", order_link_id=order.order_link_id)
        else:
            lifecycle = await self._lifecycle(order)
        outcome = _outcome(rows, lifecycle, answer)
        await self._decide(rows, outcome)
        await self._settle_group(rows, lifecycle, answer)
        await self._audit_outcome(trace, rows, outcome)
        self._latency.labels(transport).observe(self._monotonic() - trace.started)
        if outcome.code is not None:
            self._rejected.labels(outcome.code).inc()
        if outcome.status == 429:
            self._rate_rejected.inc()
        _log().info(
            "oms_submit_answered",
            order_link_id=order.order_link_id,
            status=outcome.status,
            lifecycle=lifecycle,
        )
        return outcome

    async def _lifecycle(self, order: NewOrder) -> str:
        """The order's state once it left `submitting`, or `submitting` when its step is not known
        in time: answered as `unknown` is."""
        try:
            return await self._machines.settled(
                order.exchange_account_id,
                order.id,
                leaving="submitting",
                timeout_s=self._result_wait_s,
            )
        except Exception as exc:  # not known in time, or no machine to follow
            link = order.order_link_id
            _log().warning(
                "oms_submit_outcome_unknown", order_link_id=link, failure=type(exc).__name__
            )
            return "submitting"

    async def _decide(self, rows: _Rows, outcome: SubmitOutcome) -> None:
        """The anchor's outcome, by compare-and-set from none (21 Sec.3.3.10), so every repeat
        replays it; best effort, within `store_timeout_s` as each write after the send is, whatever
        the anchor service bounds itself to: a repeat past `CV_OMS_INFLIGHT_STUCK_S` decides it
        otherwise."""
        anchor_id = str(rows.anchor_id)
        try:
            decided = outcome.anchor_outcome(self._now())
            recorded = await self._bounded(self._anchors.record(rows.anchor_id, decided))
        except Exception as exc:  # never the answer: logged, and a repeat decides it
            _log().error(
                "oms_anchor_outcome_unrecorded", anchor_id=anchor_id, failure=type(exc).__name__
            )
            return
        if not recorded:
            _log().info("oms_anchor_outcome_taken", anchor_id=anchor_id)

    async def _settle_group(
        self, rows: _Rows, lifecycle: str, answer: Mapping[str, Any] | None
    ) -> None:
        """S2-Q4, best effort until E34's B2 and B3 own them: a rejected order's leg `rejected`
        and its group `failed`, any other's leg `submitted`, each by compare-and-set from the
        status the first persist wrote; a `held` order's leg is left as it is (Q-M: B1 pages and
        the operator decides). A stale compare-and-set is logged."""
        group_id, leg_id = rows.group_id, rows.leg_id
        if group_id is None or leg_id is None or lifecycle == "held":
            return
        groups = self._deps.groups
        if lifecycle == "rejected":
            refused = LegUpdate(status="rejected", rejection_code=_reject_code(answer))
            await self._compare_and_set(
                groups.update_leg(group_id, leg_id, refused, expected_status="pending"), group_id
            )
            failed = GroupUpdate(status="failed")
            await self._compare_and_set(
                groups.update_group(group_id, failed, expected_status="submitting"), group_id
            )
            return
        sent = LegUpdate(status="submitted", submitted_at=_us(self._now()))
        await self._compare_and_set(
            groups.update_leg(group_id, leg_id, sent, expected_status="pending"), group_id
        )

    async def _compare_and_set(self, call: Awaitable[object], group_id: GroupId) -> None:
        try:
            await self._bounded(call)
        except TradeGroupStaleError:
            _log().info("oms_trade_group_status_stale", trade_group_id=str(group_id))
        except Exception as exc:  # never the answer
            _log().error(
                "oms_trade_group_status_unrecorded",
                trade_group_id=str(group_id),
                failure=type(exc).__name__,
            )

    async def _audit_outcome(self, trace: _Trace, rows: _Rows, outcome: SubmitOutcome) -> None:
        """The answer's record, best effort: the order's own steps (`order_events`) are its
        write-ahead trail, and the request's intent was recorded with the order (C-2.9)."""
        accepted = outcome.status == 202
        reason = (outcome.lifecycle or "submitting") if accepted else (outcome.code or "")
        detail: dict[str, str | None] = {
            "order_link_id": rows.order.order_link_id,
            "status": str(outcome.status),
            "lifecycle": outcome.lifecycle,
            "anchor_id": str(rows.anchor_id),
        }
        record = self._request_record(
            trace,
            SUBMIT_ACTION,
            "order",
            rows.order.id,
            "success" if accepted else "failure",
            reason,
            detail,
            severity="info" if accepted else "warning",
        )
        try:
            await self._bounded(self._deps.audit.write(record))
        except Exception as exc:  # never the answer
            link = rows.order.order_link_id
            _log().error(
                "oms_submit_outcome_unrecorded", order_link_id=link, failure=type(exc).__name__
            )

    # --- Refusals, records and bounds ------------------------------------------------------------

    async def _refused(self, trace: _Trace, error: Exception) -> None:
        """A refusal's record, written before it is answered (C-2.9), and its count; when the record
        does not land, `AuditNotDurable` (503 `audit_unavailable`) is raised in its place."""
        problem = problem_for(error) if isinstance(error, OmsError) else INTERNAL_ERROR
        trace.result = problem.code
        request, order = trace.request, trace.order
        if trace.persisted and order is not None:
            kind: RequestObject = "order"
            object_id: UUID = order.id
        else:
            kind, object_id = "exchange_account", request.account_id
        link = None if order is None else order.order_link_id
        detail: dict[str, str | None] = {
            "step": trace.step,
            "code": problem.code,
            "symbol": request.symbol,
            "environment": trace.environment,
            "order_link_id": link,
        }
        _log().warning(
            "oms_submit_refused",
            code=problem.code,
            step=trace.step,
            account_id=str(request.account_id),
            symbol=request.symbol,
            order_link_id=link,
        )
        severity: AuditSeverity = "error" if problem.status >= 500 else "warning"
        record = self._request_record(
            trace, SUBMIT_ACTION, kind, object_id, "denied", problem.code, detail, severity=severity
        )
        try:
            await self._bounded(self._deps.audit.write(record))
        except Exception as exc:  # no refusal is answered unrecorded
            trace.result = _AUDIT_UNAVAILABLE
            self._rejected.labels(_AUDIT_UNAVAILABLE).inc()
            _log().error(
                "oms_submit_refusal_unrecorded", code=problem.code, failure=type(exc).__name__
            )
            raise AuditNotDurable("the refusal's record did not land") from None
        self._rejected.labels(problem.code).inc()

    def _request_record(
        self,
        trace: _Trace,
        action: str,
        object_kind: RequestObject,
        object_id: UUID,
        outcome: AuditOutcome,
        reason: str,
        detail: Mapping[str, str | None],
        *,
        severity: AuditSeverity = "info",
    ) -> RequestRecord:
        context = trace.context
        return RequestRecord(
            action=action,
            account_id=trace.request.account_id,
            object_kind=object_kind,
            object_id=object_id,
            outcome=outcome,
            severity=severity,
            reason=reason,
            actor=context.actor,
            detail=dict(detail),
            request_id=context.request_id,
        )

    async def _store_read[T](self, call: Awaitable[T]) -> T:
        """A store read of steps 1 and 2, or the stop-request gate's clear at step 9 (bounded here
        whatever the gate bounds itself, as `StopRequestGate` asks of its caller, C-2.18), within
        `store_timeout_s`; one that fails or does not answer in time is 503 `store_unavailable`, an
        OMS refusal is answered as itself."""
        try:
            return await self._bounded(call)
        except OmsError:
            raise
        except (TimeoutError, StorageError, OrderStoreError) as exc:
            _log().warning("oms_submit_store_unread", failure=type(exc).__name__)
            raise StoreUnavailable from None

    async def _bounded[T](self, call: Awaitable[T]) -> T:
        async with asyncio.timeout(self._store_timeout_s):
            return await call

    def _page(self, summary: str) -> None:
        """The pager is a synchronous sink; one that raises is logged, never the answer."""
        try:
            self._pager.raise_alert("page", summary, machine_kind="order")
        except Exception as exc:
            _log().critical("oms_pager_failed", summary=summary, failure=type(exc).__name__)


def _outcome(rows: _Rows, lifecycle: str, answer: Mapping[str, Any] | None) -> SubmitOutcome:
    """Step 11's answer from the state B1 recorded (24 Sec.8.4 point 6): `rejected` is a 429 for a
    refused rate token, else a 502 with the exchange's return code; any other state is a 202. Each
    carries the rows the first persist wrote."""
    order_id, group_id, anchor_id = rows.order.id, rows.group_id, rows.anchor_id
    written = WrittenRows(rows.order, rows.first.group, rows.first.legs)
    if lifecycle != "rejected":
        return SubmitOutcome(202, anchor_id, order_id, group_id, lifecycle, written=written)
    if answer is not None and answer.get("error_code") == _RATE_CODE:
        return SubmitOutcome(
            429, anchor_id, order_id, group_id, lifecycle, RATE_LIMITED,
            retry_after_s=_retry_after(answer), written=written,
        )  # fmt: skip
    return SubmitOutcome(
        502, anchor_id, order_id, group_id, lifecycle, EXCHANGE_ERROR, _ret_code(answer),
        written=written,
    )  # fmt: skip


def _anchor(
    context: SubmitContext,
    anchor_id: UUID,
    *,
    trade_group_id: GroupId | None = None,
    order_id: UUID | None = None,
) -> NewAnchor:
    """The request's replay anchor (21 Sec.3.3.10), written last in the first persist: its
    principal, its key and fingerprint, and the one row it names (`ia_target`)."""
    return NewAnchor(
        id=anchor_id,
        created_by=context.actor.user_id,
        operation=context.operation,
        client_ref=str(context.anchored_ref),
        request_sha256=context.request_sha256,
        trade_group_id=trade_group_id,
        order_id=order_id,
    )


def _persist_refusal(refused: OrderStepRefused) -> OmsError:
    """A refused first persist's answer, nothing written: the share-locked re-check's refusals as
    403 (`account_not_live` as `trading_disabled`, `profile_changed` as `risk_limit_breached`), an
    audit that did not land as 503 `audit_unavailable`, a store's refusal of the order's own rows
    as a fault (500), anything else as 503 `store_unavailable`."""
    cause = refused.__cause__
    if isinstance(cause, SubmissionRefused):
        return TradingDisabled() if cause.reason == "account_not_live" else RiskRefused()
    if isinstance(cause, AuditNotDurable):
        return AuditNotDurable("the order's write-ahead audit did not land")
    if refused.deterministic:
        return OmsError("the first persist refused the order's own rows")
    return StoreUnavailable()
