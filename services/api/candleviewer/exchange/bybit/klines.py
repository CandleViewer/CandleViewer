"""Bybit v5 kline history (`GET /v5/market/kline`, E12-S05).

All wire knowledge for the endpoint lives here (C-2.2): params, the list-of-lists row
`[startTime, open, high, low, close, volume, turnover]` delivered **newest first**, and the
strict page validation the E12 STRIDE model asks for (SR-E12-09, BR-02):

- open times on the absolute interval grid (UTC epoch; weeks from Monday), strictly
  descending on the wire and **contiguous** (exactly one interval apart — a missing bar
  rejects the page);
- at most `limit` (<= 1000) rows, checked before any row is parsed;
- `retCode == 0` and `result.symbol` present and equal to the requested symbol;
- `high >= max(open, close)`, `low <= min(open, close)`, prices `> 0`, volume/turnover `>= 0`;
- every price a multiple of the instrument tick size (when the catalogue supplies one).

A single bad row rejects the **whole page** (`KlinePageRejected`); the caller keeps every page
it already persisted. Public data only: this module never touches credentials, and fetches go
through the governed client's `MARKET_DATA` bucket so a backfill cannot draw down the
stop/cancel/SL reserve of the order or position buckets (C-12.7, BR-33).

REST klines carry no `confirm` flag; a row is `confirmed` only once its interval has ended
before `now` (the newest row of a page reaching the present is the still-forming bar).
"""

from __future__ import annotations

import itertools
import re
import time
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final, cast, get_args
from uuid import uuid4

from candleviewer.domain.klines import KlinePageRejected
from candleviewer.domain.primitives import EventId, Symbol, TsUs
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.rest import BybitRestClient

PATH: Final = "/v5/market/kline"
MAX_PAGE_LIMIT: Final = 1000
_MIN_MS: Final = 60_000
#: Interval code -> width in ms. `M` (calendar month) has no fixed width and is not backfilled.
INTERVAL_MS: Final[dict[str, int]] = {
    **{c: int(c) * _MIN_MS for c in ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720")},
    "D": 1440 * _MIN_MS,
    "W": 7 * 1440 * _MIN_MS,
}
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,24}$")
_KLINE_INTERVALS: Final = frozenset(get_args(KlineEvent.model_fields["interval"].annotation))

TickSizeFor = Callable[[str], Decimal | None]


#: Bybit weeks open on Monday 00:00 UTC; the Unix epoch was a Thursday.
_WEEK_OFFSET_MS: Final = 4 * 1440 * _MIN_MS


def _aligned(start_ms: int, interval: str) -> bool:
    """Absolute grid: open time is a multiple of the interval (UTC epoch; `W` from Monday)."""
    offset = _WEEK_OFFSET_MS if interval == "W" else 0
    return (start_ms - offset) % INTERVAL_MS[interval] == 0


#: |adjusted exponent| bound for prices/volumes (1e-12 .. 1e12): far beyond any real kline.
_MAX_ADJUSTED: Final = 12
#: A ms open time is exactly 13 ASCII digits (2001..2286); `str.isdigit` would admit Unicode
#: digits that `int()` then rejects with a non-`KlinePageRejected` error.
_TS_RE: Final = re.compile(r"[0-9]{13}")


def _dec(raw: object) -> Decimal:
    if not isinstance(raw, str):
        raise KlinePageRejected("kline value is not a string", "row_shape")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise KlinePageRejected("kline value is not a number", "unparseable") from exc
    if not value.is_finite():  # NaN, sNaN, Infinity
        raise KlinePageRejected("kline value is not finite", "unparseable")
    # S1: bound the magnitude so `"1e999999"` can neither pass nor blow up later arithmetic.
    if value and not -_MAX_ADJUSTED <= value.adjusted() <= _MAX_ADJUSTED:
        raise KlinePageRejected("kline value magnitude is out of range", "unparseable")
    return value


def _check_row(
    o: Decimal, h: Decimal, low: Decimal, c: Decimal, v: Decimal, t: Decimal, tick: Decimal | None
) -> None:
    if min(o, h, low, c) <= 0:
        raise KlinePageRejected("kline price is not positive", "non_positive_price")
    if h < max(o, c):
        raise KlinePageRejected("kline high is below the body", "high_below_body")
    if low > min(o, c):
        raise KlinePageRejected("kline low is above the body", "low_above_body")
    if v < 0 or t < 0:
        raise KlinePageRejected("kline volume/turnover is negative", "negative_volume")
    if tick is not None:
        try:
            off = any(p % tick != 0 for p in (o, h, low, c))
        except ArithmeticError as exc:  # any decimal fault is a bad page, never "transient"
            raise KlinePageRejected(
                "kline price cannot be checked on the tick grid", "off_tick"
            ) from exc
        if off:
            raise KlinePageRejected("kline price is off the tick grid", "off_tick")


