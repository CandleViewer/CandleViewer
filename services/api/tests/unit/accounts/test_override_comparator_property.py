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
    OTHER_ACCOUNT,
)

D = Decimal
REF = D("64010")
TICK, LOT = BTCUSDT.tick_size, BTCUSDT.qty_step
_RANK = {"FOK": 0, "IOC": 0, "GTC": 1, "PostOnly": 1}
#: A profile of B's account that is neither B nor A.
FOREIGN_ID = "0b5f6d0e-28a1-4c1e-9e01-0000000000ee"


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
def _profiles(draw: st.DrawFn, /, *, default: bool, **identity: Any) -> AccountProfile:
    """B (`default`) or an alternate; its default flag is sometimes the wrong one."""
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
            "is_default": draw(_mostly(st.just(default), st.booleans())),
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
                st.builds(
                    lambda n, m: (
                        {"mode": "fixed_notional", "notional_usd": str(n)}
                        | ({} if m is None else {"max_notional_usd": str(m)})
                    ),
                    _money(1, 50_000),
                    st.none() | _money(1, 100_000),
                ),
                st.builds(
                    lambda p: {"mode": "risk_based", "risk_per_trade_pct": str(p)},
                    _FRACTION,
                ),
                st.builds(
                    lambda q: {"mode": "fixed_qty", "qty": str(q)},
                    st.sampled_from([D("100"), D("100.001")]),  # the instrument's maximum
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
    draw: st.DrawFn,
    /,
    bound: AccountProfile,
    alternate: AccountProfile | None,
    hint: int | None,
) -> ResolvedLeg:
    """Adversarial: any size, leverage, stop, take-profit and order default a resolver could hand
    over, mostly plausible and on the grids, sometimes hostile or off them. `hint` is the lot
    count the request's sizing asks for: the resolver often sizes to it, or one lot past it."""
    side = draw(st.sampled_from(["buy", "sell"]))
    sign = 1 if side == "buy" else -1
    lots = draw(_mostly(st.integers(1, 100), st.integers(1, 2_000_000)))
    if hint is not None and draw(st.booleans()):
        lots = max(1, hint + draw(st.sampled_from([-1, 0, 0, 1])))
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
            "stop_qty": draw(_mostly(st.none(), _money(0, 1, 3).map(lambda q: q or LOT))),
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


def _hint(requested: tuple[LegOverrides, ...]) -> int | None:
    """The lot count the last sizing layer asks for, if it names a size."""
    sizing = [layer.sizing for layer in requested if layer.sizing is not None]
    if not sizing:
        return None
    if sizing[-1].qty is not None:
        return int(sizing[-1].qty / LOT)
    if sizing[-1].notional_usd is not None:
        return int(sizing[-1].notional_usd / REF / LOT)
    return None


