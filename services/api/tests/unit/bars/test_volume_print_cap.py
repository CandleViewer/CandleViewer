"""SR-E12-15 for volume bars (#2770): one print closes at most `MAX_BRICKS_PER_TRADE` bars.

A print that would close more is refused before any state changes: the builder raises `BarsError`
as the renko builder does, and on the live path `BarBuilderSet` quarantines the series, counts it
and logs it once.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.bars.activity_builders import (
    VolumeBarBuilder,
    bar_volume_splits_total,
    bars_partial_series_total,
)
from candleviewer.bars.builder_set import BarsHealthReason
from candleviewer.bars.errors import BarsError
from candleviewer.bars.metrics import bar_builder_quarantined_total
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from candleviewer.bars.time_builder import bars_built_total
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import T3, TOPIC, RecordingSink, make_set, settle
from ._trades import SYM, closes, trade, us

T0 = 1_700_000_000_000_000
CAP = 1_000  # SR-E12-15; the constant itself is pinned by tests/unit/api/test_market_response.py

#: (threshold, volume already in the open bar, print qty, volume left for the next bar): a print
#: that closes exactly CAP bars. The open bar's room is the first close; a remainder is no close.
AT_THE_CAP = [
    pytest.param("1", "0", "1000", "0", id="whole-bars"),
    pytest.param("10", "4", "9996", "0", id="part-filled-open-bar"),
    pytest.param("10", "4", "10005", "9", id="remainder-opens-the-next-bar"),
    pytest.param("0.5", "0.25", "499.75", "0", id="fractional-threshold"),
]
#: (threshold, volume already in the open bar, print qty, bars it would close): one past the cap.
OVER_THE_CAP = [
    pytest.param("1", "0", "1001", 1001, id="whole-bars"),
    pytest.param("10", "4", "10006", 1001, id="part-filled-open-bar"),
    pytest.param("0.5", "0.25", "500.25", 1001, id="fractional-threshold"),
    pytest.param("1", "0", "20000", 20_000, id="far-over-the-cap"),
]
#: The open bar's room is the threshold less its buy AND its sell volume, so each case runs with the
#: open bar filled by buys and by sells (a case with no open bar runs twice, the same).
SIDES = pytest.mark.parametrize("side", ["buy", "sell"])


def vol(threshold: str) -> VolumeBarBuilder:
    return VolumeBarBuilder(BarSpec(kind="volume", volume_threshold=Decimal(threshold)), SYM)


def feed(b: VolumeBarBuilder, trades: Sequence[TradeEvent]) -> list[BarUpdate]:
    out: list[BarUpdate] = []
    for t in trades:
        out += b.on_trade(t)
    return out


def prefilled(threshold: str, filled: str, side: str = "buy") -> VolumeBarBuilder:
    b = vol(threshold)
    if Decimal(filled):
        b.on_trade(trade(T0, qty=filled, side=side, seq=1))
    return b


def volume_counters() -> tuple[float, float, float]:
    """What a volume builder counts in the process registry: bars built, splits, partial series."""
    return (
        float(bars_built_total.labels(symbol=SYM, kind="volume")._value.get()),
        float(bar_volume_splits_total.labels(symbol=SYM)._value.get()),
        float(bars_partial_series_total.labels(kind="volume")._value.get()),
    )


@SIDES
@pytest.mark.parametrize(("threshold", "filled", "qty", "rest"), AT_THE_CAP)
def test_volume_print_closing_exactly_the_cap_is_emitted(
    threshold: str, filled: str, qty: str, rest: str, side: str
) -> None:
    out = prefilled(threshold, filled, side).on_trade(trade(T0 + 1, qty=qty, seq=2))
    bars = closes(out)
    assert len(bars) == CAP
    assert [b.index for b in bars] == list(range(CAP))
    assert {b.volume for b in bars} == {Decimal(threshold)}
    if Decimal(rest):  # the remainder is the forming bar, emitted after the last close
        assert [u.kind for u in out[CAP:]] == ["open"]
        assert out[CAP].bar.index == CAP and out[CAP].bar.volume == Decimal(rest)
    else:
        assert len(out) == CAP
    assert sum(u.bar.volume for u in out) == Decimal(filled) + Decimal(qty)  # BI-1


@SIDES
@pytest.mark.parametrize(("threshold", "filled", "qty", "n"), OVER_THE_CAP)
def test_volume_print_closing_one_more_than_the_cap_is_refused(
    threshold: str, filled: str, qty: str, n: int, side: str
) -> None:
    b = prefilled(threshold, filled, side)
    with pytest.raises(BarsError, match=rf"would close {n} volume bars \(cap {CAP}\)"):
        b.on_trade(trade(T0 + 1, qty=qty, seq=2))


def test_volume_cap_counts_both_sides_of_a_mixed_open_bar() -> None:
    """An open bar of 1 buy and 2 sell has room 7 (the threshold less both sides): a print of 9997
    closes exactly CAP bars; a print of 10007 would close one more and is refused."""
    opening = [trade(T0, qty="1", seq=1), trade(T0 + 1, qty="2", side="sell", seq=2)]
    emitted, refused = vol("10"), vol("10")
    feed(emitted, opening)
    feed(refused, opening)
    bars = closes(emitted.on_trade(trade(T0 + 2, qty="9997", seq=3)))
    assert len(bars) == CAP and {b.volume for b in bars} == {Decimal(10)}
    with pytest.raises(BarsError, match=rf"would close {CAP + 1} volume bars \(cap {CAP}\)"):
        refused.on_trade(trade(T0 + 2, qty="10007", seq=3))


@settings(max_examples=150, deadline=None)
@given(
    threshold=st.decimals(Decimal("0.001"), Decimal(100), places=3),
    filled=st.integers(0, 999),  # thousandths of the threshold already in the open bar
    side=st.sampled_from(["buy", "sell"]),  # which side traded it
    n=st.integers(CAP - 2, CAP + 2),  # bars the print closes
    rest=st.integers(0, 999),  # thousandths of the threshold left for the next bar
)
def test_volume_cap_holds_at_the_boundary_for_any_threshold_and_fill(
    threshold: Decimal, filled: int, side: str, n: int, rest: int
) -> None:
    """A print built to close exactly `n` bars (the open bar's room, n - 1 whole bars and a
    remainder below one bar) is emitted when n is at most the cap and refused above it."""
    part = filled * threshold / 1000
    qty = (threshold - part) + (n - 1) * threshold + rest * threshold / 1000
    b = prefilled(str(threshold), str(part), side)
    t = trade(T0 + 1, qty=str(qty), seq=2)
    if n > CAP:
        with pytest.raises(BarsError):
            b.on_trade(t)
    else:
        assert len(closes(b.on_trade(t))) == n


@pytest.mark.parametrize("prefix", [[], ["4"], ["10"], ["25"]], ids=lambda p: "+".join(p) or "new")
def test_volume_refusal_leaves_the_builder_as_if_the_print_never_arrived(
    prefix: list[str],
) -> None:
    b, control = vol("10"), vol("10")
    for i, q in enumerate(prefix):  # new, a forming bar, a just closed bar, a split behind it
        b.on_trade(trade(T0 + i, qty=q, seq=i))
        control.on_trade(trade(T0 + i, qty=q, seq=i))
    state, counted = b.snapshot(), (b._n_trades, b._n_splits)
    assert state.last_trade_seq == (len(prefix) - 1 if prefix else None)
    metrics = volume_counters()
    with pytest.raises(BarsError):
        b.on_trade(trade(T0 + 50, "105", "100000", "sell", seq=50))
    assert b.snapshot() == state  # the open bar, the next index and the last seq
    assert (b._n_trades, b._n_splits) == counted
    assert volume_counters() == metrics
    tail = [trade(T0 + 60, "101", "3", seq=60), trade(T0 + 61, "102", "30", "sell", seq=61)]
    assert feed(b, tail) == feed(control, tail)
    assert b.snapshot() == control.snapshot()
    assert b.snapshot().last_trade_seq == 61


def test_volume_refusal_keeps_the_forming_bar_and_its_index() -> None:
    b = vol("10")
    b.on_trade(trade(T0, qty="4", seq=1))
    with pytest.raises(BarsError):
        b.on_trade(trade(T0 + 1, qty="100000", seq=2))
    (up,) = b.on_trade(trade(T0 + 2, qty="3", seq=3))
    assert (up.kind, up.bar.index) == ("update", 0)
    assert (up.bar.volume, up.bar.trade_count) == (Decimal(7), 2)


@SIDES
def test_volume_refusal_past_the_decimal_context_is_still_a_bars_error(
    side: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quotient of 1e29 has more digits than the Decimal context holds: the count in the message
    must not raise `decimal.InvalidOperation`, and the builder is as if the print never arrived."""
    b = prefilled("1", "0.5", side)
    state, counted = b.snapshot(), (b._n_trades, b._n_splits)
    real, built = b._emit, list[int]()

    # stand-in: stop after 2 x cap emissions, so a missing cap fails fast
    def emit(*args: Any, **kwargs: Any) -> BarUpdate:
        built.append(1)
        assert len(built) <= 2 * CAP, "more than 2 x cap emissions for one print"
        return real(*args, **kwargs)

    monkeypatch.setattr(b, "_emit", emit)
    with pytest.raises(BarsError, match=rf"would close over {CAP} volume bars \(cap {CAP}\)"):
        b.on_trade(trade(T0 + 1, qty="1E+29", seq=2))
    assert b.snapshot() == state and (b._n_trades, b._n_splits) == counted


