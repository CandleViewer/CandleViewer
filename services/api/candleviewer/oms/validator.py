"""The OMS validator: the read-only gate (E09-T04 AC3) and the order checks of the submission
pipeline (E29-T04, #913).

"Read-only mode is a single process-wide flag consulted by the OMS
validator (`20-architecture.md` §3.x `Validator`) so it cannot be bypassed by
any route" (ticket Technical notes). This module never imports
`candleviewer.net` (M14's §3 allow-list does not include it): the read-only
flag is injected as a structurally-typed `ReadOnlyCheck` at construction time
by the composition root (`candleviewer.app`), which *is* allowed to import
both M14 and the `net` package. Mirrors the `SecretsHandle`/`AuditHandle`
type-alias pattern `admin.wiring` already uses to avoid a direct import edge.

`Validator.check_order` judges the SIZED and ROUNDED order (SR-E29-04), after
`classify.NativeStopGuard` and before the risk gate; the first step that fails refuses:

1. the read-only gate (`OrderPlacementRefused`, `403 trading_disabled`);
2. a price, trigger price, reference price or quantity that is not finite, each listed, before
   any figure is compared (`validation_failed`); then each figure outside the instrument's
   bounds, listed before any figure meets a step, which cannot judge one of 10**28 steps or more,
   so a figure however large or negative is named: a price, trigger price, stop or take-profit
   above `max_price` or below `min_price`, a quantity not above zero, named by
   `min_order_qty`, and a quantity above both quantity ceilings, named by the order's own
   (`lot_size_violation` if a quantity is listed, else `validation_failed`); then the
   instrument's trading status and a limit order without its price (`validation_failed`). Every
   step on a figure runs under one handler, so a figure no step can judge all the same, such as a
   market order's reference price or a trigger price of 10**28 ticks within `max_price`, is
   `validation_failed` too, never an unhandled error;
3. for an entry, any order whose effect is not `REDUCE` (fail closed), the effective profile
   (`403 risk_limit_breached`), as 24-internal-schemas.md Sec.9.3 step 1 reads it: no profile
   allows nothing (D11); a profile not `enabled` or not `trading_enabled` allows nothing
   (SR-E28-27); then the symbol allow-list, `all_symbols`, else a listed symbol or an anchored
   suffix pattern (`*USDT`) that matches only a trading USDT perpetual (SR-E28-06), then the deny
   list, whose patterns match any symbol. An order that only reduces is never refused by them
   (SR-E28-24, SR-E28-27);
4. the instrument filters of `exchange.policy.InstrumentPolicy`, the one rule source, with the
   order path's own: a trigger price on its tick, a market order's ceiling, and an entry's
   leverage within the instrument's maximum. Every violation is listed in `errors[]`, a quantity
   above zero but below `min_order_qty` among them, named by the instrument field it breaks
   (24-internal-schemas.md Sec.1.3 rule 3); the answer is `tick_size_violation` if a price is off
   its tick, else `lot_size_violation` if the quantity or the notional is, else
   `validation_failed`. A market order has no price of its own: its reference price measures its
   notional only.

`Validator.check_route` refuses an order whose environment is not its route's (C-2.11): a demo
account's order never reaches a live client, nor the reverse. Decimal throughout.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import InvalidOperation
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

from candleviewer.accounts.profiles import SymbolScope
from candleviewer.exchange.policy import FilterViolation, FilterViolationCode, InstrumentPolicy

from .errors import (
    EnvironmentMismatch,
    FieldError,
    LotSizeViolation,
    OrderInvalid,
    RiskRefused,
    TickSizeViolation,
    TradingDisabled,
)
from .ports import OrderEffect, SizedOrder

if TYPE_CHECKING:
    from candleviewer.accounts.profiles import AccountProfile
    from candleviewer.domain.events import Instrument
    from candleviewer.domain.primitives import Environment

#: `InstrumentPolicy`'s violations as `errors[]` items: the field, and the instrument limit broken.
_POLICY_RULES: Final[Mapping[FilterViolationCode, tuple[str, str]]] = MappingProxyType(
    {
        FilterViolationCode.SYMBOL_NOT_TRADING: ("symbol", "status"),
        FilterViolationCode.PRICE_NOT_TICK_MULTIPLE: ("price", "tick_size"),
        FilterViolationCode.QTY_NOT_LOT_MULTIPLE: ("qty", "qty_step"),
        FilterViolationCode.QTY_BELOW_MIN: ("qty", "min_order_qty"),
        FilterViolationCode.QTY_ABOVE_MAX: ("qty", "max_order_qty"),
        FilterViolationCode.NOTIONAL_BELOW_MIN: ("qty", "min_notional"),
    }
)
#: A market order has no price of its own, and a ceiling of its own.
_NOT_FOR_MARKET: Final = frozenset(
    {FilterViolationCode.PRICE_NOT_TICK_MULTIPLE, FilterViolationCode.QTY_ABOVE_MAX}
)
_TICK_RULES: Final = frozenset({"tick_size"})
_LOT_RULES: Final = frozenset(
    {"qty_step", "min_order_qty", "max_order_qty", "max_mkt_order_qty", "min_notional"}
)


class ReadOnlyCheck(Protocol):
    """Structural type for `candleviewer.net.ReadOnlyGate` — no import edge.

    Any object exposing `is_read_only`/`reason_code`/`reason_text` satisfies
    this (the real `ReadOnlyGate`, or a test fake), so `oms` never has a
    static or runtime import of the `net` package.
    """

    @property
    def is_read_only(self) -> bool: ...

    @property
    def reason_code(self) -> str | None: ...

    @property
    def reason_text(self) -> str | None: ...


class OrderPlacementRefused(TradingDisabled):
    """Raised when an order-opening command is rejected because the process
    is in read-only degraded mode (a public/off-mesh binding was detected):
    `403 trading_disabled` with no reason (`errors.PROBLEMS`). `reason_code` and
    `reason_text` are the gate's own, for the log; the answer's detail is fixed.
    """

    default_detail = "Order entry is paused: the terminal is read-only."

    def __init__(self, *, reason_code: str | None, reason_text: str | None) -> None:
        self.reason_code = reason_code or "net.read_only"
        self.reason_text = reason_text or "The trading terminal is in read-only mode."
        super().__init__()


class Validator:
    """OMS command validator boundary (`20-architecture.md` §3 `Validator`).

    The read-only gate (E09-T04) and, on the same boundary, the order checks
    of the submission pipeline (E29-T04): every order path calls `check_order`,
    which runs the gate first, so none can route around it. RBAC scope, the
    kill switch and risk caps stay with their own checks (the route, B18, the
    risk gate port).
    """

    def __init__(self, *, read_only_gate: ReadOnlyCheck) -> None:
        self._read_only_gate = read_only_gate

    def assert_order_placement_allowed(self) -> None:
        """Raise `OrderPlacementRefused` if the process is read-only.

        Called before any position-opening order is accepted, per the
        ticket's "Read-only degradation" scope: order placement is disabled
        at the OMS boundary while the gate is tripped, and this check cannot
        be routed around by any other entry point because every order path
        must call it (no flag, config, or role may re-enable placement).
        """
        if self._read_only_gate.is_read_only:
            raise OrderPlacementRefused(
                reason_code=self._read_only_gate.reason_code,
                reason_text=self._read_only_gate.reason_text,
            )

    def check_order(
        self, order: SizedOrder, *, instrument: Instrument, profile: AccountProfile | None
    ) -> None:
        """Refuse the sized, rounded `order` (see the module docstring for the steps); return
        when it may go on to the risk gate."""
        if instrument.symbol != order.symbol:
            raise ValueError("the instrument is not the order's symbol")
        self.assert_order_placement_allowed()
        errors = _terms_errors(order, instrument)
        if order.effect is not OrderEffect.REDUCE:
            if profile is None:
                raise RiskRefused("No profile allows this order.")
            if not (profile.enabled and profile.trading_enabled):
                raise RiskRefused("The account's profile is not enabled for trading.")
            if not symbol_allowed(profile, instrument):
                raise RiskRefused("The account's profile does not allow this symbol.")
            errors += _leverage_errors(profile, instrument)
        _refuse(errors)

    def check_terms(self, order: SizedOrder, *, instrument: Instrument) -> None:
        """An amend's terms (E29-T04 slice 4, 22 `amendOrder`): steps 2 and 4 alone, as
        `check_order` refuses them. The read-only gate and the profile are a risk-increasing
        amend's, which `check_order` takes too: an exit is never gated (C-2.6)."""
        if instrument.symbol != order.symbol:
            raise ValueError("the instrument is not the order's symbol")
        _refuse(_terms_errors(order, instrument))

    @staticmethod
    def check_route(order_environment: Environment, route_environment: Environment) -> None:
        """C-2.11: refuse an order whose route is another environment's."""
        if order_environment != route_environment:
            raise EnvironmentMismatch(
                order_environment=order_environment, route_environment=route_environment
            )


