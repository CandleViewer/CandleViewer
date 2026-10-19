"""#399 D2-G4: the bars path in the soak lanes at the 32-spec cap, and its gate.

Deterministic: virtual clock, seeded feed, scripted sampler; the stored tail is built from the
recorded golden bars (no network, no live exchange, C-13.5). State blobs go under `tmp_path`."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from bench.ingestion import HARNESS_VERSION, gate
from bench.ingestion import budgets as b
from bench.ingestion.bars_lane import GENERATION, SPECS, BarsFixture, BarsLane
from bench.ingestion.budgets import Verdict
from bench.ingestion.config import load
from bench.ingestion.engine import T0_MS, LaneConfig, ScriptedSampler, run_lanes
from bench.ingestion.runner import _lane_cfg, run_soak
from candleviewer.bars.activity_builders import TickBarBuilder
from candleviewer.bars.leases import CAP_PER_SYMBOL
from candleviewer.bars.limits import MAX_TAIL
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.reader import tail_window_us
from candleviewer.bars.series_store import MAX_HISTORY, Hold, SeriesStore
from candleviewer.bars.state_store import StateStore, StoredState
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent
from tests.unit.bars._set_harness import TOPIC
from tests.unit.bars._trades import trade

MiB = 2**20


def _cfg(root: Path, syms: tuple[str, ...], secs: float, specs: int, per: int) -> LaneConfig:
    """Lanes of `specs` series hydrated with `per` bars each, state blobs under `root`."""
    return LaneConfig(
        syms, secs, sample_every_s=1.0, bars_specs=specs, bars_per_series=per, bars_state_root=root
    )


def _written(root: Path) -> list[str]:
    """The symbols whose state blobs (`<symbol>/<spec_hash>.state.json`) sit under `root`."""
    return sorted(p.parent.name for p in root.glob("*/*.state.json"))


def _raises(spec: BarSpec, when: Callable[[TradeEvent], bool]) -> Callable[..., Any]:
    """`TickBarBuilder.on_trade`, except that `spec`'s builder raises on the trades `when` picks."""
    real = TickBarBuilder.on_trade

    def on_trade(self: TickBarBuilder, t: TradeEvent) -> Sequence[BarUpdate]:
        if self.spec.spec_hash == spec.spec_hash and when(t):
            raise RuntimeError("bench: a builder that raises")
        return real(self, t)

    return on_trade


def test_soak_bars_runs_the_per_symbol_spec_cap_at_the_store_cap_and_soak_steady_none() -> None:
    for profile in ("smoke", "full"):
        cfg = _lane_cfg(load("soak_bars", profile))
        assert (cfg.bars_specs, cfg.bars_per_series) == (CAP_PER_SYMBOL, MAX_HISTORY) == (32, 1000)
        assert _lane_cfg(load("soak_steady", profile)).bars_specs == 0
    assert len({s.spec_hash for s in SPECS}) == len(SPECS) == CAP_PER_SYMBOL
    times = [s for s in SPECS if s.kind == "time"]  # a tail read can hold 1 000 bars of each
    assert all(tail_window_us(s, MAX_TAIL) >= MAX_TAIL * int(s.param_value) * 1000 for s in times)


async def test_a_lane_hydrates_each_series_with_the_stored_tail_through_the_tail_read(
    tmp_path: Path,
) -> None:
    lane = await BarsFixture(2, 50, tmp_path).lane("ETHUSDT", Bus(), lambda: T0_MS * 1000)
    for spec in SPECS[:2]:
        got = lane.store.latest("ETHUSDT", spec.spec_hash, MAX_HISTORY + 1)
        assert got is not None and got.generation == GENERATION
        assert [bar.index for bar in got.closed] == list(range(50))
        assert lane.store.hydrated("ETHUSDT", spec.spec_hash)
    assert lane.set.active("ETHUSDT") == tuple(s.spec_hash for s in SPECS[:2])
    assert lane.count() == (100, 0) and lane.fewest() == 50 and await lane.stop() == (0, ())
    assert _written(tmp_path) == ["ETHUSDT"] * 2  # the blobs went here


async def test_a_lane_at_the_cap_hydrates_every_kind_and_removes_its_temp_dir_on_stop() -> None:
    assert {s.kind for s in SPECS} == {"tick", "time", "volume", "range", "delta"}
    lane = await BarsFixture(CAP_PER_SYMBOL, 20).lane("BTCUSDT", Bus(), lambda: T0_MS * 1000)
    assert lane.count() == (640, 0) and lane.fewest() == 20  # 32 series of 20 bars: none short
    assert lane._tmp is not None  # no state root given: the blobs go to the lane's own temp dir
    root = Path(lane._tmp.name)
    assert _written(root) == ["BTCUSDT"] * CAP_PER_SYMBOL
    assert await lane.stop() == (0, ()) and _written(root) == []


