"""E39-T01 (#881) slice 1: Hypothesis invariants of the pure evaluator.

More loss, more exposure or a tighter limit never turns a refusal into an admission; a policy
`warn` never admits what a blocking layer refuses (SR-E39-03); an exempt close is never refused
(SR-E39-02); a boundary is exact to the last `Decimal` place. The policy's `breach_behaviour` is
drawn from warn, block and flatten in every scenario.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.risk import ManagerCaps
from tests.unit.risk._risk_builders import D, caps, close_order, figures, order, run

_money = st.decimals(min_value=0, max_value=10**7, places=8)
_pct = st.decimals(min_value=D("0.01"), max_value=100, places=4)
_count = st.integers(min_value=0, max_value=60)
_POLICY_CAPS = (
    "max_total_notional_usd",
    "max_daily_loss_usd",
    "max_drawdown_pct",
    "max_open_positions",
    "max_leverage",
    "max_orders_per_minute",
    "per_symbol_concentration_pct",
)
_behaviour = st.sampled_from(["warn", "block", "flatten"])


@st.composite
def _scenario(draw: st.DrawFn) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    pol = {
        "max_total_notional_usd": draw(_money),
        "max_daily_loss_usd": draw(_money),
        "max_drawdown_pct": draw(_pct),
        "max_open_positions": draw(_count),
        "max_leverage": draw(st.decimals(min_value=1, max_value=100, places=2)),
        "max_orders_per_minute": draw(st.integers(min_value=1, max_value=600)),
        "per_symbol_concentration_pct": draw(_pct),
        "breach_behaviour": {name: draw(_behaviour) for name in _POLICY_CAPS},
    }
    prof = {
        "max_position_notional_usd": draw(st.one_of(st.none(), _money)),
        "max_daily_loss_pct": draw(st.one_of(st.none(), _pct)),
        "max_consecutive_losses": draw(st.one_of(st.none(), _count)),
        "max_open_positions": draw(st.one_of(st.none(), _count)),
        "max_leverage_cap": draw(st.one_of(st.none(), st.decimals(min_value=1, max_value=100))),
        "max_daily_loss_usd": draw(st.one_of(st.none(), _money)),
    }
    peak = draw(_money)
    fig = {
        "equity": draw(st.decimals(min_value=1, max_value=10**7, places=2)),
        "day_start_equity": draw(st.decimals(min_value=1, max_value=10**7, places=2)),
        "daily_figure": peak - draw(_money),
        "day_peak_figure": peak,
        "open_positions": draw(_count),
        "orders_last_minute": draw(_count),
        "consecutive_losses": draw(_count),
        "symbol_notional": {"BTCUSDT": draw(_money), "ETHUSDT": draw(_money)},
    }
    return pol, prof, fig


@given(_scenario(), _money)
def test_more_loss_never_turns_a_refusal_into_an_admission(
    s: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], extra: Decimal
) -> None:
    pol, prof, fig = s
    c = caps(pol, prof)
    if not run(f=figures(**fig), c=c).decision.allowed:
        worse = {**fig, "daily_figure": fig["daily_figure"] - extra}
        assert not run(f=figures(**worse), c=c).decision.allowed


@given(_scenario(), _money, _money)
def test_more_exposure_never_turns_a_refusal_into_an_admission(
    s: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], notional: Decimal, extra: Decimal
) -> None:
    pol, prof, fig = s
    c, f = caps(pol, prof), figures(**fig)
    if not run(order(notional=notional), f, c).decision.allowed:
        assert not run(order(notional=notional + extra), f, c).decision.allowed


@given(_scenario(), st.decimals(min_value=0, max_value=1, places=3), _money)
def test_a_tighter_layer_never_turns_a_refusal_into_an_admission(
    s: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], factor: Decimal, override: Decimal
) -> None:
    pol, prof, fig = s
    f = figures(**fig)
    if not run(f=f, c=caps(pol, prof)).decision.allowed:
        tight = {k: v * factor for k, v in pol.items() if isinstance(v, Decimal)}
        assert not run(f=f, c=caps({**pol, **tight}, prof)).decision.allowed
        assert not run(f=f, c=caps(pol, prof, ManagerCaps(override + 1))).decision.allowed


_small = st.integers(min_value=0, max_value=20)
_Over = tuple[str, Callable[[int], dict[str, Any]], Callable[[int, int], bool]]
_OVER: dict[str, _Over] = {  # cap: (profile column, figures for `n`, is `n` over limit `b`)
    "max_daily_loss_usd": ("max_daily_loss_usd", lambda n: {"daily_figure": D(-n)}, int.__ge__),
    "max_open_positions": ("max_open_positions", lambda n: {"open_positions": n}, int.__ge__),
    "max_leverage": (
        "max_leverage_cap",
        lambda n: {"symbol_notional": {"ETHUSDT": D(n * 100_000 - 10_000)}},
        int.__gt__,
    ),
}


@given(
    st.sampled_from(sorted(_OVER)),
    _small,
    st.one_of(st.none(), _small),
    st.one_of(st.none(), _small),
    _behaviour,
    st.integers(min_value=1, max_value=20),
)
def test_a_policy_warn_never_admits_what_a_blocking_layer_refuses(  # SR-E39-03
    cap: str, pol_at: int, prof_at: int | None, mgr_at: int | None, behaviour: str, n: int
) -> None:
    column, fig, over = _OVER[cap]
    mgr_at = mgr_at if cap == "max_daily_loss_usd" else None
    pol = {cap: pol_at, "breach_behaviour": {cap: behaviour}, "max_total_notional_usd": D(10**9)}
    c = caps(pol, {column: prof_at}, ManagerCaps(None if mgr_at is None else D(mgr_at)))
    blocking = [b for b in (prof_at, mgr_at) if b is not None]
    blocking += [pol_at] if behaviour != "warn" else []
    result = run(f=figures(**fig(n)), c=c)
    assert result.decision.allowed is not any(over(n, b) for b in blocking)
    if result.decision.allowed:
        assert bool(result.warnings) is (behaviour == "warn" and over(n, pol_at))


@given(_scenario(), st.booleans(), st.booleans())
def test_an_exempt_close_is_never_refused(
    s: tuple[dict[str, Any], dict[str, Any], dict[str, Any]], locked: bool, killed: bool
) -> None:
    pol, prof, fig = s
    f = figures(**{**fig, "equity": None}, lockout_active=locked, kill_switch_engaged=killed)
    assert run(close_order(), f, caps(pol, prof)).decision.allowed


@given(st.decimals(min_value=D("1E-18"), max_value=10**5, places=18), st.data())
def test_a_notional_boundary_is_exact_to_the_last_place(
    limit: Decimal, data: st.DataObject
) -> None:
    held = data.draw(st.decimals(min_value=0, max_value=limit, places=18))
    c = caps(prof={"max_position_notional_usd": limit})
    f = figures(symbol_notional={"BTCUSDT": held})
    assert run(order(notional=limit - held), f, c).decision.allowed
    over = run(order(notional=limit - held + D("1E-18")), f, c).decision
    assert over.cap == "max_position_notional_usd"
