"""Bybit v5 open-interest history (`GET /v5/market/open-interest`, E24-T01 #665).

All wire knowledge for the endpoint lives here (C-2.2): `intervalTime` (5min..1d), `limit`
1-200, millisecond `startTime`/`endTime` bounds and the opaque `nextPageCursor`. Rows are
`{openInterest, singleOpenInterest?, timestamp}` strings, newest first (docs page
`market/open-interest`). `openInterest` is base coin for a linear symbol; the history carries no
USD value. Public data only, no credentials; the `MARKET_DATA` bucket, so a backfill never draws
on the stop/cancel/SL reserve (C-12.7).

Strict: each row is a pydantic model with `extra="forbid"`; a bad row is skipped and its reason
recorded, an envelope fault raises `OiRowRejected` (STRIDE D1).
"""

from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from candleviewer.domain.open_interest import (
    REST_INTERVALS,
    SOURCE_REST,
    OiFetchFailed,
    OiPage,
    OiPoint,
    OiRowRejected,
)
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.rest import BybitRestClient

PATH: Final = "/v5/market/open-interest"
MAX_PAGE_LIMIT: Final = 200
MAX_FUTURE_SKEW_MS: Final = 300_000
#: The venue's cursor is short (`lastid=..&lasttime=..`, URL-encoded); anything longer is refused.
MAX_CURSOR_LEN: Final = 256
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,24}$")
_HTTP_RE: Final = re.compile(r"HTTP (\d{3})")


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    openInterest: str
    singleOpenInterest: str | None = None
    timestamp: str


def _point(row: object, symbol: str, interval: str, now_ms: int, prev: int | None) -> OiPoint:
    try:
        parsed = _Row.model_validate(row)
    except ValidationError as exc:
        raise OiRowRejected("row failed strict validation", "schema") from exc
    try:
        oi, ts_ms = Decimal(parsed.openInterest), int(parsed.timestamp)
    except (InvalidOperation, ValueError) as exc:
        raise OiRowRejected("unparseable value or timestamp", "unparseable") from exc
    if not oi.is_finite() or oi < 0:
        raise OiRowRejected("implausible open interest", "value_implausible")
    if ts_ms <= 0 or ts_ms > now_ms + MAX_FUTURE_SKEW_MS:
        raise OiRowRejected("timestamp out of range", "time_range")
    if prev is not None and ts_ms >= prev:
        raise OiRowRejected("page not strictly newest-first", "non_monotonic")
    return OiPoint(ts_ms * 1000, symbol, oi, None, interval, SOURCE_REST)


def parse_oi_page(
    payload: dict[str, Any], *, symbol: str, interval: str, now_ms: int | None = None
) -> OiPage:
    """Validate one page. Envelope faults raise `OiRowRejected`; a bad row is skipped and its
    reason recorded (fail-closed per row, not per page)."""
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(rows := result.get("list"), list):
        raise OiRowRejected("open interest: missing result list")
    if result.get("symbol") != symbol or result.get("category") != "linear":
        raise OiRowRejected("open interest: page is for another symbol or category", "symbol")
    cursor = result.get("nextPageCursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > MAX_CURSOR_LEN):
        raise OiRowRejected("open interest: malformed cursor", "cursor")
    now = int(time.time() * 1000) if now_ms is None else now_ms
    page = OiPage(next_cursor=cursor or None)
    prev: int | None = None
    for row in rows:
        try:
            point = _point(row, symbol, interval, now, prev)
        except OiRowRejected as exc:
            page.rejected_reasons.append(exc.reason)
            continue
        prev = point.ts_us // 1000
        page.append(point)
    return page


def _failed(exc: ExchangeError) -> OiFetchFailed:
    match = _HTTP_RE.search(str(exc))
    status = int(match.group(1)) if match else (200 if exc.exchange_ret_code is not None else None)
    return OiFetchFailed(
        type(exc).__name__,
        retryable=exc.retryable,
        http_status=status,
        ret_code=exc.exchange_ret_code,
    )


class BybitOpenInterestFetcher:
    """`orderflow.open_interest.OiFetcher` over the governed public REST client."""

    def __init__(self, client: BybitRestClient) -> None:
        self._client = client

    async def __call__(
        self, symbol: str, interval: str, start_us: int, end_us: int, cursor: str | None
    ) -> OiPage:
        if not _SYMBOL_RE.fullmatch(symbol) or interval not in REST_INTERVALS:
            raise OiRowRejected("open interest: invalid symbol or interval", "request")
        params: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": interval,
            "startTime": start_us // 1000,
            "endTime": end_us // 1000,
            "limit": MAX_PAGE_LIMIT,
        }
        if cursor:
            params["cursor"] = cursor
        try:
            payload = await self._client.get_public(
                PATH, params=params, endpoint_class=EndpointClass.MARKET_DATA
            )
        except ExchangeError as exc:
            raise _failed(exc) from exc
        return parse_oi_page(payload, symbol=symbol, interval=interval)


__all__ = ["MAX_PAGE_LIMIT", "PATH", "BybitOpenInterestFetcher", "parse_oi_page"]
