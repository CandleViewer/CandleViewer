"""E08-Q02 groups 3-5 gap closers.

Cases: E08-TC-C01 (upstream fan-in), E08-TC-C02, E08-TC-C03, E08-TC-C04, E08-TC-C06,
E08-TC-D04, E08-TC-E04.

Recorded corpus frames through the real `TickerStream` / `TradeStream` / `BookEngine` and the real
`/instruments/{symbol}/ticker` router (generated-model validated). Fake clocks, no network.
The WS-gateway halves of these groups are deferred (see `E08_Q02_COVERAGE.md`).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import Ticker
from candleviewer.api.instruments import InstrumentsPrincipal
from candleviewer.api.ticker import make_ticker_router
from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import BookDelta
from candleviewer.exchange.bybit.orderbook import parse_book_frame
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import parse_recent_trades
from candleviewer.ingestion.metrics import (
    ticker_merge_incomplete_total,
    trade_backfill_rows_total,
    trade_gaps_total,
    ws_topic_staleness_seconds,
)
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.watchdog import feed_health
from tests._corpus import frames, rest
from tests.contract.bybit._support import NOW_US, TradeHarness, counter_value, tick_of

TICKERS, BURST = "ws/tickers_BTCUSDT.jsonl", "ws/burst_tickers_BTCUSDT.jsonl"
TOPIC = "tickers.BTCUSDT"


class _Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


class _Resolver:
    def resolve(self, request: Request) -> InstrumentsPrincipal:
        return InstrumentsPrincipal(user_id="u", permissions=frozenset({"marketdata:read"}))


def _stream(clock: _Clock, desired: list[set[str]] | None = None) -> TickerStream:
    stream = TickerStream(
        bus=Bus(),
        env="live",
        set_desired=lambda d: desired.append(set(d)) if desired is not None else None,
        parse_frame=parse_ticker_frame,
        topic_for=ticker_topic,
        is_listed=lambda s: s == "BTCUSDT",
        touch=lambda _t: None,
        clock=clock,
        now_us=lambda: NOW_US,
    )
    stream.acquire("a", "BTCUSDT")
    return stream


def _get(stream: TickerStream) -> Any:
    app = FastAPI()
    app.include_router(make_ticker_router(lambda: stream, principal_resolver=_Resolver()))
    return TestClient(app, client=("127.0.0.1", 50000)).get("/instruments/BTCUSDT/ticker")


async def test_c01_two_consumers_share_one_upstream_topic() -> None:
    """E08-TC-C01 (upstream half): a second consumer adds no upstream subscription."""
    desired: list[set[str]] = []
    stream = _stream(_Clock(), desired)
    stream.acquire("b", "BTCUSDT")
    assert desired[-1] == {TOPIC}
    stream.release("a", "BTCUSDT")
    stream.sync()
    assert desired[-1] == {TOPIC}  # still demanded by "b"


async def test_c02_rest_ticker_equals_the_last_merged_frame_and_the_oracle_row() -> None:
    """E08-TC-C02: oracle O-TKR = independent last-write-wins fold of the wire frames."""
    stream = _stream(_Clock())
    oracle: dict[str, str] = {}
    for raw in frames(TICKERS):
        await stream.handle_frame(raw)
        oracle.update(json.loads(raw)["data"])
    r = _get(stream)
    assert r.status_code == 200
    body = Ticker.model_validate(r.json())
    assert body.last_price == oracle["lastPrice"] and body.mark_price == oracle["markPrice"]
    assert body.funding_rate is not None and Decimal(body.funding_rate) == Decimal(
        oracle["fundingRate"]
    )
    assert r.json()["bid1_price"] == oracle["bid1Price"]
    latest = stream.latest("BTCUSDT")
    assert latest is not None and latest.last_price == Decimal(oracle["lastPrice"])


async def test_c03_delta_only_burst_publishes_full_tickers_and_never_counts_incomplete() -> None:
    """E08-TC-C03: after the first snapshot every merged event has no null price field."""
    stream = _stream(_Clock())
    held_before = counter_value(ticker_merge_incomplete_total, symbol="BTCUSDT")
    seen = 0
    for raw in frames(BURST):
        await stream.handle_frame(raw)
        ev = stream.latest("BTCUSDT")
        if ev is not None:
            seen += 1
            assert ev.is_delta is False
            assert None not in (ev.last_price, ev.mark_price, ev.bid1_price, ev.ask1_price)
    assert seen >= 1
    assert counter_value(ticker_merge_incomplete_total, symbol="BTCUSDT") == held_before


async def test_c04_unsubscribed_topic_stays_inside_the_30s_grace_then_drops() -> None:
    """E08-TC-C04: still desired at 29 s, gone after the 30 s grace."""
    clock = _Clock()
    desired: list[set[str]] = []
    stream = _stream(clock, desired)
    stream.release("a", "BTCUSDT")
    clock.t = 29.0
    stream.sync()
    assert desired[-1] == {TOPIC}
    clock.t = 31.0
    stream.sync()
    assert desired[-1] == set()


async def test_c06_stale_flag_and_staleness_gauge_during_a_drop_then_reset() -> None:
    """E08-TC-C06: `stale: true` over REST while behind SLO; cleared by the next live frame;
    `ws_topic_staleness_seconds` rises with the clock and resets on the next message."""
    clock = _Clock()
    stream = _stream(clock)
    raws = frames(TICKERS)
    await stream.handle_frame(raws[0])
    assert _get(stream).json()["stale"] is False
    await stream.process_health(feed_health(TOPIC, "stale", 6.0, now_us=0))
    assert _get(stream).json()["stale"] is True  # never a silently-frozen "live" value
    clock.t = 7.0
    stream.sync()
    assert ws_topic_staleness_seconds.labels(topic=TOPIC)._value.get() == 7.0
    await stream.handle_frame(raws[1])
    clock.t = 7.5
    stream.sync()
    assert _get(stream).json()["stale"] is False
    assert ws_topic_staleness_seconds.labels(topic=TOPIC)._value.get() == 0.5


async def test_d04_trade_gap_is_counted_backfilled_and_equals_the_recorded_oracle() -> None:
    """E08-TC-D04 (REST/metric half; the `/market/data-coverage` + UI halves are deferred):
    a reconnect hole is backfilled from the recorded recent-trade page, `trade_gaps_total` +1 and
    `trade_backfill_rows_total{ok}` > 0, and every backfilled id is in the REST oracle set."""
    body = rest("rest/recent_trade_BTCUSDT.json")
    oracle_ids = {p.trade_id for p in parse_recent_trades("BTCUSDT", body)}

    async def fetch(_symbol: str) -> Any:
        return parse_recent_trades("BTCUSDT", body)

    h = TradeHarness(fetch=fetch)
    raws = frames("ws/publicTrade_BTCUSDT.jsonl")
    for raw in raws[:2]:
        await h.stream.handle_frame(raw)
    h.drain()
    gaps = counter_value(trade_gaps_total, symbol="BTCUSDT", recovered="true")
    rows = counter_value(trade_backfill_rows_total, result="ok")
    await h.stream.process_health(
        feed_health("publicTrade.BTCUSDT", "resubscribing", 0.0, now_us=0)
    )
    await h.stream.handle_frame(raws[2])
    await h.stream.wait_backfills()  # #1905: the backfill runs off the dispatch path
    (gap,) = h.drain_gaps()
    assert gap.recovered is True and gap.label().startswith("Backfilled")
    assert counter_value(trade_gaps_total, symbol="BTCUSDT", recovered="true") == gaps + 1
    assert counter_value(trade_backfill_rows_total, result="ok") > rows
    backfilled = [e for e in h.drain() if e.source == "backfill"]
    assert backfilled and {e.trade_id for e in backfilled} <= oracle_ids


async def test_e04_crossed_delta_is_never_published_and_forces_a_resync() -> None:
    """E08-TC-E04: a corpus delta mutated to cross the book (bid >= best ask) is dropped, the
    book falls back to SNAPSHOT_PENDING, no crossed state is served, resync +1."""
    published: list[object] = []
    resubs: list[int] = []

    async def pub(obj: object) -> None:
        published.append(obj)

    async def resub() -> None:
        resubs.append(1)

    eng = BookEngine(symbol="BTCUSDT", depth=200, publish=pub, resubscribe=resub, now_us=lambda: 0)
    await eng.start()
    raws = frames("ws/orderbook_BTCUSDT.jsonl")
    snap = parse_book_frame(raws[0], tick_of)
    assert snap is not None
    await eng.on_event(snap)
    nxt = json.loads(raws[1])
    best_ask = snap.asks[0].price
    nxt["data"]["b"] = [[str(best_ask + Decimal("10")), "1.000"]]  # a bid above the best ask
    crossed = parse_book_frame(json.dumps(nxt), tick_of)
    assert isinstance(crossed, BookDelta)
    base_resubs = len(resubs)
    await eng.on_event(crossed)
    assert eng.phase is BookPhase.SNAPSHOT_PENDING and eng.resync_count == 1
    assert len(resubs) == base_resubs + 1 and eng.live_snapshot() is None
    assert crossed not in published
