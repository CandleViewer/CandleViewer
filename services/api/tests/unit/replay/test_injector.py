"""`ReplayInjector` (E26-T03): every re-emitted field as 24 Sec.13.7 tables it, for rows recorded
before E26-T03 (the derived fallbacks) and after (the recorded values); `event_id` determinism and
uniqueness; refusals (off-grid price, missing tick size, anything not re-emitted); the ordinal,
generation, restart and loop-restart hooks."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bus.bus import Bus, Subscription
from candleviewer.bus.models import QueuePolicy, Topic, TopicPattern, replay_env
from candleviewer.domain.events import MarketEvent
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot, TradeEvent
from candleviewer.replay import (
    UNBOUNDED,
    RegroupedStream,
    ReplayClock,
    ReplayClockStateError,
    ReplayConfigInvalid,
    ReplayEventRefused,
    ReplayGap,
    ReplayLoopStartUnknown,
    ReplayPriceOffGrid,
    ReplayRequestInvalid,
    ReplayTickSizeMissing,
)
from candleviewer.replay.injector import (
    ReplayInjector,
    check_reemitted,
    price_ticks,
    replay_event_id,
)
from candleviewer.replay_wiring import LIVE_EVENT_MODELS
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    Level,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedBookUpdate,
    RecordedEvent,
    RecordedTrade,
    event_from_row,
)
from tests.unit.replay._events import SECOND, SYM, T0, delta, request, snapshot, ticker, trade
from tests.unit.replay._playback import ListStream, RecordingObserver
from tests.unit.replay._time import FakeTime

SESSION = uuid.UUID("0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18")
TICK = Decimal("0.5")
TRADES, DELTAS, SNAPSHOTS = (
    StreamKind.TRADES,
    StreamKind.ORDERBOOK_DELTA,
    StreamKind.ORDERBOOK_SNAPSHOT,
)
REEMITTED = (TRADES, DELTAS, SNAPSHOTS)


class RecordingBooks:
    """`ReplayBookHook` double: what the injector handed to the replay books."""

    def __init__(self) -> None:
        self.applied: list[MarketEvent] = []
        self.resets: list[str] = []
        self.symbol_resets: list[tuple[str, str]] = []
        self.fail: Exception | None = None
        self.gate: asyncio.Event | None = None
        self.reset_gate: asyncio.Event | None = None

    async def apply(self, event: MarketEvent) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        self.applied.append(event)

    async def reset(self, reason: str, *, symbol: str | None = None) -> None:
        if self.reset_gate is not None:
            await self.reset_gate.wait()
        if symbol is None:
            self.resets.append(reason)
        else:
            self.symbol_resets.append((symbol, reason))


class TopicLog(Bus):
    """The real bus, also noting every topic published on."""

    def __init__(self) -> None:
        super().__init__()
        self.topics: list[str] = []

    async def publish(self, topic: Topic, event: object) -> None:
        self.topics.append(topic.key)
        await super().publish(topic, event)


@dataclass
class Rig:
    injector: ReplayInjector
    bus: TopicLog
    trades: Subscription
    books: RecordingBooks

    def published(self) -> list[MarketEvent]:
        out = []
        while self.trades.qsize():
            event = self.trades.get_nowait()
            assert isinstance(event, MarketEvent)
            out.append(event)
        return out


def rig(
    *,
    session: uuid.UUID = SESSION,
    symbols: tuple[str, ...] = (SYM,),
    ticks: dict[str, Decimal] | None = None,
    loop_start_us: int | None = None,
) -> Rig:
    bus = TopicLog()
    every = TopicPattern(env=replay_env(session), domain="md", symbol="*", detail="trade")
    sub = bus.subscribe("trades", every, QueuePolicy.NEVER_DROP)
    books = RecordingBooks()
    injector = ReplayInjector(
        session_id=session,
        request=request(symbols=symbols, streams=REEMITTED),
        tick_sizes={SYM: TICK} if ticks is None else ticks,
        bus=bus,
        books=books,
        models=LIVE_EVENT_MODELS,
        loop_start_us=loop_start_us,
    )
    return Rig(injector, bus, sub, books)


def recorded_trade(
    offset_us: int,
    *,
    price: str = "100.5",
    size: str = "0.25",
    side: str = "sell",
    is_block: bool | None = None,
    seq: int = 42,
) -> RecordedEvent:
    payload = RecordedTrade(side, Decimal(price), Decimal(size), f"t{offset_us}", is_block)
    return RecordedEvent(T0 + offset_us, seq, SYM, TRADES, (f"t{offset_us}",), payload)


def update(
    offset_us: int,
    update_id: int,
    *,
    bids: tuple[Level, ...] = ((Decimal("100"), Decimal("2")),),
    asks: tuple[Level, ...] = ((Decimal("100.5"), Decimal("0")),),
    cross_seq: int | None = None,
    prev_update_id: int | None = None,
    ts_match: int | None = None,
) -> RecordedEvent:
    """A `RegroupedStream` event: one book update's rows folded into one payload."""
    payload = RecordedBookUpdate(200, update_id, cross_seq, bids, asks, prev_update_id, ts_match)
    seq = update_id if cross_seq is None else cross_seq
    return RecordedEvent(T0 + offset_us, seq, SYM, DELTAS, (update_id, 200), payload)


