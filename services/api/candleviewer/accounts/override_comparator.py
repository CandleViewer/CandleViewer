"""The never-widen comparator: one trade-group leg judged against its bound profile (#2635, F-01).

ADR-0040 (proposed, #4461) Decision 1, the resulting-leg comparator R (SR-E28-03, SR-E28-04). The
ceiling is the bound profile _B_'s caps and risk budget, tightened by an alternate _A_ of the same
account; request values (`defaults`, then the leg's `overrides`) only narrow. `judge_leg` judges the
leg the sizer and its clamps produced (_L_) against _B_, beside _B_'s own leg (_L_B_), and either
admits it unchanged or refuses it whole, naming every violated field with its rule, limit and
requested value; it never clamps (C-12.5; E28 threat model D6). A refusal is `403
risk_limit_breached` with one `errors[]` entry per offending leg (22-api-openapi.yaml), written
ahead as `trade_group.override_refused` (`refusal_record`) and counted in
`cv_override_refused_total{field}` (`refused_fields`); the route (E28-T05 #909, E34-S01 #999) does
both, as it writes and counts nothing here.

Pure: no I/O, no clock, no logging. What it cannot know is an explicit input (`AccountFigures`,
the `Instrument`), and an unknown one refuses the leg with a named reason (fail closed): never zero
room, never no limit. Comparisons are `Decimal` at 100 digits; a division rounds towards the
stricter answer.

An alternate `overrides.profile_id` that is not one of the leg's account's live profiles is the
caller's `404 not_found`, decided before any leg is sized (ADR-0040, SR-E28-03); this module only
holds the typed contract: handed a profile or a leg of another account, it raises
`ProfileNotFound`, whose message never says which.

It judges position-opening legs (the trade group's entries). Only `Admitted.leg` may be sent: the
caller's own `leg` lacks rule 8's stop size.

Precondition for the route (E28-T05 #909): R7 bounds the quantity by the instrument's
`max_order_qty` (a limit order's); a market leg is also bounded by `max_mkt_order_qty`, which
needs the order type this module is not given, so #909 checks it before sending.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Final, Literal, TypedDict, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from candleviewer.accounts.profiles import (
    AccountProfile,
    Fraction,
    MarginMode,
    OffsetUnit,
    PositionMode,
    Positive,
    SymbolScope,
    TimeInForce,
)
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Side, Symbol

if TYPE_CHECKING:  # C-3.3: accounts may not import audit at run time, only name its types
    from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity

OverrideClass = Literal["never", "narrow_only"]
_N: Final[OverrideClass] = "never"
_W: Final[OverrideClass] = "narrow_only"

#: ADR-0040 Decision 1's table: every `AccountProfile` field, in the table's order (42 rows: 15
#: `never`, 27 `narrow_only`). A field it does not name is `never` (`override_class`).
OVERRIDE_CLASS: Final[Mapping[str, OverrideClass]] = MappingProxyType(
    {
        "profile_id": _N,  # 1
        "account_id": _N,  # 2
        "name": _N,  # 3
        "is_default": _N,  # 4
        "enabled": _N,  # 5
        "trading_enabled": _N,  # 6
        "version": _N,  # 7
        "updated_at": _N,  # 8
        "sizing_mode": _W,  # 9
        "fixed_qty": _W,  # 10
        "fixed_notional": _W,  # 11
        "pct_equity": _W,  # 12
        "risk_pct_equity": _W,  # 13
        "risk_fixed_amount": _W,  # 14
        "min_leg_notional": _N,  # 15
        "qty_rounding": _N,  # 16
        "leverage": _W,  # 17
        "margin_mode": _N,  # 18
        "position_mode": _N,  # 19
        "require_native_sl": _N,  # 20
        "sl_offset_value": _W,  # 21
        "sl_offset_unit": _W,  # 22
        "sl_atr_period": _W,  # 23
        "sl_atr_multiple": _W,  # 24
        "fallback_sl_offset_pct": _N,  # 25
        "tp_offset_value": _W,  # 26
        "tp_offset_unit": _W,  # 27
        "tp_ladder": _N,  # 28
        "max_position_notional": _W,  # 29
        "max_position_pct_equity": _W,  # 30
        "max_daily_loss": _W,  # 31
        "max_daily_loss_pct": _W,  # 32
        "max_open_positions": _W,  # 33
        "max_concurrent_orders": _W,  # 34
        "max_leverage_cap": _W,  # 35
        "max_orders_per_minute": _W,  # 36
        "all_symbols": _W,  # 37
        "allowed_symbols": _W,  # 38
        "denied_symbols": _W,  # 39
        "reduce_only_default": _W,  # 40
        "time_in_force_default": _W,  # 41
        "slippage_tolerance_bps": _W,  # 42
    }
)
#: The safety floor (the orchestrator's note 2 on #968): no request value reaches any of them.
FLOOR_FIELDS: Final = frozenset(
    {
        "max_position_notional",
        "max_daily_loss",
        "max_open_positions",
        "max_leverage_cap",
        "all_symbols",
        "allowed_symbols",
        "require_native_sl",
    }
)
#: The table's identity and display rows: an alternate's value is a selection, never "held".
_IDENTITY: Final = frozenset(
    {"profile_id", "account_id", "name", "is_default", "version", "updated_at"}
)
OVERRIDE_REFUSED_ACTION: Final = "trade_group.override_refused"
_PROBLEM: Final = "risk_limit_breached"
#: Margin may use at most this share of the available margin (24 Sec.9.3 step 8).
_MARGIN_SHARE: Final = Decimal("0.98")
_DIGITS: Final = 100
_CONTEXT: Final = Context(prec=_DIGITS)
_FLOOR: Final = Context(prec=_DIGITS, rounding=ROUND_FLOOR)
_CEILING: Final = Context(prec=_DIGITS, rounding=ROUND_CEILING)
#: Resting life: an immediate order rests no longer than a resting one (row 41).
_RESTS: Final[Mapping[str, int]] = MappingProxyType({"FOK": 0, "IOC": 0, "GTC": 1, "PostOnly": 1})

Rule = Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7", "never", "narrow_only"]
Reason = Literal[
    "above_limit",
    "unknown_input",
    "no_cap",
    "below_minimum",
    "rounded_up",
    "not_on_grid",
    "wrong_side",
    "further_than_bound",
    "outside_liquidation",
    "profile_disabled",
    "symbol_not_allowed",
    "symbol_denied",
    "changed",
    "removed",
    "inconsistent",
]
_FROZEN = ConfigDict(frozen=True, extra="forbid")


def override_class(field: str) -> OverrideClass:
    """The field's row, `never` when the table does not name it (deny by default, SR-E28-04)."""
    return OVERRIDE_CLASS.get(field, _N)


