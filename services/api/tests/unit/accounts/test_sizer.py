"""E28-T03 (#907) PR1: the sizer's gate, reference price, stops, modes, fees, floor and minimums,
on the E28 fixture profiles and the 2026-10-05 capture's instruments (C-13.5)."""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.accounts import sizer as sz
from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import parse_instrument
from tests._corpus import rest

D = Decimal
_E28: Final = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "e28"
_FROZEN: Final = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
_ATR: Final = sz.AtrReading(period=14, value=D(400))
#: Gherkin: V01 the 0.416 example, V04 below the minimum lot, V05 5 % of equity, V06 the ATR
#: warm-up fallback, V07 a short's conservative stop, V12 a symbol not allowed. No cap binds in
#: any of these and no margin check fails, so PR1's steps fully determine them.
_PR1_VECTORS: Final = ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V12", "V14")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def profile(handle: str, **changes: Any) -> AccountProfile:
    spec = _json(_E28 / "profiles.json")[handle]
    base = _json(_FROZEN / spec["from"])
    return AccountProfile.model_validate({**base, **spec["set"], **changes})


@cache
def instrument(symbol: str) -> Instrument:
    rows = rest("rest/instruments_before.json", capture_date="2026-10-05")["result"]["list"]
    return parse_instrument(next(r for r in rows if r["symbol"] == symbol), fetched_at_us=0)


def wallet(equity: str | None = "10000", taker: str | None = "0") -> AccountFigures:
    known = {"equity": equity, "available_margin": equity, "taker_fee_rate": taker}
    return AccountFigures.model_validate(dict.fromkeys(AccountFigures.model_fields) | known)


def sized(p: AccountProfile, w: Any = None, market: Any = None, **intent: Any) -> sz.LegSizing:
    i = {"symbol": "BTCUSDT", "side": "buy", "price": "64000.0"} | intent
    i["order_type"] = "market" if i["price"] is None else "limit"
    it = sz.SizingIntent.model_validate(i)
    return sz.size_leg(it, p, w or wallet(), instrument(it.symbol), market or sz.SizingMarket())


@pytest.mark.parametrize("vid", _PR1_VECTORS)
def test_size_leg_pr1_golden_vector_matches(vid: str) -> None:
    v = next(x for x in _json(_E28 / "golden_sizing_vectors.json") if x["id"] == vid)
    i = {k: v["intent"][k] for k in ("symbol", "price")} | {"side": v["intent"]["side"].lower()}
    want, also = v["expected"], v.get("also", {})
    atr = v["market"]["atr"] and sz.AtrReading(period=14, value=D(v["market"]["atr"]))
    w = wallet(v["wallet"]["equity"], v["market"]["taker_fee_rate"])
    p = profile(v["profile"]["id"], **v["profile"]["set"])
    got = sized(p, w, sz.SizingMarket(atr=atr or None), **i)
    assert (got.outcome, got.reason) == (want["outcome"], want.get("code"))
    for name in ("qty", "notional", "risk_usdt", "risk_with_fees_usdt"):
        if name in want or name in also:
            assert getattr(got, name) == D({**also, **want}[name]), name
    if "stop" in want:
        stop = (D(want["stop"]), also.get("stop_fallback", False))
        assert got.stop is not None
        assert (got.stop.price, got.stop.fallback) == stop
    for kind in ("min_order_qty", "min_notional"):
        if kind in also:
            assert got.minimum == (kind, D(also[kind]))


def test_size_leg_below_min_leg_notional_names_the_profile_minimum() -> None:
    got = sized(profile("P-QTY", min_leg_notional="1000"))  # 0.01 BTC = 640 USDT
    assert (got.reason, got.minimum) == (
        sz.SkipReason.BELOW_MIN_NOTIONAL,
        ("min_leg_notional", D(1000)),
    )


@pytest.mark.parametrize(
    ("p", "symbol", "reason"),
    [
        (profile("P-RISK", enabled=False), "BTCUSDT", sz.SkipReason.PROFILE_DISABLED),
        (profile("P-RISK", trading_enabled=False), "BTCUSDT", sz.SkipReason.PROFILE_DISABLED),
        (profile("P-RISK"), "SOLUSDT", sz.SkipReason.SYMBOL_NOT_ALLOWED),  # allows BTC and ETH
        (profile("P-PCT", denied_symbols=["SOLUSDT"]), "SOLUSDT", sz.SkipReason.SYMBOL_DENIED),
    ],
)
def test_size_leg_gate_skips_with_nothing_sized(
    p: AccountProfile, symbol: str, reason: sz.SkipReason
) -> None:
    assert sized(p, symbol=symbol, price="150") == sz.LegSizing("skip", reason)


@pytest.mark.parametrize(
    ("mid", "ref"),
    [(D(64001), D(64001)), (None, D(64002)), (None, None)],
    ids=["mid", "last", "none"],
)
def test_size_leg_market_order_takes_mid_then_last_else_fails(mid: Any, ref: Any) -> None:
    market = sz.SizingMarket(mid=mid, last_price=ref and D(64002))
    got = sized(profile("P-QTY"), price=None, market=market)
    assert (got.ref_price, got.reason == sz.FailReason.NO_REFERENCE_PRICE) == (ref, ref is None)


