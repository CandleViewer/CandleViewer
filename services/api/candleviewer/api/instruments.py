"""`GET /instruments`, `GET /instruments/{symbol}` (`docs/plan/22-api-openapi.yaml`,
contract PR #1631; E08-S01-2).

Thin HTTP adapter over the ingestion refresh scheduler's in-memory
`CatalogueSnapshot`: every read is served from the current snapshot (one
attribute read, no I/O, never awaits the upstream fetch — ticket "Refresh
does not stall readers"). The only upstream-touching path is the on-demand
refresh for an *unknown* symbol on the detail route ("Refresh without
restart"), which is serialised by the scheduler's own lock and bounded by its
deadline: past it the route answers 503 while the refresh runs on (#2702).

RBAC (C-12.4): `x-rbac: {permissions: [instruments:read]}` — enforced here,
fail-closed, mirroring `api/market.py` exactly: no resolver wired -> 501, no
session -> 401, missing permission -> 403.

Neutral -> wire mapping: domain status `trading` -> contract `Trading` etc.;
`delisted` is derived (`status` not in {Trading, PreLaunch}) per the schema.

S-RL (#913): the detail route serves `risk_limit_tiers` from the snapshot (`ensure_risk_limits`:
fetched on first demand, bounded by the scheduler's deadline, then refreshed with the
catalogue), renamed to 22's `tier`/`initial_margin`/`maintenance_margin`; tiers that are not
known (a failed or late fetch, or the restart window) are served as `[]`, never guessed.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.api.market_bars import RecordingStart
from candleviewer.api.market_response import iso_us
from candleviewer.domain.events import Instrument
from candleviewer.exchange.base.models import RiskLimitTier
from candleviewer.ingestion.instruments import CatalogueSnapshot, utc_now_us
from candleviewer.ingestion.instruments_refresh import InstrumentRefreshPendingError

_REQUIRED_PERMISSION = "instruments:read"

_STATUS_WIRE = {
    "pre_launch": "PreLaunch",
    "trading": "Trading",
    "delivering": "Delivering",
    "closed": "Closed",
}
_STATUS_REASON = {
    "pre_launch": "Pre-launch: not yet open for trading.",
    "trading": None,
    "delivering": "Delivering: contract is settling; new orders are disabled.",
    "closed": "Delisted: trading closed on the exchange; order entry is disabled.",
}
_LISTED = frozenset({"trading", "pre_launch"})
#: How long the detail read waits for the recording start before serving it as unknown.
RECORDING_TIMEOUT_S: Final = 2.0


class _Unknown:
    """The recording start is unknown (no store wired, or it failed): `recorded` is omitted."""


_UNKNOWN = _Unknown()


def _log() -> Any:
    """Resolved per call, never bound at import (`cv-module-level-structlog-logger`)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class InstrumentsPrincipal:
    user_id: str
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions  # nosem: no-adhoc-authz reason=Principal.has_permission-wildcard-impl-pending-E09-T01-authorize owner=@CandleViewer/security review=2026-12-31  # noqa: E501  # fmt: skip


class _Principal(Protocol):
    """What the routes need of a caller: `InstrumentsPrincipal`, or the session-backed
    resolver's `AuditPrincipal` in the deployed app (#2561)."""

    def has(self, permission: str) -> bool: ...


class PrincipalResolver(Protocol):
    """Sync or async resolver (`resolve(request)` may return an awaitable), as in `ticker.py`;
    the deployed app wires the session-backed one (#2561)."""

    def resolve(self, request: Request) -> _Principal | Awaitable[_Principal | None] | None: ...


class CatalogueReader(Protocol):
    """Structural type for `InstrumentsRefreshScheduler` (M6). `ensure_symbol` raises
    `InstrumentRefreshPendingError` when its refresh misses the deadline (#2702)."""

    def snapshot(self) -> CatalogueSnapshot | None: ...

    async def ensure_symbol(self, symbol: str) -> Instrument | None: ...

    async def ensure_risk_limits(self, symbol: str) -> tuple[RiskLimitTier, ...] | None: ...


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "about:blank", "title": title, "status": status_code, "detail": detail},
        media_type="application/problem+json",
    )