def test_volume_foreign_symbol_is_refused_first_and_changes_nothing() -> None:
    b = vol("10")
    b.on_trade(trade(T0, qty="4", seq=1))
    state = b.snapshot()
    over = trade(T0 + 1, qty="100000", seq=2).model_copy(update={"symbol": "ETHUSDT"})
    with pytest.raises(BarsError, match="ETHUSDT"):  # the wiring error, not the cap
        b.on_trade(over)
    assert b.snapshot() == state and b._n_trades == 1


def test_delta_and_range_builders_emit_one_update_for_any_print() -> None:
    """Neither splits a trade, so SR-E12-15 needs no check there (S03; volume bars split, S02)."""
    delta = DeltaBarBuilder(BarSpec(kind="delta", delta_threshold=Decimal(1)), SYM)
    assert len(delta.on_trade(trade(T0, qty="1000000", seq=1))) == 1
    rng = RangeBarBuilder(BarSpec(kind="range", range_ticks=2), SYM, lambda _s: Decimal("0.1"))
    rng.on_trade(trade(T0, "100", seq=1))
    assert len(rng.on_trade(trade(T0 + 1, "1000000", qty="1000000", seq=2))) == 1


# -- through BarBuilderSet: the refusal is a builder error, so the set's quarantine counts it ----

