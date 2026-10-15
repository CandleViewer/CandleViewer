"""Shared harness for the `BarBuilderSet` tests (E12-T03): real bus, fake sinks/tape/clock."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from pathlib import Path

from candleviewer.bars.builder_set import BarBuilderSet
from candleviewer.bars.emit import BarEmission, EmitRouter, WriterSink
from candleviewer.bars.leases import DEFAULT_CAPS, SpecCaps
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.state_store import StateStore
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.models import TradeEvent

from ._trades import SYM

ENV = "demo"
TOPIC = Topic(env=ENV, domain="md", symbol=SYM, detail="trade")
M1 = BarSpec(kind="time", interval_ms=60_000)
H1 = BarSpec(kind="time", interval_ms=3_600_000)
T3 = BarSpec(kind="tick", tick_count=3)
V5 = BarSpec(kind="volume", volume_threshold=Decimal(5))


class Clock:
    def __init__(self, t: int = 0) -> None:
        self.t = t

    def __call__(self) -> int:
        return self.t


class RecordingSink:
    def __init__(self, name: str = "ws", delay: int = 0) -> None:
        self.name, self.delay = name, delay
        self.seen: list[tuple[str, int, str, int, str]] = []
        #: Full emissions (spec_hash, kind, Bar) for whole-bar comparisons (BI-5).
        self.bars: list[tuple[str, str, Bar]] = []

    async def emit(self, emission: BarEmission) -> None:
        for _ in range(self.delay):
            await asyncio.sleep(0)
        for u in emission.updates:
            self.bars.append((emission.spec.spec_hash, u.kind, u.bar))
            self.seen.append(
                (
                    emission.spec.spec_hash,
                    emission.generation,
                    u.kind,
                    u.bar.index,
                    str(u.bar.close),
                )
            )


class FakeWriter:
    """Structural stand-in for E12-T02 `BarWriter.submit` (no QuestDB)."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, int, str]] = []
        self.generations: list[int] = []  # one per row in `rows`

    async def submit(
        self, bars: Sequence[Bar], spec: BarSpec, *, source: str = "tape", generation: int = 0
    ) -> None:
        self.rows.extend((spec.spec_hash, b.index, source) for b in bars)
        self.generations.extend(generation for _ in bars)


class FakeTape:
    def __init__(self, trades: Sequence[TradeEvent] = ()) -> None:
        self.trades = list(trades)
        self.reads = 0

    async def head_us(self, symbol: str) -> int | None:
        return max((t.ts_event for t in self.trades), default=None)

    async def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]:
        for t in self.trades:
            if t.ts_event >= ts_us:
                self.reads += 1
                yield t


def make_set(
    root: Path,
    *,
    bus: Bus | None = None,
    sinks: Sequence[object] = (),
    tape: FakeTape | None = None,
    clock: Clock | None = None,
    caps: SpecCaps = DEFAULT_CAPS,
) -> BarBuilderSet:
    return BarBuilderSet(
        bus or Bus(),
        ENV,
        EmitRouter(sinks),  # type: ignore[arg-type]  # test sinks satisfy BarSink structurally
        StateStore(root),
        tape=tape,
        now_us=clock or Clock(),
        caps=caps,
    )


async def settle(bus: Bus, s: BarBuilderSet | None = None) -> None:
    """Yield until every bus queue is empty and no lane holds its lock (no sleeps)."""
    for _ in range(10_000):
        await asyncio.sleep(0)
        busy = s is not None and any(lane.lock.locked() for lane in s._lanes.values())
        if not busy and all(q.qsize() == 0 for q in bus._subscriptions):
            await asyncio.sleep(0)
            if not (s is not None and any(lane.lock.locked() for lane in s._lanes.values())):
                return
    raise AssertionError("lanes did not settle")


__all__ = ["FakeTape", "FakeWriter", "RecordingSink", "WriterSink", "make_set", "settle"]
