"""The ports the submission pipeline consumes, and their interim implementations (E29-T04, #913).

The pipeline (24-internal-schemas.md Sec.8.4) consumes interfaces whose owners have not landed:
the sizer and the stop resolver (E28-T03, #907), the risk gate (E39-S01, #954) and the arm record
(E30-S04, #1088). Ruling R4 on #913 approves an interim implementation of each, failing closed on
live:

- `FixedQtySizer` serves `fixed_qty` sizing only, floored to the lot step unless `round_to_lot` is
  false (the validator then judges the step); any other mode is `validation_failed` /
  `sizing_mode_unsupported`.
- `InterimStopResolver` serves `price`, `ticks` and `percent` stops and, for an entry without one,
  the profile's offset; `atr` and `r_multiple` are `validation_failed` / `stop_unit_unsupported`.
  A request's `percent` is the percent a client writes (`"0.4"` is 0.4 %), the profile's a
  fraction (24 Sec.9.2). The stop lands on a tick, rounded away from the entry, never closer
  (24 Sec.9.3.1). Its take-profit (S2-Q6) serves the request's `price`, `ticks` and `percent` on
  the profit side, on a tick rounded toward the entry (Q-L), and none when the request names none;
  `atr` and `r_multiple` are `stop_unit_unsupported` on `take_profit`. An offset that is no finite
  figure is passed through unresolved, for the guard to refuse (#2877 ruling 2).
- `InterimRiskGate` admits a demo order without evaluating it and refuses every other one.
- `NoArmRecords`: no arm record exists yet, so every live order is refused; demo needs none
  (SR-043).

The native stop depends on none of them: `classify.NativeStopGuard` judges whatever the stop
resolver answers, so C-2.6 holds on every path whatever the port (C-4.14).
`announce_interim_ports` logs one WARNING per interim port at startup and sets
`oms_interim_ports{port}`, so nobody runs them on live unknowingly; `announce_interim_port` does the
same for a port outside the slots (slice 3: the B18 kill switch, B1's machine-event sink).

The rate step has no port of its own here. #2877's G-8 rulings (item 4) have the trading port take
the rate token once per call, and B1's `rate` verdict read a non-consuming headroom figure until
E34-T02's `reserve()`: `exchange.base`'s `RateHeadroomPort`, which each environment's trading port
implements. `routing.TradingRouter.headroom` reads it and answers a `RateReading`. Nothing here
imports the exchange adapter (C-2.2).

The second slice adds two ports with no interim, both bound by slice 3's wiring. `ClockHealth` is
the exchange-clock verdict order entry halts on (24 Sec.8.6 `10002`, `clock_halt.ClockHalt`), in
the shape of `ingestion.clock.ClockGuard`, so the guard is wired as it stands while `oms` never
imports `ingestion` (C-3.4). `TradingAccounts` resolves the account the OMS has scope-checked to
the trading port's `AccountRef`, whose `key_ref` only that account's active key fills
(SR-E27-21).

The command port (`commands.OmsCommandPort`) consumes five more, which slice 3 binds:
`SubmitAudit` (the keyed audit records a stop request's row names), `OrderHandovers` (with
`NoHandoverStore`, its one production binding until E29-T06), `CredentialRejections` (24 Sec.8.6
`AUTH_ERROR`), `TradingSwitches` (C-2.21's switches before a re-send) and `StopRequestGate`, which
S3-H's `stop_gate.ResolvingStopGate` serves (21 Sec.3.3.11). `ForeignOrderLockout` (SR-E27-19) is
declared here for E29-T05 and E29-T06, its callers.

The private-stream consumer (E29-T05, #848; 24 Sec.8.12) consumes five more, which its last
slice binds and nothing binds yet: `StreamedAccounts` (the accounts it subscribes),
`ReconciliationRequests` (a REST pass for an account whose stream resyncs), `AccountNotices` (23
Sec.15.9's `account_notice`), `ExecutionHandovers` (a fill no row takes, kept for the next pass,
a sibling of `OrderHandovers`) and `ProtectionReadings` (the stop of a position no live order
protects), beside `TradingAccounts`, `CredentialRejections` and `ForeignOrderLockout`. Until their
owners land, `NoHandoverStore` refuses both hand-overs and `NoReconciliation` every pass (E29-T06;
a live process refuses to start with it), and `NoPositionProtection` a lost stop (E32-T02).

The pipeline itself (`submit.OrderSubmission`) consumes three more, which slice 3 binds too:
`Instruments` (the instrument-info cache), `ReferencePrices` (a market order's reference price)
and `Profiles` (`accounts.profile_cache.EffectiveProfiles`, in its own shape). A request's records
name its principal (`SubmitActor`, C-2.9): `RequestRecord`, written through `SubmitAudit` beside the
keyed records, which an entry's stop requests carry with their actor.

The vocabulary the ports speak lives here too: `OrderEffect` (SR-E29-01), `StopOffset` (22
`Offset`), `SizingRequest` (22 `Sizing`), `ArmToken`, the session's arm token held masked (C-12.6)
and compared in constant time (SR-043), and `SizedOrder`, the order the validator, the risk gate
and B1 see once it is sized and rounded (SR-E29-04), which cannot be built as an entry without a
stop, nor with a stop off the protective side (C-2.6), nor with a take-profit off the profit
side. Every decision by effect here and in
`classify` and `validator` fails closed: any effect but `OrderEffect.REDUCE` is an entry's.
Verdicts are B1's gate values (`statechart/bindings/b01_order.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import Any, ClassVar, Final, Literal, Protocol, get_args
from uuid import UUID

import structlog

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Px, Qty, Side, Symbol
from candleviewer.exchange.base.models import AccountRef, Execution, Order
from candleviewer.exchange.policy import InstrumentPolicy
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.secret_type import ComparableSecret, Secret
from candleviewer.risk.models import RiskDecision, RiskRefusal
from candleviewer.settings import Environment as ProcessEnvironment

from .errors import (
    RULE_SIZING_MODE_UNSUPPORTED,
    FieldError,
    HandoverUnavailable,
    OrderInvalid,
    ProtectionReadingsUnavailable,
    ReconciliationUnavailable,
    StopUnitUnsupported,
    TradingDisabled,
)
from .order_link import OrderPurpose

Verdict = Literal["pass", "fail"]
PASSED: Final[Verdict] = "pass"
FAILED: Final[Verdict] = "fail"
OffsetUnit = Literal["price", "ticks", "percent", "atr", "r_multiple"]
SizingMode = Literal[
    "fixed_qty", "fixed_notional", "pct_equity", "risk_based", "pct_position", "profile"
]
OrderType = Literal["market", "limit"]
PortName = Literal["sizer", "stop_resolver", "risk_gate", "arm_records"]
PORT_NAMES: Final[tuple[PortName, ...]] = get_args(PortName)
#: The interim ports the OMS runtime announces beside the `SubmissionPorts` slots (#913 slice 3):
#: the B18 kill switch until E39-S03 (ruling Q5), and B1's `machine_events` sink while no statechart
#: persistence bundle serves it (20 Sec.6.2). Their binders announce them (`announce_interim_port`).
RuntimePortName = Literal["kill_switch", "machine_event_sink"]
#: `oms_interim_ports{port}`'s closed label set, one series each.
INTERIM_PORT_LABELS: Final[tuple[PortName | RuntimePortName, ...]] = (
    *PORT_NAMES,
    *get_args(RuntimePortName),
)
INTERIM_PORTS_METRIC: Final = "oms_interim_ports"
#: R4: the one environment the interim risk gate admits, unevaluated.
_UNEVALUATED: Final[frozenset[Environment]] = frozenset({"demo"})
#: SR-043: the environment whose order mutations need an arm token.
_ARMED: Final[frozenset[Environment]] = frozenset({"live"})
_ONLY_FIXED_QTY: Final = "Only fixed_qty sizing is available yet."


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class OrderEffect(StrEnum):
    """An order's effect on the exchange-truth position (SR-E29-01): an `entry` opens or adds to
    it, a `reduce` order only reduces it. It decides the native stop and the intent, never the
    order's label."""

    ENTRY = "entry"
    REDUCE = "reduce"


