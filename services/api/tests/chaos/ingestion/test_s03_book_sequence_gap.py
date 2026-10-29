"""Scenario 3 - `orderbook.200` sequence gap / duplicate / reorder. C-13.6 #3.

Declared: on a hole the book goes DESYNCED *before* any further delta is
published, unsubscribes + resubscribes the topic, replays the buffered deltas
on top of the fresh snapshot and reaches LIVE; the resynced book equals the
exchange's REST-snapshot oracle at the full subscribed depth (zero silent
patching). Metric: `ingest_book_resyncs_total{reason="sequence_gap"}` +1,
`ingest_book_live` 1 -> 0 -> 1. Signal: `BookStatus(desynced, sequence_gap)`.
"""

from __future__ import annotations

import pytest

from candleviewer.book.models import BookPhase
from candleviewer.ingestion.metrics import ingest_book_live, ingest_book_resyncs_total
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

TOPIC = "orderbook.200.BTCUSDT"
RESYNC_SLO_S = 3.0


def _resyncs(reason: str) -> float:
    return metric(ingest_book_resyncs_total, symbol="BTCUSDT", reason=reason, depth="200")


async def _live(rig: Rig, feed: Feeder) -> None:
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    rig.ex.snapshot_lag_frames = 3  # snapshot arrives after 3 more deltas: exercises buffering
    await feed.run(2.0)
    assert rig.book_phase() is BookPhase.LIVE


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (FaultKind.DROP, "sequence_gap"),
        (FaultKind.REORDER, "sequence_gap"),
    ],
)
async def test_s03_gap_desyncs_before_any_delta_then_matches_oracle(
    rig: Rig, kind: FaultKind, reason: str
) -> None:
    feed = Feeder(rig.ex)
    await _live(rig, feed)
    rig.observe()
    before = _resyncs(reason)
    rig.ex.inject(Fault(kind, topic=TOPIC))

    t0 = rig.clock.now
    await feed.run(0.3)
    order = list(rig.observe().order)
    desync_at = order.index("status:desynced")
    hole_u = rig.ex.books[TOPIC].u - 2  # the frame lost/held at injection
    assert all(
        int(o.split(":")[1]) < hole_u for o in order[:desync_at] if o.startswith("delta:")
    ), "a delta past the hole was published before DESYNCED"
    assert _resyncs(reason) == before + 1
    assert metric(ingest_book_live, symbol="BTCUSDT") == 0.0
    sock = rig.ex.live_sockets()[0]
    assert [m["op"] for m in sock.sent[-2:]] == ["unsubscribe", "subscribe"]

    while rig.book_phase() is not BookPhase.LIVE:
        assert rig.clock.now - t0 <= RESYNC_SLO_S, "book not resynced within SLO"
        await feed.run(0.1)
    feed.paused.add("BTCUSDT")  # freeze the venue so book and oracle are comparable
    await feed.run(0.2)
    assert rig.book_levels() == rig.ex.books[TOPIC].levels()  # full depth, every level
    assert metric(ingest_book_live, symbol="BTCUSDT") == 1.0
    status = [s for s in rig.observe().book_status if s.state is BookPhase.DESYNCED]
    assert status and status[-1].reason == reason


async def test_s03_duplicate_delta_forces_resync_never_double_apply(rig: Rig) -> None:
    feed = Feeder(rig.ex)
    await _live(rig, feed)
    before = _resyncs("sequence_gap")
    rig.ex.inject(Fault(FaultKind.DUPLICATE, topic=TOPIC))
    await feed.run(1.5)
    assert _resyncs("sequence_gap") == before + 1  # C-13.6 #3: duplicate -> resync
    feed.paused.add("BTCUSDT")
    await feed.run(0.2)
    assert rig.book_phase() is BookPhase.LIVE
    assert rig.book_levels() == rig.ex.books[TOPIC].levels()
