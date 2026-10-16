"""Unit: E16-T07 wiring (#491): meter, series store, sources, the real-backend builder with the
SR-096 shared-volume refusal, and `CV_DISK_*` settings (E16-FR-11). I/O only under tmp_path."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from candleviewer import budget_wiring
from candleviewer.budget_wiring import (
    HOT_STREAMS,
    FileSeriesStore,
    VolumeMeter,
    _OneThread,
    build_disk_budget,
    parquet_usage,
    pinned_symbols,
    recorded_gaps,
    recording_refusal,
    written_by_symbol,
)
from candleviewer.recorder.budget import US_PER_DAY, BudgetConfig, DiskBudget, Point
from candleviewer.recorder.metrics import recorder_bytes_written_total
from candleviewer.recorder.models import DiskPressureLevel
from candleviewer.settings import Settings
from tests.unit.recorder._budget_fakes import CAP, NOW, Clock, FakeBus, FakeEvents


def _tree(root: Path, files: dict[str, int]) -> None:
    for rel, size in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)


def test_parquet_usage_is_exact_per_symbol_partition(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            "trades/symbol=BTCUSDT/dt=2026-10-01/a.parquet": 100,
            "bars/family=time/symbol=ETHUSDT/ym=2026-10/b.parquet": 50,
            "_manifests/m.json": 10,
        },
    )
    assert parquet_usage(tmp_path) == (160, {"BTCUSDT": 100, "ETHUSDT": 50})


class _Pg:
    """`fetch` answers each `table_partitions` query with one partition, then fails."""

    def __init__(self, sizes: list[int]) -> None:
        self.sizes, self.closed = sizes, False

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        if not self.sizes:
            raise OSError("questdb down")
        return [{"name": "2026-10-01", "diskSize": self.sizes.pop(0)}]

    async def close(self) -> None:
        self.closed = True


async def test_meter_apportions_hot_bytes_and_fails_the_pass_on_a_questdb_outage(
    tmp_path: Path,
) -> None:
    _tree(tmp_path, {"trades/symbol=BTCUSDT/dt=2026-10-01/a.parquet": 10})
    pg = _Pg([200] * len(HOT_STREAMS))
    meter = VolumeMeter(tmp_path, cast(Any, pg), written=lambda: {"BTCUSDT": 3, "ETHUSDT": 1})
    b = await meter.breakdown()
    assert b.tiers == {"questdb": 1_000, "parquet": 10}
    assert b.symbols == {"BTCUSDT": 760, "ETHUSDT": 250}
    with pytest.raises(OSError, match="questdb down"):  # never reported as 0 or as fresh
        await meter.breakdown()
    total, free = await meter.volume()
    assert 0 < free <= total
    await meter.close()
    assert pg.closed


async def test_a_hung_questdb_never_freezes_the_ladder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class HungPg(_Pg):
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            await asyncio.Event().wait()  # `disk_bytes` never returns
            return []

    monkeypatch.setattr(budget_wiring, "_volume", lambda _root: (100, 4))  # 4 % free
    budget = DiskBudget(
        meter=VolumeMeter(tmp_path, cast(Any, HungPg([]))),
        events=FakeEvents(),
        bus=FakeBus(),
        env="demo",
        config=BudgetConfig(cap_bytes=CAP, breakdown_timeout_s=0.05),
        now_us=Clock(),
    )
    await budget.sample_once()
    assert budget.level is DiskPressureLevel.HALT
    await budget.stop()


async def test_series_store_round_trips_skips_a_torn_line_and_keeps_n_days(tmp_path: Path) -> None:
    store = FileSeriesStore(tmp_path, "demo", keep_days=2)
    for day in range(3):
        await store.append(Point(NOW + day * US_PER_DAY, day, (("BTCUSDT", day),)))
    files = sorted((tmp_path / "_disk_budget" / "demo").glob("*.ndjson"))
    with files[-1].open("a", encoding="utf-8") as f:
        f.write('{"t": 1')  # a crash mid-append
    points = await store.load(0)
    assert len(files) == 2 and [p.symbols for p in points] == [(("BTCUSDT", 1),), (("BTCUSDT", 2),)]
    await store.close()
    missing = FileSeriesStore(tmp_path / "unmounted", "demo")
    with pytest.raises(FileNotFoundError):  # a missing root is never recreated
        await missing.append(Point(NOW, 0, ()))
    assert not (tmp_path / "unmounted").exists()
    await missing.close()


def test_builder_runs_on_the_real_backend_only_and_refuses_unsafe_volumes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data" / "parquet"
    base: dict[str, Any] = {"parquet_root": str(root), "bars_state_root": str(tmp_path / "bars")}
    repo, bus = cast(Any, object()), FakeBus()
    assert build_disk_budget(Settings(**base), bus=bus, recorder_repo=repo) is None
    real, hatch = (
        Settings(storage_backend="real", **base),
        Settings(storage_backend="real", environment="testnet", allow_shared_volume=True, **base),
    )
    missing = build_disk_budget(real, bus=bus, recorder_repo=repo)
    assert missing is not None and missing.recording_refused  # the root must exist
    root.mkdir(parents=True)
    shared = build_disk_budget(real, bus=bus, recorder_repo=repo)  # bars not created yet
    assert shared is not None and shared.recording_refused and shared.halted
    allowed = build_disk_budget(hatch, bus=bus, recorder_repo=repo)
    assert allowed is not None and not allowed.recording_refused


def test_refusal_never_raises_on_a_filesystem_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(_path: Path) -> bool:
        raise PermissionError("read-only volume")

    monkeypatch.setattr(Path, "is_dir", unreadable)
    assert recording_refusal(tmp_path, [], allow_shared=True) == "recording_volume_unreadable"


def test_disk_settings_default_to_the_k01_cap_and_refuse_the_hatch_outside_testnet() -> None:
    s = Settings()
    assert (s.disk_cap_gb, s.disk_warn_pct, s.disk_autostop_pct, s.disk_halt_pct) == (
        600,
        80,
        90,
        95,
    )
    for env in ("live", "demo"):
        with pytest.raises(ValidationError, match="CV_ALLOW_SHARED_VOLUME"):
            Settings(environment=env, allow_shared_volume=True)


class _Repo:
    at = datetime(2026, 10, 1, tzinfo=UTC)

    async def list_recorded(self) -> list[dict[str, object]]:
        return [{"symbol": "BTCUSDT", "pinned": True}, {"symbol": "ETHUSDT", "pinned": False}]

    async def gaps_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, object]]:
        end = self.at + timedelta(seconds=1)
        return [{"gap_start": self.at, "gap_end": end}] if symbol == "BTCUSDT" else []


async def test_gap_pin_and_written_sources() -> None:
    repo = cast(Any, _Repo())
    us = int(_Repo.at.timestamp()) * 1_000_000
    assert await recorded_gaps(repo, 0, 2 * us) == [(us, us + 1_000_000)]
    assert await pinned_symbols(repo) == {"BTCUSDT"}
    recorder_bytes_written_total.labels(symbol="ZZWIRINGUSDT", stream="trades").inc(5)
    assert written_by_symbol()["ZZWIRINGUSDT"] >= 5


async def test_one_thread_consumes_a_late_result_instead_of_restarting() -> None:
    lane, release, calls = _OneThread[int]("test-lane"), threading.Event(), [0]

    def slow() -> int:
        calls[0] += 1
        release.wait(5)
        return 7

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):  # the pass ends; the call keeps running
            await lane.run(slow)
    release.set()
    assert (await lane.run(slow), calls[0]) == (7, 1)
    lane.close()


async def test_one_thread_starts_a_fresh_call_after_a_failure() -> None:
    lane, answers = _OneThread[int]("test-lane"), [OSError("io"), 3]

    def call() -> int:
        answer = answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    with pytest.raises(OSError, match="io"):
        await lane.run(call)
    assert await lane.run(call) == 3
    lane.close()


async def test_one_thread_resubmits_a_call_cancelled_before_it_started() -> None:
    lane, hold, calls = _OneThread[int]("test-lane"), threading.Event(), [0]
    busy = lane._pool.submit(hold.wait, 5)  # the lane's only worker is busy: the next call queues

    def queued() -> int:
        calls[0] += 1
        return 7

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0):  # the pass ends before the worker ever starts the call
            await lane.run(queued)
    hold.set()
    await asyncio.wrap_future(busy)
    assert (await lane.run(queued), calls[0]) == (7, 1)  # not a CancelledError on every pass
    lane.close()
