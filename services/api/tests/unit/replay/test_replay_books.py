"""`ReplayBooks` (E26-T03, 20 Sec.3.9): one session's replay-scoped book engines, the hook the
injector feeds book events through. The engine is the live one, unchanged; the wiring makes it
replay-safe: a gap waits for the next recorded snapshot (never the live feed), every recorded
snapshot is a full refresh it rebuilds from, a restart drops what it holds, a reset starts the
book afresh (never `degraded` by resets), and its clock is replay time."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, is_replay_env, replay_env
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot
from candleviewer.replay import ReplayEventRefused, ReplayInjector
from candleviewer.replay_wiring import LIVE_EVENT_MODELS, ReplayBooks, build_replay_injector
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    RecordedBookSnapshot,
    RecordedBookUpdate,
    RecordedEvent,
)
from tests.unit.book._builders import lvl
from tests.unit.book._builders import snap as live_snap
from tests.unit.replay._events import SECOND, SYM, T0, request, trade

SESSION = uuid.UUID("0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18")
BOOK = f"{replay_env(SESSION)}.md.{SYM}.book"
SNAPSHOTS = StreamKind.ORDERBOOK_SNAPSHOT
DELTAS = StreamKind.ORDERBOOK_DELTA
TICK = Decimal("0.5")


class LoggingBus(Bus):
    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[Topic, object]] = []

    async def publish(self, topic: Topic, event: object) -> None:
        self.log.append((topic, event))
        await super().publish(topic, event)

    def statuses(self) -> list[BookStatus]:
        return [e for _, e in self.log if isinstance(e, BookStatus)]


def rsnap(u: int, bids: list[BookLevel], asks: list[BookLevel], *, ts: int = 0) -> BookSnapshot:
    return BookSnapshot(
        event_id=EventId(uuid.UUID(int=u)),
        ts_event=ts or T0 + u,
        ts_ingest=ts or T0 + u,
        source="replay",
        symbol=SYM,
        depth=200,
        bids=tuple(bids),
        asks=tuple(asks),
        update_id=u,
        cross_seq=u,
        ts_match=ts or T0 + u,
        reason="resync",
    )


def rdelta(
    u: int, prev: int, bids: Sequence[BookLevel] = (), asks: Sequence[BookLevel] = ()
) -> BookDelta:
    return BookDelta(
        event_id=EventId(uuid.UUID(int=u)),
        ts_event=T0 + u,
        ts_ingest=T0 + u,
        source="replay",
        symbol=SYM,
        depth=200,
        bids=tuple(bids),
        asks=tuple(asks),
        update_id=u,
        prev_update_id=prev,
        cross_seq=u,
        ts_match=T0 + u,
    )


def phase(books: ReplayBooks) -> BookPhase | None:
    """The book's phase, read afresh (an engine's phase moves under every `apply`)."""
    engine = books.engine(SYM, 200)
    return None if engine is None else engine.phase


def book_of(
    books: ReplayBooks,
) -> tuple[list[tuple[Decimal, Decimal]], list[tuple[Decimal, Decimal]]]:
    engine = books.engine(SYM, 200)
    assert engine is not None
    view = engine.live_snapshot()
    assert view is not None
    return [(lv.price, lv.qty) for lv in view.bids], [(lv.price, lv.qty) for lv in view.asks]


async def test_the_replay_books_own_status_events_carry_source_replay() -> None:
    """The engine stamps its `BookStatus` events `live` (`book/resync.py`); on the replay topic
    they must read `replay`, as every other replayed event does (24 Sec.2.9)."""
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    await books.apply(rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]))
    await books.reset("replay_restart")
    await books.apply(rsnap(600, [lvl(980, 4)], [lvl(1020, 5)]))
    statuses = bus.statuses()
    assert statuses and all(status.source == "replay" for status in statuses)
    assert all(getattr(event, "source", "replay") == "replay" for _, event in bus.log)


async def test_a_recorded_snapshot_while_live_rebuilds_the_book_without_a_desync() -> None:
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    await books.apply(rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]))
    await books.apply(rdelta(501, 500, [lvl(995, 2)]))
    await books.apply(rsnap(600, [lvl(980, 4)], [lvl(1020, 5)]))  # e.g. a periodic snapshot
    engine = books.engine(SYM, 200)
    assert engine is not None and engine.phase is BookPhase.LIVE and engine.last_u == 600
    assert book_of(books) == ([(Decimal("98"), Decimal(4))], [(Decimal("102"), Decimal(5))])
    assert all(s.state is BookPhase.LIVE for s in bus.statuses())  # never "book resyncing"
    assert engine.resync_count == 0
    await books.apply(rdelta(601, 600, [lvl(981, 1)]))  # and the deltas after it apply
    assert engine.last_u == 601


async def test_a_gap_waits_for_the_next_recorded_snapshot_and_never_reaches_the_live_feed() -> None:
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    await books.apply(rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]))
    published = len(bus.log)
    await books.apply(rdelta(503, 502, [lvl(991, 1)]))  # 501 and 502 were not recorded
    engine = books.engine(SYM, 200)
    assert engine is not None and phase(books) is BookPhase.SNAPSHOT_PENDING
    [desync] = [s for s in bus.statuses() if s.state is BookPhase.DESYNCED]
    assert desync.reason == "sequence_gap"
    await books.apply(rdelta(504, 503, [lvl(992, 1)]))  # held back, never published
    assert [e for _, e in bus.log[published:] if isinstance(e, BookDelta)] == []
    await books.apply(rsnap(510, [lvl(990, 3)], [lvl(1010, 3)]))
    assert phase(books) is BookPhase.LIVE and engine.last_u == 510
    assert {topic.key for topic, _ in bus.log} == {BOOK}  # nothing but the session's topic


async def test_reset_takes_a_live_book_out_of_live_and_held_deltas_never_outlive_it() -> None:
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    await books.apply(rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]))
    await books.reset("replay_restart")
    assert phase(books) is BookPhase.SNAPSHOT_PENDING
    assert (bus.statuses()[-1].state, bus.statuses()[-1].reason) == (
        BookPhase.DESYNCED,
        "replay_restart",
    )
    await books.apply(rdelta(700, 699, [lvl(995, 7)]))  # from before the jump: held
    await books.reset("replay_restart")  # waiting already: nothing more to say
    assert len([s for s in bus.statuses() if s.state is BookPhase.DESYNCED]) == 1
    await books.apply(rsnap(699, [lvl(990, 1)], [lvl(1010, 1)]))  # it chains onto 699, yet
    engine = books.engine(SYM, 200)  # the held delta is gone
    assert engine is not None and engine.phase is BookPhase.LIVE and engine.last_u == 699
    assert book_of(books) == ([(Decimal("99"), Decimal(1))], [(Decimal("101"), Decimal(1))])


async def test_a_symbol_reset_takes_only_that_symbols_book_out_of_live() -> None:
    """A recording gap on one symbol's book stream (the run's `reset_book`) leaves every other
    symbol's replay book LIVE."""
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    await books.apply(rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]))
    other = rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]).model_copy(update={"symbol": "ETHUSDT"})
    await books.apply(other)
    await books.reset("recording_gap", symbol=SYM)
    eth = books.engine("ETHUSDT", 200)
    assert phase(books) is BookPhase.SNAPSHOT_PENDING
    assert eth is not None and eth.phase is BookPhase.LIVE
    [desync] = [s for s in bus.statuses() if s.state is BookPhase.DESYNCED]
    assert (desync.symbol, desync.reason) == (SYM, "recording_gap")


