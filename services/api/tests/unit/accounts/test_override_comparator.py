"""The never-widen comparator, rule by rule (ADR-0040 (proposed, #4461) Decision 1; #2635, F-01).

Each rule's boundary: the limit itself is admitted, one tick or one lot past it is refused, and a
refusal is whole, never a clamped leg. Numbers: `_override_world`'s docstring.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.accounts.override_comparator import (
    FLOOR_FIELDS,
    OVERRIDE_CLASS,
    AccountFigures,
    LegOverrides,
    ProfileNotFound,
    Violation,
    override_class,
)
from candleviewer.accounts.profiles import AccountProfile
from tests.unit.accounts._override_world import (
    ALTERNATE_ID,
    BASELINE,
    BOUND,
    BTCUSDT,
    FIGURES,
    OTHER_ACCOUNT,
    admitted,
    alternate,
    figures,
    judge,
    leg,
    profile,
    refused,
    violations,
)

D = Decimal


# --- the decision table --------------------------------------------------------------------------


def test_every_profile_field_has_an_override_class() -> None:
    """42 rows, 15 `never` and 27 `narrow_only`, exactly the model's fields (SR-E28-04)."""
    assert list(OVERRIDE_CLASS) == [
        *list(AccountProfile.model_fields)[:7],
        "updated_at",
        *[f for f in list(AccountProfile.model_fields)[7:] if f != "updated_at"],
    ]
    classes = list(OVERRIDE_CLASS.values())
    assert (len(classes), classes.count("never"), classes.count("narrow_only")) == (42, 15, 27)


def test_a_field_the_table_does_not_name_is_never() -> None:
    assert override_class("max_consecutive_losses") == "never"


def test_the_six_floor_fields_take_no_request_value() -> None:
    assert FLOOR_FIELDS == {
        "max_position_notional",
        "max_daily_loss",
        "max_open_positions",
        "max_leverage_cap",
        "all_symbols",
        "allowed_symbols",
        "require_native_sl",
    }
    for field in FLOOR_FIELDS:
        with pytest.raises(ValidationError):
            LegOverrides.model_validate({field: BOUND.model_dump()[field]})


@pytest.mark.parametrize("field", [f for f, c in OVERRIDE_CLASS.items() if c == "never"])
def test_a_never_field_cannot_be_named_by_a_request(field: str) -> None:
    with pytest.raises(ValidationError):
        LegOverrides.model_validate({field: BOUND.model_dump()[field]})


@pytest.mark.parametrize(
    ("field", "value"),
    [("margin_mode", "cross"), ("position_mode", "hedge"), ("position_idx", 1)],
)
def test_a_never_field_changed_on_the_resulting_leg_is_refused(field: str, value: Any) -> None:
    rule = "position_mode" if field == "position_idx" else field
    assert refused(judge(leg(**{field: value}))) == [(rule, "never", "changed")]


def test_the_profile_s_own_leg_is_admitted_unchanged() -> None:
    result = admitted(judge())
    assert result.leg == BASELINE.model_copy(update={"stop_qty": BASELINE.qty})
    assert result.held == ()


# --- absent, null and the request's own shape ----------------------------------------------------


@pytest.mark.parametrize(
    "member", ["leverage", "stop_loss", "take_profit", "sizing", "time_in_force"]
)
def test_a_null_override_member_is_refused_not_read_as_absent(member: str) -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        LegOverrides.model_validate({member: None})


def test_an_absent_member_takes_the_bound_profile_s_value() -> None:
    assert LegOverrides().model_fields_set == set()
    admitted(judge(requested=(LegOverrides(),)))


@pytest.mark.parametrize(
    "body",
    [
        {"sizing": {"mode": "fixed_qty", "qty": "0.1", "round_to_lot": False}},
        {"sizing": {"mode": "risk_based"}},
        {"sizing": {"mode": "fixed_qty"}},
        {"sizing": {"mode": "pct_equity", "pct": "50"}},
        {"stop_loss": {"unit": "r_multiple", "value": "1"}},
        {"leverage": "0.5"},
        {"profile_snapshot": {}},
    ],
)
def test_a_malformed_override_is_a_validation_failure(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LegOverrides.model_validate(body)


def test_an_alternate_of_another_account_is_not_found() -> None:
    with pytest.raises(ProfileNotFound):
        judge(alternate=alternate(account_id=OTHER_ACCOUNT))


def test_a_leg_of_another_account_is_not_found() -> None:
    with pytest.raises(ProfileNotFound):
        judge(leg(account_id=OTHER_ACCOUNT))


def test_a_leg_sized_by_neither_profile_is_refused() -> None:
    assert refused(judge(leg(profile_id="0b5f6d0e-28a1-4c1e-9e01-0000000000ee"))) == [
        ("profile_id", "never", "changed")
    ]


@pytest.mark.parametrize("field", ["enabled", "trading_enabled"])
def test_a_disabled_alternate_is_refused(field: str) -> None:
    disabled = alternate(**{field: False})
    assert refused(judge(alternate=disabled)) == [(field, "never", "profile_disabled")]


def test_a_bound_profile_that_is_not_the_account_default_is_refused() -> None:
    assert refused(judge(bound=profile(is_default=False))) == [
        ("is_default", "never", "inconsistent")
    ]


def test_an_alternate_that_is_the_account_default_is_refused() -> None:
    assert refused(judge(alternate=alternate(is_default=True))) == [
        ("is_default", "never", "inconsistent")
    ]


def test_a_bound_profile_that_cannot_trade_is_refused() -> None:
    assert ("trading_enabled", "never", "profile_disabled") in refused(
        judge(bound=profile(trading_enabled=False))
    )


def test_an_alternate_s_never_fields_are_held_at_the_bound_profile_and_named() -> None:
    result = admitted(judge(alternate=alternate(margin_mode="cross", fallback_sl_offset_pct="0.5")))
    assert result.held == ("margin_mode", "fallback_sl_offset_pct")


# --- R1: notional within the effective position caps ---------------------------------------------


def test_raise_size_up_to_the_cap_is_admitted() -> None:
    raised = leg(qty=D("0.25"))  # 16002.5 USDT under the 20000 cap (ADR Gherkin)
    assert admitted(judge(raised)).leg.qty == D("0.25")


def test_raise_size_above_the_cap_is_refused_never_clamped() -> None:
    result = judge(leg(qty=D("0.4")))  # 25604 USDT
    assert refused(result) == [("max_position_notional", "R1", "above_limit")]
    (violation,) = violations(result)
    assert (violation.limit, violation.requested) == (D("20000"), D("25604.000"))


@pytest.mark.parametrize(("qty", "ok"), [("0.25", True), ("0.251", False)])
def test_notional_cap_boundary_equal_passes_one_lot_over_refuses(qty: str, ok: bool) -> None:
    result = judge(leg(qty=D(qty)), bound=profile(max_position_notional="16002.5"))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("max_position_notional", "R1", "above_limit")]


