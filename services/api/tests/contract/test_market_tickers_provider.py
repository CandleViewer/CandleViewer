"""E08-T08 (#4707): `GET /market/tickers` served against `22-api-openapi.yaml` (`getTickers`).

Provider side: every answer validates against `TickersResponse` or `Problem`; RBAC before anything
else (C-12.4); the symbols list as the contract bounds it; one venue read shared by every caller
(AC 5). The venue read is faked; its pages go through the adapter's real parser, from the recorded
replies (`tests/_tickers.py`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import jsonschema
import pytest
from fastapi import FastAPI, Request

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.instruments import InstrumentsPrincipal
from candleviewer.api.ticker import make_tickers_router
from candleviewer.exchange.base.ticker_delta import TickerDelta
from candleviewer.exchange.base.universe import TickerPage
from candleviewer.exchange.bybit.tickers import parse_tickers_reply
from candleviewer.ingestion.ticker_bulk import TickerBulkCache
from tests import _tickers as t
from tests.openapi_helpers import deref

_SPEC: dict[str, Any] = load_openapi_spec()
ANSWER = deref(_SPEC, _SPEC["components"]["schemas"]["TickersResponse"])
PROBLEM = deref(_SPEC, _SPEC["components"]["schemas"]["Problem"])
THREE = t.SYMBOLS


class _Resolver:
    def __init__(self, perms: frozenset[str] | None) -> None:
        self.perms = perms

    def resolve(self, request: Request) -> InstrumentsPrincipal | None:
        return None if self.perms is None else InstrumentsPrincipal("u", self.perms)


READER = _Resolver(frozenset({"marketdata:read"}))


class Clock:
    def __init__(self) -> None:
        self.t = 50.0

    def __call__(self) -> float:
        return self.t


class Venue:
    """The venue-wide read, faked: counts calls; `gate` holds one open, `fail` makes it raise."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.page = parse_tickers_reply(reply)
        self.calls = 0
        self.gate: asyncio.Event | None = None
        self.fail: Exception | None = None

    async def __call__(self) -> TickerPage:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return self.page


def _app(source: TickerBulkCache | None, resolver: _Resolver | None = READER) -> FastAPI:
    app = FastAPI()
    app.include_router(make_tickers_router(lambda: source, principal_resolver=resolver))
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _get(app: FastAPI, *symbols: str) -> httpx.Response:
    async with _client(app) as client:
        return await client.get("/market/tickers", params=[("symbols", s) for s in symbols])


def _when(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


async def _until(predicate: Callable[[], bool]) -> None:
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0)
    pytest.fail("condition never held")


async def test_twenty_clients_asking_the_same_120_symbols_within_5_s_cause_one_read() -> None:
    """AC 5. The 120 items expand in-test from the three recorded replies' items, varying only
    `symbol` and `lastPrice` (`tests/_tickers.py`), in one recorded envelope."""
    rows = t.priced(120)
    reply = t.reply(rows)
    venue, clock = Venue(reply), Clock()
    venue.gate = asyncio.Event()
    cache = TickerBulkCache(venue, clock=clock)
    symbols = [r["symbol"] for r in rows]
    query = [("symbols", s) for s in symbols]
    async with _client(_app(cache)) as client:
        pending = [
            asyncio.create_task(client.get("/market/tickers", params=query)) for _ in range(20)
        ]
        await _until(lambda: cache.waiters == 20)
        venue.gate.set()
        answers = await asyncio.gather(*pending)
        clock.t += 4.9  # every one of them within 5 s of the read
        answers.append(await client.get("/market/tickers", params=query))
    assert venue.calls == 1
    taken = datetime.fromtimestamp(reply["time"] / 1000, tz=UTC)
    for resp in answers:
        assert resp.status_code == 200
        body = resp.json()
        jsonschema.validate(body, ANSWER)
        assert [i["symbol"] for i in body["items"]] == symbols and body["unknown_symbols"] == []
        assert {(_when(i["ts"]), i["stale"]) for i in body["items"]} == {(taken, False)}
        assert body["meta"] == {"next_cursor": None, "has_more": False, "count": 120}
    prices = [i["last_price"] for i in answers[0].json()["items"]]
    assert prices == [r["lastPrice"] for r in rows]


