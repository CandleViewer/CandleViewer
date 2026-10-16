"""`PUT /users/{userId}/roles` (E09-T03, QA #1648 defects 1-2).

Enforces `users:write`, SR-055 (never the acting user), the owner-floor guard at
API level, audits the change write-ahead inside the store's transaction (C-2.9),
and notifies the WS layer so a downgrade takes effect on live sockets.
`principal_resolver=None` / `store=None` fail closed with 501 (the fake backend;
the real backend wires both, #2492); the audit emitter and notifier are
required (TypeError at wiring time).
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from candleviewer.api.step_up import _AuthLike, _bearer, require_elevation_for
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import AuthError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce

_SYSTEM_ROLES = frozenset({"owner", "manager", "viewer"})


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class SnapshotResolver(Protocol):
    """Sync (test seams) or async (`SessionSnapshotResolver`, the deployed app, #2492)."""

    def resolve(
        self, request: Request
    ) -> PrincipalSnapshot | Awaitable[PrincipalSnapshot | None] | None: ...


class UserRoleStore(Protocol):
    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None: ...

    async def count_active_owners(self) -> int: ...

    async def apply_roles(
        self,
        user_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor: uuid.UUID,
        audit: Callable[[frozenset[str]], Awaitable[None]],
    ) -> bool:
        """Atomically (one transaction, owner rows locked) enforce the owner
        floor via `assert_owner_floor`, write `roles` granted by `actor`, then
        await `audit(roles read under lock)` before committing (C-2.9
        write-ahead). Raises `OwnerFloorError` or what `audit` raises, with
        nothing changed (or `TimeoutError`, #2510); False if no such user."""
        ...


class PermissionChangeNotifier(Protocol):
    async def roles_changed(self, user_id: uuid.UUID) -> None: ...


class _AuditRefused(Exception):
    """The write-ahead audit record could not be written; the change rolled back."""


def _forbidden(reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "type": "about:blank",
            "title": "Forbidden",
            "status": 403,
            "code": "forbidden",
            "reason": reason,
        },
        media_type="application/problem+json",
    )


def _problem(status: int, code: str, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
        },
        media_type="application/problem+json",
    )


async def _audit(
    emitter: _Emitter,
    action: str,
    principal: PrincipalSnapshot,
    user_id: uuid.UUID,
    reason: str,
    *,
    before: frozenset[str],
    after: frozenset[str],
) -> None:
    """C-12.8: every record carries the role set before and after (for a
    denial, `after` is the *requested* set that was refused)."""
    await emitter.emit(
        action,
        actor_label=str(principal.user_id),
        actor_user_id=principal.user_id,
        object_kind="user",
        object_id=str(user_id),
        reason=reason,
        before_state={"roles": sorted(before)},
        after_state={"roles": sorted(after)},
    )


def make_users_router(
    store: UserRoleStore | None,
    emitter: _Emitter,
    principal_resolver: SnapshotResolver | None,
    notifier: PermissionChangeNotifier,
    *,
    auth: _AuthLike | None = None,
) -> APIRouter:
    """`emitter` and `notifier` are mandatory: a role change without an
    audit record (C-2.9) or without a live-socket re-evaluation is refused
    at wiring time, not silently skipped."""
    if emitter is None or notifier is None:
        raise TypeError("make_users_router: audit emitter and notifier are required")
    router = APIRouter()

    @router.put("/users/{userId}/roles")
    async def put_user_roles(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        if principal_resolver is None or store is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver/store wired"
            )
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _problem(
                401, "unauthorized", "Unauthorized", "no verified session for this request"
            )
        try:
            await enforce(principal, Permission.USERS_WRITE, scope=Scope.NONE, emitter=emitter)
        except ForbiddenError as exc:
            return _forbidden(exc.deny.reason.value)
        if user_id == principal.user_id:  # SR-055: never the acting user, step-up or not
            await emitter.emit(
                "rbac.denied",
                actor_label=str(principal.user_id),
                actor_user_id=principal.user_id,
                object_kind="user",
                object_id=str(user_id),
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="self_target",
            )
            return _forbidden("self_target")
        # SR-025: step-up after authn + RBAC, before any mutation. Fail closed
        # when the step-up service is not wired. Denial is audited by B16.
        if auth is None or not auth.step_up_is_active or not auth.sessions_is_active:
            return _problem(503, "service_unavailable", "Service unavailable", "step-up not wired")
        token = _bearer(request)
        if token is None:
            return _problem(401, "unauthorized", "Unauthorized", "authentication required")
        try:
            record = await auth.sessions.authenticate_access_token(token)
        except AuthError:
            return _problem(401, "unauthorized", "Unauthorized", "authentication required")
        gate = await require_elevation_for(auth, str(record.id), "users")
        if gate is not None:
            return gate
        try:
            body = await request.json()
        except ValueError:
            return _problem(400, "bad_request", "Bad request", "body must be JSON")
        roles_raw = body.get("roles") if isinstance(body, dict) else None
        if (
            not isinstance(roles_raw, list)
            or not roles_raw
            or not all(isinstance(r, str) and r in _SYSTEM_ROLES for r in roles_raw)
        ):
            return _problem(
                400, "bad_request", "Bad request", "roles must be a non-empty list of role names"
            )
        new_roles = frozenset(roles_raw)
        current = await store.get_roles(user_id)
        if current is None:
            return _problem(404, "not_found", "Not found", "user not found")

        async def write_ahead(before: frozenset[str]) -> None:
            """C-2.9: written inside the store's transaction, before commit, with the
            role set read under lock; a failed write rolls the change back."""
            try:
                for action, changed in (
                    ("roles.grant", sorted(new_roles - before)),
                    ("roles.revoke", sorted(before - new_roles)),
                ):
                    if changed:
                        await _audit(
                            emitter,
                            action,
                            principal,
                            user_id,
                            ",".join(changed),
                            before=before,
                            after=new_roles,
                        )
            except (AuditError, RuntimeError) as exc:  # RuntimeError: audit not started
                raise _AuditRefused from exc

        # Endpoint-level owner floor (defence in depth; `apply_roles` re-checks
        # atomically under lock, so a concurrent demotion still cannot slip by).
        try:
            assert_owner_floor(
                current_roles=current,
                new_roles=new_roles,
                active_owner_count=await store.count_active_owners(),
            )
            found = await store.apply_roles(
                user_id, new_roles, actor=principal.user_id, audit=write_ahead
            )
        except OwnerFloorError:
            await _audit(
                emitter,
                "rbac.denied",
                principal,
                user_id,
                "owner_floor",
                before=current,
                after=new_roles,
            )
            return _problem(409, "conflict", "Conflict", "the last active owner cannot be demoted")
        except (_AuditRefused, TimeoutError):  # TimeoutError: the store bounds the hook
            return _problem(503, "service_unavailable", "Service unavailable", "audit unavailable")
        if not found:
            return _problem(404, "not_found", "Not found", "user not found")
        await notifier.roles_changed(user_id)
        return JSONResponse(
            status_code=200, content={"id": str(user_id), "roles": sorted(new_roles)}
        )

    return router
