"""#2223: `BookStream.anchor`, the recorder's periodic seek-anchor source.

Recorded corpus (`ws/orderbook_BTCUSDT.jsonl`), a fake clock, no network (C-13.5, C-13.7): the
active tier's full book stamped with its last applied frame, or why there is none.
"""

from __future__ import annotations

from decimal import Decimal

from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import BookSnapshot
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.ingestion.watchdog import STALENESS_S
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import frames

BOOK = frames("ws/orderbook_BTCUSDT.jsonl")
WS = "ws:book:50"


async def _nothing(_arg: str) -> None:
    """A resubscribe that does nothing."""


class _Rig:
    def __init__(self) -> None:
        self.t = 0.0
        self.stream = BookStream(
            bus=Bus(), env="live", set_desired=lambda _topics: None,
            parse_frame=lambda f: parse_book_frame(f, lambda _s: Decimal("0.1")),
            topic_for=book_topic, resubscribe=_nothing, is_listed=lambda s: s == "BTCUSDT",
            touch=lambda _t: None, clock=lambda: self.t, now_us=lambda: 0,
        )  # fmt: skip

    async def feed(self, n: int) -> None:
        self.stream.acquire(WS, "BTCUSDT")
        for frame in BOOK[:n]:
            await self.stream.handle_frame(frame)


async def test_book_stream_anchor_names_a_symbol_without_a_book() -> None:
    assert _Rig().stream.anchor("BTCUSDT") == "no_book"


async def test_book_stream_anchor_is_the_live_book_at_its_last_applied_frame() -> None:
    rig = _Rig()
    await rig.feed(100)
    engine = rig.stream.engine("BTCUSDT")

    a = rig.stream.anchor("BTCUSDT")

    assert isinstance(a, BookSnapshot) and engine is not None and engine.book is not None
    assert a.update_id == engine.last_u and a.depth == engine.depth
    assert len(a.bids) + len(a.asks) == len(engine.book.snapshot()[0]) + len(
        engine.book.snapshot()[1]
    )
    assert engine.last_applied is not None and a.ts_event == engine.last_applied.ts_event


async def test_book_stream_anchor_names_a_book_that_is_not_live() -> None:
    rig = _Rig()
    await rig.feed(100)
    await rig.stream.invalidate("reconnect")

    assert rig.stream.anchor("BTCUSDT") == "not_live"


async def test_book_stream_anchor_serves_a_quiet_live_book() -> None:
    """F1: Bybit sends nothing while a book does not change; a LIVE book past the frame-age
    limit is still valid, so it is still anchored (the watchdog takes a dead feed out of LIVE)."""
    rig = _Rig()
    await rig.feed(100)
    rig.t = 30 * STALENESS_S["book"]

    assert rig.stream.is_stale("BTCUSDT")
    assert isinstance(rig.stream.anchor("BTCUSDT"), BookSnapshot)
