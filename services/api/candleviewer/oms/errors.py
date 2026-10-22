"""Domain errors for the oms module (M14).

The order path's refusals (E29-T04, #913) end the module, with `PROBLEMS`: the one table of the
answer each OMS error gets at the HTTP edge, which the API layer renders. A refusal's `detail`
and `errors[]` are fixed sentences of CandleViewer's own: never exchange text (SR-E29-09), an id
or a secret (C-12.6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final

from candleviewer.domain.order_entry import OrderEntryRefusal, RefusalReason

if TYPE_CHECKING:  # the closed vocabularies only: no runtime import of the storage port
    from candleviewer.storage.repositories.submissions import AnchorConstraint, SubmissionRefusal

#: Codes the OMS raises itself, never mapped from an exchange answer (24 Sec.8.6).
ILLEGAL_TRANSITION: Final = "ILLEGAL_TRANSITION"
POST_TERMINAL_PUSH: Final = "POST_TERMINAL_PUSH"


class OmsError(Exception):
    """Base exception for the M14 `oms` module."""


class IllegalTransition(OmsError):
    """A command, or a step, that B1's static table does not list for the order's state (24
    Sec.8.2): refused before anything is sent or written. `attempted` is the event, or the state a
    step would enter."""

    code: Final = ILLEGAL_TRANSITION

    def __init__(self, state: str, attempted: str) -> None:
        super().__init__(f"{attempted} is not a transition of {state} (B1)")
        self.state = state
        self.attempted = attempted


class ReconcileAnomaly(OmsError):
    """S6: an exchange push for an order that is final, or a fill for one that is held, changes
    nothing. It is audited ahead (`oms.reconcile_anomaly`) and counted before this is raised."""

    code: Final = POST_TERMINAL_PUSH

    def __init__(self, state: str, event: str) -> None:
        super().__init__(f"{event} for an order that is {state} changes nothing (24 Sec.8.2 S6)")
        self.state = state
        self.event = event


class OrderStepRefused(OmsError):
    """B1 rolled the step back (24 Sec.8.2 S7, S11): its write-ahead row was refused, with nothing
    written, or an action failed, so the order is as it was and nothing was sent. A write whose
    outcome is not known is `OrderStepUnknown` instead. One whose connection was lost mid-COMMIT
    (`StorageTierUnavailable`) is refused all the same, as the error also stands for a connection
    never got; if its row landed, the order's next write that meets the row rebuilds the machine,
    but a `RECON_MISS` self-loop's second row makes the next hydration refuse the history (it
    pages), and a `SEND`'s `submitting` row is sent by a restart's hydration (24 Sec.8.2 "An
    unknown outcome", residuals). `failure` is the error's class. `deterministic` says the step's
    own data was refused (a `ValueError`, a `FillRefused`, a named constraint, or a statement the
    database refused with a data-class SQLSTATE, 22 or 23: hostile or malformed, OM-T04), so the
    same event is refused on every delivery; it is False for a failure that may pass later, such
    as a store that did not serve or a read it did not answer in time (`HolderNotRead`)."""

    def __init__(self, event: str, failure: str, *, deterministic: bool = False) -> None:
        super().__init__(f"the order did not take {event}: {failure}")
        self.event = event
        self.failure = failure
        self.deterministic = deterministic


class HolderNotRead(OmsError):
    """A fill's `exec_id` is stored already, and the read of which order holds it did not answer
    within `HOLDER_READ_TIMEOUT` (24 Sec.8.2 S4): the step wrote nothing and is refused, but a
    later delivery may pass, as the read may answer then. Never a refusal of the fill's own data,
    and never an outcome in doubt, which would rebuild the machine."""


class OrderStepUnknown(OmsError):
    """B1 rolled the step back, but its row may be ahead of the machine (24 Sec.8.2 S7): the write
    did not answer in time, so a COMMIT in flight may still have landed (`StepOutcomeUnknown`), or
    it met a row that had moved on (`StaleOrderState`, a fill the row holds already included). The
    facade has paged and rebuilt the order's machine from its events, where the row decides. A
    command's caller reads the order's state again rather than resending. A push's caller delivers
    the push again once, as the facade keeps no copy of it and a repeat changes nothing the first
    one did (S4, S5), and leaves it to reconciliation (24 Sec.8.5 step 2) if that is answered so
    too, so a push no rebuild settles is never delivered in a loop. `failure` is the error's
    class."""

    def __init__(self, event: str, failure: str) -> None:
        super().__init__(f"the outcome of {event} is not known: {failure}")
        self.event = event
        self.failure = failure


class OrderHistoryRefused(OmsError):
    """An order's `order_events` do not rebuild its row, or do not replay on B1 (threat model
    OM-T03; 24 Sec.8.2 "Recovery"): the order is not hydrated, nothing is written, and the facade
    pages. Names the fault in the history, never a value from it."""


class OrderNotLoaded(OmsError):
    """No machine in this process holds the order, and its stored row is not final (or the account
    holds no such order): nothing was sent."""


class OrderMachinesFull(OmsError):
    """The process holds `MAX_MACHINES` live order machines (C-2.18). A live machine is never
    evicted, so the new order is refused before anything is written."""


class OrderBufferFull(OmsError):
    """The order's reorder buffer holds `MAX_HELD` pushes (C-2.18): this one is refused, so the
    caller must resync it (24 Sec.8.5 step 2 applies every execution again)."""


class InvalidOrderLinkId(OmsError):
    """A string the §8.3 generator cannot produce, or parts that cannot render one."""


class UnsupportedExecutionMode(OmsError):
    """`replay` has no §8.3 environment letter, so generation fails closed (#846 Q4)."""


class OrderLinkIdExhausted(OmsError):
    """§8.3 rule 5: still colliding after 16 `seq2` increments, or at `seq2` = 3843."""

    def __init__(self, *, first: str, last: str) -> None:
        super().__init__(f"no free order_link_id from {first} to {last}")
        self.first = first
        self.last = last


class InvalidHistoryRetention(OmsError, ValueError):
    """An exchange order retention under 2 days: §8.3 rule 6 expires an id after the
    retention less one day, so 1 day or less would expire every id on creation."""


class ExecutionRefused(OmsError, ValueError):
    """An execution the order cannot absorb, hostile or malformed exchange data (OM-T04): a fill
    past `qty`, a qty or price of zero or less, a fee past `MAX_FEE_RATE` or against its rate, or a
    value its column cannot hold (numeric(38,18), and numeric(18,10) for `fee_rate`). Never
    clamped; the message names the rule, never a value."""


class DuplicateOrderLinkId(OmsError):
    """`ux_orders_link` already holds this id, so the order was not stored (#845 Gherkin).

    The rule 5 collision check runs before the insert; this is the race it cannot see. The id is
    taken: the caller never sends under it, and allocates again (24 Sec.8.3 rule 5)."""

    def __init__(self, order_link_id: str) -> None:
        super().__init__(f"order_link_id {order_link_id} is already stored")
        self.order_link_id = order_link_id


class AnchorTaken(OmsError):
    """The request's key is held already (E29-T04 #913): by an earlier request of the principal,
    or by a concurrent first persist that committed first, on the anchor (`ux_ia_principal_ref`)
    or an entry's group (`ux_tg_creator_ref`). Nothing was written; the caller answers the request
    as a repeat (21 Sec.3.3.10). Names the constraint only, one of `AnchorConstraint`, so a caller's
    dispatch on it is closed (SEC-2A-06)."""

    def __init__(self, constraint: AnchorConstraint) -> None:
        super().__init__(f"the request's key is held already ({constraint})")
        self.constraint: AnchorConstraint = constraint


class StopRequestInFlight(OmsError):
    """A stop request for the position is in flight (`ux_rs_in_flight`, 21 Sec.3.3.11), so this
    one was not recorded and nothing was written or sent."""


class SubmissionRefused(OmsError):
    """The first persist found, under its share locks, the order's account not live
    (`account_not_live`) or the leg's profile past the version it was sized from
    (`profile_changed`, SR-E28-15): nothing was written. `reason` names which, one of
    `SubmissionRefusal`, so a caller's dispatch on it is closed (SEC-2A-06)."""

    def __init__(self, reason: SubmissionRefusal) -> None:
        super().__init__(f"the order was not stored: {reason}")
        self.reason: SubmissionRefusal = reason


class AuditNotDurable(OmsError):
    """A write's write-ahead audit record did not land within its bound, so the write rolled back
    and nothing was written (C-2.9). Never a `TimeoutError`: no outcome is in doubt."""


class HandoverUnavailable(OmsError):
    """An order a lookup found under the row's `order_link_id`, which is not the row's (SR-E29-03),
    could not be handed to the next reconciliation pass (`oms_handovers`, 24 Sec.8.3 rule 3), which
    E29-T06 lands. Nothing was bound: the command port answers `place` with an empty lookup, so the
    order waits in `unknown` rather than `held` (S2-Q3), and `lookup` raises, as an empty answer
    there would send the order."""


class AckWithoutOrderId(OmsError):
    """An accepted create whose answer names no exchange order id the OMS keeps (`commands`'s id
    shape): an ambiguous outcome (ruling 3 on #3972, 24 Sec.8.3 rule 7), raised so B1 lands the
    order in `unknown` (S1), never in `submitted` with nothing bound."""


class ResendRefused(OmsError):
    """A create resumed after a restart, refused by the synchronous switches just before its
    re-send (C-2.21: the kill switch, live enablement, the order-entry gate): nothing was sent.
    `refusal` is the switch's own answer."""

    def __init__(self, refusal: OrderRefused) -> None:
        super().__init__(f"the resumed create was not sent: {type(refusal).__name__}")
        self.refusal = refusal


# --- The order path's refusals and their answers (E29-T04, #913) --------------------------------

#: The `errors[]` rules of `validation_failed` that 22-api-openapi.yaml `placeOrder` names.
RULE_NATIVE_STOP_REQUIRED: Final = "native_stop_required"
RULE_INTENT_MISMATCH: Final = "intent_mismatch"
#: Ruling R4: a stop in `atr` or `r_multiple` units until E28-T03's stop resolver (#907) lands.
RULE_STOP_UNIT_UNSUPPORTED: Final = "stop_unit_unsupported"
#: Ruling R4: a `sizing.mode` other than `fixed_qty` until E28-T03's sizer (#907) lands.
RULE_SIZING_MODE_UNSUPPORTED: Final = "sizing_mode_unsupported"


@dataclass(frozen=True, slots=True)
class FieldError:
    """One `errors[]` item of a refusal (22 `Problem.errors`): the request field, the rule that
    failed and a fixed sentence, which names no value but the instrument's own limits."""

    field: str
    rule: str
    message: str


class OrderRefused(OmsError):
    """A refusal of an order request, answered with its `PROBLEMS` row. `errors` lists every rule
    that failed, in the order they were checked, never only the first."""

    default_detail: ClassVar[str] = "The order request was refused."

    def __init__(self, detail: str | None = None, *, errors: Iterable[FieldError] = ()) -> None:
        self.detail = self.default_detail if detail is None else detail
        self.errors = tuple(errors)
        super().__init__(self.detail)


class OrderInvalid(OrderRefused):
    """`validation_failed`: the native stop or the intent rule (SR-E29-01), a stop unit, a missing
    field, or an instrument limit that no narrower code names (a price bound, the leverage)."""

    default_detail = "The order failed validation."


class StopUnitUnsupported(OrderInvalid):
    """R4: the stop, the request's or the profile's, is in `atr` or `r_multiple` units."""

    def __init__(self) -> None:
        message = "Stops in atr or r_multiple units are not available yet."
        super().__init__(errors=(FieldError("stop_loss", RULE_STOP_UNIT_UNSUPPORTED, message),))


class TickSizeViolation(OrderRefused):
    default_detail = "A price is not a multiple of the instrument's tick size."


class LotSizeViolation(OrderRefused):
    default_detail = "The quantity breaks the instrument's lot step, size or notional limits."


class AccountScopeDenied(OrderRefused):
    """A body's exchange account outside the caller's grants, or one that does not exist."""

    default_detail = "The exchange account is not one you may trade."


class RiskRefused(OrderRefused):
    """`risk_limit_breached`: the risk gate refused the sized order (SR-E29-04), or the effective
    profile does not allow the symbol."""

    default_detail = "The account's risk limits or profile do not allow this order."


class TradingDisabled(OrderRefused):
    """`trading_disabled` with no `reason`: live trading not enabled, the B18 kill switch or the
    read-only gate. The order-entry gate's refusal carries a `reason` (`OrderEntryRefused`)."""

    default_detail = "Order entry is disabled."


class OrderEntryRefused(TradingDisabled):
    """The order-entry gate's refusal at the OMS intake (#3382, ruling R1's second check):
    `trading_disabled` with the gate's `reason` and `detail`, which are CandleViewer's own text
    (`OrderEntryRefusal`), as the API renders them (`TradingDisabledProblem`)."""

    def __init__(self, refusal: OrderEntryRefusal) -> None:
        super().__init__(refusal.detail)
        self.reason: RefusalReason = refusal.reason


class SessionNotArmed(OrderRefused):
    default_detail = "This session is not armed for live trading."


class OrderNotFound(OrderRefused):
    """A foreign order id and a missing one, alike (id routes)."""

    default_detail = "No such order."


class IdempotencyKeyReuse(OrderRefused):
    default_detail = "The Idempotency-Key was first used with another request."


class IdempotencyInFlight(OrderRefused):
    """The key's first request is still being processed: its anchor is undecided within
    `CV_OMS_INFLIGHT_STUCK_S` of its creation (21 Sec.3.3.10 "Repeats"). The repeat sends
    nothing; `retry_after_s` is the answer's `Retry-After`."""

    default_detail = "A request with this Idempotency-Key is still being processed."

    def __init__(self, *, retry_after_s: int) -> None:
        super().__init__()
        self.retry_after_s = _positive_delay(retry_after_s)


class StopRequestPending(OrderRefused):
    """`stop_request_in_flight`: the entry's stop request met one still holding its position, in
    flight past the bounded retry or waiting for the complete read (21 Sec.3.3.11), so nothing
    was recorded or sent and the key is not bound: after `Retry-After` the same request is a
    first submission (#4006's ruling on 2a-Q4)."""

    default_detail = "Send the entry again once the position's stop request is answered."

    def __init__(self, *, retry_after_s: int) -> None:
        super().__init__()
        self.retry_after_s = _positive_delay(retry_after_s)


class VersionConflict(OrderRefused):
    """A stale `If-Match` (R5): nothing is sent."""

    default_detail = "The order has changed since the version you named."


class OrderNotAmendable(OrderRefused):
    default_detail = "The order cannot be amended in its current state."


class RateBudgetExceeded(OrderRefused):
    """`RATE_BUDGET_EXCEEDED` (24 Sec.8.7): the per-UID budget gave no token within its bounded
    wait, so nothing was sent. `retry_after_s` is the answer's `Retry-After`."""

    default_detail = "The exchange rate budget is spent; retry later."

    def __init__(self, *, retry_after_s: int) -> None:
        super().__init__()
        self.retry_after_s = _positive_delay(retry_after_s)


class ExchangeRejected(OrderRefused):
    """A business rejection. The answer carries the exchange's return code only: the constructor
    takes no text, so the exchange's message can never reach a problem body (SR-E29-09, 24
    Sec.8.6 code-only rule)."""

    default_detail = "The exchange refused the order."

    def __init__(self, *, ret_code: int | None) -> None:
        super().__init__()
        self.ret_code = ret_code


class ClockDriftBlocked(OrderRefused):
    """Order entry halted until time sync recovers (24 Sec.8.6, `10002`); `retry_after_s` is the
    answer's `Retry-After`."""

    default_detail = "Order entry is paused until the clock is back in sync."

    def __init__(self, *, retry_after_s: int) -> None:
        super().__init__()
        self.retry_after_s = _positive_delay(retry_after_s)


class StoreUnavailable(OrderRefused):
    """The order cannot be recorded before its send (S7), so nothing reaches the exchange."""

    default_detail = "Orders cannot be recorded right now, so none is sent."


class ExchangeUnavailable(OrderRefused):
    """A read the order needs before it is recorded failed or did not answer in time (a
    reduce-only order's position, SR-E29-01), so nothing was recorded or sent; `retry_after_s` is
    the answer's `Retry-After`."""

    default_detail = "The exchange did not answer, so the order was not sent."

    def __init__(self, *, retry_after_s: int) -> None:
        super().__init__()
        self.retry_after_s = _positive_delay(retry_after_s)


class EnvironmentMismatch(OmsError):
    """C-2.11: an order built for one environment met a route to another, a demo account's order
    and a live client among them. Never sent; an invariant broken, so it pages."""

    def __init__(self, *, order_environment: str, route_environment: str) -> None:
        super().__init__(
            f"an order for {order_environment} met a route to {route_environment} (C-2.11)"
        )
        self.order_environment = order_environment
        self.route_environment = route_environment


def _positive_delay(seconds: int) -> int:
    if seconds < 1:
        raise ValueError("retry_after_s is a delay of at least one second")
    return seconds


@dataclass(frozen=True, slots=True)
class Problem:
    """The answer of an OMS error: its HTTP status and `x-error-codes` slug, whether it carries
    `Retry-After`, and whether it pages the operator."""

    status: int
    code: str
    retry_after: bool = False
    pages: bool = False


#: A fault no row names: the API's redacted 500.
INTERNAL_ERROR: Final = Problem(500, "internal_error")

#: The one mapping table (the #913 plan's taxonomy with rulings R4, R5 and R12, and the rows of
#: slice 2b's pipeline). A class answers with its own row or its nearest base's (`problem_for`);
#: `OrderPlacementRefused` (`validator`) and `OrderEntryRefused` are `TradingDisabled`s, and
#: `StopUnitUnsupported` an `OrderInvalid`. A refusal with `Retry-After` carries `retry_after_s`.
PROBLEMS: Final[Mapping[type[OmsError], Problem]] = MappingProxyType(
    {
        OrderInvalid: Problem(400, "validation_failed"),
        TickSizeViolation: Problem(400, "tick_size_violation"),
        LotSizeViolation: Problem(400, "lot_size_violation"),
        AccountScopeDenied: Problem(403, "account_scope_denied"),
        RiskRefused: Problem(403, "risk_limit_breached"),
        TradingDisabled: Problem(403, "trading_disabled"),
        SessionNotArmed: Problem(403, "session_not_armed"),
        OrderNotFound: Problem(404, "not_found"),
        IdempotencyKeyReuse: Problem(409, "idempotency_key_reuse"),
        IdempotencyInFlight: Problem(409, "idempotency_in_flight", retry_after=True),
        StopRequestPending: Problem(409, "stop_request_in_flight", retry_after=True),
        VersionConflict: Problem(412, "version_conflict"),
        OrderNotAmendable: Problem(422, "order_not_amendable"),
        RateBudgetExceeded: Problem(429, "exchange_rate_limited", retry_after=True),
        OrderLinkIdExhausted: Problem(500, "internal_error", pages=True),
        EnvironmentMismatch: Problem(500, "internal_error", pages=True),
        OrderMachinesFull: Problem(500, "internal_error", pages=True),
        ExchangeRejected: Problem(502, "exchange_error"),
        ClockDriftBlocked: Problem(503, "clock_drift", retry_after=True),
        StoreUnavailable: Problem(503, "store_unavailable"),
        ExchangeUnavailable: Problem(503, "exchange_unavailable", retry_after=True),
        AuditNotDurable: Problem(503, "audit_unavailable"),
    }
)


def problem_for(error: OmsError) -> Problem:
    """The answer of `error`'s nearest class in `PROBLEMS`; an OMS error no row names is a fault,
    `INTERNAL_ERROR`."""
    for cls in type(error).__mro__:
        if issubclass(cls, OmsError) and cls in PROBLEMS:
            return PROBLEMS[cls]
    return INTERNAL_ERROR
