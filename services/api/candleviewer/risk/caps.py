"""Cap resolution (E39-T01): three stored layers merged into one limit per cap.

The layers are the global `risk_policy` row, the account's `account_profiles` caps and the acting
manager's `user_account_access.max_daily_loss_usd` (`21-database-schema.md` §3.11, §3.3, §3.1.3).
Per cap the **most restrictive** non-NULL value wins, so no layer can widen another
(US-PROF-003, SR-E39-03). On a tie the most specific layer is named (manager, then profile, then
policy), so a refusal points at the limit someone can change. A layer column left NULL sets no limit
there; the policy row's columns are never NULL. Documented in `24-internal-schemas.md` §8.11.

`breach_behaviour` (`risk_policy`, one per policy column) decides how a policy limit takes part:
`block` and `flatten` make it a blocking limit like the profile's and the manager's, which always
block (the flatten is E39-S02's); `warn` leaves it out of the blocking minimum and keeps it apart
as a warn threshold. So per cap the tightest *blocking* limit and the policy's warn threshold are
resolved separately and evaluated independently: a policy `warn` records a warning and can never
soften or disable a profile or manager limit (SR-E39-03).

A policy limit of 0 is a limit, not "unlimited": a zero `max_daily_loss_usd` or `max_drawdown_pct`
refuses every opening order, a zero `max_open_positions` every new position, so a zero cap halts
trading on that cap.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from pydantic import TypeAdapter, ValidationError

from candleviewer.accounts.profiles import SymbolEntries, SymbolPattern, SymbolScope


class CapSource(StrEnum):
    """The layer that binds a resolved limit; `label` names it in a refusal message."""

    MANAGER = "manager"
    PROFILE = "profile"
    POLICY = "policy"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS: Final = {
    CapSource.MANAGER: "the manager override",
    CapSource.PROFILE: "the account profile",
    CapSource.POLICY: "the global risk policy",
}

Behaviour = Literal["warn", "block", "flatten"]
_PATTERN: Final = TypeAdapter(SymbolPattern)
_NO_SYMBOLS: Final = SymbolEntries.of(())


@dataclass(frozen=True, slots=True)
class PolicyCaps:
    """The `risk_policy` singleton's limits (every column NOT NULL)."""

    max_total_notional_usd: Decimal
    max_daily_loss_usd: Decimal
    max_drawdown_pct: Decimal
    max_open_positions: int
    max_leverage: Decimal
    max_orders_per_minute: int
    per_symbol_concentration_pct: Decimal
    breach_behaviour: Mapping[str, Behaviour]


@dataclass(frozen=True, slots=True)
class ProfileCaps:
    """The account profile's caps; None sets no limit at this layer.

    `max_consecutive_losses` has no stored column yet (E39-S02/E39-T03 own it): it is evaluated
    only when given. `blocked_symbols` is `AccountProfile.denied_symbols` under the gate's name:
    slice 4's binder maps the one to the other. Each symbol entry must read as the profile layer's
    `SymbolPattern`; one that does not refuses every symbol (`resolve_caps`).
    """

    max_position_notional_usd: Decimal | None = None
    max_position_pct_equity: Decimal | None = None
    max_daily_loss_usd: Decimal | None = None
    max_daily_loss_pct: Decimal | None = None
    max_open_positions: int | None = None
    max_concurrent_orders: int | None = None
    max_leverage_cap: Decimal | None = None
    max_orders_per_minute: int | None = None
    max_consecutive_losses: int | None = None
    all_symbols: bool = False
    allowed_symbols: frozenset[str] = frozenset()
    blocked_symbols: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ManagerCaps:
    """The acting manager's override row for this account (applies to that user only)."""

    max_daily_loss_usd: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCap:
    name: str
    limit: Decimal
    source: CapSource
    behaviour: Behaviour


