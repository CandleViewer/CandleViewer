"""Seek-anchor lookup (E26-T02 for E26-T04): the latest snapshot at or before an instant.

The lookup is one row, bounded on both sides (`at - ANCHOR_LOOKBACK_US <= ts <= at`), at the
session depth; under `auto` both tiers are asked and the latest by `order_key` wins.
"""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.replay import ReplayRequestInvalid, ReplaySourceUnavailable, SourceTier
from candleviewer.replay.merge import ANCHOR_LOOKBACK_US
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import SECOND, SYM, T0, BoundedTier, Harness, request, snapshot

BOOK = (StreamKind.ORDERBOOK_SNAPSHOT,)
END = 7_200 * SECOND
WINDOW = request(start_us=0, end_us=END, streams=BOOK)


def update_of(anchor: RecordedEvent | None) -> int | None:
    return None if anchor is None else int(anchor.tiebreak[0])


async def test_the_anchor_is_the_latest_snapshot_at_or_before_the_instant() -> None:
    harness = Harness(hot=[snapshot(t * 60 * SECOND, update_id=t) for t in range(5)], req=WINDOW)

    anchor = await harness.merge().anchor_at(SYM, T0 + 150 * SECOND)

    assert anchor is not None and anchor.ts_us == T0 + 120 * SECOND


async def test_an_anchor_at_the_exact_instant_is_used_but_a_later_snapshot_is_not() -> None:
    harness = Harness(
        hot=[snapshot(60 * SECOND), snapshot(60 * SECOND + 1, update_id=2)], req=WINDOW
    )

    anchor = await harness.merge().anchor_at(SYM, T0 + 60 * SECOND)

    assert update_of(anchor) == 1 and anchor is not None and anchor.ts_us == T0 + 60 * SECOND


async def test_auto_finds_a_snapshot_that_rolled_off_questdb() -> None:
    """The newest snapshot may live only in Parquet: both tiers are asked, the latest wins."""
    harness = Harness(
        cold=[snapshot(200 * SECOND, update_id=2)],  # dropped from QuestDB after archiving
        hot=[snapshot(100 * SECOND, update_id=1)],
        req=WINDOW,
    )

    anchor = await harness.merge().anchor_at(SYM, T0 + 250 * SECOND)

    assert update_of(anchor) == 2
    assert harness.coverage.calls == 0  # one row, not a stream: no tier is chosen for it


async def test_auto_finds_a_snapshot_not_yet_archived() -> None:
    harness = Harness(
        cold=[snapshot(100 * SECOND, update_id=1)],
        hot=[snapshot(100 * SECOND, update_id=1), snapshot(210 * SECOND, update_id=2)],
        req=WINDOW,
    )

    anchor = await harness.merge().anchor_at(SYM, T0 + 250 * SECOND)

    assert update_of(anchor) == 2


async def test_auto_breaks_a_cross_tier_tie_by_the_order_key() -> None:
    harness = Harness(
        cold=[snapshot(100 * SECOND, update_id=9)],
        hot=[snapshot(100 * SECOND, update_id=3)],
        req=WINDOW,
    )

    anchor = await harness.merge().anchor_at(SYM, T0 + 250 * SECOND)

    assert anchor is not None and anchor.seq == 9


@pytest.mark.parametrize(
    ("tier", "want", "unread"), [("questdb", 2, "cold"), ("parquet", 1, "hot")]
)
async def test_an_explicit_tier_looks_only_there(tier: SourceTier, want: int, unread: str) -> None:
    req = request(start_us=0, end_us=END, streams=BOOK, tier=tier)
    harness = Harness(
        cold=[snapshot(100 * SECOND, update_id=1)],
        hot=[snapshot(100 * SECOND, update_id=2)],
        req=req,
    )

    anchor = await harness.merge().anchor_at(SYM, T0 + 250 * SECOND)

    assert update_of(anchor) == want
    assert getattr(harness, unread).reads == 0 and harness.coverage.calls == 0


async def test_the_lookback_is_one_hour_inclusive_at_its_far_edge_and_no_further() -> None:
    """60 x the 60 s snapshot cadence (ADR-0035), spelled out so the constant is pinned too."""
    hour = 3_600 * SECOND
    at = hour + 10 * SECOND
    edge, older = snapshot(at - hour), snapshot(at - hour - 1, update_id=2)

    with_edge = Harness(hot=[older, edge], req=WINDOW)
    without = Harness(hot=[older], req=WINDOW)

    assert update_of(await with_edge.merge().anchor_at(SYM, T0 + at)) == 1
    assert await without.merge().anchor_at(SYM, T0 + at) is None
    assert ANCHOR_LOOKBACK_US == hour


