"""Read-ahead never changes what a replay emits (E26-T02 test plan: Hypothesis properties).

The recordings, the key they are sorted by and the expected sequence are those of
`test_merge_properties.py`: 3 symbols x 4 streams with equal timestamps and equal `seq` across
them, gap markers on the same instants, re-exported copies, any storage order, read windows of
1-64 µs, row caps of 1-8. On top of them, a read-ahead of 1-8 queue slots, batches of 1-8 events
and a consumer that pauses a different number of turns after each item, so the producer runs
ahead, parks and resumes at points the generator picks. The result must equal the oracle exactly:
no row dropped, repeated or moved, whatever the slots, batch and pace; and the queue never holds
more than `slots x batch` events.
"""

from __future__ import annotations

import asyncio

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.replay import ReadAheadConfig, ReplayItem, ReplaySource
from candleviewer.replay.merge import row_bytes
from tests.unit.replay._events import Harness, digest
from tests.unit.replay._source import BOUND_S
from tests.unit.replay.test_merge_properties import (
    SNAPSHOTS,
    STREAMS,
    SYMBOLS,
    Recording,
    recordings,
    window_of,
)

READAHEAD_BYTES = 1 << 20


def config_for(rec: Recording, *, window_us: int, slots: int, batch: int) -> ReadAheadConfig:
    """`slots` queue slots of `batch` events: the read-ahead holds `slots + 2` batches (the
    producer's and the consumer's are the two more), and the cursors' share is the one slice 5's
    property gives the merge, so each read is capped at `rec.cap` rows."""
    share = rec.cap * row_bytes(SNAPSHOTS, 1) * len(SYMBOLS) * len(STREAMS)
    return ReadAheadConfig(
        window_us=window_us,
        max_window_us=64,
        readahead_events=(slots + 2) * batch,
        batch_events=batch,
        readahead_bytes=READAHEAD_BYTES,
        memory_ceiling_bytes=READAHEAD_BYTES + share,
        io_timeout_s=5.0,
    )


def replay(
    harness: Harness, config: ReadAheadConfig, *, slots: int, pauses: list[int]
) -> list[ReplayItem]:
    async def run() -> list[ReplayItem]:
        got: list[ReplayItem] = []
        async with (
            asyncio.timeout(BOUND_S),
            ReplaySource(harness.req, harness.tiers, config=config) as source,
        ):
            async for item in source:
                assert source.buffered_events <= slots * config.batch_events
                got.append(item)
                for _ in range(pauses[len(got) % len(pauses)]):
                    await asyncio.sleep(0)
        return got

    return asyncio.run(run())


@given(
    recording=recordings(),
    data=st.data(),
    window_us=st.integers(1, 64),
    slots=st.integers(1, 8),
    batch=st.integers(1, 8),
    pauses=st.lists(st.integers(0, 3), min_size=1, max_size=6),
)
def test_any_read_ahead_replays_the_ruled_total_order_with_its_markers_exactly_once(
    recording: Recording,
    data: st.DataObject,
    window_us: int,
    slots: int,
    batch: int,
    pauses: list[int],
) -> None:
    """The slice-5 order property through the source: whichever tier served the rows and in
    whatever order storage held them, and however deep the read-ahead and slow the consumer."""
    cold_rows = data.draw(st.permutations(recording.rows + recording.copies))
    hot_rows = data.draw(st.permutations(recording.rows))
    cold = Harness(
        cold=cold_rows, gaps=recording.gaps, req=window_of(recording, "auto"), archived=True
    )
    hot = Harness(hot=hot_rows, gaps=recording.gaps, req=window_of(recording, "questdb"))
    config = config_for(recording, window_us=window_us, slots=slots, batch=batch)

    got_cold = replay(cold, config, slots=slots, pauses=pauses)
    got_hot = replay(hot, config, slots=slots, pauses=pauses)

    assert got_cold == recording.expected()
    assert got_hot == recording.expected()
    assert digest(got_cold) == digest(got_hot)
    assert cold.hot.reads == 0 and hot.cold.reads == 0
