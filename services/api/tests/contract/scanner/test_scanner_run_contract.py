"""E08-T09 (#4708) PR 2b: `runScanner` (`GET /scanner`) through the real app (session, RBAC, the
router and `ScannerService` over a fake ticker snapshot and recorded set) answers only what
22-api-openapi.yaml documents, with schema-valid bodies, at 200, 401, 422, 429 and 503, and a
Hypothesis strategy over valid `ScannerFilter`s, `sort` keys and limits finds no 200 body that
violates `ScannerRow` / `ScannerMeta`. Not reached here: `403` (every role holds
`marketdata:read`; the router tests check it)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from _scanner_contract import Api
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.api.scanner_criteria import CRITERIA, SORT_KEY_AVAILABLE
from candleviewer.api.scanner_service import ScannerService
from tests.contract.rbac.rbac_harness import bearer
from tests.scanner._scan_env import FakeRecording, FakeUniverse, entry, ticker, universe

_RANGES = [c.id for c in CRITERIA if c.available and c.kind == "range"]
_SORTS = sorted(k for k, ok in SORT_KEY_AVAILABLE.items() if ok)


def _tickers() -> dict[str, Any]:
    rows = [
        ticker(
            f"S{i:03d}USDT",
            turnover_24h=Decimal(i * 1000),
            volume_24h=Decimal(i),
            funding_rate=Decimal(i - 20) / 10000,
        )
        for i in range(40)
    ]
    rows.append(ticker("NOBOOKUSDT", bid1_price=None, high_24h=None, last_price=None))
    return universe(rows)


@pytest.fixture
def scan(api: Api) -> Iterator[Api]:
    state = api.world.app.state
    svc: ScannerService = state.scanner_service
    svc.invalidate()
    saved = (state.ticker_universe, state.recording_control)
    state.ticker_universe = FakeUniverse(_tickers())
    state.recording_control = FakeRecording([entry("S001USDT"), entry("S002USDT")])
    try:
        yield api
    finally:
        state.ticker_universe, state.recording_control = saved
        svc.invalidate()


def test_run_scanner_conforms_at_200_401_and_422(scan: Api) -> None:
    ok = scan.send("viewer", "runScanner", params={"limit": "10", "sort": "funding_rate"})
    assert ok.status_code == 200 and len(ok.json()["items"]) == 10
    every = scan.send("owner", "runScanner", params={"limit": "200"})
    assert {r["coverage"] for r in every.json()["items"]} == {"recorded", "live_only"}
    unauthenticated = scan.send("unauthenticated", "runScanner")
    assert unauthenticated.status_code == 401
    inverted = json.dumps({"funding_rate": {"min": "0.01", "max": "0.001"}})
    refused = scan.send("viewer", "runScanner", params={"filters": inverted})
    assert refused.status_code == 422
    assert refused.json()["errors"] == [
        {
            "field": "filters.funding_rate",
            "rule": "range_inverted",
            "message": refused.json()["errors"][0]["message"],
        }
    ]
    repeated = scan.world.client.get("/scanner?limit=1&limit=2", headers=bearer("viewer"))
    assert repeated.json()["errors"][0]["rule"] == "multiple_values"


def test_run_scanner_conforms_at_429_and_503(scan: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    state = scan.world.app.state
    state.ticker_universe = None
    down = scan.send("manager_with_grant", "runScanner")
    assert (down.status_code, down.headers["retry-after"]) == (503, "5")
    state.ticker_universe = FakeUniverse(_tickers())
    svc: ScannerService = state.scanner_service
    # the app's one service, built at startup: a synchronous client cannot hold evaluations
    # open, so the bound is lowered on it for this request (restored by monkeypatch)
    monkeypatch.setattr(svc, "_max_cold", 0)
    busy = scan.send("manager_with_grant", "runScanner", params={"limit": "7"})
    assert (busy.status_code, busy.headers["retry-after"]) == (429, "1")


_DEC = st.integers(-(10**6), 10**6).map(lambda i: Decimal(i) / 1000)


@st.composite
def _range(draw: st.DrawFn) -> dict[str, str]:
    lo, hi = sorted(draw(st.lists(_DEC, min_size=2, max_size=2, unique=True)))
    side = draw(st.sampled_from(["min", "max", "both"]))
    return (
        {"min": str(lo)}
        if side == "min"
        else {"max": str(hi)}
        if side == "max"
        else {"min": str(lo), "max": str(hi)}
    )


_FILTERS = st.dictionaries(st.sampled_from(_RANGES), _range(), max_size=len(_RANGES))


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(flt=_FILTERS, sort=st.sampled_from(_SORTS), limit=st.integers(1, 200))
def test_every_valid_scan_answers_a_contract_body(
    scan: Api, flt: dict[str, Any], sort: str, limit: int
) -> None:
    params = {"filters": json.dumps(flt), "sort": sort, "limit": str(limit)}
    r = scan.send("viewer", "runScanner", params=params)
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) <= limit
