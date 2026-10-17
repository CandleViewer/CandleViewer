"""`GET /market/klines` (`docs/plan/22-api-openapi.yaml`).

QA defect #1622 blocker: the E08-S06 backfill core (coverage index, paging,
rate-limit-safe fetch — `ingestion/kline_backfill.py`) landed in PR #1613,
but the ticket's own core deliverable, the REST endpoint itself, did not —
`grep -rln "market/klines" services/api/candleviewer/**/*.py` outside
`ingestion/` returned nothing. This module is the thin HTTP adapter, mirrors
the pattern `api/audit.py` and `api/health.py` already establish: a
structurally-typed Protocol for the injected cache reader (no import edge
beyond `storage`'s own public surface, which `api` — the composition root's
HTTP layer — is already allowed to depend on), RFC 9457 problem responses,
and a cache-first read so a fully-covered request never touches the
exchange (ticket "Cache hit" scenario).

Backfilling missing history (the exchange fetch itself) is intentionally
**out of scope for this endpoint** in the fake/CI-default storage backend:
`KlineBackfillService` needs a live `KlineFetcher` (the exchange adapter, not
yet implemented — E08-T02 is still a scaffold, see the adapter's
`service.py`), so until that adapter exists this route serves cache-only
reads and reports the request's coverage holes in `meta` rather than
silently pretending the exchange was consulted. Once E08-T02 lands, wiring
a real `KlineFetcher` here is a one-line change (mirrors the audit router's
own "one-line change once it lands" pattern in `app.py`).

PR #1626 review (defect #1622 fixer pass): `22-api-openapi.yaml` declares
`x-rbac: {permissions: [marketdata:read], scope: none}` for this route
(C-12.4 — RBAC is enforced server-side, never just hidden in the UI); the
first cut of this router served every request unauthenticated. This module
now mirrors `api/audit.py`'s own fail-closed `_authorize_or_raise` pattern
exactly: an injected, structurally-typed `PrincipalResolver` resolves the
caller from the request, and the caller must hold `marketdata:read` or the
request never reaches the cache. `app.py` injects the session-backed resolver
(#2092, as for `/market/bars`). `principal_resolver=None` (the composition has
no identity provider, i.e. the fake storage backend, so no session can be
verified) degrades to `501`, not to "allow anyone" — there is a difference
between "no session-verification module is composed" and "this caller is
unauthenticated", and only the resolver can tell those apart (mirrors
`api/audit.py`'s own docstring on this point).
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.market_response import (
    InvalidCursor,
    build_meta,
    cursor_scope,
    decode_cursor,
    encode_cursor,
    kline_response,
    problem,
    serialize_bar,
)
from candleviewer.bars.limits import DEFAULT_LIMIT, MAX_LIMIT, MAX_TIME_WINDOW_US
from candleviewer.bars.metrics import record_page, record_param_rejected
from candleviewer.ingestion.kline_coverage import CoverageIndex, Range
from candleviewer.ingestion.kline_read import SOURCE_HOT, KlineReadService
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import TierHint, TimeRange

_REQUIRED_PERMISSION = "marketdata:read"

#: `price_type` values the contract enumerates; only `trade` klines are stored today (the
#: mark/index/premium-index kline streams are not ingested), so the others are refused 422.
_PRICE_TYPES = frozenset({"trade", "mark", "index", "premium_index"})
_SERVED_PRICE_TYPES = frozenset({"trade"})
#: A4: slices scanned per page before a data hole ends the page (bounded work per request).
_MAX_SLICES = 16

#: exchange-compatible interval codes, mirrors `22-api-openapi.yaml`'s
#: `KlineInterval` enum — kept as a plain tuple (not an import from
#: `exchange.base`) so this router never needs an edge into `exchange.*`.
_MIN_US = 60_000_000
#: Bar width per interval for the window cap; `M` uses 31 days (its longest month).
_INTERVAL_US: dict[str, int] = {
    **{c: int(c) * _MIN_US for c in ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720")},
    "D": 1440 * _MIN_US,
    "W": 7 * 1440 * _MIN_US,
    "M": 31 * 1440 * _MIN_US,
}
_VALID_INTERVALS = (
    "1",
    "3",
    "5",
    "15",
    "30",
    "60",
    "120",
    "240",
    "360",
    "720",
    "D",
    "W",
    "M",
)


@dataclass(frozen=True, slots=True)
class MarketDataPrincipal:
    """The authenticated caller, as resolved server-side from the session
    (mirrors `audit.access.AuditPrincipal` — the audit and market-data
    surfaces share the same session concept but not the same permission
    vocabulary, so this router keeps its own small principal type rather
    than importing `audit`'s)."""

    user_id: str
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions  # nosem: no-adhoc-authz reason=Principal.has_permission-wildcard-impl-pending-E09-T01-authorize owner=@CandleViewer/security review=2026-12-31  # noqa: E501  # fmt: skip


class _Principal(Protocol):
    """All the router needs of a resolved caller: whether it holds a permission. Both
    `MarketDataPrincipal` and the session resolver's `audit.access.AuditPrincipal` (which
    the composition root injects, #2092) satisfy it structurally."""

    def has(self, permission: str) -> bool: ...


class PrincipalResolver(Protocol):
    """Resolves the authenticated caller for a `/market/klines` request.

    Structurally typed so this router never imports a concrete session
    module; the composition root injects the session-backed implementation
    (`api/audit_principal.py`, as for `/market/bars`). Returning `None`
    means "no verified session" (401) — mirrors `api/audit.py`'s own
    `PrincipalResolver`, including the distinction between a resolver that
    found no session (401) and no resolver being wired at all (501, see
    `_authorize_or_raise` below)."""

    def resolve(self, request: Request) -> _Principal | Awaitable[_Principal | None] | None: ...


class CoverageIndexProvider(Protocol):
    """`Callable[[str, str], CoverageIndex | None]` — declared as a Protocol
    (not a bare `object`) so the router's own strict typing covers this
    parameter the same way it covers `MarketDataCacheLike` and
    `PrincipalResolver`, instead of relying on a runtime `isinstance` check
    against the return value."""

    def __call__(self, symbol: str, interval: str) -> CoverageIndex | None: ...


class KlineRowLike(Protocol):
    """The subset of `storage.repositories.rows.KlineRow` this router
    reads back and serialises — declared structurally (mirrors
    `ingestion.kline_backfill.KlineRowLike`) so this module only needs the
    fields it actually renders."""

    @property
    def ts_us(self) -> int: ...
    @property
    def open(self) -> str: ...
    @property
    def high(self) -> str: ...
    @property
    def low(self) -> str: ...
    @property
    def close(self) -> str: ...
    @property
    def volume(self) -> str: ...
    @property
    def turnover(self) -> str: ...
    @property
    def confirmed(self) -> bool: ...


class MarketDataCacheLike(Protocol):
    """Structural type for `storage.repositories.market_data.
    MarketDataRepository.read_klines` — the composition root injects the
    real `ctx.storage.market_data` (or a test fake)."""

    async def read_klines(
        self,
        sym: str,
        interval: str,
        rng: TimeRange,
        tier: TierHint = "auto",
        limit: int | None = None,
    ) -> Sequence[KlineRowLike]: ...


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    """Problem with the catalogued `code` for this status (OpenAPI `Problem.code` is required)."""
    return problem(
        status_code, _CODE_BY_STATUS.get(status_code, "validation_failed"), title, detail
    )


_CODE_BY_STATUS: dict[int, str] = {
    400: "validation_failed",
    401: "unauthenticated",
    403: "forbidden",
    422: "validation_failed",
    501: "internal_error",
    503: "store_unavailable",
}


def _parse_time(value: str | None, *, default: datetime | None) -> datetime | None:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _wall_now_us() -> int:
    return time.time_ns() // 1000


def _window_too_large() -> JSONResponse:
    return problem(
        422, "bar_window_too_large", "Window too large",
        "Time bars can be requested for at most 400 days at once; narrow from/to.",
    )  # fmt: skip


def make_market_router(
    cache_provider: Callable[[], MarketDataCacheLike | None],
    *,
    coverage_index_provider: CoverageIndexProvider | None = None,
    principal_resolver: PrincipalResolver | None = None,
    read_service_provider: Callable[[], KlineReadService | None] | None = None,
    symbol_listed: Callable[[str], bool] | None = None,
    now_us: Callable[[], int] = _wall_now_us,
) -> APIRouter:
    """Bind `GET /market/klines` to a concrete cache reader.

    `cache_provider` is called once per request (not once at router
    construction) because `create_app()` builds this router before the
    ASGI lifespan runs `storage.start()` (`app.py`'s own docstring: "the
    module supervisor is *not* started here") — `ctx.storage.market_data`
    raises `StorageTierUnavailable` until then, so a request arriving
    before startup finishes must still get a clean `503`, not an
    unhandled exception. A provider returning `None` (mirrors
    `make_audit_router`'s own `audit_service=None` default) also degrades
    to `503` rather than raising at import time, so `create_app()` stays
    constructible with fakes only. `coverage_index_provider` is an
    optional `Callable[[str, str], CoverageIndex | None]` used only to
    compute the `meta.coverage_holes` diagnostic (never required for
    correctness of the returned bars) — the fake/default storage backend
    has no coverage tracking of its own, so a request against it simply
    reports an empty hole list.

    `principal_resolver=None` (no identity provider composed, i.e. the fake
    storage backend; same posture as `make_audit_router`'s own default and
    `make_market_bars_router`) makes every request fail closed with `501`
    rather than silently serving unauthenticated reads (C-12.4, PR #1626
    review) — RBAC on this route ("marketdata:read", scope none: public
    market data, not account-scoped) is enforced here, server-side, never
    left to the UI to hide a button.

    E12-S05: when `read_service_provider` yields a `KlineReadService`, reads go through it
    (cold + hot tiers merged; exchange backfill started in the background for hot holes and
    never awaited) and `meta.sources` / `meta.recording_started_at` come from it.

    SR-E12-08 (#2045 security review): a read that can start an exchange backfill is only
    served for a symbol `symbol_listed` accepts (instrument catalogue); an unknown symbol is
    `422` (declared by the route) before any read, job or per-key state. With a read service
    but no catalogue check wired, the route fails closed (`503`). The window may span at
    most 400 days (`422 bar_window_too_large`); narrower windows are paged by rows, each read
    asking for `limit + 1` rows (22-api paging rule, #2087 A1/A4).

    S3 (#2087 security review): FastAPI parses and validates query parameters before this
    handler, so an unauthenticated caller can see a 400/422 schema error before the 401. Those
    bodies go through `api.error_redaction` and never echo input.
    """
    router = APIRouter(tags=["market-data"])

    class _HttpProblem(Exception):
        def __init__(self, response: JSONResponse) -> None:
            self.response = response

    async def _authorize_or_raise(request: Request) -> None:
        if principal_resolver is None:
            raise _HttpProblem(
                _problem(501, "Not implemented", "Session verification is not wired yet.")
            )
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            raise _HttpProblem(_problem(401, "Unauthorized", "Sign in to read market data."))
        if not principal.has(_REQUIRED_PERMISSION):
            raise _HttpProblem(
                _problem(403, "Forbidden", f"Reading market data requires {_REQUIRED_PERMISSION}.")
            )

    @router.get("/market/klines")
    async def get_klines(
        request: Request,
        symbol: str,
        interval: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        # S1: no `max_length` here — FastAPI's pre-handler 422 would echo the value and skip
        # the Problem shape; `decode_cursor` enforces the length and returns `invalid_cursor`.
        cursor: str | None = Query(default=None),
        price_type: str = Query(default="trade"),
        include_open: bool = Query(default=False),
        include_delta: bool = Query(default=False),
    ) -> Response:
        try:
            await _authorize_or_raise(request)
        except _HttpProblem as problem_:
            return problem_.response
        try:
            cache = cache_provider()
        except StorageTierUnavailable:
            cache = None
        if cache is None:
            return _problem(503, "Service unavailable", "Market data storage is not ready yet.")
        if interval not in _VALID_INTERVALS:
            record_param_rejected("invalid")  # A6
            return _problem(400, "Bad request", "The interval is not a supported interval code.")
        if price_type not in _PRICE_TYPES:
            record_param_rejected("invalid")
            return _problem(
                400, "Bad request", "price_type must be trade, mark, index or premium_index."
            )
        if price_type not in _SERVED_PRICE_TYPES:
            record_param_rejected("unsupported")
            return _problem(
                422, "Unprocessable entity",
                f"{price_type} candles are not recorded yet; request price_type=trade.",
            )  # fmt: skip
        try:
            end_dt = _parse_time(to, default=datetime.fromtimestamp(now_us() / 1e6, tz=UTC))
            start_dt = _parse_time(from_, default=None)
        except ValueError:
            return _problem(400, "Bad request", "from/to must be RFC 3339 timestamps.")
        if end_dt is None or start_dt is None:
            return _problem(400, "Bad request", "'from' is required.")
        if start_dt > end_dt:
            return _problem(400, "Bad request", "'from' must not be after 'to'.")
        start_us = int(start_dt.timestamp() * 1_000_000)
        end_us = int(end_dt.timestamp() * 1_000_000)
        width = _INTERVAL_US[interval]
        grid = None if interval == "M" else width  # `M` is calendar-variable: no fixed grid
        if cursor is not None:
            try:
                start_us = max(start_us, decode_cursor(
                    cursor, scope=cursor_scope("klines", symbol, interval), end_us=end_us,
                    start_us=start_us,
                    grid_us=grid,
                ))  # fmt: skip
            except InvalidCursor:
                return problem(
                    400, "invalid_cursor", "Invalid cursor",
                    "The cursor is not valid for this request; restart without a cursor.",
                )  # fmt: skip
        if end_us - start_us > MAX_TIME_WINDOW_US:
            # The only window refusal (22-api): the SR-E12-02 hard cap. Anything narrower is
            # served page by page.
            return _window_too_large()
        service = read_service_provider() if read_service_provider is not None else None
        if service is not None and symbol_listed is None:
            return _problem(
                503, "Service unavailable", "The instrument catalogue is not ready yet."
            )
        if symbol_listed is not None and not symbol_listed(symbol):
            # 422, not 404: the only client-error statuses this route declares are 400/422.
            return _problem(422, "Unprocessable entity", "This symbol is not a listed instrument.")
        # A1/A4: row-based paging. Time bars have a fixed width, so a slice of `limit` widths
        # holds at most `limit` bars; read slices oldest-first (each read asks for `limit + 1`
        # rows, bounded) until a full page plus one row proves `has_more`, the window ends, or
        # `_MAX_SLICES` slices were scanned (a long data hole: the page then ends at the last
        # scanned slice and the cursor resumes after it; `meta.coverage_holes` names the gap).
        recording_started: int | None = None
        rows: list[KlineRowLike] = []
        sources: list[str] = []
        slice_start, slices = start_us, 0
        while slice_start < end_us and len(rows) <= limit and slices < _MAX_SLICES:
            slice_end = min(end_us, slice_start + (limit + 1) * width)
            rng = Range(slice_start, slice_end)
            if service is not None:
                try:
                    read = await service.read(symbol, interval, rng, limit=limit + 1)
                except StorageTierUnavailable:  # e.g. cold-tier DuckDB timeout: typed 503
                    return _problem(
                        503, "Service unavailable", "A kline storage tier is unavailable."
                    )
                got = list[KlineRowLike](read.rows)
                sources += [t for t in read.sources if t not in sources]
                recording_started = read.recording_started_at_us
            else:
                tr = TimeRange(start_us=slice_start, end_us=slice_end)
                got = list(await cache.read_klines(symbol, interval, tr, limit=limit + 1))
                if got and SOURCE_HOT not in sources:
                    sources.append(SOURCE_HOT)
            rows += [r for r in got if include_open or r.confirmed]
            slice_start, slices = slice_end, slices + 1
        more = len(rows) > limit or slice_start < end_us
        rows = rows[:limit]
        next_cursor: str | None = None
        if more:
            resume = rows[-1].ts_us + width if len(rows) == limit else slice_start
            if grid is not None:
                resume = -(-resume // grid) * grid  # round up onto the bar grid
            next_cursor = encode_cursor(cursor_scope("klines", symbol, interval), resume)
        rng = Range(start_us, slice_start)

        holes: list[dict[str, int]] = []
        if coverage_index_provider is not None:
            index = coverage_index_provider(symbol, interval)
            if isinstance(index, CoverageIndex):
                holes = [{"start_us": h.start_us, "end_us": h.end_us} for h in index.holes(rng)]
        served = sources if rows else []  # a tier is claimed only when its rows are served
        record_page("klines", len(rows), list(served))
        meta = build_meta(
            count=len(rows), next_cursor=next_cursor, sources=served,
            recording_started_at_us=recording_started, generated_at_us=now_us(),
            coverage_holes=holes,
        )  # fmt: skip
        return kline_response(
            symbol=symbol, interval=interval, bar_type="time",
            bars=[serialize_bar(r, include_delta=include_delta) for r in rows], meta=meta,
        )  # fmt: skip

    return router


__all__ = [
    "CoverageIndexProvider",
    "MarketDataCacheLike",
    "MarketDataPrincipal",
    "PrincipalResolver",
    "make_market_router",
]