class ProfileNotFound(LookupError):
    """`404 not_found`: one answer for a missing, deleted or another account's profile."""

    def __init__(self) -> None:
        super().__init__("profile not found")


class _Request(BaseModel):
    """A request member: closed, and JSON `null` is refused, never read as absent (an override
    cannot unset a field; ADR-0040 "Absent, null and alternates")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_nulls(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            nulls = sorted(str(key) for key, value in data.items() if value is None)
            if nulls:
                raise ValueError(f"an override member cannot be null: {nulls}")
        return data


# --- the request's profile-field members, in domain units (fractions, not the REST percent) ------

RequestSizingMode = Literal[
    "fixed_qty", "fixed_notional", "pct_equity", "risk_based", "pct_position", "profile"
]
_SIZE_OF: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "fixed_qty": ("qty",),
        "fixed_notional": ("notional_usd",),
        "pct_equity": ("pct",),
        "pct_position": ("pct",),
        "risk_based": ("risk_per_trade_usd", "risk_per_trade_pct"),
        "profile": (),
    }
)


class SizingOverride(_Request):
    """`Sizing` (yaml `Sizing`): complete for its mode, never filled from a _B_ of another mode."""

    model_config = _FROZEN

    mode: RequestSizingMode
    qty: Positive | None = None
    notional_usd: Positive | None = None
    pct: Fraction | None = None
    risk_per_trade_usd: Positive | None = None
    risk_per_trade_pct: Fraction | None = None
    max_notional_usd: Positive | None = None
    round_to_lot: bool = True

    @model_validator(mode="after")
    def _shape(self) -> SizingOverride:
        if not self.round_to_lot:  # row 16: `qty_rounding` is `never`, always `floor`
            raise ValueError("round_to_lot false conflicts with qty_rounding floor")
        sizes = [name for name in _SIZE_OF[self.mode] if getattr(self, name) is not None]
        if len(sizes) != min(len(_SIZE_OF[self.mode]), 1):
            raise ValueError(f"sizing mode {self.mode} needs exactly one size of its own")
        return self


class OffsetOverride(_Request):
    """`Offset`: judged only through the price it resolves to (rows 21 to 24, 26, 27)."""

    model_config = _FROZEN

    unit: OffsetUnit
    value: Positive
    atr_period: Annotated[int, Field(ge=2, le=200)] | None = None


class LegOverrides(_Request):
    """One request layer, `defaults` or a leg's `overrides`, its profile-field members only. The
    floor and every other `never` field have no member (`extra="forbid"`: 422); `price`,
    `trailing_stop`, `tpsl_mode`, `position_idx` and `skip` stay ticket parameters, judged on the
    resulting leg."""

    model_config = _FROZEN

    sizing: SizingOverride | None = None
    leverage: Annotated[Decimal, Field(ge=1, le=100)] | None = None
    stop_loss: OffsetOverride | None = None
    take_profit: OffsetOverride | None = None
    time_in_force: TimeInForce | None = None
    reduce_only: bool | None = None

    @field_validator("stop_loss")
    @classmethod
    def _stop_defines_r(cls, stop: OffsetOverride | None) -> OffsetOverride | None:
        if stop is not None and stop.unit == "r_multiple":
            raise ValueError("stop_defines_r: the stop is never expressed in R")
        return stop


# --- what the comparator judges, and what it cannot know ------------------------------------------

NonNegative = Annotated[Decimal, Field(ge=0)]
Count = Annotated[int, Field(ge=0)]
Rate = Annotated[Decimal, Field(ge=0, lt=1)]


class AccountFigures(BaseModel):
    """The inputs the comparator cannot know, each explicit; `None` is unknown and fails closed.

    `committed_risk` is the account's live reservations, this request's other legs on the
    account included (ADR-0040 rule 2: one ledger, nothing counted twice). The netting is a
    money-semantics decision on the owner's sign-off list (#2701). `realised_loss_today` is the
    day's realised loss as a positive figure. The `*_after` counts include this leg, as the guard
    counts them.

    `available_margin` is net of the margin this request's other legs on the account take, on the
    same ledger as `committed_risk` (two legs each fundable alone may not be fundable together);
    a deficit is a negative figure, accepted and refused under R6 (fail closed), never a
    validation error. `maintenance_margin_rate` is the symbol's risk-limit tier rate for the
    position's notional after this leg is filled, not before (OPEN-3). `taker_fee_rate`
    is the account's real fee tier, which the route passes; `0` is a real zero-fee tier, never a
    placeholder for an unknown rate (that is `None`)."""

    model_config = _FROZEN

    equity: NonNegative | None
    available_margin: Decimal | None
    committed_risk: NonNegative | None
    realised_loss_today: NonNegative | None
    open_positions_after: Count | None
    open_orders_after: Count | None
    orders_in_minute_after: Count | None
    taker_fee_rate: Rate | None
    maintenance_margin_rate: Rate | None


class ResolvedLeg(BaseModel):
    """A position-opening leg as it would be sent: _L_ (from _B_ with _A_ and the request) or
    _L_B_ (_B_ alone), on the quantized values (quantity floored to the lot, the stop rounded away
    from entry). In hedge mode `position_idx` is keyed on `side` (1 buy, 2 sell), which holds for
    an opening leg only; a closing (`reduce_only`) leg of a hedge position is not judged here.
    `stop_qty` is `None` or the full `qty` (rule 8); any other size is refused, never rewritten."""

    model_config = _FROZEN

    account_id: AccountId
    profile_id: UUID  # the profile it was sized by: _B_ or _A_
    symbol: Symbol
    side: Side
    ref_price: Positive
    qty: Positive
    leverage: Annotated[Decimal, Field(ge=1)]
    stop_price: Positive
    stop_qty: Positive | None = None  # the server sets it (rule 8)
    tpsl_mode: Literal["Full", "Partial"]
    take_profit_price: Positive | None = None
    time_in_force: TimeInForce
    reduce_only: bool
    margin_mode: MarginMode
    position_mode: PositionMode
    position_idx: Literal[0, 1, 2]
    slippage_tolerance_bps: Annotated[int, Field(ge=0)]


class Violation(BaseModel):
    """One violated row: the table field, the rule, why, and the figures (an unknown input names
    the input and carries none). A rule-2 entry also carries the net headroom and the committed
    risk.

    Not the contract's `errors[]` item, whose members mean other things (22-api-openapi.yaml
    `Problem.errors`): there `field` names the request member, here `field` is the
    `AccountProfile` row whose cap or class the leg breaks (`max_leverage_cap` is a cap, not a
    member a client sends), and `rule` is ADR-0040's rule id. The route (E28-T05 #909, E34-S01
    #999) maps one entry per offending leg: `errors[].field` = that leg's request path
    (`legs[<i>]`), `errors[].rule` = this `field`, `errors[].limit` = this `limit`; `rule`,
    `reason` and `requested` stay in the audit row (`refusal_record`). The final shape is the
    contract's (C-6.1)."""

    model_config = _FROZEN

    field: str
    rule: Rule
    reason: Reason
    limit: Decimal | None = None
    requested: Decimal | None = None
    input: str | None = None
    net_headroom: Decimal | None = None
    committed_risk: Decimal | None = None

    @field_validator("field")
    @classmethod
    def _a_table_field(cls, field: str) -> str:
        if field not in OVERRIDE_CLASS:
            raise ValueError(f"{field} is not a field of the override table")
        return field