@dataclass(frozen=True, slots=True)
class StopOffset:
    """22 `Offset` for a stop: an absolute level (`price`) or a distance from the reference price
    in `ticks`, `percent` (as a client writes it), `atr` or `r_multiple`."""

    unit: OffsetUnit
    value: Decimal


@dataclass(frozen=True, slots=True)
class SizingRequest:
    """22 `Sizing`: the members the interim sizer reads."""

    mode: SizingMode
    qty: Qty | None = None
    round_to_lot: bool = True


@dataclass(frozen=True, slots=True)
class SizedOrder:
    """The order once sized, rounded, classified and given its stop: what `Validator.check_order`,
    the risk gate and B1 see (SR-E29-04). `reference_price` is what the stop and the notional are
    measured from (24 Sec.9.3 step 2): a limit order's price, else the market's reference."""

    account_id: AccountId
    environment: Environment
    symbol: Symbol
    side: Side
    order_type: OrderType
    qty: Qty
    price: Px | None
    trigger_price: Px | None
    reference_price: Px
    reduce_only: bool
    intent: OrderPurpose
    effect: OrderEffect
    stop_loss: Px | None
    take_profit: Px | None = None

    def __post_init__(self) -> None:
        """The invariants every later check relies on, whatever the call order, as strict as
        `classify.stop_errors` and `classify.take_profit_errors` (C-2.6, SR-E29-01, S2-Q6):
        `effect` is an `OrderEffect`, a string that names none refused, and any effect but
        `REDUCE` is an entry's; an entry carries a stop; any stop is finite, above zero and on the
        protective side of a reference price above zero, below it for a buy and above it for a
        sell; any take-profit is finite, above zero and on the profit side, above a buy's
        reference price and below a sell's (#2877 ruling 2); and an order that only reduces is
        reduce-only."""
        object.__setattr__(self, "effect", OrderEffect(self.effect))
        entry = self.effect is not OrderEffect.REDUCE
        stop, reference = self.stop_loss, self.reference_price
        if stop is None:
            if entry:
                raise ValueError("an entry carries a stop_loss (C-2.6)")
        elif not stop.is_finite() or stop <= 0:
            raise ValueError("a stop_loss is finite and above zero (C-2.6)")
        elif not reference.is_finite() or reference <= 0:
            raise ValueError("a stop_loss is judged against a reference_price above zero")
        elif not (stop < reference if self.side == "buy" else stop > reference):
            raise ValueError("a stop_loss is below a buy's reference_price, above a sell's (C-2.6)")
        take_profit = self.take_profit
        if take_profit is not None:
            if not take_profit.is_finite() or take_profit <= 0:
                raise ValueError("a take_profit is finite and above zero (#2877 ruling 2)")
            if not reference.is_finite() or reference <= 0:
                raise ValueError("a take_profit is judged against a reference_price above zero")
            if not (take_profit > reference if self.side == "buy" else take_profit < reference):
                raise ValueError("a take_profit is above a buy's reference_price, below a sell's")
        if not entry and not self.reduce_only:
            raise ValueError("an order that only reduces is reduce_only (SR-E29-01)")


