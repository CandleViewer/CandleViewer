"""E28-T03 (#907): the sizer's caps (24 Sec.9.3.2), the margin step, the explanation and its
`sizing_explanation` text, the take-profits (Sec.9.3.3), and the ruled properties: an `ok` leg
passes the comparator's R1, R2, R5, R6, R7 and take-profit rows, never exceeds a cap or the
margin, and grows with the risk."""

from __future__ import annotations

import re
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from typing import Any, Final

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from candleviewer.accounts import sizer as sz
from candleviewer.accounts.override_comparator import (
    MARGIN_SHARE,
    Refused,
    ResolvedLeg,
    judge_leg,
)
from candleviewer.accounts.profiles import AccountProfile
from tests.unit.accounts.test_sizer import (
    _ATR,
    _E28,
    _json,
    atr,
    instrument,
    profile,
    sized,
    wallet,
)

D = Decimal
_SOL: Final = {"symbol": "SOLUSDT", "price": "150.000"}
_ANY_SOL: Final = {"allowed_symbols": ["*USDT"]}
_QA: Final = _json(_E28 / "golden_sizing_vectors.json")


def run(v: dict[str, Any]) -> sz.LegSizing:
    """One vector through `size_leg`: `daily_loss_used` is the day's realised loss, nothing is
    committed; `mid` and `last_price` are optional (a market vector's)."""
    m, it = v["market"], v["intent"]
    intent = sz.SizingIntent.model_validate(it | {"side": it["side"].lower()})
    p = profile(v["profile"]["id"], **v["profile"]["set"])
    reading = atr(D(m["atr"]), p.sl_atr_period) if m["atr"] else None
    market = sz.SizingMarket(mid=m.get("mid"), last_price=m.get("last_price"), atr=reading)
    w = wallet(v["wallet"]["equity"], m["taker_fee_rate"], realised_loss_today=m["daily_loss_used"])
    w = w.model_copy(update={"available_margin": D(v["wallet"]["available_margin"])})
    return sz.size_leg(intent, p, w, instrument(intent.symbol), market)


def vector(vid: str) -> sz.LegSizing:
    return run(next(v for v in _QA if v["id"] == vid))


_MID: Final = sz.SizingMarket(mid=D(64000), last_price=D(63000), atr=_ATR)
#: Named legs off QA's vectors: a market order at mid where max_mkt_order_qty binds, the ATR
#: fallback, a denied symbol, the day's room spent or overspent, and a market order with no price.
_LEGS: Final = {
    "market-at-mid": lambda: sized(profile("P-PCT"), wallet("1000000000"), _MID, price=None),
    "atr-fallback": lambda: sized(profile("P-PCT")),
    "denied": lambda: sized(profile("P-PCT", denied_symbols=["SOLUSDT"]), **_SOL),
    "room-spent": lambda: sized(
        profile("P-NOTIONAL", **_ANY_SOL), wallet(realised_loss_today="250"), **_SOL
    ),
    "room-overspent": lambda: sized(
        profile("P-NOTIONAL", **_ANY_SOL), wallet(realised_loss_today="300"), **_SOL
    ),
    "no-price": lambda: sized(profile("P-QTY"), price=None),
}


def leg(name: str) -> sz.LegSizing:
    return vector(name) if name in {v["id"] for v in _QA} else _LEGS[name]()


@pytest.mark.parametrize(
    ("w", "cap", "qty"),
    [
        (wallet(committed_risk="248"), "max_daily_loss", "4.000"),  # the committed risk nets
        (wallet(realised_loss_today="249.5", taker="0.001"), "max_daily_loss", "0.625"),  # 0.5/0.8
    ],
    ids=["committed-risk", "realised-loss-and-fees"],
)
def test_clamp_daily_room_is_net_of_loss_and_committed_risk_with_fees(
    w: Any, cap: str, qty: str
) -> None:
    got = sized(profile("P-NOTIONAL", **_ANY_SOL), w, **_SOL)
    assert (got.outcome, got.binding and got.binding.cap, got.qty) == ("ok", cap, D(qty))
    assert cap in got.rules