def _terms_errors(order: SizedOrder, instrument: Instrument) -> list[FieldError]:
    """Steps 2 and 4 of the module docstring: a figure step 2 refuses raises; step 4's
    violations are listed for the caller, which may add the leverage's."""
    non_finite = _non_finite_errors(order)
    if non_finite:
        raise OrderInvalid(errors=non_finite)
    out_of_bounds = _bound_errors(order, instrument)
    if out_of_bounds:
        _refuse(out_of_bounds)
    priced = order.price if order.price is not None else order.reference_price
    try:  # every step on a figure, under one handler (the module docstring's step 2)
        violations = InstrumentPolicy(instrument).validate(priced, order.qty)
        status = [v for v in violations if v.code is FilterViolationCode.SYMBOL_NOT_TRADING]
        if status:
            raise OrderInvalid(errors=map(_policy_error, status))
        malformed = _price_errors(order)
        if malformed:
            raise OrderInvalid(errors=malformed)
        if order.order_type == "market":
            violations = [v for v in violations if v.code not in _NOT_FOR_MARKET]
        return [*map(_policy_error, violations), *_order_path_errors(order, instrument)]
    except InvalidOperation as error:  # a figure no step can judge: DivisionImpossible
        raise OrderInvalid() from error


def symbol_allowed(profile: AccountProfile, instrument: Instrument) -> bool:
    """D11 and SR-E28-06: `all_symbols`, or a listed symbol, or an anchored suffix pattern that
    matches only a trading USDT perpetual; then no entry of the deny list, whose patterns match
    any symbol (the deny side fails closed). An empty allow-list allows nothing. `SymbolScope`
    judges it, as it judges a profile save, so the two never disagree (PF-T07)."""
    return SymbolScope.of(profile).allows(instrument)