class ArmToken(ComparableSecret[str]):
    """The session's arm token (SR-043, the `X-Arm-Token` header), held masked: its `str`, `repr`
    and format are `[redacted]`, and the redaction filter writes it as `***` under any key, so no
    log line, exception or repr carries it (C-12.6). No token code calls `reveal()` (refused
    outside `secrets/`, M2 R10): an arm-record check compares a presented token with the issued
    one through `==`; the token is never bound to a logger.

    Two tokens compare in constant time over their encoded values
    (`ComparableSecret.equals_constant_time`, `hmac.compare_digest` underneath), so the time a
    comparison takes tells nothing of how much of a presented token matches (SR-043). A token
    never equals another kind of `Secret`, whose `==` is not constant time, nor a plain string.
    Every token hashes alike: equal tokens hash alike, and the hash carries nothing of the
    token."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ArmToken):
            return self.equals_constant_time(other)
        if isinstance(other, Secret):
            return False
        return NotImplemented

    def __hash__(self) -> int:
        return hash(ArmToken)


class Sizer(Protocol):
    """E28-T03 (#907): the order's quantity, sized and rounded, or an `OrderRefused`."""

    def size(self, sizing: SizingRequest, instrument: Instrument) -> Qty: ...


class StopResolver(Protocol):
    """E28-T03 (#907): the stop-loss price: the request's `stop`, else for an entry the profile's
    offset, else `None`; `StopUnitUnsupported` for a unit it cannot resolve. It decides nothing:
    `classify.NativeStopGuard` judges its answer. And the take-profit price (S2-Q6): the request's
    `take_profit`, or `None`, judged by `classify.take_profit_errors`."""

    def resolve(
        self,
        stop: StopOffset | None,
        *,
        side: Side,
        reference_price: Px,
        effect: OrderEffect,
        instrument: Instrument,
        profile: AccountProfile | None,
    ) -> Px | None: ...

    def resolve_take_profit(
        self,
        take_profit: StopOffset | None,
        *,
        side: Side,
        reference_price: Px,
        instrument: Instrument,
        profile: AccountProfile | None,
    ) -> Px | None: ...


class RiskGate(Protocol):
    """E39-S01 (#954): the verdict on the sized, rounded order, never the intent (SR-E29-04)."""

    def check(self, order: SizedOrder, *, profile: AccountProfile | None) -> RiskDecision: ...


class ArmRecords(Protocol):
    """E30-S04 (#1088): whether the session's arm token admits an order mutation that needs one
    (SR-043); `FAILED` for a token missing, expired, revoked or bound to another session. The
    token arrives masked, an `ArmToken`, and is never logged (C-12.6). The real port compares a
    presented token through `ArmToken`'s own equality (`ComparableSecret.equals_constant_time`),
    never through `reveal()` (refused outside `secrets/`, M2 R10) and never with a plain `==` on
    the strings (SR-043)."""

    def check(
        self, *, session_id: UUID, environment: Environment, token: ArmToken | None
    ) -> Verdict: ...


class ClockHealth(Protocol):
    """The exchange-clock verdict order entry halts on (24 Sec.8.6 `10002`): `ClockGuard`'s own
    members (`ingestion/clock.py`), so slice 3 wires the guard with no adapter. It records the
    verdict; `clock_halt.ClockHalt` enforces it."""

    def assert_healthy(self) -> None:
        """`ClockDriftError` when no measurement has succeeded yet, or the measured offset is past
        the hard threshold. Slice 3's binding answers an unmeasured clock, and one not composed,
        with `OmsNotReady` instead (ruling Q8): only a measured halt is `clock_drift`."""
        ...

    def offset_age_s(self) -> float:
        """Seconds since the last successful measurement, on a monotonic clock; `inf` before the
        first."""
        ...

    async def resync_after_signature_failure(self, *, reason: str) -> int:
        """Measure at once, as a request refused for its timestamp asks (`10002`), and return the
        offset measured, in microseconds, which the OMS does not read. Raises when no sample
        answered: the last measurement stands."""
        ...


class TradingAccounts(Protocol):
    """The account an order is signed for (SR-E27-21, KV-E14): the exchange account the OMS has
    already scope-checked, as the trading port's `AccountRef`, whose `key_ref` is that account's
    active key. It takes the account id alone, so no request field can select a key."""

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        """The account's UID, environment and active key (`key_ref`, never the key itself). An
        `OrderRefused`, with nothing recorded or sent, for an account the OMS does not trade or
        one with no active key."""
        ...


class Instruments(Protocol):
    """The instrument-info cache (24 Sec.1.3, `ingestion.instruments`, which slice 3 binds): the
    symbol's instrument, or None when none is listed under it."""

    async def instrument(self, symbol: Symbol) -> Instrument | None: ...


class ReferencePrices(Protocol):
    """The market's reference price a market order is measured from (24 Sec.9.3 step 2: the mid,
    else the last price), or None when the market shows none; slice 3 binds the ticker."""

    async def reference_price(self, symbol: Symbol) -> Px | None: ...


class Profiles(Protocol):
    """The effective profile (24 Sec.9.3): `accounts.profile_cache.EffectiveProfiles`'s own member,
    so slice 3 wires the cache as it stands. The given profile, or the account's default; raises
    `AccountNotFoundError` when the account has no such profile (another account's included) and
    `ProfileUnavailableError` when the store cannot answer (SR-E28-24: never a default)."""

    async def get_effective_profile(
        self, account_id: UUID, profile_id: UUID | None = None
    ) -> AccountProfile: ...


@dataclass(frozen=True, slots=True)
class RateReading:
    """The rate step's verdict (24 Sec.8.7, `routing.TradingRouter.headroom`): whether the order's
    request would get its rate token within its lane's wait, read without taking one. A refusal
    carries `retry_after_s`, the whole seconds of its `Retry-After` (429 `exchange_rate_limited`);
    an admission carries none."""

    available: bool
    retry_after_s: int | None = None

    def __post_init__(self) -> None:
        delay = self.retry_after_s
        if self.available:
            if delay is not None:
                raise ValueError("an admission carries no retry_after_s")
        elif isinstance(delay, bool) or not isinstance(delay, int) or delay < 1:
            raise ValueError("a refusal carries a retry_after_s of at least one whole second")


# --- The command port's collaborators (`commands.OmsCommandPort`) --------------------------------

#: An M19 record's outcome and severity, as `order_machine.OrderAuditRecord` names them (a test
#: pins the two alike).
AuditOutcome = Literal["success", "failure", "denied"]
AuditSeverity = Literal["info", "warning", "error", "critical"]
#: What a keyed record is about: a stop request's record has its row as its object (21
#: Sec.3.3.11 "Audit").
AuditObject = Literal["order", "recorded_stop"]
#: What a request's own record is about: its order, an entry's group, or, for a refusal before
#: any row exists, the account it named.
RequestObject = Literal["order", "trade_group", "exchange_account"]


@dataclass(frozen=True, slots=True)
class SubmitActor:
    """Who sends an order request, as its records name them (C-2.9: the actor and the role): the
    principal the route authenticated, or a rule's owner (M15), never a client value, with the
    session and the address the route read."""

    user_id: UUID
    role: str
    session_id: UUID | None = None
    ip: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """One record an order request writes about itself (`submit.OrderSubmission`, C-2.9): its
    intent with its rows (`orders.submit`, `trade_group.submit`), a refusal (`denied`, its problem
    code as `reason`) or its outcome, naming the requesting principal. `detail` holds ids, state
    names and codes, never a price, a size, the key or a secret (C-12.6); `request_id` is the
    request's correlation id (`X-Correlation-Id`, #3990), None for a job."""

    action: str
    account_id: UUID
    object_kind: RequestObject
    object_id: UUID
    outcome: AuditOutcome
    severity: AuditSeverity
    reason: str
    actor: SubmitActor
    detail: Mapping[str, str | None]
    request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class KeyedRecord:
    """One audit record the order path writes under an id it knows ahead (21 Sec.3.3.11 "Audit"):
    `SubmitAudit.record_id(action, name)`'s, so a row carries it (`audit_record_id`) before the
    record lands, and a repeat of the write stores no second row. `detail` holds ids, state names
    and reasons, never a price, a size or a secret (C-12.6); `actor_user_id` is None for the
    system (`system:oms`). `request_id` is the correlation id of the HTTP request the record is
    written for (`X-Correlation-Id`, #3990), None for a job, a restart's resume or a fill-driven
    attach (21 Sec.3.10.1). `actor` is the requesting principal of a record a request writes (an
    entry's stop requests), whose `actor_user_id` it is; None for the system."""

    action: str
    name: str
    account_id: UUID
    object_kind: AuditObject
    object_id: UUID
    outcome: AuditOutcome
    severity: AuditSeverity
    reason: str
    actor_user_id: UUID | None
    detail: Mapping[str, str | None]
    request_id: UUID | None = None
    actor: SubmitActor | None = None

    def __post_init__(self) -> None:
        if self.actor is not None and self.actor.user_id != self.actor_user_id:
            raise ValueError("a keyed record's actor_user_id is its actor's")


class SubmitAudit(Protocol):
    """The audit writer's records of the order path, which slice 3 wires (`oms` never imports
    `audit`, C-3.3): a `KeyedRecord` through `AuditWriter.emit_keyed`, a request's
    `RequestRecord` through `emit`. `record_id` is the id `write` stores a keyed record under,
    the writer's `keyed_record_id(action, name)`, fixed for good; `write` makes the record
    durable or raises (C-2.9)."""

    def record_id(self, action: str, name: str) -> UUID: ...

    async def write(self, record: KeyedRecord | RequestRecord) -> None: ...


class OrderHandovers(Protocol):
    """Where a lookup hands an order it found under a row's id that is not the row's (SR-E29-03)
    to the next reconciliation pass: `oms_handovers`, appended before the lookup answers (24
    Sec.8.3 rule 3), idempotent on the account and the order's exchange id. E29-T06 lands the
    table and its writer; until then `NoHandoverStore` is the one production binding."""

    async def hand_over_order(self, account_id: AccountId, order: Order) -> None:
        """Append `order` for the next pass, or raise `HandoverUnavailable`."""
        ...


class NoHandoverStore:
    """`OrderHandovers` and `ExecutionHandovers` until E29-T06's `oms_handovers` (S2-Q3's
    deviation): no hand-over can be recorded, so each is `HandoverUnavailable`, and an order whose
    id another order holds waits in `unknown`, where reconciliation meets the other order, instead
    of `held`."""

    async def hand_over_order(self, account_id: AccountId, order: Order) -> None:
        raise HandoverUnavailable("no hand-over store exists until E29-T06 (S2-Q3)")

    async def hand_over_execution(
        self, account_id: AccountId, execution: Execution, *, empty_read: bool = False
    ) -> None:
        raise HandoverUnavailable("no hand-over store exists until E29-T06 (S2-Q3)")


class CredentialRejections(Protocol):
    """24 Sec.8.6 `AUTH_ERROR`: the exchange refused a request for its key (an invalid key, a bad
    signature, a missing permission). The OMS passes the code and the exchange's return code on as
    they came (the orchestrator's Q-I ruling); slice 3's binding maps the return code through the
    adapter's public key-verdict table (a code outside it, or none, is `unknown_key`), flips the
    account's key standing in memory and pages the Owner (ruling Q10; the durable reaction is
    #4243), so `oms` holds no exchange code (C-2.2)."""

    async def refused(
        self, account_id: AccountId, *, error_code: str, exchange_ret_code: int | None
    ) -> None: ...


class TradingSwitches(Protocol):
    """The synchronous switches checked just before a send (C-2.21): live trading enabled for a
    live account, the B18 kill switch and the order-entry gate (#3382, ruling R1's second check).
    The refusal, or None; it reads in-memory state and never awaits."""

    def refusal(
        self, account_id: AccountId, environment: Environment
    ) -> TradingDisabled | None: ...


@dataclass(frozen=True, slots=True)
class PositionKey:
    """The position a stop request is for (21 Sec.3.3.11, `ux_rs_in_flight`): its account, symbol
    and position index."""

    account_id: AccountId
    symbol: Symbol
    position_idx: int


class StopRequestGate(Protocol):
    """Asked before every stop request for a position leaves (21 Sec.3.3.11): an entry's first
    persist, and `attach_stop` before its record. `clear` returns when the key may take a request,
    and raises `StopRequestPending` while a row of the key waits for the complete read, which
    S3-H's `stop_gate.ResolvingStopGate` starts: an entry is refused at once (`wait_s` 0), an
    attach after waiting up to `wait_s` for that read (24 Sec.8.4). An attach says it is
    `protective`: it may take the read's slot kept for it and no cooldown holds it. The caller
    bounds the call as any other (`commands.PORT_TIMEOUT_S`, C-2.18), whatever the gate bounds
    itself."""

    async def clear(
        self, key: PositionKey, *, wait_s: float = 0.0, protective: bool = False
    ) -> None: ...


#: The `Retry-After` of a request refused because a row of its key waits for the complete read, in
#: seconds: only that read clears it (the orchestrator's Q-D ruling); a key whose read cleared
#: nothing waits as long before an entry asks the venue again.
STOP_REQUEST_RETRY_AFTER_S: Final = 5
#: The gate's bound on each of its reads of the key's waiting rows, in seconds.
STOP_GATE_READ_TIMEOUT_S: Final = 1.0


#: What a lockout opens on: an order, or a trade execution, with no OMS intent (24 Sec.8.10); and,
#: until E29-T06 can keep one, a fill whose intent is undecided, fail closed (Sec.8.12 step 4).
Finding = Literal["order", "execution", "undecided"]


class ForeignOrderLockout(Protocol):
    """SR-E27-19's freeze (24 Sec.8.10; S2-Q7): the risk module's one setter of the
    `reconciliation_foreign_order` lockout, which E39 owns and the private-stream consumer (E29-T05)
    and reconciliation (E29-T06) call. Opening it where it is open already changes nothing, and it
    opens once per finding, keyed by the order's exchange id or the fill's `exec_id`, so the
    Owner's release sticks. T04 declares it and calls it nowhere."""

    async def open(self, account_id: AccountId, *, finding: Finding, key: str) -> None: ...


# --- The private-stream consumer's collaborators (E29-T05, 24 Sec.8.12) -------------------------

#: Why a stream asks for a REST pass: its `resyncing` reasons (24 Sec.14.2 rule 13), as
#: `exchange.base.models.PRIVATE_STREAM_REASONS` names them (a test pins the two alike).
ResyncReason = Literal["connected", "reconnected", "rejected_frame"]
#: The `reason` of an account notice (23-ws-protocol.md Sec.15.9, SR-E29-10): its current values,
#: the stream lost (E29-T05) and reconciliation's three (E29-T06).
AccountNoticeReason = Literal[
    "oms.account_resyncing", "oms.account_desync", "oms.account_stale", "oms.account_synced"
]


class StreamedAccounts(Protocol):
    """The accounts the private-stream consumer subscribes (24 Sec.8.12), the set account health
    monitors: each enabled and not deleted, holding an active key, of an environment the router
    has a port for. Ids alone, so nothing it answers selects a key (`TradingAccounts`, SR-E27-21).
    The consumer reads it again on each of health's tracking refreshes (15 s), bounding the call
    (C-2.18), and skips an account whose resolve is refused (`OrderRefused`), logged by its id
    alone, until the next read. A read that cannot answer raises; an empty set found none."""

    async def streamed_accounts(self) -> frozenset[AccountId]: ...


class ReconciliationRequests(Protocol):
    """Asks for a REST reconciliation of one account (24 Sec.8.5, which runs on every private-WS
    reconnect: B19's `RECONNECTED`), the consumer's answer to a `resyncing` status, as private
    topics send no snapshot (C-2.5). It returns once the request is taken, never once the pass has
    run, and the caller bounds the call (C-2.18)."""

    async def request_reconciliation(
        self, account_id: AccountId, *, reason: ResyncReason
    ) -> None: ...


class NoReconciliation:
    """`ReconciliationRequests` until E29-T06 (24 Sec.8.12): each request is
    `ReconciliationUnavailable`, which the consumer logs, counts and pages once per episode
    (`oms_reconciliation_unavailable`), keeping `oms.account_resyncing` in force without holding
    order entry."""

    async def request_reconciliation(self, account_id: AccountId, *, reason: ResyncReason) -> None:
        raise ReconciliationUnavailable("no reconciliation pass exists until E29-T06")


def refuse_live_without_reconciliation(
    environment: ProcessEnvironment, port: ReconciliationRequests
) -> None:
    """The live start-up self-check (24 Sec.8.12, C-2.21), which E29-T05's wiring slice calls on
    the binding as bound, before any wrapper (a wrapped stand-in would pass it):
    `ReconciliationUnavailable` when a live process would run with `NoReconciliation`, as the
    exchange is truth after a reconnect (C-2.5). The environment compares by value, so a plain
    `"live"` refuses too. Demo and testnet run with its page; E29-T06 removes the stand-in and
    this refusal together."""
    if environment == ProcessEnvironment.LIVE and isinstance(port, NoReconciliation):
        raise ReconciliationUnavailable("a live process needs E29-T06's reconciliation pass")


class AccountNotices(Protocol):
    """Publishes one `account_notice` about one account (23-ws-protocol.md Sec.15.9, SR-E29-10).
    The composition root binds it to the gateway's `system` topic, so `oms` imports no `ws`
    (C-3.4), and gives each `reason` its fixed severity and message, which name no account.
    Synchronous and non-blocking, as the gateway's own offer is: it queues and never awaits."""

    def publish(self, account_id: AccountId, *, reason: AccountNoticeReason) -> None: ...


class ExecutionHandovers(Protocol):
    """Where the private-stream consumer keeps a trade execution that no row takes for the next
    reconciliation pass (24 Sec.8.3 rule 7, Sec.8.5 step 3d): `oms_handovers`, idempotent on the
    account and the execution's `exec_id`; a sibling of `OrderHandovers`, never a widening of it.
    `empty_read`, which the entry counts, is true only when a completed read of the fill's order
    found none. E29-T06 lands the table and its writer; until then `NoHandoverStore` is the one
    production binding. The caller bounds the call (C-2.18)."""

    async def hand_over_execution(
        self, account_id: AccountId, execution: Execution, *, empty_read: bool = False
    ) -> None:
        """Append `execution` for the next pass, or raise `HandoverUnavailable`."""
        ...


@dataclass(frozen=True, slots=True)
class ProtectionReading:
    """A position row's protection reading (24 Sec.8.12), B1's `SL_OBSERVED` or `SL_LOST`: the
    row's exchange time in ms, its stop (None when it has none) and its size, B1's `_READING`
    keys. `SL_LOST` is an open position (size above zero) with no stop; any other row, a flat one
    included, is `SL_OBSERVED`, so a close never pages."""

    event: Literal["SL_OBSERVED", "SL_LOST"]
    updated_time: int
    stop_loss: Px | None
    size: Qty


class ProtectionReadings(Protocol):
    """Where the consumer sends the protection reading of a position no live order protects (24
    Sec.8.12): a live order protects it while its B1 `protection` region holds it, in any leaf
    but `not_required`, and takes the reading through `OrderMachines.push`. A reading no such
    order took, as each closed before its push, comes here too. E32-T02 binds it to B8
    (`position_protection`) in its own contract change; until then `NoPositionProtection` is the
    one binding. `key` names the position's account too."""

    async def take_reading(self, key: PositionKey, reading: ProtectionReading) -> None: ...


class NoPositionProtection:
    """`ProtectionReadings` until E32-T02: no machine holds the position, so an `SL_LOST` is
    `ProtectionReadingsUnavailable`, which the consumer logs, counts and pages P1 on once per
    episode (C-2.6); an `SL_OBSERVED`, a flat position's included, asks for nothing."""

    async def take_reading(self, key: PositionKey, reading: ProtectionReading) -> None:
        if reading.event == "SL_LOST":
            raise ProtectionReadingsUnavailable("no position-protection machine until E32-T02")


class Interim:
    """An interim port (R4): `port` is the slot it fills, `replaced_by` the ticket whose port
    replaces it, and `serves` what it serves and refuses, for the startup log."""

    port: ClassVar[PortName | RuntimePortName]
    replaced_by: ClassVar[str]
    serves: ClassVar[str]


class FixedQtySizer(Interim):
    port: ClassVar[PortName] = "sizer"
    replaced_by: ClassVar[str] = "E28-T03 (#907)"
    serves: ClassVar[str] = "fixed_qty sizing only; every other mode is sizing_mode_unsupported"

    def size(self, sizing: SizingRequest, instrument: Instrument) -> Qty:
        if sizing.mode != "fixed_qty":
            unsupported = FieldError("sizing.mode", RULE_SIZING_MODE_UNSUPPORTED, _ONLY_FIXED_QTY)
            raise OrderInvalid(_ONLY_FIXED_QTY, errors=(unsupported,))
        if sizing.qty is None:
            needed = FieldError("sizing.qty", "required", "fixed_qty sizing needs a qty.")
            raise OrderInvalid(errors=(needed,))
        if not sizing.qty.is_finite():
            raise OrderInvalid("The quantity must be a finite number.")
        if not sizing.round_to_lot:
            return sizing.qty
        return InstrumentPolicy(instrument).round_qty(sizing.qty)


class InterimStopResolver(Interim):
    port: ClassVar[PortName] = "stop_resolver"
    replaced_by: ClassVar[str] = "E28-T03 (#907)"
    serves: ClassVar[str] = (
        "price, ticks and percent stops and the profile's offset; atr and r_multiple are "
        "stop_unit_unsupported"
    )

    def resolve(
        self,
        stop: StopOffset | None,
        *,
        side: Side,
        reference_price: Px,
        effect: OrderEffect,
        instrument: Instrument,
        profile: AccountProfile | None,
    ) -> Px | None:
        tick = instrument.tick_size
        if stop is not None:
            level = _requested_level(stop, side, reference_price, tick)
        elif effect is not OrderEffect.REDUCE and profile is not None:  # an entry: fail closed
            level = _profile_level(profile, side, reference_price, tick)
        else:
            return None
        return _on_tick(level, side, tick)  # away from the entry (24 Sec.9.3.1)

    def resolve_take_profit(
        self,
        take_profit: StopOffset | None,
        *,
        side: Side,
        reference_price: Px,
        instrument: Instrument,
        profile: AccountProfile | None,
    ) -> Px | None:
        """S2-Q6: the request's take-profit in `price`, `ticks` or `percent`, on the profit side,
        on a tick rounded toward the entry (Q-L); None when it names none, as the profile's
        offset is not applied to an order unasked. `atr` and `r_multiple` are refused."""
        if take_profit is None:
            return None
        tick = instrument.tick_size
        level = _take_profit_level(take_profit, side, reference_price, tick)
        return _on_tick(level, side, tick)  # toward the entry (Q-L)


def _requested_level(stop: StopOffset, side: Side, reference: Px, tick: Px) -> Px:
    if not stop.value.is_finite():  # unresolved: the guard refuses it (#2877 ruling 2)
        return stop.value
    if stop.unit == "price":
        return stop.value
    if stop.unit == "ticks":
        return _protective(reference, stop.value * tick, side)
    if stop.unit == "percent":
        return _protective(reference, reference * stop.value / 100, side)
    raise StopUnitUnsupported  # atr, r_multiple (R4)


def _profile_level(profile: AccountProfile, side: Side, reference: Px, tick: Px) -> Px:
    value = profile.sl_offset_value
    if profile.sl_offset_unit == "ticks":
        return _protective(reference, value * tick, side)
    if profile.sl_offset_unit == "percent":  # a fraction in the model (24 Sec.9.2)
        return _protective(reference, reference * value, side)
    raise StopUnitUnsupported  # atr (R4)


def _take_profit_level(take_profit: StopOffset, side: Side, reference: Px, tick: Px) -> Px:
    if not take_profit.value.is_finite():  # unresolved: the guard refuses it (#2877 ruling 2)
        return take_profit.value
    if take_profit.unit == "price":
        return take_profit.value
    if take_profit.unit == "ticks":
        return _profitable(reference, take_profit.value * tick, side)
    if take_profit.unit == "percent":
        return _profitable(reference, reference * take_profit.value / 100, side)
    raise StopUnitUnsupported(field="take_profit")  # atr, r_multiple (S2-Q6)


def _protective(reference: Px, distance: Decimal, side: Side) -> Px:
    """`distance` from `reference` on the protective side: below a buy, above a sell."""
    return reference - distance if side == "buy" else reference + distance


def _profitable(reference: Px, distance: Decimal, side: Side) -> Px:
    """`distance` from `reference` on the profit side: above a buy, below a sell."""
    return reference + distance if side == "buy" else reference - distance


def _on_tick(level: Px, side: Side, tick: Px) -> Px:
    """`level` on a tick, down for a buy and up for a sell. A stop sits on the far side of the
    entry from its take-profit, so this rounds a stop away from the entry, never closer (24
    Sec.9.3.1), and a take-profit toward it (Q-L). A figure that is not finite is left for the
    guard to refuse."""
    if not level.is_finite():
        return level
    rounding = ROUND_FLOOR if side == "buy" else ROUND_CEILING
    return (level / tick).to_integral_value(rounding=rounding) * tick


class InterimRiskGate(Interim):
    port: ClassVar[PortName] = "risk_gate"
    replaced_by: ClassVar[str] = "E39-S01 (#954)"
    serves: ClassVar[str] = (
        "admits demo orders without a risk evaluation; refuses every other environment's"
    )

    def __init__(self, *, now: Callable[[], datetime]) -> None:
        self._now = now

    def check(self, order: SizedOrder, *, profile: AccountProfile | None) -> RiskDecision:
        evaluated_at = self._now()
        if order.environment in _UNEVALUATED:
            return RiskDecision(allowed=True, evaluated_at=evaluated_at)
        return RiskDecision(
            allowed=False,
            code=RiskRefusal.RISK_STATE_UNAVAILABLE,
            message="No risk evaluation is available for this environment yet.",
            evaluated_at=evaluated_at,
        )


class NoArmRecords(Interim):
    port: ClassVar[PortName] = "arm_records"
    replaced_by: ClassVar[str] = "E30-S04 (#1088)"
    serves: ClassVar[str] = "no arm record exists: every live order is session_not_armed"

    def check(
        self, *, session_id: UUID, environment: Environment, token: ArmToken | None
    ) -> Verdict:
        return FAILED if environment in _ARMED else PASSED


@dataclass(frozen=True, slots=True)
class SubmissionPorts:
    """The ports the composition root wires into the pipeline, one per `PORT_NAMES` slot."""

    sizer: Sizer
    stop_resolver: StopResolver
    risk_gate: RiskGate
    arm_records: ArmRecords

    @classmethod
    def interim(cls, *, now: Callable[[], datetime]) -> SubmissionPorts:
        """Every slot filled with its R4 interim port."""
        return cls(FixedQtySizer(), InterimStopResolver(), InterimRiskGate(now=now), NoArmRecords())


def announce_interim_ports(ports: SubmissionPorts, *, metrics: Metrics) -> tuple[PortName, ...]:
    """At startup: `announce_interim_port` for each slot (R4); returns the slots interims fill."""
    return tuple(
        name
        for name in PORT_NAMES
        if announce_interim_port(name, getattr(ports, name), metrics=metrics)
    )


def announce_interim_port(
    name: PortName | RuntimePortName, port: object, *, metrics: Metrics
) -> bool:
    """At startup, for one port: `oms_interim_ports{port}` at 1 with one WARNING while an interim
    serves it, else 0; returns whether one does. A `name` outside `INTERIM_PORT_LABELS`, the
    gauge's closed set, is a `ValueError` before any series (the cap would drop it silently)."""
    if name not in INTERIM_PORT_LABELS:
        raise ValueError(f"{name!r} is not a label of {INTERIM_PORTS_METRIC}")
    spec = next(spec for spec in CATALOGUE if spec.name == INTERIM_PORTS_METRIC)
    gauge = metrics.gauge(spec.name, spec.help, spec.labels, max_series=spec.max_series)
    gauge.labels(name).set(1 if isinstance(port, Interim) else 0)
    if isinstance(port, Interim):
        _log().warning(
            "oms_interim_port", port=name, replaced_by=port.replaced_by, serves=port.serves
        )
    return isinstance(port, Interim)
