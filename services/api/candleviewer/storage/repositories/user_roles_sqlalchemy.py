"""`SqlAlchemyUserRoleStore` - the Postgres `UserRoleStore` of `api/users.py` (#2492).

Lives in M10, so the owner floor (`auth.owner_floor`, M18) is injected by the
composition root, not imported (C-3.1). Static, parameterised SQL over effective
(unexpired) grants, with the predicate of `trg_owner_floor_fn` (migration 0001).
`apply_roles` is one transaction under the owner-floor lock it shares with the
user lifecycle store (`owner_floor_sqlalchemy.py`): lock the target user (changes
to one user queue), lock every active-owner grant in key order (concurrent
demotions and disables queue, never deadlock), re-check the floor on the count
read after that lock, replace the set, fire the deferred owner-floor trigger
(SQLSTATE 23514 maps onto the same check), then hand the locked before-set to the
caller's write-ahead audit hook before commit (C-2.9): a refused audit write rolls
the change back. Held under those locks, the hook is bounded
(`WRITE_AHEAD_TIMEOUT_S`, #2510): `WriteAheadTimeout` rolls back and frees them. A
timed-out append may still land (`AuditWriter.emit` is cancellation-safe): the trail
may over-report an attempt (as a failed commit can), never under-report.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.owner_floor_sqlalchemy import (
    CONSTRAINTS_NOW,
    COUNT_OWNERS,
    LOCK_USER,
    OwnerFloorCheck,
    effective_roles,
    lock_active_owners,
    refuse_floor_violation,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Write-ahead audit of the change, given the role set read under lock.
AuditHook = Callable[[frozenset[str]], Awaitable[None]]
#: Default bound (s) on a write-ahead audit hook awaited under row locks (#2510; invites too).
WRITE_AHEAD_TIMEOUT_S = 5.0

# Dropped: roles outside the new set, and expired grants (re-granted fresh below).
_DROP = sa.text(
    "DELETE FROM user_roles ur USING roles r WHERE ur.user_id = CAST(:id AS uuid) "
    "AND r.id = ur.role_id AND (r.name::text <> ALL(CAST(:roles AS text[])) "
    "OR (ur.expires_at IS NOT NULL AND ur.expires_at <= now()))"
)
_GRANT = sa.text(
    "INSERT INTO user_roles (user_id, role_id, granted_by) SELECT CAST(:id AS uuid), r.id, "
    "CAST(:by AS uuid) FROM roles r WHERE r.name::text = ANY(CAST(:roles AS text[])) "
    "ON CONFLICT (user_id, role_id) DO NOTHING"
)


async def bounded_write_ahead(hook: Awaitable[None], timeout_s: float) -> None:
    """Await a write-ahead audit `hook` in the caller's unit of work (row locks held);
    past `timeout_s` raise `WriteAheadTimeout`, so the unit of work rolls back. Only that
    type means "rolled back": a driver or commit `TimeoutError` is not converted."""
    try:
        async with asyncio.timeout(timeout_s):
            await hook
    except TimeoutError as exc:
        raise WriteAheadTimeout(f"write-ahead audit exceeded {timeout_s} s") from exc


class SqlAlchemyUserRoleStore:
    """Postgres `UserRoleStore`: reads and replaces a user's effective role set."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        owner_floor: OwnerFloorCheck,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        """`owner_floor` is the M18 rule, injected by the composition root (`app.py`)."""
        self._relational = relational
        self._owner_floor = owner_floor
        self._audit_timeout_s = audit_timeout_s

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        """Effective role names; `None` when the user does not exist (or is deleted)."""
        async with self._relational.unit_of_work() as uow:
            return await effective_roles(uow.session, str(user_id))

    async def count_active_owners(self) -> int:
        """Active, undeleted users holding an unexpired owner grant (the trigger's count)."""
        async with self._relational.unit_of_work() as uow:
            return int((await uow.session.execute(COUNT_OWNERS)).scalar_one())

    async def apply_roles(
        self, user_id: uuid.UUID, roles: frozenset[str], *, actor: uuid.UUID, audit: AuditHook
    ) -> bool:
        """Replace the role set atomically (new grants record `actor`); False if the user
        does not exist. Raises what the owner-floor check or `audit` raises, or
        `WriteAheadTimeout` when `audit` outlives its bound; each rolls the transaction back,
        so nothing changes without its audit record."""
        uid, wanted = str(user_id), sorted(roles)
        current: frozenset[str] = frozenset()
        try:
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                if (await s.execute(LOCK_USER, {"id": uid})).first() is None:
                    return False
                owners = await lock_active_owners(s)
                current = await effective_roles(s, uid) or current
                self._owner_floor(current, roles, owners)
                await s.execute(_DROP, {"id": uid, "roles": wanted})
                await s.execute(_GRANT, {"id": uid, "roles": wanted, "by": str(actor)})
                await s.execute(CONSTRAINTS_NOW)  # the floor trigger fires before the audit
                await bounded_write_ahead(audit(current), self._audit_timeout_s)
                await uow.commit()
        except IntegrityError as exc:
            refuse_floor_violation(exc, self._owner_floor, current, roles)
            raise
        return True