def _iso(us: int | None) -> str | None:
    if us is None:
        return None
    return datetime.fromtimestamp(us / 1_000_000, tz=UTC).isoformat().replace("+00:00", "Z")


def serialize_risk_limit_tier(t: RiskLimitTier) -> dict[str, object]:
    """22's `InstrumentDetail.risk_limit_tiers[]` item (decimals as strings, C6). Fixed-point
    `format(d, "f")`, never `str(d)`, which can answer exponent form (`1E+2`) outside 22's
    Decimal pattern."""
    return {
        "tier": t.tier_id,
        "risk_limit_value": format(t.risk_limit_value, "f"),
        "initial_margin": format(t.initial_margin_rate, "f"),
        "maintenance_margin": format(t.maintenance_margin_rate, "f"),
        "max_leverage": format(t.max_leverage, "f"),
    }


def serialize_instrument(i: Instrument) -> dict[str, object]:
    return {
        "symbol": i.symbol,
        "category": "linear",
        "base_coin": i.base_coin,
        "quote_coin": i.quote_coin,
        "settle_coin": i.settle_coin,
        "contract_type": "LinearPerpetual",
        "status": _STATUS_WIRE[i.status],
        "tick_size": str(i.tick_size),
        "price_scale": i.price_scale,
        "qty_step": str(i.qty_step),
        "min_order_qty": str(i.min_order_qty),
        "max_order_qty": str(i.max_order_qty),
        "min_notional_value": str(i.min_notional),
        "max_leverage": str(i.max_leverage),
        "leverage_step": str(i.leverage_step),
        "funding_interval_minutes": i.funding_interval_min,
        "launch_time": _iso(i.launch_time),
        "copy_trading": i.copy_trading,
        "revision": i.metadata_version,
        "updated_at": _iso(i.fetched_at),
        "delisted": i.status not in _LISTED,
        "status_reason": _STATUS_REASON[i.status],
    }


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        text = base64.urlsafe_b64decode(padded.encode()).decode()
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("malformed cursor") from exc
    if not text.startswith("o:") or not text[2:].isdigit():
        raise ValueError("malformed cursor")
    return int(text[2:])


