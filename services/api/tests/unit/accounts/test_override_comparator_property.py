"""No input ever widens (#2635 F-01; ADR-0040 (proposed, #4461) Decision 1; SR-E28-03, SR-E28-04).

For any bound profile B, any alternate A of its account, any request layers and any resulting leg
a resolver could hand over, adversarial ones included, the comparator either refuses the request
whole or admits a leg that is within every one of B's caps and A's: the check below restates
each cap plainly, from B and A alone, without the module's helpers. The examples are the shared
Hypothesis profile's (`tests/_hypothesis_profiles.py`: derandomized in CI).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypothesis import event, given, settings
from hypothesis import strategies as st

from candleviewer.accounts.override_comparator import (
    OVERRIDE_CLASS,
    AccountFigures,
    Admitted,
    LegOverrides,
    Refused,
    ResolvedLeg,
    judge_leg,
)
from candleviewer.accounts.profiles import AccountProfile, SymbolScope
from tests.unit.accounts._override_world import (
    ALTERNATE_ID,
    BASELINE_VALUES,
    BOUND_VALUES,
    BTCUSDT,
)

D = Decimal
REF = D("64010")
TICK, LOT = BTCUSDT.tick_size, BTCUSDT.qty_step
_RANK = {"FOK": 0, "IOC": 0, "GTC": 1, "PostOnly": 1}


def _money(low: int, high: int, places: int = 2) -> st.SearchStrategy[Decimal]:
    return st.integers(low * 10**places, high * 10**places).map(lambda n: D(n).scaleb(-places))


def _mostly[T](good: st.SearchStrategy[T], bad: st.SearchStrategy[T]) -> st.SearchStrategy[T]:
    """`good` about 15 times in 16, else `bad`: each value a resolver hands over is usually
    plausible and sometimes hostile, so the property sees admitted legs as well as refused ones.
    The hostile pick is a middle value: Hypothesis favours an integer range's ends."""
    return st.integers(0, 15).flatmap(lambda pick: bad if pick == 7 else good)


_FRACTION = st.integers(1, 10_000).map(lambda n: D(n).scaleb(-4))
_PLENTY = st.integers(1_000, 10_000).map(lambda n: D(n).scaleb(-4))
_BTC_ALLOWED = [
    {"all_symbols": False, "allowed_symbols": ["BTCUSDT"]},
    {"all_symbols": False, "allowed_symbols": ["*USDT"]},
    {"all_symbols": True, "allowed_symbols": []},
]
_SYMBOLS = _mostly(
    st.sampled_from(_BTC_ALLOWED),
    st.sampled_from(
        [
            {"all_symbols": False, "allowed_symbols": []},
            {"all_symbols": False, "allowed_symbols": ["ETHUSDT"]},
        ]
    ),
)
_ANY_TIF = st.sampled_from(sorted(_RANK))


@st.composite
def _profiles(draw: st.DrawFn, /, **identity: Any) -> AccountProfile:
    cap = draw(_mostly(_money(5, 100), _money(1, 100)))
    sizing: dict[str, Any] = draw(
        st.sampled_from(
            [
                {"sizing_mode": "fixed_qty", "fixed_qty": "0.1"},
                {"sizing_mode": "risk_based", "fixed_qty": None, "risk_fixed_amount": "50"},
                {"sizing_mode": "risk_based", "fixed_qty": None, "risk_pct_equity": "0.001"},
            ]
        )
    )
    return AccountProfile.model_validate(
        {
            **BOUND_VALUES,
            **identity,
            **sizing,
            **draw(_SYMBOLS),
            "denied_symbols": draw(
                _mostly(st.just([]), st.sampled_from([["BTCUSDT"], ["*USDT"], ["ETHUSDT"]]))
            ),
            "enabled": draw(_mostly(st.just(True), st.booleans())),
            "trading_enabled": draw(_mostly(st.just(True), st.booleans())),
            "leverage": str(min(cap, draw(_money(1, 100)))),
            "max_leverage_cap": str(cap),
            "max_position_notional": str(
                draw(_mostly(_money(10_000, 100_000), _money(10, 10_000)))
            ),
            "max_position_pct_equity": draw(st.none() | _mostly(_PLENTY, _FRACTION).map(str)),
            "max_daily_loss": str(draw(_mostly(_money(100, 2_000), _money(1, 100)))),
            "max_daily_loss_pct": draw(_mostly(st.none() | _PLENTY.map(str), _FRACTION.map(str))),
            "max_open_positions": draw(_mostly(st.integers(2, 50), st.integers(1, 50))),
            "max_concurrent_orders": draw(_mostly(st.integers(2, 500), st.integers(1, 500))),
            "max_orders_per_minute": draw(_mostly(st.integers(2, 600), st.integers(1, 600))),
            "min_leg_notional": str(draw(_mostly(_money(0, 5), _money(0, 500)))),
            "slippage_tolerance_bps": draw(_mostly(st.integers(5, 1000), st.integers(0, 1000))),
            "time_in_force_default": draw(_mostly(st.sampled_from(["GTC", "PostOnly"]), _ANY_TIF)),
            "reduce_only_default": draw(_mostly(st.just(False), st.booleans())),
            "margin_mode": draw(st.sampled_from(["isolated", "cross"])),
        }
    )


