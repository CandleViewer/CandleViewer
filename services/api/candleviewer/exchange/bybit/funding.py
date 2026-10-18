"""Bybit v5 settled funding history (`GET /v5/market/funding/history`, E24-T02).

All wire knowledge for the endpoint lives here (C-2.2): params, the
`fundingRate` / `fundingRateTimestamp` row shape, and strict validation. The
endpoint pages by *time window*, newest first (`endTime` walks backwards), not
by an opaque cursor; `limit` is 1-200. Public data only, no credentials.

Every row is validated before anything is returned; a malformed row is skipped and
counted (fail-closed per row; an envelope fault raises `FundingRowRejected`)
(STRIDE D1, `docs/security/threat-models/E24-derivatives.md`).
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from candleviewer.domain.funding import FundingPage, FundingRowRejected, FundingSettlement
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.rest import BybitRestClient

PATH: Final = "/v5/market/funding/history"
MAX_PAGE_LIMIT: Final = 200
#: Per-interval plausibility ceiling (3 %). Bybit caps funding at about +/-0.75 % per
#: 8 h for most linear perps (per-symbol cap/floor in instruments-info); 3 % is a
#: deliberately generous bound that still rejects spoofed/drifted magnitudes.
MAX_ABS_RATE: Final = Decimal("0.03")
#: Settlement timestamps beyond now + this skew are rejected as spoofed.
MAX_FUTURE_SKEW_MS: Final = 300_000
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,24}$")


def _parse_row(
    row: object, symbol: str, now_ms: int, prev_ts_ms: int | None
) -> tuple[Decimal, int]:
    if not isinstance(row, dict):
        raise FundingRowRejected("row is not an object", "not_object")
    if row.get("symbol") != symbol:
        raise FundingRowRejected("row symbol does not match the request", "symbol_mismatch")
    raw_rate, raw_ts = row.get("fundingRate"), row.get("fundingRateTimestamp")
    if not isinstance(raw_rate, str) or not isinstance(raw_ts, str):
        raise FundingRowRejected("rate/timestamp not strings", "type")
    try:
        rate = Decimal(raw_rate)
        ts_ms = int(raw_ts)
    except (InvalidOperation, ValueError) as exc:
        raise FundingRowRejected("unparseable rate or timestamp", "unparseable") from exc
    if not rate.is_finite() or abs(rate) > MAX_ABS_RATE:
        raise FundingRowRejected("implausible funding rate", "rate_implausible")
    if ts_ms <= 0:
        raise FundingRowRejected("non-positive settlement time", "time_nonpositive")
    if ts_ms > now_ms + MAX_FUTURE_SKEW_MS:
        raise FundingRowRejected("settlement time in the future", "time_future")
    if prev_ts_ms is not None and ts_ms >= prev_ts_ms:
        raise FundingRowRejected("page not strictly newest-first", "non_monotonic")
    return rate, ts_ms


def parse_funding_page(
    payload: dict[str, Any], *, symbol: str, now_ms: int | None = None
) -> FundingPage:
    """Validate one page. Envelope faults raise `FundingRowRejected`; a bad row is
    skipped and its reason recorded (fail-closed per row, not per page)."""
    result = payload.get("result")
    if not isinstance(result, dict):
        raise FundingRowRejected("funding history: missing result object")
    rows = result.get("list")
    if not isinstance(rows, list):
        raise FundingRowRejected("funding history: missing list")
    now = int(time.time() * 1000) if now_ms is None else now_ms
    out = FundingPage()
    prev: int | None = None
    for row in rows:
        try:
            rate, ts_ms = _parse_row(row, symbol, now, prev)
        except FundingRowRejected as exc:
            out.rejected_reasons.append(exc.reason)
            continue
        prev = ts_ms
        out.append(FundingSettlement(ts_us=ts_ms * 1000, symbol=symbol, funding_rate=rate))
    return out


async def fetch_funding_page(
    client: BybitRestClient,
    symbol: str,
    *,
    start_us: int,
    end_us: int,
    limit: int = MAX_PAGE_LIMIT,
) -> FundingPage:
    """One page (newest first) of settlements within `[start_us, end_us]`."""
    if not _SYMBOL_RE.fullmatch(symbol):
        raise FundingRowRejected("funding history: invalid symbol")
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be within 1..{MAX_PAGE_LIMIT}")
    payload = await client.get_public(
        PATH,
        params={
            "category": "linear",
            "symbol": symbol,
            "startTime": start_us // 1000,
            "endTime": end_us // 1000,
            "limit": limit,
        },
        endpoint_class=EndpointClass.MARKET_DATA,
    )
    return parse_funding_page(payload, symbol=symbol)


class BybitFundingFetcher:
    """`orderflow.funding.FundingFetcher` over the governed REST client. Uses the
    `MARKET_DATA` bucket, so a backfill can never draw down the stop/cancel/SL
    reserve of the order or position buckets (C-12.7)."""

    def __init__(self, client: BybitRestClient) -> None:
        self._client = client

    async def __call__(
        self, symbol: str, start_us: int, end_us: int, limit: int
    ) -> Sequence[FundingSettlement]:
        return await fetch_funding_page(
            self._client, symbol, start_us=start_us, end_us=end_us, limit=limit
        )


__all__ = [
    "MAX_ABS_RATE",
    "MAX_PAGE_LIMIT",
    "PATH",
    "BybitFundingFetcher",
    "FundingRowRejected",
    "fetch_funding_page",
    "parse_funding_page",
]
