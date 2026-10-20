"""`ReplayBooks` (E26-T03, 20 Sec.3.9): one session's replay-scoped book engines, the hook the
injector feeds book events through. The engine is the live one, unchanged; the wiring makes it
replay-safe: a gap waits for the next recorded snapshot (never the live feed), every recorded
snapshot is a full refresh it rebuilds from, a restart drops what it holds, and its clock is
replay time."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic, is_replay_env, replay_env
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot
from candleviewer.replay import ReplayEventRefused
from candleviewer.replay_wiring import ReplayBooks, build_replay_injector
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import RecordedBookSnapshot, RecordedEvent
from tests.unit.book._builders import lvl
from tests.unit.book._builders import snap as live_snap
from tests.unit.replay._events import SYM, T0, request, trade

SESSION = uuid.UUID("0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18")
BOOK = f"{replay_env(SESSION)}.md.{SYM}.book"
SNAPSHOTS = StreamKind.ORDERBOOK_SNAPSHOT


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
    engine = books.engine(SYM, 200)
    assert engine is not None and phase(books) is BookPhase.SNAPSHOT_PENDING
    assert (bus.statuses()[-1].state, bus.statuses()[-1].reason) == (
        BookPhase.DESYNCED,
        "replay_restart",
    )
    await books.apply(rdelta(700, 699, [lvl(995, 7)]))  # from before the jump: held
    await books.reset("replay_restart")  # waiting already: nothing more to say
    assert len([s for s in bus.statuses() if s.state is BookPhase.DESYNCED]) == 1
    await books.apply(rsnap(699, [lvl(990, 1)], [lvl(1010, 1)]))  # it chains onto 699, yet
    assert phase(books) is BookPhase.LIVE and engine.last_u == 699  # the held delta is gone
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
