"""Composition-root adapters for view-as (#3085): `ViewAsService`'s ports, the users routes'
role-change notifier, and `build_view_as`, which composes the service and its sweeper.

The eligibility port reads what the request resolvers read (`SessionSnapshotResolver`): the
viewer's permissions (none unless active), the target's status and roles. What it cannot place,
a role outside the system set or a status other than active or locked (a locked target may still
be viewed), ends the context: it fails closed. The socket closer (`HubSocketCloser`) closes the
sockets bound to the ended context across the session's rotation family, and `SessionViewAs`
is the binding a WebSocket `auth` reads (23-ws-protocol.md section 9.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.admin.view_as import (
    CloseReason,
    EndRecordRunner,
    Ineligible,
    ViewAsAudit,
    ViewAsService,
)
from candleviewer.admin.view_as_sweeper import ViewAsSweeper
from candleviewer.api.users import PermissionChangeNotifier
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsBinding, ViewAsEndReason
from candleviewer.settings import Settings
from candleviewer.ws.revocation import RevocationHub

if TYPE_CHECKING:
    from candleviewer.auth.service import AuthService, AuthSessionStore

_VIEWABLE: Final = frozenset({UserStatus.ACTIVE.value, UserStatus.LOCKED.value})
HOOK_TIMEOUT_S: Final = 5.0  # bounds the role-change hook, so it never holds the registry


class Identity(Protocol):  # `SqlAlchemyIdentityProvider`
    async def user(self, user_id: str) -> dict[str, Any]: ...  # `LookupError`: no such user
    async def session_info(self, user_id: str) -> dict[str, Any]: ...


class IdentityEligibility:
    def __init__(self, identity: Identity) -> None:
        self._identity = identity

    async def ineligible(self, viewer: SessionRecord, target_user_id: UUID) -> Ineligible | None:
        info = await self._identity.session_info(str(viewer.user_id))
        if Permission.USERS_WRITE.value not in info.get("permissions", ()):
            return ViewAsEndReason.VIEWER_INELIGIBLE
        try:
            target = await self._identity.user(str(target_user_id))
        except LookupError:  # gone
            return ViewAsEndReason.TARGET_INELIGIBLE
        roles = frozenset(str(role) for role in target.get("roles") or ())
        try:
            snapshot = PrincipalSnapshot(
                user_id=target_user_id, roles=roles, permissions=frozenset()
            )
        except ValueError:  # a role outside the system set
            return ViewAsEndReason.TARGET_INELIGIBLE
        if snapshot.is_owner or target.get("status") not in _VIEWABLE:
            return ViewAsEndReason.TARGET_INELIGIBLE
        return None


class IdentityLabels:
    def __init__(self, identity: Identity) -> None:
        self._identity = identity

    async def usernames(self, user_ids: Collection[UUID]) -> Mapping[UUID, str]:
        names: dict[UUID, str] = {}
        for user_id in user_ids:
            try:
                names[user_id] = str((await self._identity.user(str(user_id)))["username"])
            except LookupError:  # gone: no label
                continue
        return names


class HubSocketCloser:
    """`ViewAsService`'s socket closer: across `session_id`'s rotation family, the sockets bound
    to the ended context, and only those (`RevocationHub.close_context`). A socket stays
    registered under its predecessor's id until it re-`auth`s, so the whole family is walked;
    a successor already on a newer context keeps its sockets (S5-SEC-03's go-live condition).
    The session's own sockets close first: that needs no read, so a walk that fails (its error
    reaches the service, which logs it) still closes them."""

    def __init__(self, hub: RevocationHub, store: AuthSessionStore) -> None:
        self._hub, self._store = hub, store

    async def close_family(self, session_id: str, *, context_id: UUID, reason: CloseReason) -> None:
        await self._hub.close_context(session_id, str(context_id), reason)
        for member in await self._store.walk_rotation_family(session_id):
            if member != session_id:  # the walk includes the session itself
                await self._hub.close_context(member, str(context_id), reason)


class SessionViewAs:
    """The WebSocket's view-as read (`ws.gateway.ViewAsRead`): `session_id`'s binding as a
    request's would be (`ViewAsService.evaluate`), `None` for a session that holds no context or
    is gone. `views` is read per call, since the router is built before the service; `None`
    there (the fake backend) binds nothing."""

    def __init__(
        self,
        views: Callable[[], ViewAsService | None],
        store: AuthSessionStore,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._views, self._store, self._clock = views, store, clock

    async def __call__(self, session_id: str) -> ViewAsBinding | None:
        service = self._views()
        if service is None:
            return None
        record = await self._store.find_by_id(session_id)
        return None if record is None else await service.evaluate(record, now=self._clock())


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class RoleChangeNotifier:
    """The users routes' `PermissionChangeNotifier`: `ViewAsService.on_roles_changed` runs first,
    so no viewing socket takes on a promoted target's Owner scope when the WebSocket registry
    re-evaluates. A hook that fails or outlasts its bound still lets the registry run; its error
    is raised after, for the route to count (`users.update.step`), and the sweeper evaluates what
    it left within a tick. A cancelled request still runs the registry, and a registry failure
    then is logged, never raised: it would replace the cancellation."""

    def __init__(
        self,
        view_as: ViewAsService,
        registry: PermissionChangeNotifier,
        *,
        timeout_s: float = HOOK_TIMEOUT_S,
    ) -> None:
        self._view_as, self._registry, self._timeout_s = view_as, registry, timeout_s

    async def roles_changed(self, user_id: UUID) -> None:
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._view_as.on_roles_changed(user_id)
        except asyncio.CancelledError:
            try:
                await self._registry.roles_changed(user_id)
            except Exception as exc:
                _log().error("admin.view_as.registry_push_failed", error=type(exc).__name__)
            raise
        except Exception:
            await self._registry.roles_changed(user_id)
            raise
        await self._registry.roles_changed(user_id)


def build_view_as(
    settings: Settings,
    *,
    auth: AuthService,
    identity: Identity | None,
    audit: ViewAsAudit,
    runner: EndRecordRunner,
    hub: RevocationHub,
    clock: Callable[[], datetime] | None,  # `create_app`'s auth clock: `None` is real UTC
) -> tuple[ViewAsService, ViewAsSweeper] | None:
    """The service and its sweeper over the auth module's session store; `None` on the fake
    backend, which has no session store or identity to read, so no context can exist there."""
    if identity is None or not auth.view_as_store_is_active:
        return None
    clock = clock or (lambda: datetime.now(UTC))
    store = auth.view_as_store
    service = ViewAsService(
        store,
        audit,
        runner=runner,
        eligibility=IdentityEligibility(identity),
        sockets=HubSocketCloser(hub, store),
        labels=IdentityLabels(identity),
        clock=clock,
    )
    sweeper = ViewAsSweeper(
        service,
        store,
        clock=clock,
        interval_s=settings.view_as_sweep_interval_s,
        rotated_grace=timedelta(seconds=settings.view_as_rotated_grace_s),
    )
    return service, sweeper
