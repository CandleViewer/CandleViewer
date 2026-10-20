"""Fixtures for cv-admin-route-guarded in a file with PEP 695 generics, which Semgrep parses
another way (#3549, X03-F4): the rule must hold here too (D10)."""

from fastapi import APIRouter

from candleviewer.admin.http import admin_router
from candleviewer.auth.generated_permissions import Permission


def first[T](items: list[T]) -> T:
    return items[0]


def make_audit_router() -> APIRouter:
    router = APIRouter(prefix="/admin/audit", tags=["admin"])

    @router.get("")  # ok: cv-admin-route-guarded
    async def query_audit_log[T](request: T) -> T:
        return request

    @router.post("/verify")  # ok: cv-admin-route-guarded
    async def verify_audit_chain() -> None: ...

    @router.post("/purge")  # ruleid: cv-admin-route-guarded
    async def purge[T](request: T) -> T:
        return request

    @router.post(path="/verify")  # ok: cv-admin-route-guarded
    async def verify_by_keyword() -> None: ...

    @router.post(path="/purge-by-keyword")  # ruleid: cv-admin-route-guarded
    async def purge_by_keyword[T](request: T) -> T:
        return request

    router.add_api_route("/purge-by-call", purge, methods=["POST"])  # ruleid: cv-admin-route-guarded

    return router


def make_guarded(resolver, audit) -> APIRouter:
    router = admin_router(Permission.BACKUPS_READ, resolver=resolver, audit=audit)  # ok: cv-admin-route-guarded
    admin_router(permission=resolver.permission, resolver=resolver, audit=audit)  # ruleid: cv-admin-route-guarded

    @router.get("/backups")  # ok: cv-admin-route-guarded
    async def list_backups[T](request: T) -> T:
        return request

    return router
