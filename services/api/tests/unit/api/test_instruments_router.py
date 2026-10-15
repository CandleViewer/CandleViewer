"""Unit tests for `candleviewer.api.instruments` (E08-S01-2): listing from
the snapshot with `cache_age_s`/`stale_since`, delisted exclusion + detail
flag, unknown-symbol on-demand refresh, RBAC fail-closed (501/401/403),
paging, and a p95 < 50 ms read-latency measurement that never touches the
upstream fetcher."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.instruments import InstrumentsPrincipal, make_instruments_router
from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.ingestion.instruments import CatalogueSnapshot


def raw(symbol: str, **overrides: object) -> dict[str, object]:
    r: dict[str, object] = {
        "symbol": symbol,
        "baseCoin": symbol.removesuffix("USDT"),
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "status": "Trading",
        "launchTime": "1585699200000",
        "priceScale": "2",
        "priceFilter": {"tickSize": "0.10"},
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "100"},
        "leverageFilter": {"maxLeverage": "100.00"},
    }
    r.update(overrides)
    return r


_NOW = 1_700_000_000_000_000


def _inst(symbol: str, status: str = "Trading") -> Instrument:
    return parse_instrument(raw(symbol, status=status), fetched_at_us=_NOW - 30_000_000)


class FakeReader:
    def __init__(
        self,
        snap: CatalogueSnapshot | None,
        extra: Instrument | None = None,
        loads: CatalogueSnapshot | None = None,
    ) -> None:
        self._snap = snap
        self._extra = extra
        self._loads = loads  # the snapshot an on-demand refresh loads (None: still down)
        self.ensure_calls: list[str] = []

    def snapshot(self) -> CatalogueSnapshot | None:
        return self._snap

    async def ensure_symbol(self, symbol: str) -> Instrument | None:
        self.ensure_calls.append(symbol)
        if self._loads is not None:
            self._snap = self._loads
            return self._loads.get(symbol)
        if self._extra is not None and self._extra.symbol == symbol:
            return self._extra
        return None


class Resolver:
    def __init__(self, principal: InstrumentsPrincipal | None) -> None:
        self._p = principal

    def resolve(self, request: Request) -> InstrumentsPrincipal | None:
        return self._p


VIEWER = Resolver(InstrumentsPrincipal(user_id="u", permissions=frozenset({"instruments:read"})))


def _snap(stale_since_us: int | None = None) -> CatalogueSnapshot:
    items = [_inst("BTCUSDT"), _inst("ETHUSDT"), _inst("LUNAUSDT", "Closed")]
    return CatalogueSnapshot(
        by_symbol={i.symbol: i for i in items},
        fetched_at_us=_NOW - 30_000_000,
        stale_since_us=stale_since_us,
    )


def _client(reader: FakeReader | None, resolver: Resolver | None = VIEWER) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_instruments_router(lambda: reader, principal_resolver=resolver, now_us=lambda: _NOW)
    )
    return TestClient(app)


def test_list_returns_trading_symbols_with_cache_age() -> None:
    r = _client(FakeReader(_snap())).get("/instruments")
    assert r.status_code == 200
    body = r.json()
    assert [i["symbol"] for i in body["items"]] == ["BTCUSDT", "ETHUSDT"]
    assert body["meta"]["cache_age_s"] < 60
    assert body["meta"]["stale_since"] is None
    assert body["items"][0]["status"] == "Trading" and body["items"][0]["delisted"] is False
    assert body["items"][0]["tick_size"] == "0.10"


def test_list_reports_stale_since_when_refresh_failing() -> None:
    body = _client(FakeReader(_snap(stale_since_us=_NOW))).get("/instruments").json()
    assert body["meta"]["stale_since"].endswith("Z")
    assert len(body["items"]) == 2  # previous catalogue keeps serving


def test_delisted_detail_reports_delisted() -> None:
    body = _client(FakeReader(_snap())).get("/instruments/LUNAUSDT").json()
    assert body["delisted"] is True and body["status"] == "Closed"
    assert body["status_reason"]


def test_status_filter_can_include_closed() -> None:
    body = _client(FakeReader(_snap())).get("/instruments?status=Closed").json()
    assert [i["symbol"] for i in body["items"]] == ["LUNAUSDT"]


def test_query_and_paging() -> None:
    c = _client(FakeReader(_snap()))
    assert [i["symbol"] for i in c.get("/instruments?q=eth").json()["items"]] == ["ETHUSDT"]
    p1 = c.get("/instruments?limit=1").json()
    assert p1["meta"]["has_more"] is True
    p2 = c.get(f"/instruments?limit=1&cursor={p1['meta']['next_cursor']}").json()
    assert [i["symbol"] for i in p2["items"]] == ["ETHUSDT"] and p2["meta"]["has_more"] is False
    assert c.get("/instruments?cursor=!!").status_code == 400


def test_unknown_symbol_triggers_on_demand_refresh() -> None:
    reader = FakeReader(_snap(), extra=_inst("NEWUSDT"))
    r = _client(reader).get("/instruments/NEWUSDT")
    assert r.status_code == 200 and reader.ensure_calls == ["NEWUSDT"]
    r404 = _client(reader).get("/instruments/NOPEUSDT")
    assert r404.status_code == 404


def test_not_loaded_is_503_never_empty() -> None:
    assert _client(FakeReader(None)).get("/instruments").status_code == 503
    assert _client(None).get("/instruments").status_code == 503


def test_detail_refreshes_on_demand_before_any_snapshot_is_loaded() -> None:
    """#2599: after a failed cold start the detail route still triggers its on-demand refresh."""
    reader = FakeReader(None, loads=_snap())
    r = _client(reader).get("/instruments/BTCUSDT")
    assert r.status_code == 200, r.text
    assert r.json()["symbol"] == "BTCUSDT" and reader.ensure_calls == ["BTCUSDT"]


