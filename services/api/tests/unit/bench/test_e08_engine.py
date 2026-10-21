"""E08-Q04 harness self-tests (ticket test plan) + fast default-lane sanity (< 10 s total).

Deterministic: virtual clock, seeded feed, scripted sampler. The leak and the drop are
injected into the real lane engine and must flip the verdict."""

from __future__ import annotations

import asyncio
import gc
import itertools
from pathlib import Path
from typing import Any

import pytest

import bench.ingestion.engine as engine
from bench.ingestion import budgets as b
from bench.ingestion.config import load
from bench.ingestion.engine import Lane, LaneConfig, ScriptedSampler, run_lanes, symbols_for
from bench.ingestion.fixture_app import assert_loopback_target
from bench.ingestion.ratelimit import run_headroom
from bench.ingestion.runner import _lane_cfg, main, run_soak
from bench.ingestion_soak import SyntheticMarket

SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
MiB = 2**20


def _cfg(**kw: Any) -> LaneConfig:
    base: dict[str, Any] = {"symbols": SYMS, "duration_s": 6.0, "sample_every_s": 1.0}
    return LaneConfig(**{**base, **kw})


async def test_clean_run_balances_injected_and_ingested() -> None:
    res = await run_lanes(_cfg(), ScriptedSampler())
    assert sum(res.injected.values()) > 0
    assert b.check_loss(res.injected, res.ingested, res.detected_gap).passed


async def test_injected_undetected_drop_fails_the_loss_assertion() -> None:
    res = await run_lanes(_cfg(drop_every=3, drop_symbol="ETHUSDT"), ScriptedSampler())
    c = b.check_loss(res.injected, res.ingested, res.detected_gap)
    assert not c.passed and "ETHUSDT" in c.note and "BTCUSDT" not in c.note


async def test_detected_and_reported_gap_is_not_a_loss() -> None:
    res = await run_lanes(_cfg(drop_every=3, drop_detected=True), ScriptedSampler())
    assert sum(res.detected_gap.values()) > 0
    assert b.check_loss(res.injected, res.ingested, res.detected_gap).passed


async def test_injected_leak_fails_memory_flatness() -> None:
    lanes: list[Lane] = []
    sampler = ScriptedSampler(
        retained=lambda: sum(len(x.retained) for x in lanes), bytes_per_event=65536
    )
    res = await run_lanes(_cfg(leak=True), sampler, bind=lanes.extend)
    assert res.retained > 0
    assert b.flatness(res.samples, 1.0)[0] > 0.05
    clean = await run_lanes(_cfg(), ScriptedSampler())
    assert b.flatness(clean.samples, 1.0)[0] == 0.0


async def test_pre_lanes_rss_is_sampled_before_the_market_and_lanes_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    class RecordingMarket(SyntheticMarket):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            order.append("market")
            super().__init__(*args, **kwargs)

    class Spy:
        def sample(self) -> tuple[int, float]:
            order.append("sample")
            return (100 + order.count("sample")) * MiB, 0.0

    monkeypatch.setattr(engine, "SyntheticMarket", RecordingMarket)
    res = await run_lanes(
        _cfg(duration_s=1.0), Spy(), bind=lambda ls: order.append(f"lanes:{len(ls)}")
    )
    assert order[:3] == ["sample", "market", f"lanes:{len(SYMS)}"]  # the book state is in #8 too
    assert set(order[3:]) == {"sample"}
    assert res.rss_pre_lanes_bytes == 101 * MiB and res.samples[0].rss_bytes == 102 * MiB


async def test_default_config_has_no_warmup_and_samples_the_whole_run() -> None:
    cfg = _cfg(duration_s=1.0)
    assert (cfg.warmup_s, cfg.warmup_wall_s) == (0.0, 0.0)
    res = await run_lanes(cfg, ScriptedSampler())
    assert [s.t_s for s in res.samples] == [0.0, 1.0]
    assert sum(res.injected.values()) == len(SYMS) * 50 * 1  # exactly duration_s of feed


