"""Server-side RBAC for the `/admin/audit*` operations (C-12.4).

Grants follow `docs/plan/04-security-program.md` §7.2.1 / §7.2.2 rows 49,
49a, 50 and SR-067 (mirrored in `22-api-openapi.yaml` `x-rbac`):

* `query` (`audit:read`): Owner sees every entry raw; a Manager holding
  `audit:read` sees only entries it is the actor of, with payload, IP,
  user-agent and both hashes removed (`AuditView.OWN_REDACTED`); a Viewer
  holds no `audit:read` and is refused. Viewer stays at 403 as decided on
  #2083; C-12.4's "Viewer (read-only, including audit)" is open for the
  owner's decision on #2428 (design D7), and nothing here widens it.
* `verify` (`audit:read`, row 49a): Owner only.
* `export` (`audit:export`, row 50): Owner only (step-up enforced upstream).

Owner-ness arrives on the principal (`is_owner`), resolved by the caller via
`candleviewer.auth.scopes.PrincipalSnapshot.is_owner`; the wildcard grant
`*` is treated as owner too.

Anything that is not provably the Owner is narrowed, never widened: a
principal with `audit:read` but no `owner` role gets the redacted own-events
view. Every denial is itself audited (`admin.audit_denied`, severity
`warning`, outcome `denied`) *before* `AuditAccessDenied` propagates to the
HTTP edge, which maps it to RFC 7807 `403`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditEntry, AuditOutcome, Severity

AuditPermission = Literal["audit:read", "audit:export"]

_OPERATION_PERMISSION: dict[str, AuditPermission] = {
    "query": "audit:read",
    "verify": "audit:read",
    "export": "audit:export",
}

#: Operations only the Owner may perform even when `audit:read` is held.
_OWNER_ONLY: frozenset[str] = frozenset({"verify", "export"})


class AuditView(StrEnum):
    """Projection of the log a caller is entitled to (SR-067)."""

    RAW = "raw"
    OWN_REDACTED = "own_redacted"


@dataclass(frozen=True, slots=True)
class AuditPrincipal:
    """The authenticated caller, as resolved server-side from the session."""

    user_id: uuid.UUID
    username: str
    permissions: frozenset[str]
    session_id: uuid.UUID | None = None
    ip: str | None = None
    request_id: uuid.UUID | None = None
    #: Resolved by the session resolver through `auth.scopes.PrincipalSnapshot.is_owner`
    #: (the sanctioned owner check, SR-017); this module never compares role names.
    is_owner: bool = False

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions  # nosem: no-adhoc-authz reason=Principal.has_permission-wildcard-impl-pending-E09-T01-authorize owner=@CandleViewer/security review=2026-12-31  # noqa: E501  # fmt: skip


class _Emitter(Protocol):
    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: uuid.UUID | None = ...,
        actor_ip: str | None = ...,
        session_id: uuid.UUID | None = ...,
        object_kind: str | None = ...,
        outcome: AuditOutcome = ...,
        severity: Severity = ...,
        reason: str | None = ...,
        request_id: uuid.UUID | None = ...,
    ) -> None: ...


class AuditAccessDenied(AuditError):
    """The caller lacks the permission for an `/admin/audit*` operation (→ 403)."""

    def __init__(self, operation: str, permission: str) -> None:
        super().__init__(f"audit {operation} requires {permission}")
        self.operation = operation
        self.permission = permission


async def authorize(principal: AuditPrincipal, operation: str, emitter: _Emitter) -> AuditView:
    """Allow `operation` (`query`/`verify`/`export`) for `principal` and return
    the projection it may see, or audit the denial and raise
    `AuditAccessDenied`. Unknown operations are denied (fail closed)."""
    permission = _OPERATION_PERMISSION.get(operation)
    if permission is not None and principal.has(permission):
        if principal.is_owner or principal.has("*"):
            return AuditView.RAW
        if operation not in _OWNER_ONLY:
            return AuditView.OWN_REDACTED
    required = permission or "<unknown-operation>"
    reason = (
        f"missing_permission:{required}"
        if permission is None or not principal.has(permission)
        else "owner_only"
    )
    await emitter.emit(
        "admin.audit_denied",
        actor_label=principal.username,
        actor_user_id=principal.user_id,
        actor_ip=principal.ip,
        session_id=principal.session_id,
        object_kind="audit_log",
        outcome=AuditOutcome.DENIED,
        severity=Severity.WARNING,
        reason=reason,
        request_id=principal.request_id,
    )
    raise AuditAccessDenied(operation, required)


#: SR-067 allow-list: the only `AuditEntry` fields a non-owner projection keeps.
#: Anything not named here (payload, IP, user-agent, any field added later) is
#: dropped or nulled by default. Both hashes are withheld too (contract #2392):
#: with the hashed fields known, `entry_hash` would let a caller confirm guesses
#: about the fields the projection hides, and `prev_hash` links to the hash of
#: the entry before it.
OWN_REDACTED_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "ts",
        "actor_user_id",
        "actor_username",
        "action",
        "subject_type",
        "subject_id",
        "outcome",
        "severity",
        "request_id",
    }
)


def redact_entry_for_view(entry: AuditEntry, view: AuditView) -> AuditEntry:
    """SR-067 projection: raw for the Owner; otherwise only the allow-listed
    `OWN_REDACTED_FIELDS` keep their values and every other field is blanked
    (`detail` -> `{}`, everything else -> `None`)."""
    if view is AuditView.RAW:
        return entry
    blanked: dict[str, object] = {
        name: ({} if name == "detail" else None)
        for name in type(entry).model_fields
        if name not in OWN_REDACTED_FIELDS
    }
    return entry.model_copy(update=blanked)
