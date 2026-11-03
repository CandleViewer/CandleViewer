"""Unit tests for tick and volume bars (E12-S02, `24-internal-schemas.md` §3.3)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from candleviewer.bars.activity_builders import (
    ActivityBarUpdate,
    TickBarBuilder,
    VolumeBarBuilder,
)
from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.models import BarSpec, BarUpdate, BuilderState
from candleviewer.exchange.base.models import TradeEvent
from tests.unit.bars._trades import SYM, closes, final_bars, trade

T0 = 1_700_000_000_000_000


def vol(threshold: str) -> VolumeBarBuilder:
    return VolumeBarBuilder(BarSpec(kind="volume", volume_threshold=Decimal(threshold)), SYM)


def tick(n: int) -> TickBarBuilder:
    return TickBarBuilder(BarSpec(kind="tick", tick_count=n), SYM)


def feed(b: TickBarBuilder | VolumeBarBuilder, trades: Sequence[TradeEvent]) -> list[BarUpdate]:
    out: list[BarUpdate] = []
    for t in trades:
        out += b.on_trade(t)
    return out


def test_volume_overshoot_closes_at_threshold_and_carries_remainder() -> None:
    b = vol("1500")
    feed(b, [trade(T0, "100", "1400", seq=1)])
    out = b.on_trade(trade(T0 + 5, "101", "300", side="sell", seq=2))
    assert [u.kind for u in out] == ["close", "open"]
    closed, opened = out[0].bar, out[1].bar
    assert closed.volume == Decimal("1500") and closed.close == Decimal("101")
    assert opened.volume == Decimal("200") and opened.open == Decimal("101")
    assert opened.open_time == T0 + 5 == closed.close_time
    assert opened.delta == Decimal("-200") and closed.delta == Decimal("1300")
    ids = {u.split_from_trade_id for u in out if isinstance(u, ActivityBarUpdate)}
    assert ids == {"2"}


def test_volume_huge_print_spans_several_thresholds() -> None:
    out = vol("1500").on_trade(trade(T0, "100", "5000", seq=7))
    bars = closes(out)
    assert [b.volume for b in bars] == [Decimal("1500")] * 3
    assert len({(b.open, b.high, b.low, b.close, b.open_time, b.close_time) for b in bars}) == 1
    assert [b.index for b in bars] == [0, 1, 2]
    assert out[-1].kind == "open" and out[-1].bar.volume == Decimal("500")
    assert out[-1].bar.index == 3 and not out[-1].bar.closed


def test_volume_one_million_size_print_is_bounded_and_exact() -> None:
    out = vol("1000").on_trade(trade(T0, "100", "1000000", seq=1))
    assert len(out) == 1000 and all(u.kind == "close" for u in out)
    assert sum(u.bar.volume for u in out) == Decimal("1000000")


def test_volume_exactly_at_threshold_closes_without_split() -> None:
    b = vol("10")
    out = feed(b, [trade(T0, qty="4", seq=1), trade(T0 + 1, qty="6", seq=2)])
    assert [u.kind for u in out] == ["open", "close"]
    assert isinstance(out[1], ActivityBarUpdate) and out[1].split_from_trade_id is None
    assert out[1].bar.volume == Decimal("10") and out[1].bar.trade_count == 2


def test_volume_zero_qty_trade_counts_without_volume() -> None:
    b = vol("10")
    out = feed(b, [trade(T0, qty="0", seq=1), trade(T0 + 1, "101", qty="1", seq=2)])
    assert [u.kind for u in out] == ["open"]  # the second print only extends it (#2022)
    forming = b.forming()
    assert forming is not None and forming.kind == "update"
    assert forming.bar.trade_count == 2 and forming.bar.volume == Decimal("1")


def test_volume_fractional_threshold_is_exact_decimal() -> None:
    b = vol("0.1")
    out = feed(b, [trade(T0, qty="0.07", seq=1), trade(T0 + 1, qty="0.25", seq=2)])
    assert [x.volume for x in closes(out)] == [Decimal("0.1")] * 3
    assert out[-1].bar.volume == Decimal("0.02")


def test_tick_bar_closes_on_exact_count_regardless_of_batching() -> None:
    trades = [trade(T0 + i, str(100 + i % 7), seq=i) for i in range(1200)]
    whole = feed(tick(500), trades)
    batched: list[BarUpdate] = []
    b = tick(500)
    for i in range(0, 1200, 50):  # 50-record pushes
        batched += feed(b, trades[i : i + 50])
    assert whole == batched
    bars = closes(whole)
    assert [x.trade_count for x in bars] == [500, 500]
    assert bars[0].close_time == T0 + 499 and bars[1].open_time == T0 + 500


def test_tick_count_one_closes_every_trade() -> None:
    out = feed(tick(1), [trade(T0, seq=1), trade(T0 + 1, seq=2)])
    assert [u.kind for u in out] == ["close", "close"]


def test_tick_block_trade_counts_as_one_tick() -> None:
    blk = trade(T0, qty="50", seq=1).model_copy(update={"is_block_trade": True})
    out = feed(tick(2), [blk, trade(T0 + 1, seq=2)])
    assert out[-1].kind == "close" and out[-1].bar.volume == Decimal("51")


def test_first_bar_partial_marks_where_tape_begins() -> None:
    for b in (tick(2), vol("2")):
        out = feed(b, [trade(T0 + 9, seq=1), trade(T0 + 10, seq=2), trade(T0 + 11, seq=3)])
        bars = final_bars(out, b)
        assert bars[0].partial and bars[0].open_time == T0 + 9
        assert not bars[1].partial
        assert not any(x.gap_before for x in bars)


def test_out_of_order_trade_goes_to_open_bar_with_event_order_ohlc() -> None:
    b = tick(3)
    out = feed(
        b,
        [trade(T0 + 10, "100", seq=2), trade(T0 + 5, "99", seq=1), trade(T0 + 20, "101", seq=3)],
    )
    bar = closes(out)[0]
    assert (bar.open, bar.close, bar.open_time, bar.close_time) == (
        Decimal("99"),
        Decimal("101"),
        T0 + 5,
        T0 + 20,
    )


def test_on_clock_is_noop() -> None:
    b = vol("5")
    b.on_trade(trade(T0, seq=1))
    assert b.on_clock(T0 + 10**12) == ()


def test_snapshot_restore_mid_split_resumes_identically() -> None:
    tail = [trade(T0 + 2, qty="2", seq=2), trade(T0 + 3, qty="9", seq=3)]
    a = vol("5")
    a.on_trade(trade(T0, qty="12", seq=1))  # 5 + 5 closed, 2 carried
    snap = a.snapshot()
    b = vol("5")
    b.restore(snap)
    assert feed(a, tail) == feed(b, tail)
    assert a.forming() == b.forming() is not None


@pytest.mark.parametrize(
    ("spec", "cls"),
    [
        (BarSpec(kind="time", interval_ms=60_000), TickBarBuilder),
        (BarSpec(kind="tick", tick_count=5), VolumeBarBuilder),
    ],
)
def test_wrong_kind_spec_is_rejected(spec: BarSpec, cls: type[TickBarBuilder]) -> None:
    with pytest.raises(BarSpecError):
        cls(spec, SYM)


def test_wrong_symbol_is_rejected() -> None:
    with pytest.raises(BarsError):
        tick(2).on_trade(trade(T0).model_copy(update={"symbol": "ETHUSDT"}))


def test_restore_rejects_foreign_or_unknown_state() -> None:
    b = tick(2)
    s = b.snapshot()
    with pytest.raises(BarsError):
        tick(3).restore(s)
    with pytest.raises(BarsError):
        b.restore(BuilderState(**{**s.model_dump(), "state_version": 99}))


def test_split_rate_warns_once() -> None:
    b = vol("1")
    for i in range(1001):
        b.on_trade(trade(T0 + i, qty="1.5", seq=i))
    assert b._warned  # every trade overshoots: misconfigured threshold


def test_subscribable_tick_floor_matches_sr_e12_03() -> None:
    from candleviewer.bars.activity_builders import MIN_SUBSCRIBABLE_TICK_COUNT

    assert MIN_SUBSCRIBABLE_TICK_COUNT == 100  # E12 threat model SR-E12-03 / BR-29
