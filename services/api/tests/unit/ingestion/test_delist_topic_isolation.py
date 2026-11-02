"""#1913: a silent/delisted topic never recycles the shared public socket, and a
catalogue flip to non-`trading` tears held demand down (chaos scenario 9 —
promotes the two strict xfails in `tests/chaos/ingestion/test_s09_instrument_delist.py`
from PR #1921). Fake clock + fake transport; no network."""

from __future__ import annotations

import asyncio
import json
import random
from decimal import Decimal

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, TopicPattern
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.exchange.bybit.public_ws import topic_kind
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.ingestion.watchdog import FeedHealthEvent, StalenessWatchdog
from candleviewer.orderbook_wiring import BookStream

BOOK_BTC, BOOK_ETH, BOOK_LUNA = (f"orderbook.50.{s}" for s in ("BTCUSDT", "ETHUSDT", "LUNAUSDT"))


class _Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


class _Sock:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False
        self.q: asyncio.Queue[str] = asyncio.Queue()
        self.first_send = asyncio.Event()

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))
        self.first_send.set()

    async def recv(self, max_bytes: int) -> str:
        return await self.q.get()

    async def close(self) -> None:
        self.closed = True


class _Rig:
    """ConnectionManager over fake sockets; `alive` topics get a frame every tick."""

    def __init__(self, topics: set[str], alive: set[str]) -> None:
        self.clk, self.socks, self.alive = _Clock(), list[_Sock](), set(alive)
        self.frames: list[str] = []
        self.health: list[FeedHealthEvent] = []
        self.bus = Bus()
        self.sub = self.bus.subscribe("t", "*.health.*.*", QueuePolicy.NEVER_DROP, maxsize=10_000)
        self.watchdog = StalenessWatchdog(self.clk, self.health.append, kind_of=topic_kind)
        self.guard = ConnectionRateGuard(self.clk)
        self.m = ConnectionManager(
            self._connect,
            SubscriptionPlanner(),
            self.watchdog,
            ReconnectPolicy(rng=random.Random(3)),  # noqa: S311  (deterministic jitter)
            self.guard,
            self._on_message,
            sleep=self._sleep,
            bus=self.bus,
            ping_interval_s=10_000.0,
        )
        self.m.set_desired(topics)
        self.reopened = asyncio.Event()

    async def _connect(self) -> _Sock:
        self.socks.append(_Sock())
        if len(self.socks) == 2:
            self.reopened.set()
        return self.socks[-1]

    def states(self) -> list[str]:
        out: list[str] = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait().state)
        return out

    def _on_message(self, frame: str) -> None:
        topic = json.loads(frame)["topic"]
        self.frames.append(topic)
        self.watchdog.touch(topic)

    async def _sleep(self, s: float) -> None:
        if s >= 1000:  # the ping loop: parked, so it never jumps the fake clock
            await asyncio.Event().wait()
        self.clk.t += s
        if self.socks and not self.socks[-1].closed:
            for t in sorted(self.alive):
                self.socks[-1].q.put_nowait(json.dumps({"topic": t}))
        for _ in range(5):
            await asyncio.sleep(0)

    async def run_for(self, seconds: float) -> None:
        start = self.clk.t
        for _ in range(20_000):
            if self.clk.t - start >= seconds:
                return
            await asyncio.sleep(0)
        raise AssertionError("fake clock did not advance")

    def sent(self, op: str, sock: int = 0) -> list[str]:
        return [a for f in self.socks[sock].sent if f["op"] == op for a in f["args"]]  # type: ignore[attr-defined]


