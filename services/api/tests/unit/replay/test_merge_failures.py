"""Fail-closed construction and typed, bounded storage failures (E26-T02)."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable

import pytest

from candleviewer.replay import ReplayConfigInvalid, ReplaySourceUnavailable
from candleviewer.replay.merge import RecordedMerge
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import SECOND, BoundedTier, Harness, drain, trade

#: Storage error text may carry a path (RP-I02); the typed replay error must not.
COLD_PATH = "/srv/cv/cold/env=live/symbol=BTCUSDT/date=2026-10-01"


class _FailingTier(BoundedTier):
    """Serves its first read, then fails every later one with a storage error naming a path."""

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if self.reads:
            raise StorageTierUnavailable(f"cannot read {COLD_PATH}")
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


class _StuckTier(BoundedTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        await asyncio.Event().wait()  # never answers
        return []


def recording() -> list[RecordedEvent]:
    return [trade(t * SECOND, trade_id=f"r{t:02}") for t in range(60)]


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda h: h.merge(window_us=0), id="zero-window"),
        pytest.param(lambda h: h.merge(window_us=-SECOND), id="negative-window"),
        pytest.param(lambda h: h.merge(window_us=2, max_window_us=1), id="cap-below-window"),
        pytest.param(lambda h: h.merge(timeout_s=0.0), id="zero-timeout"),
        pytest.param(lambda h: h.merge(timeout_s=-1.0), id="negative-timeout"),
        pytest.param(lambda h: h.merge(timeout_s=math.inf), id="unbounded-timeout"),
        pytest.param(lambda h: h.merge(timeout_s=math.nan), id="nan-timeout"),
        pytest.param(lambda h: h.merge(budget_bytes=0), id="zero-budget"),
        pytest.param(lambda h: h.merge(budget_bytes=-1), id="negative-budget"),
    ],
)
def test_an_out_of_bound_merge_is_refused_before_any_read(
    build: Callable[[Harness], RecordedMerge],
) -> None:
    harness = Harness(hot=recording())

    with pytest.raises(ReplayConfigInvalid):
        build(harness)

    assert harness.hot.reads == harness.coverage.calls == 0


async def test_a_zero_read_window_fails_fast_instead_of_reading_forever() -> None:
    """A 0 µs window would re-read one empty window with no suspension point, so no timeout
    could fire. The bounded tier turns such a loop into a failure, never a hung test."""
    harness = Harness(hot=recording())

    with pytest.raises(ReplayConfigInvalid):
        await harness.read_all(window_us=0)

    assert harness.hot.reads == 0


async def test_a_storage_failure_becomes_a_typed_error_with_its_code_and_no_path() -> None:
    harness = Harness().replace_ports(hot=_FailingTier(recording()))

    _, error = await drain(harness.merge(window_us=10 * SECOND), batch=8)

    assert isinstance(error, ReplaySourceUnavailable)
    assert (error.tier, error.stream, error.reason) == (
        "questdb",
        StreamKind.TRADES,
        "STORAGE_TIER_UNAVAILABLE",
    )
    assert "/srv" not in str(error) and "date=" not in str(error)
    assert error.__cause__ is None and error.__context__ is None


async def test_a_storage_read_that_never_answers_times_out_as_a_typed_error() -> None:
    harness = Harness().replace_ports(hot=_StuckTier())

    async with asyncio.timeout(5):  # a merge without its own deadline fails here, not hangs
        delivered, error = await drain(harness.merge(timeout_s=0.001), batch=8)

    assert delivered == []
    assert isinstance(error, ReplaySourceUnavailable)
    assert (error.reason, error.__cause__, error.__context__) == ("timeout", None, None)


@pytest.mark.parametrize("batch", [1, 4, 64])
async def test_a_failure_mid_replay_is_raised_after_every_event_already_merged(batch: int) -> None:
    """24 Sec.13.7: the error follows the events already merged, whatever the batch size: the
    batch in progress is delivered, never dropped."""
    harness = Harness().replace_ports(hot=_FailingTier(recording()))

    delivered, error = await drain(harness.merge(window_us=10 * SECOND), batch=batch)

    assert [e.tiebreak[0] for e in delivered if isinstance(e, RecordedEvent)] == [
        f"r{t:02}" for t in range(10)
    ]
    assert isinstance(error, ReplaySourceUnavailable)
