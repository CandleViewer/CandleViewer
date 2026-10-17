"""SR-E12-02 for non-time bars (#2093): `/market/bars` estimates the bars from the window's stored
prints after `no_data_recorded` and the 31 d cap, and before any bar is read. Stored rows, the
fake fetcher and `_client` are the main `/market/bars` contract module's."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, cast

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from candleviewer.api import market_bars
from candleviewer.api.market_bars import TradeTotalsSource
from candleviewer.bars.limits import MAX_WINDOW_BARS as CAP
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import QuestDbReader
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.repositories.rows import TradeTotals
from tests.contract.test_market_bars_contract import _P, _STORE, _T0, _client, _Fetch, _problem

_TICK = {**_P, "bar_type": "tick", "param": "100"}


def _fixed(prints: int, qty: Decimal, calls: list[TimeRange] | None = None) -> TradeTotalsSource:
    async def totals(symbol: str, rng: TimeRange) -> TradeTotals:
        (calls if calls is not None else []).append(rng)
        return TradeTotals(prints, qty)

    return totals


_SAYS = {  # tick and volume: about the estimate; delta and range: a bound; renko: an estimate
    "tick": "holds more than 250,000 tick bars, estimated from recorded trades",
    "volume": "holds more than 250,000 volume bars, estimated from recorded trades",
    "delta": "may hold more than 250,000 delta bars (at most one per recorded print)",
    "range": "may hold more than 250,000 range bars (at most one per recorded print)",
    "renko": "may hold more than 250,000 renko bars (estimated at one per recorded print)",
}


@pytest.mark.parametrize(
    ("bar_type", "param", "at_cap", "over"),  # (prints, qty): CAP bars, then CAP + 1
    [
        ("tick", "100", (100 * CAP, Decimal(1)), (100 * CAP + 1, Decimal(1))),
        ("volume", "5", (1, Decimal(5 * CAP)), (1, Decimal(5 * CAP) + Decimal("0.001"))),
        ("delta", "1", (CAP, Decimal(CAP)), (CAP + 1, Decimal(CAP + 1))),
        ("range", "20", (CAP, Decimal(1)), (CAP + 1, Decimal(1))),
        ("renko", "20", (CAP, Decimal(1)), (CAP + 1, Decimal(1))),
    ],
)
def test_at_the_cap_is_served_and_one_bar_over_is_refused_before_any_read(
    bar_type: str, param: str, at_cap: tuple[int, Decimal], over: tuple[int, Decimal]
) -> None:
    q = {**_P, "bar_type": bar_type, "param": param}
    ok = _client(totals=_fixed(*at_cap)).get("/market/bars", params=q)
    assert ok.status_code == 200 and ok.json()["bars"], ok.text
    fetch = _Fetch()
    resp = _client(totals=_fixed(*over), fetch=fetch).get("/market/bars", params=q)
    body = _problem(resp, 422, "bar_window_too_large")
    assert body["detail"] == f"The window {_SAYS[bar_type]}; narrow from/to." and fetch.calls == 0


@pytest.mark.parametrize(
    ("kw", "params", "status", "code"),
    [
        ({"perms": None}, _TICK, 401, "unauthenticated"),
        ({"perms": frozenset({"orders:read"})}, _TICK, 403, "forbidden"),
        ({}, {**_TICK, "symbol": "NOPEUSDT"}, 422, "validation_failed"),
        ({}, {**_TICK, "cursor": "nope"}, 400, "invalid_cursor"),
    ],
    ids=["401", "403", "unlisted-symbol", "invalid-cursor"],
)
def test_a_request_refused_before_the_estimate_takes_no_count(
    kw: dict[str, Any], params: dict[str, Any], status: int, code: str
) -> None:
    calls: list[TimeRange] = []
    client = _client(totals=_fixed(10**12, Decimal(10**12), calls), **kw)
    _problem(client.get("/market/bars", params=params), status, code)
    assert calls == []


def test_no_count_for_a_pre_recording_or_over_31_day_window_or_for_time_bars() -> None:
    calls: list[TimeRange] = []
    over = _fixed(10**12, Decimal(10**12), calls)
    early = _client(totals=over, recording_us=_T0 + 1).get("/market/bars", params=_TICK)
    _problem(early, 422, "no_data_recorded")  # precedence: before the estimate
    wide = _client(totals=over).get("/market/bars", params={**_TICK, "to": "2099-01-01T00:00:00Z"})
    assert "31 days" in _problem(wide, 422, "bar_window_too_large")["detail"]
    time_q = {**_P, "bar_type": "time", "param": "1"}
    assert _client(totals=over).get("/market/bars", params=time_q).status_code == 200
    assert calls == []


def test_the_count_covers_the_window_the_read_pages_through() -> None:
    """Uncursored: [from, to). Cursored: from the cursor's bar, the first of the next page."""
    calls: list[TimeRange] = []
    client = _client(totals=_fixed(1, Decimal(1), calls))
    q = {**_TICK, "limit": 1}
    cursor = client.get("/market/bars", params=q).json()["meta"]["next_cursor"]
    assert client.get("/market/bars", params={**q, "cursor": cursor}).status_code == 200
    start, end = market_bars._ts_us(_P["from"]), market_bars._ts_us(_P["to"])
    second = int(str(_STORE["tick:100"][1]["ts"]))
    assert start is not None and end is not None
    assert calls == [TimeRange(start_us=start, end_us=end), TimeRange(start_us=second, end_us=end)]


