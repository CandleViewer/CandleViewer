"""#410 scenario 3: a burst of 5 000 book updates a second is coalesced, not lost (§8; the chaos
row of 23 §16.4, "5 000 msg/s burst on one symbol; assert coalescing and no sequence break").
C-13.6 has no row for it: the nearest is #11, backpressure.

E17-T03's flag is on (`_server.flag_on`: coalescing is flag-on only). One client holds
`book.BTCUSDT.50` structured, and the hub gets 5 000 updates a second of virtual time from a
`Loop` (`_book`): a recorded stretch of the book, as the book publisher (#604) will send it. A tick
of 250 ms publishes its 1 250 updates in one go, moves the virtual clock, and waits until the
client holds every update published. So each window closes before the next tick's first update
arrives, and the frames are deterministic: the first update of a cold lane leaves alone (§8.6,
D12), the rest of its tick leaves as one window, and each later tick is one window of all its
updates. The tick is longer than the slowest window the book can get, its 50 ms throttle x4
(`saturated`, §8.3): the class follows RTT samples read on the virtual clock, so a `pong` that
crosses ticks can raise it (scenario 1 met that at 125 ms), and a window that outlasts its tick
waits for a clock the waiting tick never moves.

The client's frames are the disclosure the gateway owes: each after the first `coalesced`, with a
`coalesced_count` of the updates its window merged, the counts summing to what was published, `s`
contiguous, no snapshot but the first. After every tick its `Replica` equals the server's book (23
§16.4, unit: the coalescer equals applying every source update). The pacer's own series agree with
the frames, and nothing was dropped, closed or re-snapshotted. The 10 s run (50 000 updates) is in
the PR lane; the 60 s one (300 000), marked `harness`, is meant for the nightly job (wired in the
next #410 PR). The loop's own test, with no server, is the last: two laps from two places in the
recording, window and book equal at every update, and back where they began at the end of each.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from candleviewer.ws.metrics import (
    COALESCED_UPDATES,
    cv_ws_closes_total,
    cv_ws_conflated_total,
    cv_ws_overflow_total,
)
from candleviewer.ws.pacing import _MULTIPLIER
from candleviewer.ws.sequencing import SequencingHub, cv_ws_resync_total
from candleviewer.ws.topics import effective_throttle_ms, parse_topic
from tests.chaos.ws._book import LAP, BookTap, Delta, Loop, Replica, structured
from tests.chaos.ws._server import BOOK, DEPTH, SEED, SYM, Stack
from tests.unit.ws._seq_support import Conn, Source

pytestmark = pytest.mark.chaos

RATE = 5_000  # book updates a second of virtual time
TICK_S = 0.25
PER_TICK = round(RATE * TICK_S)
#: The client's §9.1 pings, on the virtual clock, well inside the 45 s of silence. A whole number of
#: ticks: no virtual timer then fires between two, and a window flushed off the tick grid would
#: leave the next tick's first update a leading edge again.
HEARTBEAT_S = 5.0
#: At import, so drift fails here, not as a 5 s timeout: the tick exceeds the slowest window (§8.3):
#: the topic's throttle as `sub_ok` reports it (a book's follows its depth) x the top class's.
assert effective_throttle_ms(parse_topic(BOOK), None) * max(_MULTIPLIER.values()) / 1000 < TICK_S
assert HEARTBEAT_S % TICK_S == 0
USER = uuid.UUID(int=0x401)


def series() -> dict[str, float]:
    """The series the burst is judged by, as `name{label}`: the pacer's conflation counters and
    `cv_ws_coalesced_updates`'s count and sum, and the counters that would say a client was shed
    (`cv_ws_overflow_total`), closed or re-snapshotted."""
    out: dict[str, float] = {}
    for metric in (
        cv_ws_conflated_total,
        cv_ws_overflow_total,
        cv_ws_closes_total,
        cv_ws_resync_total,
    ):
        for family in metric.collect():
            for sample in family.samples:
                if sample.name.endswith("_total"):
                    (label,) = sample.labels.values()
                    out[f"{sample.name}{{{label}}}"] = sample.value
    cumulative, total = COALESCED_UPDATES.reading()
    out["cv_ws_coalesced_updates_count"], out["cv_ws_coalesced_updates_sum"] = cumulative[-1], total
    return out


def moved(before: dict[str, float]) -> dict[str, float]:
    """What `series()` has gained since `before`: only the series that changed."""
    return {k: v - before.get(k, 0.0) for k, v in series().items() if v != before.get(k, 0.0)}


@pytest.mark.parametrize(
    "seconds", [10, pytest.param(60, marks=pytest.mark.harness)], ids=["10s", "60s"]
)
async def test_s3_a_burst_of_5000_book_updates_a_second_is_coalesced_not_lost(
    stack_on: Stack, seconds: int
) -> None:
    feed, tap = Loop(stack_on.source), BookTap()
    c = stack_on.client(await stack_on.sessions.mint(str(USER)), SEED)
    c.heartbeat_s, c.on_data = HEARTBEAT_S, tap
    await c.start(structured(BOOK)).until(lambda: c.synced, "first snapshot")
    ticks, publishing, before = seconds * RATE // PER_TICK, 0.0, series()
    began = time.perf_counter()
    for tick in range(1, ticks + 1):
        spent = time.perf_counter()
        for _ in range(PER_TICK):
            assert feed.publish(stack_on.hub) == 1, "an update the subscription did not take"
        publishing += time.perf_counter() - spent
        await stack_on.clock.advance(TICK_S)
        await c.until(
            lambda: tap.updates == feed.published, f"tick {tick}: every update in a frame"
        )
        assert tap.replica.matches(feed.book, DEPTH), f"tick {tick}: the replica left the book"
    took = time.perf_counter() - began

    published, frames = feed.published, len(tap.deltas)
    assert published == seconds * RATE and tap.updates == published
    assert tap.deltas == [
        Delta(2, False, None),  # s 1 was the snapshot: the cold lane's first update, no disclosure
        Delta(3, True, PER_TICK - 1),  # the others of its tick, as one window
        *(Delta(s, True, PER_TICK) for s in range(4, ticks + 3)),  # then a window a tick
    ]
    assert c.gaps == [] and tap.replica.gaps == 0 and c.closes == [] and c.sessions == 1
    assert moved(before) == {
        "cv_ws_conflated_total{book}": published - frames,  # n - 1 for each window of n
        "cv_ws_coalesced_updates_count": frames - 1,  # one for each frame but the leading edge
        "cv_ws_coalesced_updates_sum": published - 1,
    }
    print(
        f"#410 s3 {seconds} s: {published} updates in {frames} frames (x{published / frames:.0f}), "
        f"{ticks} windows of {PER_TICK}, {len(c.system('connection_quality'))} class notices; "
        f"{took:.2f} s of wall time, {1e6 * publishing / published:.1f} us of it an update"
    )


class Quiet(Conn):
    """A `Conn` that does not validate each frame against the schemas (about 3 ms a frame)."""

    def push(self, frame: dict[str, Any]) -> None:
        self.out.append(frame)


@pytest.mark.parametrize(
    ("sym", "start"), [(SYM, 0), ("ETHUSDT", LAP)], ids=["from_the_start", "a_lap_in"]
)
def test_s3_loop_feed_returns_to_its_start_window_every_lap_and_matches_the_server_book(
    sym: str, start: int
) -> None:
    source, hub, replica = Source(), SequencingHub(), Replica()
    feed = Loop(source, sym, start)
    conn = Quiet(source)
    hub.register(conn.authz, conn.emitter)
    conn.sub(structured(feed.ch))
    for frame in conn.take():  # the snapshot of the book as the lap begins
        replica.feed(frame)
    opened = dict(replica.bids), dict(replica.asks)
    assert len(opened[0]) == len(opened[1]) == DEPTH and replica.matches(feed.book, DEPTH)
    for lap in range(2):
        for n in range(1, len(feed) + 1):
            assert feed.publish(hub) == 1
            (frame,) = conn.take()
            replica.feed(frame)
            assert replica.matches(feed.book, DEPTH), f"lap {lap}, update {n}"
            if n == len(feed) - 1:  # the bridge has something to take back
                assert (replica.bids, replica.asks) != opened
        assert (replica.bids, replica.asks) == opened, f"lap {lap}: the window did not return"
        assert (feed.book.bids, feed.book.asks) == feed.opening, f"lap {lap}: nor the book"
    assert replica.gaps == 0