@pytest.mark.parametrize(("equity", "ok"), [("32005", True), ("32004.99", False)])
def test_pct_of_equity_cap_boundary(equity: str, ok: bool) -> None:
    """0.25 BTC is 16002.5 USDT: half of 32005 USDT exactly."""
    result = judge(leg(qty=D("0.25")), figures=figures(equity=D(equity)))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("max_position_pct_equity", "R1", "above_limit")]


def test_alternate_caps_tighten_and_never_loosen() -> None:
    tighter = alternate(max_position_notional="10000")
    assert refused(judge(leg(qty=D("0.2")), alternate=tighter)) == [
        ("max_position_notional", "R1", "above_limit")
    ]
    looser = alternate(max_position_notional="99999", max_position_pct_equity="1")
    assert refused(judge(leg(qty=D("0.4")), alternate=looser)) == [
        ("max_position_notional", "R1", "above_limit")
    ]


def test_a_request_max_notional_only_narrows() -> None:
    capped = LegOverrides.model_validate(
        {"sizing": {"mode": "fixed_qty", "qty": "0.2", "max_notional_usd": "10000"}}
    )
    assert refused(judge(leg(qty=D("0.2")), requested=(capped,))) == [
        ("max_position_notional", "R1", "above_limit")
    ]


def test_no_position_cap_at_all_fails_closed() -> None:
    bare = profile(trading_enabled=False).model_copy(
        update={"trading_enabled": True, "max_position_notional": None,
                "max_position_pct_equity": None}
    )  # fmt: skip
    assert refused(judge(bound=bare)) == [("max_position_notional", "R1", "no_cap")]


# --- R2: risk at the stop within the net daily-loss ceiling --------------------------------------


@pytest.mark.parametrize(("committed", "ok"), [("0", True), ("0.0001", False)])
def test_risk_boundary_against_the_net_daily_loss_headroom(committed: str, ok: bool) -> None:
    capped = profile(max_daily_loss="71.0511")  # B's leg risks exactly this
    result = judge(bound=capped, figures=figures(committed_risk=D(committed)))
    if ok:
        admitted(result)
        return
    assert refused(result) == [("max_daily_loss", "R2", "above_limit")]
    (violation,) = violations(result)
    assert (violation.net_headroom, violation.committed_risk) == (D("71.0510"), D("0.0001"))
    assert (violation.limit, violation.requested) == (D("71.0510"), D("71.0511000"))


@pytest.mark.parametrize(("cap", "ok"), [("71.0863055", True), ("71.0863054", False)])
def test_a_short_leg_s_exit_fee_is_priced_at_its_stop(cap: str, ok: bool) -> None:
    """OPEN-4 (ruled 2026-10-25): the exit fee at the further of `ref` and the stop. A short
    0.1 BTC at 64010 stopped at 64650.1 risks 64.01 + 3.52055 (entry) + 3.5557555 (exit at the
    stop) = 71.0863055; priced at `ref` the exit fee would be 3.52055 and 71.0863054 would pass."""
    short = dict(side="sell", stop_price=D("64650.1"), take_profit_price=D("62729.8"))
    result = judge(leg(**short), baseline=leg(**short), bound=profile(max_daily_loss=cap))
    if ok:
        admitted(result)
        return
    assert refused(result) == [("max_daily_loss", "R2", "above_limit")]
    (violation,) = violations(result)
    assert violation.requested == D("71.0863055")


def test_realised_loss_today_reduces_the_headroom() -> None:
    result = judge(figures=figures(realised_loss_today=D("430")))  # 70 left, 71.0511 at risk
    assert refused(result) == [("max_daily_loss", "R2", "above_limit")]


