"""Fakes for the admin-area guard tests (E42-T01): one principal per RBAC actor, a resolver that
reads `x-role`, an audit spy keyed like `AuditWriter.emit`, and the record the guard must write."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Request

from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission

_PERMISSIONS = {
    "owner": frozenset({"admin:read", "admin:write"}),
    "manager": frozenset({"accounts:read", "audit:read"}),
    "viewer": frozenset({"audit:read"}),
}


def principal(role: str, last_step_up_at: datetime | None = None) -> AuditPrincipal:
    """Every field distinct and non-null, so a dropped audit field cannot go unseen. The last
    step-up is the one field left to the caller: `None` is a session that never stepped up."""
    n = list(_PERMISSIONS).index(role) + 1
    ids = UUID(int=n), UUID(int=100 + n), UUID(int=200 + n)  # user, session, request
    return AuditPrincipal(
        ids[0],
        role,
        _PERMISSIONS[role],
        ids[1],
        f"10.0.0.{n}",
        ids[2],
        n == 1,
        last_step_up_at=last_step_up_at,
    )


class Resolver:
    """`x-role` names the RBAC actor; anything else is an unauthenticated caller. Every actor
    last stepped up at `last_step_up_at`."""

    def __init__(self, last_step_up_at: datetime | None = None) -> None:
        self._last_step_up_at = last_step_up_at

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        role = request.headers.get("x-role", "")
        return principal(role, self._last_step_up_at) if role in _PERMISSIONS else None


class AuditSpy:
    """Records every call; keyword-only, with `AuditWriter.emit`'s parameter names."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: UUID,
        actor_ip: str | None,
        session_id: UUID | None,
        object_kind: str,
        object_id: str,
        outcome: AuditOutcome,
        severity: Severity,
        reason: str | None,
        after_state: dict[str, Any],
        request_id: UUID | None,
    ) -> None:
        call = dict(locals())  # every parameter, exactly as passed
        del call["self"]
        self.records.append(call)


def expected_record(
    role: str,
    route: str,
    permission: Permission = Permission.ADMIN_READ,
    reauth_age_s: int | None = None,
) -> dict[str, Any]:
    """The whole `admin.area_entered` record the guard must write for `role` on `route`, a router
    guarded by `permission`, for a caller whose last step-up was `reauth_age_s` seconds ago."""
    who, allowed = principal(role), permission.value in _PERMISSIONS[role]
    return {
        "action": "admin.area_entered",
        "actor_label": role,
        "actor_user_id": who.user_id,
        "actor_ip": who.ip,
        "session_id": who.session_id,
        "object_kind": "admin_route",
        "object_id": route,
        "outcome": AuditOutcome.SUCCESS if allowed else AuditOutcome.DENIED,
        "severity": Severity.INFO if allowed else Severity.WARNING,
        "reason": None if allowed else f"missing_permission:{permission.value}",
        "after_state": {"route": route, "reauth_age_s": reauth_age_s},
        "request_id": who.request_id,
    }
