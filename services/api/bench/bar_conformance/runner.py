"""E12-Q02 conformance runner: tapes -> the live `BarBuilderSet` fan-out -> goldens.

Extends the E12-T04 harness; reuses its comparator, builders factory and `final_bars`.
Every `(tape, bar_type, param)` pair is fed through ONE `BarBuilderSet` (bus -> lane -> every
registered builder), never through individual builders, so "live and replay identical" is
structural. Goldens live in `packages/fixtures/golden/bars/conformance/goldens/<tape>/<pair>.jsonl`
(canonical `comparator.line` rows, Decimal strings), regenerated only by
`python -m bench.bar_determinism.regen_goldens --suite conformance --write --reason ...`.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from bench.bar_determinism import comparator, reference, tapes
from bench.bar_determinism.generator import TICK
from candleviewer.bars.builder_set import BarBuilderSet, default_factory, renko_factory
from candleviewer.bars.emit import BarEmission, EmitRouter
from candleviewer.bars.errors import BarSpecError
from candleviewer.bars.models import Bar, BarBuilder, BarSpec
from candleviewer.bars.spec import from_wire
from candleviewer.bars.state_store import StateStore
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.models import TradeEvent

ENV = "demo"
GOLDEN_ROOT = tapes.BANK_DIR / "goldens"
MANIFEST = tapes.BANK_DIR / "MANIFEST.toml"


@dataclass(frozen=True)
class Case:
    label: str  # "vol:50"
    bar_type: str  # wire bar_type
    param: str  # wire param

    @property
    def stem(self) -> str:
        return self.label.replace(":", "-")


#: Scope matrix of the ticket. `from_wire` is the single source of what each pair means.
CASES: tuple[Case, ...] = (
    Case("time:1", "time", "1"),
    Case("time:5", "time", "5"),
    Case("time:1d", "time", "D"),
    Case("tick:100", "tick", "100"),
    Case("tick:1000", "tick", "1000"),
    Case("vol:50", "volume", "50"),
    Case("range:20", "range", "20"),
    Case("delta:500", "delta", "500"),
    Case("renko:30", "renko", "30"),
    Case("renko:atr:14", "renko", "atr:14"),
    Case("heikin_ashi:5", "heikin_ashi", "5"),
)


def resolve(case: Case) -> BarSpec | str:
    """The spec, or the typed rejection message (ATR renko deferred, heikin-ashi not a builder)."""
    try:
        return from_wire(case.bar_type, case.param)
    except BarSpecError as e:
        return str(e)


def live_cases() -> dict[str, BarSpec]:
    return {c.label: s for c in CASES if not isinstance(s := resolve(c), str)}


def rejected_cases() -> dict[str, str]:
    return {c.label: s for c in CASES if isinstance(s := resolve(c), str)}


def _base(spec: BarSpec, symbol: str) -> BarBuilder:
    # TODO(#2191): production `default_factory` lacks range/delta (and renko is flag-gated), so
    # the runner composes them here. Until #2191 lands, 2 of the 9 pairs do not use the
    # production factory; the set, bus, lanes and every builder class are still production code.
    if spec.kind == "range":
        return RangeBarBuilder(spec, symbol, lambda _s: TICK)
    if spec.kind == "delta":
        return DeltaBarBuilder(spec, symbol)
    return default_factory(spec, symbol)


def factory(spec: BarSpec, symbol: str) -> BarBuilder:
    return renko_factory(lambda _s: TICK, base=_base)(spec, symbol)


class _Sink:
    name = "conformance"

    def __init__(self) -> None:
        self.latest: dict[str, dict[int, Bar]] = {}
        #: Every update in emission order: (kind, amended, canonical bar row).
        self.updates: dict[str, list[tuple[str, bool, str]]] = {}

    async def emit(self, emission: BarEmission) -> None:
        h = emission.spec.spec_hash
        d, seq = self.latest.setdefault(h, {}), self.updates.setdefault(h, [])
        for u in emission.updates:
            d[u.bar.index] = u.bar
            seq.append((u.kind, u.amended, comparator.line(u.bar)))


class _Clock:
    def __init__(self) -> None:
        self.t = 0

    def __call__(self) -> int:
        return self.t


async def _settle(bus: Bus, s: BarBuilderSet) -> None:
    for _ in range(100_000):
        await asyncio.sleep(0)
        if not any(lane.lock.locked() for lane in s._lanes.values()) and all(
            q.qsize() == 0 for q in bus._subscriptions
        ):
            await asyncio.sleep(0)
            if not any(lane.lock.locked() for lane in s._lanes.values()):
                return
    raise AssertionError("lanes did not settle")


Update = tuple[str, bool, str]


async def run_set(
    tape: Sequence[TradeEvent],
    specs: dict[str, BarSpec],
    symbol: str,
    chunk: int = 4_000,
    tick: bool = True,
) -> dict[str, list[Bar]]:
    """Final bars per spec label (latest emission per index)."""
    return (await run_full(tape, specs, symbol, chunk, tick))[0]


async def run_full(
    tape: Sequence[TradeEvent],
    specs: dict[str, BarSpec],
    symbol: str,
    chunk: int = 4_000,
    tick: bool = True,
) -> tuple[dict[str, list[Bar]], dict[str, list[Update]]]:
    """Publish `tape` to the bus in `chunk`-sized bursts; after each burst settle and (when
    `tick`) drive the set's clock to the burst's last trade time, as the live ticker would, then
    take one forming-bar sample, as the live sampler would (24 §3.2, #2022)."""
    bus, sink, clock = Bus(), _Sink(), _Clock()
    topic = Topic(env=ENV, domain="md", symbol=symbol, detail="trade")
    with tempfile.TemporaryDirectory() as root:
        s = BarBuilderSet(
            bus, ENV, EmitRouter([sink]), StateStore(Path(root)), now_us=clock, factory=factory
        )
        for label, spec in specs.items():
            await s.register(spec, symbol, f"conformance:{label}")
        for i in range(0, len(tape), chunk):
            burst = tape[i : i + chunk]
            for t in burst:
                await bus.publish(topic, t)
            await _settle(bus, s)
            if tick:
                clock.t = max(clock.t, burst[-1].ts_event)
                await s.tick()
            await s.sample()  # the forming bar, as the live 250 ms sampler routes it (#2022)
        await s.stop()
    finals = {
        label: [b for _, b in sorted(sink.latest.get(spec.spec_hash, {}).items())]
        for label, spec in specs.items()
    }
    return finals, {label: sink.updates.get(sp.spec_hash, []) for label, sp in specs.items()}


def run(tape: Sequence[TradeEvent], symbol: str, chunk: int = 4_000) -> dict[str, list[Bar]]:
    return asyncio.run(run_set(tape, live_cases(), symbol, chunk))


def reference_diffs(
    spec: BarSpec, symbol: str, tape: Sequence[TradeEvent], bars: Sequence[Bar]
) -> list[comparator.Diff]:
    """Live bars vs the independent reference (`bar_determinism.reference`, written from the
    spec text). The reference flushes time bars past the last bucket, so the time tail's `closed`
    flag is the one documented, ignored difference."""
    ref = reference.build(spec, symbol, list(tape), TICK).bars
    diffs = comparator.compare(ref, bars)
    last = len(ref) - 1
    return [
        d for d in diffs if not (spec.kind == "time" and d.field == "closed" and d.position == last)
    ]


def lines(bars: Sequence[Bar]) -> list[str]:
    return [comparator.line(b) for b in bars]


def golden_path(tape: str, label: str) -> Path:
    return GOLDEN_ROOT / tape / f"{label.replace(':', '-')}.jsonl"


def read_golden(tape: str, label: str) -> list[str]:
    return golden_path(tape, label).read_text(encoding="utf-8").splitlines()


def digest(ls: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(ls) + "\n").encode()).hexdigest()


