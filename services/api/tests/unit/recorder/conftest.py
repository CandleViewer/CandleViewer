"""Fixtures for RecordingPolicy tests: fake clock, bus and audit sink (no I/O, no sleeps)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from candleviewer.recorder.policy import RecordingPolicy
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, MemRecordedStore


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def bus() -> FakeBus:
    return FakeBus()


@pytest.fixture
def trace() -> list[str]:
    """The order of the store's calls and the audit's emits."""
    return []


@pytest.fixture
def audit(trace: list[str]) -> FakeAudit:
    return FakeAudit(trace)


@pytest.fixture
def store(trace: list[str]) -> MemRecordedStore:
    return MemRecordedStore(trace)


@pytest.fixture
async def policy(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit, store: MemRecordedStore
) -> AsyncIterator[RecordingPolicy]:
    p = RecordingPolicy(
        disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock, recorded=store
    )
    p.positions_reloaded()
    yield p
    await p.stop()
