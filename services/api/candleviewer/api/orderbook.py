"""`GET /market/orderbook` (`docs/plan/22-api-openapi.yaml` `getOrderbookSnapshot`, E08-S05).

Serves the backend-maintained book, but **only while it is LIVE**: during a
resync (or before the first snapshot) the answer is `503` with a text reason,
never a patched book (R7). A LIVE book that has applied no frame within the
watchdog's book limit is served with `stale: true` (`BookStream.is_stale`,
#3807). A request for a listed symbol (re)acquires its `orderbook` demand with
a grace period so the book warms lazily. RBAC (C-12.4) mirrors `api/ticker.py`:
fail-closed 501/401/403.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.api.problems import problem
from candleviewer.api.ticker import _iso, _Principal, _Resolver
from candleviewer.exchange.base.models import BookLevel, BookSnapshot
from candleviewer.ws._generated.error_codes import ErrorCode

_REQUIRED_PERMISSION = "marketdata:read"
DEMAND_CONSUMER = "rest-orderbook"


class _View(Protocol):
    @property
    def snapshot(self) -> BookSnapshot: ...
    @property
    def stale(self) -> bool: ...


class BookReader(Protocol):
    def view(self, symbol: str, depth: int) -> _View | None: ...
    def is_listed(self, symbol: str) -> bool: ...
    def acquire(self, consumer: str, symbol: str) -> None: ...
    def release(self, consumer: str, symbol: str) -> None: ...


def _rows(levels: tuple[BookLevel, ...]) -> list[list[str]]:
    return [[format(lv.price, "f"), format(lv.qty, "f")] for lv in levels]


def serialize_orderbook(snap: BookSnapshot, *, stale: bool) -> dict[str, object]:
    return {
        "symbol": snap.symbol,
        "depth": snap.depth,
        "u": snap.update_id,
        "seq": snap.cross_seq,
        "ts": _iso(snap.ts_event),
        "bids": _rows(snap.bids),
        "asks": _rows(snap.asks),
        "stale": stale,
    }


def make_orderbook_router(
    reader_provider: Callable[[], BookReader | None],
    *,
    principal_resolver: _Resolver | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.get("/market/orderbook")
    async def get_orderbook(
        request: Request,
        symbol: str,
        depth: int = Query(default=50),
    ) -> JSONResponse:
        if principal_resolver is None:
            return problem(ErrorCode.NOT_IMPLEMENTED, 501, "no principal resolver wired")
        resolved: Any = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return problem(ErrorCode.UNAUTHENTICATED, 401, "no verified session for this request")
        if not principal.has(_REQUIRED_PERMISSION):
            return problem(ErrorCode.FORBIDDEN, 403, f"requires {_REQUIRED_PERMISSION}")
        if depth not in (1, 50, 200, 500):
            return problem(ErrorCode.VALIDATION_FAILED, 422, "depth must be one of 1, 50, 200, 500")
        if not (4 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum()):
            return problem(ErrorCode.VALIDATION_FAILED, 400, "invalid symbol")
        symbol = symbol.upper()
        reader = reader_provider()
        if reader is None:
            return problem(ErrorCode.DEGRADED_DATA, 503, "order book not running")
        if not reader.is_listed(symbol):
            return problem(ErrorCode.NOT_FOUND, 404, f"unknown instrument {symbol}")
        reader.acquire(DEMAND_CONSUMER, symbol)
        reader.release(DEMAND_CONSUMER, symbol)  # grace period keeps the topic warm
        view = reader.view(symbol, depth)
        if view is None:
            return problem(
                ErrorCode.DEGRADED_DATA, 503, f"order book for {symbol} is resynchronising"
            )
        return JSONResponse(
            status_code=200, content=serialize_orderbook(view.snapshot, stale=view.stale)
        )

    return router


__all__ = ["BookReader", "make_orderbook_router", "serialize_orderbook"]
