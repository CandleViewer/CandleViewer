"""`GET /instruments/{symbol}/ticker` (E08-S03) and `GET /market/tickers` (E08-T08, #4707), both
in `docs/plan/22-api-openapi.yaml`.

`/instruments/{symbol}/ticker` serves the *merged* last-known ticker (always fully populated, never
a raw delta). RBAC (C-12.4) mirrors `api/instruments.py`: fail-closed 501/401/403. `404` for an
unknown symbol; `503` when the symbol is listed but no complete ticker exists yet (warming) or the
stream is not wired. `stale` is true while the topic is marked stale or reconnecting so clients
grey the cells.

`/market/tickers` (`getTickers`) answers 1 to 200 symbols from the shared venue-wide snapshot
(`ingestion.ticker_bulk`), RBAC first (`marketdata:read`, 501/401/403), then the list, read by hand
so a bad one is the contract's `400 validation_failed`: one item per symbol the snapshot holds, in
the order first asked, each with its `symbol`, its `ts` (the snapshot's) and its `stale`, and every
other symbol in `unknown_symbols`. No snapshot within its bound is `503 exchange_unavailable` with
`Retry-After`. Every problem carries its catalogued `code`. A field the venue left empty is left
out, never `null`, here and in the per-symbol ticker alike.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.exchange.base.models import TickerEvent
from candleviewer.ingestion.ticker_bulk import REFRESH_S, BulkTickers, TickersUnavailable

_REQUIRED_PERMISSION = "marketdata:read"
#: `getTickers`: 1 to 200 symbols, a watchlist's cap, each a 22 `Symbol`.
TICKERS_MAX: Final = 200
_SYMBOL: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
#: The REST `Ticker`'s decimals, by the `TickerEvent` field each one is read from (24 §2.3).
_DECIMALS: Final = (
    ("last_price", "last_price"), ("mark_price", "mark_price"), ("index_price", "index_price"),
    ("bid1_price", "bid1_price"), ("bid1_size", "bid1_qty"), ("ask1_price", "ask1_price"),
    ("ask1_size", "ask1_qty"), ("price_change_pct_24h", "price_24h_pcnt"),
    ("high_24h", "high_24h"), ("low_24h", "low_24h"), ("volume_24h", "volume_24h"),
    ("turnover_24h", "turnover_24h"), ("open_interest", "open_interest"),
    ("open_interest_value", "open_interest_value"), ("funding_rate", "funding_rate"),
)  # fmt: skip


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    """Sync or async resolver (`resolve(request)` may return an awaitable)."""

    def resolve(self, request: Request) -> Any: ...


class TickerReader(Protocol):
    def latest(self, symbol: str) -> TickerEvent | None: ...
    def phase(self, symbol: str) -> str | None: ...
    def is_listed(self, symbol: str) -> bool: ...


class TickersSource(Protocol):
    """The shared venue-wide snapshot (`ingestion.ticker_bulk.TickerBulkCache`)."""

    async def serve(self) -> BulkTickers: ...


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
    )


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(us: int | None) -> str | None:
    if us is None:
        return None
    return datetime.fromtimestamp(us / 1e6, tz=UTC).isoformat().replace("+00:00", "Z")


def serialize_ticker(event: TickerEvent, *, stale: bool) -> dict[str, object]:
    """The REST `Ticker`, `ts` its event time: a field the event lacks is left out, never `null`
    (E08-T08), so `symbol`, `ts` and `stale` are always there."""
    body: dict[str, object] = {"symbol": event.symbol}
    for name, field in _DECIMALS:
        value: Decimal | None = getattr(event, field)
        if value is not None:
            body[name] = _dec(value)
    if event.next_funding_time is not None:
        body["next_funding_time"] = _iso(event.next_funding_time)
    return body | {"ts": _iso(event.ts_event), "stale": stale}


def make_ticker_router(
    reader_provider: Callable[[], TickerReader | None],
    *,
    principal_resolver: _Resolver | None = None,
) -> APIRouter:
    router = APIRouter(tags=["instruments"])

    @router.get("/instruments/{symbol}/ticker")
    async def get_ticker(request: Request, symbol: str) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        resolved = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if not (principal.has(_REQUIRED_PERMISSION)):
            return _problem(403, "Forbidden", f"requires {_REQUIRED_PERMISSION}")
        if not (4 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum()):
            return _problem(400, "Bad request", "invalid symbol")
        symbol = symbol.upper()
        reader = reader_provider()
        if reader is None:
            return _problem(503, "Service unavailable", "ticker stream not running")
        if not reader.is_listed(symbol):
            return _problem(404, "Not found", f"unknown instrument {symbol}")
        event = reader.latest(symbol)
        if event is None:
            return _problem(503, "Service unavailable", f"ticker for {symbol} is warming up")
        stale = reader.phase(symbol) != "live"
        return JSONResponse(status_code=200, content=serialize_ticker(event, stale=stale))

    return router


def _coded(status: int, code: str, title: str, detail: str, **extra: int) -> JSONResponse:
    """RFC 9457 with its catalogued `code` (`Problem.code` is required); `retry_after_seconds`
    is also sent as `Retry-After`."""
    body = {"type": f"https://candleviewer.local/errors/{code}", "title": title, "status": status,
            "code": code, "detail": detail, **extra}  # fmt: skip
    retry = extra.get("retry_after_seconds")
    headers = None if retry is None else {"Retry-After": str(retry)}
    return JSONResponse(body, status, headers=headers, media_type="application/problem+json")


def _unavailable(retry_after_s: int) -> JSONResponse:
    """`503 exchange_unavailable`: no snapshot within its bound; retry once a read may start."""
    detail = "No ticker snapshot recent enough to serve; retry after the advertised delay."
    return _coded(503, "exchange_unavailable", "Exchange tickers unavailable", detail,
                  retry_after_seconds=retry_after_s)  # fmt: skip


def make_tickers_router(
    source_provider: Callable[[], TickersSource | None],
    *,
    principal_resolver: _Resolver | None = None,
) -> APIRouter:
    """`GET /market/tickers` over the shared snapshot `source_provider` returns, resolved per
    request; `None` (no venue source composed) answers 503 after RBAC, never a value."""
    router = APIRouter(tags=["market-data"])

    @router.get("/market/tickers")
    async def get_tickers(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _coded(
                501, "internal_error", "Not implemented", "Session verification is not wired."
            )
        resolved = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _coded(401, "unauthenticated", "Unauthorized", "Sign in to read market data.")
        if not principal.has(_REQUIRED_PERMISSION):
            detail = f"Reading market data requires {_REQUIRED_PERMISSION}."
            return _coded(403, "forbidden", "Forbidden", detail)
        asked = request.query_params.getlist("symbols")
        if not 1 <= len(asked) <= TICKERS_MAX or not all(_SYMBOL.fullmatch(s) for s in asked):
            detail = f"symbols must name 1 to {TICKERS_MAX} USDT linear perpetual symbols."
            return _coded(400, "validation_failed", "Invalid symbols", detail)
        source = source_provider()
        if source is None:
            return _unavailable(int(REFRESH_S))
        try:
            answer = await source.serve()
        except TickersUnavailable as exc:
            return _unavailable(exc.retry_after_s)
        tickers, items, unknown = answer.universe.tickers, [], []
        for symbol in dict.fromkeys(asked):
            event = tickers.get(symbol)
            if event is None:
                unknown.append(symbol)
            else:  # `ts` is the venue's answer time, every row's event time
                items.append(serialize_ticker(event, stale=answer.stale))
        meta = {"next_cursor": None, "has_more": False, "count": len(items)}
        return JSONResponse({"items": items, "unknown_symbols": unknown, "meta": meta})

    return router


__all__ = [
    "TICKERS_MAX",
    "TickerReader",
    "TickersSource",
    "make_ticker_router",
    "make_tickers_router",
    "serialize_ticker",
]
