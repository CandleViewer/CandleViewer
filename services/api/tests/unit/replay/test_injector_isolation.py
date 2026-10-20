"""AC 4 "Replay events cannot reach live state" (E26-T03; threat model RP-T06, RP-S08).

A live `BookEngine` for BTCUSDT holds a live book while a replay session for BTCUSDT re-emits its
recorded book and trades on the same bus. The live book's state and its topics stay as they were,
the live consumers (a recorder-shaped subscriber per live topic, and a live bars set standing for
every bars-fed consumer such as the rule engine) see nothing, and every replayed event carries
`source="replay"` on a `replay-<uuid>` topic. The same bars code, subscribed to the session's
namespace, builds bars from the replayed trades (P2). The `source` invariant is then attacked: a
frozen field no copy drops, never on a live topic, and no session publishes into another's
namespace."""

from __future__ import annotations

import copy
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.bars.builder_set import BarBuilderSet
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.models import BarSpec
from candleviewer.bars.state_store import StateStore
from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, is_replay_env, replay_env
from candleviewer.domain.events import DomainEvent, MarketEvent
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import BookDelta, BookSnapshot, TradeEvent
from candleviewer.replay import UNBOUNDED, RegroupedStream, ReplayClock, ReplayInjector
from candleviewer.replay_wiring import LIVE_EVENT_MODELS, ReplayBooks, build_replay_injector
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedTrade,
)
from tests.unit.bars._set_harness import Clock, settle
from tests.unit.bars._set_harness import RecordingSink as BarSink
from tests.unit.book._builders import delta as live_delta
from tests.unit.book._builders import lvl
from tests.unit.book._builders import snap as live_snap
from tests.unit.replay._events import SECOND, SYM, T0, request
from tests.unit.replay._playback import ListStream, RecordingObserver
from tests.unit.replay._time import FakeTime

SESSION = uuid.UUID("0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18")
OTHER = uuid.UUID("5d0e7b2c-4f18-4c8e-9a61-0b7c5e1a3f2d")
TICK = Decimal("0.1")  # the grid `tests/unit/book/_builders.py` prices the live book on
REEMITTED = (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA, StreamKind.ORDERBOOK_SNAPSHOT)
T3 = BarSpec(kind="tick", tick_count=3)


