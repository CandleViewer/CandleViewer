"""`SqlAlchemyOwnerTotpReset` - the owner TOTP reset as one unit of work (#2593, BQ-05 (a)).

`POST /users/{userId}/mfa/reset` used to write through three stores, each in its own transaction,
after the actor had been authorised at entry: an owner demoted in between still completed it, and
a failure part-way left a partial reset. Here it is one transaction in the disable's lock order
(`user_lifecycle_sqlalchemy`), so the two queue and never deadlock: lock the target user
(`LOCK_USER`), then every active-owner grant, and re-read the actor as an active owner
(`require_active_owner`: `ActorNotAuthorised` before any write); set `mfa_required` (#2295, Q9);
revoke the target's confirmed methods; revoke every live session; await the caller's write-ahead
audit with the counts, bounded (C-2.9, #2510); commit. No `CONSTRAINTS_NOW`: no role changes, so
the owner floor is not in play. A raise before the commit rolls everything back. The socket close
and the B16 records follow the commit, fed by the revoked session records this returns.
Lives in M10, so `auth` (M18) reaches it through its `OwnerTotpReset` port (C-3.1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.owner_floor_sqlalchemy import (
    LOCK_USER,
    require_active_owner,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import REVOKE_ALL_SQL, row_to_fields
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

#: `auth.step_up.ResetAudit`, restated: storage may not import `auth` (C-3.1).
ResetAudit = Callable[[int, int], Awaitable[None]]

_REQUIRE_MFA = sa.text("UPDATE users SET mfa_required = true WHERE id = CAST(:id AS uuid)")
#: The methods `find_active_methods` lists (confirmed, not revoked), revoked in one statement.
_REVOKE_METHODS = sa.text(
    "UPDATE mfa_methods SET revoked_at = :now WHERE user_id = CAST(:id AS uuid) "
    "AND confirmed_at IS NOT NULL AND revoked_at IS NULL RETURNING id"
)


class SqlAlchemyOwnerTotpReset:
    """Postgres `auth.step_up.OwnerTotpReset`."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        session_factory: Callable[..., Any],
        *,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        """`session_factory` builds a `SessionRecord` from `row_to_fields`' keywords."""
        self._relational = relational
        self._make = session_factory
        self._audit_timeout_s = audit_timeout_s

    async def reset_totp(
        self,
        target_user_id: str,
        *,
        actor_user_id: str,
        now: datetime,
        reason: str,
        audit: ResetAudit,
    ) -> tuple[int, tuple[Any, ...]] | None:
        """The methods revoked and the session records revoked; `None` when the target does not
        exist (or is deleted), nothing written. Raises `ActorNotAuthorised` when the actor is no
        longer an active owner (before the not-found answer and any write), what `audit` raises,
        or `WriteAheadTimeout` when it outlives its bound; each rolls everything back."""
        async with self._relational.unit_of_work() as uow:
            s = uow.session
            target = (await s.execute(LOCK_USER, {"id": target_user_id})).first()
            await require_active_owner(s, actor_user_id)
            if target is None:
                return None
            await s.execute(_REQUIRE_MFA, {"id": target_user_id})
            params = {"id": target_user_id, "now": now}
            methods = len((await s.execute(_REVOKE_METHODS, params)).all())
            ended = {"u": target_user_id, "reason": reason, "now": now, "except_id": None}
            sessions = tuple(
                self._make(**row_to_fields(r)) for r in (await s.execute(REVOKE_ALL_SQL, ended))
            )
            await bounded_write_ahead(audit(methods, len(sessions)), self._audit_timeout_s)
            await uow.commit()
        return methods, sessions
