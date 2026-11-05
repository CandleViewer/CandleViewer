"""E35-T15 PR 2 (#5745): the quote, ticker and book producers (`rules_producers_wiring.py`).

The bus consumers are driven by hand (`offer`, `pump`, `flush`; their task is stopped right after
attach), the book producer's timer never fires (`poll` by hand), and every clock is a fake. Book
data is the recorded corpus through a real `BookStream`; tickers are the recorded frames (C-13.5).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer import rules_producers_wiring as wiring
from candleviewer.book.models import BestQuoteEvent
from candleviewer.book.quote import QuoteTracker
from candleviewer.book.state import BookState
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import StreamInvalidated, Topic, replay_env
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.bybit.ticker import parse_ticker_frame
from candleviewer.ingestion.ticker_stream import ticker_event
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules.producers import LOST_AFTER_S, SOURCE_DEGRADED, MetricProducer, Want
from candleviewer.rules.runner import PushedMetricSource
from candleviewer.rules_producers_wiring import (
    BOOK_CADENCE_MS,
    TICKER_CADENCE_MS,
    BookDepthProducer,
    BookReader,
    BookTicks,
    QuoteProducer,
    TickerProducer,
    depth_n,
    depth_sums,
    microprice,
)
from tests import _tickers as t
from tests.rules.test_instance_binding import ref, rule
from tests.rules.test_producers import Clock, Rig, _never
from tests.unit.book._builders import lvl, snap
from tests.unit.ingestion.test_book_stream_staleness import BOOK, WS
from tests.unit.ingestion.test_book_stream_staleness import _Rig as BookRig

TS_US = 1_790_000_000_000_000
_FIRST = parse_ticker_frame(t.FRAMES[0])
assert _FIRST is not None


class Counting(PushedMetricSource):
    def __init__(self) -> None:
        super().__init__()
        self.pushes: list[str] = []

    def push_key(self, key: str, value: Any, ts_ms: int, cadence_ms: int) -> None:
        self.pushes.append(key)
        super().push_key(key, value, ts_ms, cadence_ms)


def _rig(rules: list[Rule], *producers: MetricProducer) -> Rig:
    rig = Rig(rules)
    rig.source = Counting()
    for producer in producers:
        rig.bridge.add(producer)
    return rig


def _rule(metric: str, trigger: str, params: dict[str, Any] | None = None, rid: int = 7) -> Rule:
    left = {"metric": metric, "params": params or {}}
    return rule(left, symbols=("BTCUSDT",), trigger={"type": trigger}, rid=rid)


def _quote(us: int = TS_US, bid_qty: int = 2, ask_qty: int = 3) -> BestQuoteEvent:
    book = BookState.from_levels(200, [lvl(999, bid_qty)], [lvl(1001, ask_qty)])
    quote = QuoteTracker().update(book, snap(us, [], []))
    assert quote is not None
    return quote


def _ticker(us: int = TS_US, **fields: Any) -> TickerEvent:
    assert _FIRST is not None
    return ticker_event("BTCUSDT", dict(_FIRST.fields) | fields, ts_event_us=us, ts_ingest_us=us)


async def _hand_driven(producer: QuoteProducer | TickerProducer) -> None:
    """Stop the consumer's task (the test drives it), keep its bus subscription."""
    await producer.stop()
    producer.open()


# --- microprice --------------------------------------------------------------------------------


def test_microprice_size_weighted_top_is_the_formula() -> None:
    value = microprice(Decimal(100), Decimal(2), Decimal(101), Decimal(6))
    assert value == (Decimal(100) * 6 + Decimal(101) * 2) / 8 == Decimal("100.25")


def test_microprice_empty_top_is_not_a_value() -> None:
    assert microprice(Decimal(100), Decimal(0), Decimal(101), Decimal(0)) is None


# --- QuoteProducer ------------------------------------------------------------------------------


