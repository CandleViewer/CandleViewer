"""#3807 (E08-Q06 F2): a released book whose grace has run out is never served frozen as live.

`BookStream` drops the upstream topic and forgets the retained book when a released symbol's
grace (`DEFAULT_GRACE_S`, US-MKT-005) ends: on the stream's own tick even when no demand change
comes, and at once when a frame for it arrives. A later acquire subscribes again and is served
a fresh snapshot. Recorded corpus, fake clock, no network (C-13.5, C-13.7).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, Request

from candleviewer.api.orderbook import make_orderbook_router
from candleviewer.book.models import BookPhase
from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.ingestion.planner import DEFAULT_GRACE_S
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import frames

#: [0] snapshot u=1, then deltas u=2.. (a hole at [2700]); [4000] a later snapshot u=1.
BOOK = frames("ws/orderbook_BTCUSDT.jsonl")
TOPIC = "orderbook.200.BTCUSDT"
WS = "ws:book:50"  # a WS book subscription's demand key


class _Rig:
    """A `BookStream` on the corpus with a fake clock; `tick()` runs its scripted ticks."""

    def __init__(self, ticks: tuple[float, ...] = ()) -> None:
        self.t = 0.0
        self.desired: list[set[str]] = []
        self._ticks = list(ticks)
        self._parked = asyncio.Event()
        self.stream = BookStream(
            bus=Bus(),
            env="live",
            set_desired=lambda topics: self.desired.append(set(topics)),
            parse_frame=lambda f: parse_book_frame(f, lambda _s: Decimal("0.1")),
            topic_for=book_topic,
            resubscribe=self._resubscribe,
            is_listed=lambda s: s == "BTCUSDT",
            touch=lambda _t: None,
            clock=lambda: self.t,
            now_us=lambda: 0,
            sleep=self._sleep,
        )

    @staticmethod
    async def _resubscribe(_topic: str) -> None:
        return None

    async def _sleep(self, _delay: float) -> None:
        if self._ticks:  # the next tick runs at this clock reading
            self.t = self._ticks.pop(0)
            return
        self._parked.set()
        await asyncio.Event().wait()  # until stop() cancels the loop

    async def tick(self) -> None:
        """Start the stream and return once every scripted tick has run."""
        await self.stream.start()
        async with asyncio.timeout(5):  # hang guard only
            await self._parked.wait()

    async def feed(self, raw: list[str]) -> None:
        for frame in raw:
            await self.stream.handle_frame(frame)

    async def live_then_released(self) -> None:
        """A WS consumer holds the book to u=100 at t=0, then releases it."""
        self.stream.acquire(WS, "BTCUSDT")
        await self.feed(BOOK[:100])
        self.stream.release(WS, "BTCUSDT")


class _Viewer:
    def has(self, permission: str) -> bool:
        return permission == "marketdata:read"


class _Resolver:
    def resolve(self, request: Request) -> _Viewer:
        return _Viewer()


async def _get_orderbook(stream: BookStream) -> httpx.Response:
    app = FastAPI()
    app.include_router(make_orderbook_router(lambda: stream, principal_resolver=_Resolver()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/market/orderbook", params={"symbol": "BTCUSDT", "depth": 50})


async def test_f2_a_released_book_is_never_served_frozen_as_live_after_its_grace() -> None:
    """The E08-Q06 charter-2 probe (#283): frames go on arriving after the grace."""
    rig = _Rig()
    await rig.live_then_released()
    rig.t = 3600.0  # an hour on; the upstream feed kept running
    await rig.feed(BOOK[100:400])

    view = rig.stream.view("BTCUSDT", 50)
    served_live = (
        rig.stream.phase("BTCUSDT") is BookPhase.LIVE and view is not None and not view.stale
    )
    assert not served_live, "a book that stopped applying frames an hour ago is served as live"
    assert TOPIC not in rig.desired[-1]  # the first ignored frame dropped the topic upstream


@pytest.mark.parametrize(
    ("at", "kept"), [(DEFAULT_GRACE_S - 1, True), (DEFAULT_GRACE_S + 1, False)]
)
async def test_the_tick_alone_ends_a_released_books_grace(at: float, kept: bool) -> None:
    rig = _Rig(ticks=(at,))
    await rig.live_then_released()  # then no frame and no demand change
    await rig.tick()
    assert (rig.stream.engine("BTCUSDT") is not None) is kept
    assert (TOPIC in rig.desired[-1]) is kept
    await rig.stream.stop()


@pytest.mark.parametrize("hold", ["reacquired_in_grace", "second_consumer"])
async def test_a_book_still_held_outlives_the_grace(hold: str) -> None:
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    if hold == "second_consumer":
        rig.stream.acquire("rest-orderbook", "BTCUSDT")
    await rig.live_then_released()
    engine = rig.stream.engine("BTCUSDT")
    if hold == "reacquired_in_grace":
        rig.t = DEFAULT_GRACE_S - 10
        rig.stream.acquire(WS, "BTCUSDT")
    await rig.tick()
    assert engine is not None and rig.stream.engine("BTCUSDT") is engine
    assert TOPIC in rig.desired[-1]
    await rig.stream.stop()


async def test_a_new_subscription_after_idle_gets_a_fresh_snapshot_not_the_frozen_book() -> None:
    """Gherkin 2: the engine the WS book snapshot reads (#2196) is rebuilt from a new snapshot."""
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    await rig.live_then_released()
    await rig.tick()
    rig.t = 3600.0
    rig.stream.acquire(WS, "BTCUSDT")  # a new WS book subscription after idle
    assert TOPIC in rig.desired[-1] and rig.stream.engine("BTCUSDT") is None
    await rig.feed(BOOK[4000:4010])  # the new subscription's snapshot (u=1) and deltas

    engine = rig.stream.engine("BTCUSDT")
    assert engine is not None and engine.phase is BookPhase.LIVE and engine.last_u == 10
    view = rig.stream.view("BTCUSDT", 50)
    assert view is not None and view.snapshot.update_id == 10
    await rig.stream.stop()


async def test_a_rest_read_after_the_grace_is_never_the_frozen_book() -> None:
    """Gherkin 1 through `GET /market/orderbook`: the tick at 31 s had dropped the book."""
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    await rig.live_then_released()
    await rig.tick()

    r = await _get_orderbook(rig.stream)
    assert r.status_code == 503  # resynchronising until a fresh snapshot: never u=100 as live
    assert TOPIC in rig.desired[-1]  # the read subscribed the topic again
    await rig.stream.stop()
