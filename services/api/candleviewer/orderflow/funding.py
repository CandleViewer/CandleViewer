"""Funding-rate service (E24-T02): settled-history backfill, interval resolution,
predicted-rate exposure.

Module boundary (C-3.1): orderflow may not import `storage`, `ingestion` or
the exchange adapter, so every collaborator is a local structural Protocol and the
composition root injects the concrete store / fetcher / catalogue / ticker.

Invariants (STRIDE `docs/security/threat-models/E24-derivatives.md` D3/D12):
- the interval is resolved per symbol from the instruments cache and raises when
  unknown - there is no runtime default (`domain.funding`);
- `annualised_pct` is computed once, here, at write time;
- the predicted rate is built from the ticker, flagged `predicted`/`estimated`,
  and has no code path to the store;
- an absent ticker rate yields no predicted item (never a stale one).
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from candleviewer.domain.funding import (
    FundingIntervalUnknown,
    FundingPage,
    FundingRowRejected,
    FundingSettlement,
    HasFundingInterval,
    PredictedFunding,
    SettledFunding,
    resolve_funding_interval_minutes,
    settle,
)
from candleviewer.orderflow.errors import OrderflowError
from candleviewer.orderflow.funding_metrics import (
    deriv_funding_backfill_pages_total,
    deriv_funding_interval_minutes,
    deriv_funding_refresh_total,
    deriv_upstream_schema_rejected_total,
    symbol_label,
)


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Page size of the upstream history call (exchange maximum).
PAGE_LIMIT: Final = 200
#: Hard bound on pages per backfill run (200 rows x 200 pages = 40k settlements).
MAX_PAGES_PER_RUN: Final = 200
#: Read-side caps (STRIDE D12; G1 window cap proposal: 400 d for funding).
MAX_WINDOW_DAYS: Final = 400
MAX_LIMIT: Final = 500
DEFAULT_LIMIT: Final = 100
CURSOR_TTL_S: Final = 3600
CURSOR_MAX_LEN: Final = 512
_INT64_MAX: Final = 2**63 - 1
_US_PER_DAY: Final = 86_400 * 1_000_000


class FundingInvalidRequest(OrderflowError):
    """Request bounds violated; `code` is the 22-api error-registry code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class FundingSymbolUnknown(OrderflowError):
    """The symbol is not in the instruments cache."""


class FundingStore(Protocol):
    async def write_settled(self, rows: Sequence[SettledFunding]) -> None: ...

    async def read_settled(
        self, symbol: str, rng: _Range, limit: int
    ) -> Sequence[SettledFunding]: ...


class _Range(Protocol):
    @property
    def start_us(self) -> int: ...
    @property
    def end_us(self) -> int: ...


class FundingFetcher(Protocol):
    """One newest-first page of settlements in `[start_us, end_us]`."""

    async def __call__(
        self, symbol: str, start_us: int, end_us: int, limit: int
    ) -> Sequence[FundingSettlement]: ...


class TickerFunding(Protocol):
    @property
    def funding_rate(self) -> Decimal | None: ...
    @property
    def next_funding_time(self) -> int | None: ...
    @property
    def ts_event(self) -> int: ...


class TickerSource(Protocol):
    def latest(self, symbol: str) -> TickerFunding | None: ...


InstrumentLookup = Callable[[str], HasFundingInterval | None]


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start_us: int
    end_us: int


@dataclass(frozen=True, slots=True)
class FundingSeries:
    symbol: str
    funding_interval_minutes: int
    settled: tuple[SettledFunding, ...]
    predicted: PredictedFunding | None
    next_funding_time_us: int | None
    next_cursor: str | None
    has_more: bool


