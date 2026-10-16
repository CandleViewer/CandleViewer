"""Scenario 4 - trade-stream gap. C-13.6 #1 (public WS disconnect).

Declared: a reconnect (or lost frame) opens a gap window at the last print;
the first post-gap batch triggers a REST recent-trade backfill. Recoverable
window -> `GapEvent(recovered=True)` on `{env}.md.{sym}.gap`, missing prints
published with `source="backfill"`, no duplicates. Backfill impossible (REST
down) -> `GapEvent(recovered=False)` and `trade_gaps_total{recovered="false"}`
+1, which the `IngestionTradeGapUnrecovered` alert keys on - never absorbed.
#2715: health stays `degraded` (`trade_gap_unrecovered`) after live prints
resume, until a retried backfill covers the window once REST recovers; the
lost prints then reach the hot tier (never the live topic) and health is `ok`.
"""

from __future__ import annotations

import pytest

from candleviewer.ingestion.metrics import trade_backfill_rows_total, trade_gaps_total
from candleviewer.ingestion.service import HealthReason
from candleviewer.ingestion.trade_stream import BACKFILL_TIMEOUT_S, GAP_RETRY_MAX_S
from tests.chaos.ingestion._clock import ScenarioTimeoutError
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

TOPIC = "publicTrade.BTCUSDT"
BACKFILL_PATH = "/v5/market/recent-trade"
#: 3 retries x full-jitter backoff capped at 2/4/8 s (rest.py `_retry_after_default`).
BACKFILL_RETRY_BUDGET_S = 15.0


def _gaps(recovered: str) -> float:
    return metric(trade_gaps_total, symbol="BTCUSDT", recovered=recovered)


async def _feed_until_ok(rig: Rig, feed: Feeder, *, within_s: float) -> None:
    """The venue keeps trading while ingestion recovers; health `ok` is the SLO."""
    start = rig.clock.now
    while rig.health_report() != "ok":
        if rig.clock.now - start > within_s:
            detail = rig.svc.health().detail
            raise ScenarioTimeoutError(f"health not ok within {within_s}s ({detail})")
        await feed.run(1.0)


async def _reconnect_with_lost_prints(rig: Rig, feed: Feeder) -> list[str]:
    """Run, then drop prints on the wire and reset - the venue keeps trading."""
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(3.0)
    rig.observe()
    rig.ex.inject(Fault(FaultKind.DROP, topic=TOPIC, count=2))
    await feed.run(1.0)  # two trade frames lost on the wire
    lost = [r["i"] for r in list(rig.ex.trades.prints["BTCUSDT"])[-2:]]
    rig.ex.inject(Fault(FaultKind.RESET))
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="reopen")
    await feed.run(1.0)
    return lost


async def test_s04_gap_is_backfilled_and_reported_recovered(rig: Rig) -> None:
    feed = Feeder(rig.ex)
    before = _gaps("true")
    lost = await _reconnect_with_lost_prints(rig, feed)
    seen = rig.observe()
    assert [g.recovered for g in seen.gaps] == [True]
    assert seen.gaps[0].reason == "reconnect"
    assert _gaps("true") == before + 1
    by_id = {t.trade_id: t for t in seen.trades if hasattr(t, "trade_id")}
    assert set(lost) <= by_id.keys(), "lost prints not healed by the REST backfill"
    assert {by_id[i].source for i in lost} == {"backfill"}
    ids = [t.trade_id for t in seen.trades if hasattr(t, "trade_id")]
    assert len(ids) == len(set(ids)), "backfill duplicated live prints"


async def test_s04_unrecoverable_gap_raises_an_alert_signal(rig: Rig) -> None:
    feed = Feeder(rig.ex)
    before, errors = _gaps("false"), metric(trade_backfill_rows_total, result="error")
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    lost = await _reconnect_with_lost_prints(rig, feed)
    await feed.run(BACKFILL_RETRY_BUDGET_S)  # REST retries back off on the virtual clock
    seen = rig.observe()
    assert [g.recovered for g in seen.gaps] == [False]  # visible, never absorbed
    assert _gaps("false") == before + 1  # IngestionTradeGapUnrecovered fires on this
    # +1 per failed attempt: the first backfill, then each #2715 retry
    assert metric(trade_backfill_rows_total, result="error") >= errors + 1
    # #2715: live prints resumed, but the hole is still open while REST is down
    assert rig.svc.health().detail == HealthReason.TRADE_GAP_UNRECOVERED

    rig.ex.clear(FaultKind.HTTP_STATUS, path=BACKFILL_PATH)  # the REST outage ends
    await _feed_until_ok(rig, feed, within_s=GAP_RETRY_MAX_S + BACKFILL_TIMEOUT_S)
    await feed.run(1.0)  # the write-behind flushes the healed rows
    healed = {t.trade_id for t in rig.writer.persisted_trades if t.source == "backfill"}
    assert set(lost) <= healed, "lost prints not healed into the hot tier"
    live = {t.trade_id for t in rig.observe().trades if hasattr(t, "trade_id")}
    assert not set(lost) & live, "healed prints republished: time moved backwards"
    assert [g.recovered for g in rig.observe().gaps] == [False]  # the window's event stays


async def test_s04_rest_outage_during_backfill_does_not_recycle_the_ws(rig: Rig) -> None:
    """A REST outage must not starve the book / trigger WS reconnects (06 §6.1 isolation)."""
    feed = Feeder(rig.ex)
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    await _reconnect_with_lost_prints(rig, feed)
    opened = len(rig.ex.sockets)
    await feed.run(BACKFILL_RETRY_BUDGET_S)
    assert len(rig.ex.sockets) == opened, "WS recycled because the pump was blocked on REST"
    stale = [f for f in rig.observe().feed if f.state == "stale"]
    assert stale == [], "book went stale while its frames sat behind a backfill"
