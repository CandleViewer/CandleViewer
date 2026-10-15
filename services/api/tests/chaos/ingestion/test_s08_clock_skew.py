"""Scenario 8 - host clock jumps +-10 s (WSL sleep). C-13.6 #6.

Declared: a signed call that fails signature validation (`10002`) triggers a
ClockGuard re-measure, is retried exactly once with the corrected offset and
the drift alarm (`exchange_clock_drift_ms`, `clock_resync_triggered_total`)
fires; a second consecutive 10002 surfaces `ClockDriftError` distinctly.
Market data stays exchange-anchored: `ts_event` comes from the venue, so bar
boundaries (floor(ts_event / interval)) are unchanged by the host skew.
"""

from __future__ import annotations

import pytest

from candleviewer.exchange.base.errors import ClockDriftError

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import RestClientConfig

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rest import BybitRestClient

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.ingestion.metrics import (
    clock_resync_triggered_total,
    exchange_clock_drift_ms,
    trade_prints_rejected_total,
)
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import STUB_BASE_URL, Rig, metric

pytestmark = pytest.mark.chaos

SKEW_S = 10.0
PATH = "/v5/account/wallet-balance"
BAR_MS = 60_000


def _signed(rig: Rig, guard: ClockGuard) -> BybitRestClient:
    # Fixed test-only key id; M2 holds the secret and computes the MAC (C-2.7, #2339).
    signer = BybitSigner(fake_capability("chaos-test-key"), CREDENTIAL_ID)
    return BybitRestClient(
        RestClientConfig(base_url=STUB_BASE_URL),
        signer=signer,
        governor=rig.governor,
        clock_offset_ms_provider=lambda: guard.offset_ms_or_none() or 0,
        transport=rig.ex.transport,
        sleep=rig.clock.sleep,
        random_fn=rig.rng.random,
        wall_clock=rig.host_wall_s,
        on_signature_failure=guard.resync_after_signature_failure,
    )


def _guard(rig: Rig) -> ClockGuard:
    return rig.clock_guard  # the same guard the rig's EventWindow runs on


@pytest.mark.parametrize("skew", [SKEW_S, -SKEW_S])
async def test_s08_measured_skew_raises_the_drift_alarm_and_signs_correctly(
    rig: Rig, skew: float
) -> None:
    guard = _guard(rig)
    rig.ex.inject(Fault(FaultKind.CLOCK_JUMP, seconds=skew))
    await rig.call(guard.measure_once())
    assert abs(metric(exchange_clock_drift_ms) + skew * 1000) < 250  # offset = venue - host
    assert guard.health_severity() == "critical"  # > 2 000 ms: BybitClockDriftCritical
    client = _signed(rig, guard)
    try:
        body = await rig.call(client.signed_request("GET", PATH))
        assert body["retCode"] == 0  # corrected timestamp lands inside recv_window
    finally:
        await client.aclose()


async def test_s08_second_consecutive_10002_surfaces_clock_drift_distinctly(rig: Rig) -> None:
    guard = _guard(rig)
    await rig.call(guard.measure_once())  # offset ~0, then the venue rejects regardless
    rig.ex.inject(Fault(FaultKind.REJECT_SIGNED, count=2))
    client = _signed(rig, guard)
    first = len(rig.ex.rest_calls)
    try:
        with pytest.raises(ClockDriftError):
            await rig.call(client.signed_request("GET", PATH))
    finally:
        await client.aclose()
    assert len(rig.ex.trace.kinds("rest.10002")) == 2  # exactly one retry, never a loop
    signed = [p for _t, p in rig.ex.rest_calls[first:] if p == PATH]
    assert len(signed) == 2  # one re-signed retry; the re-measure (#1911) hits /market/time only


async def test_s08_signature_failure_remeasures_and_the_retry_succeeds(rig: Rig) -> None:
    guard = _guard(rig)
    await rig.call(guard.measure_once())
    # A venue-side step the host cannot see (no host-step detector) -> only 10002 reveals it.
    rig.ex.inject(Fault(FaultKind.VENUE_CLOCK_JUMP, seconds=SKEW_S))
    triggered = metric(clock_resync_triggered_total, reason="signature_failure")
    client = _signed(rig, guard)
    try:
        body = await rig.call(client.signed_request("GET", PATH))
    except ClockDriftError as exc:  # the retry failed too: report why, not the venue text
        pytest.fail(f"10002 retry failed again: no clock re-measure before re-signing ({exc})")
    finally:
        await client.aclose()
    assert metric(clock_resync_triggered_total, reason="signature_failure") == triggered + 1
    assert body["retCode"] == 0


@pytest.mark.parametrize("skew", [SKEW_S, -SKEW_S / 4])  # within the 5 s plausibility window
async def test_s08_bar_boundaries_stay_exchange_anchored(rig: Rig, skew: float) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(2.0)
    published = len(rig.observe().trades)
    rig.host_skew_s = skew  # the host (EventWindow's wall clock) jumps; the venue does not
    await feed.run(3.0)
    trades = [t for t in rig.observe().trades[published:] if hasattr(t, "ts_event")]
    venue = {r["i"]: int(r["T"]) for r in rig.ex.trades.prints["BTCUSDT"]}
    assert trades, "no prints published during the skew window"
    for t in trades:  # ts_event is the venue's T, never a host-clock stamp
        assert t.ts_event // 1000 == venue[t.trade_id]
        assert t.ts_event // 1000 // BAR_MS == venue[t.trade_id] // BAR_MS


async def test_s08_backward_jump_does_not_reject_live_prints(rig: Rig) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(2.0)
    published = len(rig.observe().trades)
    rejected = metric(trade_prints_rejected_total)
    rig.host_skew_s = -SKEW_S
    await feed.run(3.0)
    assert metric(trade_prints_rejected_total) == rejected, "venue-correct prints rejected"
    assert len(rig.observe().trades) - published >= 6
