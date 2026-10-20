"""Unit (E42-T05 #966 BK-9): `POST /admin/backups/{backupId}/verify` over a stand-in of BK-9b's
service (tested in `tests/unit/admin/test_backup_verify.py`): the `202` and the handler's
`requested` record, each refusal as its registered problem, and the guard's 403 cells (a record
and a count). CSRF and 401 for every actor: the RBAC matrix row (`tests/contract/rbac/`)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, Request
from prometheus_client import REGISTRY

from candleviewer.admin.backups.gate import BackupConflict
from candleviewer.admin.backups.verify import BackupVerifications, VerifiesLimited, VerifyNotUsable
from candleviewer.admin.errors import OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_backup_verify import make_admin_backup_verify_router
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from tests.unit.admin._admin_fakes import AuditSpy, expected_record, principal

BACKUP, JOB = UUID(int=1), UUID(int=2001)
_PATH, _ROUTE = f"/admin/backups/{BACKUP}/verify", "/admin/backups/{backupId}/verify"


class Resolver:
    """`x-role` names an `_admin_fakes` actor, the owner holding `backups:write`."""

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        role = request.headers.get("x-role", "")
        if role not in ("owner", "manager", "viewer"):
            return None
        who = principal(role)
        return (
            replace(who, permissions=who.permissions | {"backups:write"})
            if role == "owner"
            else who
        )


class Service:
    """`BackupVerifications` as the route sees it: `start` answers `answer` (a job id, `None`, or a
    refusal to raise) after the handler's `write_ahead`, which `audit_requested` serves."""

    def __init__(self, answer: object = JOB) -> None:
        self.answer, self.calls, self.requested = answer, list[object](), list[object]()

    async def start(self, who: AuditPrincipal, backup_id: UUID, *, write_ahead: Any) -> object:
        self.calls.append((who.username, backup_id))
        if isinstance(self.answer, Exception):
            raise self.answer
        if self.answer is not None:
            await write_ahead(backup_id, self.answer)
        return self.answer

    async def audit_requested(self, who: AuditPrincipal, backup_id: UUID, job_id: UUID) -> None:
        self.requested.append((who.username, backup_id, job_id))


async def _call(service: Service, role: str = "owner", path: str = _PATH) -> tuple[Any, AuditSpy]:
    spy, app = AuditSpy(), FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    install_error_redaction(app)
    verifications = cast(BackupVerifications, service)
    app.include_router(
        make_admin_backup_verify_router(verifications, resolver=Resolver(), audit=spy)
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(path, headers={"x-role": role}), spy


def _denied() -> float:
    """`authz_denied_total` for `backups:write` (SR-125); a test asserts the delta."""
    labels = {"permission": "backups:write"}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


async def test_verify_answers_202_with_its_job_after_the_handlers_requested_record() -> None:
    service = Service()
    answer, _ = await _call(service)
    assert (answer.status_code, answer.json()) == (202, {"job_id": str(JOB)})
    assert (service.calls, service.requested) == ([("owner", BACKUP)], [("owner", BACKUP, JOB)])


_REFUSALS = [
    (None, 404, "not_found", None, None),
    (VerifyNotUsable("x"), 409, "conflict", "backup_not_usable", None),
    (BackupConflict("verify_running"), 409, "conflict", "verify_running", None),
    (
        BackupConflict("backup_or_restore_running"),
        409,
        "conflict",
        "backup_or_restore_running",
        None,
    ),
    (VerifiesLimited(1234), 429, "rate_limited", None, "1234"),
    (OpsNotWired("backups: no verifier wired"), 501, "not_implemented", None, None),
    (OpsUnavailable("backups: the admission lock is busy"), 503, "store_unavailable", None, "5"),
    (OpsAuditUnavailable("backups: unwritten"), 503, "audit_unavailable", None, "5"),
]


@pytest.mark.parametrize(("answer", "status", "code", "rule", "retry"), _REFUSALS)
async def test_each_refusal_is_its_registered_problem(
    answer: object, status: int, code: str, rule: str | None, retry: str | None
) -> None:
    service = Service(answer)
    refused, _ = await _call(service)
    body = refused.json()
    assert (refused.status_code, body["code"], refused.headers.get("retry-after")) == (
        status,
        code,
        retry,
    )
    assert [error["rule"] for error in body.get("errors", [])] == ([rule] if rule else [])
    assert (refused.headers["content-type"], service.requested) == ("application/problem+json", [])


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_manager_and_viewer_get_403_never_reaching_the_service(role: str) -> None:
    service, before = Service(), _denied()
    refused, spy = await _call(service, role)
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert spy.records == [expected_record(role, _ROUTE, Permission.BACKUPS_WRITE)]
    assert (_denied(), service.calls) == (before + 1, [])


async def test_a_malformed_backup_id_is_422_after_the_guard() -> None:
    service = Service()
    refused, _ = await _call(service, path="/admin/backups/not-a-uuid/verify")
    assert (refused.status_code, refused.json()["code"], service.calls) == (
        422,
        "validation_failed",
        [],
    )
