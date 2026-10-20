"""E08-S03 acceptance scenarios (fake clock, no network)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import Ticker
from candleviewer.api.instruments import InstrumentsPrincipal
from candleviewer.api.ticker import make_ticker_router
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, TopicPattern
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.ingestion.ticker_stream import TickerMerger, TickerStream, UnknownSymbolError
from candleviewer.ingestion.watchdog import FeedHealthEvent, feed_health
from tests._corpus import corpus_path

FIX = corpus_path("ws/tickers_BTCUSDT.jsonl")
FRAMES = FIX.read_text(encoding="utf-8").splitlines()


class Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


class Harness:
    def __init__(self) -> None:
        self.clock = Clock()
        self.bus = Bus()
        self.desired: set[str] = set()
        self.touched: list[str] = []
        self.raw: list[object] = []
        self.sub = self.bus.subscribe("t", "live.md.*.ticker", QueuePolicy.NEVER_DROP)
        self.health = self.bus.subscribe(
            "h", TopicPattern(env="live", domain="health", detail="feed"), QueuePolicy.NEVER_DROP
        )
        self.stream = TickerStream(
            bus=self.bus,
            env="live",
            set_desired=self._set,
            parse_frame=parse_ticker_frame,
            topic_for=ticker_topic,
            is_listed=lambda s: s == "BTCUSDT",
            touch=self.touched.append,
            clock=self.clock,
            now_us=lambda: 1_700_000_000_500_000,
            raw_sink=self.raw.append,
        )

    def _set(self, desired: set[str]) -> None:
        self.desired = set(desired)

    def events(self) -> list[Any]:
        out: list[Any] = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out

    def states(self) -> list[str]:
        out: list[str] = []
        while not self.health.queue.empty():
            ev = self.health.queue.get_nowait()
            if isinstance(ev, FeedHealthEvent):
                out.append(ev.state)
        return out


async def test_subscribed_once_fanned_out_and_grace() -> None:
    h = Harness()
    h.stream.acquire("viewA", "BTCUSDT")
    h.stream.acquire("viewB", "BTCUSDT")
    assert h.desired == {"tickers.BTCUSDT"}  # one upstream topic for two consumers
    h.stream.release("viewA", "BTCUSDT")
    assert h.desired == {"tickers.BTCUSDT"}
    h.stream.release("viewB", "BTCUSDT")
    h.clock.t = 29.0
    h.stream.sync()
    assert h.desired == {"tickers.BTCUSDT"}  # inside the 30 s grace
    h.clock.t = 30.5
    h.stream.sync()
    assert h.desired == set()


async def test_reacquire_within_grace_keeps_subscription() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    h.stream.release("a", "BTCUSDT")
    h.clock.t = 10.0
    h.stream.acquire("b", "BTCUSDT")
    h.clock.t = 100.0
    h.stream.sync()
    assert h.desired == {"tickers.BTCUSDT"}


async def test_unknown_symbol_cannot_create_topic() -> None:
    h = Harness()
    with pytest.raises(UnknownSymbolError):
        h.stream.acquire("a", "EVIL.*")
    assert h.desired == set()


async def test_delta_merged_never_nulled_and_is_delta_false() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    for frame in FRAMES[:2]:
        await h.stream.handle_frame(frame)
    first, second = h.events()
    assert second.last_price == Decimal("63121.00")
    for f in ("bid1_price", "ask1_price", "mark_price", "volume_24h", "turnover_24h"):
        assert getattr(second, f) == getattr(first, f)
        assert getattr(second, f) is not None
    assert first.is_delta is False
    assert second.is_delta is False
    assert len(h.raw) == 2  # recorder gets the raw deltas
    assert h.touched == ["tickers.BTCUSDT"] * 2


async def test_explicit_zero_is_a_value_not_unchanged() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    for frame in FRAMES:
        await h.stream.handle_frame(frame)
    last = h.events()[-1]
    assert last.bid1_qty == Decimal("0")
    assert last.funding_rate == Decimal("0")
    assert last.ask1_price == Decimal("63120.60")


async def test_first_delta_before_snapshot_holds_and_reports_warming() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[1])  # delta first, no prior state
    assert h.events() == []
    assert h.stream.phase("BTCUSDT") == "warming"
    assert h.stream.latest("BTCUSDT") is None
    assert h.states() == ["warming"]
    await h.stream.handle_frame(FRAMES[0])
    assert len(h.events()) == 1
    assert h.stream.phase("BTCUSDT") == "live"


async def test_reconnect_invalidates_state_and_rebuilds_from_full_push() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[0])
    h.events()
    h.states()
    await h.stream.process_health(feed_health("*", "resubscribing", 0.0, now_us=0))
    assert h.stream.latest("BTCUSDT") is None  # no stale values presented as live
    assert "reconnecting" in h.states()
    await h.stream.handle_frame(FRAMES[1])  # delta only after reconnect: held
    assert h.events() == []
    await h.stream.handle_frame(FRAMES[0])  # full push rebuilds
    assert len(h.events()) == 1
    assert h.states() == ["healthy"]


async def test_stale_marks_and_recovers() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[0])
    await h.stream.process_health(feed_health("tickers.BTCUSDT", "stale", 6.0, now_us=0))
    assert h.stream.is_stale("BTCUSDT")
    await h.stream.handle_frame(FRAMES[1])
    assert h.stream.phase("BTCUSDT") == "live"


async def test_frames_for_undemanded_symbols_are_ignored() -> None:
    h = Harness()
    await h.stream.handle_frame(FRAMES[0])
    assert h.events() == []
    assert h.raw == []


async def test_malformed_and_nonticker_frames_dropped() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    for bad in ("not json", '{"op":"pong"}', '{"topic":"tickers.BTCUSDT","type":"delta"}'):
        await h.stream.handle_frame(bad)
    assert h.events() == []


async def test_stalled_consumer_memory_bounded_by_conflation() -> None:
    h = Harness()
    slow = h.bus.subscribe("slow", "live.md.*.ticker", QueuePolicy.CONFLATE_LATEST, maxsize=4)
    h.stream.acquire("a", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[0])
    for i in range(500):
        d = {
            "topic": "tickers.BTCUSDT",
            "type": "delta",
            "ts": 1700000001000 + i,
            "data": {"lastPrice": str(100 + i)},
        }
        await h.stream.handle_frame(json.dumps(d))
    assert slow.qsize() == 1
    assert (await slow.get()).last_price == Decimal("599")


def test_merger_snapshot_resets_state() -> None:
    m = TickerMerger()
    full = parse_ticker_frame(FRAMES[0])
    assert full is not None
    assert m.apply(full, ts_ingest_us=1) is not None
    only_last = parse_ticker_frame(
        json.dumps(
            {
                "topic": "tickers.BTCUSDT",
                "type": "snapshot",
                "ts": 5,
                "data": {"lastPrice": "1"},
            }
        )
    )
    assert only_last is not None
    assert m.apply(only_last, ts_ingest_us=1) is None


def test_parser_units_and_rejections() -> None:
    d = parse_ticker_frame(FRAMES[0])
    assert d is not None
    assert d.ts_event_us == 1_700_000_000_100_000
    assert d.fields["next_funding_time"] == 1_700_006_400_000_000
    empty = parse_ticker_frame(
        '{"topic":"tickers.BTCUSDT","type":"delta","ts":1,"data":{"lastPrice":""}}'
    )
    assert empty is not None
    assert empty.fields == {}
    for bad in (
        '{"topic":"tickers.bad sym","type":"delta","ts":1,"data":{}}',
        '{"topic":"tickers.BTCUSDT","type":"delta","ts":1,"data":{"lastPrice":"abc"}}',
        '{"topic":"tickers.BTCUSDT","type":"delta","ts":1,"data":{"lastPrice":"NaN"}}',
        '{"topic":"tickers.BTCUSDT","type":"weird","ts":1,"data":{}}',
    ):
        with pytest.raises(ValueError):
            parse_ticker_frame(bad)
    assert parse_ticker_frame("[]") is None


# ---- REST endpoint -------------------------------------------------------
class _Resolver:
    def __init__(self, perms: frozenset[str] | None) -> None:
        self.perms = perms

    def resolve(self, request: Request) -> InstrumentsPrincipal | None:
        return None if self.perms is None else InstrumentsPrincipal("u", self.perms)


def _client(stream: TickerStream | None, resolver: _Resolver | None) -> TestClient:
    app = FastAPI()
    app.include_router(make_ticker_router(lambda: stream, principal_resolver=resolver))
    return TestClient(app)


async def test_rest_contract_and_rbac() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    url = "/instruments/BTCUSDT/ticker"
    ok = _Resolver(frozenset({"marketdata:read"}))
    assert _client(h.stream, None).get(url).status_code == 501
    assert _client(h.stream, _Resolver(None)).get(url).status_code == 401
    assert _client(h.stream, _Resolver(frozenset())).get(url).status_code == 403
    c = _client(h.stream, ok)
    assert c.get(url).status_code == 503  # warming
    assert c.get("/instruments/ZZZZUSDT/ticker").status_code == 404
    assert c.get("/instruments/a-b/ticker").status_code == 400
    assert _client(None, ok).get(url).status_code == 503
    await h.stream.handle_frame(FRAMES[0])
    await h.stream.handle_frame(FRAMES[1])
    r = c.get(url)
    body = r.json()
    assert r.status_code == 200
    assert body["last_price"] == "63121.00"
    assert body["bid1_price"] == "63120.40"
    assert body["stale"] is False
    Ticker.model_validate(body)
    await h.stream.process_health(feed_health("tickers.BTCUSDT", "stale", 6.0, now_us=0))
    assert c.get(url).json()["stale"] is True


class _AsyncResolver:
    """Mirrors `SessionAuditPrincipalResolver`: async `resolve`, `has()` principal."""

    async def resolve(self, request: Request) -> InstrumentsPrincipal | None:
        header = request.headers.get("authorization", "")
        return InstrumentsPrincipal("u", frozenset({"marketdata:read"})) if header else None


async def test_rest_accepts_async_session_resolver() -> None:
    h = Harness()
    h.stream.acquire("a", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[0])
    app = FastAPI()
    app.include_router(make_ticker_router(lambda: h.stream, principal_resolver=_AsyncResolver()))
    c = TestClient(app)
    url = "/instruments/BTCUSDT/ticker"
    assert c.get(url).status_code == 401
    assert c.get(url, headers={"authorization": "Bearer t"}).status_code == 200


def test_questdb_ticker_write_includes_best_bid_ask() -> None:
    import asyncio

    from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
    from candleviewer.storage.repositories.rows import TickerRow

    captured: list[tuple[str, list[dict[str, object]]]] = []

    class _W:
        async def write_rows(self, table: str, rows: list[dict[str, object]], ts: str) -> None:
            captured.append((table, rows))

    repo = QuestDbMarketDataRepository.__new__(QuestDbMarketDataRepository)
    repo._writer = _W()  # type: ignore[attr-defined]
    row = TickerRow(1, "BTCUSDT", "1", "1", "1", "0", "0", "9.5", "2", "9.6", "3")
    asyncio.run(repo.write_tickers([row]))
    out = captured[0][1][0]
    assert (out["bid1_price"], out["bid1_size"], out["ask1_price"], out["ask1_size"]) == (
        9.5,
        2.0,
        9.6,
        3.0,
    )


async def test_ingest_to_bus_latency_50_symbols_measured() -> None:
    """Perf (E08-S03): ingest->bus handling of 50 symbols x 20 frames; asserts a
    generous CI-safe bound and prints p95 for the PR record."""
    import json
    import time

    h = Harness()
    h.stream._is_listed = lambda _s: True  # type: ignore[method-assign]  # test-only: 50 symbols
    syms = [f"SYM{i:02d}USDT" for i in range(50)]
    base = json.loads(FRAMES[0])
    lat: list[float] = []
    for sym in syms:
        h.stream.acquire("a", sym)
    for sym in syms:
        for k in range(20):
            f = json.loads(json.dumps(base))
            f["topic"] = f"tickers.{sym}"
            f["data"]["symbol"] = sym
            f["data"]["lastPrice"] = str(100 + k)
            t0 = time.perf_counter()
            await h.stream.handle_frame(json.dumps(f))
            lat.append(time.perf_counter() - t0)
    lat.sort()
    p95 = lat[int(len(lat) * 0.95)] * 1000
    print(f"ticker ingest->bus p95={p95:.3f}ms n={len(lat)}")
    assert p95 <= 20.0
