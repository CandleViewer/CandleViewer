"""BookEngine Gherkin scenarios (E08-S05) without the chart (plain path)."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.book.models import BookDesyncEvent, BookPhase, BookStatus
from candleviewer.book.resync import BREAKER_MAX, BUFFER_BOUND, BookEngine
from candleviewer.book.state import BookState
from candleviewer.book.tiers import TieredBook
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, StreamInvalidated, Topic
from candleviewer.exchange.base.models import BookDelta, BookSnapshot

from ._builders import delta, lvl, snap


class _Harness:
    def __init__(self) -> None:
        self.out: list[object] = []
        self.resubs = 0
        self.t = 0

    async def publish(self, ev: object) -> None:
        self.out.append(ev)

    async def resub(self) -> None:
        self.resubs += 1

    def engine(self, depth: int = 200, muted: bool = False) -> BookEngine:
        e = BookEngine(
            symbol="BTCUSDT", depth=depth, publish=self.publish, resubscribe=self.resub,
            now_us=lambda: self.t,
        )  # fmt: skip
        e.muted = muted
        return e

    def books(self) -> list[object]:
        return [o for o in self.out if not isinstance(o, BookStatus | BookDesyncEvent)]


async def test_snapshot_then_deltas_reaches_live_before_publishing() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    assert e.phase is BookPhase.SNAPSHOT_PENDING and h.out == [] and h.resubs == 1
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    await e.on_event(delta(11, 10, [lvl(99, 2)]))
    assert e.phase is BookPhase.LIVE
    assert isinstance(h.out[0], BookSnapshot) and isinstance(h.out[-1], BookDelta)
    assert e.book is not None and e.book.as_dicts()[0] == {99: Decimal(2)}


async def test_sequence_break_invalidates_and_requests_snapshot() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    n = len(h.books())
    await e.on_event(delta(13, 12, [lvl(98, 1)]))
    assert e.phase is BookPhase.SNAPSHOT_PENDING and e.book is None and h.resubs == 2
    assert len(h.books()) == n  # the gapped delta was never published
    st = [o for o in h.out if isinstance(o, BookStatus)][-1]
    assert st.state is BookPhase.DESYNCED and st.reason == "sequence_gap"
    assert st.last_good_ts_us is not None and e.resync_count == 1


async def test_buffered_deltas_replayed_after_snapshot_seq() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    for d in (
        delta(9, 8, [lvl(90, 9)]),
        delta(11, 10, [lvl(98, 3)]),
        delta(12, 11, [], [lvl(101, 0)]),
    ):
        await e.on_event(d)
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1), lvl(102, 1)]))
    ref = BookState.from_levels(200, [lvl(99, 1)], [lvl(101, 1), lvl(102, 1)])
    ref.apply([lvl(98, 3)], [])
    ref.apply([], [lvl(101, 0)])
    assert e.book is not None and e.book.as_dicts() == ref.as_dicts() and e.last_u == 12


async def test_buffer_gap_after_snapshot_resyncs() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    await e.on_event(delta(13, 12))
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    assert e.phase is BookPhase.SNAPSHOT_PENDING and h.resubs == 2


async def test_buffer_is_bounded() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    for i in range(BUFFER_BOUND + 1):
        await e.on_event(delta(i + 2, i + 1))
    assert h.resubs == 2 and e.resync_count == 1


async def test_crossed_delta_is_treated_as_desync_not_clamped() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    await e.on_event(delta(11, 10, [lvl(105, 1)]))
    assert e.phase is BookPhase.SNAPSHOT_PENDING
    assert [o for o in h.out if isinstance(o, BookStatus)][-1].reason == "crossed"


async def test_server_reset_snapshot_while_live_resyncs() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    await e.on_event(snap(1, [lvl(99, 1)], [lvl(101, 1)]))
    assert e.phase is BookPhase.SNAPSHOT_PENDING


async def test_bad_snapshot_and_delta_when_init_ignored() -> None:
    h = _Harness()
    e = h.engine()
    await e.on_event(delta(2, 1))  # INIT: dropped
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(99, 1)]))  # crossed snapshot
    assert e.phase is BookPhase.SNAPSHOT_PENDING and h.books() == []


async def test_resync_breaker_reports_degraded() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    for _ in range(BREAKER_MAX + 1):
        await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
        await e.on_event(delta(99, 50))
    assert e.degraded


async def test_snapshot_timeout_detection() -> None:
    h = _Harness()
    e = h.engine()
    await e.start()
    assert not e.check_timeout(5)
    h.t = 5
    assert e.check_timeout(5)


async def test_depth_tier_change_is_atomic() -> None:
    h = _Harness()
    tb = TieredBook(lambda d, m: h.engine(d, m), depth=200)
    await tb.start()
    await tb.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)], depth=200))
    await tb.change_depth(50)
    await tb.on_event(delta(11, 10, [lvl(98, 1)], depth=200))  # old tier still live
    seen = len(h.books())
    await tb.on_event(snap(5, [lvl(97, 4)], [lvl(103, 4)], depth=50))
    swapped = h.books()[seen:]
    assert tb.active.depth == 50 and tb.warming is None
    assert len(swapped) == 1 and isinstance(swapped[0], BookSnapshot) and swapped[0].depth == 50
    await tb.on_event(delta(12, 11, [lvl(96, 1)], depth=200))  # retired tier
    await tb.on_event(delta(6, 5, [lvl(96, 1)], depth=50))
    assert all(getattr(o, "depth", 50) == 50 for o in h.books()[seen:])
    await tb.change_depth(50)  # no-op


async def test_consumer_stall_gets_invalidated_marker_not_skipped_delta() -> None:
    bus = Bus()
    sub = bus.subscribe("dom", "demo.md.*.book", QueuePolicy.INVALIDATE_ON_FULL, maxsize=2)
    topic = Topic(env="demo", domain="md", symbol="BTCUSDT", detail="book")

    async def pub(ev: object) -> None:
        if not isinstance(ev, BookStatus):
            await bus.publish(topic, ev)

    async def noop() -> None: ...

    e = BookEngine(symbol="BTCUSDT", depth=200, publish=pub, resubscribe=noop, now_us=lambda: 0)
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    for u in range(11, 14):
        await e.on_event(delta(u, u - 1, [lvl(99, u)]))
    assert isinstance(sub.get_nowait(), StreamInvalidated)
    await e.publish_current("resync")  # consumer resyncs from a fresh snapshot
    fresh = [sub.get_nowait() for _ in range(sub.qsize())][-1]
    assert isinstance(fresh, BookSnapshot) and fresh.update_id == 13


async def test_desync_event_resync_count_is_the_lifetime_count_as_book_status() -> None:
    """F4: `BookDesyncEvent.resync_count` is the engine's lifetime count, the one `BookStatus`
    carries, not the breaker window's length (which forgets incidents past 60 s)."""
    h = _Harness()
    e = h.engine()
    e.incidents = True
    await e.start()
    for u, t in ((10, 0), (20, 120_000_000)):  # the second incident is past the breaker window
        h.t = t
        await e.on_event(snap(u, [lvl(99, 1)], [lvl(101, 1)]))
        await e.on_event(delta(u + 3, u + 2))
    events = [o for o in h.out if isinstance(o, BookDesyncEvent)]
    status = [o for o in h.out if isinstance(o, BookStatus)][-1]
    assert [ev.resync_count for ev in events] == [1, 2] == [1, status.resync_count]
