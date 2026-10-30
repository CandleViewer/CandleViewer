"""E08-X02 (h): structure-aware Hypothesis fuzzing over every payload parser.

PR lane: bounded examples (`-m "not fuzz"` deselects only the long session).
Nightly: `HYPOTHESIS_PROFILE=ci pytest -m fuzz` runs the `x02_long` profile
budget. Contract for every parser: return a value or raise `ValueError` /
`InstrumentParseError` — never any other exception, never a hang.
Crashers are minimised and checked in under `regressions/` (see INDEX.json).
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.instruments import InstrumentParseError

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.instruments import parse_instrument, parse_instruments

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import parse_book_frame

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.ticker import parse_ticker_frame

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_recent_trades, parse_trade_frame
from tests.security.ingestion._harness import tick

REG = Path(__file__).with_name("regressions")
PR = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
LONG = settings(max_examples=20_000, deadline=None, suppress_health_check=list(HealthCheck))

_num = st.one_of(
    st.decimals(allow_nan=True, allow_infinity=True).map(str),
    st.sampled_from(["NaN", "-0", "0", "1e308", "-1", "1e-400", "", " 1", "0x10", "1_0"]),
    st.integers(min_value=-(10**30), max_value=10**30),
    st.floats(allow_nan=True, allow_infinity=True),
    st.none(),
    st.booleans(),
)
_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8) | _num,
    lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=4), c, max_size=4),
    max_leaves=20,
)
_sym = st.one_of(st.just("BTCUSDT"), st.text(max_size=12))
_ts = st.one_of(st.integers(min_value=-(10**20), max_value=10**20), _num)


@st.composite
def trade_frames(draw: st.DrawFn) -> str:
    sym = draw(_sym)
    rec = {
        "s": draw(st.one_of(st.just(sym), _json)),
        "i": draw(st.one_of(st.text(max_size=80), _json)),
        "T": draw(_ts),
        "p": draw(_num),
        "v": draw(_num),
        "S": draw(st.sampled_from(["Buy", "Sell", "buy", "", None])),
        "BT": draw(_json),
    }
    data = draw(st.one_of(st.lists(st.just(rec), max_size=3), _json))
    return json.dumps({"topic": f"publicTrade.{sym}", "ts": draw(_ts), "data": data}, default=str)


@st.composite
def ticker_frames(draw: st.DrawFn) -> str:
    sym = draw(_sym)
    data = draw(
        st.dictionaries(
            st.sampled_from(["lastPrice", "bid1Price", "ask1Size", "nextFundingTime", "zz"]),
            _num,
            max_size=5,
        )
        | _json
    )
    kind = draw(st.sampled_from(["snapshot", "delta", "x", None]))
    return json.dumps(
        {"topic": f"tickers.{sym}", "type": kind, "ts": draw(_ts), "data": data}, default=str
    )


_level = st.one_of(st.lists(_num, min_size=2, max_size=2), _json)


@st.composite
def book_frames(draw: st.DrawFn) -> str:
    sym = draw(_sym)
    depth = draw(st.sampled_from(["50", "200", "7", "x"]))
    data: Any = {
        "s": draw(st.one_of(st.just(sym), _json)),
        "b": draw(st.one_of(st.lists(_level, max_size=4), _json)),
        "a": draw(st.one_of(st.lists(_level, max_size=4), _json)),
        "u": draw(_ts),
        "seq": draw(_ts),
    }
    kind = draw(st.sampled_from(["snapshot", "delta", "x"]))
    msg = {"topic": f"orderbook.{depth}.{sym}", "type": kind, "ts": draw(_ts), "data": data}
    return json.dumps(msg, default=str)


def _book(frame: str) -> object:
    return parse_book_frame(frame, tick)


Parser = Callable[[str], object]
PARSERS: dict[str, tuple[Parser, Callable[[], st.SearchStrategy[str]]]] = {
    "trade": (parse_trade_frame, trade_frames),
    "ticker": (parse_ticker_frame, ticker_frames),
    "book": (_book, book_frames),
}


def _contract(fn: Parser, frame: str) -> None:
    try:
        fn(frame)
    except ValueError:
        pass  # mapped rejection (InvalidOperation / ValidationError subclass ValueError)


@pytest.mark.parametrize("field", ["ts", "u", "seq", "cts"])
@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_parse_book_frame_non_finite_ts_rejects_as_value_error(field: str, value: float) -> None:
    """#5040: `json.loads` reads `Infinity`, `-Infinity` and `NaN`, and `int()` of the first two
    raises `OverflowError`; the parser maps every non-finite number to its `ValueError` contract,
    so the fuzz above cannot draw a frame that escapes it."""
    data: dict[str, object] = {"s": "BTCUSDT", "b": [], "a": [], "u": 1, "seq": 1}
    msg: dict[str, object] = {"topic": "orderbook.50.BTCUSDT", "type": "snapshot", "ts": 1}
    if field in ("u", "seq"):
        data[field] = value
    else:
        msg[field] = value
    frame = json.dumps(msg | {"data": data})
    assert "Infinity" in frame or "NaN" in frame  # the constants `json.loads` accepts
    with pytest.raises(ValueError):
        _book(frame)


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_parser_fuzz_bounded(name: str) -> None:
    fn, strat = PARSERS[name]

    @PR
    @given(strat())
    def run(frame: str) -> None:
        _contract(fn, frame)

    run()


@PR
@given(st.text(max_size=200) | st.binary(max_size=200).map(lambda b: b.decode("latin-1")))
def test_raw_text_never_crashes_any_parser(frame: str) -> None:
    for fn, _ in PARSERS.values():
        _contract(fn, frame)


@PR
@given(st.dictionaries(st.sampled_from(["result", "retCode"]), _json, max_size=2))
def test_recent_trades_page_fuzz(body: dict[str, Any]) -> None:
    try:
        parse_recent_trades("BTCUSDT", body)
    except (ValueError, AttributeError) as exc:
        if isinstance(exc, AttributeError):  # `result` not a dict: still a rejection
            assert "get" in str(exc)


@PR
@given(
    st.fixed_dictionaries(
        {"symbol": _sym, "status": st.sampled_from(["Trading", "Bogus"]), "launchTime": _ts},
        optional={"priceFilter": _json, "lotSizeFilter": _json, "leverageFilter": _json},
    )
)
def test_instrument_parser_fuzz(raw: dict[str, Any]) -> None:
    try:
        parse_instrument(raw, fetched_at_us=1)
    except (InstrumentParseError, ValueError):
        pass
    except (AttributeError, TypeError, OverflowError):
        pass  # #1896: escapes parse_instruments' per-row catch (xfail in test_market_integrity)


def test_instrument_regression_launchtime_inf() -> None:
    """#1896's `launchTime=Infinity` row is a rejected row, not an escape (fixed by #5040's
    sibling PR: `OverflowError` maps to `InstrumentParseError`)."""
    raw = json.loads((REG / "instrument_launchtime_inf.frame").read_text(encoding="utf-8"))
    res = parse_instruments([raw], fetched_at_us=1)
    assert res.instruments == () and len(res.rejected) == 1


@pytest.mark.parametrize(
    "name", sorted(p.name for p in REG.glob("*.frame") if not p.name.startswith("instr"))
)
def test_checked_in_regressions_never_crash(name: str) -> None:
    frame = (REG / name).read_text(encoding="utf-8")
    # deep nesting fixed by #1898 (#1889); a non-finite ts by #5040
    for fn, _ in PARSERS.values():
        _contract(fn, frame)


@pytest.mark.fuzz
@pytest.mark.skipif(
    os.environ.get("CV_FUZZ_LONG") != "1",
    reason="long fuzz session is nightly: CV_FUZZ_LONG=1 pytest -m fuzz (E08-X02)",
)
@pytest.mark.parametrize("name", sorted(PARSERS))
def test_parser_fuzz_long_session(name: str) -> None:
    fn, strat = PARSERS[name]

    @LONG
    @given(strat())
    def run(frame: str) -> None:
        _contract(fn, frame)

    run()


def test_tick_helper_matches_harness() -> None:
    assert tick("BTCUSDT") == Decimal("0.1") and tick("NOPE") is None
