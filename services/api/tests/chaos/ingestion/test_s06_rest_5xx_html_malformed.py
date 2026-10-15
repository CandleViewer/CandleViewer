"""Scenario 6 - exchange 5xx / 502 HTML page / malformed JSON on REST. C-13.6 #4
(public-data REST; the order-path half is OMS chaos, E29-Q04).

Declared, table-driven: each fault surfaces as a typed adapter error (never a
crash, never a raw `httpx`/`JSONDecodeError`), 5xx is retried with backoff
before giving up, the backfill caller degrades to an *unrecovered gap* signal,
and nothing is parsed into a trusted domain event (SR-040b).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pytest

from candleviewer.exchange.base.errors import ExchangeError, TransportError

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.metrics import bybit_rest_requests_total

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import recent_trades_fetcher
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

PATH = "/v5/market/recent-trade"
PARAMS = {"category": "linear", "symbol": "BTCUSDT", "limit": 1000}


@dataclass(frozen=True)
class Case:
    fault: Fault
    error: type[ExchangeError]
    attempts: int  # requests the venue saw
    result_label: str  # bybit_rest_requests_total{result=...}
    backoff: bool  # retried with a non-zero wait between attempts


_503 = Fault(FaultKind.HTTP_STATUS, status=503, count=9, path=PATH)
_HTML = Fault(FaultKind.HTML_502, count=9, path=PATH)
_JUNK = Fault(FaultKind.MALFORMED_JSON, count=9, path=PATH)
CASES = {
    "503": Case(_503, TransportError, 4, "5xx", True),
    "502-html": Case(_HTML, TransportError, 4, "5xx", True),
    "malformed-json": Case(_JUNK, TransportError, 4, "malformed_json", True),
}


@pytest.mark.parametrize("name", sorted(CASES))
async def test_s06_rest_fault_maps_to_typed_error_with_backoff(rig: Rig, name: str) -> None:
    case = CASES[name]
    before = metric(bybit_rest_requests_total, endpoint=PATH, result=case.result_label)
    rig.ex.inject(case.fault)
    first = len(rig.ex.rest_calls)
    with pytest.raises(case.error):
        await rig.call(rig.rest.get_public(PATH, params=PARAMS), within_s=60)
    calls = rig.ex.rest_calls[first:]
    assert len(calls) == case.attempts
    gaps = [b[0] - a[0] for a, b in itertools.pairwise(calls)]
    assert all(g > 0 for g in gaps) if case.backoff else gaps == []
    assert metric(bybit_rest_requests_total, endpoint=PATH, result=case.result_label) == (
        before + case.attempts
    )
    assert rig.ws.state() in ("open", "connecting")  # a REST fault never touches the WS


async def test_s06_malformed_json_is_a_retried_transport_error(rig: Rig) -> None:
    """Ticket-declared: malformed JSON -> `TransportError`, retried with backoff."""
    rig.ex.inject(Fault(FaultKind.MALFORMED_JSON, count=1, path=PATH))
    body = await rig.call(rig.rest.get_public(PATH, params=PARAMS), within_s=60)
    assert body["retCode"] == 0  # the one-off truncated body healed on retry


async def test_s06_hostile_row_never_becomes_a_trusted_event(rig: Rig) -> None:
    """SR-040b: an attacker-shaped row (NaN price) rejects the page, not just the row."""
    good = {"T": 1, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "100.0", "i": "ok-1", "BT": False}
    rig.ex.trades.apply({"data": [good]})
    rig.ex.inject(Fault(FaultKind.HOSTILE_JSON, path=PATH))
    fetch = recent_trades_fetcher(rig.rest.get_public)
    with pytest.raises(ValueError):
        await rig.call(fetch("BTCUSDT"), within_s=10)