def levels(*pairs: tuple[str, str]) -> tuple[BookLevel, ...]:
    return tuple(
        BookLevel(price=Decimal(p), qty=Decimal(q), price_ticks=int(Decimal(p) / TICK))
        for p, q in pairs
    )


# --- derived fields, one per 24 Sec.13.7 row ------------------------------------------------


async def test_trade_keeps_recorded_fields_and_derives_the_rest_as_live_does() -> None:
    r = rig()
    await r.injector.deliver(recorded_trade(7, is_block=True))
    [event] = r.published()
    assert isinstance(event, TradeEvent)
    assert event.model_dump() == {
        "schema_version": 1,
        "event_id": replay_event_id(T0 + 7, SESSION, 0, 0),
        "ts_event": T0 + 7,
        "ts_ingest": T0 + 7,  # replay reads no wall clock
        "source": "replay",
        "exchange": "bybit",
        "category": "linear",
        "symbol": SYM,
        "trade_id": "t7",
        "price": Decimal("100.5"),
        "qty": Decimal("0.25"),
        "side": "sell",
        "is_block_trade": True,
        "price_ticks": 201,
        "notional": Decimal("25.125"),
        "seq": 42,
    }


@pytest.mark.parametrize(("stored", "expected"), [(None, False), (False, False), (True, True)])
async def test_trade_is_block_trade_is_the_recorded_flag_and_null_is_false(
    stored: bool | None, expected: bool
) -> None:
    r = rig()
    await r.injector.deliver(recorded_trade(1, is_block=stored))
    [event] = r.published()
    assert isinstance(event, TradeEvent) and event.is_block_trade is expected


async def test_trade_from_a_stored_row_matches_what_the_live_tape_derived() -> None:
    """A row as the hot tier returns it: DOUBLE price and size, no `seq` column (a row written
    before the recorder stored it, read as 0) and NULL `is_block`."""
    stored = {
        "ts": T0 + 9,
        "symbol": SYM,
        "side": "buy",
        "price": 65000.5,
        "size": 0.003,
        "trade_id": "abc",
        "is_block": None,
    }
    r = rig(ticks={SYM: Decimal("0.1")})
    await r.injector.deliver(event_from_row(TRADES, stored))
    [event] = r.published()
    assert isinstance(event, TradeEvent)
    live_price, live_qty = Decimal("65000.5"), Decimal("0.003")  # the wire text, as live parsed it
    assert (event.price, event.qty, event.side, event.seq) == (live_price, live_qty, "buy", 0)
    assert event.notional == live_price * live_qty
    assert event.price_ticks == int((live_price / Decimal("0.1")).to_integral_value()) == 650005
    assert event.is_block_trade is False


