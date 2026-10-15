"""Unit: E16-T07 `DiskBudget` — growth measured from the sampled series (vs the E16-K01 figure),
the warning before the wall, the hard-limit / pinned-dominant critical event, hysteresis as seen
on the bus, persistence and the supervised task. Fakes only (`_budget_fakes`)."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest

from candleviewer.recorder.budget import (
    US_PER_DAY,
    US_PER_S,
    BudgetConfig,
    DiskBudget,
    Measurement,
    Point,
)
from candleviewer.recorder.models import DiskPressureLevel as L
from tests.unit.recorder._budget_fakes import (
    CAP,
    GB,
    NOW,
    TOTAL,
    Clock,
    FakeBus,
    FakeEvents,
    FakeMeter,
    FakeStore,
    make_budget,
)

HOUR = 3_600 * US_PER_S
_K01 = next(p for p in Path(__file__).resolve().parents if (p / "docs/plan/notes").is_dir())


def _k01_btc_bytes_per_day() -> int:
    """E16-K01 BTCUSDT depth-200 hot GB/day (trades + deltas + snapshots + tickers, ~14.2)."""
    raw = _K01 / "docs/plan/notes/e16-storage-measurement-raw/storage_measure.json"
    rows = json.loads(raw.read_text(encoding="utf-8"))["results"]
    btc = [r for r in rows if r["symbol"] == "BTCUSDT" and r["depth"] in (None, 200)]
    return int(sum(Decimal(str(r["hot_GB_day_reference_rate"])) for r in btc) * GB)


def _week(rate: int) -> tuple[list[Point], tuple[int, int]]:
    """7 days of 60 s samples: diurnal rate (x0.5 .. x1.5), 16 MiB QuestDB page steps, a 3 h
    recorded outage (flat, a `recording_gaps` window) and a 2 h hole (process down)."""
    start, page, written, points = NOW - 7 * US_PER_DAY, 16 * 2**20, 0, []
    outage = (start + 3 * US_PER_DAY, start + 3 * US_PER_DAY + 3 * HOUR)
    for i in range(7 * 1_440):
        t = start + i * 60 * US_PER_S
        if start + 5 * US_PER_DAY <= t < start + 5 * US_PER_DAY + 2 * HOUR:
            continue
        if not outage[0] <= t < outage[1]:
            boost = round(50 * math.sin(2 * math.pi * i / 1_440))
            written += rate * 60 * (100 + boost) // (86_400 * 100)
        size = -(-written // page) * page
        points.append(Point(t, size, (("BTCUSDT", size),)))
    return points, outage


async def test_growth_is_measured_from_the_series_within_20pct_of_k01() -> None:
    k01 = _k01_btc_bytes_per_day()
    points, outage = _week(k01)
    size = points[-1].recorded_bytes
    meter = FakeMeter(used=size, symbols={"BTCUSDT": size})
    budget, _, _ = make_budget(meter, store=FakeStore(points), gaps=[outage])
    await budget.load_series()
    await budget.sample_once()
    report = budget.report()
    assert report is not None
    (btc,) = report.symbols
    for measured in (report.daily_growth_bytes, btc.daily_growth_bytes):
        assert abs(measured - k01) <= k01 // 5, (measured, k01)


async def test_warning_names_the_projected_date_and_actions_six_days_before_the_cap() -> None:
    rate = 600_000 * 86_400  # bytes/day, exact per 600 s point
    used = CAP - 6 * rate
    day = [
        Point(t, used - 600_000 * (NOW - t) // US_PER_S, ())
        for t in range(NOW - US_PER_DAY, NOW, 600 * US_PER_S)
    ]
    budget, events, bus = make_budget(FakeMeter(used=used), store=FakeStore(day))
    await budget.load_series()
    await budget.sample_once()
    ((severity, code, detail),) = events.events
    assert (severity, code) == ("WARNING", "recorder.disk_budget_warning")
    assert detail["projected_full_at"] == "2026-09-27T14:13:20+00:00"  # NOW + 6 days
    assert (detail["trigger"], detail["runway_days"]) == ("projection", "6.0")
    assert set(str(detail["actions"]).split(",")) == {"reduce_depth", "shorten_retention", "unpin"}
    assert [e.level for e in bus.events] == [L.WARN]


async def test_pinned_dominant_consumer_is_named_and_no_path_leaks() -> None:
    symbols = {"BTCUSDT": 280 * GB, "SOLUSDT": 20 * GB, "../../etc": 999 * GB}
    meter = FakeMeter(used=300 * GB, free=TOTAL * 4 // 100, symbols=symbols)
    budget, events, _ = make_budget(meter, pinned=frozenset({"BTCUSDT"}))
    await budget.sample_once()
    ((severity, code, detail),) = events.events
    assert (severity, code, budget.level) == ("CRITICAL", "recorder.disk_halt", L.HALT)
    assert (detail["dominant_symbol"], detail["dominant_symbol_pinned"]) == ("BTCUSDT", "true")
    assert not any(sep in str(v) for v in detail.values() for sep in ("/", "\\"))
    report = budget.report()
    assert report is not None
    assert [(s.symbol, s.pinned) for s in report.symbols] == [("BTCUSDT", True), ("SOLUSDT", False)]


async def test_bus_sees_one_autostop_engagement_while_usage_oscillates_89_91() -> None:
    meter, clock = FakeMeter(), Clock()
    budget, _, bus = make_budget(meter, clock=clock)
    for pct in [89, 91] * 5 + [84, 91]:
        meter.used = CAP * pct // 100
        clock.t += 60 * US_PER_S
        await budget.sample_once()
    assert [e.level for e in bus.events] == [L.WARN, L.AUTOSTOP, L.WARN, L.AUTOSTOP]


async def test_before_history_growth_is_zero_and_nothing_is_projected() -> None:
    budget, events, bus = make_budget(FakeMeter(used=10 * GB, symbols={"BTCUSDT": 10 * GB}))
    assert budget.report() is None and budget.level is L.NORMAL
    await budget.sample_once()
    report = budget.report()
    assert report is not None and (report.daily_growth_bytes, report.projected_full_at) == (0, None)
    assert report.symbols[0].daily_growth_bytes == 0 and not events.events and not bus.events
    with pytest.raises(ValueError, match="0 <= free <= total"):
        Measurement(10, 11, {}, {})


async def test_series_is_thinned_persisted_and_pruned_to_the_window() -> None:
    meter, clock, store = FakeMeter(), Clock(), FakeStore()
    short = BudgetConfig(cap_bytes=CAP, fit_window_s=3_600, fallback_window_s=1_800)
    budget, _, _ = make_budget(meter, clock=clock, store=store, config=short)
    for _ in range(120):
        meter.used += GB // 100
        clock.t += 60 * US_PER_S
        await budget.sample_once()
    ts = [p.ts_us for p in store.appended]
    assert len(ts) == 12 and all(b - a == 600 * US_PER_S for a, b in pairwise(ts))
    report = budget.report()
    assert report is not None and report.daily_growth_bytes == 1_440 * GB // 100


async def test_store_and_bus_failures_never_lose_the_announcement() -> None:
    bus = FakeBus(fail_next=True)
    budget, events, _ = make_budget(
        FakeMeter(used=CAP * 96 // 100), store=FakeStore(broken=True), bus=bus
    )
    await budget.load_series()
    with pytest.raises(OSError, match="bus unavailable"):
        await budget.sample_once()
    await budget.sample_once()
    assert [(e.previous, e.level) for e in bus.events] == [(L.NORMAL, L.HALT)]
    assert len(events.events) == 2  # the alert is at-least-once


async def test_task_survives_a_failed_pass_and_stops_cleanly() -> None:
    meter, passes, done = FakeMeter(used=CAP * 96 // 100, fail=True), [0], asyncio.Event()

    async def sleep(_: float) -> None:
        meter.fail, passes[0] = False, passes[0] + 1
        if passes[0] >= 2:
            done.set()
        await asyncio.sleep(0)

    budget, events, _ = make_budget(meter, sleep=sleep)
    budget.start()
    budget.start()  # idempotent
    await asyncio.wait_for(done.wait(), timeout=5)
    await budget.stop()
    await budget.stop()  # idempotent
    assert budget.level is L.HALT and events.events[0][1] == "recorder.disk_halt"


async def test_hard_limit_alerts_first_then_publishes_halt() -> None:
    meter = FakeMeter(used=CAP * 96 // 100, symbols={"ETHUSDT": 176 * GB, "BTCUSDT": 400 * GB})
    budget, events, bus = make_budget(meter)
    await budget.sample_once()
    assert (budget.level, budget.accelerate_retention) == (L.HALT, True)
    assert [(s, c) for s, c, _ in events.events] == [("CRITICAL", "recorder.disk_halt")]
    assert [(e.previous, e.level, e.cap_bytes) for e in bus.events] == [(L.NORMAL, L.HALT, CAP)]


async def test_gap_and_pin_outages_never_block_the_ladder() -> None:
    answers: list[frozenset[str] | OSError] = [frozenset({"BTCUSDT"}), OSError("pg down")]

    async def pinned() -> frozenset[str]:
        answer = answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    async def gaps(lo: int, hi: int) -> Sequence[tuple[int, int]]:
        raise TimeoutError

    meter, clock, events = FakeMeter(used=GB, symbols={"BTCUSDT": GB}), Clock(), FakeEvents()
    cfg = BudgetConfig(cap_bytes=CAP)
    budget = DiskBudget(
        meter=meter,
        events=events,
        bus=FakeBus(),
        env="demo",
        config=cfg,
        now_us=clock,
        gaps=gaps,
        pinned=pinned,
    )
    await budget.sample_once()
    meter.used, clock.t = CAP * 96 // 100, clock.t + 600 * US_PER_S
    await budget.sample_once()
    assert budget.level is L.HALT
    assert events.events[0][2]["dominant_symbol_pinned"] == "true"  # the last known pins
