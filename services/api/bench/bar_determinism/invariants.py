"""BI-1..BI-6 (`24-internal-schemas.md` §3.4) over the six shipped builders (E12-T04).

`check(spec_label, spec, tape, seed)` feeds one builder, then reports every broken invariant as a
`Violation` naming the invariant, builder, spec, first offending bar and the seed (the repro).
How each invariant is decided:
- BI-1 sum(bar.volume) == sum(applied trade.qty). Time bars drop trades outside the 60 s amend
  window (§3.3c); the dropped quantity comes from the reference model. Volume bars must also close
  at exactly the threshold (the split rule); renko volume sits on one brick per run.
- BI-2 delta == buy - sell (and volume == buy + sell) on every bar.
- BI-3 min_delta <= delta <= max_delta, and both extremes equal the extremes of the reference's
  intrabar running-delta path (so they are attained, not endpoint-only).
- BI-4 a second fresh run is identical field by field, and spec_hash == compute_spec_hash(spec).
- BI-5 snapshot/restore (through a JSON round trip of the `BuilderState`) at random cut points
  yields the same final series as the uninterrupted run.
- BI-6 vwap == round_half_even(turnover / volume, 8 dp), or open when volume == 0.
- REF the series equals the independent reference (`reference.py`) on every field.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.models import Bar, BarBuilder, BarSpec, BarUpdate, BuilderState
from candleviewer.bars.renko_builder import RenkoBarBuilder
from candleviewer.bars.spec import compute_spec_hash
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.exchange.base.models import TradeEvent

from . import comparator, reference
from .generator import SYMBOL, TICK

_Q8 = Decimal("0.00000001")
Factory = Callable[[BarSpec], BarBuilder]

#: The standard spec matrix: every builder kind, at least one non-default parameter shape.
STANDARD_SPECS: dict[str, BarSpec] = {
    "time:1m": BarSpec(kind="time", interval_ms=60_000),
    "time:5m": BarSpec(kind="time", interval_ms=300_000),
    "tick:100": BarSpec(kind="tick", tick_count=100),
    "tick:1000": BarSpec(kind="tick", tick_count=1000),
    "volume:5": BarSpec(kind="volume", volume_threshold=Decimal(5)),
    "volume:0.25": BarSpec(kind="volume", volume_threshold=Decimal("0.25")),
    "range:20": BarSpec(kind="range", range_ticks=20),
    "delta:2": BarSpec(kind="delta", delta_threshold=Decimal(2)),
    "renko:10": BarSpec(kind="renko", range_ticks=10),
    "renko:10:wick:rev3": BarSpec(kind="renko", range_ticks=10, renko_wick=True, reversal_bricks=3),
}


def make_builder(spec: BarSpec, symbol: str = SYMBOL, tick: Decimal = TICK) -> BarBuilder:
    """The shipped production builder for `spec`."""
    if spec.kind == "time":
        return TimeBarBuilder(spec, symbol)
    if spec.kind == "tick":
        return TickBarBuilder(spec, symbol)
    if spec.kind == "volume":
        return VolumeBarBuilder(spec, symbol)
    if spec.kind == "delta":
        return DeltaBarBuilder(spec, symbol)
    if spec.kind == "range":
        return RangeBarBuilder(spec, symbol, lambda _s: tick)
    return RenkoBarBuilder(spec, symbol, lambda _s: tick)


@dataclass(frozen=True)
class Violation:
    invariant: str
    builder: str
    spec: str
    bar_index: int | None
    seed: int | None
    detail: str

    def __str__(self) -> str:
        bar = "-" if self.bar_index is None else self.bar_index
        return (
            f"{self.invariant} violated: builder={self.builder} spec={self.spec} "
            f"first_bar={bar} seed={self.seed}: {self.detail}"
        )


def final_bars(updates: Iterable[BarUpdate], builder: BarBuilder | None = None) -> list[Bar]:
    """Latest emission per index, in index order (amendments overwrite, like the upsert). With
    `builder`, its `forming()` comes last: a builder emits no `update` per trade (24 §3.2, #2022),
    so a trailing bar still forming at the end of the tape is read on demand."""
    latest: dict[int, Bar] = {}
    for u in updates:
        latest[u.bar.index] = u.bar
    tail = None if builder is None else builder.forming()
    if tail is not None:
        latest[tail.bar.index] = tail.bar
    return [latest[i] for i in sorted(latest)]


def feed(b: BarBuilder, tape: Sequence[TradeEvent]) -> list[BarUpdate]:
    """Every emission of `b` over `tape` (opens, closes and amends; the full feed BI-4 and the
    invariants read)."""
    clocked = b.spec.kind == "time"
    out: list[BarUpdate] = []
    for t in tape:
        out += b.on_trade(t)
        if clocked:
            out += b.on_clock(t.ts_event)
    return out


def count(b: BarBuilder, tape: Sequence[TradeEvent]) -> int:
    """The throughput path: feed `b` and retain no emission, only their number (#2022). It times
    the builder alone, not a million retained objects; the invariants keep `feed`."""
    on_trade, on_clock = b.on_trade, b.on_clock
    n = 0
    if b.spec.kind == "time":
        for t in tape:
            n += len(on_trade(t)) + len(on_clock(t.ts_event))
    else:
        for t in tape:
            n += len(on_trade(t))
    return n


def flush(b: BarBuilder, tape: Sequence[TradeEvent]) -> list[BarUpdate]:
    """Time bars: advance the clock one interval past the last trade so every bar closes."""
    if b.spec.kind != "time" or not tape:
        return []
    last = max(t.ts_event for t in tape)
    return list(b.on_clock(last + int(b.spec.param_value) * 1000))


def run(factory: Factory, spec: BarSpec, tape: Sequence[TradeEvent]) -> list[Bar]:
    b = factory(spec)
    ups = feed(b, tape)
    return final_bars(ups + flush(b, tape), b)


def fixed_cuts(factory: Factory, spec: BarSpec, tape: Sequence[TradeEvent]) -> list[int]:
    """Deterministic BI-5 cut points at the hard edges: just before and just after the first
    volume-bar split (the remainder sits in the open bar at the cut) and the first renko
    reversal (direction + anchor in flight). Empty for other kinds or when none occurs."""
    if spec.kind not in ("volume", "renko"):
        return []
    b = factory(spec)
    prev_dir = 0
    for i, t in enumerate(tape):
        closes = [u.bar for u in b.on_trade(t) if u.kind == "close"]
        hit = False
        if spec.kind == "volume":
            hit = t.qty > Decimal(spec.param_value) or len(closes) > 1
        for c in closes:
            d = 1 if c.close > c.open else -1
            hit = hit or (spec.kind == "renko" and prev_dir == -d)
            prev_dir = d
        if hit:
            return [c for c in (i, i + 1) if 0 < c < len(tape)]
    return []


def run_with_cuts(
    factory: Factory, spec: BarSpec, tape: Sequence[TradeEvent], cuts: Sequence[int]
) -> list[Bar]:
    """Snapshot, JSON round trip and restore into a FRESH builder at every cut point."""
    b = factory(spec)
    ups: list[BarUpdate] = []
    prev = 0
    for c in [*sorted(cuts), len(tape)]:
        ups += feed(b, tape[prev:c])
        prev = c
        if c < len(tape):
            state = BuilderState.model_validate_json(b.snapshot().model_dump_json())
            b = factory(spec)
            b.restore(state)
    return final_bars(ups + flush(b, tape), b)


def _first(
    out: list[Violation],
    inv: str,
    spec: BarSpec,
    label: str,
    seed: int | None,
    bars: Iterable[Bar],
    bad: Callable[[Bar], str | None],
) -> None:
    for b in bars:
        msg = bad(b)
        if msg is not None:
            out.append(Violation(inv, spec.kind, label, b.index, seed, msg))
            return


def _bi2(b: Bar) -> str | None:
    if b.delta != b.buy_volume - b.sell_volume:
        return f"delta {b.delta} != buy {b.buy_volume} - sell {b.sell_volume}"
    if b.volume != b.buy_volume + b.sell_volume:
        return f"volume {b.volume} != buy {b.buy_volume} + sell {b.sell_volume}"
    return None


def _bi6(b: Bar) -> str | None:
    want = (b.turnover / b.volume).quantize(_Q8, ROUND_HALF_EVEN) if b.volume else b.open
    return None if b.vwap == want else f"vwap {b.vwap} != {want}"


def check(
    label: str,
    spec: BarSpec,
    tape: Sequence[TradeEvent],
    seed: int | None = None,
    factory: Factory | None = None,
    cuts: int = 3,
) -> list[Violation]:
    """Every BI-1..BI-6 (+ REF) violation of the builder for `spec` over `tape`."""
    fac: Factory = factory or make_builder
    out: list[Violation] = []
    bars = run(fac, spec, tape)
    ref = reference.build(spec, SYMBOL, list(tape), TICK)
    ref_by_index = {b.index: b for b in ref.bars}

    applied = sum((t.qty for t in tape), Decimal(0)) - ref.dropped_qty
    got = sum((b.volume for b in bars), Decimal(0))
    if got != applied:
        first = next(
            (
                b.index
                for b in bars
                if b.index not in ref_by_index or b.volume != ref_by_index[b.index].volume
            ),
            None,
        )
        out.append(
            Violation(
                "BI-1",
                spec.kind,
                label,
                first,
                seed,
                f"sum(bar.volume) {got} != sum(trade.qty) {applied}",
            )
        )
    if spec.kind == "volume":
        quota = Decimal(spec.param_value)
        _first(
            out,
            "BI-1",
            spec,
            label,
            seed,
            bars,
            lambda b: (
                f"closed volume bar holds {b.volume}, threshold {quota} (split rule)"
                if b.closed and b.volume != quota
                else None
            ),
        )
    _first(out, "BI-2", spec, label, seed, bars, _bi2)

    def bi3(b: Bar) -> str | None:
        if not b.min_delta <= b.delta <= b.max_delta:
            return f"min {b.min_delta} <= delta {b.delta} <= max {b.max_delta} fails"
        r = ref_by_index.get(b.index)
        if r is not None and (r.min_delta, r.max_delta) != (b.min_delta, b.max_delta):
            return (
                f"path extremes ({b.min_delta}, {b.max_delta}) != intrabar path "
                f"({r.min_delta}, {r.max_delta})"
            )
        return None

    _first(out, "BI-3", spec, label, seed, bars, bi3)

    again = run(fac, spec, tape)
    d = comparator.compare(bars, again)
    if d:
        out.append(Violation("BI-4", spec.kind, label, d[0].index, seed, str(d[0])))
    want_hash = compute_spec_hash(spec)
    _first(
        out,
        "BI-4",
        spec,
        label,
        seed,
        bars,
        lambda b: f"spec_hash {b.spec_hash} != {want_hash}" if b.spec_hash != want_hash else None,
    )

    if cuts and len(tape) > 1:
        rng = random.Random(seed if seed is not None else 0)  # noqa: S311 - reproducible cuts
        random_points = rng.sample(range(1, len(tape)), min(cuts, len(tape) - 1))
        points = sorted(set(random_points) | set(fixed_cuts(fac, spec, tape)))
        d = comparator.compare(bars, run_with_cuts(fac, spec, tape, points))
        if d:
            out.append(
                Violation("BI-5", spec.kind, label, d[0].index, seed, f"cuts {points}: {d[0]}")
            )
    _first(out, "BI-6", spec, label, seed, bars, _bi6)

    d = comparator.compare(ref.bars, bars)
    if d:
        out.append(
            Violation(
                "REF",
                spec.kind,
                label,
                d[0].index,
                seed,
                "differs from the reference:\n" + comparator.render(d, 5),
            )
        )
    return out


def report(violations: Sequence[Violation]) -> str:
    return "\n".join(str(v) for v in violations)