def test_the_daily_loss_pct_cap_binds_when_tighter() -> None:
    result = judge(bound=profile(max_daily_loss_pct="0.0007"))  # 70 USDT of 100000
    assert refused(result) == [("max_daily_loss_pct", "R2", "above_limit")]


def test_one_click_minimum_above_the_risk_budget_is_refused_not_rounded_up() -> None:
    """ADR Gherkin (#904 V04): 0.001 BTC at the stop risks 0.710511 USDT, above a 0.10 budget."""
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="0.10")
    assert refused(judge(leg(qty=D("0.001")), bound=risk)) == [
        ("risk_fixed_amount", "R2", "above_limit")
    ]


def test_risk_based_budget_from_equity_caps_the_leg() -> None:
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_pct_equity="0.0007")
    assert refused(judge(bound=risk)) == [("risk_pct_equity", "R2", "above_limit")]
    assert refused(judge(bound=risk, figures=figures(equity=None))) == [
        ("max_position_pct_equity", "R1", "unknown_input"),
        ("risk_pct_equity", "R2", "unknown_input"),
    ]


@pytest.mark.parametrize(("budget", "ok"), [("100", True), ("100.0000000000000000000001", False)])
def test_a_requested_risk_budget_never_exceeds_the_bound_one(budget: str, ok: bool) -> None:
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="100")
    body = {"sizing": {"mode": "risk_based", "risk_per_trade_usd": budget}}
    result = judge(bound=risk, requested=(LegOverrides.model_validate(body),))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("risk_fixed_amount", "narrow_only", "above_limit")]


def test_an_alternate_s_larger_risk_budget_is_refused() -> None:
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="100")
    wider = alternate(sizing_mode="risk_based", fixed_qty=None, risk_pct_equity="0.01")
    assert refused(judge(bound=risk, alternate=wider)) == [
        ("risk_pct_equity", "narrow_only", "above_limit")
    ]


# --- R3: leverage within the cap, the stop inside liquidation ------------------------------------


@pytest.mark.parametrize(("leverage", "ok"), [("10", True), ("10.000000000000000000000001", False)])
def test_leverage_cap_boundary_in_exact_decimal(leverage: str, ok: bool) -> None:
    result = judge(leg(leverage=D(leverage)))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("max_leverage_cap", "R3", "above_limit")]


def test_an_alternate_s_lower_leverage_cap_binds() -> None:
    assert refused(judge(alternate=alternate(leverage="5", max_leverage_cap="5"))) == [
        ("max_leverage_cap", "R3", "above_limit")
    ]


_NO_FEE_1PCT = {"maintenance_margin_rate": D("0.01"), "taker_fee_rate": D("0")}


@pytest.mark.parametrize(("leverage", "ok"), [("49.99", True), ("50", False)])
def test_a_stop_at_the_liquidation_estimate_is_refused(leverage: str, ok: bool) -> None:
    """OPEN-2 (ruled 2026-10-25): at 50x, a 1 % rate and no fee a long liquidates at
    64010 * 0.99 = 63369.9, B's stop. A stop there races the liquidation: refused, not admitted."""
    wide = profile(max_leverage_cap="100")
    result = judge(leg(leverage=D(leverage)), bound=wide, figures=figures(**_NO_FEE_1PCT))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("leverage", "R3", "outside_liquidation")]


def test_a_short_stop_at_its_liquidation_estimate_is_refused() -> None:
    short = dict(side="sell", stop_price=D("64650.1"), take_profit_price=D("62729.8"))
    base = leg(**short)
    wide = profile(max_leverage_cap="100")
    rate = figures(**_NO_FEE_1PCT)
    admitted(judge(leg(**short, leverage=D("49.99")), baseline=base, bound=wide, figures=rate))
    assert refused(
        judge(leg(**short, leverage=D("50")), baseline=base, bound=wide, figures=rate)
    ) == [("leverage", "R3", "outside_liquidation")]


@pytest.mark.parametrize(("leverage", "ok"), [("47.4", True), ("47.5", False)])
def test_the_liquidation_estimate_keeps_both_taker_fees_at_the_stop(
    leverage: str, ok: bool
) -> None:
    """OPEN-3 (ruled 2026-10-25): the room before liquidation, 64010 * (1 / leverage - 0.01), less
    both taker fees on the notional at the stop, 2 * 0.00055 * 63369.9 = 69.70689 per unit. At
    47.5x the room is 707.48 without them (admitted) and 637.77 with them, under the 640.1 stop."""
    wide = profile(max_leverage_cap="100")
    rate = figures(maintenance_margin_rate=D("0.01"))
    result = judge(leg(leverage=D(leverage)), bound=wide, figures=rate)
    if ok:
        admitted(result)
        return
    assert refused(result) == [("leverage", "R3", "outside_liquidation")]
    (violation,) = violations(result)
    assert violation.limit is not None
    assert D("63372.2279") < violation.limit < D("63372.2280")  # 64010 - 637.7720...


def test_leverage_above_the_instrument_maximum_is_refused() -> None:
    wide = profile(max_leverage_cap="100")
    instrument = BTCUSDT.model_copy(update={"max_leverage": D("25")})
    assert ("leverage", "R3", "above_limit") in refused(
        judge(leg(leverage=D("30")), bound=wide, instrument=instrument)
    )


