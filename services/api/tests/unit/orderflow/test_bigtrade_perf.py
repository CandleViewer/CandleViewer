"""Perf budget evidence for the big-trade engine (perf label; C-13.9).

Runs in the required `unit-backend` lane, under coverage and on shared runners, so the
assertions must be noise-robust (pattern of #1943 / #1956): GC disabled around the timed loops,
fastest-of-N rounds via `perf_counter_ns` (host load only ever adds time, so the minimum is the
least-contended estimate), a non-zero baseline, and:

* a **complexity ratio**: 100x the prints may cost at most 160x the CPU time (per-print work is
  O(1) amortised; no window rescans, no state growing with the prints, threat model D16; the
  measured reason is on the test), and
* a **generous absolute sanity bound**: 50-print batch < 20 ms.

**Target, not asserted here:** <= 2 ms p95 per 50-print push (US-MKT-006: <= 2 ms added to
ingest->bus) and >= 5 000 prints/s (budget #5). The repo has no dedicated unit perf lane (the
`perf` marker only runs in the nightly integration perf workflows), so enforcing the exact 2 ms
figure is E22-Q03 load/perf work. Measured on the dev laptop without coverage: p95 1.44-1.57 ms,
~44 000 prints/s (PR #2001)."""

from __future__ import annotations

import gc
import random
import time
from collections.abc import Callable
from decimal import Decimal

import pytest

from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from tests.unit.orderflow._bigtrade_helpers import TICK, trade

pytestmark = pytest.mark.perf

ROUNDS = 5  # fastest-of-N
PAIR_ROUNDS = 5  # the scaling pair's interleaved rounds, each side's fastest kept (#5391)
BATCH = 50
#: Untimed warm-up to steady state: a 2 000 ms cluster window at 5 prints/ms buffers 10 000
#: prints, so both runs are timed with full (bounded) state and the ratio is per-print cost.
WARM = 220


def _batches(n: int, seed: int) -> list[list[TradeEvent]]:
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible bench data
    ts, out = 0, []
    for _ in range(n):
        batch = []
        for _ in range(BATCH):
            ts += 200  # 5 000 prints/s of print time
            px = f"{60000 + rng.randint(-50, 50) / 10:.1f}"
            side = rng.choice(["buy", "sell"])
            batch.append(trade(ts, px, f"{rng.lognormvariate(-2, 1.5):.3f}", side))
        out.append(batch)
    return out


def _engine() -> BigTradeEngine:  # most expensive path: percentile + clustering
    cfg = BigTradeConfig(
        mode="percentile", value=Decimal("99"), cluster_window_ms=2000, cluster_tolerance_ticks=2
    )
    return BigTradeEngine("BTCUSDT", TICK, cfg)


def _pass_ns(
    batches: list[list[TradeEvent]], clock: Callable[[], int] = time.perf_counter_ns
) -> int:
    """One pass over `batches[WARM:]` on a fresh engine warmed with `batches[:WARM]`, timed on
    *clock*."""
    eng = _engine()
    for b in batches[:WARM]:
        eng.process(b)
    t0 = clock()
    for b in batches[WARM:]:
        eng.process(b)
    return clock() - t0


def _best_ns(batches: list[list[TradeEvent]]) -> int:
    """Fastest of ROUNDS passes over `batches[WARM:]`, each on a fresh engine warmed with
    `batches[:WARM]` (same prints, same work)."""
    gc.collect()
    gc.disable()  # a GC pause inside one timed loop would skew the sample
    try:
        return min(_pass_ns(batches) for _ in range(ROUNDS))
    finally:
        gc.enable()


# #5391: a run is about 24 s of CPU time; under load 24-38 on an 8-vCPU host it took 58-127 s
# of wall time, past the suite's 120 s default.
@pytest.mark.timeout(300)
def test_perf_engine_cost_scales_linearly_with_prints() -> None:
    """The pair is timed interleaved, small then large in each of PAIR_ROUNDS rounds, on the
    thread's CPU time, and each side keeps its fastest round (#5391). Interleaved, a busy round
    costs both sides; on CPU time, a slice the scheduler gives another process costs neither.

    The large side is 100x the prints, and the bound 160x (60 % slack), as measured (#5391): with
    both sides warmed to the same bounded state, an engine whose per-print cost grows with the
    prints it has seen read only ~14x at a 10x pair, inside the noise of a loaded runner, so a
    10x pair could not both guard that and not flake. At 100x the same mutant read 339-407x
    (state rescanned once per batch), while the clean engine read 120-139x under load 24-38 on
    the lane's 8-vCPU host; no quiet host was free, and a linear engine's floor is 100x."""
    small_batches = _batches(WARM + 20, seed=5)  # 20 timed batches = 1 000 prints
    large_batches = _batches(WARM + 2000, seed=5)  # 2 000 timed batches = 100 000 prints
    small = large = 0
    gc.collect()
    gc.disable()  # a GC pause inside one timed loop would skew the sample
    try:
        for _ in range(PAIR_ROUNDS):
            s_ns = _pass_ns(small_batches, time.thread_time_ns)
            l_ns = _pass_ns(large_batches, time.thread_time_ns)
            small = s_ns if small == 0 else min(small, s_ns)
            large = l_ns if large == 0 else min(large, l_ns)
    finally:
        gc.enable()
    assert small > 0  # non-zero baseline (ns timer resolution)
    assert large <= 160 * small, f"100x prints cost {large / small:.1f}x CPU time"


def test_perf_batch_absolute_sanity_bound() -> None:
    per_batch_ns = _best_ns(_batches(WARM + 40, seed=6)) / 40
    assert 0 < per_batch_ns < 20_000_000, f"{per_batch_ns / 1e6:.2f} ms per {BATCH}-print batch"