async def test_warmup_runs_the_lanes_unsampled_and_the_sampled_window_follows() -> None:
    cfg = _cfg(duration_s=2.0, warmup_s=3.0)
    res = await run_lanes(cfg, ScriptedSampler())
    assert [s.t_s for s in res.samples] == [0.0, 1.0, 2.0]  # sample times count from the window
    assert sum(res.injected.values()) == len(SYMS) * 50 * 5  # the 3 s warm-up was fed as well
    assert b.check_loss(res.injected, res.ingested, res.detected_gap).passed
    cold = await run_lanes(_cfg(duration_s=2.0), ScriptedSampler())  # same rate over the window
    rate, cold_rate = (b.storage_gb_per_day_per_symbol(r.samples, 3) for r in (res, cold))
    assert rate == pytest.approx(cold_rate)


def _bounded_fill(lanes: list[Lane], cap: int) -> ScriptedSampler:
    """RSS grows with the prints ingested up to `cap`, then holds: a bounded buffer filling."""

    def fill() -> int:
        return min(sum(x.ingested for x in lanes), cap)

    return ScriptedSampler(retained=fill, bytes_per_event=65536)


async def test_warmup_keeps_a_filling_buffer_out_of_flatness_but_not_a_leak() -> None:
    lanes: list[Lane] = []
    cap = 600  # fills during the first 4 s (3 symbols x 50 prints/s), then holds
    cold = await run_lanes(_cfg(), _bounded_fill(lanes, cap), bind=lanes.extend)
    assert b.flatness(cold.samples, 1.0)[0] > 0.05  # the base sample sits inside the fill
    lanes.clear()
    warm = await run_lanes(_cfg(warmup_s=5.0), _bounded_fill(lanes, cap), bind=lanes.extend)
    assert b.flatness(warm.samples, 1.0)[0] == 0.0  # the fill is over before the first sample
    lanes.clear()
    leak = ScriptedSampler(
        retained=lambda: sum(len(x.retained) for x in lanes), bytes_per_event=65536
    )
    leaking = await run_lanes(_cfg(leak=True, warmup_s=2.0), leak, bind=lanes.extend)
    assert leaking.retained > 0 and b.flatness(leaking.samples, 1.0)[0] > 0.05


async def test_warmup_wall_floor_keeps_the_lanes_running_until_it_has_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = itertools.count()

    class Clock:  # a stub wall clock: every read advances it 10 ms, so no real time passes
        @staticmethod
        def perf_counter() -> float:
            return next(reads) / 100

    stamps: list[float] = []

    class Spy(ScriptedSampler):
        def sample(self) -> tuple[int, float]:
            stamps.append(Clock.perf_counter())  # when each sample was taken, on the stub clock
            return super().sample()

    monkeypatch.setattr(engine, "time", Clock)
    res = await run_lanes(_cfg(duration_s=1.0, warmup_wall_s=2.0), Spy())
    assert stamps[1] - stamps[0] >= 2.0  # the first sample of the window came after the floor
    assert sum(res.injected.values()) > len(SYMS) * 50 * 1  # more was fed than the 1 s window


async def test_warmup_with_load_windows_is_refused() -> None:
    loads = (("BTCUSDT", 1.0, 2.0, 3),)
    with pytest.raises(ValueError, match="load windows"):
        await run_lanes(_cfg(warmup_s=1.0, loads=loads), ScriptedSampler())


async def test_burst_backpressures_and_recovers_without_cross_symbol_impact() -> None:
    cfg = _cfg(duration_s=14.0, loads=(("BTCUSDT", 2.0, 10.0, 5),))
    res = await run_lanes(cfg, ScriptedSampler(), drain_ticks=300)
    assert res.backpressure["BTCUSDT"] > 0 and res.backpressure["ETHUSDT"] == 0
    assert res.recovery_s["BTCUSDT"] is not None and res.max_backlog["ETHUSDT"] == 0
    assert b.check_loss(res.injected, res.ingested, res.detected_gap).passed


