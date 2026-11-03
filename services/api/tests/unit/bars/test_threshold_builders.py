"""Range and delta bar builders (E12-S03): Gherkin scenarios, edge cases, BI-1/4/5 properties."""

from __future__ import annotations

import types
from decimal import Decimal
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars import threshold_builders as tb
from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from candleviewer.exchange.base.models import TradeEvent
from tests.unit.bars._trades import SYM, closes, final_bars, trade

D = Decimal


def _range(ticks: int = 20, tick: str = "0.10") -> RangeBarBuilder:
    spec = BarSpec(kind="range", range_ticks=ticks)
    return RangeBarBuilder(spec, SYM, lambda s: D(tick) if s == SYM else None)


def _delta(thr: str = "2000") -> DeltaBarBuilder:
    return DeltaBarBuilder(BarSpec(kind="delta", delta_threshold=D(thr)), SYM)


def _feed(b: RangeBarBuilder | DeltaBarBuilder, ts: list[TradeEvent]) -> list[BarUpdate]:
    out: list[BarUpdate] = []
    for t in ts:
        out += b.on_trade(t)
    return out


def test_range_bar_closes_on_span_and_next_opens_at_close() -> None:
    b = _range()
    ups = _feed(b, [trade(1, "100.0", seq=0), trade(2, "101.0", seq=1), trade(3, "102.0", seq=2)])
    (c,) = closes(ups)
    assert (c.open, c.high, c.low, c.close, c.trade_count) == (D(100), D(102), D(100), D(102), 3)
    nxt = b.on_trade(trade(4, "102.5", seq=3))[0]
    assert (nxt.kind, nxt.bar.open, nxt.bar.gap_before, nxt.bar.index) == (
        "open",
        D("102.0"),
        False,
        1,
    )
    assert nxt.bar.high == D("102.5") and nxt.bar.low == D("102.0")
    assert nxt.open_source_ts == 4  # type: ignore[attr-defined]


def test_range_jump_emits_one_bar_no_phantoms_and_gap_before() -> None:
    b = _range(ticks=10)  # width 1.0
    ups = _feed(b, [trade(1, "100", seq=0), trade(2, "105", seq=1), trade(3, "105.2", seq=2)])
    bars = final_bars(ups, b)
    assert [x.index for x in bars] == [0, 1]
    assert bars[0].closed and bars[0].high == D(105) and bars[0].volume == D(2)
    assert bars[1].gap_before and not bars[0].gap_before
    assert bars[1].open == D(105)  # opens at the close, the following trade is the first in it
    assert sum(x.volume for x in bars) == D(3)  # BI-1
    # the flag belongs to the bar after the jump only, and stays on it while it is open
    assert b.on_trade(trade(4, "105.3", seq=3)) == ()  # extends the open bar (#2022)
    forming = b.forming()
    assert forming is not None and forming.bar.gap_before
    nxt = _feed(b, [trade(5, "106.4", seq=4), trade(6, "106.5", seq=5)])
    assert [u.kind for u in nxt] == ["close", "open"] and not nxt[-1].bar.gap_before


def test_range_closure_is_inclusive_and_exact_decimal() -> None:
    b = _range(ticks=3, tick="0.1")  # width 0.3, float(0.1)*3 != 0.3
    assert closes(_feed(b, [trade(1, "1.0", seq=0), trade(2, "1.3", seq=1)]))


def test_range_late_trade_joins_open_bar_and_open_stays_pinned() -> None:
    b = _range()
    _feed(b, [trade(5, "100", seq=0), trade(6, "102", seq=1)])  # closed at 102
    _feed(b, [trade(10, "102.5", seq=2)])
    assert b.on_trade(trade(3, "102.2", seq=3)) == ()  # joins the open bar, emits nothing
    forming = b.forming()
    assert forming is not None
    late = forming.bar
    assert late.index == 1 and late.open == D("102.0") and late.trade_count == 2


def test_range_requires_known_tick_size() -> None:
    spec = BarSpec(kind="range", range_ticks=5)
    with pytest.raises(BarSpecError, match="BTCUSDT"):
        RangeBarBuilder(spec, SYM, lambda s: None)
    with pytest.raises(BarSpecError):
        RangeBarBuilder(spec, SYM, lambda s: D(0))
    with pytest.raises(BarSpecError):
        RangeBarBuilder(BarSpec(kind="delta", delta_threshold=D(1)), SYM, lambda s: D(1))


def test_delta_closure_is_final_and_overshoot_is_not_split() -> None:
    b = _delta("2000")
    ups = _feed(b, [trade(1, qty="2000", seq=0), trade(2, qty="100", side="sell", seq=1)])
    first, second = ups
    assert first.kind == "close" and first.bar.delta == D(2000)
    assert second.kind == "open" and second.bar.index == 1 and second.bar.delta == D(-100)
    c = _feed(b, [trade(3, qty="1900", side="sell", seq=2)])
    assert c[0].kind == "close" and c[0].bar.delta == D(-2000)

    b2 = _delta("2000")
    _feed(b2, [trade(1, qty="1900", side="buy", seq=0)])
    (over,) = b2.on_trade(trade(2, qty="500", side="buy", seq=1))
    assert over.kind == "close" and over.bar.delta == D(2400) and over.bar.trade_count == 2
    assert getattr(over, "split_from_trade_id", None) is None
    assert (over.bar.min_delta, over.bar.max_delta) == (D(1900), D(2400))