_LAYER = st.builds(
    LegOverrides.model_validate,
    st.fixed_dictionaries(
        {},
        optional={
            "sizing": st.one_of(
                st.builds(
                    lambda q: {"mode": "fixed_qty", "qty": str(q)},
                    _money(0, 1, 3).map(lambda q: q or LOT),
                ),
                st.builds(
                    lambda r, m: {
                        "mode": "risk_based",
                        "risk_per_trade_usd": str(r),
                        "max_notional_usd": str(m),
                    },
                    _money(1, 5_000),
                    _money(1, 100_000),
                ),
            ),
            "leverage": _money(1, 100).map(str),
            "time_in_force": _ANY_TIF,
            "reduce_only": st.booleans(),
        },
    ),
)


@st.composite
def _legs(
    draw: st.DrawFn, /, bound: AccountProfile, alternate: AccountProfile | None
) -> ResolvedLeg:
    """Adversarial: any size, leverage, stop, take-profit and order default a resolver could hand
    over, mostly plausible and on the grids, sometimes hostile or off them."""
    side = draw(st.sampled_from(["buy", "sell"]))
    sign = 1 if side == "buy" else -1
    lots = draw(_mostly(st.integers(1, 100), st.integers(1, 2_000_000)))
    stop_ticks = draw(_mostly(st.integers(1, 600), st.integers(-50, 20_000)))
    tp_ticks = draw(_mostly(st.integers(1, 2_000), st.none() | st.integers(-50, 40_000)))
    ids = [bound.profile_id, *([alternate.profile_id] if alternate else [])]
    return ResolvedLeg.model_validate(
        {
            **BASELINE_VALUES,
            "profile_id": draw(_mostly(st.sampled_from(ids), st.just(BOUND_VALUES["account_id"]))),
            "side": side,
            "qty": lots * LOT + draw(_mostly(st.just(D(0)), st.just(D("0.0001")))),
            "leverage": draw(_mostly(_money(1, 5), _money(1, 100))),
            "stop_price": REF - sign * stop_ticks * TICK,
            "stop_qty": draw(st.none() | _money(0, 1, 3).map(lambda q: q or LOT)),
            "tpsl_mode": draw(st.sampled_from(["Full", "Partial"])),
            "take_profit_price": None if tp_ticks is None else REF + sign * tp_ticks * TICK,
            "time_in_force": draw(_mostly(st.sampled_from(["FOK", "IOC"]), _ANY_TIF)),
            "reduce_only": draw(_mostly(st.just(True), st.booleans())),
            "margin_mode": draw(_mostly(st.just(bound.margin_mode), st.just("cross"))),
            "slippage_tolerance_bps": draw(_mostly(st.integers(0, 5), st.integers(0, 1000))),
            "position_idx": draw(_mostly(st.just(0), st.sampled_from([1, 2]))),
        }
    )