async def test_quote_producer_window_pushes_once_then_ticks_on_book_update() -> None:
    clock = Clock()
    quotes = QuoteProducer(Bus(), "demo", BookTicks(clock), clock=clock, sleep=_never)
    rules = [_rule("microprice", "on_book_update"), _rule("spread_ticks", "on_book_update", rid=8)]
    async with _rig(rules, quotes) as rig:
        await _hand_driven(quotes)
        for us in range(TS_US, TS_US + 500):  # 500 quotes inside one window
            quotes.offer(_quote(us))
        assert quotes.flush() == 1
        quotes.offer(_quote(TS_US + 500))
        assert quotes.flush() == 0  # the window is still open
        mp = rig.source.read(ref("microprice", symbol="BTCUSDT"))
        assert mp.value == microprice(Decimal("99.9"), Decimal(2), Decimal("100.1"), Decimal(3))
        assert (mp.ts_ms, mp.cadence_ms) == ((TS_US + 499) // 1000, BOOK_CADENCE_MS)
        assert rig.source.read(ref("spread_ticks", symbol="BTCUSDT")).value == Decimal(2)
        assert isinstance(rig.source, Counting) and len(rig.source.pushes) == 2
        assert rig.ticks == [("on_book_update", "BTCUSDT", None)]
        clock.t += 0.1  # the next window
        assert quotes.flush() == 1 and len(rig.source.pushes) == 4


async def test_quote_producer_undemanded_symbol_pushes_and_ticks_nothing() -> None:
    clock = Clock()
    quotes = QuoteProducer(Bus(), "demo", BookTicks(clock), clock=clock, sleep=_never)
    async with _rig([_rule("mid", "on_book_update")], quotes) as rig:
        await _hand_driven(quotes)
        quotes.offer(_quote().model_copy(update={"symbol": "SOLUSDT"}))
        assert quotes.flush() == 0 and rig.ticks == []


async def test_quote_producer_invalidation_clears_the_dict_and_the_next_event_re_pushes() -> None:
    clock = Clock()
    quotes = QuoteProducer(Bus(), "demo", BookTicks(clock), clock=clock, sleep=_never)
    async with _rig([_rule("microprice", "on_book_update")], quotes) as rig:
        await _hand_driven(quotes)
        quotes.offer(_quote(TS_US + 5_000))
        quotes.flush()
        clock.t += 1
        quotes.offer(_quote(TS_US, bid_qty=7))  # older than the one held: never back in time
        assert quotes.flush() == 0
        quotes.offer(StreamInvalidated(topic="demo.md.BTCUSDT.quote", ts_event=0))
        quotes.offer(_quote(TS_US, bid_qty=7))
        assert quotes.flush() == 1
        mp = rig.source.read(ref("microprice", symbol="BTCUSDT"))
        assert mp.ts_ms == TS_US // 1000
        assert mp.value == microprice(Decimal("99.9"), Decimal(7), Decimal("100.1"), Decimal(3))


async def test_book_ticks_quote_and_depth_share_one_tick_per_symbol_per_window() -> None:
    clock = Clock()
    ticks = BookTicks(clock)
    assert ticks.allow("BTCUSDT") and not ticks.allow("BTCUSDT") and ticks.allow("ETHUSDT")
    clock.t += 0.1
    assert ticks.allow("BTCUSDT")


# --- TickerProducer -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "field"),
    [({}, "last_price"), ({"source": "mark"}, "mark_price"), ({"source": "index"}, "index_price")],
)
async def test_ticker_producer_price_reads_its_source_param(
    params: dict[str, str], field: str
) -> None:
    clock = Clock()
    ticker = TickerProducer(Bus(), "demo", clock=clock, sleep=_never)
    async with _rig([_rule("price", "on_price_update", params)], ticker) as rig:
        await _hand_driven(ticker)
        event = _ticker()
        ticker.offer(event)
        assert ticker.flush() == 1
        read = rig.source.read(ref("price", params=params, symbol="BTCUSDT"))
        assert read.value == getattr(event, field) and read.value is not None
        assert (read.ts_ms, read.cadence_ms) == (TS_US // 1000, TICKER_CADENCE_MS)
        assert rig.ticks == [("on_price_update", "BTCUSDT", None)]


async def test_ticker_producer_none_price_is_not_pushed_and_ticks_nothing() -> None:
    clock = Clock()
    ticker = TickerProducer(Bus(), "demo", clock=clock, sleep=_never)
    async with _rig([_rule("price", "on_price_update", {"source": "mark"})], ticker) as rig:
        await _hand_driven(ticker)
        ticker.offer(_ticker(mark_price=None))
        assert ticker.flush() == 0 and rig.ticks == []
        assert rig.source.read(ref("price", params={"source": "mark"}, symbol="BTCUSDT")).reason


async def test_ticker_producer_bus_wildcard_delivers_every_symbol() -> None:
    clock, bus = Clock(), Bus()
    ticker = TickerProducer(bus, "demo", clock=clock, sleep=_never)
    rules = [rule({"metric": "price"}, symbols=("BTCUSDT", "ETHUSDT"))]
    async with _rig(rules, ticker) as rig:
        await _hand_driven(ticker)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            event = _ticker().model_copy(update={"symbol": symbol})
            await bus.publish(Topic(env="demo", domain="md", symbol=symbol, detail="ticker"), event)
        assert ticker.pump() == 2 and ticker.flush() == 2
        assert {s for _, s, _ in rig.ticks} == {"BTCUSDT", "ETHUSDT"}


async def test_ticker_producer_detach_unsubscribes_and_stops_its_task() -> None:
    clock, bus = Clock(), Bus()
    ticker = TickerProducer(bus, "demo", clock=clock, sleep=_never)
    async with _rig([_rule("price", "on_price_update")], ticker):
        task = ticker._task
        assert task is not None and not task.done()
    assert task.done() and ticker._sub is None
    assert bus._resolve(Topic(env="demo", domain="md", symbol="BTCUSDT", detail="ticker")) == []


async def test_a_replay_session_never_feeds_the_live_source() -> None:
    """Gherkin: A replay session never feeds the live source (quotes and tickers; bars: the one
    live `BarBuilderSet` is the only emitter into `BarFieldProducer`)."""
    clock, bus = Clock(), Bus()
    replay = replay_env(uuid.UUID(int=1))
    quotes = QuoteProducer(bus, "demo", BookTicks(clock), clock=clock, sleep=_never)
    ticker = TickerProducer(bus, "demo", clock=clock, sleep=_never)
    rules = [_rule("mid", "on_book_update"), _rule("price", "on_price_update", rid=8)]
    async with _rig(rules, quotes, ticker) as rig:
        await _hand_driven(quotes)
        await _hand_driven(ticker)
        for detail, event in (("quote", _quote()), ("ticker", _ticker())):
            topic = Topic(env=replay, domain="md", symbol="BTCUSDT", detail=detail)
            await bus.publish(topic, event)  # the replay env: never matched
            live = Topic(env="demo", domain="md", symbol="BTCUSDT", detail=detail)
            await bus.publish(live, event.model_copy(update={"source": "replay"}))
        assert quotes.pump() == 1 and ticker.pump() == 1  # taken off the bus, then dropped
        assert quotes.flush() == 0 and ticker.flush() == 0
        assert isinstance(rig.source, Counting) and rig.source.pushes == [] and rig.ticks == []
    with pytest.raises(ValueError, match="live env"):
        TickerProducer(bus, replay)


# --- BookDepthProducer --------------------------------------------------------------------------


def _depth(books: BookRig, clock: Clock) -> BookDepthProducer:
    reader: BookReader = books.stream  # `BookStream` is the reader (structural)
    return BookDepthProducer(lambda: reader, BookTicks(clock), clock=clock, sleep=_never)


async def test_book_pressure_is_pushed_at_the_book_window_not_per_delta() -> None:
    """Gherkin: Book pressure is pushed at the book window, not per delta."""
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    async with _rig([_rule("book_pressure", "on_book_update", {"n": 20})], depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:1])
        await books.feed(BOOK[1:501])  # 500 book updates inside one 100 ms window
        assert isinstance(rig.source, Counting) and rig.source.pushes == []  # none per delta
        assert depth.poll() == 1
        assert len(rig.source.pushes) == 1
        view = books.stream.view("BTCUSDT", 20)
        engine = books.stream.engine("BTCUSDT")
        assert view is not None and engine is not None and engine.last_applied is not None
        b = sum((lvl.qty for lvl in view.snapshot.bids), Decimal(0))
        a = sum((lvl.qty for lvl in view.snapshot.asks), Decimal(0))
        read = rig.source.read(ref("book_pressure", params={"n": 20}, symbol="BTCUSDT"))
        assert read.value == (b - a) / (b + a)
        assert (read.ts_ms, read.cadence_ms) == (
            engine.last_applied.ts_event // 1000, BOOK_CADENCE_MS,
        )  # fmt: skip
        assert rig.ticks == [("on_book_update", "BTCUSDT", None)]


