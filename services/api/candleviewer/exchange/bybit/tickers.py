"""Bybit v5 venue-wide tickers (`GET /v5/market/tickers`, `category=linear`; E08-T08, #4707).

All wire knowledge for the endpoint lives here (C-2.2): the params, the reply's `time` and its
`result.list` rows, each read through the stream parser's own field table (`ticker.py`), so a REST
row and a stream frame map alike, `highPrice24h` / `lowPrice24h` included. Public data only: one
`BybitRestClient.get_public` call in the `MARKET_DATA` bucket, so a read never draws on the
stop/cancel/SL reserve of the order or position buckets (C-12.7); a venue or transport failure
raises the client's taxonomy error.

Validated before anything is returned (STRIDE D1, as the funding history): an envelope fault (no
`linear` result, no row list, more than `MAX_ROWS` rows, an implausible `time`) fails the whole read
with `ValueError`, while a malformed or implausible row is skipped and counted in
`TickerPage.rejected` (fail closed per row), so one odd listing never hides the others. A row of a
`linear` contract that is no USDT perpetual (a USDC perpetual, a dated future) is left out
uncounted: those are not CandleViewer instruments (C-1.2). The rows are parsed off the event loop:
one reply holds every linear contract.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from candleviewer.exchange.base.frame_guard import check_event_ts
from candleviewer.exchange.base.ticker_delta import TickerDelta
from candleviewer.exchange.base.universe import TickerPage, TickersFetcher
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.risk_limits import PublicGetter
from candleviewer.exchange.bybit.ticker import parse_ticker_row

PATH: Final = "/v5/market/tickers"
#: Bound on one reply's rows (C-2.18): the venue lists some 600 linear contracts.
MAX_ROWS: Final = 2000
#: A USDT linear perpetual (22 `Symbol`); another well-formed contract name is out of scope.
_USDT_PERPETUAL: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
_CONTRACT: Final = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,30}$")


def parse_tickers_reply(payload: Mapping[str, Any]) -> TickerPage:
    """One reply's tickers, keyed by symbol in the venue's order, all at the reply's `time`."""
    result = payload.get("result")
    if not isinstance(result, Mapping) or result.get("category") != "linear":
        raise ValueError("tickers: no linear result object")
    rows = result.get("list")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError(f"tickers: the row list is missing or over {MAX_ROWS} rows")
    ts = payload.get("time")
    if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
        raise ValueError("tickers: no reply time")
    check_event_ts(ts, None)
    tickers: dict[str, TickerDelta] = {}
    rejected = 0
    for row in rows:
        symbol = row.get("symbol") if isinstance(row, dict) else None
        named = isinstance(symbol, str) and _CONTRACT.fullmatch(symbol) is not None
        if named and not _USDT_PERPETUAL.fullmatch(str(symbol)):
            continue  # a USDC perpetual or a dated future: no instrument here
        try:
            delta = parse_ticker_row(row, ts_ms=ts)
        except ValueError:
            rejected += 1
            continue
        if delta.symbol in tickers:
            rejected += 1  # a repeated symbol: the first row stands
            continue
        tickers[delta.symbol] = delta
    return TickerPage(ts * 1000, MappingProxyType(tickers), rejected)


async def fetch_tickers(client: PublicGetter) -> TickerPage:
    """Every linear ticker, in one public read."""
    payload = await client.get_public(
        PATH, params={"category": "linear"}, endpoint_class=EndpointClass.MARKET_DATA
    )
    return await asyncio.to_thread(parse_tickers_reply, payload)


def make_tickers_fetcher(client: PublicGetter) -> TickersFetcher:
    """The neutral `TickersFetcher` port over the governed public client (C-2.2)."""

    async def _fetch() -> TickerPage:
        return await fetch_tickers(client)

    return _fetch


__all__ = ["MAX_ROWS", "PATH", "fetch_tickers", "make_tickers_fetcher", "parse_tickers_reply"]