async def test_the_store_stays_at_the_cap_while_the_builders_close_bars_onto_it(
    tmp_path: Path,
) -> None:
    syms = ("BTCUSDT", "SOLUSDT")  # tick:100 and tick:200, full
    res = await run_lanes(_cfg(tmp_path, syms, 4.0, 2, MAX_HISTORY), ScriptedSampler())
    assert res.bars_fewest == [MAX_HISTORY] * 5  # every sample: each series full
    assert res.bars_folded == [3, 3]  # 4 s at 50 prints/s: two tick:100 closes, one tick:200
    assert res.bars_health == []
    checks = b.check_bars(res.bars_fewest, MAX_HISTORY, res.bars_folded, res.bars_health)
    assert all(c.passed for c in checks)
    assert b.check_loss(res.injected, res.ingested, res.detected_gap).passed
    assert sorted(set(_written(tmp_path))) == sorted(syms)  # the blobs went here


async def test_each_sample_records_the_fewest_bars_any_lane_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # one lane has a series a bar short of the cap
    short = {"BTCUSDT": MAX_HISTORY, "SOLUSDT": MAX_HISTORY - 1}
    monkeypatch.setattr(BarsLane, "fewest", lambda self: short[self.symbol])
    cfg = _cfg(tmp_path, ("BTCUSDT", "SOLUSDT"), 2.0, 1, MAX_HISTORY)
    res = await run_lanes(cfg, ScriptedSampler())
    assert res.bars_fewest == [MAX_HISTORY - 1] * 3
    checks = b.check_bars(res.bars_fewest, MAX_HISTORY, res.bars_folded, res.bars_health)
    assert {c.name for c in checks if not c.passed} == {"bars_store_at_cap"}


async def test_the_bar_set_ticks_each_second_of_lane_time_and_rewrites_the_blobs_at_60_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[str] = []
    save = StateStore.save

    async def spy(self: StateStore, stored: StoredState) -> None:
        saved.append(stored.state.spec_hash)
        await save(self, stored)

    monkeypatch.setattr(StateStore, "save", spy)
    res = await run_lanes(_cfg(tmp_path, ("BTCUSDT",), 61.0, 7, 50), ScriptedSampler())
    # 61 s at 50 prints/s: tick:100 to tick:2000 close 30 + 15 + 10 + 6 + 3 + 1 times, the 1m bar
    # (a time series) once, at 40 s; each folds onto its stored tail of 50
    assert res.bars_folded == [66]
    assert (res.bars_fewest[0], res.bars_fewest[-1]) == (50, 51)  # tick:2000 and the 1m: one close
    assert len(saved) == 3 * 7  # each blob: at hydration, at 60 s (the set's tick), at the stop
    checks = b.check_bars(res.bars_fewest, 50, res.bars_folded, res.bars_health)
    assert all(c.passed for c in checks)


@pytest.mark.parametrize(
    ("fewest", "folded", "unhealthy", "failed"),
    [
        ([1000, 1000], [3, 1], [], set()),
        ([1000, 999], [3, 1], [], {"bars_store_at_cap"}),  # a series short of the cap
        ([1000, 1000], [3, 0], [], {"bars_closes_folded"}),  # a lane whose builders closed nothing
        ([1000], [3], ["SOLUSDT: bar_builder_quarantined"], {"bars_builders_healthy"}),
        ([], [], [], {"bars_store_at_cap", "bars_closes_folded"}),
    ],
)
def test_check_bars(
    fewest: list[int], folded: list[int], unhealthy: list[str], failed: set[str]
) -> None:
    checks = b.check_bars(fewest, 1000, folded, unhealthy)
    assert {c.name for c in checks if not c.passed} == failed
    assert all(c.hard and c.budget == "#8" for c in checks)


async def test_a_builder_that_raises_fails_the_run_though_the_store_stays_full_and_folds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tick:200 raises in the first lane only (tick:100 lives on); the last lane stops healthy
    raises = _raises(SPECS[1], lambda t: t.symbol == "BTCUSDT")
    monkeypatch.setattr(TickBarBuilder, "on_trade", raises)
    over: dict[str, Any] = {"symbols": ("BTCUSDT", "SOLUSDT"), "duration_s": 4.0}
    over |= {"sample_every_s": 1.0, "warmup_s": 0.0, "warmup_wall_s": 0.0}
    over |= {"bars_specs": 2, "bars_state_root": tmp_path}
    v = await run_soak(load("soak_bars"), ScriptedSampler(), **over)
    checks = {c.name: c for c in v.checks}
    assert checks["bars_store_at_cap"].passed and checks["bars_closes_folded"].passed
    health = checks["bars_builders_healthy"]  # what the other two cannot see
    assert not health.passed and health.hard and not v.passed
    assert health.note == "BTCUSDT: bar_builder_quarantined"