async def test_book_depth_producer_imbalance_and_staleness_from_the_stream() -> None:
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    rules = [
        _rule("dom_imbalance_ratio", "on_book_update"),
        _rule("book_staleness_ms", "on_book_update", rid=8),
    ]
    async with _rig(rules, depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:10])
        books.t = 0.25  # the stream's own monotonic clock
        assert books.stream.applied_age_ms("BTCUSDT") == 250
        depth.poll()
        view = books.stream.view("BTCUSDT", 10)
        assert view is not None
        b = sum((lvl.qty for lvl in view.snapshot.bids), Decimal(0))
        a = sum((lvl.qty for lvl in view.snapshot.asks), Decimal(0))
        assert rig.source.read(ref("dom_imbalance_ratio", symbol="BTCUSDT")).value == b / a
        assert rig.source.read(ref("book_staleness_ms", symbol="BTCUSDT")).value == 250


async def test_book_depth_producer_book_not_held_deep_enough_stays_warmup() -> None:
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    async with _rig([_rule("book_pressure", "on_book_update", {"n": 201})], depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:1])
        assert depth.poll() == 0 and rig.ticks == []
        read = rig.source.read(ref("book_pressure", params={"n": 201}, symbol="BTCUSDT"))
        assert read.reason == "warmup"