V1 = BarSpec(kind="volume", volume_threshold=Decimal(1))


def quarantined_total() -> float:
    return float(bar_builder_quarantined_total.labels(reason="builder_error")._value.get())


async def test_set_quarantines_a_volume_series_over_the_cap_once(tmp_path: Path) -> None:
    t0 = us("10:00:00")
    bus, sink = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[sink])
    await s.register(V1, SYM, "a")
    await s.register(T3, SYM, "b")
    before = quarantined_total()
    with capture_logs() as logs:
        await bus.publish(TOPIC, trade(t0, qty="1.5", seq=0))  # 1 close, 0.5 left in the open bar
        await bus.publish(TOPIC, trade(t0 + 1, qty="1000.5", seq=1))  # 1 001 closes: refused
        await settle(bus, s)
        assert s.active(SYM) == (T3.spec_hash,)
        assert s.quarantined(SYM, V1.spec_hash)
        assert BarsHealthReason.BUILDER_QUARANTINED in s.health_reasons()
        assert quarantined_total() == before + 1
        for i, qty in enumerate(("5000", "1", "1", "1"), start=2):  # the series is gone by now
            await bus.publish(TOPIC, trade(t0 + i, qty=qty, seq=i))
        await settle(bus, s)
    assert quarantined_total() == before + 1  # counted once
    events = [e for e in logs if e["event"] == "bars_builder_quarantined"]
    assert len(events) == 1  # and logged once
    assert events[0]["log_level"] == "error" and events[0]["symbol"] == SYM
    assert events[0]["spec_hash"] == V1.spec_hash and events[0]["error_type"] == "BarsError"
    seen = [(k, i) for h, _, k, i, _ in sink.seen if h == V1.spec_hash]
    assert seen == [("close", 0), ("open", 1)]  # the first print only: nothing of the refused one
    t3_closes = [i for h, _, k, i, _ in sink.seen if h == T3.spec_hash and k == "close"]
    assert t3_closes == [0, 1]  # every trade still reached the tick series: 6 trades, 3 a bar
    await s.stop()