@dataclass(frozen=True, slots=True)
class Admitted:
    """The leg, unchanged but for its first native stop's size, set to the full quantity (rule 8;
    C-2.6), and the alternate's `never` fields held at _B_'s value (for `sizing_explanation`)."""

    leg: ResolvedLeg
    held: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Refused:
    """The whole request is refused, before any leg is sent: never a clamped leg."""

    violations: tuple[Violation, ...]
    problem: ClassVar[str] = _PROBLEM
    status: ClassVar[int] = 403


# --- the comparator R --------------------------------------------------------------------------


def _tighter[T: (Decimal, int)](values: Iterable[T | None]) -> T | None:
    """`min(B, A)`: a `None` is "no value from this side", never "no cap" when the other has one."""
    known = [value for value in values if value is not None]
    return min(known) if known else None


def _v(field: str, rule: Rule, reason: Reason, **figures: Any) -> Violation:
    return Violation(field=field, rule=rule, reason=reason, **figures)


def _unknown(field: str, rule: Rule, name: str) -> Violation:
    return _v(field, rule, "unknown_input", input=name)


def _on_grid(value: Decimal, step: Decimal) -> bool:
    return value % step == 0


@dataclass(frozen=True, slots=True)
class _Case:
    bound: AccountProfile
    alternate: AccountProfile | None
    leg: ResolvedLeg
    baseline: ResolvedLeg
    instrument: Instrument
    figures: AccountFigures
    sizing: SizingOverride | None  # the later layer's, if any sets it

    @property
    def profiles(self) -> tuple[AccountProfile, ...]:
        return (self.bound,) if self.alternate is None else (self.bound, self.alternate)

    def money_cap(self, field: str) -> Decimal | None:
        values: list[Decimal | None] = [getattr(p, field) for p in self.profiles]
        return _tighter(values)

    def count_cap(self, field: str) -> int | None:
        values: list[int | None] = [getattr(p, field) for p in self.profiles]
        return _tighter(values)

    @property
    def notional(self) -> Decimal:
        return self.leg.qty * self.leg.ref_price

    @property
    def distance(self) -> Decimal:
        return abs(self.leg.ref_price - self.leg.stop_price)

    @property
    def long(self) -> bool:
        return self.leg.side == "buy"


