"""E08-Q04 harness self-tests (ticket test plan) + fast default-lane sanity (< 10 s total).

Deterministic: virtual clock, seeded feed, scripted sampler. The leak and the drop are
injected into the real lane engine and must flip the verdict."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bench.ingestion import budgets as b
from bench.ingestion.engine import Lane, LaneConfig, ScriptedSampler, run_lanes, symbols_for
from bench.ingestion.fixture_app import assert_loopback_target
from bench.ingestion.ratelimit import run_headroom
from bench.ingestion.runner import main

SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


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
