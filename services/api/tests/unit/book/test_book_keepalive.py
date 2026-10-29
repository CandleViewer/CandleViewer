"""E21-T01 Gherkin "Depth-1 keepalive is not a book event" (BQ-1; `book/resync.py`).

Bybit re-sends the depth-1 snapshot every 3 s while the book is unchanged, at the same `u`. Before
#604 the engine took any snapshot while LIVE as a server reset and desynced. No depth-1 capture
exists (C-13.5), so the frame is derived from the recorded depth-200 snapshot (the fixture
directory's README names the derivation): its best bid and best ask, on the `orderbook.1` topic,
at the same `u`, `seq` and times. The resend is that frame again 3 s later.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from candleviewer.book.models import BestQuoteEvent, BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, TopicPattern
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import TICKS, frames

SYMBOL = "BTCUSDT"
KEEPALIVE_S = 3


def depth1_frame(shift_ms: int = 0, *, bid_qty: str | None = None) -> str:
    """The depth-1 snapshot derived from the recorded `orderbook.200.BTCUSDT` snapshot (frame 0)."""
    msg: dict[str, Any] = json.loads(frames("ws/orderbook_BTCUSDT.jsonl")[0])
    data = msg["data"]
    bid = max(data["b"], key=lambda lv: Decimal(lv[0]))
    ask = min(data["a"], key=lambda lv: Decimal(lv[0]))
    if bid_qty is not None:
        bid = [bid[0], bid_qty]
    msg["topic"] = f"orderbook.1.{SYMBOL}"
    msg["ts"] += shift_ms
    msg["cts"] = msg.get("cts", msg["ts"]) + shift_ms
    data["b"], data["a"] = [bid], [ask]
    return json.dumps(msg)


def _parse(frame: str) -> BookSnapshot:
    ev = parse_book_frame(frame, TICKS.get)
    assert isinstance(ev, BookSnapshot) and ev.depth == 1
    return ev


async def test_depth_1_keepalive_is_not_a_book_event_for_the_engine() -> None:
    out: list[object] = []

    async def publish(ev: object) -> None:
        out.append(ev)

    async def resub() -> None:
        return None

    eng = BookEngine(symbol=SYMBOL, depth=1, publish=publish, resubscribe=resub, now_us=lambda: 0)
    await eng.start()
    await eng.on_event(_parse(depth1_frame()))
    assert eng.phase is BookPhase.LIVE
    published = len(out)
    await eng.on_event(_parse(depth1_frame(KEEPALIVE_S * 1000)))  # the unchanged resend
    assert eng.phase is BookPhase.LIVE and eng.resync_count == 0
    assert out[published:] == []  # no BookDelta, no BookSnapshot, no status: no book event


async def test_depth_1_keepalive_a_changed_resend_is_still_a_server_reset() -> None:
    out: list[object] = []

    async def publish(ev: object) -> None:
        out.append(ev)

    async def resub() -> None:
        return None

    eng = BookEngine(symbol=SYMBOL, depth=1, publish=publish, resubscribe=resub, now_us=lambda: 0)
    await eng.start()
    await eng.on_event(_parse(depth1_frame()))
    await eng.on_event(_parse(depth1_frame(KEEPALIVE_S * 1000, bid_qty="9.999")))
    status = [o for o in out if isinstance(o, BookStatus)][-1]
    assert status.state is BookPhase.DESYNCED and status.reason == "server_reset"
    assert eng.phase is BookPhase.SNAPSHOT_PENDING and eng.resync_count == 1


async def test_depth_1_keepalive_is_not_a_book_event_no_delta_and_no_quote_change() -> None:
    """Through the production `BookStream` (default tier 1 here): the resend publishes no book
    event on `.book` and no `BestQuoteEvent` on `.quote` (the quote changed only at going live)."""
    bus = Bus()
    book_q = bus.subscribe(
        "t-book", TopicPattern(env="live", domain="md", symbol=SYMBOL, detail="book"),
        QueuePolicy.NEVER_DROP, maxsize=64,
    )  # fmt: skip
    quote_q = bus.subscribe(
        "t-quote", TopicPattern(env="live", domain="md", symbol=SYMBOL, detail="quote"),
        QueuePolicy.NEVER_DROP, maxsize=64,
    )  # fmt: skip

    async def noop(_: object = None) -> None:
        return None

    stream = BookStream(
        bus=bus, env="live", set_desired=lambda _t: None, topic_for=book_topic,
        parse_frame=lambda f: parse_book_frame(f, TICKS.get), resubscribe=noop,
        is_listed=lambda _s: True, touch=lambda _t: None, clock=lambda: 0.0,
        now_us=lambda: 0, rand=lambda: 0.0, default_depth=1,
    )  # fmt: skip
    stream.acquire("t", SYMBOL)
    await stream.handle_frame(depth1_frame())
    assert stream.phase(SYMBOL) is BookPhase.LIVE
    first = [q for q in _drain(quote_q) if isinstance(q, BestQuoteEvent)]
    assert len(first) == 1 and first[0].spread_ticks >= 1
    _drain(book_q)
    await stream.handle_frame(depth1_frame(KEEPALIVE_S * 1000))
    assert stream.phase(SYMBOL) is BookPhase.LIVE
    assert [e for e in _drain(book_q) if isinstance(e, BookDelta | BookSnapshot)] == []
    assert _drain(quote_q) == []


def _drain(q: Any) -> list[object]:
    out: list[object] = []
    while q.qsize():
        out.append(q.get_nowait())
    return out
