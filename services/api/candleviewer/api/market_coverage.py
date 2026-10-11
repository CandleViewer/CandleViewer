"""`GET /market/data-coverage` (E16-T04; 22-api `getDataCoverage`, schema `DataCoverage`).

RBAC server-side (`marketdata:read`, C-12.4): no resolver wired -> 501, no session -> 401,
missing permission -> 403. The contract has no window parameters, so the report spans the
symbol's whole recorded history up to now. Gaps carry the contract's closed `reason` enum
(`recorder.coverage.GAP_REASON`); backfilled (kline) gaps stay listed — bars-derived data
never makes a tick window covered. `rows` is omitted (optional; needs QuestDB partition
metadata, not wired).
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Annotated, Any, Final, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.market_response import iso_us, problem
from candleviewer.observability.metrics import Counter
from candleviewer.recorder.coverage import GAP_REASON, CoverageService
from candleviewer.recorder.sessions import DEFAULT_STREAMS

#: Bounded label set for the unmapped-cause counter.
_CAUSE_LABEL: Final = {"seq_jump": "seq_jump", "backpressure_drop": "backpressure_drop"}
coverage_gap_reason_unmapped_total = Counter(
    "coverage_gap_reason_unmapped_total",
    "Coverage gaps served without a contract reason (cause has no enum value yet, #2216).",
    ["cause"],
)
_REQUIRED_PERMISSION: Final = "marketdata:read"
_SYMBOL: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
_STREAMS: Final = frozenset(
    {
        "trades",
        "orderbook_delta",
        "orderbook_snapshot",
        "tickers",
        "klines",
        "liquidations",
        "open_interest",
        "funding",
    }
)


class _Resolver(Protocol):
    """Structural, like `market_bars._Resolver` (the composition root injects the real one)."""

    def resolve(self, request: Request) -> Any: ...


def _z(us: int) -> str:
    return iso_us(us).replace("+00:00", "Z")


def _gap(lo: int, hi: int, cause: str) -> dict[str, str]:
    """A gap with its contract `reason`, or with `reason` OMITTED (optional in `DataCoverage`)
    when the DB cause has no honest contract value — never relabelled as another cause.
    TODO(#2216): drop the omission once the enum carries the recorder-loss slugs."""
    out = {"from": _z(lo), "to": _z(hi)}
    reason = GAP_REASON.get(cause)
    if reason is None:
        coverage_gap_reason_unmapped_total.labels(cause=_CAUSE_LABEL.get(cause, "other")).inc()
    else:
        out["reason"] = reason
    return out


def make_data_coverage_router(
    service_provider: Callable[[], CoverageService | None],
    *,
    principal_resolver: _Resolver | None = None,
    symbol_listed: Callable[[str], bool] | None = None,
) -> APIRouter:
    """Bind `GET /market/data-coverage`. `symbol_listed` is the instrument-catalogue check the
    bars route uses; an unknown symbol is 422 `validation_failed`, `None` fails closed (503)."""
    router = APIRouter(tags=["market-data"])

    @router.get("/market/data-coverage")
    async def get_data_coverage(
        request: Request,
        symbol: str,
        stream: Annotated[list[str] | None, Query()] = None,
    ) -> Response:
        if principal_resolver is None:
            return problem(501, "internal_error", "Not implemented",
                           "Session verification is not wired yet.")  # fmt: skip
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return problem(401, "unauthenticated", "Unauthorized", "Sign in to read market data.")
        if not principal.has(_REQUIRED_PERMISSION):
            return problem(403, "forbidden", "Forbidden",
                           f"Reading market data requires {_REQUIRED_PERMISSION}.")  # fmt: skip
        if not _SYMBOL.fullmatch(symbol):
            return problem(400, "validation_failed", "Bad request", "Invalid symbol.")
        streams = list(dict.fromkeys(stream or DEFAULT_STREAMS))
        if any(s not in _STREAMS for s in streams):
            return problem(400, "validation_failed", "Bad request", "Unknown stream kind.")
        if symbol_listed is None:
            return problem(503, "store_unavailable", "Service unavailable",
                           "The instrument catalogue is not ready yet.")  # fmt: skip
        if not symbol_listed(symbol):
            return problem(422, "validation_failed", "Unprocessable entity",
                           "This symbol is not a listed instrument.")  # fmt: skip
        service = service_provider()
        if service is None:
            return problem(503, "store_unavailable", "Service unavailable",
                           "Recording metadata is not available yet; retry shortly.")  # fmt: skip
        try:
            # Server-side window cap: the last CACHE_DAYS (90 d, = the klines hot fallback),
            # served from the per-symbol cache; never a full-history scan per call.
            # TODO(#2216): proper `from`/`to` query params once the contract declares them.
            _lo, now, report = await service.coverage_recent(symbol, streams)
        except (TimeoutError, OSError):
            return problem(503, "store_unavailable", "Service unavailable",
                           "Recording metadata is not available yet; retry shortly.")  # fmt: skip
        body = {
            "symbol": symbol,
            "streams": [
                {
                    "stream": sc.stream,
                    "intervals": [
                        {"from": _z(i.lo), "to": _z(i.hi), "tier": i.tier} for i in sc.intervals
                    ],
                    "gaps": [_gap(g.lo, g.hi, g.cause) for g in sc.gaps],
                }
                for sc in report
            ],
            "generated_at": _z(now),
        }
        return JSONResponse(body)

    return router