async def test_one_silent_topic_resubscribes_only_that_topic_and_keeps_socket() -> None:
    rig = _Rig({BOOK_BTC, BOOK_ETH, BOOK_LUNA}, alive={BOOK_BTC, BOOK_ETH})
    opens_before = rig.guard.remaining()
    await rig.m.start()
    await rig.run_for(20.0)
    assert len(rig.socks) == 1 and not rig.socks[0].closed  # zero new sockets
    assert rig.m.state() == "open"
    assert rig.sent("unsubscribe") == [BOOK_LUNA]  # once per staleness episode, not a loop
    assert rig.sent("subscribe").count(BOOK_LUNA) == 2  # initial + one resubscribe
    assert rig.m.topic_resubscribes == 1
    assert rig.guard.remaining() == opens_before - 1  # SR-039: only the first dial counted
    late = rig.frames[-20:]
    assert BOOK_BTC in late and BOOK_ETH in late  # other symbols keep flowing
    assert [h.topic for h in rig.health if h.state == "stale"] == [BOOK_LUNA]
    await rig.m.stop()


async def test_all_topics_silent_still_recycles_socket() -> None:
    rig = _Rig({BOOK_BTC, BOOK_LUNA}, alive=set())
    await rig.m.start()
    async with asyncio.timeout(10):
        await rig.reopened.wait()
        await rig.socks[1].first_send.wait()
    assert rig.socks[0].closed
    assert set(rig.sent("subscribe", 1)) == {BOOK_BTC, BOOK_LUNA}  # full subscribe
    assert "resubscribing" in rig.states()  # a reopened socket still reports it
    await rig.m.stop()


async def test_dropped_demand_is_unsubscribed_on_live_socket() -> None:
    rig = _Rig({BOOK_BTC, BOOK_LUNA}, alive={BOOK_BTC, BOOK_LUNA})
    await rig.m.start()
    await rig.run_for(1.0)
    subs_before = rig.sent("subscribe")
    rig.states()
    rig.m.set_desired({BOOK_BTC})
    await rig.run_for(1.0)
    assert rig.sent("unsubscribe") == [BOOK_LUNA]
    assert rig.sent("subscribe") == subs_before  # no re-subscribe of the rest
    assert "resubscribing" not in rig.states()
    assert len(rig.socks) == 1 and rig.m.state() == "open"
    await rig.m.stop()


async def test_live_add_subscribes_only_the_new_topic() -> None:
    rig = _Rig({BOOK_BTC}, alive={BOOK_BTC, BOOK_ETH})
    await rig.m.start()
    await rig.run_for(1.0)
    rig.states()
    rig.m.set_desired({BOOK_BTC, BOOK_ETH})
    await rig.run_for(1.0)
    live_add = rig.socks[0].sent[1:]
    assert [{k: v for k, v in f.items() if k != "req_id"} for f in live_add] == [
        {"op": "subscribe", "args": [BOOK_ETH]}
    ]
    assert all("req_id" in f for f in live_add)  # #1955
    assert "resubscribing" not in rig.states()
    assert len(rig.socks) == 1 and rig.m.state() == "open"
    late = rig.frames[-6:]
    assert BOOK_BTC in late and BOOK_ETH in late  # reader/session kept running
    await rig.m.stop()


# ---- catalogue flip -> demand dropped + `delisted` published (all three streams) ----


class _Catalogue:
    def __init__(self) -> None:
        self.listed = {"BTCUSDT", "LUNAUSDT"}

    def __call__(self, symbol: str) -> bool:
        return symbol in self.listed


def _health(bus: Bus) -> object:
    pattern = TopicPattern(env="live", domain="health", detail="feed")
    return bus.subscribe("h", pattern, QueuePolicy.NEVER_DROP)


def _drain(sub: object) -> list[tuple[str, str]]:
    q = sub.queue  # type: ignore[attr-defined]
    out: list[tuple[str, str]] = []
    while not q.empty():
        ev = q.get_nowait()
        out.append((ev.topic, ev.state))
    return out


async def _noop_resub(_t: str) -> None:
    return None