def _identity(c: _Case) -> list[Violation]:
    """Rows 1 to 6, 18, 19 and 20: who sized the leg, whether it may trade, the account-wide
    modes, which no request moves, and the native stop's size (rule 8). The hedge-mode index is
    keyed on the side: the leg opens a position (`ResolvedLeg`)."""
    found = []
    if not c.bound.is_default or (c.alternate is not None and c.alternate.is_default):
        found.append(_v("is_default", "never", "inconsistent"))  # _B_ is the account's default
    if c.leg.profile_id not in {p.profile_id for p in c.profiles}:
        found.append(_v("profile_id", "never", "changed"))
    for flag in ("enabled", "trading_enabled"):
        if not all(getattr(p, flag) for p in c.profiles):
            found.append(_v(flag, "never", "profile_disabled"))
    if c.leg.margin_mode != c.bound.margin_mode:
        found.append(_v("margin_mode", "never", "changed"))
    hedge_idx = 1 if c.long else 2
    idx = 0 if c.bound.position_mode == "one_way" else hedge_idx
    if c.leg.position_mode != c.bound.position_mode or c.leg.position_idx != idx:
        found.append(_v("position_mode", "never", "changed"))
    if c.leg.stop_qty not in (None, c.leg.qty):
        found.append(_v("require_native_sl", "never", "inconsistent", limit=c.leg.qty,
                        requested=c.leg.stop_qty))  # fmt: skip
    return found


def _symbols(c: _Case) -> list[Violation]:
    """Rows 37 to 39: allowed by _B_ **and** _A_, denied by either."""
    if c.instrument.symbol != c.leg.symbol:
        return [_v("allowed_symbols", "narrow_only", "inconsistent")]
    scopes = [SymbolScope.of(p) for p in c.profiles]
    found = []
    if not all(scope.admits(c.instrument) for scope in scopes):
        found.append(_v("allowed_symbols", "narrow_only", "symbol_not_allowed"))
    if any(scope.denied.matches(c.leg.symbol, wildcard=True) for scope in scopes):
        found.append(_v("denied_symbols", "narrow_only", "symbol_denied"))
    return found


def _r1_notional(c: _Case) -> list[Violation]:
    """R1: the notional within the effective position caps, and a request's `max_notional_usd`."""
    cap, pct = c.money_cap("max_position_notional"), c.money_cap("max_position_pct_equity")
    if cap is None and pct is None:
        return [_v("max_position_notional", "R1", "no_cap")]
    found = []
    if c.sizing is not None:
        cap = _tighter([cap, c.sizing.max_notional_usd])
    if cap is not None and c.notional > cap:
        found.append(_v("max_position_notional", "R1", "above_limit", limit=cap,
                        requested=c.notional))  # fmt: skip
    if pct is not None:
        if c.figures.equity is None:
            found.append(_unknown("max_position_pct_equity", "R1", "equity"))
        elif c.notional > pct * c.figures.equity:
            found.append(_v("max_position_pct_equity", "R1", "above_limit",
                            limit=pct * c.figures.equity, requested=c.notional))  # fmt: skip
    return found