async def test_the_anchor_is_a_snapshot_of_the_session_depth_only() -> None:
    stored = [snapshot(10 * SECOND, depth=50, update_id=1), snapshot(11 * SECOND, update_id=2)]
    shallow = request(start_us=0, end_us=END, streams=BOOK, depth=50)

    assert (
        update_of(await Harness(hot=stored, req=shallow).merge().anchor_at(SYM, T0 + 20 * SECOND))
        == 1
    )
    assert (
        update_of(await Harness(hot=stored, req=WINDOW).merge().anchor_at(SYM, T0 + 20 * SECOND))
        == 2
    )
    other = Harness(hot=[snapshot(10 * SECOND, depth=500)], req=WINDOW)
    assert await other.merge().anchor_at(SYM, T0 + 20 * SECOND) is None


class _LookupLog(BoundedTier):
    """Records the arguments of every anchor lookup."""

    def __init__(self) -> None:
        super().__init__()
        self.lookups: list[tuple[str, int, int, int]] = []

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        self.lookups.append((symbol, depth, at_us, not_before_us))
        return await super().snapshot_at(symbol, depth, at_us, not_before_us=not_before_us)


async def test_each_tier_is_asked_for_a_two_sided_bounded_range() -> None:
    hot, cold = _LookupLog(), _LookupLog()
    req = request(start_us=0, end_us=END, streams=BOOK, depth=50)
    harness = Harness(req=req).replace_ports(hot=hot, cold=cold)
    at = T0 + 250 * SECOND

    await harness.merge().anchor_at(SYM, at)

    want = [(SYM, 50, at, at - ANCHOR_LOOKBACK_US)]
    assert hot.lookups == want and cold.lookups == want


@pytest.mark.parametrize(("symbol", "at"), [("ETHUSDT", 10 * SECOND), (SYM, -1), (SYM, END + 1)])
async def test_anchor_requests_outside_the_replay_are_refused_before_any_read(
    symbol: str, at: int
) -> None:
    harness = Harness(hot=[snapshot(5 * SECOND)], cold=[snapshot(5 * SECOND)], req=WINDOW)

    with pytest.raises(ReplayRequestInvalid) as raised:
        await harness.merge().anchor_at(symbol, T0 + at)

    assert harness.hot.reads == harness.cold.reads == 0
    assert "ETHUSDT" not in str(raised.value) and str(T0) not in str(raised.value)


@pytest.mark.parametrize("at", [0, END])
async def test_both_edges_of_the_replay_are_valid_anchor_instants(at: int) -> None:
    harness = Harness(hot=[snapshot(at)], req=WINDOW)

    anchor = await harness.merge().anchor_at(SYM, T0 + at)

    assert anchor is not None and anchor.ts_us == T0 + at


class _FailingLookups(BoundedTier):
    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        raise StorageTierUnavailable("unreachable at /srv/cv/cold")


class _StuckLookups(BoundedTier):
    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        await asyncio.Event().wait()  # never answers
        return None


@pytest.mark.parametrize(("failing", "tier"), [("hot", "questdb"), ("cold", "parquet")])
async def test_a_failing_tier_fails_the_lookup_instead_of_answering_from_the_other(
    failing: str, tier: str
) -> None:
    """Under `auto` the answer must not depend on which tier is up: an older row from the
    healthy tier would be a silently wrong anchor."""
    harness = Harness(hot=[snapshot(100 * SECOND)], cold=[snapshot(100 * SECOND)], req=WINDOW)
    if failing == "hot":
        harness.replace_ports(hot=_FailingLookups())
    else:
        harness.replace_ports(cold=_FailingLookups())

    with pytest.raises(ReplaySourceUnavailable) as raised:
        await harness.merge().anchor_at(SYM, T0 + 250 * SECOND)

    error = raised.value
    assert (error.tier, error.stream, error.reason) == (
        tier,
        StreamKind.ORDERBOOK_SNAPSHOT,
        "STORAGE_TIER_UNAVAILABLE",
    )
    assert "/srv" not in str(error) and error.__cause__ is None and error.__context__ is None


async def test_a_lookup_that_never_answers_times_out_as_a_typed_error() -> None:
    harness = Harness(req=WINDOW).replace_ports(hot=_StuckLookups())

    async with asyncio.timeout(5):
        with pytest.raises(ReplaySourceUnavailable) as raised:
            await harness.merge(timeout_s=0.001).anchor_at(SYM, T0 + 250 * SECOND)

    assert (raised.value.tier, raised.value.reason) == ("questdb", "timeout")
