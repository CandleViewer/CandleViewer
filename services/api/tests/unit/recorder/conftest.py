"""Fakes for RecordingPolicy tests: fake clock, bus and audit sink (no I/O, no sleeps)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from candleviewer.bus.models import Topic
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy


class FakeClock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, RecorderSetChanged]] = []

    async def publish(self, topic: Topic, event: Any) -> None:
        self.events.append((topic.key, event))


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.records.append((action, kwargs))

    def envs(self) -> list[tuple[str, str]]:
        return [(a, kw["env"]) for a, kw in self.records]

    def actions(self) -> list[str]:
        return [a for a, _ in self.records]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def bus() -> FakeBus:
    return FakeBus()


@pytest.fixture
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture
async def policy(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> AsyncIterator[RecordingPolicy]:
    p = RecordingPolicy(
        disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock, config=PolicyConfig()
    )
    p.positions_reloaded()
    yield p
    await p.stop()