async def test_a_builder_that_raises_on_the_last_trade_before_the_stop_fails_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = Bus()
    lane = await BarsFixture(2, 50, tmp_path).lane("BTCUSDT", bus, lambda: T0_MS * 1000)
    monkeypatch.setattr(TickBarBuilder, "on_trade", _raises(SPECS[1], lambda _t: True))
    await bus.publish(TOPIC, trade(T0_MS * 1000))  # queued, not applied: the stop's drain does
    assert lane.set.health_reasons() == ()
    _, reasons = await lane.stop()
    assert reasons == ("bar_builder_quarantined",)
    checks = b.check_bars([50], 50, [1], [f"BTCUSDT: {reason}" for reason in reasons])
    assert {c.name for c in checks if not c.passed} == {"bars_builders_healthy"}


async def test_a_lane_whose_hydration_raises_leaves_no_task_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure = SeriesStore.ensure

    async def fails_on_the_second(self: SeriesStore, symbol: str, spec: BarSpec) -> Hold:
        if spec == SPECS[1]:
            raise RuntimeError("bench: ensure raises on the second spec")
        return await ensure(self, symbol, spec)

    monkeypatch.setattr(SeriesStore, "ensure", fails_on_the_second)
    with pytest.raises(RuntimeError, match="ensure raises on the second spec"):
        await BarsFixture(2, 50, tmp_path).lane("ETHUSDT", Bus(), lambda: T0_MS * 1000)
    assert [t for t in asyncio.all_tasks() if t.get_name().startswith("bars-lane-")] == []


@pytest.mark.parametrize("dies", [True, False])
async def test_a_lane_that_fails_to_stop_hides_neither_the_runs_error_nor_the_lanes_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dies: bool
) -> None:
    stopped: list[str] = []
    stop = BarsLane.stop

    async def spy(self: BarsLane) -> tuple[int, tuple[str, ...]]:
        stopped.append(self.symbol)
        done = await stop(self)  # it stops for real; the finally's call is the one that fails
        if stopped.count(self.symbol) == (1 if dies else 2):
            raise OSError(f"bench: {self.symbol} fails to stop")
        return done

    class Dies(ScriptedSampler):
        def sample(self) -> tuple[int, float]:
            if dies and self.n == 6:  # mid-window, with the bars lanes built
                raise RuntimeError("the sampler died")
            return super().sample()

    monkeypatch.setattr(BarsLane, "stop", spy)
    cfg = _cfg(tmp_path, ("BTCUSDT", "SOLUSDT"), 4.0, 2, 50)
    error, shown = (RuntimeError, "the sampler died") if dies else (OSError, "BTCUSDT fails")
    with capture_logs() as logs, pytest.raises(error, match=shown):  # the run's, else the first
        await run_lanes(cfg, Dies())
    assert stopped[-2:] == ["BTCUSDT", "SOLUSDT"]  # both lanes stop at the end, in order
    failed = [e["symbol"] for e in logs if e["event"] == "bars_lane_stop_failed"]
    assert failed == ["BTCUSDT", "SOLUSDT"]  # each failure is logged


async def test_run_soak_gates_the_bars_lane_on_budget_8_beside_the_cap_checks(
    tmp_path: Path,
) -> None:
    over: dict[str, Any] = {"symbols": ("BTCUSDT",), "duration_s": 2.0, "sample_every_s": 1.0}
    over |= {"warmup_s": 0.0, "warmup_wall_s": 0.0, "bars_specs": 1, "bars_state_root": tmp_path}
    # call 0: before the lanes (200 MiB), 1 and 2: around the bars path, 3 on: the window
    v = await run_soak(load("soak_bars"), ScriptedSampler(base=200 * MiB, slope=150 * MiB), **over)
    checks = {c.name: c for c in v.checks}
    assert checks["bars_store_at_cap"].passed and checks["bars_closes_folded"].passed
    assert checks["bars_builders_healthy"].passed
    rss = checks["rss_per_symbol_p95"]  # the window reads 650 ... 950 MiB: 750 MiB added
    assert not rss.passed and rss.hard and rss.measured == pytest.approx(750.0) and not v.passed
    assert v.metrics["bars_setup_mb_per_symbol"]["p95"] == pytest.approx(150.0)


def test_the_gate_holds_the_bars_lane_to_its_committed_baseline() -> None:
    base = gate.load_baseline("soak_bars")
    assert base is not None and base["harness_version"] == HARNESS_VERSION
    assert {"rss_mb_per_symbol", "bars_setup_mb_per_symbol"} <= set(base["metrics"])
    tolerances, profile = load("soak_bars").tolerances, base["machine_profile"]

    def status(scale: float, baseline: dict[str, Any], only: str | None = None) -> str:
        v = Verdict("soak_bars")
        v.metrics = {
            k: {**m, "p95": m["p95"] * (scale if only in (None, k) else 1.0)}
            for k, m in base["metrics"].items()
        }
        return gate.compare(v, baseline, profile, tolerances).status

    armed = {**base, "gate": "gated"}
    assert (status(1.0, armed), status(1.3, armed), status(1.3, base)) == ("PASS", "FAIL", "WARN")
    # a GC spike (#3641) twice the baseline's warns, and fails only past its wide band
    assert (status(2.0, armed, "event_loop_lag_ms"), status(4.0, armed, "event_loop_lag_ms")) == (
        "WARN",
        "FAIL",
    )