async def test_delta_rows_recorded_before_e26_t03_derive_as_the_live_adapter_emits() -> None:
    r = rig()
    await r.injector.deliver(update(5, 1234))
    [event] = r.books.applied
    assert isinstance(event, BookDelta)
    assert event.source == "replay" and event.ts_event == event.ts_ingest == T0 + 5
    assert (event.update_id, event.prev_update_id) == (1234, 1233)  # update_id - 1
    assert event.cross_seq == 1234  # NULL takes the row's update_id
    assert event.ts_match == T0 + 5  # NULL takes ts_event
    assert event.depth == 200
    assert event.bids == levels(("100", "2")) and event.asks == levels(("100.5", "0"))
    assert event.event_id == replay_event_id(T0 + 5, SESSION, 0, 0)


async def test_delta_rows_recorded_from_e26_t03_on_keep_their_values() -> None:
    rows = [
        RecordedEvent(
            T0 + 5,
            98765,
            SYM,
            DELTAS,
            (1234, 200, side, Decimal(price)),
            RecordedBookDelta(200, side, Decimal(price), Decimal(1), 1234, 98765, 1200, T0 + 3),
        )
        for side, price in (("bid", "99.5"), ("ask", "101"))
    ]
    r = rig()
    async for item in RegroupedStream(ListStream(rows)):
        assert isinstance(item, RecordedEvent)
        await r.injector.deliver(item)
    [event] = r.books.applied
    assert isinstance(event, BookDelta)
    assert (event.update_id, event.prev_update_id, event.cross_seq) == (1234, 1200, 98765)
    assert event.ts_match == T0 + 3
    assert event.bids == levels(("99.5", "1")) and event.asks == levels(("101", "1"))


@pytest.mark.parametrize(
    ("cross_seq", "ts_match", "expected"),
    [(None, None, (77, T0 + 4)), (5000, T0 + 2, (5000, T0 + 2))],
    ids=["legacy", "recorded"],
)
async def test_snapshot_cross_seq_ts_match_and_resync_reason(
    cross_seq: int | None, ts_match: int | None, expected: tuple[int, int]
) -> None:
    base = snapshot(4, update_id=77)
    assert isinstance(base.payload, RecordedBookSnapshot)
    payload = RecordedBookSnapshot(
        200, 77, cross_seq, base.payload.bids, base.payload.asks, ts_match=ts_match
    )
    event = RecordedEvent(base.ts_us, base.seq, SYM, SNAPSHOTS, base.tiebreak, payload)
    r = rig()
    await r.injector.deliver(event)
    [snap] = r.books.applied
    assert isinstance(snap, BookSnapshot)
    assert (snap.cross_seq, snap.ts_match) == expected
    assert snap.reason == "resync"  # the recording holds a full refresh, not its cause
    assert snap.update_id == 77 and snap.depth == 200
    assert snap.bids == levels(("100", "1")) == snap.asks


async def test_a_seek_anchor_is_reemitted_with_reason_replay_seek() -> None:
    r = rig()
    await r.injector.deliver_seek_anchor(snapshot(4, update_id=77))
    [snap] = r.books.applied
    assert isinstance(snap, BookSnapshot) and snap.reason == "replay_seek"
    with pytest.raises(ReplayEventRefused):
        await r.injector.deliver_seek_anchor(trade(5))


# --- price_ticks --------------------------------------------------------------------------

TICK_SIZES = [Decimal(t) for t in ("0.0001", "0.001", "0.01", "0.05", "0.1", "0.5", "1", "5")]


@settings(max_examples=200)
@given(st.integers(1, 10**9), st.sampled_from(TICK_SIZES))
def test_price_ticks_of_a_stored_double_equal_the_live_adapters(k: int, tick: Decimal) -> None:
    wire = str(k * tick)  # the exchange's price text
    live_ticks, rest = divmod(Decimal(wire), tick)  # `exchange/bybit/orderbook.py` `_levels`
    assert rest == 0
    recorded = Decimal(repr(float(wire)))  # stored as a DOUBLE, read as `event_from_row` does
    assert price_ticks(recorded, tick, symbol=SYM, stream=TRADES) == int(live_ticks) == k


@given(st.integers(1, 10**9), st.sampled_from(TICK_SIZES))
def test_price_ticks_never_rounds_an_off_grid_price(k: int, tick: Decimal) -> None:
    with pytest.raises(ReplayPriceOffGrid) as info:
        price_ticks(k * tick + tick / 2, tick, symbol=SYM, stream=DELTAS)
    assert (info.value.symbol, info.value.stream) == (SYM, DELTAS)
    assert str(k * tick + tick / 2) not in str(info.value)  # names the stream, not the price