def _raising(error: Exception) -> TradeTotalsSource:
    async def failing(symbol: str, rng: TimeRange) -> TradeTotals:
        raise error

    return failing


class _DriverDown:
    """A pg-wire connection whose query dies in asyncpg, under the real reader and repository."""

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        raise asyncpg.exceptions.ConnectionDoesNotExistError("connection was closed")


_DOWN = QuestDbMarketDataRepository(cast(IlpWriter, None), QuestDbReader(_DriverDown()))


@pytest.mark.parametrize(
    ("source", "error", "cause"),
    [
        (_raising(TimeoutError()), "TimeoutError", None),
        (_raising(OSError("down")), "OSError", None),
        (_raising(StorageTierUnavailable()), "StorageTierUnavailable", None),
        (_DOWN.trade_totals, "StorageTierUnavailable", "ConnectionDoesNotExistError"),
    ],
    ids=["timeout", "os", "tier", "asyncpg"],
)
def test_a_count_that_fails_is_503_logged_by_type_and_nothing_is_read(
    source: TradeTotalsSource, error: str, cause: str | None
) -> None:
    fetch = _Fetch()
    with capture_logs() as logs:
        resp = _client(totals=source, fetch=fetch).get("/market/bars", params=_TICK)
    detail = _problem(resp, 503, "store_unavailable")["detail"]
    assert detail == "Trade storage is unavailable; retry shortly or narrow from/to."
    assert fetch.calls == 0
    entry = {"event": "market_bars_estimate_failed", "log_level": "warning", "error": error,
             "cause": cause}  # fmt: skip
    assert [e for e in logs if e["event"].startswith("market_bars")] == [entry]  # type only


def test_no_count_source_fails_closed_for_non_time_bars_only() -> None:
    fetch = _Fetch()
    resp = _client(totals=None, fetch=fetch).get("/market/bars", params=_TICK)
    _problem(resp, 503, "store_unavailable")
    assert fetch.calls == 0
    time_q = {**_P, "bar_type": "time", "param": "1"}
    assert _client(totals=None).get("/market/bars", params=time_q).status_code == 200


async def test_a_count_that_outlives_the_query_timeout_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count runs under `QUERY_TIMEOUT_S` (10 ms here): a store that never answers is a 503,
    not a hung request. The outer 30 s bound only trips on a build that lost the timeout."""
    monkeypatch.setattr(market_bars, "QUERY_TIMEOUT_S", 0.01)

    async def stalled(symbol: str, rng: TimeRange) -> TradeTotals:
        await asyncio.Event().wait()  # never set
        raise AssertionError("unreachable")

    app = cast(FastAPI, _client(totals=stalled).app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        with capture_logs() as logs:
            resp = await asyncio.wait_for(c.get("/market/bars", params=_TICK), 30)
    _problem(resp, 503, "store_unavailable")
    errors = [e.get("error") for e in logs if e["event"].startswith("market_bars")]
    assert errors == ["TimeoutError"]
