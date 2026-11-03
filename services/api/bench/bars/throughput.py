"""Builder throughput harness (E12-Q05 slice 2, #528; budget #5).

Replays a seeded synthetic tape (`bar_determinism.generator`, no network, C-13.5) through all
six builder families at once, as one live symbol runs them, using the production factory
(`production_factory`, renko on) and the tape's `Decimal` prices and sizes: no float fast path.
Each print goes to every builder's `on_trade`, which is the per-print work the set's fan-out
does; the set's bus/router/store composition is NOT included (a later slice). BQ-03: six
families (time, tick, volume, range, delta, renko), not five. The delta series needs a tape
whose |delta| reaches its threshold, so the tape is skewed to buys.

Time, resource and GC readings are injected (`Probes`), so the unit tests check the counting
and sampling mechanics without measuring real speed. Per-print latency is sampled every
`sample_every`-th print (the whole six-builder step is timed) after `warmup` prints.
Run: `python -m bench.bars.throughput --prints 100000 --runs 3`.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import resource
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field

import structlog

from bench.bar_determinism.generator import TICK, GenConfig, iter_trades
from bench.bars import HARNESS_VERSION
from bench.bars.scrub import scrub
from bench.bars.stats import (
    RUNS_PER_CONFIG,
    Distribution,
    distribution,
    median_run,
    relative_spread,
)
from candleviewer.bars.builder_set import production_factory
from candleviewer.bars.models import BarBuilder, BarSpec
from candleviewer.bars.spec import from_wire
from candleviewer.exchange.base.models import TradeEvent

SYMBOL = "BTCUSDT"
#: The six families run together (BQ-03), as wire pairs.
FAMILIES: tuple[tuple[str, str], ...] = (
    ("time", "1"),
    ("tick", "100"),
    ("volume", "50"),
    ("delta", "1"),
    ("range", "10"),
    ("renko", "30"),
)
SIZES = (100_000, 1_000_000, 5_000_000)
SEED = 12528
BUY_SKEW = 0.2  # so delta bars close (BQ-03); the soak feed's alternating prints leave them inert


@dataclass(slots=True)
class Probes:
    """Injected readings: monotonic ns, peak RSS (KiB), cumulative GC collections."""

    now_ns: Callable[[], int] = time.perf_counter_ns
    rss_kib: Callable[[], int] = lambda: int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    gc_collections: Callable[[], int] = lambda: sum(s["collections"] for s in gc.get_stats())


@dataclass(slots=True)
class RunResult:
    prints: int
    elapsed_s: float
    prints_per_s: float
    latency_us: Distribution
    bars_by_kind: dict[str, int]
    peak_rss_mib: float
    gc_collections: int
    sample_every: int
    warmup: int
    seed: int = SEED
    harness: str = HARNESS_VERSION
    notes: list[str] = field(default_factory=list)


def make_builders() -> list[BarBuilder]:
    factory = production_factory(lambda _s: TICK, renko_enabled=True)
    specs: list[BarSpec] = [from_wire(t, p) for t, p in FAMILIES]
    return [factory(s, SYMBOL) for s in specs]


def tape(prints: int, seed: int = SEED) -> Iterable[TradeEvent]:
    return iter_trades(GenConfig(seed=seed, n=prints, buy_skew=BUY_SKEW))


def run_once(
    trades: Iterable[TradeEvent],
    builders: list[BarBuilder],
    *,
    probes: Probes | None = None,
    sample_every: int = 100,
    warmup: int = 0,
) -> RunResult:
    """Feed `trades` through every builder; count closed bars by kind and time the steps."""
    if sample_every < 1 or warmup < 0:
        raise ValueError("sample_every must be >= 1 and warmup >= 0")
    p = probes or Probes()
    closed: dict[str, int] = {b.spec.kind: 0 for b in builders}
    samples: list[float] = []
    gc0, t_start, n = p.gc_collections(), p.now_ns(), 0
    for trade in trades:
        n += 1
        timed = n > warmup and (n - warmup) % sample_every == 0
        t0 = p.now_ns() if timed else 0
        for b in builders:
            for upd in b.on_trade(trade):
                if upd.kind == "close":
                    closed[b.spec.kind] += 1
        if timed:
            samples.append((p.now_ns() - t0) / 1_000.0)
    elapsed = max(p.now_ns() - t_start, 1) / 1e9
    if not samples:
        samples = [0.0]
    return RunResult(
        prints=n,
        elapsed_s=elapsed,
        prints_per_s=n / elapsed,
        latency_us=distribution(samples),
        bars_by_kind=closed,
        peak_rss_mib=p.rss_kib() / 1024.0,
        gc_collections=p.gc_collections() - gc0,
        sample_every=sample_every,
        warmup=warmup,
    )


def median_of_runs(results: list[RunResult]) -> tuple[RunResult, float]:
    """The median run by prints/s and the relative spread across the three (flakiness signal)."""
    if len(results) != RUNS_PER_CONFIG:
        raise ValueError(f"expected {RUNS_PER_CONFIG} runs, got {len(results)}")
    rates = [r.prints_per_s for r in results]
    mid = median_run(rates)
    return next(r for r in results if r.prints_per_s == mid), relative_spread(rates)


def render(prints: int, median: RunResult, spread: float) -> str:
    lat = median.latency_us
    return scrub(
        "\n".join(
            [
                f"## builder throughput, {prints} prints (budget #5, median of 3)",
                "",
                f"- prints/s: {median.prints_per_s:.0f} (run spread {spread * 100:.1f} %)",
                f"- six-builder step latency us (n={lat.n}, every {median.sample_every}th): "
                f"p50 {lat.p50:.1f} p95 {lat.p95:.1f} p99 {lat.p99:.1f}",
                f"- peak RSS {median.peak_rss_mib:.0f} MiB; GC collections {median.gc_collections}",
                f"- bars closed: {json.dumps(median.bars_by_kind, sort_keys=True)}",
                f"- seed {median.seed}, harness `{median.harness}`; Decimal prices, no network",
            ]
        )
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prints", type=int, default=SIZES[0])
    ap.add_argument("--sample-every", type=int, default=100)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    # Builder logs (late drops, first bar) would pollute stdout and the timing.
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))
    runs = [
        run_once(
            tape(a.prints), make_builders(), sample_every=a.sample_every, warmup=a.prints // 20
        )
        for _ in range(RUNS_PER_CONFIG)
    ]
    med, spread = median_of_runs(runs)
    print(scrub(json.dumps(asdict(med), default=str)) if a.json else render(a.prints, med, spread))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
