"""E42-T01: the audited admin-area guard (`candleviewer.admin.http`), on a probe route mounted
the way the E42-T03/T05/T07 routes will mount theirs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.admin.http import (
    AREA_ENTERED,
    AdminAreaRefused,
    AuditEmitter,
    PrincipalResolver,
    admin_area,
    admin_area_refused_handler,
    admin_router,
)
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.generated_permissions import Permission
from tests.unit.admin._admin_fakes import AuditSpy, Resolver, expected_record, principal
from tests.unit.audit.audit_fakes import FakeAuditRepository

READ = Permission.ADMIN_READ
AUDIT = Permission.AUDIT_READ  # held by the viewer and the manager, not the owner
_ERRORS = "https://candleviewer.local/errors/"


def _guarded(
    resolver: PrincipalResolver | None, audit: AuditEmitter | None, permission: Permission = READ
) -> tuple[TestClient, list[str]]:
    served: list[str] = []
    router = admin_router(permission, resolver=resolver, audit=audit)

    @router.get("/probe")
    @router.get("/probe/{item}")
    async def probe(request: Request) -> dict[str, str]:
        served.append(request.state.admin_principal.username)  # left there by the guard
        return {"served": "yes"}

    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(router)
    return TestClient(app), served


def _request(role: str) -> Request:
    headers = [(b"x-role", role.encode())]
    route = SimpleNamespace(path="/admin/overview")
    return Request({"type": "http", "path": "/admin/overview", "headers": headers, "route": route})


def _denied(permission: Permission) -> float:
    """`authz_denied_total` (SR-125) for `permission`; a test asserts the delta, not the value."""
    labels = {"permission": permission.value}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


class FailingAudit:
    async def emit(self, action: str, **fields: Any) -> None:
        raise RuntimeError("wal full at /var/lib/cv")


class CancelledAudit:
    async def emit(self, action: str, **fields: Any) -> None:
        raise asyncio.CancelledError


@pytest.mark.parametrize(
    ("role", "status", "code"),
    [
        ("owner", 200, None),
        ("manager", 403, "forbidden"),
        ("viewer", 403, "forbidden"),
        ("", 401, "unauthenticated"),
    ],
    ids=["owner", "manager", "viewer", "unauthenticated"],
)
def test_rbac_cell_on_any_admin_route(role: str, status: int, code: str | None) -> None:
    spy = AuditSpy()
    client, served = _guarded(Resolver(), spy)
    denied = _denied(READ)
    response = client.get("/admin/probe", headers={"x-role": role})
    assert response.status_code == status
    assert served == (["owner"] if status == 200 else [])
    assert spy.records == ([] if status == 401 else [expected_record(role, "/admin/probe")])
    assert _denied(READ) - denied == (1 if status == 403 else 0)  # a decided denial, not a 401
    if code is not None:
        assert (response.json()["code"], response.json()["type"]) == (code, _ERRORS + code)
    if status == 403:
        assert response.json()["detail"] == "requires admin:read"


@pytest.mark.parametrize(("role", "status"), [("viewer", 200), ("manager", 200), ("owner", 403)])
def test_the_guard_checks_the_permission_it_was_given(role: str, status: int) -> None:
    # A second router on `audit:read`, which the viewer and manager hold and the owner does not.
    spy = AuditSpy()
    client, served = _guarded(Resolver(), spy, AUDIT)
    denied = _denied(AUDIT), _denied(READ)
    response = client.get("/admin/probe", headers={"x-role": role})
    assert response.status_code == status
    assert served == ([role] if status == 200 else [])
    assert spy.records == [expected_record(role, "/admin/probe", AUDIT)]
    moved = (_denied(AUDIT) - denied[0], _denied(READ) - denied[1])
    assert moved == (1 if status == 403 else 0, 0)  # the label is the router's permission
    if status == 403:
        assert response.json()["detail"] == "requires audit:read"


@pytest.mark.parametrize(
    ("resolver", "audit", "role", "status", "code"),
    [
        (None, AuditSpy(), "owner", 501, "not_implemented"),
        (Resolver(), None, "owner", 503, "audit_unavailable"),
        (Resolver(), None, "viewer", 503, "audit_unavailable"),  # before the permission check
        (Resolver(), FailingAudit(), "owner", 503, "audit_unavailable"),
        (Resolver(), FailingAudit(), "viewer", 403, "forbidden"),  # a denial stays a 403
    ],
    ids=["no-resolver", "no-audit-owner", "no-audit-viewer", "failed-owner", "failed-viewer"],
)
def test_the_guard_fails_closed_before_any_route_runs(
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
    role: str,
    status: int,
    code: str,
) -> None:
    client, served = _guarded(resolver, audit)
    response = client.get("/admin/probe", headers={"x-role": role})
    assert (response.status_code, served) == (status, [])
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert (body["status"], body["code"], body["type"]) == (status, code, _ERRORS + code)
    assert "wal" not in response.text  # the failure's own message never leaves


@pytest.mark.parametrize(
    ("audit", "status", "counted"),
    [(FailingAudit(), 403, 1), (None, 503, 0)],
    ids=["write-failed", "no-audit-writer"],
)
def test_authz_denied_total_counts_a_decided_denial_even_if_the_audit_write_fails(
    audit: AuditEmitter | None, status: int, counted: int
) -> None:
    client, _ = _guarded(Resolver(), audit)  # a viewer: denied, so there is a denial to count
    denied = _denied(READ)
    assert client.get("/admin/probe", headers={"x-role": "viewer"}).status_code == status
    assert _denied(READ) - denied == counted  # no writer: the permission is never decided


@pytest.mark.parametrize("role", ["owner", "viewer"])
def test_a_failed_audit_write_is_logged_with_the_actor_and_the_request(role: str) -> None:
    client, _ = _guarded(Resolver(), FailingAudit())
    with capture_logs() as logs:
        client.get("/admin/probe", headers={"x-role": role})
    who = principal(role)
    assert logs == [
        {
            "event": "admin.area_entered.audit_failed",
            "log_level": "error",
            "route": "/admin/probe",
            "actor_user_id": who.user_id,
            "request_id": who.request_id,
            "error": "RuntimeError",  # the class only, never "wal full at /var/lib/cv"
        }
    ]


def test_the_record_names_the_route_template_not_the_concrete_path() -> None:
    spy = AuditSpy()
    client, _ = _guarded(Resolver(), spy)
    client.get("/admin/probe/42", headers={"x-role": "owner"})
    assert spy.records == [expected_record("owner", "/admin/probe/{item}")]


@pytest.mark.parametrize("role", ["owner", "viewer"])
async def test_a_cancelled_audit_write_propagates(role: str) -> None:
    denied = _denied(READ)
    with pytest.raises(asyncio.CancelledError):
        await admin_area(READ, Resolver(), CancelledAudit())(_request(role))
    assert _denied(READ) - denied == (1 if role == "viewer" else 0)  # counted before the write


async def test_an_unexpected_error_renders_as_a_generic_internal_error() -> None:
    response = await admin_area_refused_handler(Request({"type": "http"}), ValueError("dsn=x"))
    body = json.loads(bytes(response.body))
    assert (response.status_code, body["code"]) == (500, "internal_error")
    assert "dsn" not in body["detail"]


async def test_the_record_survives_the_real_writer_and_its_redactor(tmp_path: Path) -> None:
    repo = FakeAuditRepository()
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), sleep=repo.retry_sleep)
    await writer.start()
    enter = admin_area(READ, Resolver(), writer)
    await enter(_request("owner"))
    with pytest.raises(AdminAreaRefused):
        await enter(_request("viewer"))
    await writer.flush(5)
    await writer.stop(1)
    rows = [(r["action"], r["outcome"], json.loads(r["after_state"])) for r in repo.rows]
    state = {"route": "/admin/overview", "reauth_age_s": None}  # unmasked, both keys
    assert rows == [(AREA_ENTERED, "success", state), (AREA_ENTERED, "denied", state)]
