"""#3806 (E08-Q06 F1): a tick-size change under a LIVE book is a resync, never a delta on two grids.
Gherkin 1 and the F1 repro (#283's strict xfail, promoted), on recorded BTCUSDT frames parsed at
the catalogue's tick size of the moment, as `app.wire_public_ws` parses them (C-13.5)."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from candleviewer.app import build_app_context, wire_public_ws
from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.models import BookDelta
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.ingestion.metrics import ingest_book_resyncs_total, symbol_label
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import frames
from tests.unit.ingestion._fakes import settle
from tests.unit.ws._feed_support import Feed

FRAMES = frames("ws/orderbook_BTCUSDT.jsonl")  # snapshot u=1, then deltas u=2, 3, ...
SYMBOL = "BTCUSDT"
A, B = Decimal("0.1"), Decimal("0.05")  # BTCUSDT's tick size, then half of it (grid B)
SNAP = json.loads(FRAMES[0])["data"]  # 200 bids, 200 asks, each side in ascending price


def _frame(raw: str, topic: str | None = None, **data: Any) -> str:
    """A recorded frame with its topic and some `data` fields (`b`, `a`) replaced."""
    msg = json.loads(raw)
    msg["data"].update(data)
    msg["topic"] = topic or msg["topic"]
    return json.dumps(msg)


def _grid_resyncs() -> float:
    child = ingest_book_resyncs_total.labels(
        symbol=symbol_label(SYMBOL), reason="grid", depth="200"
    )
    return float(child._value.get())


class _Rig:
    """`BookStream` as `app.wire_public_ws` builds it: the catalogue's tick size feeds the parser
    and, when `wired`, the stream's grid check (`tick_size=`)."""

    def __init__(self, *, wired: bool = True) -> None:
        self.tick = A
        self.bus = Bus()
        self.sub = self.bus.subscribe("t", "live.md.*.book", QueuePolicy.NEVER_DROP, maxsize=10**5)
        self.resubs: list[str] = []

        async def resub(topic: str) -> None:
            self.resubs.append(topic)

        kw: dict[str, Any] = {"tick_size": self.tick_size} if wired else {}
        self.stream = BookStream(
            bus=self.bus, env="live", set_desired=lambda _t: None,
            parse_frame=lambda f: parse_book_frame(f, self.tick_size), topic_for=book_topic,
            resubscribe=resub, is_listed=lambda s: s == SYMBOL, touch=lambda _t: None,
            clock=lambda: 0.0, now_us=lambda: 0, rand=lambda: 0.0, **kw,
        )  # fmt: skip
        self.stream.acquire("c", SYMBOL)

    def tick_size(self, _symbol: str) -> Decimal:
        return self.tick

    def drain(self) -> list[object]:
        out: list[object] = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out

    def counts(self) -> tuple[int, int]:
        """(levels, distinct prices) of the book the stream holds; (0, 0) once it is dropped."""
        eng = self.stream.engine(SYMBOL)
        bids, asks = ((), ()) if eng is None or eng.book is None else eng.book.snapshot()
        return len(bids) + len(asks), len({lv.price for lv in (*bids, *asks)})


async def test_tick_size_change_under_a_live_book_resyncs_on_the_new_grid() -> None:
    rig = _Rig()
    for raw in FRAMES[:21]:  # the recorded snapshot and 20 deltas: LIVE on grid A
        await rig.stream.handle_frame(raw)
    eng = rig.stream.engine(SYMBOL)
    assert eng is not None and eng.book is not None and eng.phase is BookPhase.LIVE
    top_ask = eng.book.snapshot()[1][-1].price
    before, resubs = _grid_resyncs(), len(rig.resubs)
    rig.drain()
    rig.tick = B  # the catalogue halves the tick size, as the corpus's SOLUSDT 0.010 -> 0.005
    # The next recorded delta, as an ask above every ask at a price only grid B has: the book's
    # own per-level check admits it (it breaks no order), so only the stream's check refuses it.
    await rig.stream.handle_frame(_frame(FRAMES[21], b=[], a=[[str(top_ask + B), "1.000"]]))
    out = rig.drain()
    statuses = [(o.state, o.reason) for o in out if isinstance(o, BookStatus)]
    assert statuses == [(BookPhase.DESYNCED, "grid")]  # it left LIVE, with reason `grid`
    assert rig.stream.phase(SYMBOL) is BookPhase.SNAPSHOT_PENDING and eng.last_u == 21
    assert not any(isinstance(o, BookDelta) for o in out)  # the delta was never applied
    assert rig.stream.view(SYMBOL, 50) is None  # nothing is served until the rebuild
    assert _grid_resyncs() == before + 1 and len(rig.resubs) == resubs + 1
    await rig.stream.handle_frame(FRAMES[0])  # the venue's snapshot, now parsed on grid B
    await rig.stream.handle_frame(FRAMES[1])  # and the delta after it applies again
    assert eng.phase is BookPhase.LIVE and eng.book is not None and eng.last_u == 2
    bids, asks = eng.book.snapshot()
    assert all(lv.price == lv.price_ticks * B for lv in (*bids, *asks))  # none keyed on grid A
    assert rig.stream.view(SYMBOL, 50) is not None


