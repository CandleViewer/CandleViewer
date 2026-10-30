"""E21-T04 bench - `LiquidityTracker.on_sample` at book depth 200 (budget #14: <= 2 ms/sample).

Synthetic, seeded book (200 levels a side, random sizes, churn on 20 levels per side per sample,
a print every sample; no network. Run:

    uv run python bench/liquidity_tracker.py [--samples 6000] [--budget-ms 2.0]

Three cases, all gated on the p99: the steady book above, a burst (about 5 000 prints in the
5 s window, 40 levels dropping in one sample), and the wired path (PR 2): the same steady book as
the heatmap's instantaneous float levels through `LiquidityEngine.on_deadline` (quantise to
`qty_step`, sample, the event cap, the outbound queue, the metrics), on the 100 ms grid. The
timed call includes the `islice` list copies of both sides (up to `max_levels` each) that
`on_sample` allocates, and this file's fake book sorts its levels inside `walk`, which the real
`BookState.walk` does not.

Exit status 1 when any p99 exceeds the budget."""

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
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from candleviewer.book.models import BookPhase
from candleviewer.bus import Bus
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.heatmap import Sampler
from candleviewer.orderflow.liquidity import LiquidityTracker
from candleviewer.orderflow.liquidity_engine import LiquidityEngine

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


def _print(i: int, ts: int, tick: int, side: Literal["buy", "sell"]) -> TradeEvent:
    return TradeEvent(
        event_id=EventId(uuid.UUID(int=i + 1)),
        ts_event=ts,
        ts_ingest=ts,
        source="live",
        symbol="BTCUSDT",
        trade_id=f"b{i}",
        price=Decimal(tick) * TICK,
        qty=Decimal("0.5"),
        side=side,
        is_block_trade=False,
        price_ticks=tick,
        notional=Decimal(1),
        seq=i,
    )


def measure_burst(rounds: int = 300, seed: int = 11) -> list[float]:
    """Steady ~5 000 prints in the window; every other sample 40 levels halve at once."""
    rng = random.Random(seed)  # noqa: S311 - reproducible synthetic data, not crypto
    mid = 600_000
    sizes = [Decimal(rng.randint(100, 900)) / 100 for _ in range(DEPTH)]
    full = _Book(
        {mid - i: sizes[i] for i in range(DEPTH)}, {mid + 1 + i: sizes[i] for i in range(DEPTH)}
    )
    halved = _Book(dict(full.bids), dict(full.asks))
    for i in range(20):  # 20 bid + 20 ask levels drop by exactly 50 %
        halved.bids[mid - i * 3] = sizes[i * 3] / 2
        halved.asks[mid + 1 + i * 3] = sizes[i * 3] / 2
    tracker, n, out = LiquidityTracker("BTCUSDT", TICK, STEP), 0, []
    for r in range(rounds):
        for i in range(200):  # 1 000 prints/s for 5 s keeps ~5 000 in the window
            ts = r * 200_000 + i * 1_000
            n += 1
            tracker.on_trade(
                _print(n, ts, mid + rng.randint(-100, 100), rng.choice(("buy", "sell")))
            )
        for k, book in enumerate((halved, full)):
            ts = r * 200_000 + 100_000 * k
            t0 = time.perf_counter_ns()
            tracker.on_sample(ts, BookPhase.LIVE, book)
            out.append((time.perf_counter_ns() - t0) / 1e6)
    return out[60:]  # the first 30 rounds fill the window


class _Pins:
    def set_sampler(self, sampler: Sampler | None) -> None: ...
    def pin_native(self, symbol: str, depth: int) -> None: ...
    def unpin_native(self, symbol: str) -> None: ...


class _Levels:
    def __init__(self, bids: dict[int, float], asks: dict[int, float]) -> None:
        self.bids, self.asks = bids, asks


def measure_wired(samples: int, seed: int = 7) -> list[float]:
    """`on_deadline` with float levels (best first, as the heatmap reads them), 20 levels a side
    churned and one print a sample; the timed call is the whole wired sample."""
    rng = random.Random(seed)  # noqa: S311 - reproducible synthetic data, not crypto
    mid, t0 = 600_000, 1_700_000_000_000
    bids = {mid - i: rng.randint(10, 900) / 100 for i in range(DEPTH)}
    asks = {mid + 1 + i: rng.randint(10, 900) / 100 for i in range(DEPTH)}
    engine = LiquidityEngine(
        Bus(), "live", pins=_Pins(), steps=lambda s: (TICK, STEP), symbols=("BTCUSDT",)
    )
    out: list[float] = []
    for i in range(samples):
        for side in (bids, asks):
            for tick in rng.sample(sorted(side), 20):
                side[tick] = rng.randint(0, 900) / 100 or 0.5
        t_ms = t0 + i * 100
        engine._offer(_print(i, t_ms * 1000, mid, "buy"))
        levels = _Levels(dict(bids), dict(asks))
        t1 = time.perf_counter_ns()
        engine.on_deadline("BTCUSDT", t_ms, levels)
        out.append((time.perf_counter_ns() - t1) / 1e6)
    return out


def _report(name: str, ms: list[float]) -> float:
    ms = sorted(ms)
    p50, p99 = statistics.median(ms), ms[int(len(ms) * 0.99) - 1]
    print(f"{name} depth={DEPTH} n={len(ms)} p50={p50:.3f} ms p99={p99:.3f} ms max={ms[-1]:.3f} ms")
    return p99


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=6000)
    ap.add_argument("--budget-ms", type=float, default=2.0)
    args = ap.parse_args()
    steady = _report("on_sample", measure(args.samples))
    burst = _report("on_sample burst(5000 prints, 40 drops)", measure_burst())
    wired = _report("on_deadline wired(quantise+sample+emit)", measure_wired(args.samples))
    return 0 if max(steady, burst, wired) <= args.budget_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
