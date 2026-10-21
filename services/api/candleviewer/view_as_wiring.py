"""Composition-root adapters for view-as (#3085): `ViewAsService`'s ports, and `build_view_as`,
which composes the service and its sweeper.

The eligibility port reads what the request resolvers read (`SessionSnapshotResolver`): the
viewer's permissions (none unless active), the target's status and roles. What it cannot place,
a role outside the system set or a status other than active or locked (a locked target may still
be viewed), ends the context: it fails closed. The socket closer closes nothing until #3085's
WebSocket side wires `RevocationHub.close_session`; no context can start before #3085's start
route lands, so no socket is bound to one meanwhile.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

from candleviewer.admin.view_as import (
    CloseReason,
    EndRecordRunner,
    Ineligible,
    ViewAsAudit,
    ViewAsService,
)
from candleviewer.admin.view_as_sweeper import ViewAsSweeper
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsEndReason
from candleviewer.settings import Settings

if TYPE_CHECKING:
    from candleviewer.auth.service import AuthService

_VIEWABLE: Final = frozenset({UserStatus.ACTIVE.value, UserStatus.LOCKED.value})


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


class UnwiredSockets:
    async def close_family(self, session_id: str, *, reason: CloseReason) -> None:
        return None


def build_view_as(
    settings: Settings,
    *,
    auth: AuthService,
    identity: Identity | None,
    audit: ViewAsAudit,
    runner: EndRecordRunner,
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
        sockets=UnwiredSockets(),
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
