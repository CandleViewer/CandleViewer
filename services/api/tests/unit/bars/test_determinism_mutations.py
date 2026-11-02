"""E12-T04 mutation set: deliberately seeded builder defects the harness must catch.

Each defect is injected ONLY here, by wrapping or monkeypatching a production builder for the
duration of one test; production code is never changed. A test passes when the harness reports
the expected invariant (or the golden comparator reports a diff naming the golden file). A
defect the harness misses is a gap in the harness (ticket Test plan).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

import pytest

from bench.bar_determinism import comparator, goldens, invariants
from bench.bar_determinism.generator import TICK, GenConfig, generate
from candleviewer.bars import time_builder
from candleviewer.bars.activity_builders import VolumeBarBuilder
from candleviewer.bars.models import BarBuilder, BarSpec, BarUpdate, BuilderState
from candleviewer.bars.renko_builder import RenkoBarUpdate
from candleviewer.domain.primitives import TsUs
from candleviewer.exchange.base.models import TradeEvent

SEED = 4242
_TAPE: list[TradeEvent] = []


def tape() -> list[TradeEvent]:
    """Generated on first use, never at import/collection time."""
    if not _TAPE:
        _TAPE.extend(
            generate(
                GenConfig(
                    seed=SEED,
                    n=4_000,
                    p_exact=0.05,
                    p_huge=0.01,
                    p_reversal=0.02,
                    threshold_lots=250,
                    jump_ticks=60,
                )
            )
        )
    return _TAPE


class Mutant:
    """A production builder whose input and/or emissions pass through a defect."""

    def __init__(
        self,
        inner: BarBuilder,
        on_input: Callable[[TradeEvent], TradeEvent] = lambda t: t,
        on_output: Callable[[Sequence[BarUpdate]], Sequence[BarUpdate]] = lambda u: u,
    ) -> None:
        self.inner, self.spec = inner, inner.spec
        self._in, self._out = on_input, on_output

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        return self._out(self.inner.on_trade(self._in(t)))

    def on_clock(self, now_us: TsUs) -> Sequence[BarUpdate]:
        return self._out(self.inner.on_clock(now_us))

    def forming(self) -> BarUpdate | None:
        """The forming bar through the same defect as an emission (#2022)."""
        f = self.inner.forming()
        return None if f is None else self._out((f,))[-1]

    def snapshot(self) -> BuilderState:
        return self.inner.snapshot()

    def restore(self, state: BuilderState) -> None:
        self.inner.restore(state)


def caught(
    label: str, spec: BarSpec, factory: invariants.Factory, tape: list[TradeEvent]
) -> set[str]:
    clean = invariants.check(label, spec, tape, seed=SEED)
    assert not clean, invariants.report(clean)  # the tape is green on the real builder
    v = invariants.check(label, spec, tape, seed=SEED, factory=factory)
    for x in v:  # the report names builder, spec and seed
        assert (x.builder, x.spec, x.seed) == (spec.kind, label, SEED)
    return {x.invariant for x in v}


def test_mutant_time_bar_off_by_one_boundary_is_caught() -> None:
    """A trade exactly on a bucket boundary is put in the previous bar (`<=` for `<`)."""
    spec = BarSpec(kind="time", interval_ms=60_000)
    step = 60_000_000

    def shift(t: TradeEvent) -> TradeEvent:
        return t.model_copy(update={"ts_event": t.ts_event - 1}) if t.ts_event % step == 0 else t

    assert any(t.ts_event % step == 0 for t in tape())
    got = caught(
        "time:1m", spec, lambda s: Mutant(invariants.make_builder(s), on_input=shift), tape()
    )
    assert "REF" in got


def test_mutant_time_bar_off_by_one_fails_the_golden_file() -> None:
    spec = goldens.GOLDEN_SPECS["time-1m"]
    day = goldens.load_tape()
    step = 60_000_000
    on_edge = [t.ts_event - t.ts_event % step for t in day]
    edged = [
        t.model_copy(update={"ts_event": e}) if i % 7 == 0 else t
        for i, (t, e) in enumerate(zip(day, on_edge, strict=True))
    ]

    def shift(t: TradeEvent) -> TradeEvent:
        return t.model_copy(update={"ts_event": t.ts_event - 1}) if t.ts_event % step == 0 else t

    good = [comparator.line(b) for b in invariants.run(invariants.make_builder, spec, edged)]
    bad = [
        comparator.line(b)
        for b in invariants.run(
            lambda s: Mutant(invariants.make_builder(s), on_input=shift), spec, edged
        )
    ]
    diffs = comparator.compare_lines(good, bad)
    assert diffs
    msg = f"{goldens.path('time-1m').name}:\n{comparator.render(diffs)}"
    assert "time-1m.jsonl" in msg and "expected" in msg and "actual" in msg


def test_mutant_endpoint_only_min_delta_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """min/max_delta from the bar's endpoint instead of the running intrabar path."""
    real = time_builder._Draft.fold

    def endpoint_only(
        self: time_builder._Draft, px: Decimal, qty: Decimal, ts: int, seq: int, buy: bool
    ) -> None:
        real(self, px, qty, ts, seq, buy)
        self.min_d = min(Decimal(0), self.delta)
        self.max_d = max(Decimal(0), self.delta)

    spec = invariants.STANDARD_SPECS["delta:2"]
    clean = invariants.check("delta:2", spec, tape(), seed=SEED)
    assert not clean
    monkeypatch.setattr(time_builder._Draft, "fold", endpoint_only)
    v = invariants.check("delta:2", spec, tape(), seed=SEED)
    assert "BI-3" in {x.invariant for x in v}, invariants.report(v)


class _NoSplitVolume(VolumeBarBuilder):
    """Volume bars that close on `>=` without splitting the overshooting trade."""

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        self._guard(t)
        d = self._draft(t)
        d.apply(t)
        return (self._emit(d, closed=d.buy + d.sell >= self._quota),)


def test_mutant_missing_volume_split_is_caught() -> None:
    spec = invariants.STANDARD_SPECS["volume:0.25"]
    got = caught("volume:0.25", spec, lambda s: _NoSplitVolume(s, "BTCUSDT"), tape())
    assert "BI-1" in got


def _phantom(updates: Sequence[BarUpdate], width: Decimal, shift: list[int]) -> list[BarUpdate]:
    """On a jump, synthesise the skipped intermediate bar (copying the closed bar's volume)."""
    out: list[BarUpdate] = []
    for u in updates:
        bar = u.bar.model_copy(update={"index": u.bar.index + shift[0]})
        out.append(u.model_copy(update={"bar": bar}))
        if u.kind == "close" and u.bar.high - u.bar.low >= 2 * width:
            shift[0] += 1
            out.append(
                u.model_copy(update={"bar": bar.model_copy(update={"index": bar.index + 1})})
            )
    return out


def test_mutant_phantom_range_bars_are_caught() -> None:
    spec = BarSpec(kind="range", range_ticks=20)
    width = 20 * TICK

    def factory(s: BarSpec) -> BarBuilder:
        shift = [0]
        return Mutant(invariants.make_builder(s), on_output=lambda u: _phantom(u, width, shift))

    got = caught("range:20", spec, factory, tape())
    assert "BI-1" in got


def _double_allocate(updates: Sequence[BarUpdate]) -> list[BarUpdate]:
    owners = [
        u
        for u in updates
        if isinstance(u, RenkoBarUpdate) and u.volume_allocated and u.kind == "close"
    ]
    if not owners:
        return list(updates)
    src = owners[-1].bar
    vol = {
        f: getattr(src, f)
        for f in (
            "volume",
            "buy_volume",
            "sell_volume",
            "delta",
            "min_delta",
            "max_delta",
            "turnover",
            "trade_count",
        )
    }
    return [
        u.model_copy(update={"bar": u.bar.model_copy(update=vol)})
        if u.kind == "close" and not getattr(u, "volume_allocated", True)
        else u
        for u in updates
    ]


def test_mutant_renko_double_allocation_is_caught() -> None:
    spec = invariants.STANDARD_SPECS["renko:10"]

    def factory(s: BarSpec) -> BarBuilder:
        return Mutant(invariants.make_builder(s), on_output=_double_allocate)

    got = caught("renko:10", spec, factory, tape())
    assert "BI-1" in got