def _figure(good: st.SearchStrategy[Any], bad: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """Usually known and plausible; sometimes unknown (`None`) or hostile."""
    return _mostly(good, st.none() | bad)


_FIGURES = st.builds(
    AccountFigures,
    equity=_figure(_money(100_000, 1_000_000), _money(0, 1_000_000)),
    available_margin=_figure(_money(10_000, 1_000_000), _money(0, 1_000_000)),
    committed_risk=_figure(_money(0, 10), _money(0, 1_000)),
    realised_loss_today=_figure(_money(0, 10), _money(0, 1_000)),
    open_positions_after=_figure(st.integers(0, 1), st.integers(0, 60)),
    open_orders_after=_figure(st.integers(0, 1), st.integers(0, 600)),
    orders_in_minute_after=_figure(st.integers(0, 1), st.integers(0, 700)),
    taker_fee_rate=_figure(st.just(D("0.00055")), st.sampled_from([D("0"), D("0.001")])),
    maintenance_margin_rate=_figure(
        st.sampled_from([D("0"), D("0.005"), D("0.01")]), st.just(D("0.5"))
    ),
)


@st.composite
def _cases(draw: st.DrawFn, /) -> dict[str, Any]:
    bound = draw(_profiles())
    alternate = draw(
        _mostly(st.none(), _profiles(profile_id=ALTERNATE_ID, name="Alt", is_default=False))
        | st.none()
    )
    resulting = draw(_legs(bound, alternate))
    sign = 1 if resulting.side == "buy" else -1
    other = "sell" if resulting.side == "buy" else "buy"
    baseline = ResolvedLeg.model_validate(
        {
            **BASELINE_VALUES,
            "side": draw(_mostly(st.just(resulting.side), st.just(other))),
            "ref_price": draw(_mostly(st.just(REF), st.just(REF + TICK))),
            "stop_price": REF
            - sign * draw(_mostly(st.integers(600, 10_000), st.integers(1, 600))) * TICK,
            "take_profit_price": draw(st.none() | st.just(REF + sign * 2000 * TICK)),
        }
    )
    return {
        "bound": bound,
        "alternate": alternate,
        "leg": resulting,
        "baseline": baseline,
        "figures": draw(_FIGURES),
        "requested": tuple(draw(_mostly(st.just([]), st.lists(_LAYER, max_size=2)))),
    }


def _tighter(*values: Any) -> Any:
    known = [v for v in values if v is not None]
    return min(known) if known else None


def _assert_within_caps(case: dict[str, Any], result: Admitted) -> None:
    """The independent check: every cap restated from B and A alone."""
    b: AccountProfile = case["bound"]
    a: AccountProfile | None = case["alternate"]
    leg: ResolvedLeg = result.leg
    base: ResolvedLeg = case["baseline"]
    f: AccountFigures = case["figures"]
    profiles = [b] if a is None else [b, a]
    notional = leg.qty * leg.ref_price
    distance = abs(leg.ref_price - leg.stop_price)
    assert leg == case["leg"].model_copy(update={"stop_qty": leg.qty})  # never clamped (R8 apart)
    assert all(p.enabled and p.trading_enabled for p in profiles)
    assert all(SymbolScope.of(p).allows(BTCUSDT) for p in profiles)
    assert leg.margin_mode == b.margin_mode and leg.position_idx == 0
    for p in profiles:
        if p.max_position_notional is not None:
            assert notional <= p.max_position_notional
        if p.max_position_pct_equity is not None:
            assert f.equity is not None and notional <= p.max_position_pct_equity * f.equity
        assert p.max_leverage_cap is not None and leg.leverage <= p.max_leverage_cap
        assert f.open_positions_after is not None and p.max_open_positions is not None
        assert f.open_positions_after <= p.max_open_positions
        assert f.open_orders_after is not None and p.max_concurrent_orders is not None
        assert f.open_orders_after <= p.max_concurrent_orders
        assert f.orders_in_minute_after is not None
        assert f.orders_in_minute_after <= p.max_orders_per_minute
        assert leg.slippage_tolerance_bps <= p.slippage_tolerance_bps
    assert any(p.max_position_notional or p.max_position_pct_equity for p in profiles)
    # R2: the risk at the stop, both fees, within the net daily-loss headroom and B's budget
    assert f.taker_fee_rate is not None and f.committed_risk is not None
    assert f.realised_loss_today is not None
    risk = leg.qty * distance + leg.qty * leg.ref_price * 2 * f.taker_fee_rate
    caps = [p.max_daily_loss for p in profiles]
    caps += [None if p.max_daily_loss_pct is None or f.equity is None
             else p.max_daily_loss_pct * f.equity for p in profiles]  # fmt: skip
    daily = _tighter(*caps)
    assert daily is not None
    assert risk <= daily - f.realised_loss_today - f.committed_risk
    if b.sizing_mode == "risk_based":
        budget = b.risk_fixed_amount
        if budget is None:
            assert f.equity is not None and b.risk_pct_equity is not None
            budget = b.risk_pct_equity * f.equity
        assert risk <= budget
    # R3: the stop inside the isolated-margin liquidation estimate
    assert f.maintenance_margin_rate is not None
    move = leg.ref_price * (1 / leg.leverage - f.maintenance_margin_rate)
    assert distance <= move
    # R4: the stop on the loss side, no further than B's own
    loss_side = (
        leg.stop_price < leg.ref_price if leg.side == "buy" else leg.stop_price > leg.ref_price
    )
    assert loss_side and base.side == leg.side
    assert distance <= abs(base.ref_price - base.stop_price)
    # R5: minimums met on the grids, never rounded up
    assert leg.qty % LOT == 0 and leg.stop_price % TICK == 0
    assert leg.qty >= BTCUSDT.min_order_qty
    assert notional >= max(BTCUSDT.min_notional, b.min_leg_notional)
    # R6: margin fundable
    assert f.available_margin is not None
    assert notional / leg.leverage <= f.available_margin * D("0.98")
    # rows 40 and 41
    assert _RANK[leg.time_in_force] <= _RANK[b.time_in_force_default]
    assert leg.reduce_only or not b.reduce_only_default
    # R8
    assert result.leg.stop_qty == leg.qty


@settings(max_examples=600, deadline=None)
@given(case=_cases())
def test_no_input_ever_widens_a_cap(case: dict[str, Any]) -> None:
    result = judge_leg(
        case["bound"],
        case["leg"],
        baseline=case["baseline"],
        instrument=BTCUSDT,
        figures=case["figures"],
        alternate=case["alternate"],
        requested=case["requested"],
    )
    if isinstance(result, Refused):
        event("refused")
        assert result.violations
        assert all(v.field in OVERRIDE_CLASS for v in result.violations)
        return
    event("admitted")
    _assert_within_caps(case, result)
