"""Fakes for the admin ops read-model tests (E42-T05): a probe registry with a settled health
snapshot, and the ops routes on the audited guard."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import FastAPI

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.ops.health import AdminHealthService, HealthSource
from candleviewer.api.admin_ops import make_admin_ops_router
from candleviewer.observability.health_probes import (
    CallableProbe,
    ComponentState,
    HealthRegistry,
    ProbeResult,
)
from tests.unit.admin._admin_fakes import AuditSpy, Resolver

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


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


def make_app(health: HealthSource | None = None) -> tuple[FastAPI, AuditSpy]:
    """The health route on the audited guard, with the actors, resolver and audit spy of the
    guard's own tests (`_admin_fakes`)."""
    spy = AuditSpy()
    report = AdminHealthService(health, version="1.2.3", git_sha="abc", environment="demo")
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(make_admin_ops_router(report, resolver=Resolver(), audit=spy))
    return app, spy
