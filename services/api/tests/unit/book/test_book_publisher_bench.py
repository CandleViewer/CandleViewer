"""Smoke test for `bench/book_publisher.py` (E21-T01 budgets #5, #6, #8): the harness replays a
short window of the recorded capture end to end and reports every budget. Not the performance
gate itself: the recorded numbers are the PR's, on the reference machine."""

from __future__ import annotations

import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parents[3] / "bench"
sys.path.insert(0, str(BENCH_DIR))

from book_publisher import BUDGET_8_MB, run  # noqa: E402 - the bench directory is no package


async def test_book_publisher_bench_runs_and_reports_every_budget() -> None:
    report = await run(frames=200, symbols=2)
    tl = report.throughput_latency
    assert tl["frames"] == 200 and tl["deltas_applied"] == 199
    assert tl["resyncs"] == tl["bus_overflow_markers"] == tl["publisher_resyncs"] == 0
    assert tl["d_frames"] > 0 and tl["added_ms_p95"] > 0
    assert 0 < report.memory["mb_per_symbol"] < BUDGET_8_MB
    assert set(report.verdict) == {"budget_5", "budget_6", "budget_8"}
    assert report.verdict["budget_5"] and report.verdict["budget_8"]
