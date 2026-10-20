"""Fixtures for cv-admin-route-guarded (E42-X03; C-12.4, SR-017, SR-E42-09): every /admin route
sits on `admin_router(Permission.<member>, ...)`. A route with a guard of its own is excepted in
the rule by its exact method and path, so a new route beside it still fails."""

from fastapi import APIRouter, FastAPI

from candleviewer.admin import http as admin_http
from candleviewer.admin.http import admin_router
from candleviewer.auth.generated_permissions import Permission


def make_guarded(resolver, audit) -> APIRouter:
    router = admin_router(Permission.ADMIN_READ, resolver=resolver, audit=audit)  # ok: cv-admin-route-guarded

    @router.get("/overview")  # ok: cv-admin-route-guarded
    async def overview() -> dict[str, str]:
        return {}

    return router


def make_prefixed() -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.post("/probe")  # ruleid: cv-admin-route-guarded
    async def probe() -> None: ...

    @router.get("/support-bundle/{job_id}")  # ok: cv-admin-route-guarded
    async def status(job_id: str) -> None: ...

    @router.delete("/support-bundle/{job_id}")  # ruleid: cv-admin-route-guarded
    async def forget(job_id: str) -> None: ...

    @router.post(path="/probe-by-keyword")  # ruleid: cv-admin-route-guarded
    async def probe_by_keyword() -> None: ...

    @router.put(response_model=None, path="/log-level")  # ok: cv-admin-route-guarded
    async def set_log_level() -> None: ...

    router.add_api_route("/probe-by-call", probe, methods=["POST"])  # ruleid: cv-admin-route-guarded
    router.add_api_route(endpoint=probe, path="/probe-by-keyword-call")  # ruleid: cv-admin-route-guarded
    router.add_route("/probe-starlette", probe, methods=["POST"])  # ruleid: cv-admin-route-guarded
    router.get("/probe-by-hand")(probe)  # ruleid: cv-admin-route-guarded
    router.include_router(APIRouter())  # ruleid: cv-admin-route-guarded

    return router


def make_audit_router() -> APIRouter:
    router = APIRouter(prefix="/admin/audit", tags=["admin"])

    @router.get("")  # ok: cv-admin-route-guarded
    async def query_audit_log() -> None: ...

    @router.delete("")  # ruleid: cv-admin-route-guarded
    async def wipe_audit_log() -> None: ...

    return router


def make_literal() -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.post("/admin/keys/kek-rewrap")  # ok: cv-admin-route-guarded
    async def rewrap_kek() -> None: ...

    @router.post("/admin/keys/rotate")  # ruleid: cv-admin-route-guarded
    async def rotate() -> None: ...

    @router.api_route("/admin", methods=["GET"])  # ruleid: cv-admin-route-guarded
    async def index() -> None: ...

    @router.get("/health/live")  # ok: cv-admin-route-guarded
    async def live() -> None: ...

    @router.get("/administrators")  # ok: cv-admin-route-guarded
    async def administrators() -> None: ...

    @router.post(path="/admin/keys/import")  # ruleid: cv-admin-route-guarded
    async def import_key() -> None: ...

    router.add_api_route("/admin/keys/export", rotate, methods=["POST"])  # ruleid: cv-admin-route-guarded
    router.add_api_websocket_route("/admin/stream", rotate)  # ruleid: cv-admin-route-guarded
    router.add_api_route("/health/ready", live, methods=["GET"])  # ok: cv-admin-route-guarded

    @router.websocket_route("/admin/feed")  # ruleid: cv-admin-route-guarded
    async def feed() -> None: ...

    return router


async def live_probe() -> None: ...


def mount(app: FastAPI, extra: APIRouter, resolver, audit, permission: Permission) -> None:
    app.include_router(extra, prefix="/admin")  # ruleid: cv-admin-route-guarded
    app.include_router(extra)  # ok: cv-admin-route-guarded
    app.include_router(admin_router(permission, resolver=resolver, audit=audit))  # ruleid: cv-admin-route-guarded
    app.include_router(admin_router(permission=permission, resolver=resolver, audit=audit))  # ruleid: cv-admin-route-guarded
    app.include_router(  # ok: cv-admin-route-guarded
        admin_router(permission=Permission.ADMIN_READ, resolver=resolver, audit=audit)
    )
    app.add_api_route("/admin/direct-call", live_probe)  # ruleid: cv-admin-route-guarded
    app.mount("/admin/files", extra)  # ruleid: cv-admin-route-guarded
    app.mount(path="/admin", app=extra)  # ruleid: cv-admin-route-guarded
    app.mount("/static", extra)  # ok: cv-admin-route-guarded
    admin_http.admin_router(permission, resolver=resolver, audit=audit)  # ruleid: cv-admin-route-guarded
    admin_http.admin_router(Permission.ADMIN_READ, resolver=resolver, audit=audit)  # ok: cv-admin-route-guarded

    @app.get("/admin/direct")  # ruleid: cv-admin-route-guarded
    async def direct() -> None: ...
