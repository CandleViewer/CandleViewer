"""Smoke test for the E26-T02 throughput harness (`bench/replay_source.py`).

It asserts that the harness replays every event through both tiers and reports positive rates
at a small size. Budgets are not asserted here: E26-Q03 wires the regression gate against the
recorded baseline.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_bench() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "bench" / "replay_source.py"
    spec = importlib.util.spec_from_file_location("replay_source_bench", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_bench_replays_every_event_through_both_tiers(tmp_path: Path) -> None:
    bench = _load_bench()

    report = await bench.run(2_000, 40, 1, tmp_path)

    assert report["events"] == 2_040
    rates = report["events_per_s_p50"]
    assert rates["in_memory"] > 0
    assert rates["cold_parquet"] > 0