async def test_book_depth_producer_stale_book_pushes_only_its_staleness() -> None:
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    rules = [
        _rule("book_pressure", "on_book_update"),
        _rule("book_staleness_ms", "on_book_update", rid=8),
    ]
    async with _rig(rules, depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:1])
        books.t = 30.0
        assert books.stream.is_stale("BTCUSDT")
        depth.poll()
        assert rig.source.read(ref("book_pressure", symbol="BTCUSDT")).reason == "warmup"
        assert rig.source.read(ref("book_staleness_ms", symbol="BTCUSDT")).value == 30_000


def test_applied_age_ms_no_applied_frame_is_none() -> None:
    assert BookRig().stream.applied_age_ms("BTCUSDT") is None


async def test_book_depth_producer_detach_stops_its_timer() -> None:
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    async with _rig([_rule("book_pressure", "on_book_update")], depth):
        task = depth._task
        assert task is not None
    assert task.done() and depth._task is None


# --- review fold (#5745 PR 2) ------------------------------------------------------------------


async def test_book_depth_producer_too_deep_want_never_blocks_shallower_wants() -> None:
    """A want deeper than the book (n=201 on a 200-deep book) stays warmup alone: the n=20
    want and the staleness are still pushed for the other rules on the symbol."""
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    rules = [
        _rule("book_pressure", "on_book_update", {"n": 201}),
        _rule("book_pressure", "on_book_update", {"n": 20}, rid=8),
        _rule("book_staleness_ms", "on_book_update", rid=9),
    ]
    async with _rig(rules, depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:10])
        assert books.stream.view("BTCUSDT", 201) is None
        assert depth.poll() == 1
        deep = rig.source.read(ref("book_pressure", params={"n": 201}, symbol="BTCUSDT"))
        assert deep.reason == "warmup"
        n20 = rig.source.read(ref("book_pressure", params={"n": 20}, symbol="BTCUSDT"))
        assert n20.value is not None and n20.reason is None
        assert rig.source.read(ref("book_staleness_ms", symbol="BTCUSDT")).value is not None


async def test_book_depth_producer_staleness_is_pushed_without_any_view() -> None:
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    rules = [
        _rule("book_pressure", "on_book_update", {"n": 201}),
        _rule("book_staleness_ms", "on_book_update", rid=8),
    ]
    async with _rig(rules, depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:1])
        books.t = 2.0
        assert depth.poll() == 1
        assert rig.source.read(ref("book_staleness_ms", symbol="BTCUSDT")).value == 2_000


def _quotes_on(rig: Rig) -> QuoteProducer:
    """A quote consumer on the bridge's own clock (both monotonic in the app)."""
    quotes = QuoteProducer(Bus(), "demo", BookTicks(rig.clock), clock=rig.clock, sleep=_never)
    rig.bridge.add(quotes)
    return quotes


