"""`GET /market/liquidations` (`docs/plan/22-api-openapi.yaml`, E24-T03 #667).

Contract-exact: `items` `{ts, symbol, side, price, size, notional_usd, cluster_size}` ascending by
`ts`, and `LiquidationsPageMeta` (`Page` meta plus `coverage`). Reads only the local table: the
venue has no liquidation history. RBAC, the problem documents and the 501/401/403 order mirror
`api/funding.py` (C-12.4). Bounds, `cluster_window_ms` over 60000, `invalid_cursor` and the
unlisted symbol are refused by `LiquidationService` BEFORE any storage query (STRIDE D).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.api.funding import (
    _SYMBOL_RE,
    _iso,
    _parse_time,
    _Principal,
    _problem,
    _Resolver,
)
from candleviewer.orderflow.deriv_limits import (
    DEFAULT_LIMIT,
    DerivInvalidRequest,
    DerivSymbolUnlisted,
)
from candleviewer.orderflow.funding_metrics import deriv_range_rejected_total
from candleviewer.orderflow.liquidations import LiquidationPage
from candleviewer.storage.errors import StorageTierUnavailable

_REQUIRED_PERMISSION = "marketdata:read"
_ENDPOINT = "liquidations"
_MAX_DECIMAL_CHARS = 32


class LiquidationReader(Protocol):
    async def page(
        self,
        symbol: str,
        *,
        start_us: int | None,
        end_us: int | None,
        limit: int,
        cursor: str | None,
        side: str | None,
        min_notional: Decimal | None,
        cluster_window_ms: int,
    ) -> LiquidationPage: ...


def _opt_iso(us: int | None) -> str | None:
    return None if us is None else _iso(us)


def serialize_page(page: LiquidationPage) -> dict[str, object]:
    items: list[dict[str, object]] = []
    for item in page.items:
        wire = item.wire()
        wire["ts"] = _iso(item.first.ts_us)
        del wire["ts_ms"]
        items.append(wire)
    cov = page.coverage
    return {
        "items": items,
        "meta": {
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
            "count": len(items),
            "coverage": {
                "first_available_ts": _opt_iso(cov.first_available_us),
                "covered_from": _opt_iso(cov.covered_from_us),
                "covered_to": _opt_iso(cov.covered_to_us),
                "no_coverage": cov.no_coverage,
            },
        },
    }


def _bad(code: str, detail: str) -> JSONResponse:
    deriv_range_rejected_total.labels(endpoint=_ENDPOINT).inc()
    return _problem(400, code, "Bad request", detail)


def _decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    if len(text) > _MAX_DECIMAL_CHARS:
        raise InvalidOperation("too long")
    return Decimal(text)


def make_liquidations_router(
    reader_provider: Callable[[], LiquidationReader | None],
    *,
    principal_resolver: _Resolver | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.get("/market/liquidations")
    async def get_liquidations(
        request: Request,
        symbol: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        cursor: str | None = Query(default=None),
        limit: str = Query(default=str(DEFAULT_LIMIT)),
        side: str | None = Query(default=None),
        min_notional_usd: str | None = Query(default=None),
        cluster_window_ms: str = Query(default="0"),
    ) -> JSONResponse:
        if principal_resolver is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver wired"
            )
        resolved = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _problem(401, "unauthenticated", "Unauthorized", "no verified session")
        if not principal.has(_REQUIRED_PERMISSION):
            return _problem(403, "forbidden", "Forbidden", f"requires {_REQUIRED_PERMISSION}")
        if not _SYMBOL_RE.fullmatch(symbol):
            return _bad("validation_failed", "invalid symbol")
        try:
            n, window = int(limit), int(cluster_window_ms)
            floor = _decimal(min_notional_usd)
        except (ValueError, InvalidOperation):
            return _bad("validation_failed", "limit, cluster_window_ms or min_notional_usd")
        reader = reader_provider()
        if reader is None:
            return _problem(
                503, "service_unavailable", "Service unavailable", "liquidations not wired"
            )
        try:
            page = await reader.page(
                symbol,
                start_us=_parse_time(from_),
                end_us=_parse_time(to),
                limit=n,
                cursor=cursor,
                side=side,
                min_notional=floor,
                cluster_window_ms=window,
            )
        except ValueError:  # malformed from/to timestamp
            return _bad("invalid_time_range", "invalid from/to timestamp")
        except DerivInvalidRequest as exc:
            return _bad(exc.code, exc.detail)
        except ArithmeticError:  # backstop: decimal faults only a crafted cursor can reach
            return _bad("invalid_cursor", "pagination cursor is malformed or expired")
        except DerivSymbolUnlisted:
            return _problem(422, "validation_failed", "Unprocessable", f"{symbol} is not listed")
        except StorageTierUnavailable:
            return _problem(
                503, "service_unavailable", "Service unavailable", "hot tier unavailable"
            )
        return JSONResponse(status_code=200, content=serialize_page(page))

    return router


__all__ = ["LiquidationReader", "make_liquidations_router", "serialize_page"]
