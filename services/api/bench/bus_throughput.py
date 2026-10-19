"""Benchmark harness for the M5 bus (E08-T03).

Reports publish->deliver p50/p95/p99 latency at 5,000 and 50,000 events/s
with a configurable subscriber count. Run directly:

    uv run python bench/bus_throughput.py

Or via pytest as a smoke check (`tests/unit/bus/test_bus_throughput_bench.py`)
that the harness runs and produces sane output; the perf budget itself
(§ Performance notes: p99 <=1ms @ 50k events/s, 8 subscribers) is asserted
against a regression baseline in CI, not an absolute number in this file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.observability import spawn


@dataclass(frozen=True)
class BenchResult:
    events_per_s: int
    subscribers: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    delivered: int


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * pct))
    return sorted_values[idx]


async def _run_once(events_per_s: int, n_subscribers: int, duration_s: float = 1.0) -> BenchResult:
    bus = Bus()
    subs = [
        bus.subscribe(f"sub-{i}", "demo.md.BTCUSDT.trade", QueuePolicy.NEVER_DROP)
        for i in range(n_subscribers)
    ]

    latencies: list[float] = []
    topic = Topic(env="demo", domain="md", symbol="BTCUSDT", detail="trade")
    n_events = int(events_per_s * duration_s)
    interval = 1.0 / events_per_s if events_per_s else 0.0

    async def consume(sub: object) -> None:
        while True:
            await sub.get()  # type: ignore[attr-defined]

    consumer_tasks = [spawn(consume(s), name="bench-consume") for s in subs]

    async def publish_all() -> None:
        for _ in range(n_events):
            t0 = time.perf_counter()
            await bus.publish(topic, {"ts": t0})
            latencies.append((time.perf_counter() - t0) * 1000)
            if interval:
                await asyncio.sleep(0)
        await asyncio.sleep(0.05)

    publisher = spawn(publish_all(), name="bench-publish")
    try:
        # A consumer never returns, so one that ends has failed: its error ends the run at once.
        done, _ = await asyncio.wait(
            {publisher, *consumer_tasks}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
    finally:
        for t in (publisher, *consumer_tasks):
            t.cancel()
        await asyncio.gather(publisher, *consumer_tasks, return_exceptions=True)

    latencies.sort()
    return BenchResult(
        events_per_s=events_per_s,
        subscribers=n_subscribers,
        p50_ms=_percentile(latencies, 0.50),
        p95_ms=_percentile(latencies, 0.95),
        p99_ms=_percentile(latencies, 0.99),
        delivered=len(latencies),
    )


async def run_bench(subscribers: int = 8) -> list[BenchResult]:
    results = []
    for rate in (5_000, 50_000):
        results.append(await _run_once(rate, subscribers))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscribers", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = asyncio.run(run_bench(args.subscribers))
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        for r in results:
            print(
                f"{r.events_per_s:>7} ev/s x{r.subscribers} subs: "
                f"p50={r.p50_ms:.4f}ms p95={r.p95_ms:.4f}ms p99={r.p99_ms:.4f}ms "
                f"delivered={r.delivered}"
            )


if __name__ == "__main__":
    main()