@dataclass(frozen=True, slots=True)
class ResolvedCaps:
    """Per cap the tightest blocking limit and the policy's warn threshold, plus the symbol rule.

    `caps` holds the blocking limits (behaviour `block` or `flatten`), `warn_limits` the policy
    limits whose behaviour is `warn`; a cap may appear in either, both or neither. `symbols` is the
    profile's lists compiled into `accounts.profiles.SymbolScope`, the one matcher the order path
    and a profile save use (#908, PF-T07, SR-E28-06), so a `*USDT` pattern means here what it
    means there.
    """

    caps: Mapping[str, ResolvedCap]
    symbols: SymbolScope
    warn_limits: Mapping[str, ResolvedCap] = MappingProxyType({})

    def get(self, name: str) -> ResolvedCap | None:
        return self.caps.get(name)

    def warn_limit(self, name: str) -> ResolvedCap | None:
        return self.warn_limits.get(name)


def _num(value: Decimal | int | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def resolve_caps(
    policy: PolicyCaps, profile: ProfileCaps, manager: ManagerCaps | None = None
) -> ResolvedCaps:
    """Merge the three layers, most restrictive blocking limit per cap; ties name the most specific.

    `manager` is the override row of the order's acting user (`RiskOrder.user_id`) on this account
    only, never another manager's, and None for a system origin (SR-E39-03, "that acting user").
    """
    m, f, p = manager or ManagerCaps(), profile, policy
    layers: dict[str, tuple[Decimal | int | None, ...]] = {  # cap: (manager, profile, policy)
        "max_position_notional_usd": (None, f.max_position_notional_usd, None),
        "max_total_notional_usd": (None, None, p.max_total_notional_usd),
        "max_position_pct_equity": (None, f.max_position_pct_equity, None),
        "max_daily_loss_usd": (m.max_daily_loss_usd, f.max_daily_loss_usd, p.max_daily_loss_usd),
        "max_daily_loss_pct": (None, f.max_daily_loss_pct, None),
        "max_drawdown_pct": (None, None, p.max_drawdown_pct),
        "max_open_positions": (None, f.max_open_positions, p.max_open_positions),
        "max_concurrent_orders": (None, f.max_concurrent_orders, None),
        "max_leverage": (None, f.max_leverage_cap, p.max_leverage),
        "max_orders_per_minute": (None, f.max_orders_per_minute, p.max_orders_per_minute),
        "per_symbol_concentration_pct": (None, None, p.per_symbol_concentration_pct),
        "max_consecutive_losses": (None, f.max_consecutive_losses, None),
    }
    sources = (CapSource.MANAGER, CapSource.PROFILE, CapSource.POLICY)
    caps: dict[str, ResolvedCap] = {}
    warns: dict[str, ResolvedCap] = {}
    for name, values in layers.items():
        best: tuple[Decimal, CapSource, Behaviour] | None = None
        for source, raw in zip(sources, values, strict=True):
            value = _num(raw)
            if value is None:
                continue
            behaviour: Behaviour = "block"
            if source is CapSource.POLICY:
                behaviour = policy.breach_behaviour.get(name, "block")
                if behaviour == "warn":  # a threshold apart: never in the blocking minimum
                    warns[name] = ResolvedCap(name, value, source, behaviour)
                    continue
            # Strict `<`: on a tie the earlier, more specific layer keeps the attribution.
            if best is None or value < best[0]:
                best = (value, source, behaviour)
        if best is not None:
            caps[name] = ResolvedCap(name, *best)
    return ResolvedCaps(
        caps=MappingProxyType(caps),
        warn_limits=MappingProxyType(warns),
        symbols=_scope(profile),
    )


def _entries(listed: frozenset[str]) -> SymbolEntries | None:
    try:
        return SymbolEntries.of(_PATTERN.validate_python(entry) for entry in listed)
    except ValidationError:
        return None


def _scope(profile: ProfileCaps) -> SymbolScope:
    """The profile's lists compiled; an entry outside `SymbolPattern` on either list fails closed:
    the scope admits nothing, whatever `all_symbols` says."""
    allowed, denied = _entries(profile.allowed_symbols), _entries(profile.blocked_symbols)
    if allowed is None or denied is None:
        return SymbolScope(all_symbols=False, allowed=_NO_SYMBOLS, denied=_NO_SYMBOLS)
    return SymbolScope(all_symbols=profile.all_symbols, allowed=allowed, denied=denied)
