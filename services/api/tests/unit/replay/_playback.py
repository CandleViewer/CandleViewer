"""Test doubles for the replay clock's ports (E26-T03)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from candleviewer.replay import ReplayError, ReplayGap, ReplayItem, StopReason
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._time import FakeTime


class ListStream:
    """`ReplayStream` over `items`; `closes` counts `aclose` calls. `fail_at` raises `error` in
    place of that item, as a storage failure mid-replay would."""

    def __init__(
        self, items: Iterable[ReplayItem], *, fail_at: int = -1, error: ReplayError | None = None
    ) -> None:
        self._items, self._next, self._fail_at, self._error = list(items), 0, fail_at, error
        self.closes = 0

    async def __anext__(self) -> ReplayItem:
        if self.closes or self._next >= len(self._items):
            raise StopAsyncIteration
        if self._next == self._fail_at and self._error is not None:
            raise self._error
        self._next += 1
        return self._items[self._next - 1]

    async def aclose(self) -> None:
        self.closes += 1


class RecordingSink:
    """`ReplaySink` recording each event and the fake time it arrived; each delivery costs
    `cost_s` of fake time (a consumer that slow)."""

    def __init__(self, time: FakeTime, *, cost_s: float = 0.0) -> None:
        self.time, self.cost_s = time, cost_s
        self.events: list[RecordedEvent] = []
        self.at: list[float] = []

    async def deliver(self, event: RecordedEvent) -> None:
        self.at.append(self.time.now())
        self.events.append(event)
        if self.cost_s:
            self.time.advance(self.cost_s)
            await asyncio.sleep(0)


class RecordingObserver:
    def __init__(self) -> None:
        self.gaps: list[tuple[ReplayGap, bool]] = []
        self.edges: list[bool] = []
        self.stops: list[tuple[StopReason, ReplayError | None]] = []

    def on_gap(self, gap: ReplayGap, *, stopped: bool) -> None:
        self.gaps.append((gap, stopped))

    def on_backpressure(self, active: bool) -> None:
        self.edges.append(active)

    def on_stop(self, reason: StopReason, error: ReplayError | None) -> None:
        self.stops.append((reason, error))