async def test_quote_producer_quiet_but_receiving_symbol_is_never_marked_lost() -> None:
    """Quiet but healthy: the feed still delivers the symbol, its values unchanged."""
    rig = _rig([_rule("mid", "on_book_update")])
    quotes = _quotes_on(rig)
    async with rig:
        await _hand_driven(quotes)
        for i in range(5):  # the same top every 30 s, for 2.5 lost bounds
            quotes.offer(_quote(TS_US + i))
            quotes.flush()
            rig.clock.t += 30
            assert rig.bridge.watch() == 0 and quotes.holds("BTCUSDT")
        assert rig.source.read(ref("mid", symbol="BTCUSDT")).value == Decimal(100)


async def test_quote_producer_dead_feed_holding_its_last_event_is_marked_after_the_bound() -> None:
    """A feed that stops with no health event (the book dropped): the held event no longer
    keeps the ref unmarked once nothing was received for the lost bound (fail closed)."""
    rig = _rig([_rule("mid", "on_book_update")])
    quotes = _quotes_on(rig)
    async with rig:
        await _hand_driven(quotes)
        quotes.offer(_quote())
        assert quotes.flush() == 1
        rig.clock.t += LOST_AFTER_S - 1
        assert rig.bridge.watch() == 0 and quotes.holds("BTCUSDT")
        rig.clock.t += 2
        assert not quotes.holds("BTCUSDT")
        assert rig.bridge.watch() == 1
        assert rig.source.read(ref("mid", symbol="BTCUSDT")).reason == SOURCE_DEGRADED


class _Frames:
    """A `BookReader` whose book last applied a frame `age` ms ago (None: never)."""

    def __init__(self) -> None:
        self.age: int | None = 0

    def view(self, symbol: str, depth: int) -> Any:
        return None

    def applied_age_ms(self, symbol: str) -> int | None:
        return self.age

    def engine(self, symbol: str) -> Any:
        return None


def _book_quotes_on(rig: Rig, frames: _Frames) -> QuoteProducer:
    reader: BookReader = frames
    quotes = QuoteProducer(
        Bus(), "demo", BookTicks(rig.clock), books=lambda: reader, clock=rig.clock, sleep=_never
    )
    rig.bridge.add(quotes)
    return quotes


async def test_quote_producer_top_unchanged_while_frames_apply_is_never_marked_lost() -> None:
    """The book publishes a quote on a top change only: a quiet top over a live book."""
    frames = _Frames()
    rig = _rig([_rule("mid", "on_book_update")])
    quotes = _book_quotes_on(rig, frames)
    async with rig:
        await _hand_driven(quotes)
        quotes.offer(_quote())
        assert quotes.flush() == 1
        for _ in range(3):  # 90 s with one quote, the book applying frames all along
            rig.clock.t += 30
            frames.age = 40
            assert rig.bridge.watch() == 0 and quotes.holds("BTCUSDT")
        assert rig.source.read(ref("mid", symbol="BTCUSDT")).value == Decimal(100)


async def test_quote_producer_book_frames_stopped_is_marked_lost() -> None:
    frames = _Frames()
    rig = _rig([_rule("mid", "on_book_update")])
    quotes = _book_quotes_on(rig, frames)
    async with rig:
        await _hand_driven(quotes)
        quotes.offer(_quote())
        assert quotes.flush() == 1
        rig.clock.t += LOST_AFTER_S + 1
        frames.age = round((LOST_AFTER_S + 1) * 1000)  # no frame since the quote
        assert not quotes.holds("BTCUSDT")
        assert rig.bridge.watch() == 1
        assert rig.source.read(ref("mid", symbol="BTCUSDT")).reason == SOURCE_DEGRADED
        frames.age = None  # the book dropped: still not held
        assert not quotes.holds("BTCUSDT")


async def test_quote_producer_one_symbol_failing_every_window_logs_once() -> None:
    clock = Clock()
    quotes = QuoteProducer(Bus(), "demo", BookTicks(clock), clock=clock, sleep=_never)
    rules = [rule({"metric": "mid"}, symbols=("BTCUSDT", "ETHUSDT"))]
    async with _rig(rules, quotes) as rig:
        await _hand_driven(quotes)
        real = quotes._push

        def flaky(sink: Any, event: BestQuoteEvent) -> bool:
            if event.symbol == "ETHUSDT":
                raise ValueError("bad frame")
            return real(sink, event)

        quotes._push = flaky  # type: ignore[method-assign]  # one symbol raises every window
        with capture_logs() as logs:
            for i in range(4):
                for symbol in ("BTCUSDT", "ETHUSDT"):
                    quotes.offer(_quote(TS_US + i).model_copy(update={"symbol": symbol}))
                assert quotes.flush() == 1  # BTCUSDT still pushes and ticks
                clock.t += 1
        assert [e["event"] for e in logs].count("rules.producer_failed") == 1
        assert rig.sample("rule_metric_producer_errors_total", producer="quote") == 4


