"""`SqlAlchemyBootstrapOwnerRepository`: the Postgres side of
`candleviewer.auth.bootstrap_owner.BootstrapOwnerStore` (#4479 C1, SR-023), built only by the
offline CLI's `SqlAlchemyBootstrapOwnerDatabase`, so cv-api holds nothing that can mint an Owner
invite (R4, S8). `mint_owner_invite` is ONE unit of work, steps (0) to (6) below; a refusal rolls
back with nothing written. Whole literal statements, never spliced (B608); the token arrives only
as its sha256. The row and the refusals are typed here: `storage` may not import `auth`
(DC-4479-18).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final, Literal, NamedTuple

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.storage.repositories.invites_sqlalchemy import (
    BOOTSTRAP_LOCK,
    INSERT_INVITE,
    INSERT_INVITED_USER,
)
from candleviewer.storage.repositories.owner_floor_sqlalchemy import COUNT_OWNERS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: The refusals, each a `candleviewer.auth.bootstrap_owner.BootstrapRefusal` value (a test pins
#: them): an active Owner exists, or the email's user (or the username it takes) cannot be it.
OWNER_EXISTS: Final = "owner_exists"
NOT_CANDIDATE: Final = "not_candidate"
BootstrapStoreRefusal = Literal["owner_exists", "not_candidate"]
#: `auth.invite_repository.BOOTSTRAP_ROLE`, spelled here: `storage` may not import `auth`.
_ROLE = "owner"

#: First: under REPEATABLE READ the lock statement would fix a snapshot that misses an Owner
#: committed while it waited (DC-4479-12).
_READ_COMMITTED = sa.text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
#: The undeleted user an email names (`citext`), and whether it may become the bootstrap Owner:
#: `invited`, and every role it holds an unexpiring `owner` grant (none, after F1). The state read
#: and the mint's locked read are whole literals (never spliced) that differ only by `FOR UPDATE
#: OF u`, which a unit test pins, so the two agree.
_READ_CANDIDATE = sa.text(
    "SELECT u.id::text AS id, (u.status = 'invited' AND NOT EXISTS (SELECT 1 FROM user_roles ur "
    "JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id AND (r.name <> 'owner' "
    "OR ur.expires_at IS NOT NULL))) AS eligible FROM users u "
    "WHERE u.email = :email AND u.deleted_at IS NULL"
)
_LOCK_CANDIDATE = sa.text(
    "SELECT u.id::text AS id, (u.status = 'invited' AND NOT EXISTS (SELECT 1 FROM user_roles ur "
    "JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id AND (r.name <> 'owner' "
    "OR ur.expires_at IS NOT NULL))) AS eligible FROM users u "
    "WHERE u.email = :email AND u.deleted_at IS NULL FOR UPDATE OF u"
)
#: A user the mint would create needs a free username (the unique index is on undeleted users).
_USERNAME_TAKEN = sa.text(
    "SELECT 1 FROM users WHERE username = :username AND deleted_at IS NULL LIMIT 1"
)
#: Reissue's predicate (open, or consumed with a parked password) over this user's invites, plus
#: every other bootstrap invite: the marker arm, `BOOTSTRAP_MARKER` written out (a unit test pins
#: it verbatim), is what revokes a run for another email (DC-4479-07).
_SUPERSEDE = sa.text(
    "UPDATE user_invites i SET revoked_at = :now WHERE i.revoked_at IS NULL "
    "AND (i.consumed_at IS NULL OR i.pending_password_hash IS NOT NULL) "
    "AND (i.user_id = CAST(:id AS uuid) "
    "OR (i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id)) RETURNING i.id"
)


class BootstrapMintRow(NamedTuple):
    """What a committed mint wrote: ids and counts, never the token or its hash."""

    user_id: uuid.UUID
    invite_id: uuid.UUID
    created_user: bool
    superseded: int


async def _judge(
    session: AsyncSession, email: str, username: str, candidate: sa.TextClause
) -> uuid.UUID | BootstrapStoreRefusal | None:
    """A refusal, the eligible user's id, or None: no user has the email and the username is free,
    so the mint creates one."""
    if int((await session.execute(COUNT_OWNERS)).scalar_one()) > 0:
        return OWNER_EXISTS
    row = (await session.execute(candidate, {"email": email})).first()
    if row is not None:
        return uuid.UUID(row.id) if row.eligible else NOT_CANDIDATE
    taken = (await session.execute(_USERNAME_TAKEN, {"username": username})).first()
    return None if taken is None else NOT_CANDIDATE


class SqlAlchemyBootstrapOwnerRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def bootstrap_state(
        self, email: str, username: str
    ) -> uuid.UUID | BootstrapStoreRefusal | None:
        """Read only, unlocked: what the mint would decide now. The mint decides again under its
        lock."""
        async with self._relational.unit_of_work() as uow:
            return await _judge(uow.session, email, username, _READ_CANDIDATE)

    async def mint_owner_invite(
        self,
        *,
        email: str,
        username: str,
        password_hash: str,
        token_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> BootstrapMintRow | BootstrapStoreRefusal:
        """A refusal after rolling back (nothing written), else the row after one commit."""
        async with self._relational.unit_of_work() as uow:
            session = uow.session
            await session.execute(_READ_COMMITTED)  # (0) before any query (DC-4479-12)
            await session.execute(BOOTSTRAP_LOCK)  # (1) the activation's key
            found = await _judge(session, email, username, _LOCK_CANDIDATE)  # (2), (3)
            if isinstance(found, str):
                await uow.rollback()
                return found
            user_id = uuid.uuid4() if found is None else found
            uid = str(user_id)
            if found is None:  # F1: no `user_roles` row while no Owner is active
                user = {"id": uid, "email": email, "username": username, "ph": password_hash}
                await session.execute(INSERT_INVITED_USER, user | {"dn": None, "by": None})
            revoked = await session.execute(_SUPERSEDE, {"id": uid, "now": now})  # (4)
            superseded, invite_id = len(revoked.all()), uuid.uuid4()
            # (5) the marker: the invite's inviter is its own user
            invite = {"iid": str(invite_id), "id": uid, "by": uid, "role": _ROLE, "th": token_hash}
            await session.execute(INSERT_INVITE, invite | {"exp": expires_at, "now": now})
            await uow.commit()  # (6)
        return BootstrapMintRow(user_id, invite_id, found is None, superseded)
