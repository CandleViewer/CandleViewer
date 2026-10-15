"""RBAC policy decision point (M18, E09-T03).

`decide()` answers "may this principal do this thing to this object?",
pure and synchronous over a per-request `PrincipalSnapshot` (roles,
permissions, account scope, loaded once — `docs/plan/20-architecture.md`
P8, §3.10). No ambient context: object-scoped decisions (account id) take
the object as an explicit argument, so the function is trivially testable
and the OMS validator's later use (E39+) stays honest.

Deny-by-default: `decide()` never raises `AllowUnknownPermission` — an
unresolvable principal, an unknown permission code, or a missing account
grant all yield `Deny`. Denials never leak whether the object exists (a
manager asking about another manager's account gets the same `Deny` as for
a non-existent one) — callers must render every `Deny` as a uniform 403,
never branching on `reason` for user-facing text beyond the fixed
`forbidden` body (ticket "403 semantics").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import authz_denied_total, normalise_permission
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope

#: Mirrors the database `role_name` ENUM (`'owner','manager','viewer'`,
#: migration `0001_identity_rbac_sessions_mfa.py`) — the *only* three role
#: names that can ever exist, enforced at the schema level, not just here.
#: "Custom or user-defined roles" are out of scope for v1 (ticket "Out of
#: scope"), so this set is exhaustive: a `roles` frozenset can only ever
#: contain members of it, and nothing upstream can mint a role called
#: "owner" that isn't the real system owner role.
_SYSTEM_ROLES = frozenset({"owner", "manager", "viewer"})


class DenyReason(StrEnum):
    """Machine-readable reason code for the uniform `forbidden` body
    (ticket "403 semantics" / SCR-154)."""

    MISSING_PERMISSION = "missing_permission"
    ACCOUNT_NOT_GRANTED = "account_not_granted"
    ACCOUNT_FROZEN = "account_frozen"
    TRADING_NOT_GRANTED = "trading_not_granted"
    OBJECT_REQUIRED = "object_required"


@dataclass(frozen=True)
class AccountGrant:
    """One row of `user_account_access` (`21-database-schema.md` §3.1.3):
    `can_view`/`can_trade`/`frozen` for one `exchange_account_id`."""

    exchange_account_id: uuid.UUID
    can_view: bool
    can_trade: bool
    frozen: bool


@dataclass(frozen=True)
class PrincipalSnapshot:
    """A principal's roles, resolved permissions and account grants, loaded
    once per request (or once per WS connection, refreshed on a role/access
    change bus event) — never re-queried per decision.

    `account_grants` is empty for `owner`: per the ticket's own text ("empty
    `allowed_account_ids` means all, owner only"), an owner's absence of any
    row in `user_account_access` means "every account", not "no account" —
    `decide()` special-cases `is_owner` for exactly this reason rather than
    trying to represent "all accounts" as a sentinel grant row.
    """

    user_id: uuid.UUID
    roles: frozenset[str]
    permissions: frozenset[Permission]
    account_grants: tuple[AccountGrant, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Defence in depth for the review finding that `is_owner` trusts the
        # role name alone: the DB `role_name` ENUM is the real guarantee
        # (no custom role can ever be named "owner"), but this snapshot is
        # constructed from whatever the caller supplies, so re-assert the
        # closed set here too rather than silently trusting it.
        unknown = self.roles - _SYSTEM_ROLES
        if unknown:
            raise ValueError(f"unknown role(s) not in the system role_name ENUM: {sorted(unknown)}")

    @property
    def is_owner(self) -> bool:
        return "owner" in self.roles

    def grant_for(self, exchange_account_id: uuid.UUID) -> AccountGrant | None:
        for grant in self.account_grants:
            if grant.exchange_account_id == exchange_account_id:
                return grant
        return None


@dataclass(frozen=True)
class Allow:
    """The decision was permitted."""


@dataclass(frozen=True)
class Deny:
    """The decision was refused; `reason` is machine-readable only — never
    used to distinguish "object doesn't exist" from "object not yours" in
    the HTTP response (ticket "Security notes").

    `permission`/`scope` echo the inputs `decide()` was called with, so a
    caller can build the audited `rbac.denied` record and the ticket's own
    acceptance criterion ("the denial names the permission and scope")
    without threading those values through separately — `Deny` alone is a
    complete, self-describing record of what was refused."""

    reason: DenyReason
    permission: Permission
    scope: Scope


Decision = Allow | Deny


def decide(
    principal: PrincipalSnapshot,
    permission: Permission,
    *,
    scope: Scope = Scope.NONE,
    exchange_account_id: uuid.UUID | None = None,
    requires_trade: bool = False,
) -> Decision:
    """Deny-by-default policy decision.

    `scope` mirrors the operation's `x-rbac.scope`:
    - `Scope.NONE`: the permission alone decides (no object).
    - `Scope.SELF`: caller-scoped; the router resolves "self" before
      calling `decide()` — this function only ever checks the permission
      (there is no cross-user "self" check to make here).
    - `Scope.GRANTED_ACCOUNTS`: `exchange_account_id` must be supplied and
      the principal must hold a live, unfrozen grant for it; `owner` is
      implicitly granted every account (empty `user_account_access` rows
      for owner means "all", per the ticket's own text).
    """
    if permission not in principal.permissions:
        return Deny(DenyReason.MISSING_PERMISSION, permission=permission, scope=scope)

    if scope is not Scope.GRANTED_ACCOUNTS:
        return Allow()

    if exchange_account_id is None:
        return Deny(DenyReason.OBJECT_REQUIRED, permission=permission, scope=scope)

    if principal.is_owner:
        return Allow()

    grant = principal.grant_for(exchange_account_id)
    if grant is None or not grant.can_view:
        return Deny(DenyReason.ACCOUNT_NOT_GRANTED, permission=permission, scope=scope)
    if grant.frozen:
        return Deny(DenyReason.ACCOUNT_FROZEN, permission=permission, scope=scope)
    if requires_trade and not grant.can_trade:
        return Deny(DenyReason.TRADING_NOT_GRANTED, permission=permission, scope=scope)

    return Allow()


def account_scope(principal: PrincipalSnapshot) -> AccountScope:
    """Storage scope for account reads/writes, mirroring `decide()` for GRANTED_ACCOUNTS: an
    owner sees every account; others only grants with `can_view` and not `frozen`. Zero grants
    is an empty scope (nothing), never "all"."""
    if principal.is_owner:
        return OwnerScope(principal.user_id)
    return GrantScope(
        principal.user_id,
        frozenset(
            g.exchange_account_id for g in principal.account_grants if g.can_view and not g.frozen
        ),
    )


class _AuditEmitter(Protocol):
    """Structural subset of `AuditWriter.emit` (mirrors `api/audit.py`'s
    `_Emitter`/`api/audit.py`'s `AuditWriterLike`) — this module never
    imports a concrete audit backend, only the shape it needs."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: Any = None,
        actor_ip: str | None = None,
        session_id: Any = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        outcome: Any = ...,
        severity: Any = ...,
        reason: str | None = None,
        request_id: Any = None,
    ) -> None: ...


class ForbiddenError(Exception):
    """Raised by `require_permission`'s dependency callable when `decide()`
    denies; the HTTP edge (composition root) maps this to the uniform
    `forbidden` RFC 7807 body per ticket "403 semantics" — callers never
    branch on `.deny.reason` for user-facing text, only for the audited
    record and the machine-readable body field."""

    def __init__(self, deny: Deny) -> None:
        self.deny = deny
        super().__init__(f"forbidden: {deny.reason.value} ({deny.permission.value})")


async def enforce(
    principal: PrincipalSnapshot,
    permission: Permission,
    *,
    scope: Scope = Scope.NONE,
    exchange_account_id: uuid.UUID | None = None,
    requires_trade: bool = False,
    emitter: _AuditEmitter | None = None,
    actor_ip: str | None = None,
    session_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
) -> None:
    """Runtime enforcement wrapper around `decide()`: on `Deny`, audits
    `rbac.denied` (severity warning, naming the permission and scope —
    ticket AC "the denial names the permission and scope and rbac.denied is
    audited") and raises `ForbiddenError`; on `Allow`, returns normally.

    This is the one call site FastAPI route dependencies and the WS
    gateway's per-subscribe check are expected to use so every enforcement
    point audits denials identically; `decide()` itself stays pure and
    audit-free so it remains trivially unit-testable (ticket "Technical
    notes": "a decision costs a set lookup, not a query").
    """
    decision = decide(
        principal,
        permission,
        scope=scope,
        exchange_account_id=exchange_account_id,
        requires_trade=requires_trade,
    )
    if isinstance(decision, Allow):
        return
    # SR-125: counted before the audit write, so a denial is never lost to an audit failure.
    authz_denied_total.labels(permission=normalise_permission(decision.permission)).inc()
    if emitter is not None:
        await emitter.emit(
            "rbac.denied",
            actor_label=str(principal.user_id),
            actor_user_id=principal.user_id,
            actor_ip=actor_ip,
            session_id=session_id,
            object_kind=str(exchange_account_id) if exchange_account_id else None,
            outcome="denied",
            severity="warning",
            reason=f"{decision.reason.value}:{decision.permission.value}:{decision.scope.value}",
            request_id=request_id,
        )
    raise ForbiddenError(decision)
