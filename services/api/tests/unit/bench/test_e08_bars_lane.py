"""#399 D2-G4: the bars path in the soak lanes at the 32-spec cap, and its gate.

Deterministic: virtual clock, seeded feed, scripted sampler; the stored tail is built from the
recorded golden bars (no network, no live exchange, C-13.5)."""

from __future__ import annotations

from typing import Any

import pytest

from bench.ingestion import HARNESS_VERSION, gate
from bench.ingestion import budgets as b
from bench.ingestion.bars_lane import GENERATION, SPECS, BarsFixture
from bench.ingestion.budgets import Verdict
from bench.ingestion.config import load
from bench.ingestion.engine import T0_MS, LaneConfig, ScriptedSampler, run_lanes
from bench.ingestion.runner import _lane_cfg, run_soak
from candleviewer.bars.leases import CAP_PER_SYMBOL
from candleviewer.bars.limits import MAX_TAIL
from candleviewer.bars.reader import tail_window_us
from candleviewer.bars.series_store import MAX_HISTORY
from candleviewer.bus.bus import Bus

MiB = 2**20


def test_soak_bars_runs_the_per_symbol_spec_cap_at_the_store_cap_and_soak_steady_none() -> None:
    for profile in ("smoke", "full"):
        cfg = _lane_cfg(load("soak_bars", profile))
        assert (cfg.bars_specs, cfg.bars_per_series) == (CAP_PER_SYMBOL, MAX_HISTORY) == (32, 1000)
        assert _lane_cfg(load("soak_steady", profile)).bars_specs == 0
    assert len({s.spec_hash for s in SPECS}) == len(SPECS) == CAP_PER_SYMBOL
    times = [s for s in SPECS if s.kind == "time"]  # a tail read can hold 1 000 bars of each
    assert all(tail_window_us(s, MAX_TAIL) >= MAX_TAIL * int(s.param_value) * 1000 for s in times)


async def test_a_lane_hydrates_each_series_with_the_stored_tail_through_the_tail_read() -> None:
    lane = await BarsFixture(2, 50).lane("ETHUSDT", Bus(), lambda: T0_MS * 1000)
    for spec in SPECS[:2]:
        got = lane.store.latest("ETHUSDT", spec.spec_hash, MAX_HISTORY + 1)
        assert got is not None and got.generation == GENERATION
        assert [bar.index for bar in got.closed] == list(range(50))
        assert lane.store.hydrated("ETHUSDT", spec.spec_hash)
    assert lane.set.active("ETHUSDT") == tuple(s.spec_hash for s in SPECS[:2])
    assert lane.count() == (100, 0) and await lane.stop() == 0


async def test_the_store_stays_at_the_cap_while_the_builders_close_bars_onto_it() -> None:
    syms, cap = ("BTCUSDT", "SOLUSDT"), 2 * MAX_HISTORY  # tick:100 and tick:200, full
    cfg = LaneConfig(syms, 4.0, sample_every_s=1.0, bars_specs=2, bars_per_series=MAX_HISTORY)
    res = await run_lanes(cfg, ScriptedSampler())
    assert res.bars_held == [2 * cap] * 5  # every sample: each series full
    assert res.bars_folded == [3, 3]  # 4 s at 50 prints/s: two tick:100 closes, one tick:200
    assert all(c.passed for c in b.check_bars(res.bars_held, 2, cap, res.bars_folded))
    assert b.check_loss(res.injected, res.ingested, res.detected_gap).passed


@pytest.mark.parametrize(
    ("held", "folded", "failed"),
    [
        ([4000, 4000], [3, 1], set()),
        ([4000, 3999], [3, 1], {"bars_store_at_cap"}),  # a series short of the cap
        ([4000, 4000], [3, 0], {"bars_closes_folded"}),  # a lane whose builders closed nothing
        ([], [], {"bars_store_at_cap", "bars_closes_folded"}),
    ],
)
def test_check_bars(held: list[int], folded: list[int], failed: set[str]) -> None:
    checks = b.check_bars(held, 2, 2000, folded)
    assert {c.name for c in checks if not c.passed} == failed
    assert all(c.hard and c.budget == "#8" for c in checks)


async def test_run_soak_gates_the_bars_lane_on_budget_8_beside_the_cap_checks() -> None:
    over: dict[str, Any] = {"symbols": ("BTCUSDT",), "duration_s": 2.0, "sample_every_s": 1.0}
    over |= {"warmup_s": 0.0, "warmup_wall_s": 0.0, "bars_specs": 1}
    # call 0: before the lanes (200 MiB), 1 and 2: around the bars path, 3 on: the window
    v = await run_soak(load("soak_bars"), ScriptedSampler(base=200 * MiB, slope=150 * MiB), **over)
    checks = {c.name: c for c in v.checks}
    assert checks["bars_store_at_cap"].passed and checks["bars_closes_folded"].passed
    rss = checks["rss_per_symbol_p95"]  # the window reads 650 ... 950 MiB: 750 MiB added
    assert not rss.passed and rss.hard and rss.measured == pytest.approx(750.0) and not v.passed
    assert v.metrics["bars_setup_mb_per_symbol"]["p95"] == pytest.approx(150.0)


def test_the_gate_holds_the_bars_lane_to_its_committed_baseline() -> None:
    base = gate.load_baseline("soak_bars")
    assert base is not None and base["harness_version"] == HARNESS_VERSION
    assert {"rss_mb_per_symbol", "bars_setup_mb_per_symbol"} <= set(base["metrics"])
    tolerances, profile = load("soak_bars").tolerances, base["machine_profile"]

    def status(scale: float, baseline: dict[str, Any]) -> str:
        v = Verdict("soak_bars")
        v.metrics = {k: {**m, "p95": m["p95"] * scale} for k, m in base["metrics"].items()}
        return gate.compare(v, baseline, profile, tolerances).status

    armed = {**base, "gate": "gated"}
    assert (status(1.0, armed), status(1.3, armed), status(1.3, base)) == ("PASS", "FAIL", "WARN")