# --- edges: depth parameters, caps, the timers ---------------------------------------------------


@pytest.mark.parametrize(
    ("metric", "params", "n"),
    [
        ("book_staleness_ms", {}, 1), ("book_pressure", {}, 20), ("dom_imbalance_ratio", {}, 10),
        ("book_pressure", {"n": "7"}, 7), ("book_pressure", {"n": 0}, None),
        ("book_pressure", {"n": 501}, None), ("book_pressure", {"n": True}, None),
        ("book_pressure", {"n": "x"}, None), ("book_pressure", {"n": "²"}, None),
        ("book_pressure", {"n": "\u0661\u0660"}, None),
        ("book_pressure", {"n": "\uff11\uff10"}, None),
        ("book_pressure", {"n": "9" * 5000}, None), ("book_pressure", {"n": "0500"}, None),
        ("book_pressure", {"n": Decimal(20)}, None), ("book_pressure", {"n": None}, None),
    ],
)  # fmt: skip
def test_depth_n_reads_the_authored_n_else_the_default_and_refuses_the_rest(
    metric: str, params: dict[str, Any], n: int | None
) -> None:
    assert depth_n(Want(metric, params, None, "")) == n


def test_depth_sums_reads_the_top_n_levels_only() -> None:
    assert depth_sums([lvl(10, 2), lvl(9, 3), lvl(8, 4)], 2) == Decimal(5)


def test_book_ticks_full_table_is_cleared_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiring, "MAX_SYMBOLS", 2)
    ticks = BookTicks(Clock())
    assert ticks.allow("AAAUSDT") and ticks.allow("BBBUSDT")
    assert ticks.allow("CCCUSDT")  # a third symbol clears the table
    assert ticks.allow("AAAUSDT")  # cleared: one extra tick, never a lost one


async def test_quote_producer_symbol_cap_drops_new_symbols_and_logs_once() -> None:
    clock = Clock()
    quotes = QuoteProducer(
        Bus(), "demo", BookTicks(clock), clock=clock, sleep=_never, max_symbols=1
    )
    with capture_logs() as logs:
        quotes.offer(_quote())
        for symbol in ("ETHUSDT", "SOLUSDT"):
            quotes.offer(_quote().model_copy(update={"symbol": symbol}))
    assert [e["event"] for e in logs] == ["rules.producer_symbols_full"]
    assert quotes.flush() == 0  # not attached: nothing pushed


async def test_quote_producer_task_takes_a_published_quote_to_a_push_and_a_tick() -> None:
    clock, bus = Clock(), Bus()
    quotes = QuoteProducer(bus, "demo", BookTicks(clock), clock=clock, sleep=_never)
    async with _rig([_rule("mid", "on_book_update")], quotes) as rig:
        await bus.publish(
            Topic(env="demo", domain="md", symbol="BTCUSDT", detail="quote"), _quote()
        )
        for _ in range(100):  # the consumer's own task: yield until it has run
            if rig.ticks:
                break
            await asyncio.sleep(0)
        assert rig.ticks == [("on_book_update", "BTCUSDT", None)]
        assert rig.source.read(ref("mid", symbol="BTCUSDT")).value is not None


async def test_quote_producer_task_survives_a_failing_turn() -> None:
    clock, bus = Clock(), Bus()
    quotes = QuoteProducer(bus, "demo", BookTicks(clock), clock=clock, sleep=_never)
    async with _rig([_rule("mid", "on_book_update")], quotes) as rig:
        quotes.pump = lambda: 1 // 0  # type: ignore[method-assign]  # every turn raises
        await bus.publish(
            Topic(env="demo", domain="md", symbol="BTCUSDT", detail="quote"), _quote()
        )
        for _ in range(100):
            if rig.sample("rule_metric_producer_errors_total", producer="quote"):
                break
            await asyncio.sleep(0)
        assert rig.sample("rule_metric_producer_errors_total", producer="quote") == 1
        task = quotes._task
        assert task is not None and not task.done()  # parked, never dead