async def test_a_failed_read_serves_the_snapshot_stale_up_to_15_s_then_answers_503() -> None:
    """AC 5, failure case: no value older than the 15 s bound is ever served as current."""
    venue, clock = Venue(t.reply([t.row(s) for s in THREE])), Clock()
    app = _app(TickerBulkCache(venue, clock=clock))
    assert (await _get(app, "BTCUSDT")).status_code == 200
    venue.fail = RuntimeError("venue down")
    clock.t += 10.0
    stale = await _get(app, "BTCUSDT", "ETHUSDT")
    assert stale.status_code == 200 and venue.calls == 2
    assert [i["stale"] for i in stale.json()["items"]] == [True, True]
    clock.t += 5.5  # 15.5 s since the snapshot's receipt
    refused = await _get(app, "BTCUSDT")
    assert (refused.status_code, venue.calls) == (503, 3)
    assert refused.headers["content-type"] == "application/problem+json"
    assert refused.headers["retry-after"] == "5"  # the next read may start in 5 s
    body = refused.json()
    jsonschema.validate(body, PROBLEM)
    assert (body["code"], body["status"], body["retry_after_seconds"]) == (
        "exchange_unavailable",
        503,
        5,
    )


@pytest.mark.parametrize("route_first", [True, False])
async def test_the_route_and_the_scanners_refresh_share_one_read_budget(route_first: bool) -> None:
    """One venue budget (#4708): a route request and a `refresh()` within 5 s cause one read."""
    venue, clock = Venue(t.reply([t.row(s) for s in THREE])), Clock()
    cache = TickerBulkCache(venue, clock=clock)
    app = _app(cache)
    if route_first:
        assert (await _get(app, "BTCUSDT")).status_code == 200
    universe = await cache.refresh()
    clock.t += 4.9
    if not route_first:
        assert (await _get(app, "BTCUSDT")).status_code == 200
    assert venue.calls == 1 and universe is not None and cache.latest() is universe
    assert sorted(universe.tickers) == sorted(THREE)


async def test_unknown_symbols_are_reported_in_request_order_and_each_symbol_once() -> None:
    venue = Venue(t.reply([t.row("BTCUSDT"), t.row("ETHUSDT")]))
    resp = await _get(
        _app(TickerBulkCache(venue, clock=Clock())),
        *("SOLUSDT", "BTCUSDT", "NOSUCHUSDT", "BTCUSDT", "SOLUSDT"),
    )
    body = resp.json()
    jsonschema.validate(body, ANSWER)
    assert [i["symbol"] for i in body["items"]] == ["BTCUSDT"]
    assert body["unknown_symbols"] == ["SOLUSDT", "NOSUCHUSDT"] and body["meta"]["count"] == 1


async def test_an_item_carries_the_24h_range_and_leaves_out_what_the_venue_left_empty() -> None:
    """An empty value, and a 24 h high or low of `"0"` (no price), are left out, never `null`."""
    blank = {**t.row("ETHUSDT"), "openInterestValue": "", "highPrice24h": ""}
    zero = {**t.row("SOLUSDT"), "lowPrice24h": "0"}
    venue = Venue(t.reply([t.row("BTCUSDT"), blank, zero]))
    cache = TickerBulkCache(venue, clock=Clock())
    body = (await _get(_app(cache), "BTCUSDT", "ETHUSDT", "SOLUSDT")).json()
    jsonschema.validate(body, ANSWER)
    btc, eth, sol = body["items"]
    btc_row = t.row("BTCUSDT")
    assert (btc["high_24h"], btc["low_24h"]) == (btc_row["highPrice24h"], btc_row["lowPrice24h"])
    assert {"symbol", "ts", "stale", "next_funding_time", "bid1_size"} <= btc.keys()
    assert "high_24h" not in eth and "open_interest_value" not in eth and "low_24h" in eth
    assert "low_24h" not in sol and sol["high_24h"] == t.row("SOLUSDT")["highPrice24h"]
    assert None not in (*btc.values(), *eth.values(), *sol.values())


async def test_a_row_the_model_refuses_is_reported_unknown_and_never_served() -> None:
    """A row the parser passed but `TickerEvent` refuses is left out of the snapshot (counted),
    so its symbol is reported unknown; the others are served."""
    venue = Venue(t.reply([t.row(s) for s in THREE]))
    eth = venue.page.tickers["ETHUSDT"]
    fields = {**eth.fields, "next_funding_time": Decimal("0.5")}  # no whole microsecond
    refused = TickerDelta("ETHUSDT", True, eth.ts_event_us, fields)
    venue.page = TickerPage(venue.page.ts_event_us, {**venue.page.tickers, "ETHUSDT": refused})
    resp = await _get(_app(TickerBulkCache(venue, clock=Clock())), *THREE)
    body = resp.json()
    jsonschema.validate(body, ANSWER)
    assert [i["symbol"] for i in body["items"]] == ["BTCUSDT", "SOLUSDT"]
    assert body["unknown_symbols"] == ["ETHUSDT"] and body["meta"]["count"] == 2


