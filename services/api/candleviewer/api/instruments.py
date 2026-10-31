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
import math
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.api.market_bars import RecordingStart
from candleviewer.api.market_response import iso_us
from candleviewer.api.recorder_admin import AdminJobStore, Job
from candleviewer.api.step_up import RequestElevation, demand_elevation
from candleviewer.api.step_up_challenge import ChallengeText
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
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


# -- `POST /instruments/refresh` (`refreshInstruments`, E08-T10, #5111) -------------------------

REFRESH_PERMISSION: Final = "instruments:write"
REFRESH_JOB_KIND: Final = "instrument_refresh"
#: The step-up class `refreshInstruments` demands (22 `authStepUp`; 04 §7.2.2 row 5a, SR-025): a
#: grace class, registered in `api.step_up.HANDLER_GATED_ROUTES`.
REFRESH_STEP_UP_CLASS: Final = "instruments"
#: Q2: one accepted refresh per environment per this many seconds.
REFRESH_WINDOW_S: Final = 60.0
#: 22 "Idempotency": a key replays its `202` for 24 h; at most this many keys are kept (C-2.18).
IDEMPOTENCY_TTL_S: Final = 86_400.0
IDEMPOTENCY_MAX_KEYS: Final = 256
_LIVE = ("queued", "running")


class CatalogueRefresher(Protocol):
    """What the refresh route needs of `InstrumentsRefreshScheduler` (M6): never the adapter."""

    @property
    def stopped(self) -> bool: ...

    async def refresh_now(self) -> None: ...


class RefreshPrincipalResolver(Protocol):
    """The session-backed resolver the deployed app wires (#2561); the audit record needs the
    whole `AuditPrincipal`, not only `has`."""

    async def resolve(self, request: Request) -> AuditPrincipal | None: ...


class RefreshAudit(Protocol):
    async def emit(self, action: str, **kwargs: object) -> None: ...


#: `(tokens, wait_s)` of the venue budget the refresh's fetches draw (`MARKET_DATA`), read
#: without taking a token.
VenueHeadroom = Callable[[], tuple[float, float]]
#: Takes one token of `user`'s bucket: None when one was there, else whole seconds to wait.
UserBucket = Callable[[uuid.UUID], int | None]


def _coded(
    status: int, code: str, title: str, detail: str, retry_s: int | None = None
) -> JSONResponse:
    body: dict[str, object] = {
        "type": f"https://candleviewer.local/errors/{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
    }
    headers = None
    if retry_s is not None:
        body["retry_after_seconds"], headers = retry_s, {"Retry-After": str(retry_s)}
    return JSONResponse(body, status, headers=headers, media_type="application/problem+json")


def _whole_s(seconds: float) -> int:
    return max(1, math.ceil(seconds))


def refresh_instruments_text(environment: str) -> ChallengeText:
    """What the `instruments` challenge restates: a fixed template over the server's own
    environment, nothing from the client."""
    return ChallengeText(f"Refresh the {environment} instrument catalogue from Bybit")


