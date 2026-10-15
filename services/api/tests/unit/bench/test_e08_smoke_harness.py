"""E08-Q04 PR-lane smoke of each scenario (`harness` marker: > 30 s in total, run by the nightly
and on demand, deselected from the default lane). Each runs the scenario's `smoke` profile through
the same runner + assertion set the full profile uses. The REST smoke asserts the routes serve and
the cache path is faster; the absolute budget #13 verdict is reported, not asserted here, because
cold-tier DuckDB p95 on shared laptops/CI runners is the number this pack exists to measure."""

from __future__ import annotations

import pytest

from bench.ingestion.config import SCENARIOS, load
from bench.ingestion.runner import run_scenario

pytestmark = pytest.mark.harness

_ASSERT_ALL = tuple(s for s in SCENARIOS if s != "rest_k6")


@pytest.mark.parametrize("name", _ASSERT_ALL)
async def test_smoke_scenario_passes_every_hard_check(name: str) -> None:
    v = await run_scenario(load(name, "smoke"))
    failed = [
        f"{c.name}={c.measured:.4g}>{c.limit:.4g}" for c in v.checks if c.hard and not c.passed
    ]
    assert v.passed, failed
    assert v.metrics and all(not k.startswith("_") or k == "_curve" for k in v.metrics)


async def test_smoke_rest_profile_serves_every_route_and_cache_is_faster() -> None:
    v = await run_scenario(load("rest_k6", "smoke"))
    routes = {k for k in v.metrics if k.startswith("rest_")}
    assert routes == {
        "rest_instruments_ms",
        "rest_klines_cold_ms",
        "rest_klines_warm_ms",
        "rest_klines_page_boundary_ms",
        "rest_trades_ms",
        "rest_orderbook_ms",
        "rest_data_coverage_ms",
    }
    speed = next(c for c in v.checks if c.name == "klines_cache_speedup")
    assert speed.passed, speed.note
    assert all(c.budget == "#13" for c in v.checks)
