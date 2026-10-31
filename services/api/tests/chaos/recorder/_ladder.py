"""The disk-pressure ladder rig (E16-Q04, C-13.6 #13): the production pieces over one volume.

Composed as `recorder_wiring` composes them, with only the edges faked:
- `DiskBudget` samples a `VolumeMeter` (cap = the whole volume) and drives the ladder;
- `RecordingPolicy` reads `budget.refuses_auto_record` for every new chart-open start;
- `StreamWriter` gates on `DiskGate(budget.halted, policy.position_open)`, its WAL on a separate
  tmp dir (SR-096: never the recording volume), fed by the fixture-derived E16-Q04 mix;
- the E07 `Reaper` runs over the same files (`VolumeRetention`): it accelerates below 15 % free
  and pauses the non-pinned auto-recorded symbols below 5 %.
Time is fixed (`NOW`); the budget's stale gate reads a constant monotonic clock, so no sample ever
ages; nothing sleeps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from bench.recorder.generator import Mix
from bench.recorder.harness import dispatch
from candleviewer.recorder.budget import BudgetConfig, DiskBudget
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy
from candleviewer.recorder.writer import STREAMS, DiskGate, StreamWriter, WriterConfig
from candleviewer.storage.retention.locks import InProcessRunLock
from candleviewer.storage.retention.policy import RetentionPolicy, load_defaults
from candleviewer.storage.retention.ports import Tier
from candleviewer.storage.retention.reaper import Reaper
from tests.chaos.recorder._volume import (
    NOW,
    NOW_US,
    TOTAL,
    VirtualVolume,
    VolumeMeter,
    VolumeRetention,
)
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem
from tests.unit.recorder._writer_helpers import FakeEvents, FakeSink, FakeStore, FsyncCounter

PINNED: Final = "BTCUSDT"  # pinned, auto-recorded, holds the open position
AUTO: Final = "ETHUSDT"  # auto-recorded, not pinned, no position
#: Pinned partitions: one inside the 30 d hot window, one past it, one past the 730 d cold one.
PINNED_PARTS: Final[tuple[tuple[Tier, int], ...]] = (("hot", 20), ("hot", 40), ("cold", 800))
#: 20 d old: inside trades' 30 d hot window, outside the accelerated (halved) 15 d one.
AUTO_PARTS: Final[tuple[tuple[Tier, int], ...]] = (("hot", 20),)


class LadderRig:
    def __init__(self, tmp_path: Path) -> None:
        self.volume = VirtualVolume(tmp_path / "recording", TOTAL, tmp_root=tmp_path)
        for tier, age in PINNED_PARTS:
            self.volume.add_partition(PINNED, tier, age)
        for tier, age in AUTO_PARTS:
            self.volume.add_partition(AUTO, tier, age)
        self.pinned_digest = self.volume.digest(PINNED)
        self.retention = VolumeRetention(self.volume, pinned={PINNED}, auto={PINNED, AUTO})
        self.bus = FakeBus()

        async def pins() -> frozenset[str]:
            return frozenset(self.retention.pinned)

        self.budget = DiskBudget(
            meter=VolumeMeter(self.volume), events=self.retention, bus=self.bus, env="demo",
            config=BudgetConfig(cap_bytes=TOTAL), now_us=lambda: NOW_US, pinned=pins,
            monotonic=lambda: 0.0,
        )  # fmt: skip
        r = self.retention
        self.reaper = Reaper(
            RetentionPolicy([], load_defaults()), r, r, r, r, r, r, clock=lambda: NOW,
            lock=InProcessRunLock(),
        )  # fmt: skip
        self.clock, self.audit = FakeClock(), FakeAudit()
        self.policy = RecordingPolicy(
            bus=self.bus, audit=self.audit, env="demo", now=self.clock, config=PolicyConfig(),
            disk_refuses=lambda: self.budget.refuses_auto_record, recorded=Mem(),
        )  # fmt: skip
        self.sink, self.store, self.events = FakeSink(), FakeStore(), FakeEvents()
        self.writer = StreamWriter(
            lambda _s: self.sink, self.store, self.events,
            WriterConfig(wal_dir=tmp_path / "wal", env="demo"),
            clock=self.clock, wall_clock_us=lambda: NOW_US, fsync=FsyncCounter(),
            disk_gate=DiskGate(lambda: self.budget.halted, self.policy.position_open),
        )  # fmt: skip
        self.mix = Mix((PINNED, AUTO), seed=13, depth=200)

    async def start(self) -> None:
        self.policy.positions_reloaded()
        await self.policy.on_position_opened(PINNED, "pos-1")
        await self.writer.open()
        self.writer.seed([PINNED, AUTO])

    async def stop(self) -> None:
        await self.writer.stop()
        await self.policy.stop()
        await self.budget.stop()

    async def at(self, pct: int) -> None:
        """Fill the volume to `pct` % used, then one budget sample and one reaper pass."""
        self.volume.fill_to(pct)
        await self.budget.sample_once()
        await self.reaper.run()

    async def feed(self, n: int) -> None:
        """`n` messages of the mix, then every lane flushed and gaps and counters persisted."""
        for i in range(n):
            await dispatch(self.writer, *self.mix.next(NOW_US + i))
        self.clock.advance(1.0)
        for stream in STREAMS:
            await self.writer.pump(stream)
        await self.writer.flush_gaps()
        await self.writer.flush_counters()

    def written(self, symbol: str | None = None) -> int:
        rows = [r for table in self.sink.flushed.values() for r in table]
        return sum(1 for r in rows if symbol is None or r["symbol"] == symbol)

    def dropped(self) -> int:
        return sum(kw["messages_dropped"] for _, kw in self.store.counters)

    def assert_pins_intact(self) -> None:
        """The negative control's target: every pinned byte is still what it was at arrange."""
        assert self.volume.digest(PINNED) == self.pinned_digest, "INVARIANT: pinned bytes changed"