@pytest.mark.parametrize("wired", [True, False], ids=["stream-check", "book-invariant"])
async def test_f1_a_coarser_tick_size_never_serves_173_levels_at_172_prices(wired: bool) -> None:
    """F1: 172 levels, the tick size doubles, a delta updates a price both grids share. It was a
    second level at that price (173 at 172 prices) on a book still LIVE and served. Unwired
    (`book-invariant`, as main composed it), the book's own check must stop it."""
    rig = _Rig(wired=wired)
    await rig.stream.handle_frame(_frame(FRAMES[0], b=SNAP["b"][-86:], a=SNAP["a"][:86]))
    assert rig.stream.phase(SYMBOL) is BookPhase.LIVE and rig.counts() == (172, 172)
    before = _grid_resyncs()
    rig.tick = 2 * A
    await rig.stream.handle_frame(_frame(FRAMES[1], b=[["631199.8", "2.000"]], a=[]))
    levels, prices = rig.counts()
    assert rig.stream.view(SYMBOL, 200) is None, f"served {levels} levels at {prices} prices"
    assert rig.stream.phase(SYMBOL) is BookPhase.SNAPSHOT_PENDING
    assert _grid_resyncs() == before + 1 and rig.resubs == [book_topic(SYMBOL)]


async def test_a_retired_tiers_late_delta_on_a_new_grid_leaves_the_active_tier_live() -> None:
    rig = _Rig()
    for raw in FRAMES[:3]:  # LIVE at depth 200 on grid A
        await rig.stream.handle_frame(raw)
    await rig.stream.change_depth(SYMBOL, 50)
    rig.tick = B
    top50 = _frame(FRAMES[0], "orderbook.50.BTCUSDT", b=SNAP["b"][-50:], a=SNAP["a"][:50])
    await rig.stream.handle_frame(top50)  # the depth-50 snapshot on grid B: the tiers swap
    eng = rig.stream.engine(SYMBOL)
    assert eng is not None and eng.depth == 50 and eng.phase is BookPhase.LIVE
    await rig.stream.handle_frame(FRAMES[3])  # a late depth-200 delta, now on grid B
    assert rig.stream.engine(SYMBOL) is eng and eng.phase is BookPhase.LIVE


async def test_the_composition_root_passes_the_catalogue_tick_size_to_the_book_stream() -> None:
    """`wire_public_ws` wires `tick_size=`: its stream refuses the Gherkin 1 delta, which only the
    stream's check sees (a stand-in instrument catalogue)."""
    ctx = build_app_context()
    wire_public_ws(ctx)
    inst = SimpleNamespace(tick_size=A, status="trading", launch_time=0)
    ctx.ingestion.attach_instruments(cast(Any, SimpleNamespace(snapshot=lambda: {SYMBOL: inst})))
    stream = ctx.ingestion.books
    assert isinstance(stream, BookStream)
    stream.acquire("c", SYMBOL)
    for raw in FRAMES[:2]:
        await stream.handle_frame(raw)
    inst.tick_size = B
    await stream.handle_frame(_frame(FRAMES[2], b=[], a=[["631230.05", "1.000"]]))  # above all
    assert stream.phase(SYMBOL) is BookPhase.SNAPSHOT_PENDING
    await stream.stop()
    await settle()  # the B14 chart's spawned stop


async def test_the_composition_root_gives_the_book_supervisor_the_machines_feed() -> None:
    """E17-T08: `wire_public_ws(machine_feed=)` reaches the B14 supervisor, so a book that goes live
    is `machines.book:{symbol}.state` (an unscoped entry) and a stopped stream takes it away."""
    feed, ch = Feed(), f"machines.book:{SYMBOL}.state"
    ctx = build_app_context()
    wire_public_ws(ctx, machine_feed=feed.port)
    inst = SimpleNamespace(tick_size=A, status="trading", launch_time=0)
    ctx.ingestion.attach_instruments(cast(Any, SimpleNamespace(snapshot=lambda: {SYMBOL: inst})))
    stream = ctx.ingestion.books
    assert isinstance(stream, BookStream)
    stream.acquire("c", SYMBOL)
    await stream.handle_frame(FRAMES[0])  # the snapshot: the engine and its B14 chart go live
    await settle(64)
    served = feed.served(ch)
    assert served is not None and (served["state"], served["tags"]) == ("live", ["consumable"])
    assert feed.scope_missing() == 0
    await stream.stop()
    await settle(64)  # the chart's spawned stop
    assert feed.served(ch) is None
