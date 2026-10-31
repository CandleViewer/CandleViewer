"""`GET /market/open-interest` (`docs/plan/22-api-openapi.yaml`, E24-T01 #665).

Contract-exact: top-level `symbol`, `items` `{t, open_interest, open_interest_value, interval,
source}` ascending by `t`, and `OpenInterestPageMeta` (`Page` meta plus `coverage`). RBAC, the
problem documents and the 501/401/403 order mirror `api/funding.py` (C-12.4). Bounds,
`invalid_time_range` / `invalid_cursor` and the unlisted symbol are refused by
`OpenInterestService` BEFORE any storage query (STRIDE D12).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

# The funding router's helpers, so the two derivatives routes answer alike (one RBAC order,
# one problem shape, one time parser).
from candleviewer.api.funding import (
    _SYMBOL_RE,
    _dec,
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
from candleviewer.orderflow.open_interest import OiSeries
from candleviewer.storage.errors import StorageTierUnavailable

_REQUIRED_PERMISSION = "marketdata:read"
_ENDPOINT = "open_interest"


class OpenInterestReader(Protocol):
    async def series(
        self,
        symbol: str,
        *,
        interval: str,
        start_us: int | None,
        end_us: int | None,
        limit: int,
        cursor: str | None,
    ) -> OiSeries: ...


def serialize_series(series: OiSeries) -> dict[str, object]:
    items: list[dict[str, object]] = [
        {
            "t": _iso(p.ts_us),
            "open_interest": _dec(p.open_interest),
            "open_interest_value": (
                None if p.open_interest_value is None else _dec(p.open_interest_value)
            ),
            "interval": p.interval,
            "source": p.source,
        }
        for p in series.points
    ]
    cov = series.coverage
    return {
        "symbol": series.symbol,
        "items": items,
        "meta": {
            "next_cursor": series.next_cursor,
            "has_more": series.has_more,
            "count": len(items),
            "coverage": {
                "from": None if cov is None else _iso(cov[0]),
                "to": None if cov is None else _iso(cov[1]),
                "native_interval": series.interval,
                "source": series.source,
                "gaps": [{"from": _iso(a), "to": _iso(b)} for a, b in series.gaps],
            },
        },
    }


def _bad(code: str, detail: str) -> JSONResponse:
    deriv_range_rejected_total.labels(endpoint=_ENDPOINT).inc()
    return _problem(400, code, "Bad request", detail)


def make_open_interest_router(
    reader_provider: Callable[[], OpenInterestReader | None],
    *,
    principal_resolver: _Resolver | None = None,
) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.get("/market/open-interest")
    async def get_open_interest(
        request: Request,
        symbol: str,
        interval: str = Query(default="5min"),
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
            return _bad("validation_failed", "invalid symbol")
        reader = reader_provider()
        if reader is None:
            return _problem(
                503, "service_unavailable", "Service unavailable", "open interest not wired"
            )
        try:
            series = await reader.series(
                symbol,
                interval=interval,
                start_us=_parse_time(from_),
                end_us=_parse_time(to),
                limit=limit,
                cursor=cursor,
            )
        except ValueError:  # malformed from/to timestamp
            return _bad("invalid_time_range", "invalid from/to timestamp")
        except DerivInvalidRequest as exc:
            return _bad(exc.code, exc.detail)
        except DerivSymbolUnlisted:
            return _problem(422, "validation_failed", "Unprocessable", f"{symbol} is not listed")
        except StorageTierUnavailable:
            return _problem(
                503, "service_unavailable", "Service unavailable", "hot tier unavailable"
            )
        return JSONResponse(status_code=200, content=serialize_series(series))

    return router


__all__ = ["OpenInterestReader", "make_open_interest_router", "serialize_series"]
