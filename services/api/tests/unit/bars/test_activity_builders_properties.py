"""Property tests for tick/volume bars: BI-1..BI-6 (24 §3.4) and the split rules (E12-S02)."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.models import BarBuilder, BarSpec, BarUpdate
from candleviewer.exchange.base.models import TradeEvent
from tests.unit.bars._trades import SYM, final_bars, trade

T0 = 1_790_000_000_000_000
SPECS = st.sampled_from(
    [
        BarSpec(kind="tick", tick_count=1),
        BarSpec(kind="tick", tick_count=7),
        BarSpec(kind="volume", volume_threshold=Decimal("0.5")),
        BarSpec(kind="volume", volume_threshold=Decimal("3.3")),
        BarSpec(kind="volume", volume_threshold=Decimal("0.05")),
    ]
)


def build(spec: BarSpec) -> TickBarBuilder | VolumeBarBuilder:
    return TickBarBuilder(spec, SYM) if spec.kind == "tick" else VolumeBarBuilder(spec, SYM)


@st.composite
def tapes(draw: st.DrawFn) -> list[TradeEvent]:
    n = draw(st.integers(1, 150))
    ts = T0
    out = []
    for i in range(n):
        ts += draw(st.integers(-5_000, 200_000))
        px = Decimal(draw(st.integers(9_000, 11_000))) / 10
        qty = Decimal(draw(st.integers(0, 5_000))) / 1000
        out.append(trade(ts, px, qty, draw(st.sampled_from(["buy", "sell"])), seq=i))
    return out


def run_builder(spec: BarSpec, tape: list[TradeEvent]) -> tuple[list[BarUpdate], BarBuilder]:
    """Every emission over `tape`, and the builder (its `forming()` is the trailing bar)."""
    b = build(spec)
    out: list[BarUpdate] = []
    for t in tape:
        out += b.on_trade(t)
    return out, b


def run(spec: BarSpec, tape: list[TradeEvent]) -> list[BarUpdate]:
    return run_builder(spec, tape)[0]


@settings(max_examples=150, deadline=None)
@given(SPECS, tapes())
def test_bar_invariants_bi1_to_bi6_hold(spec: BarSpec, tape: list[TradeEvent]) -> None:
    bars = final_bars(*run_builder(spec, tape))
    assert sum(b.volume for b in bars) == sum(t.qty for t in tape)  # BI-1
    assert [b.index for b in bars] == list(range(len(bars)))
    for b in bars:
        assert b.delta == b.buy_volume - b.sell_volume  # BI-2
        assert b.min_delta <= b.delta <= b.max_delta  # BI-3
        exp = (b.turnover / b.volume).quantize(Decimal("1e-8")) if b.volume else b.open
        assert b.vwap == exp  # BI-6
        assert b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close)
        if spec.kind == "volume":
            assert b.volume <= spec.param_value
            assert (b.volume == spec.param_value) == b.closed
        else:
            assert (b.trade_count == spec.param_value) == b.closed
            assert b.trade_count <= spec.param_value
    if spec.kind == "tick":
        assert sum(b.trade_count for b in bars) == len(tape)


@settings(max_examples=100, deadline=None)
@given(SPECS, tapes(), st.integers(0, 10_000))
def test_bi5_restore_at_any_cut_matches_uninterrupted(
    spec: BarSpec, tape: list[TradeEvent], seed: int
) -> None:
    cut = random.Random(seed).randint(0, len(tape))  # noqa: S311 - seeded test data, not crypto
    a = build(spec)
    head: list[BarUpdate] = []
    for t in tape[:cut]:
        head += a.on_trade(t)
    b = build(spec)
    b.restore(a.snapshot())
    tail: list[BarUpdate] = []
    for t in tape[cut:]:
        tail += b.on_trade(t)
    want, whole = run_builder(spec, tape)
    assert head + tail == want
    assert b.forming() == whole.forming()  # the forming bar too (#2022)


@settings(max_examples=50, deadline=None)
@given(SPECS, tapes())
def test_bi4_replay_is_deterministic(spec: BarSpec, tape: list[TradeEvent]) -> None:
    assert run(spec, tape) == run(spec, list(tape))


def _bi1_volume_conserved(n_trades: int) -> None:
    rng = random.Random(42)  # noqa: S311 - seeded test data, not crypto
    spec = BarSpec(kind="volume", volume_threshold=Decimal("250"))
    b = VolumeBarBuilder(spec, SYM)
    total = Decimal(0)
    vols: dict[int, Decimal] = {}
    for i in range(n_trades):
        q = Decimal(rng.randint(1, 4000)) / 1000
        total += q
        t = trade(T0 + i, "100", q, "buy" if i & 1 else "sell", seq=i)
        for u in b.on_trade(t):
            vols[u.bar.index] = u.bar.volume
    forming = b.forming()  # the trailing bar: a print that only extends it emits nothing
    if forming is not None:
        vols[forming.bar.index] = forming.bar.volume
    assert sum(vols.values()) == total
    assert max(vols.values()) <= Decimal("250")


def test_bi1_volume_conserved_over_fifty_thousand_trades() -> None:
    """PR-lane BI-1 sample; the 1M-trade run is in the nightly `harness` lane (#2177)."""
    _bi1_volume_conserved(50_000)


@pytest.mark.harness
def test_bi1_volume_conserved_over_one_million_trades() -> None:
    """Nightly `harness` lane: 1M trades (~100 s under coverage, #2177)."""
    _bi1_volume_conserved(1_000_000)
