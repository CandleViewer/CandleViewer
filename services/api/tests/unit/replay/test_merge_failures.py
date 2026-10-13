"""Typed, bounded storage failures (E26-T02): every await is time-bounded and typed."""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.replay import ReplaySourceUnavailable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from candleviewer.storage.testing import InMemoryRecordedTier, StaticArchiveCoverage
from tests.unit.replay._events import Harness


class _FailingTier(InMemoryRecordedTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        raise StorageTierUnavailable("questdb unreachable")


class _StuckTier(InMemoryRecordedTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        await asyncio.Event().wait()  # never answers
        return []


class _FailingCoverage(StaticArchiveCoverage):
    async def archived(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[TimeRange]:
        raise StorageTierUnavailable("cold manifests unreadable")


async def test_a_storage_failure_surfaces_as_a_typed_error_with_its_code() -> None:
    harness = Harness().replace_ports(hot=_FailingTier())

    with pytest.raises(ReplaySourceUnavailable) as raised:
        await harness.read_all()

    assert (raised.value.tier, raised.value.reason) == ("questdb", "STORAGE_TIER_UNAVAILABLE")


async def test_a_storage_read_that_never_answers_times_out() -> None:
    harness = Harness().replace_ports(hot=_StuckTier())
    merge = harness.merge(timeout_s=0.01)

    with pytest.raises(ReplaySourceUnavailable) as raised:
        async for _ in merge.batches(max_events=8, max_bytes=1 << 30):
            pass

    assert raised.value.reason == "timeout"


async def test_a_failing_manifest_lookup_is_typed_and_reads_nothing() -> None:
    harness = Harness().replace_ports(coverage=_FailingCoverage())

    with pytest.raises(ReplaySourceUnavailable) as raised:
        await harness.read_all()

    assert raised.value.tier == "manifest"
    assert harness.hot.reads == harness.cold.reads == 0