def _budget(p: AccountProfile, equity: Decimal | None) -> tuple[str, Decimal | None]:
    """A `risk_based` profile's per-trade budget in USDT and the field that sets it."""
    if p.risk_fixed_amount is not None:
        return "risk_fixed_amount", p.risk_fixed_amount
    if p.risk_pct_equity is None or equity is None:
        return "risk_pct_equity", None
    return "risk_pct_equity", p.risk_pct_equity * equity


def _r2_risk(c: _Case) -> list[Violation]:
    """R2: the risk at the stop, both taker fees included (24 Sec.9.3 step 5), within the net
    daily-loss headroom (the effective daily caps less the realised loss and the committed risk),
    capped by _B_'s per-trade budget when _B_ sizes `risk_based`. The entry fee is priced at
    `ref`, the exit fee at the further of `ref` and the stop (OPEN-4, ruled 2026-10-25): a short's
    exit at its stop costs more than at entry."""
    f = c.figures
    if f.taker_fee_rate is None:
        return [_unknown("max_daily_loss", "R2", "taker_fee_rate")]
    daily: list[tuple[str, Decimal]] = []
    cap, pct = c.money_cap("max_daily_loss"), c.money_cap("max_daily_loss_pct")
    if cap is not None:
        daily.append(("max_daily_loss", cap))
    if pct is not None:
        if f.equity is None:
            return [_unknown("max_daily_loss_pct", "R2", "equity")]
        daily.append(("max_daily_loss_pct", pct * f.equity))
    if not daily:
        return [_v("max_daily_loss", "R2", "no_cap")]
    missing = [
        name for name in ("realised_loss_today", "committed_risk") if getattr(f, name) is None
    ]
    if f.realised_loss_today is None or f.committed_risk is None:
        return [_unknown("max_daily_loss", "R2", name) for name in missing]
    field, ceiling = min(daily, key=lambda entry: entry[1])
    headroom = ceiling - f.realised_loss_today - f.committed_risk
    ceiling = headroom
    if c.bound.sizing_mode == "risk_based":
        budget_field, budget = _budget(c.bound, f.equity)
        if budget is None:
            return [_unknown(budget_field, "R2", "equity")]
        if budget < headroom:
            field, ceiling = budget_field, budget
    exit_price = max(c.leg.ref_price, c.leg.stop_price)
    risk = c.leg.qty * (c.distance + (c.leg.ref_price + exit_price) * f.taker_fee_rate)
    if risk <= ceiling:
        return []
    return [_v(field, "R2", "above_limit", limit=ceiling, requested=risk, net_headroom=headroom,
               committed_risk=f.committed_risk)]  # fmt: skip


def _requested_budget(c: _Case) -> list[Violation]:
    """Rows 13 and 14: a requested or alternate per-trade budget never above _B_'s, when _B_ sizes
    `risk_based` (one resolved USDT budget, whichever of the two fields sets it)."""
    if c.bound.sizing_mode != "risk_based":
        return []
    equity = c.figures.equity
    _, limit = _budget(c.bound, equity)
    if limit is None:  # R2 has named the unknown equity
        return []
    field: str
    asked: Decimal | None
    if c.sizing is not None:
        if c.sizing.mode != "risk_based":
            return []
        if c.sizing.risk_per_trade_usd is not None:
            field, asked = "risk_fixed_amount", c.sizing.risk_per_trade_usd
        else:
            pct = c.sizing.risk_per_trade_pct
            field, asked = (
                "risk_pct_equity",
                None if pct is None or equity is None else pct * equity,
            )
    elif c.alternate is not None and c.alternate.sizing_mode == "risk_based":
        field, asked = _budget(c.alternate, equity)
    else:
        return []
    if asked is None:
        return [_unknown(field, "narrow_only", "equity")]
    if asked > limit:
        return [_v(field, "narrow_only", "above_limit", limit=limit, requested=asked)]
    return []


def _r3_leverage(c: _Case) -> list[Violation]:
    """R3: leverage within the effective cap and the instrument's maximum, and the stop strictly
    between entry and the isolated-margin liquidation estimate at that leverage (RSK-085): the
    price moves `ref * (1 / leverage - mmr)` before liquidation, less both taker fees on the
    notional at the stop, `2 * fee * stop` (OPEN-3), and a stop at the estimate races the
    liquidation, so equality is refused (OPEN-2; both ruled 2026-10-25). `mmr` is the risk-limit
    cache's tier rate for the notional after this leg; an unknown tier or fee rate fails closed.
    `1 / leverage` rounds down, so the estimate errs towards entry."""
    found = []
    cap = c.money_cap("max_leverage_cap")
    if cap is None:
        found.append(_v("max_leverage_cap", "R3", "no_cap"))
    elif c.leg.leverage > cap:
        found.append(_v("max_leverage_cap", "R3", "above_limit", limit=cap,
                        requested=c.leg.leverage))  # fmt: skip
    if c.leg.leverage > c.instrument.max_leverage:
        found.append(_v("leverage", "R3", "above_limit", limit=c.instrument.max_leverage,
                        requested=c.leg.leverage))  # fmt: skip
    mmr, fee = c.figures.maintenance_margin_rate, c.figures.taker_fee_rate
    if mmr is None or fee is None:
        inputs = (("maintenance_margin_rate", mmr), ("taker_fee_rate", fee))
        return [*found, *(_unknown("leverage", "R3", name) for name, v in inputs if v is None)]
    room = c.leg.ref_price * (_FLOOR.divide(Decimal(1), c.leg.leverage) - mmr)
    room -= 2 * fee * c.leg.stop_price
    if c.distance >= room:
        liquidation = c.leg.ref_price - room if c.long else c.leg.ref_price + room
        found.append(_v("leverage", "R3", "outside_liquidation", limit=liquidation,
                        requested=c.leg.stop_price))  # fmt: skip
    return found


