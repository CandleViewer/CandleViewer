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
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.models import UserStatus
from candleviewer.auth.view_as import current_view_as
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
        return _holds_owner_role(self.roles)

    def grant_for(self, exchange_account_id: uuid.UUID) -> AccountGrant | None:
        for grant in self.account_grants:
            if grant.exchange_account_id == exchange_account_id:
                return grant
        return None


def _holds_owner_role(roles: Collection[str]) -> bool:
    """The Owner test, by role name: `PrincipalSnapshot.is_owner`'s rule, which
    `unviewable_target` applies to the roles of a user row that is not a snapshot yet."""
    return "owner" in roles


#: The statuses an Owner may view a user in (22 `startViewAs`): `locked` is only locked out of
#: signing in. An allow-list, so a status added to `UserStatus` is not viewable until it is placed
#: here.
VIEWABLE_STATUSES: Final = frozenset({UserStatus.ACTIVE.value, UserStatus.LOCKED.value})


class UnviewableTarget(StrEnum):
    """Why a user cannot be viewed as, in the order the start refuses it."""

    STATUS = "status"  # not in `VIEWABLE_STATUSES`
    OWNER = "owner"  # holds the Owner role (`PrincipalSnapshot.is_owner`)


def unviewable_target(status: object, roles: Collection[str]) -> UnviewableTarget | None:
    """Why the user of *status* and *roles* cannot be viewed as, `None` when an Owner may. The
    start refuses a target by it (`conflict`, then `view_as_owner_target`) and a context's
    eligibility ends on it (`target_ineligible`, `view_as_wiring.IdentityEligibility`). The port
    also ends a context whose target holds a role outside the system set, which the start does not
    check: the database's `role_name` enum allows none."""
    if status not in VIEWABLE_STATUSES:
        return UnviewableTarget.STATUS
    return UnviewableTarget.OWNER if _holds_owner_role(roles) else None


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


def scoped_account_ids(principal: PrincipalSnapshot) -> frozenset[uuid.UUID]:
    """The ids `account_scope()` lists: the grants that currently permit access, so not a frozen
    one. An owner's scope has no ids (it is every account), so none are listed for one."""
    scope = account_scope(principal)
    return scope.account_ids if isinstance(scope, GrantScope) else frozenset()


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


def _actor_of(principal: PrincipalSnapshot) -> uuid.UUID:
    """Who acts for `principal`: the viewer while the running request views as it (#3085, Q2),
    so a denial record never names the target as its actor; else the principal."""
    ctx = current_view_as()
    if ctx is not None and ctx.is_viewing_as_target and ctx.target_user_id == principal.user_id:
        return ctx.viewer_user_id
    return principal.user_id


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
    count_authz_denial(decision.permission, principal.roles)
    if emitter is not None:
        actor = _actor_of(principal)
        await emitter.emit(
            "rbac.denied",
            actor_label=str(actor),
            actor_user_id=actor,
            actor_ip=actor_ip,
            session_id=session_id,
            object_kind=str(exchange_account_id) if exchange_account_id else None,
            outcome="denied",
            severity="warning",
            reason=f"{decision.reason.value}:{decision.permission.value}:{decision.scope.value}",
            request_id=request_id,
        )
    raise ForbiddenError(decision)
