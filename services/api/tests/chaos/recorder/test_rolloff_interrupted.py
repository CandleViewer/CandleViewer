"""C-13.6 #13 extension (BQ-2), E16-Q04: the nightly roll-off killed mid-run, then re-run.

The real `RollOffJob` over the real storage-side `ColdArchiver` / `ColdExporter` (Parquet under
`tmp_path`), the file watermark store and a hot tier holding one closed day. A kill is `Crash`, a
`BaseException` no handler may swallow, fired at the exporter's test-only crash points or inside
`drop_day`. The invariant (21 §5.3, the roll-off module): a day is in the hot tier, the cold tier
or both, never neither, and a re-run converges on one verified cold copy and one drop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Final

import pytest

from candleviewer.recorder.rolloff import RollOffConfig, RollOffJob, RollOffReport
from candleviewer.storage.cold import exporter as exporter_mod
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore
from candleviewer.storage.cold.rolloff_ops import ColdArchiver
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.models import StreamKind, TimeRange
from tests.chaos.storage._harness import PART, Crash, chaos_table
from tests.unit.storage.cold._helpers import (
    DAY_START_US,
    FakeHotSource,
    RecordingSink,
    fixed_clock,
)

pytestmark = [pytest.mark.chaos, pytest.mark.usefixtures("crash_hooks")]
T: Final = StreamKind.TRADES
SYMBOL: Final = "BTCUSDT"
N: Final = 40
DAY_US: Final = 86_400_000_000


class Hot:
    """One closed QuestDB day of `SYMBOL` trades; `kill_on_drop` kills the run inside the DROP."""

    def __init__(self, source: FakeHotSource) -> None:
        self.source, self.present, self.kill_on_drop = source, True, False
        self.drops = 0

    async def closed_days(self, stream: StreamKind, before_us: int) -> list[int]:
        return [DAY_START_US] if self.present and DAY_START_US + DAY_US <= before_us else []

    async def aged_partitions(self, stream: StreamKind, before_us: int) -> int:
        return 0

    async def symbols_in(self, stream: StreamKind, rng: TimeRange) -> list[str]:
        return [SYMBOL] if self.present else []

    async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
        return {SYMBOL: self.source.table.num_rows} if self.present else {}

    async def snapshot(self, stream: StreamKind, rng: TimeRange) -> dict[str, tuple[int, str]]:
        return {s: (n, "v0") for s, n in (await self.row_counts(stream, rng)).items()}

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> None:
        if self.kill_on_drop:
            raise Crash("killed between verify and drop")
        self.present, self.drops = False, self.drops + 1


class Audit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        self.actions.append(action)


class Lock:
    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        yield True


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "cold"
        self.registry = DatasetRegistry(self.root)
        self.source = FakeHotSource(chaos_table(N))
        self.hot, self.sink, self.audit = Hot(self.source), RecordingSink(), Audit()
        self.marks = FileWatermarkStore(self.registry, self.sink)

    def job(self) -> RollOffJob:
        exporter = ColdExporter(self.registry, self.source, clock=fixed_clock, events=self.sink)
        archiver = ColdArchiver(self.registry, self.source, exporter=exporter, events=self.sink)

        async def hot_days(_symbol: str, _stream: StreamKind) -> int:
            return 1

        async def no_wait(_s: float) -> None:
            return None

        return RollOffJob(
            hot=self.hot, archiver=archiver, watermarks=self.marks, hot_days=hot_days,
            audit=self.audit, events=self.sink, lock=Lock(),
            config=RollOffConfig(streams=(T,)), clock=lambda: fixed_clock() + timedelta(days=5),
            sleep=no_wait,
        )  # fmt: skip

    def entries(self) -> list[ManifestEntry]:
        return ManifestStore(self.root / "_manifests").read(self.root / PART, self.root)

    async def archived_through(self) -> int:
        return (await self.marks.get(SYMBOL, T)).archived_through_us

    def codes(self) -> list[str]:
        return [code for _, code, _ in self.sink.events]


def _arm(point: str) -> None:
    def kill() -> None:
        raise Crash(point)

    exporter_mod.arm_test_hook(point, kill)


async def test_rolloff_killed_between_write_and_verify_keeps_hot_and_rerun_converges(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    _arm(exporter_mod.AFTER_CHECKSUM)  # Parquet committed, manifest and read-back not reached
    with pytest.raises(Crash):
        await rig.job().run()
    assert rig.hot.present and rig.hot.drops == 0, "INVARIANT: the hot day stays"
    assert rig.entries() == [] and await rig.archived_through() == 0, "nothing claims cold"
    assert rig.audit.actions == [], "no purge record before verification"

    exporter_mod._TEST_HOOKS.clear()
    report = await rig.job().run()
    assert report.dropped == [(T, DAY_START_US)] and rig.hot.drops == 1
    [entry] = rig.entries()
    assert entry.row_count == N, "INVARIANT: zero rows lost"
    assert sorted(p.name for p in (rig.root / PART).glob("part-*.parquet")) == [entry.file]
    assert await rig.archived_through() == DAY_START_US + DAY_US


async def test_rolloff_killed_between_verify_and_drop_converges_on_rerun(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.hot.kill_on_drop = True
    with pytest.raises(Crash):
        await rig.job().run()
    assert rig.hot.present, "INVARIANT: the day is in both tiers, never in neither"
    assert [e.row_count for e in rig.entries()] == [N], "verified cold copy"
    assert await rig.archived_through() == DAY_START_US + DAY_US, "watermark never trails a drop"
    assert rig.audit.actions == ["retention.purge"], "write-ahead audit (C-2.9)"

    rig.hot.kill_on_drop = False
    report: RollOffReport = await rig.job().run()
    assert report.dropped == [(T, DAY_START_US)] and rig.hot.drops == 1 and not rig.hot.present
    assert [e.row_count for e in rig.entries()] == [N], "re-archive is idempotent: one entry"
    assert await rig.archived_through() == DAY_START_US + DAY_US


async def test_rolloff_torn_file_after_kill_is_refused_alerted_then_rearchived(
    tmp_path: Path,
) -> None:
    """Killed after the manifest, with the file torn on disk: the re-run's read-back refuses the
    torn copy (CRITICAL) before anything is dropped, and its retry re-exports a good one."""
    rig = Rig(tmp_path)
    _arm(exporter_mod.AFTER_MANIFEST)
    with pytest.raises(Crash):
        await rig.job().run()
    exporter_mod._TEST_HOOKS.clear()
    assert rig.hot.present and await rig.archived_through() == 0, "the kill dropped nothing"
    part = next((rig.root / PART).glob("part-*.parquet"))
    part.write_bytes(part.read_bytes()[:-16] + b"\0" * 16)

    report = await rig.job().run()
    assert "archive.verification_failed" in rig.codes(), "the torn copy is refused loudly"
    assert report.dropped == [(T, DAY_START_US)] and rig.hot.drops == 1, "dropped once, after"
    assert [e.row_count for e in rig.entries()] == [N], "one verified copy, zero rows lost"
    assert rig.audit.actions == ["retention.purge"]
