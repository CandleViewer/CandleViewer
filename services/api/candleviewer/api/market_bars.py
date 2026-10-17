"""`GET /market/bars` (`22-api-openapi.yaml` `getBars`, E12-T05 #398).

The single REST entry point for every bar type, served from the `bars_<kind>` tables through
`bars.reader.BarReader.read_bars` (parameterised SQL, table from a closed allow-list, checksum
verified). It never constructs a builder and never substitutes exchange klines.

Order of refusal (each before any storage read except where noted):
1. RBAC `marketdata:read` (501 no resolver / 401 / 403).
2. `bar_type`/`param` parsed by E12-T01's `bars.spec.from_wire` plus the SR-E12-03 bounds
   (`bars.limits`): malformed -> 400 `validation_failed`; a type the server cannot build
   (`pnf`, `heikin_ashi`, renko `atr:*` per ADR-0033 R1) -> 422 naming the alternative.
3. Unknown symbol -> 422; storage not composed -> 503.
4. Non-time bars: a window starting before `recording_started_at` -> 422 `no_data_recorded`.
   This is checked **before** the window cap: it is the more specific data-availability fact,
   and the client cannot fix it by paginating (22-api precedence rule).
5. Hard window caps only (SR-E12-02, 22-api paging rule): time bars <= 400 d and <= 250 000
   estimated bars (window / interval), non-time bars <= 31 d and then <= 250 000 bars estimated
   from the window's stored prints (`bars.estimate`, #2093: one bounded count, the only read
   before the bars; it fails closed with 503) -> 422 `bar_window_too_large`. Anything narrower
   is paged by rows: an uncursored request is the first page, every read asks for `limit + 1`
   rows (bounded work), and a server-issued `next_cursor` is returned whenever more rows remain.

The cursor is bound to `(bars, symbol, bar_type:param)` (`api.market_response`), so a klines
cursor or one for another series is `invalid_cursor`. Time bars order by `ts` with a `ts`
cursor (open time is unique per interval; kline rows have a NULL `index`). Non-time bars order
by the stored key `(ts, generation, index)` and the cursor carries that key (#2017), so
equal-`ts` siblings (one print -> N volume bars / renko bricks) are each served exactly once
across page boundaries. Every stored bar carries `index` and `generation` when the row has one.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.market_response import (
    InvalidCursor,
    build_meta,
    cursor_scope,
    decode_cursor,
    decode_key_cursor,
    encode_cursor,
    encode_key_cursor,
    kline_response,
    problem,
    serialize_bar,
    with_recording_started_at,
)
from candleviewer.bars.errors import BarParamOutOfRange, BarSpecError
from candleviewer.bars.estimate import estimate_non_time_bars
from candleviewer.bars.limits import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_NON_TIME_WINDOW_US,
    MAX_TIME_WINDOW_US,
    MAX_WINDOW_BARS,
    QUERY_TIMEOUT_S,
)
from candleviewer.bars.metrics import (
    bars_endpoint_422_no_data_recorded_total,
    record_page,
    record_param_rejected,
)
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarKey, BarPage, row_key, stored_bar
from candleviewer.bars.spec import PARAM_MAX_LEN, check_param_bounds, from_wire
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.rows import TradeTotals

_REQUIRED_PERMISSION: Final = "marketdata:read"
_BAR_TYPES: Final = frozenset(
    {"time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"}
)
_TIME_ALTERNATIVE: Final = "use bar_type=time, tick, volume, range, delta or renko with a number"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    def resolve(self, request: Request) -> Any: ...


class BarReaderLike(Protocol):
    async def read_bars(
        self,
        symbol: str,
        spec: BarSpec,
        from_us: int,
        to_us: int,
        limit: int,
        *,
        after_us: int | None = None,
        at_key: BarKey | None = None,
    ) -> BarPage: ...


RecordingStart = Callable[[str], Awaitable[int | None]]
#: SR-E12-02 (#2093): a symbol's stored prints in a window (`MarketDataRepository.trade_totals`).
TradeTotalsSource = Callable[[str, TimeRange], Awaitable[TradeTotals]]


class _Rejected(Exception):
    def __init__(self, response: JSONResponse) -> None:
        self.response = response


def _bad_param(reason: str, status: int, detail: str) -> _Rejected:
    record_param_rejected(reason)
    return _Rejected(problem(status, "validation_failed", "Invalid param", detail))


def parse_bar_request(bar_type: str, param: str) -> BarSpec:
    """`(bar_type, param)` -> `BarSpec` or `_Rejected` (400 malformed, 422 unsupported)."""
    if bar_type not in _BAR_TYPES:
        raise _bad_param("invalid", 400, "bar_type is not a supported bar type.")
    if bar_type in ("pnf", "heikin_ashi") or param.startswith("atr:"):
        what = {
            "pnf": "Point-and-figure bars are not available yet",
            "heikin_ashi": "Heikin-Ashi is a chart transform over time bars; use bar_type=time",
        }.get(bar_type, "ATR-sized renko bricks are not available yet (ADR-0033)")
        raise _bad_param("unsupported", 422, f"{what}; {_TIME_ALTERNATIVE}.")
    if len(param) > PARAM_MAX_LEN:
        raise _bad_param("invalid", 400, f"param must be at most {PARAM_MAX_LEN} characters.")
    try:
        spec = from_wire(bar_type, param)
    except BarSpecError:
        # Never echo the client's text back (it may be a probe); name the field and the rule.
        raise _bad_param(
            "invalid", 400, f"param is not valid for bar_type {bar_type}; see the param table."
        ) from None
    try:
        check_param_bounds(spec, bar_type)
    except BarParamOutOfRange as exc:
        raise _bad_param("out_of_range", 400, str(exc)) from None
    return spec


def _ts_us(value: str | None) -> int | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000)


def _bad(detail: str) -> JSONResponse:
    return problem(400, "validation_failed", "Bad request", detail)


def _window_too_large(detail: str) -> JSONResponse:
    return problem(422, "bar_window_too_large", "Window too large", detail)


def make_market_bars_router(
    reader_provider: Callable[[], BarReaderLike | None],
    *,
    recording_started_at_us: RecordingStart | None = None,
    trade_totals: TradeTotalsSource | None = None,
    principal_resolver: _Resolver | None = None,
    symbol_listed: Callable[[str], bool] | None = None,
    now_us: Callable[[], int],
) -> APIRouter:
    """Bind `GET /market/bars`. `reader_provider()` is resolved per request (the bars reader
    exists only once a real QuestDB is composed); `None` -> 503. `symbol_listed=None` fails
    closed (503), never open, and so does `trade_totals=None` for non-time bars."""
    router = APIRouter(tags=["market-data"])

    async def _authorize(request: Request) -> None:
        if principal_resolver is None:
            raise _Rejected(problem(501, "internal_error", "Not implemented",
                                    "Session verification is not wired yet."))  # fmt: skip
        got = principal_resolver.resolve(request)
        principal: _Principal | None = await got if inspect.isawaitable(got) else got
        if principal is None:
            raise _Rejected(problem(401, "unauthenticated", "Unauthorized",
                                    "Sign in to read market data."))  # fmt: skip
        if not principal.has(_REQUIRED_PERMISSION):
            detail = f"Reading market data requires {_REQUIRED_PERMISSION}."
            raise _Rejected(problem(403, "forbidden", "Forbidden", detail))

    async def _print_estimate(
        symbol: str, spec: BarSpec, bar_type: str, rng: TimeRange
    ) -> JSONResponse | None:
        """SR-E12-02 for non-time bars (#2093): None when the bars estimated from `rng`'s stored
        prints fit `MAX_WINDOW_BARS`, else the 422. Fails closed, like the read: no count source,
        or a count that fails or outlives `QUERY_TIMEOUT_S`, is 503. Never a skipped check (a
        slow store is when the extra load costs most) and never a 422, which is final
        (`retryable: false`) and would state a size nobody measured."""
        if trade_totals is None:
            detail = "Recorded trade totals are not available yet; retry shortly."
            return problem(503, "store_unavailable", "Service unavailable", detail)
        try:
            async with asyncio.timeout(QUERY_TIMEOUT_S):
                totals = await trade_totals(symbol, rng)
        except (TimeoutError, OSError, ConnectionError, StorageTierUnavailable):
            detail = "Trade storage did not answer in time; retry shortly or narrow from/to."
            return problem(503, "store_unavailable", "Service unavailable", detail)
        if estimate_non_time_bars(spec, totals.prints, totals.qty) <= MAX_WINDOW_BARS:
            return None
        return _window_too_large(
            f"The window holds more than {MAX_WINDOW_BARS:,} {bar_type} bars, estimated from "
            "recorded trades; narrow from/to."
        )

    @router.get("/market/bars")
    async def get_bars(
        request: Request,
        symbol: str,
        bar_type: str,
        param: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        cursor: str | None = Query(default=None),  # length enforced by decode_cursor (#2087 S1)
        include_open: bool = Query(default=False),
        include_delta: bool = Query(default=True),
    ) -> Response:
        try:
            await _authorize(request)
            spec = parse_bar_request(bar_type, param)
        except _Rejected as rejected:
            return rejected.response
        try:
            start_us, end_us = _ts_us(from_), _ts_us(to)
        except ValueError:
            return _bad("from/to must be RFC 3339 timestamps.")
        if start_us is None:
            return _bad("'from' is required.")
        end_us = now_us() if end_us is None else end_us
        if start_us > end_us:
            return _bad("'from' must not be after 'to'.")
        after_us: int | None = None
        at_key: BarKey | None = None
        scope = cursor_scope("bars", symbol, f"{bar_type}:{param}")
        if cursor is not None:
            try:
                if spec.kind == "time":
                    after_us = decode_cursor(cursor, scope=scope, end_us=end_us,
                                             start_us=start_us) - 1  # fmt: skip
                else:
                    at_key = decode_key_cursor(cursor, scope=scope, end_us=end_us,
                                               start_us=start_us)  # fmt: skip
                    after_us = at_key[0] - 1  # window-cap arithmetic only; not sent to reader
            except InvalidCursor:
                detail = "The cursor is not valid for this request; restart without it."
                return problem(400, "invalid_cursor", "Invalid cursor", detail)
        if symbol_listed is None or (reader := reader_provider()) is None:
            return problem(503, "store_unavailable", "Service unavailable",
                           "Bar storage is not ready yet.")  # fmt: skip
        if not symbol_listed(symbol):
            return problem(422, "validation_failed", "Unprocessable entity",
                           "This symbol is not a listed instrument.")  # fmt: skip
        if spec.kind != "time" and recording_started_at_us is None:
            # #2089 adversarial L3: no recording-start source wired is a server state, not a
            # fact about the data — 503, never a misleading `no_data_recorded`.
            return problem(503, "store_unavailable", "Service unavailable",
                           "Recording metadata is not available yet; retry shortly.")  # fmt: skip
        started = await recording_started_at_us(symbol) if recording_started_at_us else None
        if spec.kind != "time" and (started is None or start_us < started):
            # Precedence: before the window cap (22-api /market/bars).
            bars_endpoint_422_no_data_recorded_total.inc()
            if started is None:
                when = f"{symbol} has no recorded trades yet"
            else:
                begins = datetime.fromtimestamp(started / 1e6, UTC)
                when = f"recording for {symbol} begins {begins:%d %b %Y}"
            refused = problem(422, "no_data_recorded", "No data recorded",
                              f"{bar_type.capitalize()} bars need recorded trade data; {when}. "
                              "Choose a later window or use time bars.")  # fmt: skip
            return with_recording_started_at(refused, started)
        span_cap = MAX_TIME_WINDOW_US if spec.kind == "time" else MAX_NON_TIME_WINDOW_US
        span = end_us - max(start_us, (after_us or 0) + 1)
        if span > span_cap:
            days = span_cap // 86_400_000_000
            return _window_too_large(f"A {bar_type} bar window may span at most {days} days.")
        if spec.kind == "time":
            # SR-E12-02 estimate: ceil(window / interval) <= MAX_WINDOW_BARS, before any query.
            width_us = int(spec.param_value) * 1000
            if -(-span // width_us) > MAX_WINDOW_BARS:
                return _window_too_large(
                    f"The window holds more than {MAX_WINDOW_BARS:,} {param}-minute bars; "
                    "narrow from/to."
                )
        else:
            # Non-time bars (#2093): estimate from the prints the read pages through, which
            # start at the cursor's bar when there is one.
            first_us = start_us if at_key is None else at_key[0]
            rng = TimeRange(start_us=first_us, end_us=end_us)
            if (refusal := await _print_estimate(symbol, spec, bar_type, rng)) is not None:
                return refusal
        try:
            async with asyncio.timeout(QUERY_TIMEOUT_S):
                page = await (
                    reader.read_bars(symbol, spec, start_us, end_us, limit + 1, after_us=after_us)
                    if at_key is None
                    else reader.read_bars(symbol, spec, start_us, end_us, limit + 1, at_key=at_key)
                )
        except (TimeoutError, OSError, ConnectionError):
            return problem(503, "store_unavailable", "Service unavailable",
                           "Bar storage did not answer in time; retry shortly.")  # fmt: skip
        # `has_more` comes from the RAW fetch (#2089 adversarial M1): `read_bars` withholds
        # checksum-failed rows (`page.dropped`) but reports the position of the (limit+1)-th raw
        # row whenever the fetch was full. That row is the next page's first, so a dropped row
        # (even the page's last) is stepped over, never ends the series.
        rows = [stored_bar(r) for r in page.rows]
        next_cursor: str | None = None
        if spec.kind != "time":
            if page.next_key is not None:  # keyset: the extra row opens the next page
                rows = [s for s, r in zip(rows, page.rows, strict=True)
                        if row_key(r) < page.next_key]  # fmt: skip
                next_cursor = encode_key_cursor(scope, page.next_key)
        elif (resume := page.next_cursor) is not None:
            kept = [r for r in rows if r.ts_us < resume]  # the extra row opens the next page
            if kept or not rows:
                rows = kept
            else:  # unreachable for time bars (unique open time); strict progress regardless
                rows = rows[:limit]
                resume = rows[-1].ts_us + 1
            next_cursor = encode_cursor(scope, resume)
        if not include_open:
            rows = [r for r in rows if r.confirmed]  # only the newest bar can be forming
        sources = (["tape"] if any(r.tape_built for r in rows) else []) + (
            ["questdb"] if any(not r.tape_built for r in rows) else [])  # fmt: skip
        record_page("bars", len(rows), sources)
        _log().info("market_bars_served", symbol=symbol, bar_type=bar_type,
                    spec_hash=spec.spec_hash, tiers=sources, rows=len(rows))  # fmt: skip
        meta = build_meta(count=len(rows), next_cursor=next_cursor, sources=sources,
                          recording_started_at_us=started, generated_at_us=now_us())  # fmt: skip
        return kline_response(
            symbol=symbol, interval=param, bar_type=bar_type,
            bars=[serialize_bar(r, include_delta=include_delta) for r in rows], meta=meta,
        )  # fmt: skip

    return router


__all__ = ["BarReaderLike", "RecordingStart", "make_market_bars_router", "parse_bar_request"]
