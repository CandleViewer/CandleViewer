"""Builder throughput harness (E12-Q05 slice 2, #528; budget #5).

Replays a seeded synthetic tape (`bar_determinism.generator`, no network, C-13.5) through the
per-symbol spec matrix at once, as one live symbol runs it: T04's `STANDARD_SPECS` (BQ-03, one
matrix with the determinism harness), ten specs over the six kinds (time, tick, volume, range,
delta, renko), built by the shipped production builders on the tape's `Decimal` prices and
sizes: no float fast path. Each print goes to every builder's `on_trade`, which is the per-print
work the set's fan-out does; the set's bus/router/store composition is NOT included (a later
slice). The delta specs need a tape whose |delta| reaches the threshold, so the tape is skewed
to buys. Throughput is a `throughput`-class metric (warn 10 % / fail 25 %, `compare.py`).

Time, resource and GC readings are injected (`Probes`), so the unit tests check the counting
and sampling mechanics without measuring real speed. Only the builder loop is timed: the tape
is generated in chunks outside the timed window and the timed segments are summed. The first
`warmup` prints run untimed, so `prints_per_s` and `elapsed_s` cover the measured prints only.
Per-print latency is sampled every `sample_every`-th measured print (the whole six-builder step
is timed; each sample adds two clock reads to the timed window). Peak RSS is the process
high-water mark (`ru_maxrss`, normalised to MiB on Linux and macOS), not a per-run delta.
Run: `python -m bench.bars.throughput --prints 100000 --runs 3`.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import resource
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from itertools import islice

import structlog

from bench.bar_determinism.generator import TICK, GenConfig, iter_trades
from bench.bar_determinism.invariants import STANDARD_SPECS, make_builder
from bench.bars import HARNESS_VERSION, rows
from bench.bars.scrub import scrub
from bench.bars.stats import (
    RUNS_PER_CONFIG,
    Distribution,
    distribution,
    median_run,
    relative_spread,
)
from candleviewer.bars.models import BarBuilder
from candleviewer.exchange.base.models import TradeEvent

SYMBOL = "BTCUSDT"
SIZES = (100_000, 1_000_000, 5_000_000)
SEED = 12528
BUY_SKEW = 0.2  # so delta bars close (BQ-03); the soak feed's alternating prints leave them inert


def peak_rss_mib() -> float:
    """Process high-water RSS in MiB (`ru_maxrss` is KiB on Linux, bytes on macOS)."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0)


@dataclass(slots=True)
class Probes:
    """Injected readings: monotonic ns, process peak RSS (MiB), cumulative GC collections."""

    now_ns: Callable[[], int] = time.perf_counter_ns
    peak_rss_mib: Callable[[], float] = lambda: peak_rss_mib()
    gc_collections: Callable[[], int] = lambda: sum(s["collections"] for s in gc.get_stats())


@dataclass(slots=True)
class RunResult:
    prints: int
    measured: int  # prints after warm-up: the ones `elapsed_s` and `prints_per_s` cover
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
    return [make_builder(spec, SYMBOL, TICK) for spec in STANDARD_SPECS.values()]


def tape(prints: int, seed: int = SEED) -> Iterable[TradeEvent]:
    return iter_trades(GenConfig(seed=seed, n=prints, buy_skew=BUY_SKEW))


def run_once(
    trades: Iterable[TradeEvent],
    builders: list[BarBuilder],
    *,
    probes: Probes | None = None,
    sample_every: int = 100,
    warmup: int = 0,
    chunk: int = 4_096,
) -> RunResult:
    """Feed `trades` through every builder; count closed bars by kind and time the steps."""
    if sample_every < 1 or warmup < 0 or chunk < 1:
        raise ValueError("sample_every and chunk must be >= 1 and warmup >= 0")
    p = probes or Probes()
    closed: dict[str, int] = {b.spec.kind: 0 for b in builders}
    samples: list[float] = []
    gc0, n, measured, timed_ns = p.gc_collections(), 0, 0, 0
    it = iter(trades)
    while batch := list(islice(it, chunk)):  # generation stays outside the timed window
        skip = max(0, min(len(batch), warmup - n))
        n += len(batch)
        for trade in batch[:skip]:  # warm-up: run and count bars, never timed
            for b in builders:
                for upd in b.on_trade(trade):
                    closed[b.spec.kind] += upd.kind == "close"
        if skip == len(batch):
            continue
        t0 = p.now_ns()
        for trade in batch[skip:]:
            measured += 1
            timed = measured % sample_every == 0
            s0 = p.now_ns() if timed else 0
            for b in builders:
                for upd in b.on_trade(trade):
                    closed[b.spec.kind] += upd.kind == "close"
            if timed:
                samples.append((p.now_ns() - s0) / 1_000.0)
        timed_ns += p.now_ns() - t0
    elapsed = max(timed_ns, 1) / 1e9
    if not samples:
        samples = [0.0]
    return RunResult(
        prints=n,
        measured=measured,
        elapsed_s=elapsed,
        prints_per_s=measured / elapsed,
        latency_us=distribution(samples),
        bars_by_kind=closed,
        peak_rss_mib=p.peak_rss_mib(),
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
                f"- step latency us, all specs (n={lat.n}, every {median.sample_every}th): "
                f"p50 {lat.p50:.1f} p95 {lat.p95:.1f} p99 {lat.p99:.1f}",
                f"- peak RSS {median.peak_rss_mib:.0f} MiB; GC collections {median.gc_collections}",
                f"- bars closed: {json.dumps(median.bars_by_kind, sort_keys=True)}",
                f"- seed {median.seed}, harness `{median.harness}`; Decimal prices, no network",
                "",
                rows.render(),
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
