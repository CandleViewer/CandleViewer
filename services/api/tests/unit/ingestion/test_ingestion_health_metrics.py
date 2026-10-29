"""E08-T06: the connection / book health series the Ingestion dashboard and
alerts read are emitted by the real code paths (no network, fake clocks)."""

from __future__ import annotations

import asyncio

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.domain.events import uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.metrics import (
    OTHER_SYMBOL,
    ingest_book_live,
    ingest_book_resyncs_total,
    ingest_ws_up,
    reset_symbol_universe,
)
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.watchdog import StalenessWatchdog
from candleviewer.observability.metrics import Counter, Gauge
from candleviewer.orderbook_wiring import _observe_book_status


def _val(metric: Counter | Gauge, **labels: str) -> float:
    return float(metric.labels(**labels)._value.get())


class _Sock:
    def __init__(self) -> None:
        self.closed = asyncio.Event()

    async def send(self, _m: str) -> None:
        return None

    async def recv(self, max_bytes: int) -> str:
        await self.closed.wait()
        raise ConnectionError("closed")

    async def close(self) -> None:
        self.closed.set()


async def test_ws_up_gauge_follows_connection_phase() -> None:
    t = [0.0]

    def clk() -> float:
        return t[0]

    async def factory() -> _Sock:
        return _Sock()

    m = ConnectionManager(
        factory,
        SubscriptionPlanner(),
        StalenessWatchdog(clk, lambda _e: None),
        ReconnectPolicy(),
        ConnectionRateGuard(clk),
        lambda _m: None,
    )
    await m.start()
    for _ in range(100):
        await asyncio.sleep(0)
        if m.state() == "open":
            break
    assert m.state() == "open" and _val(ingest_ws_up, socket="public") == 1.0
    await m.stop()
    assert _val(ingest_ws_up, socket="public") == 0.0


def _status(state: BookPhase, reason: str, symbol: str = "BTCUSDT") -> BookStatus:
    return BookStatus(
        event_id=EventId(uuid7(0)),
        ts_event=1,
        ts_ingest=1,
        source="live",
        symbol=symbol,
        depth=200,
        state=state,
        reason=reason,
        ts_us=1,
        last_good_ts_us=None,
        resync_count=1,
    )


def test_book_status_drives_live_gauge_and_resync_counter() -> None:
    reset_symbol_universe()
    before = _val(ingest_book_resyncs_total, symbol="BTCUSDT", reason="sequence_gap", depth="200")
    _observe_book_status(_status(BookPhase.LIVE, "subscribe"))
    assert _val(ingest_book_live, symbol="BTCUSDT") == 1.0
    _observe_book_status(_status(BookPhase.DESYNCED, "sequence_gap"))
    assert _val(ingest_book_live, symbol="BTCUSDT") == 0.0
    after = _val(ingest_book_resyncs_total, symbol="BTCUSDT", reason="sequence_gap", depth="200")
    assert after - before == 1


def test_book_status_free_text_reason_and_symbol_never_become_labels() -> None:
    reset_symbol_universe()
    before = _val(ingest_book_resyncs_total, symbol=OTHER_SYMBOL, reason="other", depth="200")
    _observe_book_status(_status(BookPhase.DESYNCED, "user typed <script>", symbol="bad sym"))
    after = _val(ingest_book_resyncs_total, symbol=OTHER_SYMBOL, reason="other", depth="200")
    assert after - before == 1