def _policy_error(violation: FilterViolation) -> FieldError:
    field, rule = _POLICY_RULES[violation.code]
    return FieldError(field, rule, violation.user_message)


def _non_finite_errors(order: SizedOrder) -> list[FieldError]:
    """Each figure `InstrumentPolicy` compares that is not finite: compared, it would raise."""
    figures = (
        ("price", order.price, "The price must be a finite number."),
        ("trigger.price", order.trigger_price, "The trigger price must be a finite number."),
        ("reference_price", order.reference_price, "The reference price must be a finite number."),
        ("qty", order.qty, "The quantity must be a finite number."),
    )
    return [
        FieldError(field, "finite", message)
        for field, figure, message in figures
        if figure is not None and not figure.is_finite()
    ]


def _bound_errors(order: SizedOrder, instrument: Instrument) -> list[FieldError]:
    """Each figure outside the instrument's bounds, judged before any figure meets a step, which
    cannot judge one of 10**28 steps or more (`decimal.DivisionImpossible`), so a figure however
    large or negative is named: a price, trigger price, stop or take-profit above `max_price` or
    below `min_price`, a quantity not above zero, the only one below `min_order_qty` that can be
    that far from its step, and a quantity above both quantity ceilings, named by the order's own. A
    quantity above zero and within either ceiling goes on to the filters, which judge it against
    its own and list it with every other violation (24-internal-schemas.md Sec.1.3)."""
    above = f"Price must not exceed {instrument.max_price}."
    below = f"Price must be at least {instrument.min_price}."
    errors: list[FieldError] = []
    for field, price in (
        ("price", order.price),
        ("trigger.price", order.trigger_price),
        ("stop_loss", order.stop_loss),
        ("take_profit", order.take_profit),
    ):
        if price is None:
            continue
        if price > instrument.max_price:
            errors.append(FieldError(field, "max_price", above))
        elif price < instrument.min_price:
            errors.append(FieldError(field, "min_price", below))
    if order.qty <= 0:
        message = f"Quantity must be at least {instrument.min_order_qty}."
        errors.append(FieldError("qty", "min_order_qty", message))
    elif order.qty > max(instrument.max_order_qty, instrument.max_mkt_order_qty):
        errors.append(_ceiling_error(order, instrument))
    return errors


def _ceiling_error(order: SizedOrder, instrument: Instrument) -> FieldError:
    """The order's own quantity ceiling, broken: a market order's `max_mkt_order_qty`, else
    `max_order_qty`, whose sentence is `InstrumentPolicy`'s."""
    if order.order_type == "market":
        message = f"A market order's quantity must not exceed {instrument.max_mkt_order_qty}."
        return FieldError("qty", "max_mkt_order_qty", message)
    message = f"Quantity must not exceed {instrument.max_order_qty}."
    return FieldError("qty", "max_order_qty", message)


def _price_errors(order: SizedOrder) -> list[FieldError]:
    if order.order_type == "limit" and order.price is None:
        return [FieldError("price", "required", "A limit order needs a price.")]
    return []


def _order_path_errors(order: SizedOrder, instrument: Instrument) -> list[FieldError]:
    errors: list[FieldError] = []
    tick = instrument.tick_size
    if order.trigger_price is not None and order.trigger_price % tick != 0:
        message = f"Price must be a multiple of {tick}."
        errors.append(FieldError("trigger.price", "tick_size", message))
    if order.order_type == "market" and order.qty > instrument.max_mkt_order_qty:
        errors.append(_ceiling_error(order, instrument))
    return errors


def _leverage_errors(profile: AccountProfile, instrument: Instrument) -> list[FieldError]:
    if profile.leverage <= instrument.max_leverage:
        return []
    message = f"The profile's leverage must not exceed {instrument.max_leverage} on this symbol."
    return [FieldError("leverage", "max_leverage", message)]


def _refuse(errors: list[FieldError]) -> None:
    rules = {error.rule for error in errors}
    if rules & _TICK_RULES:
        raise TickSizeViolation(errors=errors)
    if rules & _LOT_RULES:
        raise LotSizeViolation(errors=errors)
    if errors:
        raise OrderInvalid(errors=errors)