def _consistent(c: _Case) -> bool:
    """_L_B_ is _B_'s leg for the same ticket: sized by _B_ on _B_'s account (never an
    alternate's leg), same symbol, side and `ref`, its stop on the loss side. Anything else fails
    closed (rule 4 and the take-profit row cannot be judged)."""
    b = c.baseline
    own = (b.profile_id, b.account_id) == (c.bound.profile_id, c.bound.account_id)
    same = (b.symbol, b.side, b.ref_price) == (c.leg.symbol, c.leg.side, c.leg.ref_price)
    return own and same and (b.stop_price < b.ref_price if c.long else b.stop_price > b.ref_price)


def _r4_stop(c: _Case) -> list[Violation]:
    """R4 (rows 21 to 25): the stop on the loss side, on the tick grid, no further from `ref`
    than _L_B_'s: `abs(ref - L.stop) <= abs(ref - L_B.stop)`."""
    stop = c.leg.stop_price
    if not _consistent(c):
        return [_v("sl_offset_value", "R4", "inconsistent")]
    if (stop >= c.leg.ref_price) if c.long else (stop <= c.leg.ref_price):
        return [_v("sl_offset_value", "R4", "wrong_side", limit=c.leg.ref_price, requested=stop)]
    found = []
    if not _on_grid(stop, c.instrument.tick_size):
        found.append(_v("sl_offset_value", "R4", "not_on_grid", requested=stop))
    if c.distance > abs(c.baseline.ref_price - c.baseline.stop_price):
        found.append(_v("sl_offset_value", "R4", "further_than_bound",
                        limit=c.baseline.stop_price, requested=stop))  # fmt: skip
    return found


def _take_profit(c: _Case) -> list[Violation]:
    """Rows 26 and 27: on the profit side, on the grid, no further from entry than _L_B_'s, or
    added where _B_ has none; never removed (a `null` override is refused before this)."""
    tp, bound_tp, ref = c.leg.take_profit_price, c.baseline.take_profit_price, c.leg.ref_price
    if not _consistent(c):
        return []  # R4 has refused the leg
    if tp is None:
        return [] if bound_tp is None else [_v("tp_offset_value", "narrow_only", "removed")]
    if (tp <= ref) if c.long else (tp >= ref):
        return [_v("tp_offset_value", "narrow_only", "wrong_side", limit=ref, requested=tp)]
    found = []
    if not _on_grid(tp, c.instrument.tick_size):
        found.append(_v("tp_offset_value", "narrow_only", "not_on_grid", requested=tp))
    if bound_tp is not None and abs(tp - ref) > abs(bound_tp - ref):
        found.append(_v("tp_offset_value", "narrow_only", "further_than_bound", limit=bound_tp,
                        requested=tp))  # fmt: skip
    return found


def _r5_minimums(c: _Case) -> list[Violation]:
    """R5 (rows 10, 11, 15, 16): the quantity on the lot grid (floored), at or above the
    instrument's minimums and _B_'s `min_leg_notional`, and never above a requested quantity or
    notional: a minimum is never rounded up. The instrument's maximum is R7's."""
    inst, qty = c.instrument, c.leg.qty
    found = []
    if not _on_grid(qty, inst.qty_step):
        found.append(_v("qty_rounding", "R5", "not_on_grid", requested=qty))
    if qty < inst.min_order_qty:
        found.append(_v("min_leg_notional", "R5", "below_minimum", limit=inst.min_order_qty,
                        requested=qty))  # fmt: skip
    floor = max(inst.min_notional, c.bound.min_leg_notional)
    if c.notional < floor:
        found.append(_v("min_leg_notional", "R5", "below_minimum", limit=floor,
                        requested=c.notional))  # fmt: skip
    asked = c.sizing
    if asked is not None and asked.qty is not None and qty > asked.qty:
        found.append(_v("fixed_qty", "R5", "rounded_up", limit=asked.qty, requested=qty))
    if asked is not None and asked.notional_usd is not None and c.notional > asked.notional_usd:
        found.append(_v("fixed_notional", "R5", "rounded_up", limit=asked.notional_usd,
                        requested=c.notional))  # fmt: skip
    return found