# --- R4: the stop no further from entry than B's, on the loss side --------------------------------


@pytest.mark.parametrize(("stop", "ok"), [("63369.9", True), ("63369.8", False)])
def test_stop_distance_boundary(stop: str, ok: bool) -> None:
    result = judge(leg(stop_price=D(stop)))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("sl_offset_value", "R4", "further_than_bound")]


def test_a_tighter_stop_is_admitted() -> None:
    admitted(judge(leg(stop_price=D("63700.0"))))


@pytest.mark.parametrize("stop", ["64010", "64010.1"])
def test_a_stop_at_or_across_entry_is_refused(stop: str) -> None:
    assert refused(judge(leg(stop_price=D(stop)))) == [("sl_offset_value", "R4", "wrong_side")]


def test_a_stop_off_the_tick_grid_is_refused() -> None:
    assert refused(judge(leg(stop_price=D("63369.95")))) == [
        ("sl_offset_value", "R4", "not_on_grid")
    ]


def test_a_baseline_sized_by_another_profile_fails_closed() -> None:
    """M1: the alternate's own leg, its stop further out, is no measure of B's stop distance."""
    further = leg(stop_price=D("61000.0"))
    assert refused(
        judge(
            further,
            baseline=leg(profile_id=ALTERNATE_ID, stop_price=D("60000.0")),
            alternate=alternate(),
        )
    ) == [("sl_offset_value", "R4", "inconsistent")]
    assert refused(judge(further, alternate=alternate())) == [
        ("sl_offset_value", "R4", "further_than_bound")
    ]


def test_a_baseline_of_another_account_fails_closed() -> None:
    other = leg(account_id=OTHER_ACCOUNT)
    assert refused(judge(baseline=other)) == [("sl_offset_value", "R4", "inconsistent")]


def test_a_baseline_at_another_reference_price_fails_closed() -> None:
    result = judge(baseline=leg(ref_price=D("64000"), stop_price=D("63360.0")))
    assert refused(result) == [("sl_offset_value", "R4", "inconsistent")]


# --- R5: minimums never rounded up; quantity on the lot grid --------------------------------------


@pytest.mark.parametrize(("qty", "ok"), [("0.1", True), ("0.099", False)])
def test_min_leg_notional_boundary(qty: str, ok: bool) -> None:
    result = judge(leg(qty=D(qty)), bound=profile(min_leg_notional="6401"))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("min_leg_notional", "R5", "below_minimum")]


def test_a_requested_quantity_below_the_minimum_is_never_rounded_up() -> None:
    tiny = LegOverrides.model_validate({"sizing": {"mode": "fixed_qty", "qty": "0.0005"}})
    assert refused(judge(leg(qty=D("0.001")), requested=(tiny,))) == [
        ("fixed_qty", "R5", "rounded_up")
    ]


def test_a_requested_notional_is_never_exceeded() -> None:
    body = {"sizing": {"mode": "fixed_notional", "notional_usd": "6400"}}
    assert refused(judge(requested=(LegOverrides.model_validate(body),))) == [
        ("fixed_notional", "R5", "rounded_up")
    ]


def test_a_quantity_off_the_lot_grid_is_refused() -> None:
    assert refused(judge(leg(qty=D("0.1005")))) == [("qty_rounding", "R5", "not_on_grid")]


# --- R6: margin fundable --------------------------------------------------------------------------


@pytest.mark.parametrize(("qty", "ok"), [("0.049", True), ("0.05", False)])
def test_margin_boundary(qty: str, ok: bool) -> None:
    """0.049 BTC at 10x takes 313.649 USDT: 0.98 of 320.05 exactly."""
    result = judge(leg(qty=D(qty)), figures=figures(available_margin=D("320.05")))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("leverage", "R6", "above_limit")]


@pytest.mark.parametrize("available", ["-0.01", "-1000"])
def test_a_negative_available_margin_fails_closed_not_as_a_validation_error(
    available: str,
) -> None:
    """A margin deficit is a figure the route reads, validated as such: no room, refused."""
    negative = AccountFigures.model_validate(
        {**FIGURES.model_dump(), "available_margin": available}
    )
    assert refused(judge(figures=negative)) == [("leverage", "R6", "above_limit")]


# --- R7: every other cap the guard reads, and the order defaults ---------------------------------


@pytest.mark.parametrize(
    ("figure", "field", "cap"),
    [
        ("open_positions_after", "max_open_positions", 3),
        ("open_orders_after", "max_concurrent_orders", 5),
        ("orders_in_minute_after", "max_orders_per_minute", 60),
    ],
)
def test_count_caps_boundary(figure: str, field: str, cap: int) -> None:
    admitted(judge(figures=figures(**{figure: cap})))
    assert refused(judge(figures=figures(**{figure: cap + 1}))) == [(field, "R7", "above_limit")]


def test_slippage_above_the_effective_tolerance_is_refused() -> None:
    assert refused(judge(leg(slippage_tolerance_bps=6))) == [
        ("slippage_tolerance_bps", "R7", "above_limit")
    ]
    assert refused(judge(alternate=alternate(slippage_tolerance_bps=4))) == [
        ("slippage_tolerance_bps", "R7", "above_limit")
    ]