def test_size_leg_stop_at_or_below_zero_fails_invalid_stop_distance() -> None:
    got = sized(profile("P-RISK", sl_offset_value="640000"))  # 64 000 USDT below a 64 000 entry
    assert (got.outcome, got.reason) == ("fail", sz.FailReason.INVALID_STOP_DISTANCE)


@pytest.mark.parametrize(
    ("handle", "unknown"), [("P-PCT", "equity"), ("P-RISK", "equity"), ("P-RISK", "taker")]
)
def test_size_leg_unknown_figure_fails_closed(handle: str, unknown: str) -> None:
    got = sized(profile(handle), w=wallet(**{unknown: None}), market=sz.SizingMarket(atr=_ATR))
    assert got.reason == sz.FailReason.FIGURE_UNKNOWN


def test_size_leg_risk_fixed_amount_is_the_budget() -> None:
    assert sized(profile("P-RISK", risk_pct_equity=None, risk_fixed_amount="24")).qty == D("0.2")


def test_size_leg_short_exit_fee_is_priced_at_the_stop() -> None:
    got = sized(profile("P-RISK"), wallet(taker="0.001"), side="sell")
    # stop 64120.0; fee per unit (64000 + 64120) * 0.001 = 128.12; 50 / 248.12 = 0.2015
    assert (got.qty, got.risk_with_fees_usdt) == (D("0.201"), D("0.201") * D("248.12"))


def test_size_leg_programming_errors_raise() -> None:
    it = sz.SizingIntent(symbol="BTCUSDT", side="buy", order_type="market")
    with pytest.raises(ValueError, match="different symbols"):
        sz.size_leg(it, profile("P-RISK"), wallet(), instrument("ETHUSDT"), sz.SizingMarket())
    with pytest.raises(TypeError):
        sz.LegSizing("skip", sz.FailReason.CAP_BREACHED)


@pytest.mark.parametrize(
    ("unit", "value", "atr", "side", "stop", "fallback"),
    [
        ("ticks", "1200", None, "buy", "63880.0", False),  # 63880.05 floors away from entry
        ("ticks", "1200", None, "sell", "64120.1", False),  # 64120.05 ceils away from entry
        ("percent", "0.01", None, "buy", "63360.0", False),  # 63360.0495
        ("percent", "0.01", None, "sell", "64640.1", False),  # 64640.0505
        ("atr", "1", _ATR, "buy", "63400.0", False),  # 400 * 1.5 below 64000.05
        ("atr", "1", _ATR, "sell", "64600.1", False),
        ("atr", "1", None, "buy", "62720.0", True),  # the 2 % fallback: 62720.049
        ("atr", "1", sz.AtrReading(period=14, value=None), "sell", "65280.1", True),  # warm-up
        (
            "atr",
            "1",
            sz.AtrReading(period=20, value=D(400)),
            "buy",
            "62720.0",
            True,
        ),  # other period
    ],
)
def test_resolve_stop_rounds_away_from_entry(
    unit: str, value: str, atr: sz.AtrReading | None, side: Any, stop: str, fallback: bool
) -> None:
    p = profile("P-PCT", sl_offset_unit=unit, sl_offset_value=value)
    got, want = sz.resolve_stop(side, p, D("64000.05"), instrument("BTCUSDT"), atr), D(stop)
    assert (got.price, got.distance, got.fallback) == (want, abs(D("64000.05") - want), fallback)


def test_resolve_stop_r_multiple_is_refused_by_the_profile_and_the_resolver() -> None:
    with pytest.raises(ValidationError):
        profile("P-RISK", sl_offset_unit="r_multiple")
    forged = profile("P-RISK").model_copy(update={"sl_offset_unit": "r_multiple"})
    with pytest.raises(ValueError, match="r_multiple"):
        sz.resolve_stop("buy", forged, D(64000), instrument("BTCUSDT"), None)


def _has_float(value: object) -> bool:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return any(_has_float(getattr(value, f.name)) for f in dataclasses.fields(value))
    return isinstance(value, float)


@settings(max_examples=300)
@given(
    equity=st.decimals(min_value=D(1), max_value=D(10_000_000), places=2),
    risk_pct=st.decimals(min_value=D("0.0001"), max_value=D("0.05"), places=4),
    ticks=st.integers(min_value=1, max_value=50_000),
    taker=st.decimals(min_value=D(0), max_value=D("0.002"), places=5),
    ref=st.decimals(min_value=D(10_000), max_value=D(200_000), places=2),
    side=st.sampled_from(["buy", "sell"]),
)
def test_size_leg_risk_based_never_exceeds_budget_and_lands_on_the_lot(
    equity: Decimal, risk_pct: Decimal, ticks: int, taker: Decimal, ref: Decimal, side: str
) -> None:
    p = profile("P-RISK", risk_pct_equity=risk_pct, sl_offset_value=ticks, min_leg_notional=0)
    got = sized(p, wallet(str(equity), str(taker)), side=side, price=str(ref))
    assert not _has_float(got)  # (d)
    assert got.qty is not None
    assert got.qty >= 0
    assert got.qty % instrument("BTCUSDT").qty_step == 0  # (b)
    assert got.risk_with_fees_usdt is not None
    assert got.risk_with_fees_usdt <= equity * risk_pct  # (a), fees included, so 1R too
