"""Scenario 11 - dependency outage (QuestDB / Postgres restarted under load).
C-13.6 #10 (ingestion side; storage-internal chaos is E07-Q04).

Declared: while the hot tier is down ingestion keeps publishing live data (the
write-behind never blocks the reader), the write failures are visible
(`trade write-behind failed` log), and nothing is counted as persisted that was
not; after the outage the stream keeps persisting new data, and the instrument
catalogue (Postgres-backed) keeps serving its last snapshot, marked stale.
#2715: a failed catalogue refresh degrades health (`catalogue_stale`) at once, not
after the 12 h TTL, until the next successful refresh.
"""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from candleviewer.book.models import BookPhase
from candleviewer.ingestion.instruments_refresh import InstrumentRefreshError
from candleviewer.ingestion.metrics import instruments_refresh_total
from candleviewer.ingestion.service import HealthReason
from candleviewer.ingestion.write_behind import BACKOFF_CAP_S
from candleviewer.observability.context import spawn
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

OUTAGE_S = 10.0
CATALOGUE_PATH = "/v5/market/instruments-info"


def _ids(events: list[object]) -> set[str]:
    return {str(getattr(e, "trade_id", "")) for e in events if hasattr(e, "trade_id")}


async def _outage(rig: Rig) -> tuple[Feeder, set[str]]:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(2.0)
    published_before = _ids(rig.observe().trades)
    rig.writer.down = True
    await feed.run(OUTAGE_S)
    return feed, published_before


async def test_s11_hot_tier_outage_keeps_ingest_live_and_never_over_acknowledges(rig: Rig) -> None:
    with capture_logs() as logs:
        feed, _ = await _outage(rig)
    during = _ids(rig.observe().trades)
    assert len(during) >= OUTAGE_S * 2 - 2  # live publication never waited on storage
    assert rig.book_phase() is BookPhase.LIVE
    assert rig.writer.failed_batches > 0
    assert any(str(e.get("event", "")).startswith("trade write-behind failed") for e in logs)
    assert _ids(rig.writer.persisted_trades) < during  # never acknowledged what failed

    rig.writer.down = False
    marker = len(rig.writer.persisted_trades)
    await feed.run(BACKOFF_CAP_S + 2.0)  # the write-behind retries on its 10 s capped backoff
    assert len(rig.writer.persisted_trades) > marker  # writes resume after recovery


async def _refresh(rig: Rig, feed: Feeder) -> BaseException | None:
    """One catalogue refresh while the venue keeps streaming (REST retries on virtual time)."""
    task = spawn(rig.instruments.refresh_now(), name="s11-refresh")
    await feed.run_while(task, within_s=300)
    return task.exception()


async def test_s11_catalogue_outage_serves_last_snapshot_marked_stale(rig: Rig) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(2.0)
    assert rig.health_report() == "ok"
    errors = metric(instruments_refresh_total, result="error")
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=40, path=CATALOGUE_PATH))
    failed = await _refresh(rig, feed)
    assert isinstance(failed, InstrumentRefreshError), failed
    snap = rig.instruments.snapshot()
    assert snap is not None and snap.get("BTCUSDT") is not None  # still serving
    assert snap.stale_since_us is not None  # and visibly stale (SCR health)
    assert rig.is_listed("BTCUSDT")
    assert metric(instruments_refresh_total, result="error") == errors + 1
    # #2715: degraded at once (the snapshot is minutes old, the TTL is 12 h)
    assert rig.svc.health().detail == HealthReason.CATALOGUE_STALE

    rig.ex.clear(FaultKind.HTTP_STATUS, path=CATALOGUE_PATH)  # the outage ends
    assert await _refresh(rig, feed) is None  # the next refresh succeeds ...
    assert rig.health_report() == "ok"  # ... and clears the stale mark


async def test_s11_buffered_writes_drain_after_the_outage(rig: Rig) -> None:
    feed, _ = await _outage(rig)
    published = _ids(rig.observe().trades)
    rig.writer.down = False
    await feed.run(BACKOFF_CAP_S + 2.0)  # the retry may be parked on its capped backoff
    assert published <= _ids(rig.writer.persisted_trades), "outage-window prints never persisted"
