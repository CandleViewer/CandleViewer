"""Fixtures for RecordingPolicy tests: fake clock, bus and audit sink (no I/O, no sleeps)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock


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
