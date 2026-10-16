"""#1919: `IngestionService.health()` degrades with stable reasons (C-13.6 #1, SCR-152).

Chaos `tests/chaos/ingestion/test_visible_degradation.py::
test_unrecovered_fault_reports_degraded_health` (PR #1921) is xfail until this
lands; promote it (drop the xfail) once both are on main.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.bybit.trades import parse_recent_trades, parse_trade_frame, trade_topic
from candleviewer.ingestion.connection import PHASE_CONNECTING, PHASE_OPEN
from candleviewer.ingestion.instruments import CatalogueSnapshot, InstrumentCatalogueCache
from candleviewer.ingestion.instruments_refresh import (
    InstrumentRefreshError,
    InstrumentsRefreshScheduler,
)
from candleviewer.ingestion.service import (
    PUMP_BREAKER_TRIPS,
    PUMP_BREAKER_WINDOW_S,
    WS_GRACE_S,
    HealthReason,
    IngestionService,
)
from candleviewer.ingestion.trade_stream import UNRECOVERED_RETENTION_S, GapEvent, TradeStream
from candleviewer.ingestion.watchdog import FeedHealthEvent
from candleviewer.observability.health import HealthStatus
from tests._corpus import corpus_path
from tests.unit.ingestion._fakes import ParkingSleep, settle


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Ws:
    def __init__(self, clock: _Clock) -> None:
        self._clock, self.phase, self.since = clock, PHASE_OPEN, clock()

    def set(self, phase: str) -> None:
        self.phase, self.since = phase, self._clock()

    def state(self) -> str:
        return self.phase

    def phase_since(self) -> float:
        return self.since


class _Books:
    def __init__(self) -> None:
        self.bad: tuple[str, ...] = ()
        self.slo: float | None = None

    def out_of_live(self, slo_s: float = 30.0) -> tuple[str, ...]:
        self.slo = slo_s
        return self.bad


class _Trades:
    def __init__(self) -> None:
        self.gaps: dict[str, tuple[int, str]] = {}
        self.unrecovered: dict[str, tuple[int, int]] = {}

    def open_gaps(self) -> dict[str, tuple[int, str]]:
        return dict(self.gaps)

    def unrecovered_gaps(self) -> dict[str, tuple[int, int]]:
        return dict(self.unrecovered)


class _Instruments:
    def __init__(self) -> None:
        self.cache = InstrumentCatalogueCache(ttl_seconds=100.0)


def _svc(clock: _Clock) -> IngestionService:
    s = IngestionService(clock=clock, now_us=lambda: int(clock() * 1_000_000))
    s._started = True
    return s


def _reason(s: IngestionService) -> tuple[HealthStatus, str]:
    h = s.health()
    return h.status, h.detail


def test_stopped_service_is_stopped_not_degraded() -> None:
    s = IngestionService()
    assert s.health().status is HealthStatus.STOPPED


def test_no_signals_attached_is_ok() -> None:
    assert _reason(_svc(_Clock())) == (HealthStatus.OK, "")


def test_ws_not_open_degrades_only_past_grace_and_recovers() -> None:
    clock = _Clock()
    s, ws = _svc(clock), _Ws(clock)
    s.ws = cast(Any, ws)
    ws.set(PHASE_CONNECTING)
    clock.t += WS_GRACE_S  # boundary: exactly the grace is still OK
    assert s.health().status is HealthStatus.OK
    clock.t += 0.001
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.WS_NOT_OPEN)
    ws.set(PHASE_OPEN)
    assert s.health().status is HealthStatus.OK


def test_book_out_of_live_degrades_and_recovers() -> None:
    clock = _Clock()
    s, books = _svc(clock), _Books()
    s.books = cast(Any, books)
    assert s.health().status is HealthStatus.OK
    books.bad = ("BTCUSDT",)
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.BOOK_OUT_OF_LIVE)
    books.bad = ()
    assert s.health().status is HealthStatus.OK


def test_book_slo_override_is_forwarded() -> None:
    clock = _Clock()
    s, books = IngestionService(clock=clock, book_slo_s=7.0), _Books()
    s._started, s.books = True, cast(Any, books)
    s.health()
    assert books.slo == 7.0


def test_unrecovered_trade_gap_degrades_and_recovers() -> None:
    clock = _Clock()
    s, trades = _svc(clock), _Trades()
    s.trades = cast(Any, trades)
    trades.gaps["BTCUSDT"] = (1, "frame_loss")
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.TRADE_GAP_UNRECOVERED)
    trades.gaps.clear()
    assert s.health().status is HealthStatus.OK
    trades.unrecovered["BTCUSDT"] = (1, 2)  # #2715: a closed window that stayed a hole
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.TRADE_GAP_UNRECOVERED)
    trades.unrecovered.clear()
    assert s.health().status is HealthStatus.OK


def test_stale_catalogue_degrades() -> None:
    clock = _Clock()
    s, inst = _svc(clock), _Instruments()
    s.instruments = cast(Any, inst)
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.CATALOGUE_STALE)  # never loaded
    fetched = int(clock() * 1_000_000)
    inst.cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=fetched))
    assert s.health().status is HealthStatus.OK
    clock.t += 101.0
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.CATALOGUE_STALE)


class _Boom:
    """Parser that always faults; `mark_gap` fires only from the breaker's resync."""

    def __init__(self) -> None:
        self.resynced = asyncio.Event()

    async def handle_frame(self, frame: str) -> None:
        raise RuntimeError("parser fault")

    def mark_gap(self, reason: str, symbol: str | None = None) -> None:
        self.resynced.set()

    def open_gaps(self) -> dict[str, tuple[int, str]]:
        return {}


