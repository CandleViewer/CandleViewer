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
  (24 Sec.9.3.1).
- `InterimRiskGate` admits a demo order without evaluating it and refuses every other one.
- `NoArmRecords`: no arm record exists yet, so every live order is refused; demo needs none
  (SR-043).

The native stop depends on none of them: `classify.NativeStopGuard` judges whatever the stop
resolver answers, so C-2.6 holds on every path whatever the port (C-4.14).
`announce_interim_ports` logs one WARNING per interim port at startup and sets
`oms_interim_ports{port}`, so nobody runs them on live unknowingly.

The rate step is not a port here. #2877's G-8 rulings (item 4) have the trading port take the rate
token once per call, and B1's `rate` verdict read a non-consuming headroom figure until E34-T02's
`reserve()`; the second slice of #913 declares that port with its first consumer. Nothing here
imports the exchange adapter (C-2.2).

The second slice adds two ports with no interim, both bound by slice 3's wiring. `ClockHealth` is
the exchange-clock verdict order entry halts on (24 Sec.8.6 `10002`, `clock_halt.ClockHalt`), in
the shape of `ingestion.clock.ClockGuard`, so the guard is wired as it stands while `oms` never
imports `ingestion` (C-3.4). `TradingAccounts` resolves the account the OMS has scope-checked to
the trading port's `AccountRef`, whose `key_ref` only that account's active key fills
(SR-E27-21).

The vocabulary the ports speak lives here too: `OrderEffect` (SR-E29-01), `StopOffset` (22
`Offset`), `SizingRequest` (22 `Sizing`), `ArmToken`, the session's arm token held masked (C-12.6)
and compared in constant time (SR-043), and `SizedOrder`, the order the validator, the risk gate
and B1 see once it is sized and rounded (SR-E29-04), which cannot be built as an entry without a
stop, nor with a stop off the protective side (C-2.6). Every decision by effect here and in
`classify` and `validator` fails closed: any effect but `OrderEffect.REDUCE` is an entry's.
Verdicts are B1's gate values (`statechart/bindings/b01_order.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import Any, ClassVar, Final, Literal, Protocol, get_args
from uuid import UUID

import structlog

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Px, Qty, Side, Symbol
from candleviewer.exchange.base.models import AccountRef
from candleviewer.exchange.policy import InstrumentPolicy
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.secret_type import ComparableSecret, Secret
from candleviewer.risk.models import RiskDecision, RiskRefusal

from .errors import RULE_SIZING_MODE_UNSUPPORTED, FieldError, OrderInvalid, StopUnitUnsupported
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

    def __post_init__(self) -> None:
        """The invariants every later check relies on, whatever the call order, as strict as
        `classify.stop_errors` (C-2.6, SR-E29-01): `effect` is an `OrderEffect`, a string that
        names none refused, and any effect but `REDUCE` is an entry's; an entry carries a stop;
        any stop is finite, above zero and on the protective side of a reference price above
        zero, below it for a buy and above it for a sell; and an order that only reduces is
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
    `classify.NativeStopGuard` judges its answer."""

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
        the hard threshold."""
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


class Interim:
    """An interim port (R4): `port` is the slot it fills, `replaced_by` the ticket whose port
    replaces it, and `serves` what it serves and refuses, for the startup log."""

    port: ClassVar[PortName]
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
        return _away_from_entry(level, side, tick)


def _requested_level(stop: StopOffset, side: Side, reference: Px, tick: Px) -> Px:
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


def _protective(reference: Px, distance: Decimal, side: Side) -> Px:
    """`distance` from `reference` on the protective side: below a buy, above a sell."""
    return reference - distance if side == "buy" else reference + distance


def _away_from_entry(level: Px, side: Side, tick: Px) -> Px:
    """`level` on a tick, rounded away from the entry, never closer (24 Sec.9.3.1)."""
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
    """At startup: one WARNING per slot an interim port fills, and `oms_interim_ports{port}` set
    to 1 for it and to 0 for a real port (R4). Returns the slots interim ports fill."""
    spec = next(spec for spec in CATALOGUE if spec.name == INTERIM_PORTS_METRIC)
    gauge = metrics.gauge(spec.name, spec.help, spec.labels, max_series=spec.max_series)
    interim: list[PortName] = []
    for name in PORT_NAMES:
        port = getattr(ports, name)
        gauge.labels(name).set(1 if isinstance(port, Interim) else 0)
        if isinstance(port, Interim):
            interim.append(name)
            _log().warning(
                "oms_interim_port", port=name, replaced_by=port.replaced_by, serves=port.serves
            )
    return tuple(interim)
