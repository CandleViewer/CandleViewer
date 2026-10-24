"""`listRecordedSymbols` and `getRecordedSymbol` (E16-T08, #492): `recording:read`, scope none,
checked in order: session (401), permission (403, audited), query (400), store (503). Unknown,
malformed and restricted-away ids are the same 404. Bodies hold logical fields, never a path."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.api import recording_common as common
from candleviewer.api.drawings_models import format_errors
from candleviewer.auth.generated_permissions import Permission
from candleviewer.recorder import control as rc
from candleviewer.ws._generated.error_codes import ErrorCode

BAD, MISSING = ErrorCode.VALIDATION_FAILED, ErrorCode.NOT_FOUND

#: Fields only a bound runtime knows: served once known, never guessed.
_RUNTIME: Final = ("lingering", "linger_until", "refusal", "disk_bytes", "rows_last_hour", "lag_ms")


class _ListQuery(BaseModel):  # unknown parameters are ignored, as FastAPI's own are
    model_config = ConfigDict(frozen=True, extra="ignore")
    cursor: Annotated[str, Field(max_length=512)] | None = None
    limit: Annotated[int, Field(ge=1, le=500)] = 100
    state: rc.RecordingState | None = None
    reason: rc.RecordReason | None = None
    pinned: bool | None = None


def _dump(e: rc.RecordedEntry) -> dict[str, Any]:
    body = {"id": e.id, "symbol": e.symbol, "reason": e.reason, "pinned": e.pinned,
            "state": e.state, "streams": list(e.streams), "depth": e.depth,
            "started_at": common.iso_z(e.started_at), "retention_days": e.retention_days,
            "added_by": e.added_by}  # fmt: skip
    return body | {k: common.iso_z(v) for k in _RUNTIME if (v := getattr(e, k)) is not None}


def make_recording_symbols_router(
    control: Callable[[], rc.RecordingReads | None],
    principal_resolver: common.Resolver | None,
    audit: common.Emitter,
    *,
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    """`control` reads the recorded set: `None` until its store exists (503)."""
    router = APIRouter(tags=["recording"], route_class=common.ProblemRoute)

    def bound() -> rc.RecordingReads:
        if (found := control()) is None:
            raise common.unavailable()
        return found

    @router.get("/recording/symbols")
    async def list_recorded_symbols(request: Request) -> JSONResponse:
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_READ)
        try:
            q = _ListQuery.model_validate(dict(request.query_params))
        except ValidationError as exc:  # bounded, input-free field errors
            raise common.Problem(400, BAD, "Invalid query.", errors=format_errors(exc)) from None
        restricted, now = not p.is_owner, int(clock())
        scope = f"{q.state}|{q.reason}|{q.pinned}|{restricted}"
        after = None if q.cursor is None else common.decode_cursor(q.cursor, scope, now)
        hidden = rc.HIDDEN_CAUSES if restricted else frozenset()
        query = rc.EntryQuery(q.state, q.reason, q.pinned, hidden, after, q.limit)
        page = await bound().list(query)
        shown = [v for e in page.items if (v := rc.restricted_view(e) if restricted else e)]
        last = page.items[-1] if page.has_more else None
        nxt = None if last is None else common.encode_cursor(scope, (last.symbol, last.id), now)
        meta = {"next_cursor": nxt, "has_more": page.has_more, "count": len(shown)}
        items = [_dump(e) for e in shown]
        return JSONResponse({"items": items, "meta": meta, "role_restricted": restricted})

    @router.get("/recording/symbols/{recordedSymbolId}")
    async def get_recorded_symbol(
        request: Request, entry_id: Annotated[str, Path(alias="recordedSymbolId")]
    ) -> JSONResponse:
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_READ)
        try:
            uid = str(UUID(entry_id))
        except ValueError:  # not a uuid: it names no entry
            raise common.Problem(404, MISSING, "No such recorded symbol.") from None
        entry = await bound().get(uid)
        if entry is not None and not p.is_owner:
            entry = rc.restricted_view(entry)
        if entry is None:
            raise common.Problem(404, MISSING, "No such recorded symbol.")
        return JSONResponse(_dump(entry))

    return router