def test_clamp_only_lowers_and_names_none_when_every_cap_is_above() -> None:
    got = vector("V14")
    assert got.binding is None and got.raw_qty is not None and got.qty is not None
    assert all(clamp.limit > got.raw_qty for clamp in got.clamps)
    assert got.qty == D("6.666") and got.rounding_delta == Context(prec=100).subtract(
        got.raw_qty, got.qty
    )


def test_clamp_a_profile_with_no_caps_is_held_by_the_instrument_alone() -> None:
    # Unreachable through validation (a trading profile bounds every cap, D11); forged here
    caps = dict.fromkeys(("max_leverage_cap", "max_daily_loss", "max_daily_loss_pct"))
    p = profile("P-QTY", fixed_qty="200").model_copy(
        update=caps | {"max_position_pct_equity": None}
    )
    got = sized(p.model_copy(update={"max_position_notional": None}), wallet("1E+9"), price="100")
    assert [clamp.cap for clamp in got.clamps] == ["max_order_qty"]
    assert (got.qty, got.binding) == (D(100), got.clamps[0])


def test_size_leg_leverage_above_the_instrument_maximum_fails_leverage_unavailable() -> None:
    inst = instrument("BTCUSDT").model_copy(update={"max_leverage": D(5)})
    got = sized(profile("P-PCT"), inst=inst, market=sz.SizingMarket(atr=_ATR))
    assert (got.outcome, got.reason, got.qty) == ("fail", sz.FailReason.LEVERAGE_UNAVAILABLE, None)
    assert got.render() == (
        "stop 63400 USDT from a 14-bar 1h ATR of 400 USDT (source kernel, descriptor v1, kernel"
        " build v1, closed bar 20261005T000000Z); failed: leverage_unavailable"
    )


@pytest.mark.parametrize(
    ("side", "limit", "px"),
    [("buy", "64100", "64100"), ("sell", "63900", "64000")],
    ids=["buy-at-its-limit", "sell-at-mid"],
)
def test_size_leg_marketable_limit_judges_caps_at_the_larger_notional(
    side: str, limit: str, px: str
) -> None:
    market = sz.SizingMarket(mid=D(64000))
    got = sized(
        profile("P-RISK", max_position_notional="26650"), market=market, side=side, price=limit
    )
    notional_cap = next(c for c in got.clamps if c.cap == "max_position_notional")
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 100, ROUND_FLOOR
        assert notional_cap.limit == D(26650) / D(px)
    assert got.qty is not None
    assert got.initial_margin == got.qty * D(px) / 5
    assert (f" at {px} USDT" in got.render()) == (px != limit)  # a sell's margin is at mid


def test_size_leg_insufficient_margin_reports_the_margin_it_needed() -> None:
    got = sized(profile("P-QTY"), wallet(available_margin="65.30"))  # 64 > 65.30 x 0.98 = 63.994
    assert (got.reason, got.initial_margin) == (sz.FailReason.INSUFFICIENT_MARGIN, D(64))
    assert sized(profile("P-QTY"), wallet(available_margin="65.31")).outcome == "ok"  # 64.0038


@pytest.mark.parametrize(
    ("vid", "rules"),
    [
        ("V01", ("stop_ticks", "risk_based", "fee_correction", "lot_floor", "tp_ladder")),
        ("V10", ("stop_ticks", "fixed_notional", "max_daily_loss", "tp_ticks")),
        ("V13", ("stop_ticks", "risk_based", "fee_correction", "max_leverage_cap")),
        ("market-at-mid", ("stop_atr", "pct_equity", "max_order_qty", "max_mkt_order_qty")),
        ("atr-fallback", ("stop_fallback", "pct_equity", "lot_floor")),
        ("denied", ()),
    ],
)
def test_explanation_lists_the_rules_that_fired_in_order(vid: str, rules: tuple[str, ...]) -> None:
    assert leg(vid).rules == rules


def test_explanation_records_the_atr_reading_only_when_it_set_the_stop() -> None:
    assert (vector("V05").atr, vector("V05").stop_fallback) == (_ATR, False)
    assert (leg("atr-fallback").atr, leg("atr-fallback").stop_fallback) == (None, True)
    assert vector("V01").atr is None  # a ticks stop reads no ATR


