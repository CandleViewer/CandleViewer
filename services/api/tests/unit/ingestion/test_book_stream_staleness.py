"""#3807 (E08-Q06 F2): a released book whose grace has run out is never served frozen as live.

`BookStream` drops the upstream topic and forgets the retained book when a released symbol's
grace (`DEFAULT_GRACE_S`, US-MKT-005) ends: on the stream's own tick even when no demand change
comes, and at once when a frame for it arrives. A later acquire subscribes again and is served
a fresh snapshot. And a served book's `stale` comes from its last applied frame, against the
watchdog's book limit (#2487 F4, `25-market-data-trust-contract.md` section 3). Recorded corpus,
fake clock, no network (C-13.5, C-13.7).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, Request
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.orderbook import make_orderbook_router
from candleviewer.book.models import BookPhase
from candleviewer.book.resync import HealthSink
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.ingestion.metrics import ingest_book_live, symbol_label
from candleviewer.ingestion.planner import DEFAULT_GRACE_S
from candleviewer.ingestion.watchdog import STALENESS_S
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import frames

#: [0] snapshot u=1, then deltas u=2.. (a hole at [2700]); [4000] a later snapshot u=1.
BOOK = frames("ws/orderbook_BTCUSDT.jsonl")
TOPIC = "orderbook.200.BTCUSDT"
WS = "ws:book:50"  # a WS book subscription's demand key
LIMIT_S = STALENESS_S["book"]  # the watchdog's book limit: no new SLO


async def _nothing(_arg: str) -> None:
    """A resubscribe, or a B14 health sink, that does nothing."""


class _Charts:
    """B14 supervision, faked: a log of the charts attached and detached."""

    def __init__(self) -> None:
        self.log: list[str] = []

    async def attach(self, key: str, symbol: str) -> HealthSink:
        self.log.append(f"attach {key}")
        return _nothing

    def detach(self, key: str) -> None:
        self.log.append(f"detach {key}")


class _Rig:
    """A `BookStream` on the corpus with a fake clock, wired as `app.wire_public_ws` wires it
    (the catalogue's tick size, a B14 supervisor); `ticked()` runs its scripted ticks."""

    def __init__(self, ticks: tuple[float, ...] = ()) -> None:
        self.t = 0.0
        self.tick_size = Decimal("0.1")  # BTCUSDT's tick size in the catalogue
        self.desired: list[set[str]] = []
        self.slept: list[float] = []
        self.bus, self.charts = Bus(), _Charts()
        self._ticks = list(ticks)
        self._parked = asyncio.Event()
        self.stream = BookStream(
            bus=self.bus,
            env="live",
            set_desired=lambda topics: self.desired.append(set(topics)),
            parse_frame=lambda f: parse_book_frame(f, lambda _s: self.tick_size),
            topic_for=book_topic,
            resubscribe=_nothing,
            is_listed=lambda s: s == "BTCUSDT",
            touch=lambda _t: None,
            clock=lambda: self.t,
            now_us=lambda: 0,
            sleep=self._sleep,
            tick_size=lambda _s: self.tick_size,
            supervisor=self.charts,
        )

    async def _sleep(self, delay: float) -> None:
        self.slept.append(delay)
        if self._ticks:  # the next tick runs at this clock reading
            self.t = self._ticks.pop(0)
            return
        self._parked.set()
        await asyncio.Event().wait()  # until stop() cancels the loop

    @contextlib.asynccontextmanager
    async def ticked(self) -> AsyncIterator[None]:
        """Start the stream, run every scripted tick, and stop it on exit, a failure too."""
        await self.stream.start()
        try:
            async with asyncio.timeout(5):  # hang guard only
                await self._parked.wait()
            yield
        finally:
            await self.stream.stop()

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


def _live_gauge() -> float:
    return float(ingest_book_live.labels(symbol=symbol_label("BTCUSDT"))._value.get())


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


async def test_a_frame_after_the_grace_forgets_a_retained_book_that_is_not_live() -> None:
    """A reconnect left the released book resyncing: the first frame past its grace forgets it."""
    rig = _Rig()
    await rig.live_then_released()
    await rig.stream.invalidate("reconnect")
    assert rig.stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING
    rig.t = DEFAULT_GRACE_S + 1
    await rig.feed(BOOK[4000:4001])  # the socket's re-sent snapshot, past the grace
    assert rig.stream.engine("BTCUSDT") is None and TOPIC not in rig.desired[-1]


@pytest.mark.parametrize(
    ("at", "kept"), [(DEFAULT_GRACE_S - 1, True), (DEFAULT_GRACE_S + 1, False)]
)
async def test_the_tick_alone_ends_a_released_books_grace(at: float, kept: bool) -> None:
    rig = _Rig(ticks=(at,))
    await rig.live_then_released()  # then no frame and no demand change
    async with rig.ticked():
        assert (rig.stream.engine("BTCUSDT") is not None) is kept
        assert (TOPIC in rig.desired[-1]) is kept
        assert _live_gauge() == (1.0 if kept else 0.0)  # a forgotten book is not counted LIVE
        assert max(rig.slept) <= 0.25  # a grace ends at most one 0.25 s tick late


async def test_the_tick_drops_a_released_topic_that_never_got_a_frame() -> None:
    """The feed never answered, so no book was built; the topic still goes as the grace ends."""
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    rig.stream.acquire(WS, "BTCUSDT")
    rig.stream.release(WS, "BTCUSDT")
    async with rig.ticked():
        assert TOPIC in rig.desired[0] and TOPIC not in rig.desired[-1]


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
    async with rig.ticked():
        assert engine is not None and rig.stream.engine("BTCUSDT") is engine
        assert TOPIC in rig.desired[-1]


async def test_a_new_subscription_after_idle_gets_a_fresh_snapshot_not_the_frozen_book() -> None:
    """Gherkin 2: the engine the WS book snapshot reads (#2196) is rebuilt from a new snapshot."""
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    await rig.live_then_released()
    async with rig.ticked():
        rig.t = 3600.0
        rig.stream.acquire(WS, "BTCUSDT")  # a new WS book subscription after idle
        assert TOPIC in rig.desired[-1] and rig.stream.engine("BTCUSDT") is None
        await rig.feed(BOOK[4000:4010])  # the new subscription's snapshot (u=1) and deltas

        engine = rig.stream.engine("BTCUSDT")
        assert engine is not None and engine.phase is BookPhase.LIVE and engine.last_u == 10
        view = rig.stream.view("BTCUSDT", 50)
        assert view is not None and view.snapshot.update_id == 10


async def test_a_forgotten_book_detaches_its_chart_and_a_rebuilt_one_attaches_anew() -> None:
    """B14 supervision follows the book: one detach as the grace ends, one attach on rebuild."""
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    await rig.live_then_released()
    async with rig.ticked():
        assert rig.charts.log == ["attach live:BTCUSDT:200", "detach live:BTCUSDT:200"]
        rig.stream.acquire(WS, "BTCUSDT")
        await rig.feed(BOOK[4000:4001])
        assert rig.charts.log[2:] == ["attach live:BTCUSDT:200"]  # a new chart, none detached


async def test_a_forgotten_book_takes_its_grid_with_it() -> None:
    """#3806's per-book grid goes with the book: the rebuilt book keeps the deltas it gets
    before its snapshot, though the tick size changed while the symbol was idle."""
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    await rig.live_then_released()  # snapshotted on grid 0.1
    async with rig.ticked():
        rig.tick_size = Decimal("0.05")  # the catalogue halves the tick size meanwhile
        rig.stream.acquire(WS, "BTCUSDT")
        await rig.feed(BOOK[1:3])  # deltas before the new snapshot: buffered, not refused
        await rig.feed(BOOK[:1])  # the snapshot replays them
        engine = rig.stream.engine("BTCUSDT")
        assert engine is not None and engine.phase is BookPhase.LIVE and engine.last_u == 3


async def test_a_rest_read_after_the_grace_is_never_the_frozen_book() -> None:
    """Gherkin 1 through `GET /market/orderbook`: the tick at 31 s had forgotten the book, so the
    read answers 503 until the fresh snapshot it asked for, and is then served from that."""
    rig = _Rig(ticks=(DEFAULT_GRACE_S + 1,))
    await rig.live_then_released()
    async with rig.ticked():
        r = await _get_orderbook(rig.stream)
        assert r.status_code == 503 and "resynchronising" in r.text  # never u=100 as live
        assert TOPIC in rig.desired[-1]  # the read subscribed the topic again
        await rig.feed(BOOK[4000:4010])  # its fresh snapshot (u=1) and deltas

        r = await _get_orderbook(rig.stream)
        assert r.status_code == 200 and r.json()["u"] == 10 and r.json()["stale"] is False


# ---- #2487 F4: a served book's `stale` comes from its last applied frame -------------------


def _stale(rig: _Rig) -> bool:
    view = rig.stream.view("BTCUSDT", 50)
    assert view is not None  # LIVE: served
    return view.stale


async def test_view_is_stale_once_no_frame_applied_within_the_limit_and_fresh_after_one() -> None:
    rig = _Rig()
    rig.stream.acquire(WS, "BTCUSDT")
    await rig.feed(BOOK[:10])  # LIVE; the last frame applied at t=0
    rig.t = LIMIT_S - 0.001
    assert _stale(rig) is False
    rig.t = LIMIT_S  # `now - last >= limit`, as the watchdog counts it
    assert _stale(rig) is True
    await rig.feed(BOOK[10:11])
    assert _stale(rig) is False


async def test_only_frames_the_served_tier_takes_keep_it_fresh() -> None:
    """While a depth change warms a second tier, its frames never refresh the served one."""
    rig = _Rig()
    rig.stream.acquire(WS, "BTCUSDT")
    await rig.feed(BOOK[:10])  # depth 200 LIVE at t=0
    await rig.stream.change_depth("BTCUSDT", 50)  # a depth-50 tier warms, muted
    rig.t = LIMIT_S
    await rig.feed([BOOK[1].replace("orderbook.200.", "orderbook.50.")])  # buffered by tier 50
    assert rig.stream.phase("BTCUSDT") is BookPhase.LIVE and _stale(rig) is True


async def test_is_stale_whenever_the_book_is_not_live() -> None:
    """No book, or a book not LIVE, is stale."""
    rig = _Rig()
    assert rig.stream.is_stale("BTCUSDT")  # no book yet
    rig.stream.acquire(WS, "BTCUSDT")
    await rig.feed(BOOK[1:3])  # deltas before the snapshot: pending
    assert rig.stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING
    assert rig.stream.is_stale("BTCUSDT")
    await rig.feed(BOOK[:1])  # the snapshot replays the buffered deltas: LIVE at u=3
    assert not rig.stream.is_stale("BTCUSDT")
    await rig.feed(BOOK[2700:2701])  # a sequence gap: resyncing
    assert rig.stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING
    assert rig.stream.is_stale("BTCUSDT")


async def test_a_book_live_before_its_snapshot_frame_returns_is_served_stale() -> None:
    """Bus backpressure holds the LIVE status the snapshot frame publishes: the book is LIVE but
    no frame has finished applying yet, so a read meanwhile is stale, never an error."""
    rig = _Rig()
    held = rig.bus.subscribe("held", "live.md.BTCUSDT.book", QueuePolicy.NEVER_DROP, maxsize=1)
    rig.stream.acquire(WS, "BTCUSDT")
    applying = asyncio.create_task(rig.feed(BOOK[:1]))
    await asyncio.wait_for(held.get(), 5)  # the book went out; its LIVE status waits for room
    assert rig.stream.phase("BTCUSDT") is BookPhase.LIVE and _stale(rig) is True
    await applying
    assert _stale(rig) is False


async def test_a_rest_read_after_the_grace_with_no_tick_is_served_stale() -> None:
    """Gherkin 1, other branch: nothing ran since the release (no frame, no tick), so the
    retained book missed no frame but has been silent for 31 s: 200 with `stale: true`."""
    rig = _Rig()
    await rig.live_then_released()
    rig.t = DEFAULT_GRACE_S + 1

    r = await _get_orderbook(rig.stream)
    assert r.status_code == 200 and r.json()["stale"] is True and r.json()["u"] == 100


@settings(max_examples=50, deadline=None)
@given(steps=st.lists(st.tuples(st.floats(0.0, 3.0), st.booleans()), max_size=30))
def test_property_a_book_served_fresh_applied_a_frame_within_the_limit(
    steps: list[tuple[float, bool]],
) -> None:
    async def run() -> None:
        rig = _Rig()
        rig.stream.acquire(WS, "BTCUSDT")
        await rig.feed(BOOK[:1])
        applied, sent = rig.t, 1
        for dt, frame in steps:
            rig.t += dt
            if frame:  # the next in-sequence delta
                await rig.feed(BOOK[sent : sent + 1])
                applied, sent = rig.t, sent + 1
            assert _stale(rig) is (rig.t - applied >= LIMIT_S)

    asyncio.run(run())
