"""`getRecordingStatus` (E16-T08, #492): `recording:read`, scope none, checked in order: session
(401), permission (403, audited `rbac.denied`), snapshot (503 before the first computation). Served
from the 1 Hz `RecordingStatusCache`, never computed per request: the Owner reads the full body,
everyone else the R-I2 view (ruling Q6)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.api import recording_common as common
from candleviewer.auth.generated_permissions import Permission
from candleviewer.recorder.status import RecordingStatusCache


def make_recording_status_router(
    cache: RecordingStatusCache, principal_resolver: common.Resolver | None, audit: common.Emitter
) -> APIRouter:
    router = APIRouter(tags=["recording"], route_class=common.ProblemRoute)

    @router.get("/recording/status")
    async def get_recording_status(request: Request) -> JSONResponse:
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_READ)
        if (body := cache.body(restricted=not p.is_owner)) is None:
            raise common.unavailable()
        return JSONResponse(body)

    return router
