"""`GET /market/heatmap` (`22-api-openapi.yaml` `getHeatmap`, E21-T03 #606).

Serves recorded DOM history through `orderflow.heatmap_history.read_heatmap_history` over the
composed `HeatmapHistoryReader` (`heatmap_wiring.StoredHeatmapReader`: QuestDB and the Parquet
cold tier, paged reads, C-2.18). Order of refusal, each before any storage read:

1. RBAC `marketdata:read` (501 no resolver / 401 / 403; C-12.4, scope none, so no IDOR case).
2. Parameters (422 `validation_failed`): the symbol pattern, the `time_bucket_ms`, `depth` and
   `normalize` enums, `price_grouping` 1..1000, RFC 3339 `from` (required) and `to` (default
   now), `from` before `to`. A cursor not issued for exactly this request is 422
   `invalid_cursor`.
3. A symbol not listed in the instrument catalogue (or with no tick size) is 422, so no read is
   ever made for it; no reader composed is 503.
4. At most `MAX_PER_USER` reads per user at once; another is 429 `rate_limited` with
   `Retry-After`.

The read runs under `READ_TIMEOUT_S`; between storage reads it checks the client is still
connected and stops when it is gone, releasing its slot. A storage failure, a deadline or a
page past the read bounds (`HeatmapReadLimit`) is 503. The cursor names the older remainder's
end and is bound to `(heatmap, symbol, from:bucket:grouping:depth:normalize)`
(`api.market_response`), so the next page repeats the request with it.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.market_response import (
    InvalidCursor,
    cursor_scope,
    decode_cursor,
    encode_cursor,
    iso_us,
    problem,
)
from candleviewer.orderflow import heatmap_metrics as metrics
from candleviewer.orderflow.heatmap_history import (
    BUCKETS,
    DEPTHS,
    MAX_GROUPING,
    HeatmapHistory,
    HeatmapHistoryReader,
    HeatmapQuery,
    HeatmapReadLimit,
    Normalize,
    read_heatmap_history,
)
from candleviewer.storage.errors import StorageError

_REQUIRED_PERMISSION: Final = "marketdata:read"
_SYMBOL: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
_NORMALIZE: Final[tuple[Normalize, ...]] = ("none", "column", "window")
#: 22 `getHeatmap`: at most 2 backfills per user at once.
MAX_PER_USER: Final = 2
RETRY_AFTER_S: Final = 1
#: One page's whole read and build (budgets #1 and #14 bound the common case far below it).
READ_TIMEOUT_S: Final = 30.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Principal(Protocol):
    @property
    def user_id(self) -> object: ...

    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    def resolve(self, request: Request) -> Any: ...


class _ClientGone(Exception):
    """The client disconnected; the read stops at its next checkpoint."""


def _invalid(detail: str) -> JSONResponse:
    return problem(422, "validation_failed", "Unprocessable entity", detail)


def _ts_us(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000)


def _z(us: int) -> str:
    return iso_us(us).replace("+00:00", "Z")


def serialize_heatmap(page: HeatmapHistory, next_cursor: str | None) -> dict[str, object]:
    """`HeatmapResponse` (22): axes, matrices and the recorded-history fields."""
    q = page.query
    return {
        "symbol": q.symbol,
        "from": _z(page.from_us),
        "to": _z(page.to_us),
        "time_bucket_ms": q.time_bucket_ms,
        "price_grouping": q.price_grouping,
        "times": [_z(t) for t in page.times_us],
        "prices": [format(p, "f") for p in page.prices],
        "bid_matrix": page.bid_matrix,
        "ask_matrix": page.ask_matrix,
        "max_value": page.max_value,
        "normalize": q.normalize,
        "estimated": page.estimated,
        "first_available": None if page.first_available_us is None else _z(page.first_available_us),
        "history": page.history,
        "samples": list(page.samples),
        "estimated_columns": list(page.estimated_columns),
        "effective_time_bucket_ms": page.effective_bucket_ms,
        "segments": [
            {
                "from": _z(s.lo_us),
                "to": _z(s.hi_us),
                "source": s.source,
                "effective_resolution_ms": s.resolution_ms,
            }
            for s in page.segments
        ],
        "clamped": page.clamped,
        "next_cursor": next_cursor,
    }


def _record(page: HeatmapHistory, started: float) -> None:
    if not page.sources:
        metrics.BACKFILLS["none"].inc()
    for source in page.sources:
        metrics.BACKFILLS[source].inc()
    metrics.heatmap_backfill_duration_ms.observe((time.perf_counter() - started) * 1000)
    if page.clamped:
        metrics.heatmap_backfill_clamped_total.inc()
    if page.unverified_anchors:
        metrics.heatmap_reconstruct_unverified_total.inc(page.unverified_anchors)


def make_market_heatmap_router(
    reader_provider: Callable[[], HeatmapHistoryReader | None],
    *,
    principal_resolver: _Resolver | None = None,
    symbol_listed: Callable[[str], bool] | None = None,
    tick_size: Callable[[str], Decimal | None] | None = None,
    now_us: Callable[[], int],
) -> APIRouter:
    """Bind `GET /market/heatmap`. `reader_provider()` is resolved per request; `None` -> 503.
    `symbol_listed=None` or `tick_size=None` fails closed (503), never open."""
    router = APIRouter(tags=["market-data"])
    running: dict[object, int] = {}  # user -> reads in flight; an entry exists only while > 0

    @router.get("/market/heatmap")
    async def get_heatmap(
        request: Request,
        symbol: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None),
        cursor: str | None = Query(default=None),  # length enforced by decode_cursor
        time_bucket_ms: int = Query(default=1000),
        price_grouping: int = Query(default=1),
        depth: int = Query(default=200),
        normalize: str = Query(default="window"),
    ) -> Response:
        if principal_resolver is None:
            return problem(501, "internal_error", "Not implemented",
                           "Session verification is not wired yet.")  # fmt: skip
        got = principal_resolver.resolve(request)
        principal: _Principal | None = await got if inspect.isawaitable(got) else got
        if principal is None:
            return problem(401, "unauthenticated", "Unauthorized", "Sign in to read market data.")
        if not principal.has(_REQUIRED_PERMISSION):
            detail = f"Reading market data requires {_REQUIRED_PERMISSION}."
            return problem(403, "forbidden", "Forbidden", detail)
        if not _SYMBOL.fullmatch(symbol):
            return _invalid("symbol must be a USDT linear perpetual code.")
        if time_bucket_ms not in BUCKETS or depth not in DEPTHS:
            return _invalid("time_bucket_ms or depth is not one of the listed values.")
        if not 1 <= price_grouping <= MAX_GROUPING or normalize not in _NORMALIZE:
            return _invalid("price_grouping must be 1..1000 and normalize none, column or window.")
        if from_ is None:
            return _invalid("'from' is required.")
        try:
            start_us = _ts_us(from_)
            end_us = now_us() if to is None else _ts_us(to)
        except (ValueError, OverflowError):
            return _invalid("from/to must be RFC 3339 timestamps.")
        if start_us >= end_us:
            return _invalid("'from' must be before 'to'.")
        mode = next(m for m in _NORMALIZE if m == normalize)
        series = f"{start_us}:{time_bucket_ms}:{price_grouping}:{depth}:{mode}"
        scope = cursor_scope("heatmap", symbol, series)
        if cursor is not None:
            try:
                end_us = decode_cursor(cursor, scope=scope, end_us=end_us, start_us=start_us + 1)
            except InvalidCursor:
                detail = "The cursor is not valid for this request; restart without it."
                return problem(422, "invalid_cursor", "Invalid cursor", detail)
        if symbol_listed is None or tick_size is None or (reader := reader_provider()) is None:
            return problem(503, "store_unavailable", "Service unavailable",
                           "Recorded heatmap storage is not ready yet.")  # fmt: skip
        tick = tick_size(symbol) if symbol_listed(symbol) else None
        if tick is None:
            return _invalid("This symbol is not a listed instrument.")
        user = principal.user_id
        if running.get(user, 0) >= MAX_PER_USER:
            busy = f"At most {MAX_PER_USER} heatmap reads run at once; retry shortly."
            refused = problem(429, "rate_limited", "Too many requests", busy)
            refused.headers["Retry-After"] = str(RETRY_AFTER_S)
            return refused
        running[user] = running.get(user, 0) + 1

        async def checkpoint() -> None:
            if await request.is_disconnected():
                raise _ClientGone

        query = HeatmapQuery(symbol, start_us, end_us, time_bucket_ms, price_grouping, depth,
                             mode, tick)  # fmt: skip
        started = time.perf_counter()
        try:
            async with asyncio.timeout(READ_TIMEOUT_S):
                page = await read_heatmap_history(
                    reader, query, now_us=now_us(), checkpoint=checkpoint
                )
        except _ClientGone:
            _log().info("market_heatmap_client_gone", symbol=symbol)
            return Response(status_code=499)
        except (TimeoutError, OSError, StorageError, HeatmapReadLimit) as exc:
            _log().warning("market_heatmap_read_failed", symbol=symbol, error=type(exc).__name__)
            detail = "Recorded heatmap storage did not answer; retry or narrow from/to."
            return problem(503, "store_unavailable", "Service unavailable", detail)
        finally:
            left = running[user] - 1
            if left:
                running[user] = left
            else:
                del running[user]
        _record(page, started)
        next_cursor = None if page.remainder is None else encode_cursor(scope, page.remainder[1])
        _log().info("market_heatmap_served", symbol=symbol, columns=len(page.times_us),
                    rows=len(page.prices), sources=sorted(page.sources))  # fmt: skip
        return JSONResponse(status_code=200, content=serialize_heatmap(page, next_cursor))

    return router


__all__ = ["MAX_PER_USER", "make_market_heatmap_router", "serialize_heatmap"]