class LoggingBus(Bus):
    """The real bus, also noting every `(topic, event)` published."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[Topic, object]] = []

    async def publish(self, topic: Topic, event: object) -> None:
        self.log.append((topic, event))
        await super().publish(topic, event)


def px(text: str) -> Decimal:
    return Decimal(text)


def book_row(offset_us: int, update_id: int, side: str, price: str, size: str) -> RecordedEvent:
    """One recorded `orderbook_deltas` row (a level), as the readers return it before E26-T03."""
    payload = RecordedBookDelta(200, side, px(price), px(size), update_id, None)
    key = (update_id, 200, side, px(price))
    return RecordedEvent(T0 + offset_us, update_id, SYM, StreamKind.ORDERBOOK_DELTA, key, payload)


def book_snapshot(offset_us: int, update_id: int) -> RecordedEvent:
    payload = RecordedBookSnapshot(
        200, update_id, None, ((px("100.0"), px("1")),), ((px("100.2"), px("1")),)
    )
    key = (update_id, 200, -1)
    return RecordedEvent(
        T0 + offset_us, update_id, SYM, StreamKind.ORDERBOOK_SNAPSHOT, key, payload
    )


def tape(offset_us: int, price: str, side: str, n: int) -> RecordedEvent:
    payload = RecordedTrade(side, px(price), px("0.5"), f"r{n}", None)
    return RecordedEvent(T0 + offset_us, n, SYM, StreamKind.TRADES, (f"r{n}",), payload)


#: A recorded minute of BTCUSDT: a snapshot, two book updates (three rows), three trades.
RECORDING: list[RecordedEvent] = [
    book_snapshot(1 * SECOND, 500),
    book_row(2 * SECOND, 501, "ask", "100.2", "0"),
    book_row(2 * SECOND, 501, "ask", "100.3", "2"),
    book_row(2 * SECOND, 501, "bid", "100.1", "3"),
    tape(2 * SECOND + 500_000, "100.1", "buy", 1),
    tape(3 * SECOND, "100.3", "sell", 2),
    tape(4 * SECOND, "100.1", "buy", 3),
    book_row(5 * SECOND, 502, "bid", "100.0", "0"),
]


async def replay(bus: Bus, session: uuid.UUID = SESSION) -> ReplayInjector:
    injector = build_replay_injector(
        session_id=session, request=request(streams=REEMITTED), tick_sizes={SYM: TICK}, bus=bus
    )
    clock = ReplayClock(
        RegroupedStream(ListStream(RECORDING)),
        injector,
        RecordingObserver(),
        time=FakeTime(),
        start_us=T0,
        end_us=T0 + 60 * SECOND,
        speed=UNBOUNDED,
    )
    async with clock:
        assert await clock.play() == "range_end"
    return injector


async def test_replay_traffic_never_reaches_the_live_book_its_topics_or_live_consumers(
    tmp_path: Path,
) -> None:
    bus = LoggingBus()
    live_book = Topic(env="live", domain="md", symbol=SYM, detail="book")

    async def publish_live(obj: object) -> None:
        await bus.publish(live_book, obj)

    async def no_resubscribe() -> None:
        return None

    live = BookEngine(
        symbol=SYM, depth=200, publish=publish_live, resubscribe=no_resubscribe, now_us=lambda: 1
    )
    await live.start()
    await live.on_event(live_snap(10, [lvl(990, 1)], [lvl(1010, 1)]))
    await live.on_event(live_delta(11, 10, [lvl(990, 2)]))
    assert live.phase is BookPhase.LIVE
    recorders = {
        detail: bus.subscribe(
            f"recorder-{detail}", f"live.md.{SYM}.{detail}", QueuePolicy.NEVER_DROP
        )
        for detail in ("trade", "book")
    }
    live_bars, replay_bars = BarSink("live"), BarSink("replay")
    live_set = BarBuilderSet(
        bus, "live", EmitRouter([live_bars]), StateStore(tmp_path / "live"), now_us=Clock()
    )
    replay_set = BarBuilderSet(
        bus,
        replay_env(SESSION),
        EmitRouter([replay_bars]),
        StateStore(tmp_path / "replay"),
        now_us=Clock(),
    )
    await live_set.register(T3, SYM, "live-chart")
    await replay_set.register(T3, SYM, "replay-chart")
    book_before, last_u, seen = live.live_snapshot(), live.last_u, len(bus.log)

    await replay(bus)
    await settle(bus, replay_set)
    await settle(bus, live_set)

    # The live book: same state, nothing more published on its topics.
    assert live.phase is BookPhase.LIVE and live.last_u == last_u == 11
    assert live.live_snapshot() == book_before
    replayed = bus.log[seen:]
    assert replayed and all(is_replay_env(topic.env) for topic, _ in replayed)
    assert {topic.key for topic, _ in replayed} == {
        f"{replay_env(SESSION)}.md.{SYM}.trade",
        f"{replay_env(SESSION)}.md.{SYM}.book",
    }
    # Every replayed event is stamped, the replay book's own status events included (the engine
    # stamps those `live`; the replay book re-stamps them before they reach its topic).
    events = [event for _, event in replayed if isinstance(event, DomainEvent)]
    assert {type(e) for e in events} == {TradeEvent, BookSnapshot, BookDelta, BookStatus}
    assert all(e.source == "replay" for e in events)
    assert all(isinstance(e, DomainEvent | BookStatus) for _, e in replayed)
    # Live consumers saw nothing; the same bars code on the replay namespace built a bar.
    assert all(sub.qsize() == 0 for sub in recorders.values())
    assert live_bars.seen == []
    assert [kind for _, _, kind, _, _ in replay_bars.seen if kind == "close"] == ["close"]
    await live_set.stop()
    await replay_set.stop()


async def test_the_replay_book_is_rebuilt_from_the_recording_in_the_sessions_namespace() -> None:
    bus = LoggingBus()
    books = ReplayBooks(bus, SESSION)
    injector = ReplayInjector(
        session_id=SESSION,
        request=request(streams=REEMITTED),
        tick_sizes={SYM: TICK},
        bus=bus,
        books=books,
        models=LIVE_EVENT_MODELS,
    )
    async for item in RegroupedStream(ListStream(RECORDING)):
        assert isinstance(item, RecordedEvent)
        await injector.deliver(item)
    engine = books.engine(SYM, 200)
    assert engine is not None and engine.phase is BookPhase.LIVE and engine.last_u == 502
    view = engine.live_snapshot()
    assert view is not None and view.source == "replay"
    assert [(lv.price, lv.qty) for lv in view.bids] == [(px("100.1"), px("3"))]
    assert [(lv.price, lv.qty) for lv in view.asks] == [(px("100.3"), px("2"))]


# --- the `source` invariant, attacked ------------------------------------------------------


async def test_source_replay_is_frozen_and_survives_every_copy_but_cannot_be_dropped() -> None:
    bus = LoggingBus()
    await replay(bus)
    events = [e for _, e in bus.log if isinstance(e, MarketEvent)]
    assert len(events) >= 6
    for event in events:
        assert event.source == "replay"
        field = "source"
        with pytest.raises(ValidationError):  # frozen: the attack fails
            setattr(event, field, "live")
        model = type(event)
        copies = [
            event.model_copy(),
            event.model_copy(deep=True),
            copy.copy(event),
            copy.deepcopy(event),
            model.model_validate(event.model_dump()),
            model.model_validate_json(event.model_dump_json()),
        ]
        assert all(c.source == "replay" for c in copies)
        with pytest.raises(ValidationError):  # required: a copy without it is not an event
            model.model_validate(event.model_dump(exclude={"source"}))


async def test_nothing_on_a_live_topic_ever_carries_source_replay() -> None:
    bus = LoggingBus()
    live_trade = Topic(env="live", domain="md", symbol=SYM, detail="trade")
    live_print = TradeEvent(
        event_id=EventId(uuid.UUID(int=7)),
        ts_event=T0,
        ts_ingest=T0,
        source="live",
        symbol=SYM,
        trade_id="live-1",
        price=px("100.1"),
        qty=px("1"),
        side="buy",
        is_block_trade=False,
        price_ticks=1001,
        notional=px("100.1"),
        seq=1,
    )
    await bus.publish(live_trade, live_print)
    await replay(bus)
    await bus.publish(live_trade, live_print.model_copy(update={"trade_id": "live-2"}))
    for topic, event in bus.log:
        source = getattr(event, "source", None)
        if is_replay_env(topic.env):
            assert source == "replay"
        else:
            assert source != "replay"


async def test_two_sessions_on_one_bus_never_publish_into_each_others_namespace() -> None:
    bus = LoggingBus()
    await replay(bus, SESSION)
    await replay(bus, OTHER)
    by_env: dict[str, set[uuid.UUID]] = {}
    for topic, event in bus.log:
        if isinstance(event, DomainEvent):
            by_env.setdefault(topic.env, set()).add(event.event_id)
    assert set(by_env) == {replay_env(SESSION), replay_env(OTHER)}
    assert not by_env[replay_env(SESSION)] & by_env[replay_env(OTHER)]
