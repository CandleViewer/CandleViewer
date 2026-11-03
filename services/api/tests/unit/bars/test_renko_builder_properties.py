"""Renko properties (E12-S04): BI-1 with single allocation, BI-2, BI-4, BI-5 at random cuts."""

from __future__ import annotations

from decimal import Decimal as D
from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.renko_builder import RenkoBarBuilder, RenkoBarUpdate
from candleviewer.exchange.base.models import TradeEvent
from tests.unit.bars._trades import SYM, final_bars, trade

# Prices on a 0.1 grid with big jumps so multi-brick trades and reversals are common.
_trades = st.lists(
    st.tuples(st.integers(900, 1100), st.integers(1, 40), st.booleans(), st.integers(0, 3)),
    min_size=1,
    max_size=150,
)


def _tape(raw: list[tuple[int, int, bool, int]]) -> list[TradeEvent]:
    ts, out = 0, []
    for i, (p, q, buy, dt) in enumerate(raw):
        ts += dt
        out.append(trade(ts, D(p) / 10, q, "buy" if buy else "sell", seq=i))
    return out


def _mk(ticks: int, rev: int, wick: bool) -> RenkoBarBuilder:
    spec = BarSpec(kind="renko", range_ticks=ticks, reversal_bricks=rev, renko_wick=wick)
    return RenkoBarBuilder(spec, SYM, lambda _s: D("0.1"))


def _feed(b: RenkoBarBuilder, tape: list[TradeEvent]) -> list[BarUpdate]:
    out: list[BarUpdate] = []
    for t in tape:
        out += b.on_trade(t)
    return out


_cfg = {"ticks": st.integers(2, 40), "rev": st.integers(1, 4), "wick": st.booleans()}


@settings(max_examples=200, deadline=None)
@given(raw=_trades, **_cfg)
def test_renko_invariants(
    raw: list[tuple[int, int, bool, int]], ticks: int, rev: int, wick: bool
) -> None:
    tape = _tape(raw)
    built = _mk(ticks, rev, wick)
    ups = _feed(built, tape)
    bars = final_bars(ups, built)
    w = D(ticks) / 10
    assert [x.index for x in bars] == list(range(len(bars)))
    assert sum(x.volume for x in bars) == sum(t.qty for t in tape)  # BI-1, single allocation
    assert sum(x.trade_count for x in bars) == len(tape)
    for x in bars:
        assert x.delta == x.buy_volume - x.sell_volume  # BI-2
        assert x.low <= min(x.open, x.close) and x.high >= max(x.open, x.close)
        if not wick:
            assert (x.high, x.low) == (max(x.open, x.close), min(x.open, x.close)) or not x.closed
    done = [x for x in bars if x.closed]
    for x in done:
        assert abs(x.close - x.open) == w
    for p, n in pairwise(done):  # contiguous grid: continuation or reversal at R-1 bricks back
        up_p, up_n = p.close > p.open, n.close > n.open
        assert (
            n.open == p.close
            if up_p == up_n
            else n.open == p.close + (rev - 1) * (p.open - p.close)
        )
    # every emission group: exactly one owner, the last one, carries the volume
    for u in ups:
        assert isinstance(u, RenkoBarUpdate)
        if not u.volume_allocated:
            assert u.bar.volume == 0 and u.bar.trade_count == 0
    # BI-4 determinism
    again = _mk(ticks, rev, wick)
    assert final_bars(_feed(again, tape), again) == bars


@settings(max_examples=200, deadline=None)
@given(raw=_trades, cut=st.integers(0, 150), **_cfg)
def test_renko_restore_at_any_cut_matches_uninterrupted(
    raw: list[tuple[int, int, bool, int]], cut: int, ticks: int, rev: int, wick: bool
) -> None:
    tape = _tape(raw)
    cut = min(cut, len(tape))
    whole = _mk(ticks, rev, wick)
    full = _feed(whole, tape)
    pre = _mk(ticks, rev, wick)
    head = _feed(pre, tape[:cut])
    post = _mk(ticks, rev, wick)
    post.restore(pre.snapshot())
    assert head + _feed(post, tape[cut:]) == full  # BI-5
    assert post.forming() == whole.forming()  # the forming brick too (#2022)


def test_renko_restore_cut_spanning_a_reversal() -> None:
    tape = _tape([(1000, 1, True, 1), (1010, 1, True, 1), (1005, 2, False, 1), (1000, 3, False, 1),
                  (990, 1, False, 1), (1010, 1, True, 1)])  # fmt: skip
    full = _feed(_mk(10, 2, False), tape)
    for cut in range(len(tape) + 1):
        pre = _mk(10, 2, False)
        head = _feed(pre, tape[:cut])
        post = _mk(10, 2, False)
        post.restore(pre.snapshot())
        assert head + _feed(post, tape[cut:]) == full
