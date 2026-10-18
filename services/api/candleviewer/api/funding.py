"""`GET /market/funding` (`docs/plan/22-api-openapi.yaml`, E24-T02).

Contract-exact: top-level `symbol`, `funding_interval_minutes`, `items`
`{t, funding_rate, predicted, estimated}` and `Page` `meta`. `predicted` and
`estimated` are always present (never optional decoration) so a client cannot
mistake the unsettled rate for a settlement (STRIDE T). RBAC mirrors
`api/ticker.py`: no resolver -> 501, no session -> 401, no `marketdata:read` ->
403 (C-12.4). Errors are RFC 9457 problem documents carrying the registry `code`.

Range/limit caps and `invalid_time_range` / `invalid_cursor` are validated by
`FundingService` BEFORE any storage query (STRIDE D12).
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.orderflow.funding import (
    DEFAULT_LIMIT,
    FundingInvalidRequest,
    FundingSeries,
    FundingSymbolUnknown,
)
from candleviewer.orderflow.funding_metrics import deriv_range_rejected_total
from candleviewer.storage.errors import StorageTierUnavailable

_REQUIRED_PERMISSION = "marketdata:read"
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,24}$")


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    def resolve(self, request: Request) -> Any: ...


class FundingSeriesReader(Protocol):
    async def series(
        self,
        symbol: str,
        *,
        start_us: int | None,
        end_us: int | None,
        limit: int,
        cursor: str | None,
    ) -> FundingSeries: ...


def _problem(status: int, code: str, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
        },
    )


def _iso(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, tz=UTC).isoformat().replace("+00:00", "Z")


def _dec(value: Decimal) -> str:
    return format(value, "f")


def _parse_time(value: str | None) -> int | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000)


def serialize_series(series: FundingSeries) -> dict[str, object]:
    items: list[dict[str, object]] = [
        {
            "t": _iso(row.ts_us),
            "funding_rate": _dec(row.funding_rate),
            "predicted": False,
            "estimated": False,
        }
        for row in series.settled
    ]
    if series.predicted is not None:
        items.append(
            {
                "t": _iso(series.predicted.ts_us),
                "funding_rate": _dec(series.predicted.funding_rate),
                "predicted": True,
                "estimated": True,
            }
        )
    return {
        "symbol": series.symbol,
        "funding_interval_minutes": series.funding_interval_minutes,
        "items": items,
        "meta": {
            "next_cursor": series.next_cursor,
            "has_more": series.has_more,
            "count": len(items),
        },
    }


def make_funding_router(
    reader_provider: Callable[[], FundingSeriesReader | None],
    *,
    principal_resolver: _Resolver | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.get("/market/funding")
    async def get_funding(
        request: Request,
        symbol: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=DEFAULT_LIMIT),
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
            deriv_range_rejected_total.labels(endpoint="funding").inc()
            return _problem(400, "validation_failed", "Bad request", "invalid symbol")
        reader = reader_provider()
        if reader is None:
            return _problem(503, "service_unavailable", "Service unavailable", "funding not wired")
        try:
            series = await reader.series(
                symbol,
                start_us=_parse_time(from_),
                end_us=_parse_time(to),
                limit=limit,
                cursor=cursor,
            )
        except ValueError:  # malformed from/to timestamp
            deriv_range_rejected_total.labels(endpoint="funding").inc()
            return _problem(400, "invalid_time_range", "Bad request", "invalid from/to timestamp")
        except FundingInvalidRequest as exc:
            deriv_range_rejected_total.labels(endpoint="funding").inc()
            return _problem(400, exc.code, "Bad request", exc.detail)
        except StorageTierUnavailable:
            return _problem(
                503, "service_unavailable", "Service unavailable", "hot tier unavailable"
            )
        except FundingSymbolUnknown:
            return _problem(404, "not_found", "Not found", f"unknown instrument {symbol}")
        return JSONResponse(status_code=200, content=serialize_series(series))

    return router


__all__ = ["FundingSeriesReader", "make_funding_router", "serialize_series"]