@st.composite
def _cases(draw: st.DrawFn, /) -> dict[str, Any]:
    bound = draw(_profiles(default=True))
    alternate = draw(
        st.integers(0, 3).flatmap(
            lambda pick: (
                _profiles(default=False, profile_id=ALTERNATE_ID, name="Alt")
                if pick == 0
                else st.none()
            )
        )
    )
    requested = tuple(draw(_mostly(st.just([]), st.lists(_LAYER, max_size=2))))
    if not requested and draw(st.integers(0, 3)) == 0:
        requested = (draw(_LAYER),)
    resulting = draw(_legs(bound, alternate, _hint(requested)))
    sign = 1 if resulting.side == "buy" else -1
    other = "sell" if resulting.side == "buy" else "buy"
    baseline = ResolvedLeg.model_validate(
        {
            **BASELINE_VALUES,
            "profile_id": draw(
                _mostly(st.just(bound.profile_id), st.sampled_from([ALTERNATE_ID, FOREIGN_ID]))
            ),
            "account_id": draw(
                _mostly(st.just(BASELINE_VALUES["account_id"]), st.just(OTHER_ACCOUNT))
            ),
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
        "requested": requested,
    }


def _tighter(*values: Any) -> Any:
    known = [v for v in values if v is not None]
    return min(known) if known else None


def _budget(p: AccountProfile, equity: Decimal | None) -> Decimal:
    """A `risk_based` profile's per-trade budget in USDT; an admitted leg had it known."""
    if p.risk_fixed_amount is not None:
        return p.risk_fixed_amount
    assert equity is not None and p.risk_pct_equity is not None
    return p.risk_pct_equity * equity


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
    assert case["leg"].stop_qty in (None, leg.qty)  # R8 never overwrites a caller's stop size
    assert b.is_default and (a is None or not a.is_default)  # B is the account's default
    assert (base.profile_id, base.account_id) == (b.profile_id, b.account_id)  # L_B is B's
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
    # the exit fee priced at the further of `ref` and the stop (OPEN-4, ruled 2026-10-25)
    exit_price = max(leg.ref_price, leg.stop_price)
    risk = leg.qty * distance + leg.qty * (leg.ref_price + exit_price) * f.taker_fee_rate
    caps = [p.max_daily_loss for p in profiles]
    caps += [None if p.max_daily_loss_pct is None or f.equity is None
             else p.max_daily_loss_pct * f.equity for p in profiles]  # fmt: skip
    daily = _tighter(*caps)
    assert daily is not None
    assert risk <= daily - f.realised_loss_today - f.committed_risk
    if b.sizing_mode == "risk_based":
        assert risk <= _budget(b, f.equity)
    # R3: the stop strictly inside the isolated-margin liquidation estimate, less both taker fees
    # on the notional at the stop (OPEN-2, OPEN-3, ruled 2026-10-25)
    assert f.maintenance_margin_rate is not None
    move = leg.ref_price * (1 / leg.leverage - f.maintenance_margin_rate)
    assert distance < move - 2 * f.taker_fee_rate * leg.stop_price
    # R4: the stop on the loss side, no further than B's own
    loss_side = (
        leg.stop_price < leg.ref_price if leg.side == "buy" else leg.stop_price > leg.ref_price
    )
    assert loss_side and base.side == leg.side
    assert distance <= abs(base.ref_price - base.stop_price)
    # rows 26 and 27: the take-profit on the profit side, no further than B's, never removed
    tp, base_tp = leg.take_profit_price, base.take_profit_price
    assert tp is not None or base_tp is None
    if tp is not None:
        assert (tp > leg.ref_price) if leg.side == "buy" else (tp < leg.ref_price)
        assert tp % TICK == 0
        assert base_tp is None or abs(tp - leg.ref_price) <= abs(base_tp - base.ref_price)
    # rows 13 and 14: no requested or alternate per-trade budget above B's
    sizing = [layer.sizing for layer in case["requested"] if layer.sizing is not None]
    asked = sizing[-1] if sizing else None
    if b.sizing_mode == "risk_based":
        if asked is not None and asked.mode == "risk_based":
            wanted = asked.risk_per_trade_usd
            if wanted is None:
                assert asked.risk_per_trade_pct is not None and f.equity is not None
                wanted = asked.risk_per_trade_pct * f.equity
            assert wanted <= _budget(b, f.equity)
        elif asked is None and a is not None and a.sizing_mode == "risk_based":
            assert _budget(a, f.equity) <= _budget(b, f.equity)
    # R5: minimums met on the grids, never rounded up, never past the request or the instrument
    assert leg.qty % LOT == 0 and leg.stop_price % TICK == 0
    assert BTCUSDT.min_order_qty <= leg.qty <= BTCUSDT.max_order_qty
    assert notional >= max(BTCUSDT.min_notional, b.min_leg_notional)
    if asked is not None:
        assert asked.qty is None or leg.qty <= asked.qty <= BTCUSDT.max_order_qty
        assert asked.notional_usd is None or notional <= asked.notional_usd
        assert asked.max_notional_usd is None or notional <= asked.max_notional_usd
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
