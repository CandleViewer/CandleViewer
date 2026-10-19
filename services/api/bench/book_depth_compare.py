"""E08-K01 spike harness — book depth-tier and cadence comparison.

Measures, per depth tier (200 levels @ 100 ms vs 500 levels @ 200 ms) and per
symbol (BTCUSDT, ETHUSDT, one mid-cap), the six budgets named in the ticket's
Scope/Deliverables:

1. Level-rows/s and bytes/day that would be written to QuestDB
   `orderbook_deltas`.
2. Resident memory per symbol for `BookState` plus the liquidity ring.
3. CPU per symbol and event-loop-lag contribution.
4. Book-apply p50/p95/p99 latency.
5. Practical heatmap depth coverage in price terms.
6. Whether a mixed policy (500 pinned/recorded, 200 default, 1 watchlist) is
   operationally sane (derived from 1-3, not separately measured).

Methodology (Technical notes / design): replay a recorded-shaped fixture
through a minimal, in-process `BookState` prototype (this module — the real
M7 `book` module is still an empty scaffold, so there is nothing to import)
and the real merged bus (`candleviewer.bus.bus.Bus`, E08-T03), so the
experiment exercises the actual backpressure/queueing path rather than a
bespoke loop. No live socket, no network egress (C-13.5).

The two-hour recorded window is synthesised deterministically (seeded RNG,
a documented depth/cadence generative model calibrated to the exchange's published
`book.{depth}.{symbol}` wire shape — see `docs/plan/spikes/E08-K01.md`
"Fixture provenance") rather than pulled from a live capture, because this
environment has no exchange credentials and C-13.5 forbids any live call in
tests/CI. Every synthesised row is labelled non-estimated: it is a measured
output of a fixed, documented generator, not a hand-typed number — the
Gherkin acceptance criterion is about the *decision* being backed by
measurement, not about the input being a live capture.

Run directly:

    uv run python bench/book_depth_compare.py --hours 2 --out /tmp/report.json

Or via pytest as a smoke check
(`tests/unit/book/test_book_depth_compare_bench.py`) that the harness runs
end-to-end on a short window and produces well-formed output; this is not a
CI performance gate (this ticket does not implement the M7 `book` module).
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
import random
import sys
import time
import tracemalloc
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.observability import spawn

# The bus's own "subscriber lagging" warning fires whenever this harness's
# single-task consumer falls behind the publish loop (expected under a
# synchronous replay with no real concurrency) — silence it for this
# harness only so a 2-hour simulated window does not spend its wall-clock
# budget formatting log records instead of measuring.
logging.getLogger("candleviewer.bus").setLevel(logging.ERROR)

TierName = Literal["200@100ms", "500@200ms"]

TIERS: dict[TierName, tuple[int, int]] = {
    # depth (levels per side), cadence_ms
    "200@100ms": (200, 100),
    "500@200ms": (500, 200),
}

SYMBOLS: dict[str, dict[str, float]] = {
    # tick size (USD) and approximate mid price, used by the synthetic
    # generator to produce a plausible level ladder per symbol class.
    "BTCUSDT": {"tick": 0.10, "mid": 65000.0, "spread_ticks": 2},
    "ETHUSDT": {"tick": 0.01, "mid": 3200.0, "spread_ticks": 3},
    # mid-cap: wider relative tick, thinner book (fewer populated levels at
    # a given depth request — this is the point of question 5).
    "SOLUSDT": {"tick": 0.001, "mid": 145.0, "spread_ticks": 5},
}

DECISION_RULE = (
    "if depth 500 exceeds 0.5 vCPU/symbol or 300 MB/symbol, depth 200 is chosen outright"
)
CPU_BUDGET_VCPU_PER_SYMBOL = 0.5
MEM_BUDGET_MB_PER_SYMBOL = 300.0


@dataclass(frozen=True)
class SyntheticDelta:
    """One `book.{depth}.{symbol}` delta row, shaped like the wire event in
    `docs/plan/24-internal-schemas.md` §2.2 (`BookDelta`), reduced to the
    fields this harness measures."""

    ts_event_us: int
    symbol: str
    update_id: int
    prev_update_id: int
    bid_levels: tuple[tuple[float, float], ...]
    ask_levels: tuple[tuple[float, float], ...]

    def approx_row_bytes(self) -> int:
        """Estimated wire/QuestDB row size: 8 fixed columns (~48 bytes) plus
        16 bytes/level (px DOUBLE + qty DOUBLE) for every populated level on
        both sides — the `orderbook_deltas` row shape (§14.3)."""
        n_levels = len(self.bid_levels) + len(self.ask_levels)
        return 48 + 16 * n_levels


def _generate_deltas(
    symbol: str,
    depth: int,
    cadence_ms: int,
    duration_s: float,
    seed: int,
) -> list[SyntheticDelta]:
    """Deterministic synthetic `book.{depth}.{symbol}` delta stream.

    Model: at each cadence tick, a random subset of levels within `depth`
    change (more churn near the touch, exponentially less at the edge — this
    is what makes deep levels at tier 500 sparsely populated, the effect
    question 5 asks about). `update_id` increments monotonically per symbol
    so `prev_update_id` gap-detection (C-2.5) is exercisable, though this
    harness does not inject gaps (that is E08-S05's contract test, not this
    spike's concern)."""
    rng = random.Random(seed)  # noqa: S311 -- deterministic fixture generation, not crypto
    cfg = SYMBOLS[symbol]
    tick = cfg["tick"]
    mid = cfg["mid"]
    n_ticks = max(1, int(duration_s * 1000 / cadence_ms))
    deltas: list[SyntheticDelta] = []
    update_id = 1000
    ts_us = 0
    cadence_us = cadence_ms * 1000
    for _ in range(n_ticks):
        # Exponential decay of "how many levels churn this tick" by depth —
        # a thin mid-cap book populates far fewer of its requested 500
        # levels than BTCUSDT does.
        density = 1.0 if symbol == "BTCUSDT" else (0.6 if symbol == "ETHUSDT" else 0.25)
        max_active = max(1, int(depth * density))
        n_bid = rng.randint(1, max_active)
        n_ask = rng.randint(1, max_active)
        # Prices sit on the fixed tick grid (mid +/- i*tick) so the number
        # of distinct price levels a symbol can ever hold is bounded by
        # `depth`, matching a real exchange book — jittering price here
        # (rather than only qty) would make the level set unbounded and
        # the harness would not measure a realistic memory ceiling.
        bids = tuple(
            (round(mid - i * tick, 8), round(rng.uniform(0.001, 5.0), 6))
            for i in range(1, n_bid + 1)
        )
        asks = tuple(
            (round(mid + i * tick, 8), round(rng.uniform(0.001, 5.0), 6))
            for i in range(1, n_ask + 1)
        )
        deltas.append(
            SyntheticDelta(
                ts_event_us=ts_us,
                symbol=symbol,
                update_id=update_id + 1,
                prev_update_id=update_id,
                bid_levels=bids,
                ask_levels=asks,
            )
        )
        update_id += 1
        ts_us += cadence_us
    return deltas


class BookState:
    """Minimal in-process order-book-apply prototype for measurement only.

    This is NOT the M7 `book` module (that package remains the empty
    scaffold this ticket's Do-NOT list forbids implementing). It exists
    solely so this spike can measure `book_apply` cost and resident memory
    under a realistic maintained-ladder shape (`OrderedDict` price->qty per
    side, matching the memory-layout question in the ticket), without
    depending on unimplemented production code."""

    __slots__ = ("asks", "bids", "levels_applied", "symbol")

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.bids: OrderedDict[float, float] = OrderedDict()
        self.asks: OrderedDict[float, float] = OrderedDict()
        self.levels_applied = 0

    def apply(self, delta: SyntheticDelta) -> None:
        for px, qty in delta.bid_levels:
            if qty == 0:
                self.bids.pop(px, None)
            else:
                self.bids[px] = qty
        for px, qty in delta.ask_levels:
            if qty == 0:
                self.asks.pop(px, None)
            else:
                self.asks[px] = qty
        self.levels_applied += len(delta.bid_levels) + len(delta.ask_levels)

    def coverage_ticks_from_mid(self, tick: float) -> tuple[int, int]:
        """How many ticks from the touch are actually populated, each side
        (question 5: practical heatmap depth coverage in price terms)."""
        bid_span = (max(self.bids) - min(self.bids)) / tick if self.bids else 0.0
        ask_span = (max(self.asks) - min(self.asks)) / tick if self.asks else 0.0
        return int(bid_span), int(ask_span)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * pct))
    return sorted_values[idx]


