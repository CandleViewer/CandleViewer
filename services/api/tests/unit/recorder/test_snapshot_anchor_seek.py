"""#2223 replay seek over a recorded day: an anchor at every `snapshot_interval_s` boundary.

A synthetic, deterministic 200-depth book whose last applied delta is half a second before each
tick, driven by a fake clock and ticked once a second as the recorder runtime does, is anchored
through the real `StreamWriter` lane. The flushed `orderbook_snapshots` rows are mapped by the
storage mapper every tier shares (`event_from_row`) into an in-memory hot tier, and the replay
merge's own `anchor_at` (E26-T04) is asked at every boundary of the day. A resync stretch shows a
skipped anchor: counted, no gap row, and the seek falls back to the previous anchor (§13.7).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import BookLevel, BookSnapshot
from candleviewer.recorder.metrics import recorder_anchor_skipped_total
from candleviewer.recorder.snapshot_anchors import NoAnchor, SnapshotAnchors
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import RecordedBookSnapshot, event_from_row
from tests.unit.recorder._writer_helpers import FakeClock, make_writer
from tests.unit.replay._events import SECOND, SYM, T0, Harness, request

INTERVAL_S = 60
DAY_S = 86_400
#: The book is resyncing from 05:00:30 to 05:03:30: the 05:01, 05:02 and 05:03 anchors are skipped.
RESYNC_S = (5 * 3_600 + 30, 5 * 3_600 + 210)


class SyntheticBook:
    """`AnchorBooks` over a deterministic book that moves once a second with the clock."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock, self._t0 = clock, clock.t

    def offset_s(self) -> int:
        return int(self._clock.t - self._t0)

    def anchor(self, symbol: str) -> BookSnapshot | NoAnchor:
        s = self.offset_s()
        if RESYNC_S[0] <= s < RESYNC_S[1]:
            return "not_live"
        ts = T0 + s * SECOND - SECOND // 2  # the last applied delta, half a second ago
        mid = 650_000 + s % 97
        return BookSnapshot(
            event_id=EventId(UUID(int=s + 1)), ts_event=ts, ts_ingest=ts, source="live",
            symbol=symbol, depth=200, update_id=s, cross_seq=s * 10, ts_match=ts,
            reason="subscribe",
            bids=tuple(_lv(mid - 1 - i, i + 1) for i in range(200)),
            asks=tuple(_lv(mid + 1 + i, i + 1) for i in range(200)),
        )  # fmt: skip


def _lv(ticks: int, qty: int) -> BookLevel:
    return BookLevel(price=Decimal(ticks) / 10, qty=Decimal(qty), price_ticks=ticks)


async def test_seek_finds_an_anchor_at_most_one_interval_old_at_every_boundary_of_a_day(
    tmp_path: Path,
) -> None:
    writer, sink, store, _events, clock = await make_writer(tmp_path, env="live")
    writer.seed([SYM])
    book = SyntheticBook(clock)
    anchors = SnapshotAnchors(book, writer, interval_s=INTERVAL_S, clock=clock)
    skipped = recorder_anchor_skipped_total.labels(reason="not_live")
    before = skipped._value.get()

    await anchors.tick()  # the runtime's first tick arms the grid
    for _ in range(DAY_S):
        clock.advance(1)
        await anchors.tick()
    clock.advance(1)
    await writer.pump("orderbook_snapshots")
    await writer.flush_gaps()

    rows = sink.rows("orderbook_snapshots")
    harness = Harness(
        hot=[event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, row) for row in rows],
        req=request(start_us=0, end_us=DAY_S * SECOND, streams=(StreamKind.ORDERBOOK_SNAPSHOT,)),
    )
    merge = harness.merge()
    skipped_slots = {s // INTERVAL_S for s in range(*RESYNC_S) if s % INTERVAL_S == 0}
    late: list[int] = []
    for slot in range(1, DAY_S // INTERVAL_S + 1):
        at = T0 + slot * INTERVAL_S * SECOND
        anchor = await merge.anchor_at(SYM, at)
        assert anchor is not None, f"no anchor for the {slot * INTERVAL_S} s boundary"
        assert isinstance(anchor.payload, RecordedBookSnapshot)
        assert len(anchor.payload.bids) == len(anchor.payload.asks) == 200
        if at - anchor.ts_us > INTERVAL_S * SECOND:
            late.append(slot)

    assert len(rows) == DAY_S // INTERVAL_S - len(skipped_slots) == 1_437
    # Only the skipped boundaries fall back to an older anchor (the 05:00 one), within the
    # replay's one-hour lookback; every other boundary has one no more than an interval old.
    assert late == sorted(skipped_slots) == [301, 302, 303]
    assert skipped._value.get() == before + 3
    assert store.gaps == []