async def test_stage_latency_recorded_per_trade_frame() -> None:
    res = await run_lanes(_cfg(duration_s=2.0), ScriptedSampler(), record_stages=True)
    assert res.stage_ms and all(
        x >= 0 for x in res.stage_ms
    )  # budget is asserted in the harness lane


async def test_headroom_steady_passes_and_overload_hits_zero() -> None:
    ok = await run_headroom(
        duration_s=30,
        refresh_every_s=60,
        backfill_pages_per_s=1,
        symbols=3,
        bucket_capacity=10,
        bucket_refill_per_s=5,
    )
    assert all(
        c.passed for c in b.check_headroom(ok.min_uid_tokens, ok.ip_holds, ok.ip_limit_errors)
    )
    bad = await run_headroom(
        duration_s=10,
        refresh_every_s=60,
        backfill_pages_per_s=3,
        symbols=3,
        bucket_capacity=10,
        bucket_refill_per_s=5,
    )
    assert bad.would_block > 0 and not b.check_headroom(bad.min_uid_tokens, 0, 0)[0].passed


async def test_provoked_ip_limit_is_counted_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    import bench.ingestion.ratelimit as rl

    monkeypatch.setattr(rl, "IP_WINDOW_MAX", 5)  # the venue window is exceeded within seconds
    res = await run_headroom(
        duration_s=5, refresh_every_s=60, backfill_pages_per_s=3, symbols=1,
        bucket_capacity=100, bucket_refill_per_s=100,
    )  # fmt: skip
    assert res.ip_limit_errors > 0 and res.ip_limit_rejections > 0
    assert not b.check_headroom(res.min_uid_tokens, res.ip_holds, res.ip_limit_errors)[1].passed


def test_symbols_padding_is_deterministic() -> None:
    assert symbols_for(4, SYMS) == (*SYMS, "SYN00USDT")


@pytest.mark.parametrize(
    "url", ["https://api.bybit.com", "http://stream.bytick.com:80", "http://10.0.0.5:8000"]
)
def test_loopback_guard_refuses_exchange_and_remote_targets(url: str) -> None:
    with pytest.raises(RuntimeError):
        assert_loopback_target(url)


def test_loopback_guard_accepts_local() -> None:
    assert_loopback_target("http://127.0.0.1:8123")


def test_cli_ratelimit_smoke_writes_report(tmp_path: Path) -> None:
    assert main(["ratelimit_headroom", "--out-dir", str(tmp_path)]) == 0
    md = next(tmp_path.glob("e08-smoke-*.md")).read_text(encoding="utf-8")
    assert "ratelimit_headroom" in md and "provoked_ip_limit" in md


async def test_run_soak_reports_lane_growth_per_symbol_and_the_footprint_apart() -> None:
    sampler = ScriptedSampler(base=200 * MiB, slope=3 * MiB)  # call n reads (200 + 3n) MiB
    over = {"duration_s": 4.0, "sample_every_s": 1.0, "warmup_s": 0.0, "warmup_wall_s": 0.0}
    v = await run_soak(load("soak_steady"), sampler, **over)
    # call 0 is the pre-lanes sample (200 MiB); the window's five samples read 203 ... 215 MiB
    assert v.metrics["rss_mb_per_symbol"]["max"] == pytest.approx(5.0)
    assert v.metrics["rss_mb_process"]["max"] == pytest.approx(215.0)
    rss = next(c for c in v.checks if c.name == "rss_per_symbol_p95")
    assert rss.measured == pytest.approx(5.0) and rss.budget == "#8" and rss.limit == 300.0


async def test_run_soak_takes_the_flatness_base_from_the_window_not_the_warmup() -> None:
    over = {"symbols": SYMS[:1], "duration_s": 30.0, "warmup_s": 30.0, "warmup_wall_s": 0.0}
    v = await run_soak(load("soak_steady"), ScriptedSampler(), sample_every_s=1.0, **over)
    flat = next(c for c in v.checks if c.name == "memory_flatness")
    # 1/12 of the 30 s window is 2.5 s: the base is the t=3 s sample (over window + warm-up: t=5 s)
    assert "t=3s baseline" in flat.note