def test_detail_stays_503_when_the_on_demand_refresh_loads_nothing() -> None:
    """#2599: no catalogue even after the refresh -> 503, never a false 404 for a real symbol."""
    reader = FakeReader(None)
    assert _client(reader).get("/instruments/BTCUSDT").status_code == 503
    assert reader.ensure_calls == ["BTCUSDT"]
    assert _client(None).get("/instruments/BTCUSDT").status_code == 503  # no catalogue wired


def test_rbac_fail_closed() -> None:
    reader = FakeReader(_snap())
    assert _client(reader, resolver=None).get("/instruments").status_code == 501
    assert _client(reader, resolver=Resolver(None)).get("/instruments").status_code == 401
    no_perm = Resolver(InstrumentsPrincipal(user_id="u", permissions=frozenset({"x:read"})))
    assert _client(reader, resolver=no_perm).get("/instruments/BTCUSDT").status_code == 403


def test_invalid_symbol_is_400() -> None:
    assert _client(FakeReader(_snap())).get("/instruments/bad-sym").status_code == 400


@pytest.mark.perf
async def test_list_p95_under_50ms_from_snapshot() -> None:
    """Handler-level latency (the route coroutine awaited directly, so the
    number reflects snapshot filtering + serialisation, not TestClient's
    thread hop on a loaded CI box)."""
    items = [_inst(f"S{n:04d}USDT") for n in range(600)]
    snap = CatalogueSnapshot(by_symbol={i.symbol: i for i in items}, fetched_at_us=_NOW)
    reader = FakeReader(snap)
    router = make_instruments_router(lambda: reader, principal_resolver=VIEWER, now_us=lambda: _NOW)
    endpoint = next(
        r.endpoint  # type: ignore[attr-defined]  # APIRoute exposes endpoint
        for r in router.routes
        if getattr(r, "path", "") == "/instruments"
    )
    request = Request({"type": "http", "method": "GET", "path": "/instruments", "headers": []})
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        resp = await endpoint(
            request=request,
            cursor=None,
            limit=100,
            q=None,
            status=None,
            recorded_only=False,
            sort="symbol",
        )
        samples.append(time.perf_counter() - t0)
        assert resp.status_code == 200
    samples.sort()
    p95_ms = samples[189] * 1000
    print(f"GET /instruments handler p95={p95_ms:.2f}ms over 200 req, 600 symbols")
    assert p95_ms < 50
    assert reader.ensure_calls == []  # listing never touches upstream
