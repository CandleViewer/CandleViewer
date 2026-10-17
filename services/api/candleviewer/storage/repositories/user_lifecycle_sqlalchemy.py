"""`SqlAlchemyUserLifecycleStore` - disables a user in one transaction (E42-T04 S3).

M10: the owner floor (M18) and the audit record (M19) are injected, and the owner-floor lock is
the role store's (`owner_floor_sqlalchemy.py`), so a disable and a demotion of the last two
owners queue on it (#965 AC6). `disable` (R7) refuses a self-target before any statement, then:
lock the user row; a user already disabled is a no-op (AC5); lock the owner grants and refuse
the last active owner; set `disabled`; revoke every live session; soft-revoke every live grant
(never a DELETE: the freeze columns, the cap and `granted_by` are never written, O4); run the
deferred constraints (23514 maps onto the floor refusal); await the caller's audit hook, bounded
by `audit_timeout_s` (C-2.9); commit. A raise before the commit rolls all of it back; if the hook
had started, its record may be durable, and the caller closes it. The post-commit steps (B16
REVOKE, sockets, rule disarm, invite revoke) are slice S4's. The session revoke sees only its
statement's snapshot, so a successor that an in-flight refresh mints after it stays live. No
slice of E42-T04 removes that window (S4's post-commit sweep only narrows it): refresh, mint and
require_active read no `users.status`, which #2911 tracks.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.owner_floor_sqlalchemy import (
    CONSTRAINTS_NOW,
    LOCK_USER,
    OwnerFloorCheck,
    counted_roles,
    effective_roles,
    lock_active_owners,
    refuse_floor_violation,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_lifecycle import (
    REVOKED_REASON,
    GrantLevel,
    LifecycleAuditHook,
    UserSelfTargetError,
    UserStatusChange,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import bounded_write_ahead

#: Bounds the audit hook, during which the user row and every owner grant stay locked.
AUDIT_TIMEOUT_S = 2.0
_NO_ROLES: frozenset[str] = frozenset()

_DISABLE = sa.text("UPDATE users SET status = 'disabled' WHERE id = CAST(:id AS uuid)")
_REVOKE_SESSIONS = sa.text(
    "UPDATE sessions SET revoked_at = :now, revoked_reason = :reason "
    "WHERE user_id = CAST(:id AS uuid) AND revoked_at IS NULL RETURNING id"
)
_LIVE_GRANTS = sa.text(
    "SELECT exchange_account_id, can_trade FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid) AND can_view ORDER BY exchange_account_id "
    "FOR NO KEY UPDATE"
)
# #965 O4: the account-access store's soft revoke (E42-T08), never a DELETE.
_REVOKE_GRANTS = sa.text(
    "UPDATE user_account_access SET can_view = false, can_trade = false "
    "WHERE user_id = CAST(:id AS uuid) AND exchange_account_id = ANY(CAST(:revoked AS uuid[]))"
)


def _uuid(value: object) -> uuid.UUID:
    """asyncpg returns its own `uuid.UUID` subclass, which orjson refuses: make it plain."""
    return uuid.UUID(str(value))


class SqlAlchemyUserLifecycleStore:
    """Postgres user lifecycle store: a status change and its cascade, atomically."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        owner_floor: OwnerFloorCheck,
        audit_timeout_s: float = AUDIT_TIMEOUT_S,
    ) -> None:
        """`owner_floor` is the M18 rule, injected by the composition root."""
        self._relational = relational
        self._owner_floor = owner_floor
        self._audit_timeout_s = audit_timeout_s

    async def disable(
        self,
        user_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        now: datetime,
        audit: LifecycleAuditHook,
    ) -> UserStatusChange | None:
        """Disable the user; sessions are revoked at `now`. `None` if the user does not exist.

        Raises `UserSelfTargetError`, what the owner-floor check raises for the last active
        owner, what `audit` raises, or `WriteAheadTimeout` when `audit` outlives
        `audit_timeout_s`; on any of them the transaction rolls back and nothing changes. A
        driver or commit `TimeoutError` is raised as is: the outcome is unknown. If the commit
        landed, the revoked ids are lost with the exception, so no post-commit step runs for
        those sessions, and a retry, which is AC5's no-op and returns no ids, does not settle
        them: their sockets stay open until their access token expires (up to 12 min,
        ADR-0020) and no B16 REVOKE record is written for them."""
        if user_id == actor:
            raise UserSelfTargetError(str(user_id))
        uid = str(user_id)
        counted = _NO_ROLES  # the roles the owner floor counts: an active user's
        try:
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                if (row := (await s.execute(LOCK_USER, {"id": uid})).first()) is None:
                    return None
                before, roles = str(row[0]), await effective_roles(s, uid) or _NO_ROLES
                if before == "disabled":
                    return UserStatusChange(user_id, before, before, roles)
                counted = counted_roles(before, roles)
                self._owner_floor(counted, _NO_ROLES, await lock_active_owners(s))
                await s.execute(_DISABLE, {"id": uid})
                params = {"id": uid, "now": now, "reason": REVOKED_REASON}
                rows = (await s.execute(_REVOKE_SESSIONS, params)).all()
                sessions = tuple(sorted(_uuid(r[0]) for r in rows))
                grants: dict[uuid.UUID, GrantLevel] = {
                    _uuid(r[0]): "trade" if r[1] else "read"
                    for r in (await s.execute(_LIVE_GRANTS, {"id": uid})).all()
                }
                revoked = [str(a) for a in grants]
                await s.execute(_REVOKE_GRANTS, {"id": uid, "revoked": revoked})
                change = UserStatusChange(user_id, before, "disabled", roles, sessions, grants)
                await s.execute(CONSTRAINTS_NOW)  # the floor trigger fires before the audit
                await bounded_write_ahead(audit(change), self._audit_timeout_s)
                await uow.commit()
        except IntegrityError as exc:
            refuse_floor_violation(exc, self._owner_floor, counted, _NO_ROLES)
            raise
        return change