async def test_a_book_opened_while_a_reset_is_held_up_leaves_the_reset_whole() -> None:
    """A reset awaits each book's consumers (bus backpressure), so another symbol's first event
    can open a book meanwhile: the reset walks the books it found, and the new one stays LIVE."""
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    await books.apply(rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]))
    slow = bus.subscribe("slow", BOOK, QueuePolicy.NEVER_DROP, maxsize=1)
    slow.queue.put_nowait("unread")
    resetting = asyncio.ensure_future(books.reset("replay_restart"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not resetting.done()  # held by `slow`, announcing the book left LIVE
    other = rsnap(500, [lvl(990, 1)], [lvl(1010, 1)]).model_copy(update={"symbol": "ETHUSDT"})
    await books.apply(other)
    assert slow.get_nowait() == "unread"
    await resetting
    eth = books.engine("ETHUSDT", 200)
    assert phase(books) is BookPhase.SNAPSHOT_PENDING
    assert eth is not None and eth.phase is BookPhase.LIVE


def recorded_snapshot(offset_us: int, update_id: int) -> RecordedEvent:
    """A recorded full refresh of the book, one level a side."""
    sides = ((Decimal("100"), Decimal("1")),), ((Decimal("100.5"), Decimal("1")),)
    payload = RecordedBookSnapshot(200, update_id, None, *sides)
    key = (update_id, 200, -1)
    return RecordedEvent(T0 + offset_us, update_id, SYM, SNAPSHOTS, key, payload)


def recorded_update(offset_us: int, update_id: int) -> RecordedEvent:
    """One regrouped book update; recorded before E26-T03, it chains onto `update_id - 1`."""
    payload = RecordedBookUpdate(200, update_id, None, ((Decimal("100"), Decimal("2")),), ())
    return RecordedEvent(T0 + offset_us, update_id, SYM, DELTAS, (update_id, 200), payload)


def replayed(bus: Bus) -> tuple[ReplayBooks, ReplayInjector]:
    """A session's injector over its own `ReplayBooks`, both on `bus`."""
    books = ReplayBooks(bus, SESSION)
    injector = ReplayInjector(
        session_id=SESSION,
        request=request(streams=(StreamKind.TRADES, DELTAS, SNAPSHOTS)),
        tick_sizes={SYM: TICK},
        bus=bus,
        books=books,
        models=LIVE_EVENT_MODELS,
    )
    return books, injector


async def holds_updates_until_a_snapshot(
    bus: LoggingBus, books: ReplayBooks, injector: ReplayInjector, *, last_u: int, at: int
) -> None:
    """After a reset the book holds back even an update that chains onto the book it had, and
    publishes nothing until the next recorded snapshot rebuilds it."""
    published = len(bus.log)
    await injector.deliver(recorded_update(at, last_u + 1))
    assert phase(books) is BookPhase.SNAPSHOT_PENDING and len(bus.log) == published
    await injector.deliver(recorded_snapshot(at + 1, last_u + 10))
    await injector.deliver(recorded_update(at + 2, last_u + 11))
    assert [type(e) for _, e in bus.log[published:]] == [BookSnapshot, BookStatus, BookDelta]
    assert phase(books) is BookPhase.LIVE and not bus.statuses()[-1].degraded


async def test_ten_loop_restarts_never_leave_the_replay_book_degraded() -> None:
    """The engine's resync breaker counts desyncs over a minute of its clock, replay time, which
    a loop wrap rewinds: an engine kept across 30 s passes forgets none, so the sixth wrap read
    `degraded` for the rest of the session. A restart is a control action, not a data fault:
    the book starts afresh, and still tells its consumers it left LIVE."""
    bus = LoggingBus()
    books, injector = replayed(bus)
    for _ in range(10):  # a 30 s pass: a snapshot, an update, then the wrap back to its start
        await injector.deliver(recorded_snapshot(SECOND, 10))
        await injector.deliver(recorded_update(30 * SECOND, 11))
        await injector.restart(ordinal=0)
    desyncs = [s for s in bus.statuses() if s.state is BookPhase.DESYNCED]
    assert [s.reason for s in desyncs] == ["replay_restart"] * 10
    assert not any(s.degraded for s in bus.statuses())
    await holds_updates_until_a_snapshot(bus, books, injector, last_u=11, at=SECOND)


async def test_ten_recording_gaps_never_leave_the_replay_book_degraded() -> None:
    """Ten gaps on the book stream within a minute of replay time (the run's `reset_book`): a
    gap is a control action too, never a resync the breaker counts."""
    bus = LoggingBus()
    books, injector = replayed(bus)
    for n in range(1, 11):  # a snapshot every second, each followed by a gap
        await injector.deliver(recorded_snapshot(n * SECOND, 10 * n))
        await injector.reset_book(SYM)
    desyncs = [s for s in bus.statuses() if s.state is BookPhase.DESYNCED]
    assert [s.reason for s in desyncs] == ["recording_gap"] * 10
    assert not any(s.degraded for s in bus.statuses())
    await holds_updates_until_a_snapshot(bus, books, injector, last_u=100, at=11 * SECOND)


async def test_a_gap_at_a_split_delta_resyncs_and_never_presents_the_partial_book() -> None:
    """C-2.5 / C-2.14 (the coordinator's 2026-10-31 ruling on #481): a delta the recorder's WAL
    budget split leaves its first levels written and a `backpressure_drop` gap at the same
    `exch_ts`. The gap is a resync point: the book leaves LIVE, serves no view built from the
    partial delta, and holds the rest until the next recorded snapshot."""
    bus = LoggingBus()
    books, injector = replayed(bus)
    await injector.deliver(recorded_snapshot(SECOND, 10))
    await injector.deliver(recorded_update(2 * SECOND, 11))
    await injector.deliver(recorded_update(3 * SECOND, 12))  # the written part of the split delta
    engine = books.engine(SYM, 200)
    assert engine is not None and engine.phase is BookPhase.LIVE
    await injector.reset_book(SYM)  # the gap, starting at the split message's exch_ts
    assert engine.phase is BookPhase.SNAPSHOT_PENDING
    assert engine.live_snapshot() is None and engine.anchor_snapshot() is None
    assert (bus.statuses()[-1].state, bus.statuses()[-1].reason) == (
        BookPhase.DESYNCED,
        "recording_gap",
    )
    await holds_updates_until_a_snapshot(bus, books, injector, last_u=12, at=4 * SECOND)


async def test_the_replay_book_reads_replay_time_never_the_wall_clock() -> None:
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    await books.apply(rsnap(500, [lvl(990, 1)], [lvl(1010, 1)], ts=T0 + 42))
    [live] = bus.statuses()
    assert live.ts_us == T0 + 42 and live.last_good_ts_us == T0 + 42


async def test_the_replay_book_refuses_a_live_event() -> None:
    books = ReplayBooks(LoggingBus(), SESSION)
    with pytest.raises(ReplayEventRefused):
        await books.apply(live_snap(10, [lvl(990, 1)], [lvl(1010, 1)]))
    assert books.engine(SYM, 200) is None


async def test_the_built_injector_publishes_trades_and_books_in_one_namespace() -> None:
    bus = LoggingBus()
    streams = (StreamKind.TRADES, SNAPSHOTS)
    injector = build_replay_injector(
        session_id=SESSION,
        request=request(streams=streams),
        tick_sizes={SYM: Decimal("0.5")},
        bus=bus,
    )
    sides = ((Decimal("100"), Decimal("1")),), ((Decimal("100.5"), Decimal("1")),)
    book = RecordedBookSnapshot(200, 10, None, *sides)
    await injector.deliver(RecordedEvent(T0 + 1, 10, SYM, SNAPSHOTS, (10, 200, -1), book))
    await injector.deliver(trade(2))
    topics = {topic.key for topic, _ in bus.log}
    assert topics == {BOOK, f"{replay_env(SESSION)}.md.{SYM}.trade"}
    assert all(is_replay_env(topic.env) for topic, _ in bus.log)
