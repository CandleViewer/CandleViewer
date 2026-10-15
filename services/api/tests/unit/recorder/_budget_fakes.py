"""In-memory fakes for the E16-T07 `DiskBudget` tests (no I/O, no clock, no sleeps)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from candleviewer.bus.models import Topic
from candleviewer.recorder.budget import US_PER_S, Breakdown, BudgetConfig, DiskBudget, Point
from candleviewer.recorder.models import DiskPressureChanged, TierName

GB = 10**9
NOW = 1_790_000_000 * US_PER_S
CAP = 600 * GB
TOTAL = 1_000 * GB


@dataclass
class FakeMeter:
    used: int = 0  # recorded bytes, split across questdb / parquet
    free: int = TOTAL // 2
    symbols: dict[str, int] = field(default_factory=dict)
    fail: bool = False
    breakdown_fail: bool = False
    closed: bool = False

    async def volume(self) -> tuple[int, int]:
        if self.fail:
            raise OSError("statvfs failed")
        return TOTAL, self.free

    async def breakdown(self) -> Breakdown:
        if self.breakdown_fail:
            raise TimeoutError("questdb slow")
        half = self.used // 2
        tiers: dict[TierName, int] = {"questdb": half, "parquet": self.used - half, "postgres": GB}
        return Breakdown(tiers, dict(self.symbols))

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeEvents:
    events: list[tuple[str, str, dict[str, str | int]]] = field(default_factory=list)

    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        self.events.append((severity, code, detail))


@dataclass
class FakeBus:
    events: list[DiskPressureChanged] = field(default_factory=list)
    fail_next: bool = False

    async def publish(self, topic: Topic, event: DiskPressureChanged) -> None:
        assert topic.key == "demo.recorder.disk_pressure"
        if self.fail_next:
            self.fail_next = False
            raise OSError("bus unavailable")
        self.events.append(event)


@dataclass
class FakeStore:
    points: list[Point] = field(default_factory=list)
    appended: list[Point] = field(default_factory=list)
    broken: bool = False
    closed: bool = False

    async def load(self, since_us: int) -> list[Point]:
        if self.broken:
            raise OSError("volume full")
        return [p for p in self.points if p.ts_us >= since_us]

    async def append(self, point: Point) -> None:
        if self.broken:
            raise OSError("volume full")
        self.appended.append(point)

    async def close(self) -> None:
        self.closed = True


@dataclass
class Clock:
    t: int = NOW

    def __call__(self) -> int:
        return self.t


def make_budget(
    meter: FakeMeter,
    *,
    clock: Callable[[], int] | None = None,
    store: FakeStore | None = None,
    gaps: Sequence[tuple[int, int]] | None = None,
    pinned: frozenset[str] = frozenset(),
    sleep: Callable[[float], Awaitable[None]] | None = None,
    bus: FakeBus | None = None,
    config: BudgetConfig | None = None,
) -> tuple[DiskBudget, FakeEvents, FakeBus]:
    events, bus = FakeEvents(), bus or FakeBus()

    async def gap_source(lo: int, hi: int) -> Sequence[tuple[int, int]]:
        return [g for g in gaps or () if g[1] > lo and g[0] < hi]

    async def pinned_source() -> frozenset[str]:
        return pinned

    budget = DiskBudget(
        meter=meter,
        events=events,
        bus=bus,
        env="demo",
        config=config or BudgetConfig(cap_bytes=CAP),
        now_us=clock or Clock(),
        gaps=gap_source if gaps is not None else None,
        pinned=pinned_source,
        store=store,
        sleep=sleep or asyncio.sleep,
    )
    return budget, events, bus