@pytest.mark.parametrize(
    ("bound_tif", "leg_tif", "ok"),
    [("IOC", "FOK", True), ("IOC", "GTC", False), ("GTC", "PostOnly", True), ("FOK", "IOC", True)],
)
def test_time_in_force_rests_no_longer_than_the_bound(
    bound_tif: str, leg_tif: str, ok: bool
) -> None:
    result = judge(leg(time_in_force=leg_tif), bound=profile(time_in_force_default=bound_tif))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("time_in_force_default", "narrow_only", "above_limit")]


def test_reduce_only_may_be_set_never_cleared() -> None:
    admitted(judge(leg(reduce_only=True)))
    assert refused(judge(bound=profile(reduce_only_default=True))) == [
        ("reduce_only_default", "narrow_only", "changed")
    ]


def test_take_profit_no_further_than_the_bound_s_and_never_removed() -> None:
    admitted(judge(leg(take_profit_price=D("65000.0"))))
    admitted(judge(leg(take_profit_price=D("65000.0")), baseline=leg(take_profit_price=None)))
    assert refused(judge(leg(take_profit_price=D("65290.3")))) == [
        ("tp_offset_value", "narrow_only", "further_than_bound")
    ]
    assert refused(judge(leg(take_profit_price=None))) == [
        ("tp_offset_value", "narrow_only", "removed")
    ]
    assert refused(judge(leg(take_profit_price=D("64000.0")))) == [
        ("tp_offset_value", "narrow_only", "wrong_side")
    ]


# --- symbols (rows 37 to 39) ---------------------------------------------------------------------


def test_an_empty_allow_list_allows_nothing() -> None:
    nothing = alternate(allowed_symbols=[])
    assert refused(judge(alternate=nothing)) == [
        ("allowed_symbols", "narrow_only", "symbol_not_allowed")
    ]


def test_an_all_symbols_alternate_adds_nothing_and_its_deny_list_joins() -> None:
    every = alternate(allowed_symbols=[], all_symbols=True)
    other = BTCUSDT.model_copy(update={"symbol": "ETHUSDT"})
    assert refused(judge(leg(symbol="ETHUSDT"), baseline=leg(symbol="ETHUSDT"),
                         instrument=other, alternate=every)) == [
        ("allowed_symbols", "narrow_only", "symbol_not_allowed")
    ]  # fmt: skip
    assert refused(judge(alternate=alternate(denied_symbols=["*USDT"]))) == [
        ("denied_symbols", "narrow_only", "symbol_denied")
    ]


def test_an_instrument_for_another_symbol_fails_closed() -> None:
    other = BTCUSDT.model_copy(update={"symbol": "ETHUSDT"})
    assert refused(judge(instrument=other)) == [("allowed_symbols", "narrow_only", "inconsistent")]


# --- R8: the first native stop covers the full quantity ------------------------------------------


@pytest.mark.parametrize(
    ("mode", "stop_qty"), [("Partial", None), ("Full", None), ("Partial", "0.1")]
)
def test_the_admitted_stop_covers_the_full_quantity(mode: str, stop_qty: str | None) -> None:
    resulting = leg(tpsl_mode=mode, stop_qty=None if stop_qty is None else D(stop_qty))
    assert admitted(judge(resulting)).leg.stop_qty == D("0.1")


@pytest.mark.parametrize("stop_qty", ["0.05", "0.099", "0.2"])
def test_a_caller_stop_size_other_than_the_quantity_is_refused(stop_qty: str) -> None:
    """Rule 8 is never a silent rewrite: a stop sized short of (or past) the leg is refused."""
    resulting = leg(tpsl_mode="Partial", stop_qty=D(stop_qty))
    assert refused(judge(resulting)) == [("require_native_sl", "never", "inconsistent")]


# --- inputs the comparator cannot know: unknown is refused, never zero room or no limit ---------


@pytest.mark.parametrize(
    ("figure", "expected"),
    [
        ("available_margin", ("leverage", "R6", "unknown_input")),
        ("committed_risk", ("max_daily_loss", "R2", "unknown_input")),
        ("realised_loss_today", ("max_daily_loss", "R2", "unknown_input")),
        ("maintenance_margin_rate", ("leverage", "R3", "unknown_input")),
        ("open_positions_after", ("max_open_positions", "R7", "unknown_input")),
        ("open_orders_after", ("max_concurrent_orders", "R7", "unknown_input")),
        ("orders_in_minute_after", ("max_orders_per_minute", "R7", "unknown_input")),
    ],
)
def test_an_unknown_input_fails_closed(figure: str, expected: tuple[str, str, str]) -> None:
    result = judge(figures=figures(**{figure: None}))
    assert refused(result) == [expected]
    (violation,) = violations(result)
    assert violation.input == figure


def test_an_unknown_fee_rate_fails_the_risk_and_the_liquidation_rules() -> None:
    result = judge(figures=figures(taker_fee_rate=None))
    assert refused(result) == [
        ("max_daily_loss", "R2", "unknown_input"),
        ("leverage", "R3", "unknown_input"),
    ]
    assert {v.input for v in violations(result)} == {"taker_fee_rate"}


def test_unknown_equity_fails_every_rule_that_reads_it() -> None:
    assert refused(judge(figures=figures(equity=None))) == [
        ("max_position_pct_equity", "R1", "unknown_input")
    ]


