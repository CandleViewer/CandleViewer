"""`listRecordingSessions` and `getStorageUsage` (E16-T08, #492): `recording:read`, scope none,
checked in order: session (401), permission (403, audited), query (400), store (503).

Sessions page newest first, held to the settings' env (C-2.11). Storage is the disk budget's last
`report()`, never measured per request (SCR-142): 503 before its first sample, or with no budget
(the fake backend). Everyone but the Owner reads the R-I2 view (ruling Q6): no session of a row,
and no storage symbol, held only by a hidden cause. Bodies hold logical fields, never a path."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from candleviewer.api import recording_common as common
from candleviewer.api.drawings_models import format_errors
from candleviewer.api.recording_symbols import _z
from candleviewer.auth.generated_permissions import Permission
from candleviewer.recorder import control as rc
from candleviewer.recorder.models import StorageUsage
from candleviewer.ws._generated.error_codes import ErrorCode

#: The recorded set a non-Owner storage view is filtered by is read in one page; a longer set
#: than this fails closed (503) rather than guessing.
_SET_PAGE = 500


class SessionRows(Protocol):  # the reads repository's session page (M10 rows)
    async def sessions_page(
        self, *, env: str, symbol: str | None, since: datetime | None, until: datetime | None,
        hidden: tuple[str, ...], after: tuple[datetime, str] | None, limit: int,
    ) -> list[dict[str, Any]]: ...  # fmt: skip


class StorageReport(Protocol):  # `DiskBudget`
    def report(self) -> StorageUsage | None: ...


class _SessionQuery(BaseModel):  # unknown parameters are ignored, as FastAPI's own are
    model_config = ConfigDict(frozen=True, extra="ignore")
    cursor: Annotated[str, Field(max_length=512)] | None = None
    limit: Annotated[int, Field(ge=1, le=500)] = 100
    symbol: Annotated[str, Field(pattern=r"^[A-Z0-9]{2,20}USDT$")] | None = None
    since: AwareDatetime | None = Field(default=None, alias="from")
    until: AwareDatetime | None = Field(default=None, alias="to")


def _session(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "recorded_symbol_id": row["recorded_symbol_id"],
            "symbol": row["symbol"], "state": row["state"], "started_at": _z(row["started_at"]),
            "ended_at": _z(row["ended_at"]), "streams": list(row["streams"]),
            "depth": row["depth"], "rows": row["messages_received"],
            "bytes": row["bytes_written"], "gap_count": row["gap_count"]}  # fmt: skip


async def _hidden_symbols(reads: rc.RecordingReads) -> frozenset[str] | None:
    """The symbols the restricted view leaves out of the recorded set; `None` if unsure."""
    page = await reads.list(rc.EntryQuery(limit=_SET_PAGE))
    if page.has_more:
        return None
    return frozenset(e.symbol for e in page.items if rc.restricted_view(e) is None)


def make_recording_reports_router(
    control: Callable[[], rc.RecordingReads | None],
    sessions: Callable[[], SessionRows | None],
    budget: Callable[[], StorageReport | None],
    env: str,
    principal_resolver: common.Resolver | None,
    audit: common.Emitter,
    *,
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    """Each port is `None` until its store exists (503); `env` is the settings' environment."""
    router = APIRouter(tags=["recording"], route_class=common.ProblemRoute)

    @router.get("/recording/sessions")
    async def list_recording_sessions(request: Request) -> JSONResponse:
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_READ)
        try:
            q = _SessionQuery.model_validate(dict(request.query_params))
        except ValidationError as exc:  # bounded, input-free field errors
            bad = ErrorCode.VALIDATION_FAILED
            raise common.Problem(400, bad, "Invalid query.", errors=format_errors(exc)) from None
        restricted, now = not p.is_owner, int(clock())
        scope = f"{q.symbol}|{q.since}|{q.until}|{restricted}"
        after = None
        if q.cursor is not None:
            key, last = common.decode_cursor(q.cursor, scope, now)
            try:
                after = (datetime.fromisoformat(key), last)
            except ValueError:
                raise common.Problem(400, ErrorCode.INVALID_CURSOR, "Invalid cursor.") from None
        if (rows := sessions()) is None:
            raise common.unavailable()
        hidden = tuple(sorted(rc.HIDDEN_CAUSES)) if restricted else ()
        page = await rows.sessions_page(env=env, symbol=q.symbol, since=q.since, until=q.until,
                                        hidden=hidden, after=after, limit=q.limit + 1)  # fmt: skip
        items, more = page[: q.limit], len(page) > q.limit
        last_row = items[-1] if more else None
        nxt = None if last_row is None else common.encode_cursor(
            scope, (last_row["started_at"].isoformat(), last_row["id"]), now)  # fmt: skip
        meta = {"next_cursor": nxt, "has_more": more, "count": len(items)}
        return JSONResponse({"items": [_session(r) for r in items], "meta": meta})

    @router.get("/recording/storage")
    async def get_storage_usage(request: Request) -> JSONResponse:
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_READ)
        found = budget()
        if found is None or (usage := found.report()) is None:
            raise common.Problem(503, ErrorCode.STORE_UNAVAILABLE, "No storage sample yet.")
        body = usage.model_dump(mode="json")
        if not p.is_owner:
            reads = control()
            hidden = None if reads is None else await _hidden_symbols(reads)
            if hidden is None:
                raise common.unavailable()
            body["symbols"] = [s for s in body["symbols"] if s["symbol"] not in hidden]
        return JSONResponse(body)

    return router
