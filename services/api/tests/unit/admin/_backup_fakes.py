"""Backup catalogue test fakes (E42-T05 #966 BK-4): rows, a keyset store, the guarded app."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_backups import make_admin_backups_router
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.repositories.backups import BackupRow, Position
from tests.unit.admin._admin_fakes import AuditSpy, expected_record, principal

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


def row(n: int, **over: Any) -> BackupRow:
    """Backup `n`, newer as `n` falls; every field set and distinct, so a dropped one is seen."""
    started = NOW - timedelta(hours=n)
    fields: dict[str, Any] = {
        "id": UUID(int=n), "kind": "pg_dump", "status": "verified",
        "target_path": f"/backups/pg/{n}.dump.age", "size_bytes": 1000 + n,
        "checksum_sha256": f"{n:064x}", "encrypted": True, "covers_to": started,
        "verified_at": started + timedelta(minutes=9), "error_message": None,
        "triggered_by": "schedule", "started_at": started,
        "finished_at": started + timedelta(minutes=4),
        "retention_until": NOW + timedelta(days=90), "deleted_at": None,
    }  # fmt: skip
    return BackupRow(**(fields | over))


class Store:
    """The two reads in memory, BK-3's keyset contract included; records every call."""

    def __init__(
        self, rows: Sequence[BackupRow] = (), *, error: Exception | None = None, hang: bool = False
    ) -> None:
        self.rows, self.error, self.hang = list(rows), error, hang
        self.calls: list[tuple[Any, ...]] = []

    async def _called(self, *call: Any) -> None:
        self.calls.append(call)
        if self.hang:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error

    async def page(
        self, kind: str | None, status: str | None, after: Position | None, limit: int
    ) -> list[BackupRow]:
        await self._called("page", kind, status, after, limit)
        rows = [r for r in self.rows if kind in (None, r.kind) and status in (None, r.status)]
        rows.sort(key=lambda r: (r.started_at, r.id), reverse=True)
        return [r for r in rows if after is None or (r.started_at, r.id) < after][:limit]

    async def get(self, backup_id: UUID) -> BackupRow | None:
        await self._called("get", backup_id)
        return next((r for r in self.rows if r.id == backup_id), None)


class Resolver:
    """`x-role` names an `_admin_fakes` actor; any other value is an unauthenticated caller."""

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        role = request.headers.get("x-role", "")
        if role not in ("owner", "manager", "viewer"):
            return None
        who = principal(role)  # the manager holds account grants, the viewer `audit:read`
        granted = who.permissions | {"backups:read"}
        return replace(who, permissions=granted) if role == "owner" else who


def area_record(role: str, route: str) -> dict[str, Any]:
    """The guard's record: allowed for the owner, else denied `missing_permission:backups:read`."""
    permission = Permission.ADMIN_READ if role == "owner" else Permission.BACKUPS_READ
    return expected_record(role, route, permission)


def make_app(store: Store | None) -> tuple[FastAPI, AuditSpy]:
    spy = AuditSpy()
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    install_error_redaction(app)  # the 422 and the redacted 500, as create_app
    catalogue = BackupCatalogue(store, now=lambda: NOW)
    app.include_router(make_admin_backups_router(catalogue, resolver=Resolver(), audit=spy))
    return app, spy
