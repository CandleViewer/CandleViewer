"""Smoke test for `bench/book_depth_compare.py` (E08-K01 spike harness).

Not a CI performance gate -- the M7 `book` module remains an empty scaffold
(see `pyproject.toml` coverage `omit` list) and this ticket explicitly does
not implement it. This only asserts the harness runs end-to-end on a short
simulated window and returns well-formed, non-estimated measurements for
every (symbol, tier) pair, and that the mechanical decision rule is applied
consistently -- the same shape asserted by the bus's own
`test_bus_throughput_bench.py` smoke test.
"""

from __future__ import annotations

import asyncio
import sys
import tracemalloc
from pathlib import Path

import pytest

BENCH_DIR = Path(__file__).resolve().parents[3] / "bench"
sys.path.insert(0, str(BENCH_DIR))

from book_depth_compare import (  # noqa: E402
    SYMBOLS,
    TIERS,
    BookState,
    SymbolTierResult,
    SyntheticDelta,
    _measure_one,
    apply_decision_rule,
    build_report,
    run_comparison,
)


@pytest.mark.asyncio
async def test_run_comparison_covers_every_symbol_and_tier() -> None:
    results = await run_comparison(duration_s=0.6, seed=7)

    assert len(results) == len(SYMBOLS) * len(TIERS)
    seen = {(r.symbol, r.tier) for r in results}
    assert seen == {(s, t) for s in SYMBOLS for t in TIERS}


@pytest.mark.asyncio
async def test_every_result_is_measured_not_estimated() -> None:
    results = await run_comparison(duration_s=0.6, seed=7)

    for r in results:
        assert isinstance(r, SymbolTierResult)
        assert r.estimated is False
        assert r.n_deltas > 0
        assert r.rows_per_s >= 0.0
        assert r.bytes_per_day >= 0
        assert r.mem_mb >= 0.0
        assert r.apply_p50_ms <= r.apply_p95_ms <= r.apply_p99_ms


@pytest.mark.asyncio
async def test_tier_500_covers_more_price_depth_than_tier_200() -> None:
    """Question 5 (heatmap depth coverage): a deeper depth request must
    populate more ticks from mid than a shallower one, in aggregate across
    symbols, on this generative model. A long-enough window is used so a
    single noisy side/symbol combination cannot flip the comparison (the
    ADR itself is backed by the 2-hour run, not this smoke duration)."""
    results = await run_comparison(duration_s=10.0, seed=7)
    by_key = {(r.symbol, r.tier): r for r in results}

    shallow_total = sum(
        by_key[(s, "200@100ms")].coverage_bid_ticks + by_key[(s, "200@100ms")].coverage_ask_ticks
        for s in SYMBOLS
    )
    deep_total = sum(
        by_key[(s, "500@200ms")].coverage_bid_ticks + by_key[(s, "500@200ms")].coverage_ask_ticks
        for s in SYMBOLS
    )
    assert deep_total >= shallow_total


@pytest.mark.asyncio
async def test_decision_rule_is_deterministic_given_the_same_inputs() -> None:
    results = await run_comparison(duration_s=0.6, seed=11)

    decision_a = apply_decision_rule(results)
    decision_b = apply_decision_rule(results)

    assert decision_a == decision_b
    assert decision_a["decision"] in {
        "depth_200_default",
        "defer_depth_200_default_revisit_at_E21",
    }
    assert "rule" in decision_a


@pytest.mark.asyncio
async def test_build_report_is_json_serialisable_and_complete() -> None:
    import json

    results = await run_comparison(duration_s=0.6, seed=3)
    report = build_report(results, duration_s=0.6)

    text = json.dumps(report)
    assert json.loads(text) == report
    assert report["symbols"] == list(SYMBOLS)
    assert set(report["tiers"]) == set(TIERS)
    assert len(report["results"]) == len(results)


async def test_a_consumer_that_dies_ends_the_measurement_with_its_error_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consumer stopped, yet the measurement went on publishing, then waited out a 5 s drain
    deadline that nothing could meet, and only then raised its error."""

    def dies(self: BookState, delta: SyntheticDelta) -> None:
        raise RuntimeError("apply died")

    monkeypatch.setattr(BookState, "apply", dies)
    run = asyncio.ensure_future(_measure_one("BTCUSDT", "200@100ms", 0.6, 7))
    for _ in range(100):  # event-loop turns: no time passes
        await asyncio.sleep(0)
    ended = run.done()
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    tracemalloc.stop()  # the measurement ends without reaching its own stop()
    assert ended
    with pytest.raises(RuntimeError, match="apply died"):
        run.result()
