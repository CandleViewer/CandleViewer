"""E28-T03 (#907): the sizer's gate, reference price, stops, modes, fees, floor and minimums,
on the E28 fixture profiles and the 2026-10-05 capture's instruments (C-13.5)."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from functools import cache
from pathlib import Path
from typing import Any, Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from candleviewer.accounts import sizer as sz
from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import parse_instrument
from tests._corpus import rest

D = Decimal
_E28: Final = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "e28"
_FROZEN: Final = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"


def atr(value: Decimal | None, period: int = 14) -> sz.AtrReading:
    as_of = datetime(2026, 10, 5, tzinfo=UTC)
    return sz.AtrReading(timeframe="1h", period=period, value=value, as_of=as_of)


_ATR: Final = atr(D(400))


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


def wallet(equity: str | None = "10000", taker: str | None = "0", **known: Any) -> AccountFigures:
    known = {"equity": equity, "available_margin": equity, "taker_fee_rate": taker} | known
    known = {"realised_loss_today": "0", "committed_risk": "0"} | known
    return AccountFigures.model_validate(dict.fromkeys(AccountFigures.model_fields) | known)


def sized(
    p: AccountProfile, w: Any = None, market: Any = None, inst: Any = None, **intent: Any
) -> sz.LegSizing:
    i = {"symbol": "BTCUSDT", "side": "buy", "price": "64000.0"} | intent
    i["order_type"] = "market" if i["price"] is None else "limit"
    it = sz.SizingIntent.model_validate(i)
    inst = inst or instrument(it.symbol)
    return sz.size_leg(it, p, w or wallet(), inst, market or sz.SizingMarket())


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
    ("mid", "last", "ref", "source"),
    [
        (D(64001), D(64002), D(64001), "mid"),
        (None, D(64002), D(64002), "last"),
        (None, None, None, None),
    ],
    ids=["mid", "last", "none"],
)
def test_size_leg_market_order_takes_mid_then_last_else_fails(
    mid: Any, last: Any, ref: Any, source: Any
) -> None:
    got = sized(profile("P-QTY"), price=None, market=sz.SizingMarket(mid=mid, last_price=last))
    assert (got.ref_price, got.ref_source) == (ref, source)
    assert (got.reason == sz.FailReason.NO_REFERENCE_PRICE) == (ref is None)


@pytest.mark.parametrize(
    ("side", "limit", "mid", "ref", "source"),
    [
        ("buy", "64100", D(64000), "64100", "marketable_limit_worst_fill"),  # above mid: limit
        ("sell", "63900", D(64000), "63900", "marketable_limit_worst_fill"),  # below mid: limit
        ("buy", "64000", D(64000), "64000", "marketable_limit_worst_fill"),  # a buy at mid
        ("sell", "64000", D(64000), "64000", "marketable_limit_worst_fill"),  # a sell at mid
        ("buy", "63900", D(64000), "63900", "limit"),  # rests below mid
        ("buy", "64100", None, "64100", "limit"),  # no mid: the limit
    ],
    ids=[
        "marketable-buy",
        "marketable-sell",
        "buy-at-mid",
        "sell-at-mid",
        "non-marketable",
        "no-mid",
    ],
)
def test_size_leg_marketable_limit_sizes_and_stops_at_the_worst_case_fill(
    side: str, limit: str, mid: Any, ref: str, source: str
) -> None:
    got = sized(profile("P-RISK"), market=sz.SizingMarket(mid=mid), side=side, price=limit)
    stop = D(ref) - D(120) if side == "buy" else D(ref) + D(120)  # 1200 ticks of 0.1
    assert (got.ref_price, got.ref_source, got.limit_price) == (D(ref), source, D(limit))
    assert got.mid_price == mid  # the explanation keeps both the mid and the limit
    assert got.stop is not None
    assert got.stop.price == stop


def test_size_leg_market_order_sizes_at_mid_not_last() -> None:
    market = sz.SizingMarket(mid=D(64000), last_price=D(32000))
    got, at_mid = sized(profile("P-PCT"), price=None, market=market), sized(profile("P-PCT"))
    assert (got.ref_price, got.qty, got.notional) == (D(64000), at_mid.qty, at_mid.notional)


@pytest.mark.parametrize(
    "intent",
    [
        {"order_type": "market", "price": "32000"},
        {"order_type": "limit"},
        {"order_type": "limit", "price": "1" * 40},
    ],
    ids=["market-with-price", "limit-without-price", "40-digit-price"],
)
def test_sizing_intent_refuses_a_price_against_the_order_type_or_too_long(intent: Any) -> None:
    with pytest.raises(ValidationError):
        sz.SizingIntent.model_validate({"symbol": "BTCUSDT", "side": "buy"} | intent)


@pytest.mark.parametrize(
    ("p", "side"),
    [
        (profile("P-RISK", sl_offset_value="640000"), "buy"),  # 64 000 USDT below a 64 000 entry
        # a forged sub-1e-100 offset rounds back onto a short's entry: distance 0, taker 0
        (profile("P-RISK").model_copy(update={"sl_offset_value": D("1e-120")}), "sell"),
    ],
    ids=["stop-at-zero", "zero-distance"],
)
def test_size_leg_stop_at_zero_or_zero_distance_fails_invalid_stop_distance(
    p: AccountProfile, side: str
) -> None:
    got = sized(p, side=side)
    assert (got.outcome, got.reason) == ("fail", sz.FailReason.INVALID_STOP_DISTANCE)


@pytest.mark.parametrize(
    ("handle", "unknown"),
    [
        ("P-PCT", "equity"),
        ("P-RISK", "equity"),
        ("P-RISK", "taker"),
        ("P-QTY", "equity"),  # the caps read it
        ("P-QTY", "taker"),  # the daily room's loss per unit
        ("P-QTY", "realised_loss_today"),
        ("P-QTY", "committed_risk"),
        ("P-QTY", "available_margin"),  # step 8b
    ],
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
    side: Any = "Buy"  # not a `Side`: never a short by default
    with pytest.raises(ValueError, match="side 'Buy'"):
        sz.resolve_stop(side, profile("P-RISK"), D(64000), instrument("BTCUSDT"), None)


_BTC_QUARTER: Final = instrument("BTCUSDT").model_copy(update={"qty_step": D("0.25")})
_BTC_FINE: Final = instrument("BTCUSDT").model_copy(update={"qty_step": D("0.0001")})
_MIN_LOT: Final = ("min_order_qty", D("0.001"))  # BTCUSDT's; min_notional 5


@pytest.mark.parametrize(
    ("p", "w", "inst", "price", "qty", "minimum"),
    [
        (profile("P-PCT"), wallet(), _BTC_QUARTER, "300", "16.5", None),  # 5000 / 300 = 16.67
        (profile("P-PCT"), wallet("1E+12"), None, "64000", "100", None),  # max_order_qty
        (profile("P-PCT"), wallet("0"), None, "64000", "0", _MIN_LOT),
        (
            profile("P-PCT"),
            wallet().model_copy(update={"equity": D(-1)}),
            None,
            "64000",
            "0",  # clamped, never a negative leg
            _MIN_LOT,
        ),
        # 0.0005 misses the minimum lot and, at 0.05 USDT, the minimum notional: the lot is named
        (profile("P-QTY", fixed_qty="0.0005"), wallet(), _BTC_FINE, "100", "0.0005", _MIN_LOT),
        # a fixed size at equity 0 is clamped to 0 by max_leverage_cap: red, not grey (24 Sec.9.3.4)
        (profile("P-QTY"), wallet("0"), None, "64000", "0", ("cap_breached", *_MIN_LOT)),
    ],
    ids=[
        "step-0.25",
        "huge-qty",
        "equity-0",
        "equity-negative",
        "both-minimums-missed",
        "equity-0-fixed-qty",
    ],
)
def test_size_leg_edge_cases(
    p: AccountProfile, w: AccountFigures, inst: Any, price: str, qty: str, minimum: Any
) -> None:
    got = sized(p, w, inst=inst, price=price)
    want: tuple[str, Any] = ("ok", None)
    if minimum is not None:
        want = ("skip", sz.SkipReason.BELOW_MIN_NOTIONAL)
    if minimum is not None and minimum[0] == "cap_breached":
        want, minimum = ("fail", sz.FailReason.CAP_BREACHED), minimum[1:]
        assert got.binding is not None and got.binding.cap == "max_leverage_cap"
    assert (got.outcome, got.reason, got.qty, got.minimum) == (*want, D(qty), minimum)


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
        ("atr", "1", atr(None), "sell", "65280.1", True),  # warm-up
        (
            "atr",
            "1",
            atr(D(400), period=20),
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
        value = [getattr(value, f.name) for f in dataclasses.fields(value)]
    elif isinstance(value, BaseModel):
        value = list(value.model_dump().values())
    if isinstance(value, tuple | list):
        return any(_has_float(v) for v in value)
    return isinstance(value, float)


def test_has_float_descends_into_the_minimum() -> None:
    minimum: Any = ("min_order_qty", 0.001)
    assert _has_float(sz.LegSizing("skip", sz.SkipReason.BELOW_MIN_NOTIONAL, minimum=minimum))


_RED: Final = {sz.FailReason.CAP_BREACHED, sz.FailReason.INSUFFICIENT_MARGIN}
_UNITS: Final = {
    "ticks": st.integers(min_value=1, max_value=10_000).map(D),  # at most 5000 below a 10 000 ref
    "percent": st.decimals(min_value=D("0.0001"), max_value=D("0.2"), places=6),
    "atr": st.decimals(min_value=D("0.01"), max_value=D(2_000), places=18),  # the reading
}


@settings(max_examples=300)
@given(
    equity=st.decimals(min_value=D(1_000), max_value=D(10_000_000), places=18),
    risk_pct=st.decimals(min_value=D("0.001"), max_value=D("0.05"), places=6),
    stop=st.sampled_from(sorted(_UNITS)).flatmap(lambda u: st.tuples(st.just(u), _UNITS[u])),
    taker=st.decimals(min_value=D(0), max_value=D("0.002"), places=18),
    ref=st.decimals(min_value=D(10_000), max_value=D(200_000), places=18),
    side=st.sampled_from(["buy", "sell"]),
    step=st.sampled_from([D("0.001"), D("0.01"), D("0.1"), D("0.5")]),
    tick=st.sampled_from([D("0.01"), D("0.1"), D("0.25"), D("0.5")]),
)
def test_size_leg_risk_based_never_exceeds_budget_and_lands_on_the_lot(
    equity: Decimal,
    risk_pct: Decimal,
    stop: tuple[str, Decimal],
    taker: Decimal,
    ref: Decimal,
    side: str,
    step: Decimal,
    tick: Decimal,
) -> None:
    unit, value = stop
    p = profile("P-RISK", risk_pct_equity=risk_pct, min_leg_notional=0, sl_offset_unit=unit)
    p = p.model_copy(update={"sl_offset_value": D(1) if unit == "atr" else value})
    reading = atr(value, p.sl_atr_period) if unit == "atr" else None
    inst = instrument("BTCUSDT").model_copy(update={"qty_step": step, "tick_size": tick})
    got = sized(
        p,
        wallet(str(equity), str(taker)),
        sz.SizingMarket(atr=reading),
        inst,
        side=side,
        price=str(ref),
    )
    assert got.reason in {None, sz.SkipReason.BELOW_MIN_NOTIONAL, *_RED}
    assert not _has_float(got)  # (d)
    assert got.qty is not None and got.stop is not None and got.risk_with_fees_usdt is not None
    assert got.qty >= 0
    assert got.qty % step == 0  # (b)
    with localcontext() as ctx:
        ctx.prec = 100
        budget = equity * risk_pct
        per_unit = got.stop.distance + (ref + max(ref, got.stop.price)) * taker
        assert got.risk_with_fees_usdt <= budget  # (a), fees included, so 1R too
        # the floor is the floor: one more lot breaks the budget, unless a cap bound first
        assert got.binding is not None or (got.qty + step) * per_unit > budget