def explain(
    spec: BarSpec,
    symbol: str,
    tape: Sequence[TradeEvent],
    expected: Sequence[str],
    actual: Sequence[str],
) -> str:
    """'' when equal, else the first divergent bar (index, field, expected, actual) plus the
    first trade whose emission produced the diverging value, found by a per-trade replay."""
    diffs = comparator.compare_lines(expected, actual)
    if not diffs:
        return ""
    d = diffs[0]
    b = factory(spec, symbol)
    trigger: str | None = None
    for i, t in enumerate(tape):
        ups = list(b.on_trade(t))
        if spec.kind == "time":
            ups += b.on_clock(t.ts_event)
        forming = b.forming()  # a print that only extends a bar emits nothing (#2022)
        if forming is not None:
            ups.append(forming)
        for u in ups:
            if u.bar.index == d.index and comparator.row(u.bar).get(d.field) != d.expected:
                trigger = (
                    f"trade #{i} id={t.trade_id} ts={t.ts_event} px={t.price} "
                    f"qty={t.qty} side={t.side}"
                )
                break
        if trigger:
            break
    more = f" (+{len(diffs) - 1} more)" if len(diffs) > 1 else ""
    return f"first divergence: {d}{more}\n  triggering {trigger or 'trade: <none; bar missing>'}"


__all__ = [
    "CASES",
    "TICK",
    "Case",
    "Decimal",
    "comparator",
    "explain",
    "live_cases",
    "reference",
    "run",
    "run_full",
    "run_set",
]