def test_a_refusal_names_every_violated_field_at_once() -> None:
    wide = leg(qty=D("0.4"), leverage=D("12"), stop_price=D("63000.0"), time_in_force="GTC")
    assert [f for f, _, _ in refused(judge(wide))] == [
        "max_position_notional",
        "max_leverage_cap",
        "sl_offset_value",
        "time_in_force_default",
    ]


# --- fail-closed edges: a cap with no value on either side, unknown figures, grids --------------


def _bare(**cleared: None) -> AccountProfile:
    """B with caps cleared past the model's own rule (a drifted row): never read as "no cap"."""
    return BOUND.model_copy(update=cleared)


@pytest.mark.parametrize(
    ("cleared", "expected"),
    [
        ({"max_daily_loss": None}, ("max_daily_loss", "R2", "no_cap")),
        ({"max_leverage_cap": None}, ("max_leverage_cap", "R3", "no_cap")),
        ({"max_open_positions": None}, ("max_open_positions", "R7", "no_cap")),
    ],
)
def test_a_cap_with_no_value_on_either_side_fails_closed(
    cleared: dict[str, None], expected: tuple[str, str, str]
) -> None:
    assert refused(judge(bound=_bare(**cleared))) == [expected]


def test_a_daily_loss_pct_with_unknown_equity_fails_closed() -> None:
    result = judge(bound=profile(max_daily_loss_pct="0.01"), figures=figures(equity=None))
    assert refused(result) == [
        ("max_position_pct_equity", "R1", "unknown_input"),
        ("max_daily_loss_pct", "R2", "unknown_input"),
    ]


def test_a_requested_pct_budget_is_resolved_against_equity() -> None:
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="100")
    body = {"sizing": {"mode": "risk_based", "risk_per_trade_pct": "0.0011"}}  # 110 of 100000
    asked = (LegOverrides.model_validate(body),)
    assert refused(judge(bound=risk, requested=asked)) == [
        ("risk_pct_equity", "narrow_only", "above_limit")
    ]
    assert refused(judge(bound=risk, requested=asked, figures=figures(equity=None))) == [
        ("max_position_pct_equity", "R1", "unknown_input"),
        ("risk_pct_equity", "narrow_only", "unknown_input"),
    ]


def test_a_request_of_another_mode_is_judged_only_through_r() -> None:
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="100")
    other = LegOverrides.model_validate({"sizing": {"mode": "fixed_qty", "qty": "0.1"}})
    admitted(judge(bound=risk, requested=(other,)))


def test_a_take_profit_off_the_tick_grid_is_refused() -> None:
    assert refused(judge(leg(take_profit_price=D("65000.05")))) == [
        ("tp_offset_value", "narrow_only", "not_on_grid")
    ]


def test_a_quantity_below_the_instrument_minimum_is_refused() -> None:
    larger = BTCUSDT.model_copy(update={"min_order_qty": D("0.2")})
    assert refused(judge(instrument=larger)) == [("min_leg_notional", "R5", "below_minimum")]


def test_an_already_validated_layer_passes_through_and_a_list_is_refused() -> None:
    layer = LegOverrides(leverage=D("5"))
    assert LegOverrides.model_validate(layer) == layer
    with pytest.raises(ValidationError):
        LegOverrides.model_validate(["leverage", "5"])


def test_a_violation_names_only_a_field_of_the_table() -> None:
    with pytest.raises(ValidationError):
        Violation(field="max_consecutive_losses", rule="R7", reason="above_limit")


# --- every errors[] entry names its limit and the requested value ------------------------------