async def test_book_depth_producer_without_books_or_frames_pushes_nothing() -> None:
    books, clock = BookRig(), Clock()
    rules = [_rule("book_staleness_ms", "on_book_update")]
    unwired = BookDepthProducer(lambda: None, BookTicks(clock), sleep=_never)
    async with _rig(rules, unwired):
        assert unwired.poll() == 0  # no book stream composed
    depth = _depth(books, clock)
    async with _rig(rules, depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")  # held, but no frame applied yet
        assert depth.poll() == 0 and rig.ticks == []


async def test_book_depth_producer_timer_survives_a_failing_pass() -> None:
    books, clock = BookRig(), Clock()
    passes: list[int] = []
    gate = asyncio.Event()

    async def tick(_s: float) -> None:
        if len(passes) >= 2:
            gate.set()
            await asyncio.Event().wait()
        passes.append(1)

    reader: BookReader = books.stream
    depth = BookDepthProducer(lambda: reader, BookTicks(clock), sleep=tick)
    depth.poll = lambda: 1 // 0  # type: ignore[method-assign]  # every pass raises
    async with _rig([_rule("book_pressure", "on_book_update")], depth) as rig:
        await gate.wait()
        assert rig.sample("rule_metric_producer_errors_total", producer="book_depth") == 2


# --- slice review fold (#5745 PR 2b) -----------------------------------------------------------


async def test_book_depth_producer_unreadable_n_stays_warmup_alone_and_is_counted_once() -> None:
    """One rule's ``n`` of ``'²'`` (``isdigit`` but not ``int``) never stops the producer."""
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    rules = [
        _rule("dom_imbalance_ratio", "on_book_update", {"n": "²"}),
        _rule("dom_imbalance_ratio", "on_book_update", {"n": 10}, rid=8),
    ]
    async with _rig(rules, depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:10])
        assert depth.poll() == 1
        clock.t += 0.1
        assert depth.poll() == 1
        good = rig.source.read(ref("dom_imbalance_ratio", params={"n": 10}, symbol="BTCUSDT"))
        bad = rig.source.read(ref("dom_imbalance_ratio", params={"n": "²"}, symbol="BTCUSDT"))
        assert good.value is not None and bad.reason == "warmup"
        assert rig.refused("params") == 1


async def test_book_depth_producer_second_poll_in_one_window_pushes_nothing() -> None:
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    async with _rig([_rule("book_pressure", "on_book_update")], depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:1])
        assert depth.poll() == 1 and depth.poll() == 0
        assert isinstance(rig.source, Counting) and len(rig.source.pushes) == 1
        clock.t += 0.1
        assert depth.poll() == 1 and len(rig.source.pushes) == 2


async def test_book_depth_producer_staleness_grows_through_a_desync() -> None:
    books, clock = BookRig(), Clock()
    depth = _depth(books, clock)
    async with _rig([_rule("book_staleness_ms", "on_book_update")], depth) as rig:
        books.stream.acquire(WS, "BTCUSDT")
        await books.feed(BOOK[:10])
        depth.poll()
        engine = books.stream.engine("BTCUSDT")
        assert engine is not None
        await engine.go_desynced()
        assert engine.last_applied is None
        books.t, clock.t = 3.0, clock.t + 0.1
        assert depth.poll() == 1
        assert rig.source.read(ref("book_staleness_ms", symbol="BTCUSDT")).value == 3_000


async def test_keyed_consumer_unattached_with_a_pending_symbol_never_spins() -> None:
    quotes = QuoteProducer(Bus(), "demo", BookTicks(Clock()), clock=Clock(), sleep=_never)
    quotes.offer(_quote())  # a changed symbol, and no sink to flush it to
    turns: list[int] = []
    pump = quotes.pump

    def counted() -> int:
        turns.append(1)
        return pump()

    quotes.pump = counted  # type: ignore[method-assign]  # count the consumer's turns
    quotes.start()
    try:
        for _ in range(50):
            await asyncio.sleep(0)
        assert len(turns) <= 1  # parked on the bus for the window, not a 0 s loop
    finally:
        await quotes.stop()


