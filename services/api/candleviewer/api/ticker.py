"""`GET /instruments/{symbol}/ticker` (`docs/plan/22-api-openapi.yaml`, E08-S03).

Serves the *merged* last-known ticker (always fully populated, never a raw
delta). RBAC (C-12.4) mirrors `api/instruments.py`: fail-closed 501/401/403.
`404` for an unknown symbol; `503` when the symbol is listed but no complete
ticker exists yet (warming) or the stream is not wired. `stale` is true while
the topic is marked stale or reconnecting so clients grey the cells.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.exchange.base.models import TickerEvent

_REQUIRED_PERMISSION = "marketdata:read"


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    """Sync or async resolver (`resolve(request)` may return an awaitable)."""

    def resolve(self, request: Request) -> Any: ...


class TickerReader(Protocol):
    def latest(self, symbol: str) -> TickerEvent | None: ...
    def phase(self, symbol: str) -> str | None: ...
    def is_listed(self, symbol: str) -> bool: ...


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
    """The REST `Ticker`: a field the merged state lacks is left out, never `null` (E08-T08)."""
    body: dict[str, object] = {
        "symbol": event.symbol,
        "last_price": _dec(event.last_price),
        "mark_price": _dec(event.mark_price),
        "index_price": _dec(event.index_price),
        "bid1_price": _dec(event.bid1_price),
        "bid1_size": _dec(event.bid1_qty),
        "ask1_price": _dec(event.ask1_price),
        "ask1_size": _dec(event.ask1_qty),
        "price_change_pct_24h": _dec(event.price_24h_pcnt),
        "high_24h": _dec(event.high_24h),
        "low_24h": _dec(event.low_24h),
        "volume_24h": _dec(event.volume_24h),
        "turnover_24h": _dec(event.turnover_24h),
        "open_interest": _dec(event.open_interest),
        "open_interest_value": _dec(event.open_interest_value),
        "funding_rate": _dec(event.funding_rate),
        "next_funding_time": _iso(event.next_funding_time),
        "ts": _iso(event.ts_event),
        "stale": stale,
    }
    return {key: value for key, value in body.items() if value is not None}


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


__all__ = ["TickerReader", "make_ticker_router", "serialize_ticker"]