def test_explanation_records_the_atr_reading_a_take_profit_used() -> None:
    p = profile("P-QTY", sl_offset_unit="ticks", sl_offset_value="600", tp_offset_unit="atr")
    got = sized(p, market=sz.SizingMarket(atr=_ATR))
    assert (got.atr, got.tps) == (_ATR, (sz.TakeProfit(D(64800), D("0.01")),))  # 2 x 400


def test_explanation_records_no_atr_reading_for_a_take_profit_that_was_dropped() -> None:
    p = profile("P-QTY", sl_offset_unit="ticks", sl_offset_value="600", tp_offset_unit="atr")
    p = p.model_copy(update={"tp_offset_value": D("0.0001")})  # 0.04 floors back onto entry
    got = sized(p, market=sz.SizingMarket(atr=_ATR))
    assert (got.outcome, got.atr, got.tps, got.rules[-1]) == ("ok", None, (), "fixed_qty")


_RENDERED: Final = {
    "V01": "risk_based: 50 USDT / 120 USDT per BTC = 0.41666666 BTC -> 0.416 BTC (floored by "
    "0.00066666 BTC); stop 63880 USDT; notional 26624 USDT; 1R = 49.92 USDT; risk with fees "
    "49.92 USDT; initial margin 5324.8 USDT",
    "V08": "fixed_qty: 0.01 SOL = 0.01 SOL -> 0.01 SOL; stop 148.5 USDT; notional 1.5 USDT; "
    "1R = 0.015 USDT; risk with fees 0.015 USDT; skipped: below_min_notional, min_notional 5 USDT",
    "room-spent": "fixed_notional: 1000 USDT / 150 USDT per SOL = 6.66666666 SOL capped by "
    "max_daily_loss at 0 SOL -> 0 SOL; stop 149.5 USDT; notional 0 USDT; 1R = 0 USDT; risk "
    "with fees 0 USDT; failed: cap_breached, min_order_qty 0.001 SOL",
    "room-overspent": "fixed_notional: 1000 USDT / 150 USDT per SOL = 6.66666666 SOL capped by "
    "max_daily_loss at 0 SOL -> 0 SOL; stop 149.5 USDT; notional 0 USDT; 1R = 0 USDT; risk "
    "with fees 0 USDT; failed: cap_breached, min_order_qty 0.001 SOL",
    "atr-fallback": "pct_equity: 5000 USDT / 64000 USDT per BTC = 0.078125 BTC -> 0.078 BTC "
    "(floored by 0.000125 BTC); stop 62720 USDT (ATR fallback); notional 4992 USDT; "
    "1R = 99.84 USDT; risk with fees 99.84 USDT; initial margin 499.2 USDT",
    "denied": "skipped: symbol_denied",
    "no-price": "failed: no_reference_price",
}


@pytest.mark.parametrize("vid", sorted(_RENDERED))
def test_render_is_the_contracts_sizing_explanation(vid: str) -> None:
    assert leg(vid).render() == _RENDERED[vid]


_NUMBER: Final = re.compile(r"(?<![\w.-])-?\d+(?:\.\d+)?(?![\w.-])")
_UNIT: Final = re.compile(r" (?:USDT|BTC|ETH|SOL)\b")


def test_resolve_tps_drops_a_price_at_or_past_entry_or_at_or_below_zero() -> None:
    btc, stop = instrument("BTCUSDT"), sz.ResolvedStop(D(160), D(60), False)
    p = profile("P-QTY")  # one 2R take-profit
    assert sz.resolve_tps("sell", p, D(100), stop, D(1), btc, None) == ()  # 100 - 120 < 0
    near = profile("P-QTY", tp_offset_unit="ticks", tp_offset_value="0.5")  # 0.05 floors to entry
    assert sz.resolve_tps("buy", near, D(100), stop, D(1), btc, None) == ()
    assert sz.resolve_tps("buy", profile("P-PCT"), D(100), stop, D(1), btc, None) == ()  # none set


def test_resolve_tps_atr_reading_of_another_period_sets_none() -> None:
    p = profile("P-PCT", tp_offset_unit="atr", tp_offset_value="2")
    stop = sz.ResolvedStop(D(63400), D(600), False)
    btc = instrument("BTCUSDT")
    assert sz.resolve_tps("buy", p, D(64000), stop, D(1), btc, atr(D(400), period=20)) == ()


