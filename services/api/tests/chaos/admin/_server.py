"""The admin chaos composition (E42-Q03, #1216): the shipped admin routers and services, in process.

[BQ-4] The plan's subprocess `create_app` is replaced by the routers and services that `create_app`
mounts, built here over the real Postgres through `_relay.Relay`, and served through
`httpx.ASGITransport`: every store is the shipped one, every limiter and budget at its default,
so the build under test differs from production only by the injected fault. Three stand-ins, each
for a port no relay can aim at, and each reachable only from this test package (no setting
selects one): the principal resolver (a fixed Owner: the faults are datastore faults, and the
sign-in path has its own suites), a health source with no snapshot (scenario 1's `503`) and a
recorder port that never answers (scenario 3; the real recorder slice is always `unavailable` on
main, `tests/fixtures/admin/README.md`).

Audit rows are permanent (C-5.7): `require_test_database` refuses any DSN that is not loopback and
a database named `test` or `*_test`, or that carries query parameters, before anything connects.
"""

from __future__ import annotations

import asyncio
import math
import socket
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request
from prometheus_client import REGISTRY

from candleviewer.admin.flags.policy import StepUpClass
from candleviewer.admin.flags.push import Session
from candleviewer.admin.flags.store import FlagWrite
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.overview.ports import RecorderStatus, StorageSnapshot
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AuditWriter
from candleviewer.flags_wiring import FeatureFlagsRuntime
from candleviewer.observability.audit_query_metrics import (
    cv_audit_break_halt_state,
    cv_audit_chain_verified_state,
)
from candleviewer.observability.health_probes import HealthSnapshot
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.admin._relay import dsn_url

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
#: What `GET /admin/health` reports of the build: fixed, so the generated model validates.
BUILD_VERSION = "0.0.0"
BUILD_SHA = "0" * 40


class HarnessRefused(RuntimeError):
    """The harness will not run against this target."""


def require_test_database(dsn: str) -> None:
    """Loopback only, and a database named `test` or `*_test`, read by `_relay.dsn_url` (no
    query parameters); the message never echoes the DSN (it carries a password)."""
    try:
        url = dsn_url(dsn)
    except ValueError as refused:
        raise HarnessRefused(str(refused)) from None
    if url.host not in LOOPBACK:
        raise HarnessRefused("the admin chaos harness runs against a loopback Postgres only")
    name = url.database or ""
    if name != "test" and not name.endswith("_test"):
        raise HarnessRefused("the admin chaos harness opens only a database named for tests")


def owner_principal(user_id: uuid.UUID) -> AuditPrincipal:
    return AuditPrincipal(
        user_id,
        "chaos-owner",
        frozenset({"*"}),
        session_id=uuid.uuid4(),
        ip="127.0.0.1",
        is_owner=True,
    )


class FixedPrincipal:
    """The principal resolver stand-in: every request is `principal`."""

    def __init__(self, principal: AuditPrincipal) -> None:
        self.principal = principal

    async def resolve(self, _request: Request) -> AuditPrincipal | None:
        return self.principal


class NoSnapshot:
    """A health source before its first probe: `GET /admin/health` is `503`."""

    def snapshot(self) -> HealthSnapshot | None:
        return None


class HungRecorder:
    """The recorder port stand-in: neither read ever answers; the slice budget ends both."""

    async def recorder_status(self) -> RecorderStatus:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def storage_snapshot(self) -> StorageSnapshot | None:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def relational(dsn: str, name: str) -> SqlAlchemyRelationalRepository:
    require_test_database(dsn)
    return SqlAlchemyRelationalRepository(dsn, name)


def closed_port() -> int:
    """A loopback port nothing listens on (the QuestDB probe's target: down throughout)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def audit_module(dsn: str, wal_dir: Path) -> AsyncIterator[AuditService]:
    """The real audit module (writer, WAL, query service) on `dsn`, as the Q01 integration
    tests start it. The process-wide chain and halt gauges are put back as found."""
    repo = relational(dsn, "audit")
    service = AuditService(SqlAlchemyAuditRepository(repo))
    settings = SimpleNamespace(audit_wal_path=str(wal_dir / "a.wal"))
    settings.audit_page_structure_budget = 50_000
    kept = {
        gauge: REGISTRY.get_sample_value(name)
        for gauge, name in (
            (cv_audit_chain_verified_state, "cv_audit_chain_verified_state"),
            (cv_audit_break_halt_state, "cv_audit_break_halt_state"),
        )
    }
    ctx: Any = SimpleNamespace(settings=settings)
    try:
        await service.start(ctx)
        yield service
    finally:
        await service.stop(10)
        await repo.dispose()
        for gauge, value in kept.items():
            gauge.set(math.nan if value is None else value)


async def _no_step_up(
    _who: AuditPrincipal, _cls: StepUpClass, _write: FlagWrite, _fingerprint: str | None
) -> None:
    raise AssertionError("no flag is written in these scenarios")


class _NoUsers:
    async def unknown(self, user_ids: frozenset[uuid.UUID]) -> frozenset[uuid.UUID]:
        return frozenset()


class _NoSessions:
    def authenticated(self) -> Iterable[Session]:
        return ()


@asynccontextmanager
async def flags_runtime(dsn: str, audit: AuditWriter) -> AsyncIterator[FeatureFlagsRuntime]:
    """The shipped flag runtime (`flags_wiring.FeatureFlagsRuntime`) on `dsn`, its rows ensured.
    No write runs here: the step-up, user and session ports are inert."""
    repo = relational(dsn, "feature-flags")
    runtime = FeatureFlagsRuntime(
        repo,
        environment="testnet",
        audit=audit,
        step_up=_no_step_up,
        users=_NoUsers(),
        sessions=_NoSessions(),
    )
    try:
        await runtime.service.start()
        yield runtime
    finally:
        await repo.dispose()


def app_of(*routers: APIRouter) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    for router in routers:
        app.include_router(router)
    return app


@asynccontextmanager
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://chaos.invalid") as c:
        yield c


def problem_is_clean(body: str, *hidden: str) -> bool:
    """No stack trace, statement or `hidden` value (a host, a port) in a response body."""
    marks = ("Traceback", "[SQL", "DETAIL:", *hidden)
    return not any(mark in body for mark in marks)