def _r6_margin(c: _Case) -> list[Violation]:
    """R6: the initial margin (rounded up) within 0.98 of the available margin; a failure, never a
    shrink (24 Sec.9.3 step 8). A negative available margin leaves no room: refused."""
    available = c.figures.available_margin
    if available is None:
        return [_unknown("leverage", "R6", "available_margin")]
    margin = _CEILING.divide(c.notional, c.leg.leverage)
    if margin > available * _MARGIN_SHARE:
        return [_v("leverage", "R6", "above_limit", limit=available * _MARGIN_SHARE,
                   requested=margin)]  # fmt: skip
    return []


_COUNTS: Final = (
    ("open_positions_after", "max_open_positions"),
    ("open_orders_after", "max_concurrent_orders"),
    ("orders_in_minute_after", "max_orders_per_minute"),
)


def _r7_caps(c: _Case) -> list[Violation]:
    """R7 (rows 33, 34, 36, 42): every other cap the guard reads, at the effective value, and the
    exchange's: neither the leg's nor a requested quantity passes the instrument's
    `max_order_qty`, whatever the route clamps upstream (OPEN-5, ruled 2026-10-25);
    `max_mkt_order_qty` is the route's (module docstring)."""
    found = []
    limit = c.instrument.max_order_qty
    asked = None if c.sizing is None else c.sizing.qty
    for qty in (c.leg.qty, asked):
        if qty is not None and qty > limit:
            found.append(_v("fixed_qty", "R7", "above_limit", limit=limit, requested=qty))
    for figure, field in _COUNTS:
        count: int | None = getattr(c.figures, figure)
        cap = c.count_cap(field)
        if count is None:
            found.append(_unknown(field, "R7", figure))
        elif cap is None:
            found.append(_v(field, "R7", "no_cap"))
        elif count > cap:
            found.append(_v(field, "R7", "above_limit", limit=Decimal(cap),
                            requested=Decimal(count)))  # fmt: skip
    slippage = c.count_cap("slippage_tolerance_bps")
    if slippage is not None and c.leg.slippage_tolerance_bps > slippage:
        found.append(_v("slippage_tolerance_bps", "R7", "above_limit", limit=Decimal(slippage),
                        requested=Decimal(c.leg.slippage_tolerance_bps)))  # fmt: skip
    return found


def _order_defaults(c: _Case) -> list[Violation]:
    """Rows 40 and 41: `reduce_only` may be set, never cleared; the order rests no longer than
    _B_'s default (`FOK`, `IOC` before `GTC`, `PostOnly`)."""
    found = []
    if _RESTS[c.leg.time_in_force] > _RESTS[c.bound.time_in_force_default]:
        found.append(_v("time_in_force_default", "narrow_only", "above_limit"))
    if c.bound.reduce_only_default and not c.leg.reduce_only:
        found.append(_v("reduce_only_default", "narrow_only", "changed"))
    return found


_RULES: Final = (
    _identity,
    _symbols,
    _r1_notional,
    _r2_risk,
    _requested_budget,
    _r3_leverage,
    _r4_stop,
    _take_profit,
    _r5_minimums,
    _r6_margin,
    _r7_caps,
    _order_defaults,
)


def _held(bound: AccountProfile, alternate: AccountProfile | None) -> tuple[str, ...]:
    """The alternate's `never` fields that differ from _B_'s and were held at _B_'s value (an
    admitted leg's profiles are all enabled and trading, so those two rows never differ)."""
    if alternate is None:
        return ()
    return tuple(
        field
        for field, row in OVERRIDE_CLASS.items()
        if row == _N
        and field not in _IDENTITY
        and getattr(alternate, field) != getattr(bound, field)
    )


def judge_leg(
    bound: AccountProfile,
    leg: ResolvedLeg,
    *,
    baseline: ResolvedLeg,
    instrument: Instrument,
    figures: AccountFigures,
    alternate: AccountProfile | None = None,
    requested: Sequence[LegOverrides] = (),
) -> Admitted | Refused:
    """ADR-0040 Decision 1's R: admit `leg` (_L_) only if every rule holds against `bound` (_B_),
    tightened by `alternate` (_A_) and the `requested` layers (`defaults`, then the leg's
    `overrides`), beside `baseline` (_L_B_); otherwise refuse it whole, naming every violation.

    Only `Admitted.leg` may be sent, never `leg` itself. Raises `ProfileNotFound` for a leg or an
    alternate of another account (`404 not_found`)."""
    if leg.account_id != bound.account_id or (
        alternate is not None and alternate.account_id != bound.account_id
    ):
        raise ProfileNotFound
    layers = [layer.sizing for layer in requested if "sizing" in layer.model_fields_set]
    case = _Case(bound, alternate, leg, baseline, instrument, figures, (layers or [None])[-1])
    with localcontext(_CONTEXT):
        found = [violation for rule in _RULES for violation in rule(case)]
    if found:
        return Refused(tuple(found))
    return Admitted(leg.model_copy(update={"stop_qty": leg.qty}), _held(bound, alternate))


