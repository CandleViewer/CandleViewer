"""Smoke test for the `bench/bus_throughput.py` harness (E08-T03 DoD:
"Benchmark recorded in the PR with before/after numbers"). This does not
assert an absolute latency budget — the CI regression gate compares against
the `main` baseline separately — it only asserts the harness runs, delivers
every published event, and returns well-formed percentile results at a
small event count so the suite stays fast."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from candleviewer.bus.bus import Subscription

BENCH_DIR = Path(__file__).resolve().parents[3] / "bench"
sys.path.insert(0, str(BENCH_DIR))

from bus_throughput import BenchResult, _run_once  # noqa: E402


@pytest.mark.asyncio
async def test_bus_throughput_bench_runs_and_delivers_every_event() -> None:
    result = await _run_once(events_per_s=200, n_subscribers=2, duration_s=0.05)

    assert isinstance(result, BenchResult)
    assert result.delivered == 10
    assert result.p50_ms <= result.p95_ms <= result.p99_ms


async def test_a_subscriber_that_dies_ends_the_run_with_its_error_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead subscriber stops draining its queue, so 10 000 events would block the publisher
    on the 4 096th and the run would hang, its error unread, while the others keep waiting."""

    async def dies(self: Subscription) -> None:
        raise RuntimeError("subscriber died")

    monkeypatch.setattr(Subscription, "get", dies)
    run = asyncio.ensure_future(_run_once(events_per_s=10_000, n_subscribers=2, duration_s=1.0))
    for _ in range(100):  # event-loop turns: no time passes
        await asyncio.sleep(0)
    ended = run.done()
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    assert ended
    with pytest.raises(RuntimeError, match="subscriber died"):
        run.result()
