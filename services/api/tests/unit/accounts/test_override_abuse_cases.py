"""E28-X03 (#976) abuse cases that need no route, against the never-widen comparator (#2635, F-01).

The E28 threat model's AC-03, AC-04, AC-10, AC-11 and AC-12 (section 7), judged under ADR-0040
(proposed, #4461) Decision 1: a Manager holding `orders:write` on the account tries to widen B's
caps through a request value, an alternate `profile_id`, the order of `defaults` and `legs[]`,
a unit mix, or a null. Each leg here is what a resolver would hand over for that request; the
comparator refuses it whole, never a clamped leg. A refusal maps to `403 risk_limit_breached`, a
`ValidationError` to `422 validation_failed`, `ProfileNotFound` to `404 not_found`. AC-12's "refused
when quantity rises" is superseded by the coordinator's ruling (ADR-0040 OPEN-1): a tighter stop
under risk-based sizing may raise the size up to B's caps, never past them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.accounts.override_comparator import LegOverrides, ProfileNotFound
from tests.unit.accounts._override_world import (
    OTHER_ACCOUNT,
    admitted,
    alternate,
    figures,
    judge,
    leg,
    profile,
    refused,
)

D = Decimal


def _layer(body: dict[str, Any]) -> LegOverrides:
    return LegOverrides.model_validate(body)


#: AC-04: each protected cap widened in turn, by the leg a widening request value would produce.
_WIDENINGS = [
    ("max_position_notional", {"qty": D("0.4")}, {}),
    ("max_position_pct_equity", {"qty": D("0.2")}, {"equity": D("20000")}),
    ("max_daily_loss", {"qty": D("0.8"), "leverage": D("10")}, {"available_margin": D("1e9")}),
    ("max_leverage_cap", {"leverage": D("25")}, {}),
    ("max_open_positions", {}, {"open_positions_after": 4}),
    ("max_concurrent_orders", {}, {"open_orders_after": 6}),
    ("max_orders_per_minute", {}, {"orders_in_minute_after": 61}),
    ("slippage_tolerance_bps", {"slippage_tolerance_bps": 50}, {}),
    ("sl_offset_value", {"stop_price": D("60000.0")}, {}),
    ("time_in_force_default", {"time_in_force": "GTC"}, {}),
]


@pytest.mark.parametrize(("field", "changes", "world"), _WIDENINGS, ids=[w[0] for w in _WIDENINGS])
def test_ac04_widening_each_protected_cap_is_refused(
    field: str, changes: dict[str, Any], world: dict[str, Any]
) -> None:
    bound = profile(max_position_notional="1000000") if field == "max_daily_loss" else profile()
    result = judge(leg(**changes), figures=figures(**world), bound=bound)
    assert field in [f for f, _, _ in refused(result)]


def test_ac11_the_widest_alternate_is_judged_against_the_bound_profile() -> None:
    widest = alternate(
        fixed_qty="1", leverage="100", max_leverage_cap="100", max_position_notional="1000000",
        max_daily_loss="1000000", max_open_positions=50, max_concurrent_orders=500,
        max_orders_per_minute=600, all_symbols=True, allowed_symbols=[],
        slippage_tolerance_bps=1000, time_in_force_default="GTC",
    )  # fmt: skip
    sized_by_alternate = leg(profile_id=widest.profile_id, qty=D("1"), leverage=D("100"))
    assert [f for f, _, _ in refused(judge(sized_by_alternate, alternate=widest))] == [
        "max_position_notional",
        "max_position_pct_equity",
        "max_daily_loss",
        "max_leverage_cap",
        "leverage",
    ]


def test_ac11_an_alternate_of_another_account_is_not_found_as_a_missing_one() -> None:
    with pytest.raises(ProfileNotFound) as foreign:
        judge(alternate=alternate(account_id=OTHER_ACCOUNT))
    assert str(foreign.value) == str(ProfileNotFound())


def test_ac11_defaults_sizing_above_the_profile_is_refused() -> None:
    defaults = _layer({"sizing": {"mode": "fixed_qty", "qty": "0.4"}})
    assert refused(judge(leg(qty=D("0.4")), requested=(defaults,))) == [
        ("max_position_notional", "R1", "above_limit")
    ]


def test_defaults_then_legs_a_narrow_default_does_not_cover_a_widening_leg_value() -> None:
    narrow = _layer({"sizing": {"mode": "fixed_qty", "qty": "0.05"}})
    wide = _layer({"sizing": {"mode": "fixed_qty", "qty": "0.4"}})
    assert refused(judge(leg(qty=D("0.4")), requested=(narrow, wide))) == [
        ("max_position_notional", "R1", "above_limit")
    ]


def test_defaults_then_legs_a_resolver_that_kept_the_default_is_caught() -> None:
    """The later layer asked for 0.05; a leg sized at the earlier layer's 0.2 is rounded up."""
    wide = _layer({"sizing": {"mode": "fixed_qty", "qty": "0.2"}})
    narrow = _layer({"sizing": {"mode": "fixed_qty", "qty": "0.05"}})
    assert refused(judge(leg(qty=D("0.2")), requested=(wide, narrow))) == [
        ("fixed_qty", "R5", "rounded_up")
    ]
    admitted(judge(leg(qty=D("0.05")), requested=(wide, narrow)))


def test_unit_mix_a_percent_stop_further_than_the_bound_is_refused() -> None:
    """B's stop is 1 %; a request stop of 0.05 read as a fraction is a 5 % stop, further away."""
    mixed = _layer({"stop_loss": {"unit": "percent", "value": "0.05"}})
    assert refused(judge(leg(stop_price=D("60809.5")), requested=(mixed,))) == [
        ("sl_offset_value", "R4", "further_than_bound")
    ]


def test_unit_mix_a_percent_where_a_fraction_belongs_is_a_validation_failure() -> None:
    with pytest.raises(ValidationError):
        _layer({"sizing": {"mode": "pct_equity", "pct": "50"}})


@pytest.mark.parametrize("member", ["sizing", "leverage", "stop_loss", "take_profit"])
def test_null_cannot_unset_a_bound_value(member: str) -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        _layer({member: None})


def test_ac12_a_tighter_stop_under_risk_based_sizing_raises_size_only_within_the_caps() -> None:
    """B risks 100 USDT per trade. A stop half as far (320.0 from entry) lets 0.2 BTC risk
    64.0 + 14.0822 = 78.0822 USDT: within the budget and the 20000 USDT cap, admitted. 0.4 BTC
    risks 156.1644 USDT and is 25604 USDT: refused on both."""
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="100")
    tighter = _layer({"stop_loss": {"unit": "percent", "value": "0.005"}})
    admitted(judge(leg(qty=D("0.2"), stop_price=D("63690.0")), bound=risk, requested=(tighter,)))
    assert refused(
        judge(leg(qty=D("0.4"), stop_price=D("63690.0")), bound=risk, requested=(tighter,))
    ) == [
        ("max_position_notional", "R1", "above_limit"),
        ("risk_fixed_amount", "R2", "above_limit"),
    ]


def test_ac03_an_oversized_quantity_hint_is_refused_not_clamped() -> None:
    hint = _layer({"sizing": {"mode": "fixed_qty", "qty": "5"}})
    assert refused(judge(leg(qty=D("5")), requested=(hint,)))[0] == (
        "max_position_notional",
        "R1",
        "above_limit",
    )


@pytest.mark.parametrize("member", ["profile_snapshot", "atr", "risk_checked"])
def test_ac10_a_client_supplied_snapshot_is_refused(member: str) -> None:
    with pytest.raises(ValidationError):
        _layer({member: {}})
