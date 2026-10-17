"""Fakes for the admin ops read-model tests (E42-T05): incident rows and an in-memory store that
keeps the Postgres reader's keyset contract, a probe registry with a settled health snapshot, and
the ops routes on the audited guard."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.ops.health import AdminHealthService, HealthSource
from candleviewer.admin.ops.incidents import AdminIncidentsService
from candleviewer.api.admin_ops import make_admin_ops_router
from candleviewer.api.error_redaction import validation_error_handler
from candleviewer.observability.health_probes import (
    CallableProbe,
    ComponentState,
    HealthRegistry,
    ProbeResult,
)
from candleviewer.storage.repositories.incidents import IncidentRow, Position
from tests.unit.admin._admin_fakes import AuditSpy, Resolver

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def row(n: int, **over: Any) -> IncidentRow:
    """Incident `n`, newest first as `n` falls; every field set, so a dropped one is seen."""
    fields: dict[str, Any] = {
        "id": UUID(int=n),
        "component": "recorder",
        "signature": f"{n:016x}",
        "severity": "error",
        "status": "open",
        "title": "parquet write failed for <symbol> segment <n>",
        "detail": f"parquet write failed for BTCUSDT segment {n}",
        "occurrences": n,
        "first_seen_at": NOW - timedelta(hours=2),
        "last_seen_at": NOW - timedelta(minutes=n),
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "runbook_ref": None,
    }
    return IncidentRow(**(fields | over))


class Store:
    """The `IncidentStore` contract in memory: status filter, strictly after the keyset position,
    `last_seen_at` then `id` descending, `limit` rows. Records every call."""

    def __init__(
        self,
        rows: Sequence[IncidentRow] = (),
        *,
        error: Exception | None = None,
        hang: bool = False,
    ) -> None:
        self.rows, self.error, self.hang = list(rows), error, hang
        self.calls: list[tuple[str | None, Position | None, int]] = []

    async def page(
        self, *, status: str | None, after: Position | None, limit: int
    ) -> list[IncidentRow]:
        self.calls.append((status, after, limit))
        if self.hang:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        wanted = [r for r in self.rows if status in (None, r.status)]
        wanted.sort(key=lambda r: (r.last_seen_at, r.id), reverse=True)
        return [r for r in wanted if after is None or (r.last_seen_at, r.id) < after][:limit]


async def settled_registry() -> HealthRegistry:
    """One refresh over a healthy probe, a hanging one (`probe timeout`) and the placeholders."""

    async def ok() -> ProbeResult:
        return ProbeResult(ComponentState.HEALTHY, "pool 4/20")

    async def hang() -> ProbeResult:
        await asyncio.Event().wait()
        return ProbeResult(ComponentState.HEALTHY)

    registry = HealthRegistry(probe_deadline_s=0.01, clock=lambda: NOW)
    registry.register(CallableProbe("postgres", ok))
    registry.register(CallableProbe("parquet_store", hang, timeout=10))
    registry.register(CallableProbe("made_up_probe", ok))  # a component no client knows
    registry.register_placeholders()
    await registry.refresh()
    return registry


def make_app(
    health: HealthSource | None = None, store: Store | None = None
) -> tuple[FastAPI, AuditSpy]:
    """The ops routes on the audited guard, with the actors, resolver and audit spy of the
    guard's own tests (`_admin_fakes`) and the app's own refusal of an invalid query."""
    spy = AuditSpy()
    report = AdminHealthService(health, version="1.2.3", git_sha="abc", environment="demo")
    incidents = AdminIncidentsService(store, now=lambda: NOW)
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # as create_app
    app.include_router(make_admin_ops_router(report, incidents, resolver=Resolver(), audit=spy))
    return app, spy