def make_instruments_refresh_router(
    refresher_provider: Callable[[], CatalogueRefresher | None],
    jobs: AdminJobStore,
    *,
    audit: RefreshAudit | None,
    environment: str,
    principal_resolver: RefreshPrincipalResolver | None = None,
    venue_headroom: VenueHeadroom | None = None,
    user_bucket: UserBucket | None = None,
    elevation: RequestElevation | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:
    """`POST /instruments/refresh` (22 `refreshInstruments`): schedules one catalogue refresh as
    an `instrument_refresh` job in `jobs`, polled through `getJob`, and never awaits the fetch.
    RBAC is fail-closed as the reads' (501, 401, 403); CSRF is the edge middleware's (SR-041).
    After the scheduler's 503 and the key's shape, `elevation` demands the `instruments` step-up
    (none wired: 503, nothing runs; C-2.21), so a challenge goes only to a caller the route would
    otherwise admit. The order after it (22, Q1 and Q2 of #5111): the idempotency replay, the
    join of a job queued or running, the 60 s limit, the per-user bucket, the venue budget, then
    the write-ahead `instruments.refresh.requested` record (C-2.9), then the job. The accept path
    runs under one lock, so two requests never start two jobs."""
    router = APIRouter(tags=["instruments"])
    accept = asyncio.Lock()
    current: list[str | None] = [None]  # the last job this route started
    scheduled: dict[str, str] = {}  # job id -> its `scheduled_at`, while the store holds the job
    last_accepted: list[float | None] = [None]
    replays: OrderedDict[tuple[uuid.UUID, str], tuple[dict[str, str], float]] = OrderedDict()

    def remember(actor: uuid.UUID, key: str | None, body: dict[str, str]) -> None:
        if key is None:
            return
        replays[(actor, key)] = (body, monotonic())
        replays.move_to_end((actor, key))
        while len(replays) > IDEMPOTENCY_MAX_KEYS:
            replays.popitem(last=False)

    def replayed(actor: uuid.UUID, key: str) -> dict[str, str] | None:
        hit = replays.get((actor, key))
        if hit is None:
            return None
        if monotonic() - hit[1] >= IDEMPOTENCY_TTL_S:
            del replays[(actor, key)]
            return None
        return hit[0]

    def running() -> Job | None:
        job = jobs.get(current[0]) if current[0] is not None else None
        return job if job is not None and job.status in _LIVE else None

    async def record(
        sink: RefreshAudit, principal: AuditPrincipal, job_id: str, *, joined: bool
    ) -> bool:
        try:
            await sink.emit(
                "instruments.refresh.requested",
                actor_label=principal.actor_name,
                actor_user_id=principal.actor_id,
                actor_ip=principal.ip,
                session_id=principal.session_id,
                request_id=principal.request_id,
                object_kind=REFRESH_JOB_KIND,
                object_id=job_id,
                after_state={
                    "env": environment,
                    "role": "owner" if principal.is_owner else "user",
                    "joined": joined,
                },
            )
        except Exception as exc:
            _log().error("instruments_refresh_audit_failed", error=type(exc).__name__)
            return False
        return True

    def accepted(body: dict[str, str], *, replay: bool = False) -> JSONResponse:
        headers = {"Idempotency-Replayed": "true"} if replay else None
        return JSONResponse(status_code=202, content=body, headers=headers)

    def audit_unavailable() -> JSONResponse:
        return _coded(
            503,
            "audit_unavailable",
            "Audit unavailable",
            "The request could not be recorded; no refresh was started.",
        )

    @router.post("/instruments/refresh")
    async def refresh_instruments(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _coded(
                501, "not_implemented", "Not implemented", "No principal resolver is wired."
            )
        principal = await principal_resolver.resolve(request)
        if principal is None:
            return _coded(401, "unauthenticated", "Unauthorized", "No verified session.")
        if not principal.has(REFRESH_PERMISSION):
            return _coded(403, "forbidden", "Forbidden", f"Requires {REFRESH_PERMISSION}.")
        refresher = refresher_provider()
        if refresher is None or refresher.stopped or audit is None:
            return _coded(
                503,
                "instrument_cache_unavailable",
                "Service unavailable",
                "The instrument catalogue scheduler is not running.",
            )
        raw_key = request.headers.get("idempotency-key")
        key: str | None = None
        if raw_key is not None:
            try:
                key = str(uuid.UUID(raw_key))
            except ValueError:
                return _coded(
                    400, "validation_failed", "Bad request", "Idempotency-Key must be a UUID."
                )
        restated = refresh_instruments_text(environment)
        if (refused := await demand_elevation(elevation, request, restated)) is not None:
            return refused
        actor = principal.actor_id
        async with accept:
            if key is not None and (body := replayed(actor, key)) is not None:
                return accepted(body, replay=True)
            if (job := running()) is not None:  # Q1: join it; not counted by the limit (Q2)
                body = {"job_id": job.id, "scheduled_at": scheduled[job.id]}
                if not await record(audit, principal, job.id, joined=True):
                    return audit_unavailable()
                remember(actor, key, body)
                return accepted(body)
            now = monotonic()
            if last_accepted[0] is not None and now - last_accepted[0] < REFRESH_WINDOW_S:
                wait = _whole_s(REFRESH_WINDOW_S - (now - last_accepted[0]))
                return _coded(
                    429,
                    "rate_limited",
                    "Instrument refresh rate limited",
                    f"One refresh per {int(REFRESH_WINDOW_S)} s.",
                    wait,
                )
            if user_bucket is not None and (wait_user := user_bucket(actor)) is not None:
                return _coded(
                    429,
                    "rate_limited",
                    "Per-user API rate limit exceeded",
                    "Too many requests.",
                    _whole_s(wait_user),
                )
            if venue_headroom is not None:
                tokens, wait_s = venue_headroom()
                if tokens < 1.0:
                    return _coded(
                        429,
                        "exchange_rate_limited",
                        "The exchange's rate budget is exhausted",
                        "No market-data budget for a refresh now.",
                        _whole_s(wait_s),
                    )
            job_id = str(uuid.uuid4())
            # Write-ahead (C-2.9): recorded BEFORE the job exists; on failure nothing starts.
            if not await record(audit, principal, job_id, joined=False):
                return audit_unavailable()
            stamp = iso_us(int(wall_clock().timestamp() * 1_000_000))
            job = jobs.submit(
                REFRESH_JOB_KIND,
                (str(actor), key or f"none:{job_id}", ""),
                _work(refresher),
                _done(principal, audit, environment),
                job_id=job_id,
            )
            for stale in [j for j in scheduled if jobs.get(j) is None]:
                del scheduled[stale]
            scheduled[job.id], current[0], last_accepted[0] = stamp, job.id, now
            body = {"job_id": job.id, "scheduled_at": stamp}
            remember(actor, key, body)
            _log().info("instruments_refresh_scheduled", job_id=job.id)
            return accepted(body)

    return router


def _work(
    refresher: CatalogueRefresher,
) -> Callable[[Callable[[float], None]], Awaitable[dict[str, object]]]:
    async def work(_progress: Callable[[float], None]) -> dict[str, object]:
        # Serialised with every other refresh by the scheduler's lock; a spent retry budget
        # raises `InstrumentRefreshError` (catalogue kept, marked stale, counted).
        await refresher.refresh_now()
        return {}

    return work


def _done(
    principal: AuditPrincipal, audit: RefreshAudit, environment: str
) -> Callable[[Job], Awaitable[None]]:
    async def done(job: Job) -> None:
        """Q3: the job's end, `succeeded` or `failed` (a cancel runs no `on_done`)."""
        ok = job.status == "succeeded"
        try:
            await audit.emit(
                "instruments.refresh.completed",
                actor_label=principal.actor_name,
                actor_user_id=principal.actor_id,
                actor_ip=principal.ip,
                session_id=principal.session_id,
                request_id=principal.request_id,
                object_kind=REFRESH_JOB_KIND,
                object_id=job.id,
                outcome=AuditOutcome.SUCCESS if ok else AuditOutcome.FAILURE,
                severity=Severity.INFO if ok else Severity.ERROR,
                reason=None if ok else job.error,
                after_state={"env": environment, "status": job.status},
            )
        except Exception as exc:
            _log().error(
                "instruments_refresh_completed_audit_failed",
                job_id=job.id,
                error=type(exc).__name__,
            )

    return done


__all__ = [
    "REFRESH_STEP_UP_CLASS",
    "CatalogueReader",
    "CatalogueRefresher",
    "InstrumentsPrincipal",
    "PrincipalResolver",
    "make_instruments_refresh_router",
    "make_instruments_router",
    "serialize_instrument",
    "serialize_risk_limit_tier",
]
