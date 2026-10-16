"""The owner-floor lock shared by the user stores (#2492, E42-T04 #965).

`trg_owner_floor_fn` (migration 0001) cannot see another transaction's uncommitted change, so
two could each remove one of the last two owners. A change that can remove an active owner locks
the target user (`LOCK_USER`), then every active-owner grant in key order (`lock_active_owners`:
such changes queue, never deadlock), applies the injected `OwnerFloorCheck` (M18; storage may
not import auth) to the count read after that lock and to the target's `counted_roles`, and
fires the deferred trigger before its write-ahead audit (`CONSTRAINTS_NOW`);
`refuse_floor_violation` maps its 23514 onto the check.
"""

from __future__ import annotations

from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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


def refuse_floor_violation(
    exc: IntegrityError, check: OwnerFloorCheck, current: frozenset[str], new: frozenset[str]
) -> None:
    """Map the trigger's 23514 (the database saw no active owner left) onto `check`'s refusal;
    return for any other error, which the caller re-raises."""
    if getattr(exc.orig, "sqlstate", None) == _CHECK_VIOLATION:
        check(current, new, 0)
