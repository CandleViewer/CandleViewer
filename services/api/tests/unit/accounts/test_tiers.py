"""`lowest_tier_rate` (E29-T04, #913): the lowest risk-limit tier by value, never by id."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.accounts.tiers import RiskTier, lowest_tier_rate
from candleviewer.exchange.base.models import RiskLimitTier


def _tier(tier_id: int, value: str, mmr: str) -> RiskLimitTier:
    return RiskLimitTier(
        tier_id=tier_id, risk_limit_value=Decimal(value), maintenance_margin_rate=Decimal(mmr),
        initial_margin_rate=Decimal("0.01"), max_leverage=Decimal(100),
    )  # fmt: skip


def test_lowest_tier_rate_by_value_not_tier_id_1() -> None:
    tiers = [_tier(1, "2000000", "0.01"), _tier(11, "200000", "0.004"), _tier(5, "900000", "0.008")]
    assert lowest_tier_rate(tiers) == Decimal("0.004")


def test_lowest_tier_rate_no_tiers_is_none() -> None:
    assert lowest_tier_rate([]) is None and lowest_tier_rate(None) is None


def test_adapter_tier_satisfies_the_risk_tier_protocol() -> None:
    tier: RiskTier = _tier(1, "200000", "0.004")  # mypy fails here if the shape drifts
    assert tier.risk_limit_value == Decimal("200000")
    assert tier.maintenance_margin_rate == Decimal("0.004")
