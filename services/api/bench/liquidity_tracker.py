"""E21-T04 bench - `LiquidityTracker.on_sample` at book depth 200 (budget #14: <= 2 ms/sample).

Synthetic, seeded book (200 levels a side, random sizes, churn on 20 levels per side per sample,
a print every sample; no network. Run:

    uv run python bench/liquidity_tracker.py [--samples 6000] [--budget-ms 2.0]

Exit status 1 when the p99 exceeds the budget."""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from candleviewer.book.models import BookPhase
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.liquidity import LiquidityTracker

DEPTH = 200
TICK, STEP = Decimal("0.1"), Decimal("0.001")


class _Book:
    def __init__(self, bids: dict[int, Decimal], asks: dict[int, Decimal]) -> None:
        self.bids, self.asks = bids, asks

    def walk(self, *, bids: bool) -> Iterator[tuple[int, Decimal]]:
        return iter(sorted(self.bids.items(), reverse=True) if bids else sorted(self.asks.items()))


def measure(samples: int, seed: int = 7) -> list[float]:
    rng = random.Random(seed)  # noqa: S311 - reproducible synthetic data, not crypto
    mid = 600_000
    bids = {mid - i: Decimal(rng.randint(10, 900)) / 100 for i in range(DEPTH)}
    asks = {mid + 1 + i: Decimal(rng.randint(10, 900)) / 100 for i in range(DEPTH)}
    book, tracker = _Book(bids, asks), LiquidityTracker("BTCUSDT", TICK, STEP)
    out: list[float] = []
    for i in range(samples):
        for side in (book.bids, book.asks):
            for tick in rng.sample(sorted(side), 20):
                side[tick] = Decimal(rng.randint(0, 900)) / 100 or Decimal("0.5")
        ts = i * 100_000
        tracker.on_trade(
            TradeEvent(
                event_id=EventId(uuid.UUID(int=i + 1)),
                ts_event=ts,
                ts_ingest=ts,
                source="live",
                symbol="BTCUSDT",
                trade_id=str(i),
                price=Decimal(mid) * TICK,
                qty=Decimal("0.5"),
                side="buy",
                is_block_trade=False,
                price_ticks=mid,
                notional=Decimal(1),
                seq=i,
            )
        )
        t0 = time.perf_counter_ns()
        tracker.on_sample(ts, BookPhase.LIVE, book)
        out.append((time.perf_counter_ns() - t0) / 1e6)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=6000)
    ap.add_argument("--budget-ms", type=float, default=2.0)
    args = ap.parse_args()
    ms = sorted(measure(args.samples))
    p50, p99 = statistics.median(ms), ms[int(len(ms) * 0.99) - 1]
    print(
        f"on_sample depth={DEPTH} n={len(ms)} p50={p50:.3f} ms p99={p99:.3f} ms max={ms[-1]:.3f} ms"
    )
    return 0 if p99 <= args.budget_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
