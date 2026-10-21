"""`GET /admin/backups/{backupId}/download/{token}` (E42-T05 #966 BK-11; contract `downloadBackup`,
`backups:read`, scope none): the token in the path is the credential, so no `Authorization` header
is needed. One that is sent must resolve to a usable session, else the standard `401` (an
idle-locked one meets `IdleLockMiddleware` first), and then names the only user whose token can
match. `backupId` and `token` are plain strings checked here, so a malformed one is a miss
(`404`), never a `422`, and no `Problem.detail` echoes the path. `501` while the fetch is not wired.

Then `BackupDownloads.fetch`, each refusal its registered problem (every `410` the contract's
`used` body), and the artefact streamed as an `attachment` named after the backup, never the
stored path. The stream is closed whether or not it starts; each read waits at most
`STREAM_READ_BUDGET_S`; a stream that stalls, is closed under a read (`ValueError`), fails to read
(`ArtefactUnreadable`) or ends with another byte count than the artefact's size is an aborted
download, logged as one: the response is cut, so no client takes a short or a changed file for
the backup. `NoStoreNoReferrer` wraps the whole app (`create_app`'s `_StampedApp`, outside every
middleware) and acts on this path alone: every answer gets `Cache-Control: no-store` and
`Referrer-Policy: no-referrer`, the route's, the routing's, each middleware's refusal and an
unhandled error's `500` included."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Final

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from candleviewer.admin.backups.downloads import (
    BackupDownloads,
    Fetch,
    Fetched,
    FetchLimited,
    LinkEnded,
    LinkForbidden,
    LinkMissed,
    LinkNotUsable,
    ServeRecord,
)
from candleviewer.admin.backups.limits import STREAM_READ_BUDGET_S
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import PrincipalResolver
from candleviewer.api.csrf import route_path, source_ip
from candleviewer.observability.context import current_request_uuid
from candleviewer.storage.backup_artefacts import ArtefactUnreadable
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_TOKEN: Final = re.compile(r"[A-Za-z0-9_-]{22,64}")  # the contract's pattern, checked here
_UUID: Final = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_PATH: Final = re.compile(r"/admin/backups/[^/]*/download/[^/]+/?")  # routed, redirected, or 404
_RETRY_S: Final = 5
#: Each refusal of the fetch, by class: its status, registered code and fixed detail.
_REFUSALS: Final[dict[type[AdminError], tuple[int, ErrorCode, str]]] = {
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED, "backups: the fetch is not wired"),
    LinkMissed: (404, ErrorCode.NOT_FOUND, "No such download link."),
    LinkEnded: (410, ErrorCode.GONE, "This download link has expired or was already used."),
    LinkForbidden: (403, ErrorCode.FORBIDDEN, "The link's user may not read backups."),
    LinkNotUsable: (409, ErrorCode.CONFLICT, "This backup cannot be downloaded."),
    FetchLimited: (429, ErrorCode.RATE_LIMITED, "Too many download requests; retry later."),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE, "backups: store unavailable"),
    OpsAuditUnavailable: (503, ErrorCode.AUDIT_UNAVAILABLE, "backups: record not written"),
}


class DownloadAborted(Exception):
    """The response is cut: the artefact stalled, was closed under a read, or changed size."""


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _problem(status: int, code: ErrorCode, detail: str, retry_s: int = _RETRY_S) -> JSONResponse:
    meta = ERROR_META[code]
    body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code.value}"}
    body |= {"title": meta.title, "status": status, "code": code.value, "detail": detail}
    headers: dict[str, str] = {}
    if meta.retryable:
        body["retry_after_seconds"], headers["Retry-After"] = retry_s, str(retry_s)
    if code is ErrorCode.CONFLICT:
        body["errors"] = [{"field": "", "rule": "backup_not_usable", "message": detail}]
    return JSONResponse(body, status, headers, "application/problem+json")


def _refusal(exc: AdminError) -> JSONResponse:
    status, code, detail = next(v for k, v in _REFUSALS.items() if isinstance(exc, k))
    wait = exc.retry_after_s if isinstance(exc, FetchLimited) else _RETRY_S
    return _problem(status, code, detail, wait)


class _ArtefactResponse(StreamingResponse):
    """The artefact, as an attachment: see the module docstring."""

    def __init__(self, fetched: Fetched) -> None:
        self._artefact = fetched.artefact
        name = f"cv-backup-{fetched.kind}-{fetched.backup_id}.age"
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}
        headers |= {"X-Content-Type-Options": "nosniff", "Content-Length": str(self._artefact.size)}
        super().__init__(self._chunks(), headers=headers, media_type="application/octet-stream")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._artefact.close()  # a stream never started, or cut: closed all the same

    async def _chunks(self) -> AsyncIterator[bytes]:
        sent, reads = 0, self._artefact.stream()
        try:
            while True:
                async with asyncio.timeout(STREAM_READ_BUDGET_S):
                    chunk = await anext(reads, None)
                if chunk is None:
                    break
                sent += len(chunk)
                yield chunk
        except (TimeoutError, ValueError, ArtefactUnreadable) as exc:  # stalled, closed, failed
            _log().warning("admin_backups.download_aborted", error=type(exc).__name__)
            raise DownloadAborted("backups: the download was aborted") from None
        if sent != self._artefact.size:  # the file changed since it was resolved
            _log().warning("admin_backups.download_aborted", error="size_changed")
            raise DownloadAborted("backups: the download was aborted")


class NoStoreNoReferrer:
    """Pure ASGI: `Cache-Control: no-store` and `Referrer-Policy: no-referrer` on every answer
    to the fetch's path, whatever answers it; any other path passes untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _PATH.fullmatch(route_path(scope["path"])):
            await self._app(scope, receive, send)
            return

        async def stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"], headers["Referrer-Policy"] = "no-store", "no-referrer"
            await send(message)

        await self._app(scope, receive, stamped)


def make_admin_backup_download_router(
    downloads: BackupDownloads | None, *, resolver: PrincipalResolver | None
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/backups/{backupId}/download/{token}")
    async def download_backup(
        request: Request, backup_id: Annotated[str, Path(alias="backupId")], token: str
    ) -> Response:
        if downloads is None:
            return _problem(501, ErrorCode.NOT_IMPLEMENTED, "backups: the fetch is not wired")
        bearer = None
        if "authorization" in request.headers:  # sent: it must resolve, and then it names a user
            bearer = None if resolver is None else await resolver.resolve(request)
            if bearer is None:
                return _problem(401, ErrorCode.UNAUTHENTICATED, "no verified session")
        backup = uuid.UUID(backup_id) if _UUID.fullmatch(backup_id) else None
        fetch_token = token if _TOKEN.fullmatch(token) else None
        # #3990: the id `CorrelationMiddleware` bound and the response echoes; no header is read
        ask = Fetch(backup, fetch_token, bearer, source_ip(request.scope), current_request_uuid())

        # Each record is the service's own `audit_serve`, called from the handler (SR-112's shape).
        async def write_ahead(record: ServeRecord) -> None:
            await downloads.audit_serve(record)

        try:
            return _ArtefactResponse(await downloads.fetch(ask, write_ahead))
        except tuple(_REFUSALS) as exc:
            return _refusal(exc)

    return router