async def test_run_soak_reports_a_forced_full_collection_first_and_leaves_no_gc_callback() -> None:
    """#3641: every soak report carries a timed `gc.collect(2)` of the warm heap, labelled the
    forced worst case, beside the natural full collections (often none on a short run)."""
    before, enabled = gc.callbacks[:], gc.isenabled()
    over = {"duration_s": 2.0, "sample_every_s": 1.0, "warmup_s": 0.0, "warmup_wall_s": 0.0}
    gc.disable()  # no natural collection, so the forced one is the run's only full collection
    try:
        v = await run_soak(load("soak_steady"), ScriptedSampler(), **over)
    finally:
        if enabled:
            gc.enable()
    forced = v.metrics["gc_full_pause_ms (forced, worst case)"]
    assert forced["count"] == 1 and forced["max"] > 0
    assert v.metrics["gc_full_pause_ms (natural)"]["count"] == 0  # the forced one is apart
    assert v.metrics["gc_blocks_in_use"]["max"] > 10_000
    assert gc.callbacks == before  # the run's timer left with it


class _Dies(ScriptedSampler):
    """A sampler that fails at its third reading, inside the sampled window."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__()
        self.exc = exc

    def sample(self) -> tuple[int, float]:
        if self.n >= 2:
            raise self.exc
        return super().sample()


@pytest.mark.parametrize(
    "exc", [RuntimeError("sampler died"), asyncio.CancelledError()], ids=["raises", "cancelled"]
)
async def test_run_lanes_takes_its_gc_timer_out_when_the_run_dies(exc: BaseException) -> None:
    before = gc.callbacks[:]
    with pytest.raises(type(exc)):
        await run_lanes(_cfg(), _Dies(exc))
    assert gc.callbacks == before


def test_bench_gc_timer_keeps_full_collections_only() -> None:
    natural: list[float] = []
    timer = engine._gc_timer(natural)
    for generation in (0, 1, 2):
        timer("start", {"generation": generation})
        timer("stop", {"generation": generation, "collected": 0, "uncollectable": 0})
    assert len(natural) == 1 and natural[0] >= 0  # the young ones are not "full pause" rows


def test_soak_smoke_declares_a_warmup_and_the_full_profile_keeps_its_hour_2_base() -> None:
    smoke, full = _lane_cfg(load("soak_steady", "smoke")), _lane_cfg(load("soak_steady", "full"))
    assert smoke.warmup_s >= 100.0, (
        "the dedupe set first resizes at about 4,915 ids, about 98 s at 50 prints a second: "
        "a shorter warm-up leaves that step inside the flatness window"
    )
    assert smoke.warmup_wall_s >= 2.0
    assert (full.warmup_s, full.warmup_wall_s) == (0.0, 0.0)
    assert load("soak_steady", "full").p("flatness_baseline_fraction") == 0.0833  # hour 2 of 24


async def test_smoke_warmup_outlasts_the_recent_trades_buffer_fill() -> None:
    """`TradeStream` keeps a bounded buffer of recent prints per symbol; the declared warm-up must
    fill it, or the fill lands inside the flatness window again."""
    cfg = _lane_cfg(
        load("soak_steady", "smoke"),
        symbols=SYMS[:1],
        duration_s=2.0,
        sample_every_s=1.0,
        warmup_wall_s=0.0,
    )
    lanes: list[Lane] = []
    filled: list[int] = []

    class Spy:
        def sample(self) -> tuple[int, float]:
            filled.append(len(lanes[0].stream.recent(SYMS[0])) if lanes else -1)
            return 100 * MiB, 0.0

    await run_lanes(cfg, Spy(), bind=lanes.extend)
    assert filled[0] == -1 and filled[1] > 0
    assert len(set(filled[1:])) == 1  # full at the first sample, and still the same size after