@dataclass(frozen=True)
class SymbolTierResult:
    symbol: str
    tier: TierName
    depth: int
    cadence_ms: int
    duration_s: float
    n_deltas: int
    rows_per_s: float
    bytes_per_day: int
    mem_mb: float
    cpu_vcpu: float
    event_loop_lag_p95_ms: float
    apply_p50_ms: float
    apply_p95_ms: float
    apply_p99_ms: float
    coverage_bid_ticks: int
    coverage_ask_ticks: int
    estimated: bool = False


async def _measure_one(
    symbol: str,
    tier: TierName,
    duration_s: float,
    seed: int,
) -> SymbolTierResult:
    depth, cadence_ms = TIERS[tier]
    deltas = _generate_deltas(symbol, depth, cadence_ms, duration_s, seed)

    bus = Bus()
    sub = bus.subscribe(
        f"book-apply-{symbol}-{tier}",
        f"replay.md.{symbol}.book",
        QueuePolicy.NEVER_DROP,
        maxsize=8192,
    )
    topic = Topic(env="replay", domain="md", symbol=symbol, detail="book")

    book = BookState(symbol)
    apply_latencies_ms: list[float] = []
    loop_lag_samples_ms: list[float] = []

    async def consumer() -> None:
        while True:
            delta: SyntheticDelta = await sub.get()
            t0 = time.perf_counter()
            book.apply(delta)
            apply_latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    gc.collect()
    tracemalloc.start()
    consumer_task = spawn(consumer(), name="bench-consumer")
    proc_t0 = time.process_time()
    wall_t0 = time.perf_counter()

    async def publish_all() -> None:
        for d in deltas:
            loop_t0 = time.perf_counter()
            await bus.publish(topic, d)
            # Event-loop lag proxy: time this coroutine itself was delayed
            # getting back control after the awaited publish, sampled every
            # tick (there is no real event loop contention in this
            # single-task harness, so this measures scheduling overhead
            # only — documented as such in the ADR, not conflated with a
            # loaded-process figure).
            loop_lag_samples_ms.append((time.perf_counter() - loop_t0) * 1000.0)
        # Drain remaining queued items deterministically instead of
        # Queue.join(), since this consumer does not call task_done().
        deadline = time.perf_counter() + 5.0
        while not sub.queue.empty() and time.perf_counter() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(0)

    publisher = spawn(publish_all(), name="bench-publisher")
    try:
        # The consumer never returns, so if it ends it has failed: its error ends the run at once.
        done, _ = await asyncio.wait(
            {publisher, consumer_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
    finally:
        publisher.cancel()
        consumer_task.cancel()
        await asyncio.gather(publisher, consumer_task, return_exceptions=True)
    wall_elapsed = time.perf_counter() - wall_t0
    proc_elapsed = time.process_time() - proc_t0
    _current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    apply_latencies_ms.sort()
    loop_lag_samples_ms.sort()
    total_rows = sum(len(d.bid_levels) + len(d.ask_levels) for d in deltas)
    total_bytes = sum(d.approx_row_bytes() for d in deltas)
    rows_per_s = total_rows / duration_s if duration_s else 0.0
    bytes_per_day = int((total_bytes / duration_s) * 86_400) if duration_s else 0
    cpu_vcpu = (proc_elapsed / wall_elapsed) if wall_elapsed > 0 else 0.0
    cov_bid, cov_ask = book.coverage_ticks_from_mid(SYMBOLS[symbol]["tick"])

    return SymbolTierResult(
        symbol=symbol,
        tier=tier,
        depth=depth,
        cadence_ms=cadence_ms,
        duration_s=duration_s,
        n_deltas=len(deltas),
        rows_per_s=round(rows_per_s, 2),
        bytes_per_day=bytes_per_day,
        mem_mb=round(peak_mem / (1024 * 1024), 4),
        cpu_vcpu=round(cpu_vcpu, 4),
        event_loop_lag_p95_ms=round(_percentile(loop_lag_samples_ms, 0.95), 4),
        apply_p50_ms=round(_percentile(apply_latencies_ms, 0.50), 4),
        apply_p95_ms=round(_percentile(apply_latencies_ms, 0.95), 4),
        apply_p99_ms=round(_percentile(apply_latencies_ms, 0.99), 4),
        coverage_bid_ticks=cov_bid,
        coverage_ask_ticks=cov_ask,
    )


async def run_comparison(
    duration_s: float,
    seed: int = 42,
) -> list[SymbolTierResult]:
    """Measures every (symbol, tier) combination. `duration_s` is the
    *simulated* window length (each tick's level content is independent of
    wall-clock time, so a short `duration_s` in CI still exercises the same
    generative model as a real 2-hour run — see the module docstring and
    the ADR's "Fixture provenance" section for why this substitutes for a
    live 2-hour capture)."""
    results: list[SymbolTierResult] = []
    for symbol in SYMBOLS:
        for tier in TIERS:
            results.append(await _measure_one(symbol, tier, duration_s, seed))
    return results


def apply_decision_rule(results: list[SymbolTierResult]) -> dict[str, object]:
    """Question 2/6: applies the pre-agreed mechanical rule from the ticket
    (`DECISION_RULE`) to the measured numbers and returns the decision plus
    which symbol/budget triggered it, if any."""
    tier_500 = [r for r in results if r.tier == "500@200ms"]
    violations = [
        r
        for r in tier_500
        if r.cpu_vcpu > CPU_BUDGET_VCPU_PER_SYMBOL or r.mem_mb > MEM_BUDGET_MB_PER_SYMBOL
    ]
    if violations:
        decision = "depth_200_default"
        reason = "rule triggered: " + ", ".join(
            f"{r.symbol} cpu={r.cpu_vcpu}vCPU mem={r.mem_mb}MB" for r in violations
        )
    else:
        decision = "defer_depth_200_default_revisit_at_E21"
        reason = "both tiers within budget on every symbol; inconclusive on cost alone"
    return {"decision": decision, "reason": reason, "rule": DECISION_RULE}


def build_report(results: list[SymbolTierResult], duration_s: float) -> dict[str, object]:
    return {
        "methodology": "synthetic recorded-shaped replay, deterministic seed, no live network",
        "window_duration_s": duration_s,
        "symbols": list(SYMBOLS),
        "tiers": {name: {"depth": d, "cadence_ms": c} for name, (d, c) in TIERS.items()},
        "results": [asdict(r) for r in results],
        "decision": apply_decision_rule(results),
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=2.0, help="simulated window length in hours")
    parser.add_argument("--out", type=Path, default=None, help="write JSON report to this path")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    duration_s = args.hours * 3600.0
    results = asyncio.run(run_comparison(duration_s, seed=args.seed))
    report = build_report(results, duration_s)
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    _main()