@pytest.mark.parametrize("price", [Decimal("NaN"), Decimal("Infinity"), Decimal("1E+40")])
def test_price_ticks_refuses_a_price_with_no_grid_position(price: Decimal) -> None:
    with pytest.raises(ReplayPriceOffGrid):
        price_ticks(price, Decimal("0.0001"), symbol=SYM, stream=TRADES)


async def test_an_off_grid_level_raises_before_anything_of_the_event_is_handed_on() -> None:
    r = rig()
    bad = update(5, 9, bids=((Decimal("100"), Decimal("1")), (Decimal("99.3"), Decimal("1"))))
    with pytest.raises(ReplayPriceOffGrid):
        await r.injector.deliver(bad)
    with pytest.raises(ReplayPriceOffGrid):
        await r.injector.deliver(recorded_trade(6, price="100.2"))
    assert r.books.applied == [] and r.published() == []
    assert r.injector.next_ordinal == 0


async def test_an_off_grid_price_stops_the_clock_with_error_after_the_events_before_it() -> None:
    r = rig()
    items = [recorded_trade(1), recorded_trade(2, price="100.2"), recorded_trade(3)]
    obs, time = RecordingObserver(), FakeTime()
    clock = ReplayClock(
        ListStream(items),
        r.injector,
        obs,
        time=time,
        start_us=T0,
        end_us=T0 + SECOND,
        speed=UNBOUNDED,
    )
    async with clock:
        assert await clock.play() == "error"
    assert [e.ts_event for e in r.published() if isinstance(e, TradeEvent)] == [T0 + 1]
    [(reason, error)] = obs.stops
    assert reason == "error" and isinstance(error, ReplayPriceOffGrid)


# --- construction refusals -----------------------------------------------------------------


def test_a_session_symbol_without_a_pinned_tick_size_refuses_construction() -> None:
    with pytest.raises(ReplayTickSizeMissing) as info:
        rig(symbols=(SYM, "ETHUSDT"))
    assert info.value.symbols == ("ETHUSDT",)


@pytest.mark.parametrize("tick", [Decimal(0), Decimal("-0.5"), Decimal("NaN"), 0.5])
def test_a_tick_size_that_is_no_positive_decimal_refuses_construction(tick: object) -> None:
    with pytest.raises(ReplayConfigInvalid):
        rig(ticks=cast("dict[str, Decimal]", {SYM: tick}))  # the refused shapes, on purpose


@pytest.mark.parametrize(
    "stream", [StreamKind.TICKERS, StreamKind.LIQUIDATIONS, StreamKind.FUNDING_RATES]
)
def test_a_stream_without_listed_derivations_refuses_construction(stream: StreamKind) -> None:
    with pytest.raises(ReplayRequestInvalid):
        ReplayInjector(
            session_id=SESSION,
            request=request(streams=(TRADES, stream)),
            tick_sizes={SYM: TICK},
            bus=Bus(),
            books=RecordingBooks(),
            models=LIVE_EVENT_MODELS,
        )


def test_a_session_id_that_is_no_uuid_refuses_construction() -> None:
    with pytest.raises(ReplayConfigInvalid):
        ReplayInjector(
            session_id=cast("uuid.UUID", "live"),  # a caller-supplied namespace, refused
            request=request(),
            tick_sizes={SYM: TICK},
            bus=Bus(),
            books=RecordingBooks(),
            models=LIVE_EVENT_MODELS,
        )


# --- refusals at delivery ------------------------------------------------------------------


@pytest.mark.parametrize(
    "item",
    [
        ReplayGap(T0, SYM, TRADES, T0, T0 + SECOND, "ws_disconnect"),
        delta(5, update_id=3),  # a row the stream adapter did not regroup
        ticker(5),
        trade(5, symbol="ETHUSDT"),
    ],
    ids=["gap-marker", "unregrouped-row", "ticker", "foreign-symbol"],
)
async def test_anything_not_reemitted_is_refused_and_nothing_is_handed_on(
    item: object,
) -> None:
    r = rig()
    with pytest.raises(ReplayEventRefused):
        await r.injector.deliver(cast("RecordedEvent", item))  # a marker is no event
    assert r.books.applied == [] and r.published() == [] and r.injector.next_ordinal == 0


