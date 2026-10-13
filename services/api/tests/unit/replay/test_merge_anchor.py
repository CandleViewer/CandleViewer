"""Seek-anchor lookup (E26-T02 for E26-T04): the latest snapshot at or before an instant."""

from __future__ import annotations

import pytest

from candleviewer.replay import ReplayRequestInvalid, SourceTier
from candleviewer.replay.merge import ANCHOR_LOOKBACK_US
from candleviewer.storage.models import StreamKind
from tests.unit.replay._events import SECOND, T0, Harness, request, snapshot

BOOK = (StreamKind.ORDERBOOK_SNAPSHOT,)
WINDOW = request(start_us=0, end_us=7_200 * SECOND, streams=BOOK)


async def test_the_anchor_is_the_latest_snapshot_at_or_before_the_instant() -> None:
    harness = Harness(hot=[snapshot(t * 60 * SECOND, update_id=t) for t in range(5)], req=WINDOW)

    anchor = await harness.merge().anchor_at("BTCUSDT", T0 + 150 * SECOND)

    assert anchor is not None and anchor.ts_us == T0 + 120 * SECOND


async def test_an_anchor_at_the_exact_instant_is_used() -> None:
    harness = Harness(hot=[snapshot(60 * SECOND)], req=WINDOW)

    anchor = await harness.merge().anchor_at("BTCUSDT", T0 + 60 * SECOND)

    assert anchor is not None and anchor.ts_us == T0 + 60 * SECOND


async def test_auto_finds_a_snapshot_that_rolled_off_questdb() -> None:
    """The newest snapshot may live only in Parquet: both tiers are asked, the latest wins."""
    harness = Harness(
        cold=[snapshot(200 * SECOND, update_id=2)],  # dropped from QuestDB after archiving
        hot=[snapshot(100 * SECOND, update_id=1)],
        req=WINDOW,
    )

    anchor = await harness.merge().anchor_at("BTCUSDT", T0 + 250 * SECOND)

    assert anchor is not None and anchor.tiebreak[0] == 2
    assert harness.coverage.calls == 0  # one row, not a stream: no tier is chosen for it


async def test_auto_finds_a_snapshot_not_yet_archived() -> None:
    harness = Harness(
        cold=[snapshot(100 * SECOND, update_id=1)],
        hot=[snapshot(100 * SECOND, update_id=1), snapshot(210 * SECOND, update_id=2)],
        req=WINDOW,
    )

    anchor = await harness.merge().anchor_at("BTCUSDT", T0 + 250 * SECOND)

    assert anchor is not None and anchor.tiebreak[0] == 2


async def test_auto_breaks_a_cross_tier_tie_by_the_order_key() -> None:
    harness = Harness(
        cold=[snapshot(100 * SECOND, update_id=9)],
        hot=[snapshot(100 * SECOND, update_id=3)],
        req=WINDOW,
    )

    anchor = await harness.merge().anchor_at("BTCUSDT", T0 + 250 * SECOND)

    assert anchor is not None and anchor.seq == 9


@pytest.mark.parametrize(("tier", "want"), [("questdb", 2), ("parquet", 1)])
async def test_an_explicit_tier_looks_only_there(tier: SourceTier, want: int) -> None:
    req = request(start_us=0, end_us=7_200 * SECOND, streams=BOOK, tier=tier)
    harness = Harness(
        cold=[snapshot(100 * SECOND, update_id=1)],
        hot=[snapshot(100 * SECOND, update_id=2)],
        req=req,
    )

    anchor = await harness.merge().anchor_at("BTCUSDT", T0 + 250 * SECOND)

    assert anchor is not None and anchor.tiebreak[0] == want


async def test_a_snapshot_older_than_the_lookback_is_not_an_anchor() -> None:
    at = ANCHOR_LOOKBACK_US + 10 * SECOND
    harness = Harness(hot=[snapshot(5 * SECOND)], req=WINDOW)

    assert await harness.merge().anchor_at("BTCUSDT", T0 + at) is None


async def test_snapshots_of_another_depth_are_not_anchors() -> None:
    harness = Harness(hot=[snapshot(10 * SECOND, depth=50)], req=WINDOW)

    assert await harness.merge().anchor_at("BTCUSDT", T0 + 20 * SECOND) is None


@pytest.mark.parametrize(("symbol", "offset"), [("ETHUSDT", 10 * SECOND), ("BTCUSDT", -1)])
async def test_anchor_requests_outside_the_replay_are_refused(symbol: str, offset: int) -> None:
    merge = Harness(req=WINDOW).merge()

    with pytest.raises(ReplayRequestInvalid):
        await merge.anchor_at(symbol, T0 + offset)