def make_instruments_router(
    catalogue_provider: Callable[[], CatalogueReader | None],
    *,
    principal_resolver: PrincipalResolver | None = None,
    now_us: Callable[[], int] = utc_now_us,
    recording_started_at_us: RecordingStart | None = None,
    recording_timeout_s: float = RECORDING_TIMEOUT_S,
) -> APIRouter:
    """Bind the instruments read routes. `catalogue_provider` is called per
    request (the scheduler is created at supervisor start, after
    `create_app()`); `None` -> `503`, never an empty catalogue."""
    router = APIRouter(tags=["instruments"])

    async def _recording_start(symbol: str) -> int | _Unknown | None:
        """The earliest recorded data for `symbol`, None when nothing is recorded, or `_UNKNOWN`
        when no store is wired or it fails or is slow: the instrument read never breaks on it,
        and an unknown is never served as "not recorded"."""
        if recording_started_at_us is None:
            return _UNKNOWN
        try:
            async with asyncio.timeout(recording_timeout_s):
                return await recording_started_at_us(symbol)
        except Exception:
            _log().warning("instrument_recording_start_unavailable", symbol=symbol, exc_info=True)
            return _UNKNOWN

    async def _authorize(request: Request) -> JSONResponse | None:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        resolved = principal_resolver.resolve(request)
        principal = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(_REQUIRED_PERMISSION):
            return _problem(403, "Forbidden", f"requires {_REQUIRED_PERMISSION}")
        return None

    def _snapshot() -> CatalogueSnapshot | None:
        reader = catalogue_provider()
        return reader.snapshot() if reader is not None else None

    @router.get("/instruments")
    async def list_instruments(
        request: Request,
        cursor: str | None = Query(default=None, max_length=512),
        limit: int = Query(default=100, ge=1, le=500),
        q: str | None = Query(default=None, max_length=32),
        status: str | None = Query(default=None),
        recorded_only: bool = Query(default=False),
        sort: str = Query(default="symbol"),
    ) -> JSONResponse:
        denied = await _authorize(request)
        if denied is not None:
            return denied
        if status is not None and status not in _STATUS_WIRE.values():
            return _problem(400, "Bad request", f"unsupported status {status!r}")
        if sort != "symbol":
            return _problem(400, "Bad request", f"sort {sort!r} is not available yet")
        if recorded_only:
            return _problem(400, "Bad request", "recorded_only is not available yet")
        try:
            offset = _decode_cursor(cursor) if cursor else 0
        except ValueError:
            return _problem(400, "Bad request", "malformed cursor")
        snap = _snapshot()
        if snap is None:
            return _problem(503, "Service unavailable", "instrument catalogue not loaded yet")

        if status is not None:
            rows = [i for i in snap.by_symbol.values() if _STATUS_WIRE[i.status] == status]
        else:
            rows = list(snap.listing())
        if q:
            needle = q.upper()
            rows = [i for i in rows if needle in i.symbol or needle in i.base_coin.upper()]
        rows.sort(key=lambda i: i.symbol)
        page = rows[offset : offset + limit]
        has_more = offset + limit < len(rows)
        body = {
            "items": [serialize_instrument(i) for i in page],
            "meta": {
                "next_cursor": _encode_cursor(offset + limit) if has_more else None,
                "has_more": has_more,
                "count": len(page),
                "cache_age_s": round(snap.age_seconds(now_us=now_us()), 3),
                "stale_since": _iso(snap.stale_since_us),
            },
        }
        return JSONResponse(status_code=200, content=body)

    @router.get("/instruments/{symbol}")
    async def get_instrument(request: Request, symbol: str) -> JSONResponse:
        denied = await _authorize(request)
        if denied is not None:
            return denied
        if not (4 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum()):
            return _problem(400, "Bad request", "invalid symbol")
        symbol = symbol.upper()
        reader = catalogue_provider()
        if reader is None:
            return _problem(503, "Service unavailable", "instrument catalogue not loaded yet")
        snap = reader.snapshot()
        instrument = snap.get(symbol) if snap is not None else None
        if instrument is None:
            # "Refresh without restart": an unknown symbol triggers one (throttled) refresh,
            # also before any catalogue loaded (#2599: a failed cold start).
            try:
                instrument = await reader.ensure_symbol(symbol)
            except InstrumentRefreshPendingError:  # #2702: past the deadline; it runs on
                return _problem(503, "Service unavailable", "instrument catalogue not loaded yet")
            snap = reader.snapshot() or snap
        if snap is None:  # still nothing loaded: never a false 404 for a real symbol
            return _problem(503, "Service unavailable", "instrument catalogue not loaded yet")
        if instrument is None:
            return _problem(404, "Not found", f"unknown instrument {symbol}")
        tiers = await reader.ensure_risk_limits(symbol)
        started = await _recording_start(symbol)
        body = serialize_instrument(instrument)
        body.update(
            {
                "risk_limit_tiers": [serialize_risk_limit_tier(t) for t in tiers or ()],
                "recording_started_at": iso_us(started) if isinstance(started, int) else None,
                "stale_since": _iso(snap.stale_since_us),
            }
        )
        if not isinstance(started, _Unknown):  # `recorded` is optional: omitted while unknown
            body["recorded"] = started is not None
        return JSONResponse(status_code=200, content=body)

    return router


__all__ = [
    "CatalogueReader",
    "InstrumentsPrincipal",
    "PrincipalResolver",
    "make_instruments_router",
    "serialize_instrument",
    "serialize_risk_limit_tier",
]