def _streams(bus: Bus, cat: _Catalogue, desired: dict[str, set[str]]) -> list[object]:
    def setter(name: str) -> object:
        return lambda t: desired.__setitem__(name, set(t))

    return [
        TradeStream(
            bus=bus,
            env="live",
            set_desired=setter("trade"),  # type: ignore[arg-type]
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=cat,
            touch=lambda _t: None,
            tick_size=lambda _s: Decimal("0.1"),
            clock=lambda: 0.0,
        ),
        TickerStream(
            bus=bus,
            env="live",
            set_desired=setter("ticker"),  # type: ignore[arg-type]
            parse_frame=parse_ticker_frame,
            topic_for=ticker_topic,
            is_listed=cat,
            touch=lambda _t: None,
            clock=lambda: 0.0,
        ),
        BookStream(
            bus=bus,
            env="live",
            set_desired=setter("book"),  # type: ignore[arg-type]
            parse_frame=lambda f: parse_book_frame(f, lambda _s: Decimal("0.1")),
            topic_for=book_topic,
            resubscribe=_noop_resub,
            is_listed=cat,
            touch=lambda _t: None,
            clock=lambda: 0.0,
        ),
    ]


async def test_catalogue_delist_drops_demand_and_publishes_delisted() -> None:
    bus, cat, desired = Bus(), _Catalogue(), dict[str, set[str]]()
    sub = _health(bus)
    streams = _streams(bus, cat, desired)
    for s in streams:
        s.acquire("chart", "BTCUSDT")  # type: ignore[attr-defined]
        s.acquire("chart", "LUNAUSDT")  # type: ignore[attr-defined]
    assert all(any("LUNAUSDT" in t for t in ts) for ts in desired.values())
    cat.listed.discard("LUNAUSDT")  # refresh flips LUNAUSDT to Closed
    for s in streams:
        assert await s.prune_unlisted() == ["LUNAUSDT"]  # type: ignore[attr-defined]
    for ts in desired.values():
        assert ts and not any("LUNAUSDT" in t for t in ts)  # demand dropped, BTC kept
    delisted = [t for t, st in _drain(sub) if st == "delisted"]
    assert len(delisted) == 3 and all("LUNAUSDT" in t for t in delisted)
    for s in streams:  # idempotent: nothing left to prune
        assert await s.prune_unlisted() == []  # type: ignore[attr-defined]


async def test_service_prune_fans_out_to_every_attached_stream() -> None:
    bus, cat, desired = Bus(), _Catalogue(), dict[str, set[str]]()
    trades, tickers, books = _streams(bus, cat, desired)
    svc = IngestionService()
    svc.attach_trades(trades)  # type: ignore[arg-type]
    svc.attach_tickers(tickers)  # type: ignore[arg-type]
    svc.attach_books(books)  # type: ignore[arg-type]
    for s in (trades, tickers, books):
        s.acquire("chart", "LUNAUSDT")  # type: ignore[attr-defined]
    cat.listed.clear()
    await svc.prune_unlisted()
    assert desired == {"trade": set(), "ticker": set(), "book": set()}


async def test_delist_prune_on_live_socket_is_a_single_unsubscribe() -> None:
    btc, luna = ticker_topic("BTCUSDT"), ticker_topic("LUNAUSDT")
    rig, cat = _Rig(set(), alive={btc, luna}), _Catalogue()
    stream = TickerStream(
        bus=rig.bus,
        env="live",
        set_desired=rig.m.set_desired,
        parse_frame=parse_ticker_frame,
        topic_for=ticker_topic,
        is_listed=cat,
        touch=lambda _t: None,
        clock=lambda: 0.0,
    )
    stream.acquire("chart", "BTCUSDT")
    stream.acquire("chart", "LUNAUSDT")
    await rig.m.start()
    await rig.run_for(1.0)
    subs_before = rig.sent("subscribe")
    rig.states()
    cat.listed.discard("LUNAUSDT")
    assert await stream.prune_unlisted() == ["LUNAUSDT"]
    await rig.run_for(1.0)
    assert rig.sent("unsubscribe") == [luna]
    assert rig.sent("subscribe") == subs_before
    states = rig.states()
    assert "resubscribing" not in states and "delisted" in states
    assert len(rig.socks) == 1 and rig.m.state() == "open"
    await rig.m.stop()
