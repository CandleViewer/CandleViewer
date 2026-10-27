"""The trade-group planner (E28-T05 S3a, #909): what a group would send, leg by leg, from one
snapshot. The preview and E34's submit both run it, so what is previewed is sent (24 Sec.9.4).

`take_snapshot` reads once per group (#907's G-row) the market, with no ATR (an `atr` stop falls
back, #913 S4-S ruling Q6), and per account its cached figures (SR-E28-22) and its readiness through
`member_reason`, which fails closed. `plan_group` is plain code over it (C-2.20, C-2.21) whose ports
are reads: no trading port, OMS command or group store. Per leg, in request order: a `skip` leaves
it out; else it is sized by its bound profile _B_ (the account's default) or the alternate _A_ it
names (_A_'s `never` fields held at _B_'s), `defaults` then `overrides` laid over through
`oms.sizing`'s overlay (ADR-0040), and judged beside _B_'s own leg (#2635) as `EntrySizer.judge`
judges, but with `is_default` judged and unknown `*_after` counts left to the guard. A leg whose
request values or alternate the comparator refuses, or whose overlay a cap clamped (sized, or
failed `cap_breached`), is refused, never clamped; every leg is planned before `GroupRefused` names
each offending one (D6). Otherwise a leg is `blocked` by the first of its sizer's failure, a
missing native stop (C-2.6), the comparator, its readiness and the guard (`guard.LegGuard`, handed
the leg's profile with ADR-0040's cap rows 29 to 36 at `min(B, A)`; one that raises fails closed);
else `ready`, or `warn` when its stop fell back. Logs carry ids and codes only (C-12.6).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields, replace
from decimal import Context, Decimal, localcontext
from types import MappingProxyType
from typing import Any, Final, Literal
from uuid import UUID

import structlog
from pydantic import ValidationError

from candleviewer.accounts import override_comparator as comparator
from candleviewer.accounts.profiles import AccountProfile, TimeInForce
from candleviewer.accounts.sizer import FailReason, LegSizing, SizingIntent, SizingMarket, size_leg
from candleviewer.accounts.sizer_metrics import SizerMetrics, size_leg_observed
from candleviewer.accounts.trade_group_readiness import (
    ReadinessMember,
    ReadinessReason,
    ReadinessSource,
    member_reason,
)
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Px, Side, Symbol
from candleviewer.oms import ports
from candleviewer.oms import sizing as size_step
from candleviewer.oms.errors import FieldError, OrderInvalid
from candleviewer.oms.fanout.guard import LegGuard, RejectionCode, rejection_code

LegStatus = Literal["ready", "warn", "skipped", "blocked"]
_PROFILE: Final = ports.SizingRequest(mode="profile")
_EXACT: Final = Context(prec=100)
#: An alternate's `never` fields but its identity, held at _B_'s (ADR-0040 "alternates").
_HELD: Final = frozenset({"enabled", "trading_enabled", "min_leg_notional", "qty_rounding",
                          "margin_mode", "position_mode", "require_native_sl",
                          "fallback_sl_offset_pct", "tp_ladder"})  # fmt: skip
#: ADR-0040 rows 29 to 36, each `min(B, A)` for the guard: _A_ only ever tightens _B_'s cap.
_CAPS: Final = ("max_position_notional", "max_position_pct_equity", "max_daily_loss",
                "max_daily_loss_pct", "max_open_positions", "max_concurrent_orders",
                "max_leverage_cap", "max_orders_per_minute")  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LegTerms:
    """One layer of 22 `CreateTradeGroupRequest` (its `defaults` or a leg's `overrides`) in the
    order path's shapes; `None` is absent, so the layer under it holds (ADR-0040)."""

    sizing: ports.SizingRequest | None = None
    price: Px | None = None
    leverage: Decimal | None = None
    stop_loss: ports.StopOffset | None = None
    take_profit: ports.StopOffset | None = None
    time_in_force: TimeInForce | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    position_idx: Literal[0, 1, 2] | None = None


@dataclass(frozen=True, slots=True)
class LegRequest:
    account_id: AccountId
    overrides: LegTerms = LegTerms()
    skip: bool = False


@dataclass(frozen=True, slots=True)
class GroupRequest:
    """An entry on one symbol, one leg per account (a repeated account is `OrderInvalid`)."""

    symbol: Symbol
    side: Side
    order_type: Literal["market", "limit"]
    legs: tuple[LegRequest, ...]
    defaults: LegTerms = LegTerms()


@dataclass(frozen=True, slots=True)
class LegProfiles:
    """A leg's bound profile _B_ and alternate _A_, resolved after the scope check (else 404)."""

    bound: AccountProfile
    alternate: AccountProfile | None = None


@dataclass(frozen=True, slots=True)
class GroupSnapshot:
    """What every leg is sized against: an account's figures (each `None` when not cached) and
    its readiness reason (`None`: ready); an account it did not read is neither (fail closed)."""

    environment: Environment
    instrument: Instrument
    market: SizingMarket
    figures: Mapping[UUID, comparator.AccountFigures]
    readiness: Mapping[UUID, ReadinessReason | None]


@dataclass(frozen=True, slots=True)
class LegPlan:
    """One leg of 22's `TradeGroupPreview`: what the sizer computed, the leg admitted (its native
    stop sized to its whole quantity, rule 8) and the profile that sized it. Only a `ready` or
    `warn` leg's `admitted` may be sent; a blocked leg keeps it for the preview alone."""

    account_id: AccountId
    status: LegStatus
    reason: RejectionCode | None = None
    warnings: tuple[Literal["stop_fallback"], ...] = ()
    sizing: LegSizing | None = None
    admitted: comparator.Admitted | None = None
    profile: AccountProfile | None = None


@dataclass(frozen=True, slots=True)
class GroupTotals:
    """22's `totals` at 100 digits; the fee is the risk's two taker fees (24 Sec.9.3 step 5)."""

    accounts_targeted: int
    accounts_submittable: int
    qty: Decimal
    notional_usd: Decimal
    risk_usd: Decimal
    fee_usd: Decimal


@dataclass(frozen=True, slots=True)
class GroupPlan:
    legs: tuple[LegPlan, ...]
    totals: GroupTotals


@dataclass(frozen=True, slots=True)
class RefusedLeg:
    """An offending leg, as `refusal_record` and its 22 `errors[]` entry take it."""

    index: int
    bound: AccountProfile
    alternate: AccountProfile | None
    violations: tuple[comparator.Violation, ...]


@dataclass(frozen=True, slots=True)
class GroupRefused:
    """The whole request refused before any leg is sent (`403 risk_limit_breached`)."""

    legs: tuple[RefusedLeg, ...]


def take_snapshot(
    accounts: Iterable[tuple[UUID, bool]],
    *,
    environment: Environment,
    instrument: Instrument,
    mid: Px | None,
    last: Px | None,
    figures: Callable[[UUID], comparator.AccountFigures | None],
    readiness: ReadinessSource,
) -> GroupSnapshot:
    """The market once and, per account and its row's switch, one cached read and one ask."""
    known: dict[UUID, comparator.AccountFigures] = {}
    ready: dict[UUID, ReadinessReason | None] = {}
    for account_id, enabled in dict(accounts).items():
        known[account_id] = figures(account_id) or ports.UNKNOWN_FIGURES
        member = ReadinessMember(account_id, True, enabled)
        ready[account_id] = member_reason(readiness, member, environment)
    market = size_step.sizing_market(mid, last)
    frozen = MappingProxyType(known), MappingProxyType(ready)
    return GroupSnapshot(environment, instrument, market, *frozen)


def plan_group(
    request: GroupRequest,
    *,
    profiles: Mapping[AccountId, LegProfiles],
    snapshot: GroupSnapshot,
    guard: LegGuard,
    stops: ports.StopResolver,
    observer: SizerMetrics,
) -> GroupPlan | GroupRefused:
    """Every leg in request order (module docstring); a refusal names every offending leg. A
    repeated account is 22's `duplicate_account`; a leg with no resolved profiles is a 404."""
    if len({leg.account_id for leg in request.legs}) < len(request.legs):
        message = "Each account takes one leg at most."
        raise OrderInvalid(message, errors=(FieldError("legs", "duplicate_account", message),))
    plans: list[LegPlan] = []
    refused: list[RefusedLeg] = []
    violations: tuple[comparator.Violation, ...]
    for index, leg in enumerate(request.legs):
        plan, violations = LegPlan(leg.account_id, "skipped", "skipped"), ()
        if not leg.skip:
            if (chosen := profiles.get(leg.account_id)) is None:
                raise comparator.ProfileNotFound
            plan, violations = _plan_leg(request, leg, chosen, snapshot, guard, stops, observer)
            if violations:
                refused.append(RefusedLeg(index, chosen.bound, chosen.alternate, violations))
        _log().debug(
            "trade_group_leg_planned", leg=index, account_id=str(leg.account_id),
            status=plan.status, reason=plan.reason,
        )  # fmt: skip
        plans.append(plan)
    if refused:
        return GroupRefused(tuple(refused))
    return GroupPlan(tuple(plans), _totals(plans))


def _plan_leg(
    request: GroupRequest,
    leg: LegRequest,
    chosen: LegProfiles,
    snapshot: GroupSnapshot,
    guard: LegGuard,
    stops: ports.StopResolver,
    observer: SizerMetrics,
) -> tuple[LegPlan, tuple[comparator.Violation, ...]]:
    """One leg's plan, and the violations that refuse the whole request (module docstring)."""
    bound, alternate, side, inst = chosen.bound, chosen.alternate, request.side, snapshot.instrument
    if any(p.account_id != leg.account_id for p in (bound, alternate) if p is not None):
        raise comparator.ProfileNotFound  # another account's profile: the caller's 404
    under = request.defaults  # `overrides` over `defaults`: an absent member takes the default
    over = {f.name: getattr(leg.overrides, f.name) for f in fields(LegTerms)}
    terms = LegTerms(**{k: getattr(under, k) if v is None else v for k, v in over.items()})
    known = snapshot.figures.get(leg.account_id, ports.UNKNOWN_FIGURES)
    try:
        asked = SizingIntent(symbol=request.symbol, side=side, order_type=request.order_type,
                             price=terms.price)  # fmt: skip
    except ValidationError:
        message = "The price cannot be sized."
        raise OrderInvalid(message, errors=(FieldError("price", "finite", message),)) from None
    overlay = size_step.sizing_overlay(terms.sizing or _PROFILE)
    named = (overlay, alternate, terms.stop_loss, terms.leverage)
    overlaid, layered, market = any(v is not None for v in named), bound, snapshot.market
    if not overlaid:
        baseline = sized = size_leg_observed(asked, bound, known, inst, market, observer=observer)
    else:
        started = time.perf_counter()
        baseline = sized = size_leg(asked, bound, known, inst, market)
        if baseline.ref_price is None or baseline.stop is None:  # _B_'s gate or no price
            observer.record(baseline, time.perf_counter() - started)
        else:
            layered = _profile(chosen, overlay, terms, side, baseline.ref_price, inst)
            sized = size_leg_observed(asked, layered, known, inst, market, observer=observer)
    if sized.stop_fallback:
        _log().warning("trade_group_leg_stop_fallback", account_id=str(leg.account_id))
    plan = LegPlan(leg.account_id, "blocked", sizing=sized, profile=layered)
    found: list[comparator.Violation] = []
    if overlaid and (cap := sized.binding) is not None:  # refused whole, never clamped
        field = cap.cap if cap.cap in comparator.OVERRIDE_CLASS else "fixed_qty"  # R7's name
        found.append(comparator.Violation(field=field, rule="narrow_only", reason="above_limit",
                                          limit=cap.limit, requested=sized.raw_qty))  # fmt: skip
    if sized.outcome != "ok":  # a clamp that failed the leg `cap_breached` refuses it too
        status: LegStatus = "skipped" if sized.outcome == "skip" else "blocked"
        clamped = tuple(found) if sized.reason is FailReason.CAP_BREACHED else ()
        code = rejection_code(sized.reason, "figure_unknown")
        return replace(plan, status=status, reason=code), clamped
    stop, qty, ref = sized.stop, sized.qty, sized.ref_price
    if stop is None or qty is None or ref is None or stop.price <= 0:  # C-2.6: no stop, no send
        return replace(plan, reason="invalid_stop_distance"), ()
    # A term the request leaves out is the profile's: its time-in-force, its mode's index.
    index: Literal[0, 1, 2] = 0 if layered.position_mode == "one_way" else 1 if side == "buy" else 2
    intent = size_step.EntryIntent(
        symbol=request.symbol, side=side, order_type=request.order_type, price=terms.price,
        sizing=terms.sizing or _PROFILE, stop_loss=terms.stop_loss, take_profit=terms.take_profit,
        time_in_force=terms.time_in_force or layered.time_in_force_default,
        tpsl_mode=terms.tpsl_mode or "Full",
        position_idx=index if terms.position_idx is None else terms.position_idx,
    )  # fmt: skip
    try:
        tp = None if terms.take_profit is None else stops.resolve_take_profit(
            terms.take_profit, side=side, reference_price=ref, instrument=inst, profile=layered
        )  # fmt: skip
        own = size_step.own_take_profit(side, layered, sized, sized, inst)
        judged = size_step.resolved_leg(intent, layered, sized, own if tp is None else tp)
        bound_tp = size_step.own_take_profit(side, bound, baseline, sized, inst)
        own_leg = size_step.resolved_leg(intent, bound, replace(baseline, qty=qty), bound_tp)
        layers = size_step.requested_layers(intent.sizing)
    except ValidationError:
        message = "The request cannot be judged."
        error = FieldError("sizing", "profile_overlay", message)
        raise OrderInvalid(message, errors=(error,)) from None
    verdict = comparator.judge_leg(bound, judged, baseline=own_leg, instrument=inst, figures=known,
                                   alternate=alternate, requested=layers)  # fmt: skip
    said = verdict.violations if isinstance(verdict, comparator.Refused) else ()
    found += (v for v in said if (v.rule, v.reason) != ("R7", "unknown_input"))  # the guard's
    wanted = (*named, intent.sizing.max_notional_usd, tp, terms.time_in_force, terms.position_idx)
    if found:  # what the request or _A_ asked refuses the request; _B_'s own leg is only blocked
        widened = any(value is not None for value in wanted)
        return replace(plan, reason="cap_breached"), tuple(found) if widened else ()
    differ = tuple(f for f in comparator.OVERRIDE_CLASS if f in _HELD and alternate is not None
                   and getattr(alternate, f) != getattr(bound, f))  # fmt: skip
    admitted = comparator.Admitted(judged.model_copy(update={"stop_qty": qty}), differ)
    plan = replace(plan, admitted=admitted)
    reason = snapshot.readiness.get(leg.account_id, "trading_disabled")
    if reason is not None:
        return replace(plan, reason=rejection_code(reason, "trading_disabled")), ()
    order = ports.SizedOrder(
        account_id=leg.account_id, environment=snapshot.environment, symbol=request.symbol,
        side=side, order_type=request.order_type, qty=qty, price=terms.price, trigger_price=None,
        reference_price=ref, reduce_only=False, intent="entry",
        effect=ports.OrderEffect.ENTRY, stop_loss=stop.price, take_profit=tp,
    )  # fmt: skip
    sides = [p for p in (bound, alternate) if p is not None]  # ADR-0040 rows 29 to 36
    caps = {f: min((v for p in sides if (v := getattr(p, f)) is not None), default=None)
            for f in _CAPS}  # fmt: skip
    try:  # a guard must not raise; one that does refuses the leg, as `S4SGuard` fails closed
        refusal = guard.refusal(order, profile=layered.model_copy(update=caps), instrument=inst)
    except Exception as exc:
        error_class = type(exc).__name__  # its class alone, never its text (C-12.6)
        _log().error("trade_group_guard_failed", account_id=str(leg.account_id), error=error_class)
        refusal = "risk_state_unavailable"
    if refusal is not None:
        return replace(plan, reason=rejection_code(refusal, "risk_state_unavailable")), ()
    warnings: tuple[Literal["stop_fallback"], ...] = ("stop_fallback",) if stop.fallback else ()
    return replace(plan, status="warn" if warnings else "ready", warnings=warnings), ()


def _profile(
    chosen: LegProfiles,
    overlay: tuple[dict[str, object], Decimal] | None,
    terms: LegTerms,
    side: Side,
    ref: Decimal,
    inst: Instrument,
) -> AccountProfile:
    """_A_ (its `never` fields _B_'s) or _B_, with the request's sizing, leverage and stop."""
    base, alternate = chosen.alternate or chosen.bound, chosen.alternate
    asked = {} if overlay is None else dict(overlay[0])
    if terms.leverage is not None:
        asked["leverage"] = terms.leverage
    stop = size_step.stop_overlay(terms.stop_loss, side, ref, inst)
    kept = {} if alternate is None else chosen.bound.model_dump(include=set(_HELD))
    try:
        return AccountProfile.model_validate(base.model_dump() | kept | asked | stop)
    except ValidationError:
        raise size_step.out_of_range(base, asked) from None


def _sum(values: Iterable[Decimal | None]) -> Decimal:
    with localcontext(_EXACT):
        return sum((value for value in values if value is not None), Decimal(0))


def _totals(plans: list[LegPlan]) -> GroupTotals:
    sent = [p.sizing for p in plans if p.status in ("ready", "warn") and p.sizing is not None]
    risk, gross = _sum(s.risk_usdt for s in sent), _sum(s.risk_with_fees_usdt for s in sent)
    qty, notional = _sum(s.qty for s in sent), _sum(s.notional for s in sent)
    return GroupTotals(len(plans), len(sent), qty, notional, gross, _EXACT.subtract(gross, risk))
