"""The owner-floor lock shared by the user stores (#2492, E42-T04 #965).

`trg_owner_floor_fn` (migration 0001) cannot see another transaction's uncommitted change, so
two could each remove one of the last two owners. A change that can remove an active owner locks
the target user (`LOCK_USER`), then every active-owner grant in key order (`lock_active_owners`:
such changes queue, never deadlock), applies the injected `OwnerFloorCheck` (M18; storage may
not import auth) to the count read after that lock and to the target's `counted_roles`, and
fires the deferred trigger before its write-ahead audit (`CONSTRAINTS_NOW`); `floor_refusal`
maps its 23514 onto the check, from the error's facts alone (#2748).

#2593: every owner-only write re-checks its actor at the effect, in its own transaction, with
`require_active_owner`: after the owner lock, a fresh `ACTOR_IS_ACTIVE_OWNER` statement (never the
locked id set: a locking read does not see that an owner it queued behind was disabled) decides,
and no row refuses with `ActorNotAuthorised` before any write. Every writer that can demote or
disable an active owner takes the owner lock first, so of a revoke and an in-flight write exactly
one is ordered first: the revoke commits and the write is refused, or the write commits and the
revoke is ordered after its effect.
"""

from __future__ import annotations

from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.storage.errors import ActorNotAuthorised
from candleviewer.storage.repositories.relational_sqlalchemy import query_failure

#: `(current_roles, new_roles, active_owner_count)`; raises to refuse the change.
OwnerFloorCheck = Callable[[frozenset[str], frozenset[str], int], None]

_CHECK_VIOLATION = "23514"  # `trg_owner_floor_fn` raises this at commit
#: The user's status; a changed row is re-read before the lock is granted.
LOCK_USER = sa.text(
    "SELECT status::text FROM users WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL "
    "FOR NO KEY UPDATE"
)
#: Effective (unexpired) role names of an undeleted user.
ROLES = sa.text(
    "SELECT ARRAY(SELECT r.name::text FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "WHERE ur.user_id = u.id AND (ur.expires_at IS NULL OR ur.expires_at > now()) "
    "ORDER BY 1) AS roles FROM users u WHERE u.id = CAST(:id AS uuid) AND u.deleted_at IS NULL"
)
#: The trigger's predicate: active, undeleted users holding an unexpired owner grant.
COUNT_OWNERS = sa.text(
    "SELECT count(*) FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE r.name = 'owner' AND u.deleted_at IS NULL "
    "AND u.status = 'active' AND (ur.expires_at IS NULL OR ur.expires_at > now())"
)
LOCK_OWNERS = sa.text(
    "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE r.name = 'owner' AND u.deleted_at IS NULL "
    "AND u.status = 'active' AND (ur.expires_at IS NULL OR ur.expires_at > now()) "
    "ORDER BY ur.user_id FOR UPDATE OF ur"
)
CONSTRAINTS_NOW = sa.text("SET CONSTRAINTS ALL IMMEDIATE")
#: #2593: `COUNT_OWNERS`'s predicate for one user, the actor of an owner-only write.
ACTOR_IS_ACTIVE_OWNER = sa.text(
    "SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:id AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL "
    "AND u.status = 'active' AND (ur.expires_at IS NULL OR ur.expires_at > now())"
)


async def effective_roles(session: AsyncSession, user_id: str) -> frozenset[str] | None:
    """The user's effective role names; `None` when the user does not exist (or is deleted)."""
    row = (await session.execute(ROLES, {"id": user_id})).first()
    return None if row is None else frozenset(row._mapping["roles"] or ())


def counted_roles(status: str, roles: frozenset[str]) -> frozenset[str]:
    """The target's roles as the floor sees them: `COUNT_OWNERS` counts active users only, so a
    target in any other status holds none of the counted owner grants."""
    return roles if status == "active" else frozenset()


async def lock_active_owners(session: AsyncSession) -> int:
    """Lock every active-owner grant in key order, then count the active owners afresh.

    A locking read keeps the snapshot its statement started with: it re-checks a row it queued
    behind only if that row itself changed. An owner disabled by the transaction it waited for
    (a `users` row, not a grant) would still look active, so the count is a new statement."""
    await session.execute(LOCK_OWNERS)
    return int((await session.execute(COUNT_OWNERS)).scalar_one())


async def require_active_owner(session: AsyncSession, actor: str) -> int:
    """#2593: lock every active-owner grant (`lock_active_owners`), then read the actor afresh;
    raise `ActorNotAuthorised` unless the actor is an active, undeleted user holding an unexpired
    owner grant. Call it before any write and any early return of the unit of work, after the
    target's `LOCK_USER` if there is one (the owner lock's key order). Answers the active-owner
    count read after the lock, for a floor check."""
    owners = await lock_active_owners(session)
    if (await session.execute(ACTOR_IS_ACTIVE_OWNER, {"id": actor})).first() is None:
        raise ActorNotAuthorised(actor)
    return owners


def floor_refusal(
    check: OwnerFloorCheck,
    current: frozenset[str],
    new: frozenset[str],
    state: str | None,
    constraint: str | None,
) -> Exception:
    """The error a refused statement leaves as, from its SQLSTATE and constraint alone (#2748,
    C-12.6): the trigger's 23514 (the database saw no active owner left; it names no constraint)
    as `check`'s refusal, anything else, a named CHECK's 23514 included, as `query_failure`. Raise
    it `from None`."""
    if state == _CHECK_VIOLATION and constraint is None:
        try:
            check(current, new, 0)
        except Exception as refusal:  # the floor's own error (409 at the edge)
            return refusal
    return query_failure(state, constraint)