async def _trip(s: IngestionService) -> None:
    boom = _Boom()
    s.trades = cast(Any, boom)
    for _ in range(PUMP_BREAKER_TRIPS):
        s.ws_frames.put_nowait("{}")
    task = asyncio.create_task(s._pump_frames())
    try:
        await asyncio.wait_for(boom.resynced.wait(), timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_pump_breaker_trip_degrades_for_window_then_recovers() -> None:
    clock = _Clock()
    s = _svc(clock)
    await _trip(s)
    assert s.pump_breaker_trips == 1
    s.trades = None
    clock.t += PUMP_BREAKER_WINDOW_S  # exact boundary: still open
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.PUMP_BREAKER_OPEN)
    clock.t += 0.001
    assert s.health().status is HealthStatus.OK


def test_multiple_reasons_are_comma_joined_in_stable_order() -> None:
    clock = _Clock()
    s, ws, trades = _svc(clock), _Ws(clock), _Trades()
    s.ws, s.trades = cast(Any, ws), cast(Any, trades)
    ws.set(PHASE_CONNECTING)
    clock.t += WS_GRACE_S + 1
    trades.gaps["X"] = (1, "r")
    assert s.health().detail == f"{HealthReason.WS_NOT_OPEN},{HealthReason.TRADE_GAP_UNRECOVERED}"


def test_health_reads_only_plain_phase_signals_never_the_interpreter() -> None:
    clock = _Clock()
    s = _svc(clock)
    calls: list[str] = []

    class _Gateway:
        @property
        def _interp(self) -> Any:
            pytest.fail("health() touched the interpreter")

        def state(self) -> str:
            calls.append("state")
            return PHASE_OPEN

        def phase_since(self) -> float:
            calls.append("phase_since")
            return clock()

        def __getattr__(self, name: str) -> Any:
            pytest.fail(f"health() touched {name}")

    s.ws = cast(Any, _Gateway())
    assert s.health().status is HealthStatus.OK
    assert set(calls) <= {"state", "phase_since"}


# ---- #2715: ongoing faults stay visible (real TradeStream / refresh scheduler) -------------