def encode_cursor(symbol: str, after_ts_us: int, *, now_s: float) -> str:
    raw = json.dumps({"s": symbol, "t": after_ts_us, "i": int(now_s)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, *, symbol: str, now_s: float) -> int:
    """Return the ts to resume after. Malformed, expired or foreign-symbol
    cursors raise `FundingInvalidRequest("invalid_cursor")`."""
    bad = FundingInvalidRequest("invalid_cursor", "pagination cursor is malformed or expired")
    if not cursor or len(cursor) > CURSOR_MAX_LEN:
        raise bad
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        sym, after, issued = data["s"], data["t"], data["i"]
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise bad from exc
    in_range = isinstance(after, int) and not isinstance(after, bool) and 0 <= after <= _INT64_MAX
    ints = in_range and all(isinstance(v, int) and not isinstance(v, bool) for v in (after, issued))
    if sym != symbol or not ints or now_s - issued > CURSOR_TTL_S or issued > now_s + 60:
        raise bad
    return int(after)


class FundingService:
    def __init__(
        self,
        *,
        store: FundingStore,
        fetcher: FundingFetcher | None,
        instruments: InstrumentLookup,
        tickers: Callable[[], TickerSource | None],
        clock_s: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._fetcher = fetcher
        self._instruments = instruments
        self._tickers = tickers
        self._clock_s = clock_s

    @property
    def store(self) -> FundingStore:
        """The guarded store, read by the derivatives engine's `/market/metrics` path."""
        return self._store

    def interval_minutes(self, symbol: str) -> int:
        """THE accessor. Raises `FundingIntervalUnknown`; also publishes the gauge."""
        instrument = self._instruments(symbol)
        if instrument is None:
            logger().warning("funding_interval_missing", symbol=symbol_label(symbol))
        interval = resolve_funding_interval_minutes(instrument)
        deriv_funding_interval_minutes.labels(symbol=symbol_label(symbol)).set(interval)
        return interval

    async def backfill(self, symbol: str, window: TimeWindow) -> int:
        """Backfill settled history for `window`, newest page first, until the
        window start is reached. Idempotent (store dedups `(ts, symbol)`).
        Returns rows handed to the store."""
        if self._fetcher is None:
            raise OrderflowError("no funding fetcher wired")
        label = symbol_label(symbol)
        try:
            interval = self.interval_minutes(symbol)
        except FundingIntervalUnknown:
            deriv_funding_refresh_total.labels(symbol=label, result="interval_unknown").inc()
            raise
        written, end_us = 0, window.end_us
        try:
            for _ in range(MAX_PAGES_PER_RUN):
                page = await self._fetcher(symbol, window.start_us, end_us, PAGE_LIMIT)
                deriv_funding_backfill_pages_total.inc()
                self._count_rejected(label, page)
                if not page:
                    break
                rows = [
                    settle(symbol, s.ts_us, s.funding_rate, interval)
                    for s in page
                    if window.start_us <= s.ts_us <= window.end_us
                ]
                await self._store.write_settled(rows)
                written += len(rows)
                oldest = min(s.ts_us for s in page)
                if len(page) < PAGE_LIMIT or oldest <= window.start_us or oldest > end_us:
                    break
                end_us = oldest - 1000  # the upstream takes millisecond bounds
        except Exception as exc:
            if isinstance(exc, FundingRowRejected):
                deriv_upstream_schema_rejected_total.labels(
                    topic="funding_history", reason=exc.reason
                ).inc()
                logger().warning("funding_page_rejected", symbol=label, reason=exc.reason)
            deriv_funding_refresh_total.labels(symbol=label, result="error").inc()
            raise
        deriv_funding_refresh_total.labels(symbol=label, result="ok").inc()
        return written

    @staticmethod
    def _count_rejected(label: str, page: Sequence[FundingSettlement]) -> None:
        """Count adapter-rejected rows; one structured log line per page (no payload)."""
        reasons = page.rejected_reasons if isinstance(page, FundingPage) else []
        for reason in reasons:
            deriv_upstream_schema_rejected_total.labels(
                topic="funding_history", reason=reason
            ).inc()
        if reasons:
            logger().warning(
                "funding_rows_rejected", symbol=label, count=len(reasons), reason=reasons[0]
            )

    def predicted(self, symbol: str) -> tuple[PredictedFunding | None, int | None]:
        """`(predicted item | None, next_funding_time_us | None)` from the ticker."""
        source = self._tickers()
        event = source.latest(symbol) if source is not None else None
        if event is None:
            return None, None
        next_us = event.next_funding_time
        if event.funding_rate is None:
            return None, next_us
        ts_us = next_us if next_us is not None else event.ts_event
        return (
            PredictedFunding(ts_us=ts_us, symbol=symbol, funding_rate=event.funding_rate),
            next_us,
        )

    async def series(
        self,
        symbol: str,
        *,
        start_us: int | None,
        end_us: int | None,
        limit: int,
        cursor: str | None,
    ) -> FundingSeries:
        now_s = self._clock_s()
        now_us = int(now_s * 1_000_000)
        if cursor is not None and len(cursor) > CURSOR_MAX_LEN:
            raise FundingInvalidRequest(
                "invalid_cursor", "pagination cursor is malformed or expired"
            )
        if not 1 <= limit <= MAX_LIMIT:
            raise FundingInvalidRequest("validation_failed", f"limit must be 1..{MAX_LIMIT}")
        end = end_us if end_us is not None else now_us
        start = start_us if start_us is not None else end - MAX_WINDOW_DAYS * _US_PER_DAY
        if start >= end or end - start > MAX_WINDOW_DAYS * _US_PER_DAY:
            raise FundingInvalidRequest(
                "invalid_time_range", f"from/to must be ordered and span <= {MAX_WINDOW_DAYS} days"
            )
        try:
            interval = self.interval_minutes(symbol)
        except FundingIntervalUnknown as exc:
            raise FundingSymbolUnknown(symbol) from exc
        if cursor:
            start = max(start, decode_cursor(cursor, symbol=symbol, now_s=now_s) + 1)
        rows = list(await self._store.read_settled(symbol, TimeWindow(start, end), limit + 1))
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(symbol, rows[-1].ts_us, now_s=now_s) if has_more else None
        predicted, next_us = self.predicted(symbol)
        return FundingSeries(
            symbol=symbol,
            funding_interval_minutes=interval,
            settled=tuple(rows),
            predicted=None if has_more else predicted,
            next_funding_time_us=next_us,
            next_cursor=next_cursor,
            has_more=has_more,
        )


__all__ = [
    "CURSOR_TTL_S",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_WINDOW_DAYS",
    "FundingInvalidRequest",
    "FundingSeries",
    "FundingService",
    "FundingSymbolUnknown",
    "TimeWindow",
    "decode_cursor",
    "encode_cursor",
]
