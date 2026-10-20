"""Driver-free surface of the user lifecycle store (E42-T04 S3, #965).

`admin` may not import a storage driver (ADR-0003), so the disable service (slice S4) reads
`UserStatusChange` and catches the refusals from here; `user_lifecycle_sqlalchemy.py` implements
the store. A disable revokes every live session with `revoked_reason` `user_disabled` and
soft-revokes every live account grant (`can_view = can_trade = false`), never a DELETE, so the
freeze state and `max_daily_loss_usd` survive (#965 O4, C-12.5).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

#: `AccountAccessGrant.level` (22-api-openapi.yaml): `trade` implies `read`.
GrantLevel = Literal["read", "trade"]
#: `sessions.revoked_reason` of a disable (23-ws-protocol.md section 9.5 `bye` reason).
REVOKED_REASON = "user_disabled"


class UserSelfTargetError(Exception):
    """The actor named their own account (HTTP 403 `forbidden`, SR-055); nothing changed."""


@dataclass(frozen=True, slots=True)
class UserStatusChange:
    """A status change read and written under the user-row lock: handed to the audit hook
    before the commit, returned after it for the post-commit steps. Ids are plain `uuid.UUID`s.
    `changed` is False for a no-op: nothing was written, audited or revoked."""

    user_id: uuid.UUID
    before: str
    after: str
    #: Effective roles, read under the lock.
    roles: frozenset[str]
    revoked_session_ids: tuple[uuid.UUID, ...] = ()
    #: `exchange_account_id` -> the level the grant had before its soft revoke.
    revoked_grants: Mapping[uuid.UUID, GrantLevel] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.before != self.after


#: Writes the change's audit record ahead of the commit; raising rolls the change back.
LifecycleAuditHook = Callable[[UserStatusChange], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class UserPatch:
    """What a `PATCH /users/{userId}` asks the user admin store to apply (E42-T09, #2649): a
    `None` field was not sent. A disable never reaches the store; it is the disable cascade's."""

    #: Sent (`set_display_name`), possibly `null`.
    display_name: str | None = None
    set_display_name: bool = False
    roles: frozenset[str] | None = None
    #: Only `true` is settable: TOTP is mandatory for every user (C-12.2, #965 O3).
    require_mfa: bool = False
    #: `status: active`: only a `disabled` user is enabled, and nothing is restored (R6).
    enable: bool = False


@dataclass(frozen=True, slots=True)
class UserUpdate:
    """A change read and written under the user-row lock and the owner lock: `before` and `after`
    are the `User` representations read in the transaction (`identity_sqlalchemy.read_user`),
    handed to the audit hook before the commit and returned after it. `changed` is False when
    nothing was written or audited."""

    user_id: uuid.UUID
    before: Mapping[str, Any]
    after: Mapping[str, Any]

    @property
    def changed(self) -> bool:
        return self.before != self.after


#: Judges the representation read under the lock (a stale `If-Match`, a status the patch may not
#: leave); raising refuses the change, which rolls back.
UserPrecondition = Callable[[Mapping[str, Any]], None]
#: Writes the change's audit records ahead of the commit; raising rolls the change back.
UserUpdateAudit = Callable[[UserUpdate], Awaitable[None]]