def test_delta_negative_threshold_and_oscillation() -> None:
    b = _delta("10")
    ups = _feed(b, [trade(1, qty="6", side="sell", seq=0), trade(2, qty="3", seq=1)])
    assert not closes(ups)
    assert closes(_feed(b, [trade(3, qty="8", side="sell", seq=2)]))[0].delta == D(-11)


def test_guard_symbol_and_kind() -> None:
    with pytest.raises(BarsError):
        _delta().on_trade(trade(1, seq=0).model_copy(update={"symbol": "ETHUSDT"}))
    with pytest.raises(BarSpecError):
        DeltaBarBuilder(BarSpec(kind="range", range_ticks=3), SYM)


def test_high_emit_rate_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    stub = types.SimpleNamespace(warning=lambda ev, **kw: calls.append(ev))
    monkeypatch.setattr(tb, "_log", lambda: stub)
    b = _delta("1")
    _feed(b, [trade(i, seq=i) for i in range(1_100)])
    assert calls == ["bars_emit_rate_high"]


def test_range_snapshot_restore_incomplete_and_wrong_spec() -> None:
    b = _range()
    _feed(b, [trade(1, "100", seq=0), trade(2, "103", seq=1)])
    s = b.snapshot()
    fresh = _range()
    fresh.restore(s)
    assert fresh.snapshot().blob == s.blob
    with pytest.raises(BarsError):
        fresh.restore(s.model_copy(update={"blob": b'{"cur":null,"next":0}'}))
    with pytest.raises(BarsError):
        _range(ticks=21).restore(s)
    mid = _range()
    _feed(mid, [trade(1, "100", seq=0)])
    again = _range()
    again.restore(mid.snapshot())
    assert again.snapshot().blob == mid.snapshot().blob


_prices = st.integers(min_value=990, max_value=1010)
_trades = st.lists(
    st.tuples(_prices, st.integers(1, 40), st.booleans(), st.integers(0, 3)),
    min_size=1,
    max_size=120,
)


def _tape(raw: list[tuple[int, int, bool, int]]) -> list[TradeEvent]:
    ts = 0
    out = []
    for i, (p, q, buy, dt) in enumerate(raw):
        ts += dt
        out.append(trade(ts, D(p) / 10, q, "buy" if buy else "sell", seq=i))
    return out


@settings(max_examples=150, deadline=None)
@given(raw=_trades, ticks=st.integers(1, 30))
def test_range_properties(raw: list[tuple[int, int, bool, int]], ticks: int) -> None:
    tape = _tape(raw)
    b = _range(ticks=ticks, tick="0.1")
    ups = _feed(b, tape)
    bars = final_bars(ups, b)
    width = D(ticks) / 10
    assert [x.index for x in bars] == list(range(len(bars)))
    assert all(x.trade_count >= 1 and x.volume > 0 for x in bars)  # no phantom bars
    assert sum(x.volume for x in bars) == sum(t.qty for t in tape)  # BI-1
    assert sum(x.trade_count for x in bars) == len(tape)
    for x in bars[:-1]:
        assert x.closed and x.high - x.low >= width
    assert not bars[-1].closed or bars[-1].high - bars[-1].low >= width
    for prev, nxt in pairwise(bars):
        assert nxt.open == prev.close
    # BI-4 determinism
    again = _range(ticks=ticks, tick="0.1")
    assert final_bars(_feed(again, tape), again) == bars


@settings(max_examples=150, deadline=None)
@given(raw=_trades, thr=st.integers(1, 120), cut=st.integers(0, 120))
def test_delta_properties_and_restore_at_any_cut(
    raw: list[tuple[int, int, bool, int]], thr: int, cut: int
) -> None:
    tape = _tape(raw)
    built = _delta(str(thr))
    ups = _feed(built, tape)
    bars: list[Bar] = final_bars(ups, built)
    assert [x.index for x in bars] == list(range(len(bars)))
    assert sum(x.volume for x in bars) == sum(t.qty for t in tape)  # BI-1: no split, no loss
    assert sum(x.trade_count for x in bars) == len(tape)  # every trade in exactly one bar
    for x in bars[:-1]:
        assert x.closed and abs(x.delta) >= thr
    for x in bars:
        assert x.closed or abs(x.delta) < thr
    # BI-5: snapshot at any cut, restore into a fresh builder, same remaining output
    for make in (lambda: _delta(str(thr)), lambda: _range(ticks=max(1, thr // 10), tick="0.1")):
        cut_i = min(cut, len(tape))
        a = make()
        full = _feed(a, tape)
        pre = make()
        head = _feed(pre, tape[:cut_i])
        post = make()
        post.restore(pre.snapshot())
        assert head + _feed(post, tape[cut_i:]) == full
        assert post.forming() == a.forming()  # the forming bar too (#2022)