async def test_a_row_beyond_the_length_or_scale_bound_is_reported_unknown_never_served() -> None:
    """Numeric fields are bounded in length and scale before they are stored: a recorded row with
    its price one place past the scale bound, and one with its rate one character past the length
    bound, are counted and left out of the snapshot, so their symbols are reported unknown."""
    eth, sol = t.row("ETHUSDT"), t.row("SOLUSDT")
    finer = {**eth, "lastPrice": t.widened(eth["lastPrice"], "scale", 1)}
    longer = {**sol, "fundingRate": t.widened(sol["fundingRate"], "length", 1)}
    venue = Venue(t.reply([t.row("BTCUSDT"), finer, longer]))
    assert venue.page.rejected == 2
    resp = await _get(_app(TickerBulkCache(venue, clock=Clock())), *THREE)
    body = resp.json()
    jsonschema.validate(body, ANSWER)
    assert [i["symbol"] for i in body["items"]] == ["BTCUSDT"]
    assert body["unknown_symbols"] == ["ETHUSDT", "SOLUSDT"] and body["meta"]["count"] == 1


@pytest.mark.parametrize(
    ("resolver", "status", "code"),
    [(None, 501, "internal_error"), (_Resolver(None), 401, "unauthenticated"),
     (_Resolver(frozenset({"orders:read"})), 403, "forbidden")],
    ids=["no-resolver", "no-session", "no-permission"],
)  # fmt: skip
async def test_rbac_refuses_before_the_list_is_read_or_the_venue_asked(
    resolver: _Resolver | None, status: int, code: str
) -> None:
    venue = Venue(t.reply([t.row()]))
    for query in ((), ("BTCUSDT",)):
        resp = await _get(_app(TickerBulkCache(venue, clock=Clock()), resolver), *query)
        assert (resp.status_code, resp.json()["code"]) == (status, code)
        jsonschema.validate(resp.json(), PROBLEM)
    assert venue.calls == 0


@pytest.mark.parametrize(
    "symbols",
    [
        [],
        ["btcusdt"],
        ["BTC-USDT"],
        ["BTCUSDC"],
        ["BTCUSDT,ETHUSDT"],
        ["BTCUSDT"] * 201,
        [s["symbol"] for s in t.priced(201)],
    ],
    ids=["none", "lowercase", "dash", "not-usdt", "comma-list", "201-repeats", "201-distinct"],
)
async def test_a_symbols_list_outside_the_contract_is_400_and_asks_no_venue(
    symbols: list[str],
) -> None:
    venue = Venue(t.reply([t.row()]))
    resp = await _get(_app(TickerBulkCache(venue, clock=Clock())), *symbols)
    assert (resp.status_code, resp.json()["code"], venue.calls) == (400, "validation_failed", 0)
    jsonschema.validate(resp.json(), PROBLEM)


async def test_two_hundred_symbols_is_the_cap_and_is_served() -> None:
    rows = t.priced(200)
    venue = Venue(t.reply(rows))
    resp = await _get(_app(TickerBulkCache(venue, clock=Clock())), *(r["symbol"] for r in rows))
    assert resp.status_code == 200 and resp.json()["meta"]["count"] == 200


async def test_without_a_venue_source_the_route_answers_503_and_never_a_value() -> None:
    resp = await _get(_app(None), "BTCUSDT")
    assert (resp.status_code, resp.json()["code"]) == (503, "exchange_unavailable")
    assert 1 <= int(resp.headers["retry-after"]) <= 5
    jsonschema.validate(resp.json(), PROBLEM)


async def test_a_cache_closed_before_its_first_read_answers_503_with_a_bounded_retry() -> None:
    """Closed before any read (the app stopping), no read starts and none ever did: 503 with its
    `Retry-After` within 1 to 5, never a 500."""
    venue = Venue(t.reply([t.row()]))
    cache = TickerBulkCache(venue, clock=Clock())
    await cache.aclose()
    resp = await _get(_app(cache), "BTCUSDT")
    assert (resp.status_code, resp.json()["code"], venue.calls) == (503, "exchange_unavailable", 0)
    assert resp.headers["retry-after"] == "1"
    jsonschema.validate(resp.json(), PROBLEM)
