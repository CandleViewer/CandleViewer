"""Composition-root parity guards for `_rig.Rig` (#1975).

The rig is started through `IngestionService.start()` and composes what
`app.wire_public_ws` composes. Each test pins one element by its behaviour, so a rig
that drops it fails here rather than in a scenario that happens not to need it.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.book.models import BookPhase
from candleviewer.ingestion.metrics import ingest_rejected_total
from candleviewer.orderbook_wiring import SNAPSHOT_TIMEOUT_S
from tests._corpus import frames
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder, retime
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

BOOK_TOPIC = "orderbook.200.BTCUSDT"
BOOK_CHART = "live:BTCUSDT:200"  # the B14 chart key: env:symbol:depth
TIME_PATH = "/v5/market/time"
SAMPLES = 5  # ClockGuard samples per measurement burst
RESYNC_S, RESYNC_JITTER_S = 300.0, 30.0  # ClockGuard periodic re-measure (+ <= 10 %)
TICK_S = 0.25  # BookStream's SNAPSHOT_TIMEOUT tick
TRADES = frames("ws/clean_publicTrade_BTCUSDT.jsonl")
TICKERS = frames("ws/tickers_BTCUSDT.jsonl")  # recorded snapshot + deltas
DAY_MS = 86_400_000


def _state(chart: Any) -> set[str]:
    return {s.rsplit(".", 1)[-1] for s in chart.current_state_ids}


def _time_calls(rig: Rig) -> list[float]:
    return [t for t, path in rig.ex.rest_calls if path == TIME_PATH]


async def _open(rig: Rig) -> None:
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")


async def test_parity_started_rig_reports_healthy_on_virtual_time(rig: Rig) -> None:
    """`start(ctx)` sets the module running; its health clocks are the rig's, so a
    healthy feed reads `ok` (a real `now_us` would age the catalogue into `stale`)."""
    feed = Feeder(rig.ex)
    await _open(rig)
    await feed.run(3.0)
    assert rig.book_phase() is BookPhase.LIVE
    assert rig.health_report() == "ok"


async def test_parity_clock_guard_is_started_by_ingestion_on_virtual_time(rig: Rig) -> None:
    """`attach_clock` (as `wire_clock_offset`): `start(ctx)` measures once, then the
    periodic re-measure runs on the rig's clock."""
    assert _time_calls(rig) == [0.0] * SAMPLES  # one burst inside `start(ctx)`
    assert rig.clock_guard.offset_ms_or_none() is not None
    await rig.clock.run_until(
        lambda: len(_time_calls(rig)) == 2 * SAMPLES,
        within_s=RESYNC_S + RESYNC_JITTER_S,
        what="periodic re-measure",
    )
    assert RESYNC_S <= _time_calls(rig)[-1] <= RESYNC_S + RESYNC_JITTER_S


async def test_parity_withheld_snapshot_times_out_on_the_streams_own_tick(rig: Rig) -> None:
    """The corpus snapshot is lost on the wire: the `BookStream`'s own SNAPSHOT_TIMEOUT
    tick (virtual time) re-requests it, and its B14 chart records the lifecycle."""
    rig.ex.inject(Fault(FaultKind.DROP, topic=BOOK_TOPIC))
    feed = Feeder(rig.ex)
    await _open(rig)
    t0 = rig.clock.now
    while rig.book_phase() is not BookPhase.LIVE:
        assert rig.clock.now - t0 <= SNAPSHOT_TIMEOUT_S + 1.0, "snapshot never re-requested"
        await feed.run(0.1)
    # pending from the first delta (one feed step in): timeout + one tick + one step
    assert SNAPSHOT_TIMEOUT_S <= rig.clock.now - t0 <= SNAPSHOT_TIMEOUT_S + 2 * TICK_S
    chart = rig.book_supervisor.interpreter(BOOK_CHART)
    assert chart is not None, "the book has no B14 chart"
    assert _state(chart) == {"live"}
    assert chart.context["resync_count"] == 1  # exactly one SNAPSHOT_TIMEOUT


async def test_parity_print_before_listing_is_rejected(rig: Rig) -> None:
    """`_launch_us` gives the event window the catalogue launch time (#1892)."""
    snap = rig.instruments.snapshot()
    inst = snap.get("BTCUSDT") if snap is not None else None
    assert inst is not None
    await _open(rig)
    rejected = metric(ingest_rejected_total, stream="trade", reason="ts_past")
    published = len(rig.observe().trades)
    rig.ex.emit(retime(TRADES[0], inst.launch_time // 1000 - 2 * DAY_MS))  # grace is 1 day
    await rig.clock.settle()
    assert metric(ingest_rejected_total, stream="trade", reason="ts_past") == rejected + 1
    assert len(rig.observe().trades) == published


async def test_parity_ticker_demand_is_served_by_the_attached_stream(rig: Rig) -> None:
    """`attach_tickers`: an acquired ticker topic is merged and published via the pump."""
    await _open(rig)
    rig.tickers.acquire("chaos-ticker", "BTCUSDT")
    await rig.clock.run_until(
        lambda: "tickers.BTCUSDT" in rig.ex.live_sockets()[0].topics,
        within_s=2,
        what="ticker subscribed",
    )
    for frame in TICKERS:
        rig.ex.emit(retime(frame, int(rig.clock.wall_s() * 1000)))
        await rig.clock.advance(0.1)
    seen = rig.observe().tickers
    assert len(seen) == len(TICKERS) and {t.symbol for t in seen} == {"BTCUSDT"}
    assert rig.tickers.latest("BTCUSDT") == seen[-1]
