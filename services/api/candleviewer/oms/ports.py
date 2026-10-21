"""The ports the submission pipeline consumes, and their interim implementations (E29-T04, #913).

The pipeline (24-internal-schemas.md Sec.8.4) consumes interfaces whose owners have not landed:
the sizer and the stop resolver (E28-T03, #907), the risk gate (E39-S01, #954), the arm record
(E30-S04, #1088) and the rate verdict (E34-T02, #859). Ruling R4 on #913 approves an interim
implementation of the first four, failing closed on live:

- `FixedQtySizer` serves `fixed_qty` sizing only, floored to the lot step unless `round_to_lot` is
  false (the validator then judges the step); any other mode is `validation_failed`.
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

`RateVerdict` is the non-consuming headroom check whose answer B1 records as its `rate` verdict.
It is declared only: whether the trading port takes the rate token once per call is G-8's (#2877)
and not ruled yet, so the second slice of #913 wires it. Nothing here imports the exchange adapter
(C-2.2).

The vocabulary the ports speak lives here too: `OrderEffect` (SR-E29-01), `StopOffset` (22
`Offset`), `SizingRequest` (22 `Sizing`) and `SizedOrder`, the order the validator, the risk gate
and B1 see once it is sized and rounded (SR-E29-04). Verdicts are B1's gate values
(`statechart/bindings/b01_order.py`).
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
from candleviewer.exchange.policy import InstrumentPolicy
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.risk.models import RiskDecision, RiskRefusal

from .errors import FieldError, OrderInvalid, StopUnitUnsupported
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
    token is never logged (C-12.6)."""

    def check(
        self, *, session_id: UUID, environment: Environment, token: str | None
    ) -> Verdict: ...


class RateVerdict(Protocol):
    """E34-T02 (#859), G-8 (#2877): whether the account's rate budget has headroom for an order of
    this effect, read without taking a token; B1 records it as its `rate` verdict. Declared only:
    the second slice of #913 wires it once G-8's rulings land."""

    def headroom(self, account_id: AccountId, effect: OrderEffect) -> Verdict: ...


class Interim:
    """An interim port (R4): `port` is the slot it fills, `replaced_by` the ticket whose port
    replaces it, and `serves` what it serves and refuses, for the startup log."""

    port: ClassVar[PortName]
    replaced_by: ClassVar[str]
    serves: ClassVar[str]


class FixedQtySizer(Interim):
    port: ClassVar[PortName] = "sizer"
    replaced_by: ClassVar[str] = "E28-T03 (#907)"
    serves: ClassVar[str] = "fixed_qty sizing only; every other mode is validation_failed"

    def size(self, sizing: SizingRequest, instrument: Instrument) -> Qty:
        if sizing.mode != "fixed_qty":
            raise OrderInvalid("Only fixed_qty sizing is available yet.")
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
        elif effect is OrderEffect.ENTRY and profile is not None:
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

    def check(self, *, session_id: UUID, environment: Environment, token: str | None) -> Verdict:
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