def test_resolve_tps_folds_a_rung_under_the_minimum_lot_into_the_last() -> None:
    fine = instrument("BTCUSDT").model_copy(update={"qty_step": D("0.0001")})  # min lot 0.001
    stop, p = sz.ResolvedStop(D(63880), D(120), False), profile("P-RISK")  # 1R and 2R, half each
    got = sz.resolve_tps("buy", p, D(64000), stop, D("0.0018"), fine, None)
    assert got == (sz.TakeProfit(D(64240), D("0.0018")),)  # 0.0009 cannot be placed reduce-only


def test_resolve_tps_folds_a_last_rung_under_the_minimum_lot_into_the_previous() -> None:
    fine = instrument("BTCUSDT").model_copy(update={"qty_step": D("0.0001")})  # min lot 0.001
    ladder = [{"qty_pct": "0.9", "r": "1"}, {"qty_pct": "0.1", "r": "2"}]
    stop, p = sz.ResolvedStop(D(63880), D(120), False), profile("P-RISK", tp_ladder=ladder)
    got = sz.resolve_tps("buy", p, D(64000), stop, D("0.0018"), fine, None)
    assert got == (sz.TakeProfit(D(64120), D("0.0018")),)  # 0.0016 + 0.0002, never a 0.0002


def test_resolve_tps_drops_a_last_rung_under_the_minimum_lot_with_none_kept_before() -> None:
    fine = instrument("BTCUSDT").model_copy(update={"qty_step": D("0.0001")})  # min lot 0.001
    stop, p = sz.ResolvedStop(D(63880), D(120), False), profile("P-RISK")  # 1R and 2R, half each
    assert sz.resolve_tps("buy", p, D(64000), stop, D("0.0005"), fine, None) == ()


@pytest.mark.parametrize(
    ("side", "limit", "prices"),
    [("buy", "64100", ("64220", "64340")), ("sell", "63900", ("63780", "63660"))],
    ids=["marketable-buy", "marketable-sell"],
)
def test_size_leg_marketable_limit_anchors_take_profits_at_the_limit(
    side: str, limit: str, prices: tuple[str, str]
) -> None:
    got = sized(profile("P-RISK"), market=sz.SizingMarket(mid=D(64000)), side=side, price=limit)
    stop = D(limit) - D(120) if side == "buy" else D(limit) + D(120)  # 1R from the limit too
    assert (got.outcome, got.ref_source, got.stop) == (
        "ok",
        "marketable_limit_worst_fill",
        sz.ResolvedStop(stop, D(120), False),
    )
    assert tuple(tp.price for tp in got.tps) == tuple(D(x) for x in prices)  # 1R, 2R past the limit


@pytest.mark.parametrize(
    ("side", "limit", "outcome"),
    [
        ("buy", "64130", "fail"),  # stop 64010, above mid
        ("buy", "64120", "fail"),  # stop 64000, at mid
        ("buy", "64119.9", "ok"),  # stop 63999.9, just under mid
        ("sell", "63870", "fail"),  # stop 63990, below mid
        ("sell", "63880", "fail"),  # stop 64000, at mid
        ("sell", "63880.1", "ok"),  # stop 64000.1, just over mid
    ],
    ids=["buy-past", "buy-at-mid", "buy-inside", "sell-past", "sell-at-mid", "sell-inside"],
)
def test_size_leg_stop_on_the_wrong_side_of_mid_fails_invalid_stop_distance(
    side: str, limit: str, outcome: str
) -> None:
    got = sized(profile("P-RISK"), market=sz.SizingMarket(mid=D(64000)), side=side, price=limit)
    assert got.outcome == outcome
    assert got.reason == (sz.FailReason.INVALID_STOP_DISTANCE if outcome == "fail" else None)
    assert got.stop is not None and got.stop.distance == D(120)  # 1R from the limit either way


def test_resolve_tps_unknown_offset_unit_is_a_programming_error() -> None:
    p = profile("P-QTY").model_copy(update={"tp_offset_unit": "pips"})  # forged past validation
    stop = sz.ResolvedStop(D(63880), D(120), False)
    with pytest.raises(ValueError, match="unit 'pips'"):
        sz.resolve_tps("buy", p, D(64000), stop, D(1), instrument("BTCUSDT"), None)


