"""#1919: `BookStream.out_of_live` via real `_publish` status transitions (SLO = backoff cap)."""

from __future__ import annotations

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.bus.bus import Bus
from candleviewer.domain.events import uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.bybit.orderbook import book_topic
from candleviewer.orderbook_wiring import RESYNC_BACKOFF_CAP_S, BookStream


class _Rig:
    def __init__(self) -> None:
        self.t = 100.0
        self.stream = BookStream(
            bus=Bus(),
            env="live",
            set_desired=lambda _t: None,
            parse_frame=lambda _f: None,
            topic_for=book_topic,
            resubscribe=self._noop,
            is_listed=lambda _s: True,
            touch=lambda _t: None,
            clock=lambda: self.t,
            now_us=lambda: 0,
        )
        self.stream.acquire("c", "BTCUSDT")

    @staticmethod
    async def _noop(_topic: str) -> None:
        return None

    async def status(self, state: BookPhase) -> None:
        await self.stream._ensure("BTCUSDT")
        await self.stream._publish(
            "BTCUSDT",
            BookStatus(
                event_id=EventId(uuid7(0)),
                ts_event=0,
                ts_ingest=0,
                source="live",
                symbol="BTCUSDT",
                depth=50,
                state=state,
                reason="t",
                ts_us=0,
                last_good_ts_us=None,
                resync_count=0,
            ),
        )


async def test_out_of_live_flags_only_past_slo_and_clears_on_live() -> None:
    r = _Rig()
    await r.status(BookPhase.SNAPSHOT_PENDING)
    r.t += RESYNC_BACKOFF_CAP_S  # exact boundary: not yet
    assert r.stream.out_of_live() == ()
    r.t += 0.001
    assert r.stream.out_of_live() == ("BTCUSDT",)
    await r.status(BookPhase.LIVE)
    assert r.stream.out_of_live() == ()


async def test_live_then_resync_restarts_the_slo_window() -> None:
    r = _Rig()
    await r.status(BookPhase.LIVE)
    r.t += 1000.0  # LIVE for ages: healthy
    assert r.stream.out_of_live() == ()
    await r.status(BookPhase.DESYNCED)
    r.t += RESYNC_BACKOFF_CAP_S + 0.001
    assert r.stream.out_of_live() == ("BTCUSDT",)
    await r.status(BookPhase.SNAPSHOT_PENDING)  # still out: window not restarted
    assert r.stream.out_of_live() == ("BTCUSDT",)


async def test_drop_forgets_the_symbol() -> None:
    r = _Rig()
    await r.status(BookPhase.DESYNCED)
    r.t += 1000.0
    r.stream.release("c", "BTCUSDT")
    r.stream._drop("BTCUSDT")
    assert r.stream.out_of_live() == ()