_RISK_100 = {"sizing_mode": "risk_based", "fixed_qty": None, "risk_fixed_amount": "100"}
_WIDE = {"max_leverage_cap": "100"}
_SHORT = {"side": "sell", "stop_price": D("64650.1"), "take_profit_price": D("62729.8")}
_ENTRIES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("pct_cap", {"leg": {"qty": D("0.25")}, "figures": {"equity": D("32004.99")}},
     {"field": "max_position_pct_equity", "limit": D("16002.495"), "requested": D("16002.5")}),
    ("budget", {"bound": _RISK_100, "requested": {"risk_per_trade_usd": "100.01"}},
     {"field": "risk_fixed_amount", "limit": D("100"), "requested": D("100.01")}),
    ("leverage_cap", {"leg": {"leverage": D("12")}},
     {"field": "max_leverage_cap", "limit": D("10"), "requested": D("12")}),
    ("instrument_max", {"leg": {"leverage": D("30")}, "bound": _WIDE, "max_leverage": D("25")},
     {"field": "leverage", "reason": "above_limit", "limit": D("25"), "requested": D("30")}),
    ("liquidation_long", {"leg": {"leverage": D("80")}, "bound": _WIDE,
                          "figures": {"maintenance_margin_rate": D("0.01")}},
     {"field": "leverage", "limit": D("63919.68189"), "requested": D("63369.9")}),
    ("liquidation_short", {"leg": {**_SHORT, "leverage": D("80")}, "baseline": _SHORT,
                           "bound": _WIDE, "figures": {"maintenance_margin_rate": D("0.01")}},
     {"field": "leverage", "limit": D("64098.90989"), "requested": D("64650.1")}),
    ("stop_wrong_side", {"leg": {"stop_price": D("64010")}},
     {"field": "sl_offset_value", "limit": D("64010"), "requested": D("64010")}),
    ("stop_further", {"leg": {"stop_price": D("63369.8")}},
     {"field": "sl_offset_value", "limit": D("63369.9"), "requested": D("63369.8")}),
    ("stop_off_grid", {"leg": {"stop_price": D("63369.95")}},
     {"field": "sl_offset_value", "limit": None, "requested": D("63369.95")}),
    ("tp_wrong_side", {"leg": {"take_profit_price": D("64000.0")}},
     {"field": "tp_offset_value", "limit": D("64010"), "requested": D("64000.0")}),
    ("tp_further", {"leg": {"take_profit_price": D("65290.3")}},
     {"field": "tp_offset_value", "limit": D("65290.2"), "requested": D("65290.3")}),
    ("tp_off_grid", {"leg": {"take_profit_price": D("65000.05")}},
     {"field": "tp_offset_value", "limit": None, "requested": D("65000.05")}),
    ("qty_off_grid", {"leg": {"qty": D("0.1005")}},
     {"field": "qty_rounding", "limit": None, "requested": D("0.1005")}),
    ("min_qty", {"max_qty": D("0.2")},
     {"field": "min_leg_notional", "limit": D("0.2"), "requested": D("0.1")}),
    ("min_notional", {"leg": {"qty": D("0.099")}, "bound": {"min_leg_notional": "6401"}},
     {"field": "min_leg_notional", "limit": D("6401"), "requested": D("6336.990")}),
    ("rounded_up_qty", {"leg": {"qty": D("0.001")}, "requested": {"qty": "0.0005"}},
     {"field": "fixed_qty", "limit": D("0.0005"), "requested": D("0.001")}),
    ("rounded_up_notional", {"requested": {"notional_usd": "6400"}},
     {"field": "fixed_notional", "limit": D("6400"), "requested": D("6401")}),
    ("margin", {"leg": {"qty": D("0.05")}, "figures": {"available_margin": D("320.05")}},
     {"field": "leverage", "limit": D("313.649"), "requested": D("320.05")}),
    ("open_positions", {"figures": {"open_positions_after": 4}},
     {"field": "max_open_positions", "limit": D("3"), "requested": D("4")}),
    ("slippage", {"leg": {"slippage_tolerance_bps": 6}},
     {"field": "slippage_tolerance_bps", "limit": D("5"), "requested": D("6")}),
]  # fmt: skip


def _entry_case(args: dict[str, Any]) -> list[Any]:
    asked = args.get("requested")
    if asked is not None:
        mode = "risk_based" if "risk_per_trade_usd" in asked else (
            "fixed_qty" if "qty" in asked else "fixed_notional")  # fmt: skip
        asked = (LegOverrides.model_validate({"sizing": {"mode": mode, **asked}}),)
    instrument = BTCUSDT
    if "max_leverage" in args:
        instrument = BTCUSDT.model_copy(update={"max_leverage": args["max_leverage"]})
    if "max_qty" in args:
        instrument = BTCUSDT.model_copy(update={"min_order_qty": args["max_qty"]})
    return list(
        violations(
            judge(
                leg(**args.get("leg", {})),
                bound=profile(**args.get("bound", {})),
                baseline=leg(**args.get("baseline", {})),
                instrument=instrument,
                figures=figures(**args.get("figures", {})),
                requested=asked or (),
            )
        )
    )


@pytest.mark.parametrize(
    ("args", "expected"), [e[1:] for e in _ENTRIES], ids=[e[0] for e in _ENTRIES]
)
def test_each_entry_names_its_limit_and_the_requested_value(
    args: dict[str, Any], expected: dict[str, Any]
) -> None:
    (entry,) = [v for v in _entry_case(args) if v.field == expected["field"]]
    assert {key: getattr(entry, key) for key in expected} == expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"figures": {"equity": None}}, ("max_position_pct_equity", "equity")),
        ({"bound": {"max_daily_loss_pct": "0.01"}, "figures": {"equity": None}},
         ("max_daily_loss_pct", "equity")),
        ({"bound": {"sizing_mode": "risk_based", "fixed_qty": None, "risk_pct_equity": "0.01"},
          "figures": {"equity": None}}, ("risk_pct_equity", "equity")),
    ],
)  # fmt: skip
def test_an_unknown_input_entry_names_the_input(
    args: dict[str, Any], expected: tuple[str, str]
) -> None:
    named = {(v.field, v.input) for v in _entry_case(args) if v.reason == "unknown_input"}
    assert expected in named


# --- edges the mutation run found: hedge mode, equal values, precision, labels -----------------


@pytest.mark.parametrize(
    ("side", "idx", "ok"),
    [("buy", 1, True), ("buy", 2, False), ("sell", 2, True), ("sell", 1, False)],
)
def test_hedge_mode_takes_the_side_s_own_position_index(side: str, idx: int, ok: bool) -> None:
    hedge = profile(position_mode="hedge")
    sided = {"side": side, "position_mode": "hedge", "position_idx": idx}
    if side == "sell":
        sided |= _SHORT
    result = judge(leg(**sided), bound=hedge, baseline=leg(**sided))
    if ok:
        admitted(result)
    else:
        assert refused(result) == [("position_mode", "never", "changed")]


