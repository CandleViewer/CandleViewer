"""The risk-limit tier reading the save-time warnings and the order path share (E29-T04, #913).

`lowest_tier_rate` is the maintenance margin rate of a symbol's lowest risk-limit tier, chosen by
`risk_limit_value`, never assumed to be `tier_id == 1` (the venue does not order its ids by value).
It reads any tier of that shape (`exchange.base.models.RiskLimitTier`), so `accounts` takes no
new dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

__all__ = ["RiskTier", "lowest_tier_rate"]


class RiskTier(Protocol):
    """The tier shape read here; keeps `accounts` free of an `exchange.base` import (C-3.4: ADR)."""

    @property
    def risk_limit_value(self) -> Decimal: ...

    @property
    def maintenance_margin_rate(self) -> Decimal: ...


def lowest_tier_rate(tiers: Sequence[RiskTier] | None) -> Decimal | None:
    """The maintenance margin rate of the lowest tier by `risk_limit_value`; None with no tiers."""
    if not tiers:
        return None
    return min(tiers, key=lambda tier: tier.risk_limit_value).maintenance_margin_rate
