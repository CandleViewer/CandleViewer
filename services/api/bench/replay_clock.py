"""E26-T03 benchmark: `ReplayClock` sustained at 100x through the E26-K01 busiest minute.

The E26-T02 harness's dense busiest minute (242 k two-level book-delta rows and 1.2 k trades,
243 200 events over 60 s) runs through `ReplaySource` over an in-memory tier and `ReplayClock`
into a counting sink, on the event loop's real monotonic clock (`LoopTime`). At 100x the minute is
due in 0.6 s from its first event. The report gives wall time, the cold first read (`prime_s`:
the source's read-ahead fill, before the schedule starts), events/s, the achieved speed ratio
(scheduled over wall seconds from the first event; min, p50 and max; none when unbounded), how
many runs booked backpressure, and the dropped and out-of-order event counts, which must both
be 0. It also gives the 1-minute load average at the start, because a loaded machine slows every
figure. Speed -1 measures unbounded throughput. No network. Run:

    uv run python bench/replay_clock.py --runs 5
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from types import ModuleType

from candleviewer.replay import (
    LoopTime,
    MonotonicTime,
    ReplayClock,
    ReplayGap,
    ReplayRequest,
    ReplaySource,
    ReplayTiers,
    StopReason,
)
from candleviewer.storage.repositories.recorded import RecordedEvent, event_from_row
from candleviewer.storage.testing import StaticArchiveCoverage, StaticGapReader


def _t02_harness() -> ModuleType:
    """The E26-T02 harness beside this file: its busiest minute and in-memory tier."""
    path = Path(__file__).with_name("replay_source.py")
    spec = importlib.util.spec_from_file_location("replay_source_bench", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CountingSink:
    def __init__(self, time: MonotonicTime) -> None:
        self.count = self.disorder = 0
        self._last, self._time, self.first_at = -1, time, 0.0

    async def deliver(self, event: RecordedEvent) -> None:
        if not self.count:  # the schedule starts with the first event (after the cold read)
            self.first_at = self._time.now()
        self.disorder += event.ts_us < self._last
        self._last = event.ts_us
        self.count += 1


class _Quiet:
    def on_gap(self, gap: ReplayGap, *, stopped: bool) -> None: ...

    def on_backpressure(self, active: bool) -> None: ...

    def on_stop(self, reason: StopReason, error: Exception | None) -> None: ...


async def _once(
    t02: ModuleType, events: Sequence[RecordedEvent], speed: float, time: MonotonicTime
) -> dict[str, float]:
    tier = t02.SortedTier(events)
    tiers = ReplayTiers(
        hot=tier, cold=tier, coverage=StaticArchiveCoverage(), gaps=StaticGapReader()
    )
    start, end = t02.EPOCH + timedelta(microseconds=t02.H0), t02.H0 + t02.MINUTE
    request = ReplayRequest.model_validate(
        {
            "symbols": ("BTCUSDT",),
            "streams": t02.STREAMS,
            "start": start,
            "end": start + timedelta(microseconds=t02.MINUTE),
            "source_tier": "questdb",
        }
    )
    sink = _CountingSink(time)
    source = ReplaySource(request, tiers)
    clock = ReplayClock(source, sink, _Quiet(), time=time, start_us=t02.H0, end_us=end, speed=speed)
    began = time.now()
    async with clock:
        await clock.play()
        lost = clock.stats().backpressure_s
    done = time.now()
    wall, paced = max(done - began, 1e-9), max(done - sink.first_at, 1e-9)
    return {
        "wall_s": wall,
        "prime_s": sink.first_at - began,
        "events_per_s": sink.count / wall,
        "achieved_ratio": min(1.0, t02.MINUTE / 1e6 / speed / paced) if speed > 0 else -1.0,
        "backpressure_s": lost,
        "dropped": len(events) - sink.count,
        "out_of_order": sink.disorder,
    }


async def run(
    delta_rows: int,
    trades: int,
    runs: int,
    *,
    speeds: Sequence[float] = (100.0, -1.0),
    time: MonotonicTime | None = None,
) -> dict[str, object]:
    t02 = _t02_harness()
    rows = t02.busiest_minute(delta_rows, trades)
    events = [event_from_row(s, r) for s, stream_rows in rows.items() for r in stream_rows]
    report: dict[str, object] = {
        "events": len(events),
        "replay_s": t02.MINUTE / 1e6,
        "load_avg_1m": os.getloadavg()[0],
    }
    for speed in speeds:
        samples = [await _once(t02, events, speed, time or LoopTime()) for _ in range(runs)]
        ratios = sorted(s["achieved_ratio"] for s in samples)
        report[f"speed_{speed:g}"] = {
            **{
                k: statistics.median(s[k] for s in samples)
                for k in ("wall_s", "prime_s", "events_per_s")
            },
            "achieved_ratio": (
                {"min": ratios[0], "p50": statistics.median(ratios), "max": ratios[-1]}
                if speed > 0
                else None
            ),
            "runs_with_backpressure": sum(s["backpressure_s"] > 0 for s in samples),
            "dropped_max": max(s["dropped"] for s in samples),
            "out_of_order_max": max(s["out_of_order"] for s in samples),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--delta-rows", type=int, default=242_000)
    parser.add_argument("--trades", type=int, default=1_200)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.delta_rows, args.trades, args.runs)), indent=2))


if __name__ == "__main__":
    main()