def refused_fields(violations: Iterable[Violation]) -> tuple[str, ...]:
    """The `field` label values of `cv_override_refused_total{field}`, one per distinct field in
    the order first named: a closed set, the table's fields (never an account or a value)."""
    return tuple(dict.fromkeys(violation.field for violation in violations))


# --- the refused-widening audit row (built here, written ahead by the route, C-2.9) --------------

Role = Literal["owner", "manager", "viewer"]


@dataclass(frozen=True, slots=True)
class RefusalActor:
    """Who sent the refused request; `request_id` is the request's correlation id, the UUID of
    its `urn:cv:req:{uuid}` (the audit row's `request_id`)."""

    user_id: UUID
    role: Role
    env: Environment
    request_id: UUID | None = None
    ip: str | None = None


class RefusalEmitKwargs(TypedDict):
    """`AuditWriter.emit`'s and `build`'s keyword arguments for the row (all but `action`), typed
    as they declare them, so `emit(action, **kwargs)` type-checks at the route."""

    actor_label: str
    actor_user_id: UUID
    actor_ip: str | None
    object_kind: str
    object_id: str
    outcome: AuditOutcome
    severity: Severity
    reason: str
    after_state: dict[str, Any]
    request_id: UUID | None
    env: ExchangeEnv


#: The audit enums' values (`StrEnum`, so equal to these strings); `build()` validates them into
#: its own members. Typed as the enums: C-3.3 lets accounts name them only for the type checker.
_DENIED: Final = cast("AuditOutcome", "denied")
_WARNING: Final = cast("Severity", "warning")


@dataclass(frozen=True, slots=True)
class OverrideRefusalRecord:
    """One `trade_group.override_refused` row: `audit.emit(record.action,
    **record.emit_kwargs())`, the account its object, every violation its `after_state`."""

    action: str
    actor_label: str
    actor_user_id: UUID
    actor_ip: str | None
    object_kind: str
    object_id: str
    outcome: AuditOutcome
    severity: Severity
    reason: str
    after_state: Mapping[str, Any]
    request_id: UUID | None
    env: Environment

    def emit_kwargs(self) -> RefusalEmitKwargs:
        """`AuditWriter.emit`'s keyword arguments (all but `action`)."""
        return RefusalEmitKwargs(
            actor_label=self.actor_label,
            actor_user_id=self.actor_user_id,
            actor_ip=self.actor_ip,
            object_kind=self.object_kind,
            object_id=self.object_id,
            outcome=self.outcome,
            severity=self.severity,
            reason=self.reason,
            after_state=dict(self.after_state),
            request_id=self.request_id,
            env=cast("ExchangeEnv", self.env),  # the same three values (domain `Environment`)
        )


def _text(value: Decimal) -> str:
    """A plain decimal string with no exponent and no trailing zeros, every digit kept."""
    return format(value.normalize(_CONTEXT), "f")


def _entry(violation: Violation) -> dict[str, str]:
    entry = {"field": violation.field, "rule": violation.rule, "reason": violation.reason}
    for name in ("limit", "requested", "net_headroom", "committed_risk"):
        value: Decimal | None = getattr(violation, name)
        if value is not None:
            entry[name] = _text(value)
    if violation.input is not None:
        entry["input"] = violation.input
    return entry


def refusal_record(
    violations: Sequence[Violation],
    *,
    actor: RefusalActor,
    bound: AccountProfile,
    leg_index: int,
    alternate_id: UUID | None = None,
) -> OverrideRefusalRecord:
    """The refused-widening row for one offending leg (E28 threat model Sec.8, beside
    `tradegroup.row_overridden{field, from, to}`): per field its rule, limit and requested value,
    the role, the bound profile and its version. Figures only: no key, token or signature."""
    return OverrideRefusalRecord(
        action=OVERRIDE_REFUSED_ACTION,
        actor_label=str(actor.user_id),
        actor_user_id=actor.user_id,
        actor_ip=actor.ip,
        object_kind="exchange_account",
        object_id=str(bound.account_id),
        outcome=_DENIED,
        severity=_WARNING,
        reason=_PROBLEM,
        after_state={
            "exchange_account_id": str(bound.account_id),
            "role": actor.role,
            "leg": leg_index,
            "bound_profile_id": str(bound.profile_id),
            "bound_profile_version": bound.version,
            "alternate_profile_id": None if alternate_id is None else str(alternate_id),
            "violations": [_entry(violation) for violation in violations],
        },
        request_id=actor.request_id,
        env=actor.env,
    )