def assert_every_figure_has_a_unit(text: str) -> None:
    for number in _NUMBER.finditer(text):
        assert _UNIT.match(text, number.end()), (number.group(), text)


@pytest.mark.parametrize("name", [*(v["id"] for v in _QA), *_LEGS])
def test_render_every_figure_carries_a_unit(name: str) -> None:
    assert_every_figure_has_a_unit(leg(name).render())


# --- the ruled properties --------------------------------------------------------------------

_HANDLES: Final = {
    "P-RISK": {},
    "P-QTY": {},
    "P-PCT": {},
    "P-NOTIONAL": {"allowed_symbols": ["*USDT"]},
}


def _resolved(p: AccountProfile, got: sz.LegSizing, side: str) -> ResolvedLeg:
    assert got.ref_price is not None and got.qty is not None and got.stop is not None
    hedge_idx = 1 if side == "buy" else 2
    return ResolvedLeg.model_validate(
        {
            "account_id": p.account_id,
            "profile_id": p.profile_id,
            "symbol": "BTCUSDT",
            "side": side,
            "ref_price": got.ref_price,
            "qty": got.qty,
            "leverage": p.leverage,
            "stop_price": got.stop.price,
            "tpsl_mode": "Full",
            "time_in_force": p.time_in_force_default,
            "reduce_only": p.reduce_only_default,
            "margin_mode": p.margin_mode,
            "position_mode": p.position_mode,
            "position_idx": 0 if p.position_mode == "one_way" else hedge_idx,
            "slippage_tolerance_bps": p.slippage_tolerance_bps,
        }
    )


def _money(low: int, high: int, places: int = 2) -> st.SearchStrategy[Decimal]:
    return st.integers(low * 10**places, high * 10**places).map(lambda n: D(n).scaleb(-places))


_CEIL: Final = Context(prec=100, rounding=ROUND_CEILING)


def _scaled(low: int, high: int) -> st.SearchStrategy[Decimal]:
    """Log-uniform over 10**low to 10**high, so a large equity or cap is drawn as often as a
    small one (and `max_mkt_order_qty` is reached)."""
    return st.integers(low, high - 1).flatmap(lambda e: _money(10**e, 10 ** (e + 1)))


def _daily_cap(p: AccountProfile, equity: Decimal) -> Decimal:
    """The profile's resolved daily cap: the tighter of `max_daily_loss` and its pct of equity."""
    pct = None if p.max_daily_loss_pct is None else p.max_daily_loss_pct * equity
    return min(cap for cap in (p.max_daily_loss, pct) if cap is not None)


def _cent(value: Decimal) -> Decimal:
    return value.quantize(D("0.01"), rounding=ROUND_FLOOR)


