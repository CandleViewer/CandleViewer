"""#2487 part 1 (E17-S03 residual, QA #411): `stale` under a deliberately stalled upstream, through
`create_app()`'s own composition behind its real `/ws` router, on both wires.

The snapshot adapters are production's (`ws_wiring.book_snapshot_source`, and `BarsSnapshotSource`
over `ws_wiring.series_stale` as `create_app` builds them); only the upstream streams are the
test's, attached where `wire_public_ws` attaches them: a production `BookStream` and `TradeStream`
on a fake monotonic clock, fed the recorded BTCUSDT corpus (C-13.5). Per family: frames arrive and
the `snap` is fresh; the clock passes the watchdog's limit (`STALENESS_S`, the freshness SLO of
`23-ws-protocol.md` §6) with no frame, and the next `snap` carries `meta.stale: true` while
`cv_ws_stale_topics_in_use` counts the topic; frames resume and both clear. No sleeps (C-13.7):
the stall is the clock, the next `snap` a client `resync` (§7.5)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.orderbook import parse_book_frame
from candleviewer.exchange.bybit.trades import parse_trade_frame
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.ingestion.watchdog import STALENESS_S
from candleviewer.orderbook_wiring import BookStream
from candleviewer.ws.sequencing import cv_ws_stale_topics_in_use
from tests._corpus import TICKS, frames
from tests.contract.ws import _harness as h
from tests.contract.ws.test_ws_bars_cold_series import CH as BARS_CH
from tests.contract.ws.test_ws_bars_cold_series import _next, _stored
from tests.contract.ws.test_ws_bars_heal import _Stack

BOOK_CH = f"book.{h.SYM}.50"
BOOK = frames("ws/orderbook_BTCUSDT.jsonl")  # [0] a venue snapshot, then deltas
TRADES = frames("ws/publicTrade_BTCUSDT.jsonl")


async def _nothing(_arg: object = None) -> None:
    return None


class _Upstream:
    """`create_app` (via the heal suite's `_Stack`) with the test's streams attached to its
    ingestion service, both on `self.t`, the monotonic clock the watchdog would age them by."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.t = 0.0
        self.stack = _Stack(tmp_path, monkeypatch, [_stored(12)])
        app: Any = self.stack.client.app
        ingestion = app.state.app_context.ingestion
        self.books = BookStream(
            bus=Bus(), env="demo", set_desired=lambda _t: None, topic_for=lambda s, d: f"b.{d}.{s}",
            parse_frame=lambda f: parse_book_frame(f, TICKS.get), resubscribe=_nothing,
            is_listed=lambda _s: True, touch=lambda _t: None, clock=lambda: self.t,
            now_us=lambda: 0, rand=lambda: 0.0,
        )  # fmt: skip
        self.trades = TradeStream(
            bus=Bus(), env="demo", set_desired=lambda _t: None, parse_frame=parse_trade_frame,
            topic_for=lambda s: f"t.{s}", is_listed=lambda _s: True, touch=lambda _t: None,
            clock=lambda: self.t, now_us=lambda: 0,
        )  # fmt: skip
        ingestion.attach_books(self.books)
        ingestion.attach_trades(self.trades)
        listed = SimpleNamespace(  # the corpus instrument (`rest/instruments_before.json`)
            tick_size=TICKS[h.SYM], qty_step=Decimal("0.001"), status="trading"
        )
        ingestion.instruments = SimpleNamespace(snapshot=lambda: {h.SYM: listed})

    def book_frame(self, raw: str) -> None:
        self.stack.call(self.books.handle_frame, raw)

    def trade_frame(self, raw: str) -> None:
        self.stack.call(self.trades.handle_frame, raw)


def _gauge() -> float:
    value: float = cv_ws_stale_topics_in_use._value.get()
    return value


def _resync(c: h.Client, ch: str, last_seq: int) -> dict[str, Any]:
    """The `snap` a client `resync` is answered with (§7.5): the next one, on demand."""
    c.send({"t": "resync", "id": "r", "ch": ch, "p": {"reason": "manual", "last_seq": last_seq}})
    return _next(c, "snap")


def _sub(c: h.Client, ch: str) -> dict[str, Any]:
    topic = {"ch": ch, "opts": {"encoding": "structured"}}
    c.send({"t": "sub", "id": "s", "p": {"topics": [topic]}})
    assert _next(c, "sub_ok")["p"]["results"][0]["ok"] is True
    return _next(c, "snap")


def _stale(snap: dict[str, Any]) -> bool:
    """The snapshot's verdict: `meta.stale` is present (and true) only while stale (§7.2)."""
    assert snap["meta"].get("stale", True) is True  # never `stale: false` on the wire
    return "stale" in snap["meta"]


@pytest.mark.parametrize("offer", h.OFFERS.values(), ids=h.OFFERS.keys())
def test_book_snap_goes_stale_when_the_book_stalls_past_the_watchdog_limit_and_clears_on_resume(
    offer: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`book`: `stale` is `BookStream.is_stale`, the REST book's own verdict, so a book that
    applied no frame for `STALENESS_S["book"]` is served flagged until the next frame lands."""
    up = _Upstream(tmp_path, monkeypatch)
    limit = STALENESS_S["book"]
    with up.stack.client:
        up.books.acquire("test", h.SYM)  # held before any socket: the book is LIVE at sub
        up.book_frame(BOOK[0])
        with up.stack.connect(offer) as c:
            first = _sub(c, BOOK_CH)
            fresh = (_stale(first), first["p"]["stale"], _gauge())
            up.t += limit / 2
            up.book_frame(BOOK[1])  # a delta inside the limit: still fresh
            up.t += limit / 2
            within = _resync(c, BOOK_CH, first["s"])
            up.t += limit  # stalled: no frame for the whole limit
            stalled = _resync(c, BOOK_CH, within["s"])
            flagged = (_stale(stalled), stalled["p"]["stale"], _gauge())
            up.book_frame(BOOK[2])  # the feed resumes
            resumed = _resync(c, BOOK_CH, stalled["s"])
            cleared = (_stale(resumed), resumed["p"]["stale"], _gauge())
    assert fresh == (False, False, 0) and _stale(within) is False
    assert flagged == (True, True, 1)
    assert cleared == (False, False, 0)
    assert up.books.is_stale(h.SYM) is False  # the REST view's verdict is the same one


@pytest.mark.parametrize("offer", h.OFFERS.values(), ids=h.OFFERS.keys())
def test_bars_snap_goes_stale_when_the_trade_feed_stalls_past_the_watchdog_limit_and_clears(
    offer: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`bars` are tape-built: with no quarantine, `stale` is the symbol's trade feed past
    `STALENESS_S["trade"]` (`series_stale`); the subscription's own demand starts the clock, as
    the watchdog's `watch` does, and a frame for the symbol restarts it."""
    up = _Upstream(tmp_path, monkeypatch)
    limit = STALENESS_S["trade"]
    with up.stack.client, up.stack.connect(offer) as c:
        first = _sub(c, BARS_CH)  # its trades lease demands the tape at t=0
        fresh = (_stale(first), _gauge())
        up.t += limit / 2
        up.trade_frame(TRADES[0])
        up.t += limit / 2
        within = _resync(c, BARS_CH, first["s"])
        up.t += limit  # stalled: no trade frame for the whole limit
        stalled = _resync(c, BARS_CH, within["s"])
        flagged = (_stale(stalled), _gauge())
        up.trade_frame(TRADES[1])  # the tape resumes
        resumed = _resync(c, BARS_CH, stalled["s"])
        cleared = (_stale(resumed), _gauge())
    assert fresh == (False, 0) and _stale(within) is False
    assert flagged == (True, 1)
    assert cleared == (False, 0)


def test_indicators_share_the_bars_verdict_from_the_trade_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`indicators` are built from the same tape-built series: `create_app` hands them the very
    predicate `bars` uses, so the trade feed's stall flags both alike."""
    up = _Upstream(tmp_path, monkeypatch)
    app: Any = up.stack.client.app
    sources = app.state.ws_registry.services.snapshots._sources
    bars, indicators = sources["bars"]._stale, sources["indicators"]._stale
    up.trades.acquire("test", h.SYM)
    spec_hash = "any"
    assert (bars(h.SYM, spec_hash), indicators(h.SYM, spec_hash)) == (False, False)
    up.t += STALENESS_S["trade"]
    assert (bars(h.SYM, spec_hash), indicators(h.SYM, spec_hash)) == (True, True)
    assert bars is indicators
