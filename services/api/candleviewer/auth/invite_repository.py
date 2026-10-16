"""`InviteRepository` - storage seam for invite-based user creation (E09-S05).

Same composition-root pattern as `UserRepository`/`MfaRepository`: M18 never
imports a storage driver (ADR-0003); the Postgres implementation lives in M10.
Every state change is a single conditional statement so concurrent
redemptions cannot both win. The owner actions (create, reissue, revoke) take a
write-ahead audit hook (C-2.9, #2510).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from candleviewer.auth.models import InviteRecord

#: Write-ahead audit of an owner invite action, `(user_id, role)`: awaited before the first
#: write (inside the transaction, if any); what it raises refuses it with nothing persisted.
InviteAudit = Callable[[uuid.UUID, str], Awaitable[None]]


class InviteRepository(Protocol):
    async def create_user_with_invite(
        self,
        *,
        user_id: uuid.UUID,
        invite_id: uuid.UUID,
        email: str,
        username: str,
        display_name: str | None,
        role: str,
        placeholder_password_hash: str,
        invited_by: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        audit: InviteAudit,
    ) -> bool:
        """One transaction: `users` (status invited, mfa_required), the
        `user_roles` row, the `user_invites` row. Zero `user_account_access`
        rows. Returns False (nothing written) when the email/username is
        already taken; otherwise `audit` runs before the commit."""
        ...

    async def find_by_token_hash(self, token_hash: str) -> InviteRecord | None: ...

    async def consume(
        self, token_hash: str, *, now: datetime, pending_password_hash: str
    ) -> InviteRecord | None:
        """`UPDATE ... SET consumed_at = now WHERE token_hash = :h AND
        consumed_at IS NULL AND revoked_at IS NULL AND expires_at > :now
        RETURNING ...` - exactly one concurrent caller gets the row."""
        ...

    async def find_consumed_for_user(self, user_id: uuid.UUID) -> InviteRecord | None:
        """The consumed, unrevoked invite of a still-`invited` user, or None."""
        ...

    async def activate_user(
        self, user_id: uuid.UUID, *, password_hash: str, algo_params: dict[str, int], now: datetime
    ) -> bool:
        """`status invited -> active` and set the real password, only while
        the user is still `invited`; returns whether this call did it."""
        ...

    async def downgrade_to_viewer(self, user_id: uuid.UUID) -> None:
        """Rewrite the invite role and the user's role row to `viewer` (legacy invites)."""
        ...

    async def reissue(
        self,
        user_id: uuid.UUID,
        *,
        invite_id: uuid.UUID,
        token_hash: str,
        invited_by: uuid.UUID,
        expires_at: datetime,
        now: datetime,
        audit: InviteAudit,
    ) -> InviteRecord | None:
        """For a user still `invited`: revoke every open invite and insert a
        fresh one, then `audit`. None when the user is not an invited user."""
        ...

    async def revoke_open(self, user_id: uuid.UUID, *, now: datetime, audit: InviteAudit) -> bool:
        """Revoke the open invites, `audit` first; False (no audit) if none."""
        ...

    async def list_pending(self, *, now: datetime) -> tuple[InviteRecord, ...]:
        """Unconsumed, unrevoked invites (expired ones included) of `invited` users."""
        ...