@settings(max_examples=300)
@given(
    handle=st.sampled_from(sorted(_HANDLES)),
    equity=_scaled(2, 9),
    margin_share=st.integers(1, 300).map(lambda n: D(n) / 100),  # available up to 3x equity
    taker=_money(0, 2, 6).map(lambda n: n / 1000),
    lost=st.integers(0, 100).map(lambda n: D(n) / 100),  # of the resolved daily cap
    held=st.integers(0, 100).map(lambda n: D(n) / 100),  # of what is left of it
    leverage=st.integers(1, 10),  # held to the profile's max_leverage_cap
    ref=_money(1_000, 200_000, 1),
    side=st.sampled_from(["buy", "sell"]),
    notional_cap=_scaled(2, 9),
    mid=st.none() | _money(1_000, 200_000, 1),
    market=st.booleans(),
    fine=st.none() | st.integers(1, 99),  # a 0.0001 lot and a two-rung ladder of this share
)
def test_size_leg_ok_passes_the_comparator_and_never_exceeds_a_cap(
    handle: str,
    equity: Decimal,
    margin_share: Decimal,
    taker: Decimal,
    lost: Decimal,
    held: Decimal,
    leverage: int,
    ref: Decimal,
    side: str,
    notional_cap: Decimal,
    mid: Decimal | None,
    market: bool,
    fine: int | None,
) -> None:
    inst, changes = instrument("BTCUSDT"), dict[str, Any](_HANDLES[handle])
    if fine is not None:  # qty_step under min_order_qty, so a rung can floor under the minimum
        inst = inst.model_copy(update={"qty_step": D("0.0001")})
        share = D(fine) / 100
        changes["tp_ladder"] = [{"qty_pct": share, "r": "1"}, {"qty_pct": 1 - share, "r": "2"}]
    p = profile(handle, **changes, max_position_notional=notional_cap)
    lev_cap = p.max_leverage_cap
    assert lev_cap is not None
    p = p.model_copy(update={"leverage": min(D(leverage), lev_cap)})
    cap = _daily_cap(p, equity)
    lost = _cent(cap * lost)
    held = _cent((cap - lost) * held)
    w = wallet(str(equity), str(taker), realised_loss_today=lost, committed_risk=held)
    counts = dict.fromkeys(
        ("open_positions_after", "open_orders_after", "orders_in_minute_after"), 1
    )
    w = w.model_copy(update={"available_margin": equity * margin_share} | counts)
    prices = sz.SizingMarket(mid=mid, last_price=ref, atr=_ATR)
    got = sized(p, w, prices, inst, side=side, price=None if market else str(ref))
    event(f"{'market' if market else 'limit'} {got.outcome} {got.reason}")
    event(f"binding {got.binding and got.binding.cap}")
    assert all(c.limit >= 0 for c in got.clamps)  # an overspent room is recorded as 0
    if got.qty is not None and got.ref_price is not None:  # never above a cap, restated plainly
        px = got.ref_price  # the anchor, or mid above a marketable sell's anchor
        if got.ref_source == "marketable_limit_worst_fill" and got.mid_price is not None:
            px = max(got.ref_price, got.mid_price)
        assert got.qty * px <= notional_cap
        assert got.qty <= inst.max_order_qty
        assert not market or got.qty <= inst.max_mkt_order_qty
        assert got.qty * px <= lev_cap * equity
        if p.max_position_pct_equity is not None:
            assert got.qty * px <= p.max_position_pct_equity * equity
    if got.outcome != "ok":
        return
    assert got.qty is not None and got.ref_price is not None and w.available_margin is not None
    margin = _CEIL.divide(_CEIL.multiply(got.qty, px), p.leverage)  # R6 at the larger notional
    assert got.initial_margin == margin
    assert margin <= _CEIL.multiply(w.available_margin, MARGIN_SHARE)
    leg = _resolved(p, got, side)
    verdict = judge_leg(p, leg, baseline=leg, instrument=inst, figures=w)
    broken = [] if not isinstance(verdict, Refused) else verdict.violations
    assert [v for v in broken if v.rule in {"R1", "R2", "R5", "R6", "R7"}] == []
    assert sum(tp.qty for tp in got.tps) <= got.qty
    assert all(tp.qty >= inst.min_order_qty for tp in got.tps)  # no rung under the minimum
    for tp in got.tps:  # each rung on the comparator's take-profit row
        rung = leg.model_copy(update={"take_profit_price": tp.price})
        # The rung is its own baseline: the sizer is the bound profile's leg, so only the
        # wrong-side and off-grid checks can fire (never `further_than_bound`).
        verdict = judge_leg(p, rung, baseline=rung, instrument=inst, figures=w)
        broken = [] if not isinstance(verdict, Refused) else verdict.violations
        assert [v for v in broken if v.field == "tp_offset_value"] == []


@settings(max_examples=200)
@given(
    low=st.integers(1, 1000).map(lambda n: D(n) / 10_000),
    more=st.integers(0, 1000).map(lambda n: D(n) / 10_000),
    equity=_money(1_000, 1_000_000),
    taker=_money(0, 2, 6).map(lambda n: n / 1000),
    side=st.sampled_from(["buy", "sell"]),
)
def test_size_leg_quantity_is_monotone_in_risk(
    low: Decimal, more: Decimal, equity: Decimal, taker: Decimal, side: str
) -> None:
    w = wallet(str(equity), str(taker))
    lower, higher = (
        sized(profile("P-RISK", risk_pct_equity=risk), w, side=side) for risk in (low, low + more)
    )
    assert lower.qty is not None and higher.qty is not None
    assert lower.qty <= higher.qty