async def test_quote_producer_two_events_at_one_exchange_time_the_later_one_wins() -> None:
    """Only an older event is refused (never back in time): one at the same `ts_event` is the
    later arrival, so it replaces the held one."""
    clock = Clock()
    quotes = QuoteProducer(Bus(), "demo", BookTicks(clock), clock=clock, sleep=_never)
    async with _rig([_rule("microprice", "on_book_update")], quotes) as rig:
        await _hand_driven(quotes)
        quotes.offer(_quote(TS_US, bid_qty=2))
        quotes.offer(_quote(TS_US, bid_qty=7))
        assert quotes.flush() == 1
        mp = rig.source.read(ref("microprice", symbol="BTCUSDT"))
        assert mp.value == microprice(Decimal("99.9"), Decimal(7), Decimal("100.1"), Decimal(3))


# --- orchestrator review fold (#5745 PR 2d) ----------------------------------------------------


class _FixedBook:
    """A `BookReader` over one fixed, LIVE book for every symbol (its sides as given)."""

    def __init__(self, bids: list[Any], asks: list[Any], age_ms: int = 40) -> None:
        self.snapshot = snap(TS_US, bids, asks)
        self.age_ms = age_ms

    def view(self, symbol: str, depth: int) -> Any:
        return SimpleNamespace(snapshot=self.snapshot, stale=False)

    def applied_age_ms(self, symbol: str) -> int | None:
        return self.age_ms

    def engine(self, symbol: str) -> Any:
        return SimpleNamespace(last_applied=SimpleNamespace(ts_event=TS_US))


def _fixed_depth(book: _FixedBook, clock: Clock) -> BookDepthProducer:
    return BookDepthProducer(lambda: book, BookTicks(clock), clock=clock, sleep=_never)


async def test_book_depth_producer_staleness_is_stamped_at_the_frame_time_plus_its_age() -> None:
    clock = Clock()
    depth = _fixed_depth(_FixedBook([lvl(999, 2)], [lvl(1001, 3)], age_ms=250), clock)
    async with _rig([_rule("book_staleness_ms", "on_book_update")], depth) as rig:
        depth.poll()
        read = rig.source.read(ref("book_staleness_ms", symbol="BTCUSDT"))
        assert (read.value, read.ts_ms) == (250, TS_US // 1000 + 250)


@pytest.mark.parametrize(
    ("bids", "asks", "imbalance", "pressure"),
    [
        ([lvl(999, 2)], [], None, Decimal(1)),  # no ask: no ratio, a full bid pressure
        ([], [lvl(1001, 3)], Decimal(0), Decimal(-1)),
        ([], [], None, None),  # both empty: neither is a value
    ],
)
async def test_book_depth_producer_zero_side_pushes_no_value_and_never_raises(
    bids: list[Any], asks: list[Any], imbalance: Decimal | None, pressure: Decimal | None
) -> None:
    clock = Clock()
    depth = _fixed_depth(_FixedBook(bids, asks), clock)
    rules = [
        _rule("dom_imbalance_ratio", "on_book_update"),
        _rule("book_pressure", "on_book_update", rid=8),
    ]
    async with _rig(rules, depth) as rig:
        depth.poll()
        assert rig.sample("rule_metric_producer_errors_total", producer="book_depth") == 0
        got_ratio = rig.source.read(ref("dom_imbalance_ratio", symbol="BTCUSDT"))
        got_pressure = rig.source.read(ref("book_pressure", symbol="BTCUSDT"))
        assert (got_ratio.value, got_pressure.value) == (imbalance, pressure)


async def test_book_depth_producer_dropped_symbol_leaves_its_last_frame_time() -> None:
    clock = Clock()
    depth = _fixed_depth(_FixedBook([lvl(999, 2)], [lvl(1001, 3)]), clock)
    both = rule(
        {"metric": "book_staleness_ms"}, symbols=("BTCUSDT", "ETHUSDT"),
        trigger={"type": "on_book_update"},
    )  # fmt: skip
    async with _rig([both], depth) as rig:
        depth.poll()
        assert set(depth._last_ts) == {"BTCUSDT", "ETHUSDT"}
        rig.items = [
            EvaluableRule(_rule("book_staleness_ms", "on_book_update"), "simulate", None, "v2", "h")
        ]
        await rig.bridge.refresh()
        clock.t += 0.1
        depth.poll()
        assert set(depth._last_ts) == {"BTCUSDT"}
