"""E39-T01 (#881) slice 1: the pure evaluator's decision table, check order and Gherkin 1, 2, 4.

Threat-model ids (`docs/security/threat-models/E39-risk-killswitch.md`): SR-E39-02 (the exemption
by effect, fail-closed refusals included) and SR-E39-03 (a policy warn never softens a block).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import localcontext
from typing import Any

import pytest

from candleviewer.risk.caps import ManagerCaps, ResolvedCaps
from candleviewer.risk.evaluator import CHECK_ORDER, RiskWarning, evaluate
from candleviewer.risk.models import RiskRefusal
from tests.unit.risk._risk_builders import NOW, D, caps, close_order, figures, order, run

# cap: (layer, limit, figure, values at {under, at, over}, measured). A projected cap admits an
# order that lands exactly on it; a measured cap refuses at the limit. "BTC"/"ETH" set that symbol's
# held notional (the order adds 10 000 of BTCUSDT); "drawdown" falls from a 2 000 day peak.
_TABLE: dict[str, tuple[str, int, str, tuple[int, int, int], bool]] = {
    "max_orders_per_minute": ("prof", 5, "orders_last_minute", (3, 4, 5), False),
    "max_concurrent_orders": ("prof", 5, "open_orders", (3, 4, 5), False),
    "max_open_positions": ("prof", 5, "open_positions", (3, 4, 5), False),
    "max_position_notional_usd": ("prof", 25_000, "BTC", (10_000, 15_000, 20_000), False),
    "max_total_notional_usd": ("pol", 50_000, "ETH", (30_000, 40_000, 50_000), False),
    "max_position_pct_equity": ("prof", 20, "BTC", (1, 10_000, 15_000), False),
    "per_symbol_concentration_pct": ("pol", 2, "BTC", (1, 10_000, 15_000), False),
    "max_leverage": ("pol", 2, "ETH", (180_000, 190_000, 195_000), False),
    "max_daily_loss_usd": ("pol", 1000, "daily_figure", (-500, -1000, -1500), True),
    "max_daily_loss_pct": ("prof", 1, "daily_figure", (-500, -1000, -1500), True),
    "max_drawdown_pct": ("pol", 1, "drawdown", (500, 1000, 1500), True),
    "max_consecutive_losses": ("prof", 3, "consecutive_losses", (2, 3, 4), True),
}


# cap: the refusal's reported figure at "over", and the projected one its message names.
_REPORTED: dict[str, tuple[str, str | None]] = {
    "max_orders_per_minute": ("5", "6"),
    "max_concurrent_orders": ("5", "6"),
    "max_open_positions": ("5", "6"),
    "max_position_notional_usd": ("20000", "30000"),
    "max_total_notional_usd": ("50000", "60000"),
    "max_position_pct_equity": ("15", "25"),
    "per_symbol_concentration_pct": ("1.5", "2.5"),
    "max_leverage": ("1.95", "2.05"),
    "max_daily_loss_usd": ("1500", None),
    "max_daily_loss_pct": ("1.5", None),
    "max_drawdown_pct": ("1.5", None),
    "max_consecutive_losses": ("4", None),
}


def _row(figure: str, value: int) -> dict[str, Any]:
    if figure in ("BTC", "ETH"):
        return {"symbol_notional": {f"{figure}USDT": D(value)}}
    if figure == "drawdown":
        return {"day_peak_figure": D(2000), "daily_figure": D(2000 - value)}
    return {figure: D(value) if figure == "daily_figure" else value}


@pytest.mark.parametrize("state", [0, 1, 2], ids=["under", "at", "over"])
@pytest.mark.parametrize("cap", sorted(_TABLE))
@pytest.mark.parametrize("reduce_only", [False, True], ids=["opening", "reduce_only"])
def test_evaluate_decision_table(cap: str, state: int, reduce_only: bool) -> None:
    layer, limit, figure, values, measured = _TABLE[cap]
    limits = {cap: D(limit)}
    resolved = caps(pol=limits) if layer == "pol" else caps(prof=limits)
    o = close_order() if reduce_only else order()
    decision = run(o, figures(**_row(figure, values[state])), resolved).decision
    refused = state == 2 or (state == 1 and measured)
    if reduce_only or not refused:
        assert decision.allowed, decision.message
        return
    assert decision.code is RiskRefusal.RISK_LIMIT_BREACHED
    assert (decision.cap, decision.limit) == (cap, D(limit))
    if state == 2:
        actual, after = _REPORTED[cap]
        assert decision.actual == D(actual)
        assert (f"after this order {after})" in decision.message) is (after is not None)
        assert after is not None or "after this order" not in decision.message


def test_evaluate_position_cap_names_cap_limit_and_current_value() -> None:  # Gherkin 1
    f = figures(symbol_notional={"BTCUSDT": D(20_000)})
    decision = run(
        order(notional=D(10_000)), f, caps(prof={"max_position_notional_usd": 25_000})
    ).decision
    assert not decision.allowed and decision.code is RiskRefusal.RISK_LIMIT_BREACHED
    assert (decision.cap, decision.limit, decision.actual) == (
        "max_position_notional_usd",
        D(25_000),
        D(20_000),
    )
    assert decision.message == (
        "would exceed max_position_notional_usd 25000 (current 20000, after this order 30000), "
        "set by the account profile"
    )


# check cap: (layer, field, failing value, passing value); together the failing values fail every
# check at once, and each passing value clears exactly its own check.
_STEPS: tuple[tuple[str, str, str, Any, Any], ...] = (
    ("allowed_symbols", "prof", "all_symbols", False, True),
    ("kill_switch", "fig", "kill_switch_engaged", True, False),
    ("lockout", "fig", "lockout_active", True, False),
    ("risk_state", "fig", "as_of", NOW - timedelta(seconds=11), NOW),
    ("max_orders_per_minute", "fig", "orders_last_minute", 600, 0),
    ("max_concurrent_orders", "fig", "open_orders", 9, 0),
    ("max_open_positions", "fig", "open_positions", 9, 0),
    ("max_position_notional_usd", "prof", "max_position_notional_usd", D(5000), None),
    ("max_total_notional_usd", "pol", "max_total_notional_usd", D(5000), D(1_000_000)),
    ("max_position_pct_equity", "prof", "max_position_pct_equity", D(1), None),
    ("per_symbol_concentration_pct", "pol", "per_symbol_concentration_pct", D("0.5"), D(100)),
    ("max_leverage", "pol", "max_leverage", D("0.05"), D(100)),
    ("max_daily_loss_usd", "pol", "max_daily_loss_usd", D(1000), D(10_000)),
    ("max_daily_loss_pct", "prof", "max_daily_loss_pct", D(1), None),
    ("max_drawdown_pct", "pol", "max_drawdown_pct", D(1), D(50)),
    ("max_consecutive_losses", "prof", "max_consecutive_losses", 3, None),
)


def _all_failing() -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {"pol": {}, "prof": {}, "fig": {}}
    for _, part, key, bad, _ in _STEPS:
        state[part][key] = bad
    state["prof"].update(max_orders_per_minute=5, max_concurrent_orders=5, max_open_positions=5)
    state["fig"].update(daily_figure=D(-2000), consecutive_losses=5)
    return state


def test_evaluate_runs_checks_in_the_documented_order() -> None:
    state, seen = _all_failing(), []
    for _ in range(len(_STEPS) + 1):
        decision = run(order(), figures(**state["fig"]), caps(state["pol"], state["prof"])).decision
        if decision.allowed:
            break
        assert decision.cap is not None
        seen.append("symbol" if decision.cap == "allowed_symbols" else decision.cap)
        _, part, key, _, good = next(step for step in _STEPS if step[0] == decision.cap)
        state[part][key] = good
    assert tuple(seen) == CHECK_ORDER


def test_evaluate_reduce_only_close_passes_lockout_and_every_cap() -> None:  # Gherkin 2
    state = _all_failing()
    state["prof"]["blocked_symbols"] = frozenset({"BTCUSDT"})
    f, c = figures(**state["fig"]), caps(state["pol"], state["prof"], ManagerCaps(D(1)))
    assert not run(order(), f, c).decision.allowed
    assert run(close_order(), f, c).decision.allowed


@pytest.mark.parametrize(
    "effect",
    [
        {"opens_exposure": True, "opens_position": True},  # a flip through flat
        {"opens_exposure": True, "opens_position": False},
        {"opens_exposure": False, "opens_position": True},  # inconsistent effect: not exempt
    ],
)
def test_a_reverse_counts_as_opening(effect: dict[str, bool]) -> None:  # SR-E39-02
    o = order(reduce_only=True, **effect)
    assert not o.exempt
    assert run(o, figures(kill_switch_engaged=True)).decision.code is RiskRefusal.TRADING_DISABLED


@pytest.mark.parametrize(
    "fields",
    [
        {"as_of": NOW - timedelta(seconds=10, microseconds=1)},
        {"as_of": NOW + timedelta(microseconds=1)},
        {"equity": None},
        {"equity": D(0)},
        {"day_start_equity": None},
        {"day_start_equity": D(-1)},
        {"day_start_equity": D(0)},
        {"day_start_equity": D("-0")},
    ],
)
def test_stale_state_refuses_entries_but_not_closes(fields: dict[str, Any]) -> None:  # SR-E39-02
    decision = run(order(), figures(**fields)).decision
    assert (decision.allowed, decision.code) == (False, RiskRefusal.RISK_STATE_UNAVAILABLE)
    assert run(close_order(), figures(**fields)).decision.allowed


def test_evaluate_state_exactly_at_max_age_is_fresh() -> None:
    assert run(f=figures(as_of=NOW - timedelta(seconds=10))).decision.allowed


@pytest.mark.parametrize(
    ("prof", "cap"),
    [
        ({"all_symbols": False, "allowed_symbols": frozenset({"ETHUSDT"})}, "allowed_symbols"),
        ({"blocked_symbols": frozenset({"BTCUSDT"})}, "blocked_symbols"),
    ],
)
def test_evaluate_symbol_rule_refuses(prof: dict[str, Any], cap: str) -> None:
    decision = run(c=caps(prof=prof)).decision
    assert (decision.code, decision.cap, decision.limit) == (
        RiskRefusal.SYMBOL_NOT_ALLOWED,
        cap,
        None,
    )


def test_evaluate_allow_list_admits_a_listed_symbol() -> None:
    prof = {"all_symbols": False, "allowed_symbols": frozenset({"BTCUSDT"})}
    assert run(c=caps(prof=prof)).decision.allowed


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"kill_switch_engaged": True}, RiskRefusal.TRADING_DISABLED),
        ({"lockout_active": True}, RiskRefusal.ACCOUNT_LOCKED),
    ],
)
def test_evaluate_kill_switch_and_lockout_refuse(fields: dict[str, Any], code: RiskRefusal) -> None:
    assert run(f=figures(**fields)).decision.code is code


def test_evaluate_adding_to_a_held_symbol_opens_no_new_position() -> None:
    f = figures(open_positions=5, symbol_notional={"BTCUSDT": D(1)})
    c = caps(prof={"max_open_positions": 5})
    assert run(order(opens_position=False), f, c).decision.allowed
    # A hedge-mode second side on a held symbol is a new position: the OMS's effect says so.
    assert run(order(opens_position=True), f, c).decision.cap == "max_open_positions"


def test_evaluate_policy_warn_admits_and_records_a_warning() -> None:
    c = caps(
        pol={"max_daily_loss_usd": D(1000), "breach_behaviour": {"max_daily_loss_usd": "warn"}}
    )
    result = run(f=figures(daily_figure=D(-1500)), c=c)
    assert result.decision.allowed
    assert result.warnings == (RiskWarning("max_daily_loss_usd", D(1000), D(1500)),)
    # A later block keeps the warning beside the refusal.
    admitted = run(f=figures(daily_figure=D(-1500), consecutive_losses=9), c=c)
    assert admitted.decision.allowed  # no consecutive-loss cap is set at any layer
    c3 = caps(
        pol={"max_daily_loss_usd": D(1000), "breach_behaviour": {"max_daily_loss_usd": "warn"}},
        prof={"max_consecutive_losses": 3},
    )
    refused = run(f=figures(daily_figure=D(-1500), consecutive_losses=9), c=c3)
    assert refused.decision.cap == "max_consecutive_losses" and len(refused.warnings) == 1


@pytest.mark.parametrize("behaviour", ["block", "flatten"])
def test_evaluate_block_and_flatten_refuse(behaviour: str) -> None:
    c = caps(
        pol={"max_daily_loss_usd": D(1000), "breach_behaviour": {"max_daily_loss_usd": behaviour}}
    )
    assert run(f=figures(daily_figure=D(-1500)), c=c).decision.cap == "max_daily_loss_usd"


def test_evaluate_policy_warn_never_softens_a_tighter_profile_limit() -> None:
    c = caps(
        pol={"max_daily_loss_usd": D(1000), "breach_behaviour": {"max_daily_loss_usd": "warn"}},
        prof={"max_daily_loss_usd": D(900)},
    )
    assert run(f=figures(daily_figure=D(-950)), c=c).decision.cap == "max_daily_loss_usd"


def test_evaluate_warn_only_aggregate_cap_is_no_concentration_base() -> None:  # BQ addendum 2
    pol = {
        "max_total_notional_usd": D(1000),
        "breach_behaviour": {"max_total_notional_usd": "warn"},
        "per_symbol_concentration_pct": D(50),
    }
    decision = run(order(notional=D(400)), c=caps(pol=pol)).decision  # 40 % of the warn total
    assert decision.cap == "per_symbol_concentration_pct" and not decision.allowed
    assert "cannot be measured" in decision.message


def test_evaluate_unheld_symbol_counts_as_opening_even_if_the_order_says_not() -> None:
    f = figures(open_positions=5)
    c = caps(prof={"max_open_positions": 5})
    assert run(order(opens_position=False), f, c).decision.cap == "max_open_positions"


def test_evaluate_zero_aggregate_cap_refuses_before_concentration() -> None:
    decision = run(c=caps(pol={"max_total_notional_usd": D(0)})).decision
    assert decision.cap == "max_total_notional_usd"


def test_evaluate_zero_aggregate_cap_admits_an_order_adding_no_exposure() -> None:
    o = order(notional=D(0), opens_exposure=False)  # not reduce-only, so judged: no 0 / 0 share
    assert run(o, c=caps(pol={"max_total_notional_usd": D(0)})).decision.allowed


def test_evaluate_message_falls_back_for_a_figure_too_wide_for_plain_form() -> None:
    decision = run(f=figures(daily_figure=D("-1E+70"))).decision
    assert decision.cap == "max_daily_loss_usd" and "1E+70" in decision.message


def test_evaluate_stamps_the_injected_time() -> None:
    assert run().decision.evaluated_at == NOW


def test_evaluate_with_no_limit_at_any_layer_admits() -> None:
    bare = ResolvedCaps(caps={}, symbols=caps().symbols)  # all symbols, no cap
    f = figures(daily_figure=D(-(10**9)), consecutive_losses=99, symbol_notional={"BTCUSDT": D(1)})
    assert run(order(notional=D(10**12)), f, bare).decision.allowed


def test_evaluate_aggregate_notional_sums_every_symbol() -> None:
    f = figures(symbol_notional={"ETHUSDT": D(20_000), "SOLUSDT": D(20_000)})
    decision = run(f=f, c=caps(pol={"max_total_notional_usd": D(45_000)})).decision
    assert (decision.cap, decision.actual) == ("max_total_notional_usd", D(40_000))


_WARN = "warn"
# cap, policy warn limit, (layer, its blocking limit), figures: the lens's B1 probes.
_WARN_PROBES: tuple[tuple[str, Any, tuple[str, Any], dict[str, Any]], ...] = (
    ("max_daily_loss_usd", D(1000), ("prof", D(1500)), {"daily_figure": D(-2000)}),
    ("max_daily_loss_usd", D(1000), ("mgr", D(1500)), {"daily_figure": D(-2000)}),
    ("max_open_positions", 2, ("prof", 3), {"open_positions": 10}),
    ("max_leverage", D(2), ("prof", D(3)), {"symbol_notional": {"ETHUSDT": D(990_000)}}),
)


@pytest.mark.parametrize(("cap", "warn_at", "block", "fig"), _WARN_PROBES)
def test_evaluate_policy_warn_never_disables_a_looser_blocking_limit(  # SR-E39-03
    cap: str, warn_at: Any, block: tuple[str, Any], fig: dict[str, Any]
) -> None:
    pol = {cap: warn_at, "breach_behaviour": {cap: _WARN}}
    layer, limit = block
    if layer == "mgr":
        c = caps(pol, mgr=ManagerCaps(limit))
    else:
        c = caps(pol, {"max_leverage_cap" if cap == "max_leverage" else cap: limit})
    result = run(f=figures(**fig), c=c)
    assert (result.decision.allowed, result.decision.cap) == (False, cap)
    assert result.decision.limit == limit
    # Under the blocking limit and over the warn threshold: admitted with one warning.
    under = {
        "daily_figure": D(-1200),
        "open_positions": 2,
        "symbol_notional": {"ETHUSDT": D(240_000)},
    }
    admitted = run(f=figures(**{k: under[k] for k in fig}), c=c)
    assert admitted.decision.allowed and [w.cap for w in admitted.warnings] == [cap]


def test_evaluate_concentration_without_an_aggregate_cap_refuses_closed() -> None:
    bare = ResolvedCaps(caps={}, symbols=caps().symbols)  # all symbols, no cap
    with_cap = caps(pol={"per_symbol_concentration_pct": D(1)})
    concentration = with_cap.caps["per_symbol_concentration_pct"]
    decision = run(c=replace(bare, caps={concentration.name: concentration})).decision
    assert (decision.allowed, decision.code, decision.cap) == (
        False,
        RiskRefusal.RISK_LIMIT_BREACHED,
        "per_symbol_concentration_pct",
    )
    assert "cannot be measured" in decision.message
    # A warn-only concentration with no base cannot block and is skipped.
    warn_only = replace(bare, warn_limits={concentration.name: concentration})
    assert run(c=warn_only).decision.allowed


@pytest.mark.parametrize(  # the measured figures clamp at 0: a gain day, a peak below the figure
    ("cap", "peak"), [("max_daily_loss_usd", 100), ("max_drawdown_pct", 0)]
)
def test_evaluate_zero_cap_refuses_a_measured_figure_clamped_at_zero(cap: str, peak: int) -> None:
    f = figures(daily_figure=D(100), day_peak_figure=D(peak))
    assert run(f=f, c=caps(pol={cap: D(0)})).decision.cap == cap


_MALFORMED: tuple[tuple[str, dict[str, Any]], ...] = (
    ("o", {"notional": D(-10_000)}),
    ("o", {"notional": D("-Infinity")}),
    ("o", {"notional": D("NaN")}),
    ("o", {"qty": D(-1)}),
    ("o", {"reference_price": D("sNaN")}),
    ("f", {"equity": D("Infinity")}),
    ("f", {"day_start_equity": D("NaN")}),
    ("f", {"daily_figure": D("-Infinity")}),
    ("f", {"day_peak_figure": D("NaN")}),
    ("f", {"symbol_notional": {"BTCUSDT": D(-50_000)}}),
    ("f", {"symbol_notional": {"ETHUSDT": D("Infinity")}}),
    ("f", {"orders_last_minute": -5}),
    ("f", {"open_orders": -1}),
    ("f", {"open_positions": -5}),
    ("f", {"consecutive_losses": -1}),
    ("f", {"as_of": datetime(2026, 11, 4, 12, 0)}),
    ("c", {"max_position_notional_usd": D("NaN")}),
    ("c", {"max_position_notional_usd": D(-1)}),
    # Finite but past +/-100 orders of magnitude: a ratio of them would overflow, not refuse.
    ("f", {"equity": D("1E-999999")}),
    ("o", {"notional": D("9E+999998")}),
    ("f", {"daily_figure": D("-1E+101")}),
    ("c", {"max_position_notional_usd": D("1E-101")}),
    # Priced: positive, notional never above qty at the price, positive when opening exposure.
    ("o", {"notional": D(0)}),
    ("o", {"qty": D(0), "notional": D(0), "reference_price": D(0), "opens_exposure": False}),
    ("o", {"qty": D("0.1"), "notional": D("10000.000000000000000001")}),
)


@pytest.mark.parametrize(("part", "fields"), _MALFORMED)
def test_evaluate_refuses_malformed_inputs_closed(part: str, fields: dict[str, Any]) -> None:
    o = order(**fields) if part == "o" else order()
    f = figures(**fields) if part == "f" else figures()
    c = caps(prof=fields) if part == "c" else caps()
    decision = run(o, f, c).decision
    assert (decision.allowed, decision.code) == (False, RiskRefusal.RISK_STATE_UNAVAILABLE)
    assert decision.message == "risk inputs are malformed"


def test_evaluate_refuses_a_malformed_warn_threshold() -> None:
    c = caps(pol={"max_leverage": D("NaN"), "breach_behaviour": {"max_leverage": _WARN}})
    assert run(c=c).decision.code is RiskRefusal.RISK_STATE_UNAVAILABLE


def test_evaluate_admits_figures_at_the_magnitude_bound() -> None:
    f = figures(equity=D("1E+100"), day_start_equity=D("1E+100"), day_peak_figure=D("1E-100"))
    assert run(f=f).decision.allowed


def test_evaluate_tz_naive_now_is_a_programmer_error() -> None:
    with pytest.raises(ValueError, match="injected clock"):
        evaluate(order(), figures(), caps(), now=datetime(2026, 11, 4, 12, 0))
    with pytest.raises(ValueError, match="injected clock"):
        evaluate(close_order(), figures(), caps(), now=datetime(2026, 11, 4, 12, 0))


def test_evaluate_compares_38_digit_figures_exactly() -> None:
    f = figures(symbol_notional={"BTCUSDT": D("1E+28")})
    c = caps(prof={"max_position_notional_usd": D("1E+28")})
    assert run(order(notional=D(5)), f, c).decision.cap == "max_position_notional_usd"
    # A ratio cap's cross-product: one part in 1E+36 over the limit is still over it.
    equity = D("12345678901234567890.123456789012345678")
    pct = figures(equity=equity)
    roomy = {"max_total_notional_usd": D(10**30), "max_leverage": D(10**6)}
    edge = caps(roomy, {"max_position_pct_equity": D("1.000001")})
    with localcontext() as ctx:
        ctx.prec = 80
        exact = equity * D("1.000001") / 100
        above = exact + D("1E-18")
    assert run(order(notional=exact), pct, edge).decision.allowed
    over = run(order(notional=above), pct, edge).decision
    assert over.cap == "max_position_pct_equity"


def test_evaluate_ratio_figures_are_reported_at_28_digits() -> None:
    f = figures(equity=D(3), day_start_equity=D(3), daily_figure=D(-2))
    c = caps({"max_leverage": D(10**6)}, {"max_daily_loss_pct": D(1)})
    decision = run(f=f, c=c).decision
    assert (decision.cap, decision.actual) == (
        "max_daily_loss_pct",
        D("66.66666666666666666666666667"),
    )


def test_evaluate_exempt_close_skips_malformed_figures() -> None:  # SR-E39-02
    assert run(close_order(), figures(equity=D("NaN"), open_orders=-1)).decision.allowed