def parse_kline_page(
    payload: dict[str, Any],
    *,
    symbol: str,
    interval: str,
    tick_size: Decimal | None = None,
    now_ms: int | None = None,
    limit: int = MAX_PAGE_LIMIT,
) -> list[KlineEvent]:
    """Validate one page and return it **ascending** by open time.

    Any envelope or row fault raises `KlinePageRejected` for the whole page (SR-E12-09).
    """
    if interval not in INTERVAL_MS:
        raise KlinePageRejected(f"interval {interval[:8]!r} is not backfillable", "envelope")
    if payload.get("retCode") != 0:
        raise KlinePageRejected("kline: retCode is not 0", "envelope")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise KlinePageRejected("kline: missing result object", "envelope")
    rows = result.get("list")
    if not isinstance(rows, list):
        raise KlinePageRejected("kline: missing list", "envelope")
    # Size cap on the RESPONSE, before any row is parsed (F3): never more than was asked for.
    if len(rows) > min(limit, MAX_PAGE_LIMIT):
        raise KlinePageRejected("kline page holds more rows than requested", "oversized")
    if result.get("symbol") != symbol:
        raise KlinePageRejected("kline: page symbol does not match the request", "symbol_mismatch")
    now = int(time.time() * 1000) if now_ms is None else now_ms
    width_ms = INTERVAL_MS[interval]
    starts: list[int] = []
    events: list[KlineEvent] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise KlinePageRejected("kline row is not a 7-element list", "row_shape")
        raw_ts = row[0]
        if not isinstance(raw_ts, str) or not _TS_RE.fullmatch(raw_ts):
            raise KlinePageRejected("kline start time is not an integer string", "unparseable")
        start_ms = int(raw_ts)
        if not _aligned(start_ms, interval):
            raise KlinePageRejected("kline open time is off the interval grid", "misaligned_time")
        o, h, low, c, v, t = (_dec(x) for x in row[1:])
        _check_row(o, h, low, c, v, t, tick_size)
        starts.append(start_ms)
        end_ms = start_ms + width_ms
        events.append(
            KlineEvent(
                event_id=EventId(uuid4()),
                ts_event=start_ms * 1000,
                ts_ingest=now * 1000,
                source="backfill",
                symbol=symbol,
                interval=cast(Any, interval),
                start=start_ms * 1000,
                end=end_ms * 1000 - 1,
                open=o,
                high=h,
                low=low,
                close=c,
                volume=v,
                turnover=t,
                confirmed=end_ms <= now,
            )
        )
    # Wire order is strictly newest-first; anything else (dup, reorder) is a tampered page.
    if any(a <= b for a, b in itertools.pairwise(starts)):
        raise KlinePageRejected("kline page is not strictly newest-first", "non_monotonic")
    # Bybit returns contiguous klines: a missing bar inside a page is a truncated/tampered
    # response, so the page is rejected rather than accepted and marked covered (F1).
    if any(a - b != width_ms for a, b in itertools.pairwise(starts)):
        raise KlinePageRejected("kline page has a missing bar", "gap")
    events.reverse()
    return events


async def fetch_kline_page(
    client: BybitRestClient,
    symbol: str,
    interval: str,
    *,
    start_us: int,
    end_us: int,
    limit: int = MAX_PAGE_LIMIT,
    tick_size: Decimal | None = None,
) -> list[KlineEvent]:
    """One validated page (ascending) of klines whose open time is in `[start_us, end_us]`."""
    if not _SYMBOL_RE.fullmatch(symbol):
        raise KlinePageRejected("kline: invalid symbol", "envelope")
    if interval not in INTERVAL_MS:
        raise KlinePageRejected("kline: interval is not backfillable", "envelope")
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be within 1..{MAX_PAGE_LIMIT}")
    payload = await client.get_public(
        PATH,
        params={
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "start": start_us // 1000,
            "end": end_us // 1000,
            "limit": limit,
        },
        endpoint_class=EndpointClass.MARKET_DATA,
    )
    return parse_kline_page(
        payload, symbol=symbol, interval=interval, tick_size=tick_size, limit=limit
    )


class BybitKlineFetcher:
    """`ingestion.kline_backfill.KlineFetcher` over the governed REST client (public,
    `MARKET_DATA` bucket — the lowest-priority REST class, BR-33). `tick_size_for` is the
    instrument catalogue lookup; `None` (unknown symbol) skips only the tick check."""

    def __init__(self, client: BybitRestClient, tick_size_for: TickSizeFor | None = None) -> None:
        self._client = client
        self._tick_size_for = tick_size_for

    async def __call__(
        self, symbol: Symbol, interval: str, start: TsUs, end: TsUs, limit: int = MAX_PAGE_LIMIT
    ) -> Sequence[KlineEvent]:
        tick = self._tick_size_for(symbol) if self._tick_size_for is not None else None
        return await fetch_kline_page(
            self._client, symbol, interval, start_us=start, end_us=end, limit=limit, tick_size=tick
        )


assert frozenset(INTERVAL_MS) <= _KLINE_INTERVALS  # noqa: S101 - import-time contract pin

__all__ = [
    "INTERVAL_MS",
    "MAX_PAGE_LIMIT",
    "PATH",
    "BybitKlineFetcher",
    "KlinePageRejected",
    "fetch_kline_page",
    "parse_kline_page",
]