FRAMES = (corpus_path("ws") / "publicTrade_BTCUSDT.jsonl").read_text(encoding="utf-8").splitlines()
RECENT = json.loads(corpus_path("rest/recent_trade_BTCUSDT.json").read_text(encoding="utf-8"))
CATALOGUE = json.loads(corpus_path("rest/instruments_before.json").read_text(encoding="utf-8"))
_ID = "a0000001-0000-4000-8000-00000000000"


class _Writer:
    def __init__(self) -> None:
        self.rows: list[TradeEvent] = []

    async def write_trades(self, events: Sequence[TradeEvent]) -> None:
        self.rows.extend(events)


def _print_8() -> str:
    """A live print after the gap (the corpus frame 2 shape, next id, 1 s later)."""
    msg = json.loads(FRAMES[2])
    msg["data"][0].update({"i": f"{_ID}8", "T": 1_700_000_010_000})
    return json.dumps(msg)


class _Tape:
    """A real `TradeStream` on a started service. REST is down while `rest_down`; then the
    recent-trade page is the recorded one, which reaches back past the gap."""

    def __init__(self) -> None:
        self.clock = _Clock()
        self.svc = _svc(self.clock)
        self.sleep = ParkingSleep()
        self.writer = _Writer()
        self.bus = Bus()
        self.gap_sub = self.bus.subscribe("g", "live.md.*.gap", QueuePolicy.NEVER_DROP)
        self.trade_sub = self.bus.subscribe("t", "live.md.*.trade", QueuePolicy.NEVER_DROP)
        self.rest_down = True

        async def fetch(symbol: str) -> Sequence[TradePrint]:
            if self.rest_down:
                raise RuntimeError("503 from the venue")
            return parse_recent_trades(symbol, RECENT)

        self.stream = TradeStream(
            bus=self.bus,
            env="live",
            set_desired=lambda _t: None,
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=lambda s: s == "BTCUSDT",
            touch=lambda _t: None,
            fetch_recent=fetch,
            clock=self.clock,
            now_us=lambda: 1_700_000_010_500_000,
            grace_s=0.0,
            writer=self.writer,
            retry_sleep=self.sleep,
            retry_rand=lambda: 0.0,
        )
        self.svc.trades = self.stream
        self.stream.acquire("chart", "BTCUSDT")

    async def unrecovered_gap_then_live(self) -> None:
        """Print 3, reconnect, print 7 closes the window while REST is down (prints 4-6
        lost), then print 8: live prints have resumed."""
        await self.stream.handle_frame(FRAMES[1])
        reconnect = FeedHealthEvent("publicTrade.BTCUSDT", "resubscribing", 0.0)
        await self.stream.process_health(reconnect)
        await self.stream.handle_frame(FRAMES[2])
        await self.stream.wait_backfills()
        await self.stream.handle_frame(_print_8())

    def gap_events(self) -> list[GapEvent]:
        out: list[GapEvent] = []
        while not self.gap_sub.queue.empty():
            out.append(self.gap_sub.queue.get_nowait())
        return out


async def test_unrecovered_gap_stays_degraded_after_live_prints_resume() -> None:
    tape = _Tape()
    try:
        await tape.unrecovered_gap_then_live()
        assert [g.recovered for g in tape.gap_events()] == [False]
        assert tape.stream.open_gaps() == {}  # the window closed with the first live print
        assert _reason(tape.svc) == (HealthStatus.DEGRADED, HealthReason.TRADE_GAP_UNRECOVERED)
    finally:
        await tape.stream.stop()