def test_a_position_cap_in_one_unit_alone_bounds_the_leg() -> None:
    admitted(judge(bound=profile(max_position_pct_equity=None)))
    admitted(judge(bound=profile(max_daily_loss_pct="0.01")))  # 1000 USDT: the 500 cap binds


def test_a_budget_equal_to_the_headroom_is_named_as_the_headroom() -> None:
    """Budget 100 and headroom 100 (500 less 400 committed): the daily cap names the refusal of
    0.15 BTC, which risks 96.015 + 10.56165 = 106.57665 USDT."""
    result = judge(
        leg(qty=D("0.15")), bound=profile(**_RISK_100), figures=figures(committed_risk=D("400"))
    )
    assert refused(result) == [("max_daily_loss", "R2", "above_limit")]


def test_a_pct_based_bound_budget_still_bounds_a_requested_one() -> None:
    risk = profile(sizing_mode="risk_based", fixed_qty=None, risk_pct_equity="0.001")  # 100
    body = {"sizing": {"mode": "risk_based", "risk_per_trade_usd": "150"}}
    assert refused(judge(bound=risk, requested=(LegOverrides.model_validate(body),))) == [
        ("risk_fixed_amount", "narrow_only", "above_limit")
    ]


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_a_baseline_stop_at_entry_fails_closed(side: str) -> None:
    sided = {"side": side} | (_SHORT if side == "sell" else {})
    assert refused(judge(leg(**sided), baseline=leg(**sided | {"stop_price": D("64010")}))) == [
        ("sl_offset_value", "R4", "inconsistent")
    ]


def test_a_short_stop_at_entry_and_take_profits_at_entry_are_refused() -> None:
    assert refused(judge(leg(**_SHORT | {"stop_price": D("64010")}), baseline=leg(**_SHORT))) == [
        ("sl_offset_value", "R4", "wrong_side")
    ]
    assert refused(judge(leg(take_profit_price=D("64010")))) == [
        ("tp_offset_value", "narrow_only", "wrong_side")
    ]
    short_tp = leg(**_SHORT | {"take_profit_price": D("64010")})
    assert refused(judge(short_tp, baseline=leg(**_SHORT))) == [
        ("tp_offset_value", "narrow_only", "wrong_side")
    ]


def test_no_take_profit_on_either_leg_is_admitted() -> None:
    admitted(judge(leg(take_profit_price=None), baseline=leg(take_profit_price=None)))


def test_a_requested_notional_met_exactly_is_admitted() -> None:
    body = {"sizing": {"mode": "fixed_notional", "notional_usd": "6401"}}
    admitted(judge(requested=(LegOverrides.model_validate(body),)))


def test_a_one_in_10_to_the_27_overrun_is_refused_at_full_precision() -> None:
    """28 digits would round 71.0511 - 1E-27 back to 71.0511 and admit the leg."""
    tight = figures(committed_risk=D("1E-27"))
    result = judge(bound=profile(max_daily_loss="71.0511"), figures=tight)
    (violation,) = violations(result)
    assert violation.limit == D("71.051099999999999999999999999")


def test_the_table_classes_a_named_field_by_its_row() -> None:
    assert override_class("leverage") == "narrow_only"
    assert override_class("margin_mode") == "never"


def test_not_found_says_nothing_of_which() -> None:
    assert str(ProfileNotFound()) == "profile not found"


def test_a_requested_pct_budget_with_unknown_equity_names_the_input() -> None:
    body = {"sizing": {"mode": "risk_based", "risk_per_trade_pct": "0.001"}}
    result = judge(
        bound=profile(**_RISK_100),
        requested=(LegOverrides.model_validate(body),),
        figures=figures(equity=None),
    )
    assert ("risk_pct_equity", "equity") in {(v.field, v.input) for v in violations(result)}


# --- OPEN-5: the instrument's maximum order quantity, under R7 (ruled 2026-10-25) -------------

_ROOMY: dict[str, Any] = {
    "max_position_notional": "1000000000",
    "max_position_pct_equity": None,
    "max_daily_loss": "1000000000",
}


@pytest.mark.parametrize(("qty", "ok"), [("100", True), ("100.001", False)])
def test_a_leg_above_the_instrument_maximum_quantity_is_refused(qty: str, ok: bool) -> None:
    assert BTCUSDT.max_order_qty == D("100")
    result = judge(
        leg(qty=D(qty)),
        bound=profile(**_ROOMY),
        figures=figures(available_margin=D("1000000000")),
    )
    if ok:
        admitted(result)
        return
    assert refused(result) == [("fixed_qty", "R7", "above_limit")]
    (violation,) = violations(result)
    assert (violation.limit, violation.requested) == (BTCUSDT.max_order_qty, D(qty))


@pytest.mark.parametrize(("qty", "ok"), [("100", True), ("100.001", False)])
def test_a_requested_quantity_above_the_instrument_maximum_is_refused(qty: str, ok: bool) -> None:
    """The sizer may clamp the leg, but a request for more than the exchange takes is refused."""
    layer = LegOverrides.model_validate({"sizing": {"mode": "fixed_qty", "qty": qty}})
    result = judge(requested=(layer,))
    if ok:
        admitted(result)
        return
    assert refused(result) == [("fixed_qty", "R7", "above_limit")]
    (violation,) = violations(result)
    assert (violation.limit, violation.requested) == (BTCUSDT.max_order_qty, D(qty))
