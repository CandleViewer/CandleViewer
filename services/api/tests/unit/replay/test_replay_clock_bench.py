"""Smoke test for the E26-T03 harness (`bench/replay_clock.py`) on fake time (C-13.7).

At a small size it asserts that the harness paces every event through the clock, in order and
with none dropped, and reports the achieved ratio. Budgets are not asserted here: E26-Q03 wires
the regression gate against the recorded baseline.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from tests.unit.replay._time import FakeTime


def _load_bench() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "bench" / "replay_clock.py"
    spec = importlib.util.spec_from_file_location("replay_clock_bench", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_bench_paces_every_event_at_100x_in_order() -> None:
    bench = _load_bench()

    report = await bench.run(2_000, 40, 1, speeds=(100.0,), time=FakeTime())

    assert report["events"] == 2_040
    result = report["speed_100"]
    assert (result["dropped_max"], result["out_of_order_max"]) == (0, 0)
    assert result["achieved_ratio_p50"] > 0.99