async def test_unrecovered_gap_clears_after_a_covering_backfill() -> None:
    tape = _Tape()
    try:
        await tape.unrecovered_gap_then_live()
        assert [g.recovered for g in tape.gap_events()] == [False]
        await settle()
        tape.sleep.release()  # first retry: REST still down
        await settle()
        assert _reason(tape.svc) == (HealthStatus.DEGRADED, HealthReason.TRADE_GAP_UNRECOVERED)
        tape.rest_down = False
        tape.sleep.release()  # second retry: the page reaches back past the gap start
        await settle()
        assert tape.svc.health().status is HealthStatus.OK
        assert tape.gap_events() == []  # the window's GapEvent stays as published
        while tape.stream.write_behind.qsize():
            await tape.stream.drain_writes()
        rows = [(r.trade_id[-1], r.source) for r in tape.writer.rows]
        live = [("3", "live"), ("7", "live"), ("8", "live")]
        healed = [("4", "backfill"), ("5", "backfill"), ("6", "backfill")]
        assert rows == live + healed  # the lost prints reach the hot tier, once each
        bus: list[str] = []
        while not tape.trade_sub.queue.empty():
            bus.append(tape.trade_sub.queue.get_nowait().trade_id[-1])
        assert bus == ["3", "7", "8"]  # never the live topic: time never moves backwards
    finally:
        await tape.stream.stop()


async def test_unrecovered_gap_clears_when_the_symbol_leaves_demand() -> None:
    tape = _Tape()
    try:
        await tape.unrecovered_gap_then_live()
        assert tape.svc.health().status is HealthStatus.DEGRADED
        tape.stream.release("chart", "BTCUSDT")  # no grace: the symbol leaves demand now
        assert tape.svc.health().status is HealthStatus.OK
    finally:
        await tape.stream.stop()


async def test_unfillable_trade_gap_degrades_until_the_retention_horizon() -> None:
    """#2715 review: REST stays down, so no backfill ever fills the hole; health is degraded
    for `UNRECOVERED_RETENTION_S` after the window closed, then `ok` (the window's
    `GapEvent(recovered=False)` stays the record), and the parked retry ends without REST."""
    tape = _Tape()
    try:
        await tape.unrecovered_gap_then_live()
        tape.clock.t += UNRECOVERED_RETENTION_S - 1.0
        assert _reason(tape.svc) == (HealthStatus.DEGRADED, HealthReason.TRADE_GAP_UNRECOVERED)
        tape.clock.t += 1.0
        assert tape.svc.health().status is HealthStatus.OK
        assert [g.recovered for g in tape.stream.gaps("BTCUSDT")] == [False]
        await settle()
        tape.sleep.release()
        await settle()
        assert len(tape.sleep.delays) == 1  # nothing left to retry
    finally:
        await tape.stream.stop()


def _catalogue_page(now_us: int) -> InstrumentsFetchResult:
    return parse_instruments(CATALOGUE["result"]["list"], fetched_at_us=now_us)


async def test_failed_catalogue_refresh_degrades_until_the_next_successful_refresh() -> None:
    """#2715: a failed refresh of a fresh, loaded catalogue degrades health at once (not after
    the 12 h TTL), and the next successful refresh clears it."""
    clock = _Clock()
    exchange_up = True

    def now_us() -> int:
        return 1_700_000_000_000_000 + int(clock() * 1_000_000)

    async def fetch(stamp: Callable[[], int]) -> InstrumentsFetchResult:
        if not exchange_up:
            raise RuntimeError("instruments-info 503")
        return _catalogue_page(stamp())

    async def no_sleep(_delay: float) -> None:
        return None

    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch,
        repository=cast(Any, _NullRepo()),
        now_us=now_us,
        sleep=no_sleep,
        random_fn=lambda: 0.0,
        max_retries=1,
    )
    s = IngestionService(clock=clock, now_us=now_us)
    s._started, s.instruments = True, sched
    await sched.refresh_now()
    assert s.health().status is HealthStatus.OK
    exchange_up = False
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    clock.t += 1.0  # well inside the TTL: the snapshot itself is fresh
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.CATALOGUE_STALE)
    exchange_up = True
    await sched.refresh_now()
    assert s.health().status is HealthStatus.OK


class _NullRepo:
    async def upsert_snapshot(self, rows: Any) -> None:
        return None

    async def record_version(self, row: Any, *, changed_fields: Any) -> None:
        return None

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> list[Any]:
        return []