async def test_an_event_that_does_not_fit_the_live_model_names_the_field_not_the_value() -> None:
    r = rig()
    with pytest.raises(ReplayEventRefused) as info:
        await r.injector.deliver(recorded_trade(5, side="hold"))
    assert "side" in str(info.value) and "hold" not in str(info.value)
    assert info.value.__context__ is None and info.value.__cause__ is None


# --- event_id: layout, determinism, uniqueness ----------------------------------------------


def test_event_id_is_pinned_for_fixed_controls() -> None:
    """A golden value: the id layout and its hash inputs are a contract (24 Sec.13.7)."""
    eid = replay_event_id(1_760_000_000_123_456, SESSION, 2, 7)
    assert str(eid) == "0199c82c-c07b-7ad3-89cd-95ea4ed8338d"


@settings(max_examples=200)
@given(st.uuids(), st.integers(0, 2**32 - 1), st.integers(0, 2**64 - 1), st.integers(0, 2**52))
def test_event_id_is_uuid7_shaped_over_ts_ms_and_the_blake2b_prefix(
    session: uuid.UUID, generation: int, ordinal: int, ts_us: int
) -> None:
    eid = replay_event_id(ts_us, session, generation, ordinal)
    assert eid.version == 7 and eid.variant == uuid.RFC_4122
    assert eid.int >> 80 == (ts_us // 1000) & ((1 << 48) - 1)
    digest = hashlib.blake2b(
        session.bytes + generation.to_bytes(4, "big") + ordinal.to_bytes(8, "big"),
        digest_size=16,
    ).digest()
    rand = int.from_bytes(digest[:10], "big")
    keep = ((1 << 80) - 1) & ~(0xF << 76) & ~(0x3 << 62)  # all but the version and variant bits
    assert eid.int & keep == rand & keep
    assert replay_event_id(ts_us, session, generation, ordinal) == eid  # a pure function


async def run_session(
    events: list[RecordedEvent], *, session: uuid.UUID = SESSION
) -> list[dict[str, object]]:
    r = rig(session=session)
    for event in events:
        await r.injector.deliver(event)
    return [e.model_dump() for e in [*r.published(), *r.books.applied]]


SESSION_EVENTS = [snapshot(1, update_id=10), recorded_trade(2), update(3, 11), recorded_trade(4)]


async def test_two_replays_under_the_same_controls_reemit_identical_events() -> None:
    assert await run_session(SESSION_EVENTS) == await run_session(SESSION_EVENTS)


async def test_ids_are_unique_within_a_session_and_differ_across_sessions() -> None:
    one = [e["event_id"] for e in await run_session(SESSION_EVENTS)]
    other = [e["event_id"] for e in await run_session(SESSION_EVENTS, session=uuid.uuid4())]
    assert len(set(one)) == len(one) == 4 and not set(one) & set(other)


# --- ordinal, generation, restart, loop -----------------------------------------------------


async def test_the_ordinal_advances_only_once_an_event_was_handed_on() -> None:
    r = rig()
    r.books.fail = RuntimeError("the book refused")
    with pytest.raises(RuntimeError):
        await r.injector.deliver(update(1, 5))
    assert r.injector.next_ordinal == 0
    r.books.fail = None
    await r.injector.deliver(update(1, 5))  # delivered again: same ordinal, same id
    assert r.books.applied[0].event_id == replay_event_id(T0 + 1, SESSION, 0, 0)
    assert r.injector.next_ordinal == 1


async def test_restart_resumes_at_an_ordinal_under_a_new_generation_and_resets_the_books() -> None:
    r = rig()
    for event in SESSION_EVENTS:
        await r.injector.deliver(event)
    first = r.books.applied[0].event_id
    await r.injector.restart(ordinal=0)
    assert (r.injector.generation, r.injector.next_ordinal) == (1, 0)
    assert r.books.resets == ["replay_restart"]
    await r.injector.deliver(SESSION_EVENTS[0])
    again = r.books.applied[-1].event_id
    assert again == replay_event_id(T0 + 1, SESSION, 1, 0) and again != first


@pytest.mark.parametrize("ordinal", [-1, 2**64])
async def test_restart_refuses_an_ordinal_out_of_range(ordinal: int) -> None:
    r = rig()
    with pytest.raises(ReplayRequestInvalid):
        await r.injector.restart(ordinal=ordinal)
    assert r.injector.generation == 0 and r.books.resets == []


async def test_restart_is_refused_while_an_event_is_being_handed_on() -> None:
    r = rig()
    r.books.gate = asyncio.Event()
    pending = asyncio.ensure_future(r.injector.deliver(update(1, 5)))
    await asyncio.sleep(0)
    with pytest.raises(ReplayClockStateError):
        await r.injector.restart(ordinal=0)
    with pytest.raises(ReplayClockStateError):
        await r.injector.deliver(update(2, 6))
    r.books.gate.set()
    await pending
    assert r.injector.next_ordinal == 1


async def test_a_delivery_is_refused_while_restart_resets_the_books() -> None:
    """Review m2: the books' reset is awaited, and an event delivered meanwhile would go out
    under the generation the restart is replacing, its ordinal then overwritten. The restart
    holds the injector until it is done."""
    r = rig()
    await r.injector.deliver(SESSION_EVENTS[0])
    r.books.reset_gate = asyncio.Event()
    restarting = asyncio.ensure_future(r.injector.restart(ordinal=0))
    await asyncio.sleep(0)  # parked in the books' reset
    with pytest.raises(ReplayClockStateError):
        await r.injector.deliver(SESSION_EVENTS[1])
    with pytest.raises(ReplayClockStateError):
        await r.injector.reset_book(SYM)
    r.books.reset_gate.set()
    await restarting
    assert (r.injector.generation, r.injector.next_ordinal) == (1, 0)
    assert len(r.books.applied) == 1 and r.published() == []  # nothing slipped in
    for event in SESSION_EVENTS[:2]:
        await r.injector.deliver(event)
    [trade_event] = r.published()
    assert [r.books.applied[-1].event_id, trade_event.event_id] == [
        replay_event_id(T0 + 1, SESSION, 1, 0),
        replay_event_id(T0 + 2, SESSION, 1, 1),
    ]


async def test_a_delivery_is_refused_while_reset_book_resets_that_book() -> None:
    """The same hold while one symbol's book resets after a gap: nothing reaches a book that is
    being replaced, and the ids run on once the reset is done."""
    r = rig()
    r.books.reset_gate = asyncio.Event()
    resetting = asyncio.ensure_future(r.injector.reset_book(SYM))
    await asyncio.sleep(0)
    with pytest.raises(ReplayClockStateError):
        await r.injector.deliver(SESSION_EVENTS[0])
    with pytest.raises(ReplayClockStateError):
        await r.injector.restart(ordinal=0)
    r.books.reset_gate.set()
    await resetting
    assert (r.books.symbol_resets, r.books.resets, r.books.applied) == (
        [(SYM, "recording_gap")],
        [],
        [],
    )
    await r.injector.deliver(SESSION_EVENTS[0])
    assert r.books.applied[-1].event_id == replay_event_id(T0 + 1, SESSION, 0, 0)


async def test_the_loop_restarts_at_the_first_event_at_or_after_the_loop_start() -> None:
    r = rig(loop_start_us=T0 + 3)
    with pytest.raises(ReplayLoopStartUnknown):
        await r.injector.restart_loop()  # not reached yet
    for event in SESSION_EVENTS:  # ts 1, 2, 3, 4: the event at 3 is the third (ordinal 2)
        await r.injector.deliver(event)
    assert r.injector.loop_start_ordinal == 2
    before = r.books.applied[-1].event_id
    await r.injector.restart_loop()
    assert (r.injector.generation, r.injector.next_ordinal) == (1, 2)
    await r.injector.deliver(SESSION_EVENTS[2])
    assert r.books.applied[-1].event_id == replay_event_id(T0 + 3, SESSION, 1, 2) != before


async def test_a_loop_start_set_behind_playback_is_learnt_only_when_playback_crosses_it() -> None:
    r = rig()
    for event in SESSION_EVENTS[:3]:
        await r.injector.deliver(event)
    r.injector.set_loop_start(T0 + 2)  # already passed: where it begins is unknown
    await r.injector.deliver(SESSION_EVENTS[3])
    assert r.injector.loop_start_ordinal is None
    with pytest.raises(ReplayLoopStartUnknown):
        await r.injector.restart_loop()
    await r.injector.restart(ordinal=0)  # a seek back to range_start
    await r.injector.deliver(SESSION_EVENTS[0])
    await r.injector.deliver(SESSION_EVENTS[1])  # ts 2: the first at or after the loop start
    assert r.injector.loop_start_ordinal == 1


async def test_reset_book_resets_only_that_symbols_book_and_keeps_the_ids_running() -> None:
    r = rig()
    await r.injector.deliver(SESSION_EVENTS[0])
    await r.injector.reset_book(SYM)
    assert (r.books.symbol_resets, r.books.resets) == ([(SYM, "recording_gap")], [])
    assert (r.injector.generation, r.injector.next_ordinal) == (0, 1)
    await r.injector.deliver(SESSION_EVENTS[1])
    [trade_event] = r.published()
    assert trade_event.event_id == replay_event_id(T0 + 2, SESSION, 0, 1)


async def test_reset_book_is_refused_mid_event_and_for_a_symbol_outside_the_session() -> None:
    r = rig()
    with pytest.raises(ReplayRequestInvalid, match="outside the session"):
        await r.injector.reset_book("ETHUSDT")
    r.books.gate = asyncio.Event()
    pending = asyncio.ensure_future(r.injector.deliver(update(1, 5)))
    await asyncio.sleep(0)
    with pytest.raises(ReplayClockStateError):
        await r.injector.reset_book(SYM)
    r.books.gate.set()
    await pending
    assert r.books.symbol_resets == []


@pytest.mark.parametrize("streams", [(TRADES,), REEMITTED])
def test_check_reemitted_accepts_the_reemitted_streams(streams: tuple[StreamKind, ...]) -> None:
    check_reemitted(request(streams=streams))


def test_check_reemitted_names_every_stream_it_refuses() -> None:
    req = request(streams=(StreamKind.TICKERS, TRADES, StreamKind.KLINES))
    with pytest.raises(ReplayRequestInvalid, match="streams klines, tickers are not re-emitted"):
        check_reemitted(req)


async def test_trades_publish_on_the_sessions_namespace_and_books_go_to_the_hook() -> None:
    r = rig()
    assert r.injector.env == "replay-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18"
    for event in SESSION_EVENTS:
        await r.injector.deliver(event)
    trade_topic = "replay-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18.md.BTCUSDT.trade"
    assert r.bus.topics == [trade_topic, trade_topic]  # book events go to the book hook only
    assert [type(e) for e in r.books.applied] == [BookSnapshot, BookDelta]


async def test_a_slow_consumer_holds_delivery_back_and_loses_nothing() -> None:
    """Awaiting the bus is the clock's backpressure: a full `NEVER_DROP` subscriber holds the
    next delivery until it reads, and the injector buffers nothing of its own."""
    r = rig()
    slow = r.bus.subscribe(
        "slow", f"{replay_env(SESSION)}.md.{SYM}.trade", QueuePolicy.NEVER_DROP, maxsize=1
    )
    await r.injector.deliver(recorded_trade(1))
    pending = asyncio.ensure_future(r.injector.deliver(recorded_trade(2)))
    for _ in range(20):
        await asyncio.sleep(0)
    assert not pending.done() and r.injector.next_ordinal == 1  # held, not dropped or queued
    first = await slow.get()
    await pending
    second = await slow.get()
    assert isinstance(first, TradeEvent) and isinstance(second, TradeEvent)
    assert [first.ts_event, second.ts_event] == [T0 + 1, T0 + 2]
    assert r.injector.next_ordinal == 2
