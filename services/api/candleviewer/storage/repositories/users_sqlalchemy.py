"""`SqlAlchemyUserRepository` — Postgres implementation of
`candleviewer.auth.repository.UserRepository` (E09-S01, QA #1658).

Lives in M10 so `candleviewer.auth` never imports a storage driver (ADR-0003).
Every statement is static, parameterised SQL; no password material is ever
returned beyond the stored Argon2id digest `LoginService` must verify.
Lockout increment-and-lock is one atomic `UPDATE ... RETURNING`.

`SqlAlchemyUserAdminStore` (E42-T09, #2649) is the `User` read model behind `getUser` and the
locked update behind `updateUser`: never `password_hash`, and one transaction per change (R7).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.identity_sqlalchemy import read_user
from candleviewer.storage.repositories.owner_floor_sqlalchemy import (
    CONSTRAINTS_NOW,
    LOCK_USER,
    OwnerFloorCheck,
    counted_roles,
    lock_active_owners,
    refuse_floor_violation,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_lifecycle import (
    UserPatch,
    UserPrecondition,
    UserUpdate,
    UserUpdateAudit,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    DROP_ROLES,
    GRANT_ROLES,
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

_FIND_SQL = sa.text("""
    SELECT u.id::text AS id, u.username::text AS username, u.email::text AS email,
           u.password_hash, u.password_algo_params, u.status::text AS status,
           u.mfa_required, u.failed_login_count, u.locked_until,
           COALESCE((SELECT array_agg(DISTINCT m.kind::text) FROM mfa_methods m
                     WHERE m.user_id = u.id AND m.confirmed_at IS NOT NULL
                       AND m.revoked_at IS NULL), ARRAY[]::text[]) AS mfa_methods
    FROM users u
    WHERE u.deleted_at IS NULL AND (u.username = :ident OR u.email = :ident)
    LIMIT 1
    """)
_FIND_BY_ID_SQL = sa.text("""
    SELECT u.id::text AS id, u.username::text AS username, u.email::text AS email,
           u.password_hash, u.password_algo_params, u.status::text AS status,
           u.mfa_required, u.failed_login_count, u.locked_until,
           COALESCE((SELECT array_agg(DISTINCT m.kind::text) FROM mfa_methods m
                     WHERE m.user_id = u.id AND m.confirmed_at IS NOT NULL
                       AND m.revoked_at IS NULL), ARRAY[]::text[]) AS mfa_methods
    FROM users u
    WHERE u.deleted_at IS NULL AND u.id = CAST(:ident AS uuid)
    LIMIT 1
    """)
_SUCCESS_SQL = sa.text(
    "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = :now "
    "WHERE id = CAST(:id AS uuid)"
)
_FAILURE_SQL = sa.text("""
    UPDATE users SET
      failed_login_count = failed_login_count + 1,
      locked_until = CASE WHEN failed_login_count + 1 >= :threshold
                          THEN CAST(:lock_until AS timestamptz) ELSE locked_until END
    WHERE id = CAST(:id AS uuid)
    RETURNING CASE WHEN failed_login_count >= :threshold THEN locked_until END AS locked_until
    """)
_REHASH_SQL = sa.text(
    "UPDATE users SET password_hash = :h, password_algo_params = CAST(:p AS jsonb), "
    "password_changed_at = now() WHERE id = CAST(:id AS uuid)"
)
_REQUIRE_MFA_SQL = sa.text("UPDATE users SET mfa_required = true WHERE id = CAST(:id AS uuid)")


class SqlAlchemyUserRepository:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        record_factory: Callable[..., Any],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._relational = relational
        self._make = record_factory
        self._clock = clock

    async def find_by_identifier(self, identifier: str) -> Any:
        return await self._find(_FIND_SQL, identifier)

    async def find_by_id(self, user_id: str) -> Any:
        return await self._find(_FIND_BY_ID_SQL, user_id)

    async def _find(self, stmt: sa.TextClause, ident: str) -> Any:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(stmt, {"ident": ident})).first()
            await uow.commit()
        if row is None:
            return None
        m = row._mapping
        params = m["password_algo_params"]
        if isinstance(params, str):
            params = json.loads(params)
        return self._make(
            id=m["id"],
            username=m["username"],
            email=m["email"],
            password_hash=m["password_hash"],
            password_algo_params=dict(params),
            status=m["status"],
            mfa_required=m["mfa_required"],
            failed_login_count=m["failed_login_count"],
            locked_until=m["locked_until"],
            mfa_methods=tuple(m["mfa_methods"] or ()),
        )

    async def record_login_success(self, user_id: str) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_SUCCESS_SQL, {"id": user_id, "now": self._clock()})
            await uow.commit()

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        async with self._relational.unit_of_work() as uow:
            row = (
                await uow.session.execute(
                    _FAILURE_SQL,
                    {
                        "id": user_id,
                        "threshold": lockout_threshold,
                        "lock_until": now + lock_duration,
                    },
                )
            ).first()
            await uow.commit()
        return None if row is None else row._mapping["locked_until"]

    async def rehash_password(
        self, user_id: str, *, password_hash: str, algo_params: dict[str, int]
    ) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(
                _REHASH_SQL,
                {"id": user_id, "h": password_hash, "p": json.dumps(algo_params)},
            )
            await uow.commit()

    async def set_mfa_required(self, user_id: str) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_REQUIRE_MFA_SQL, {"id": user_id})
            await uow.commit()


#: The `users` columns a `PATCH` sets (E42-T09): a name sent, `mfa_required` only ever to true
#: (C-12.2), and `active` only from `disabled` (R6), whatever the caller checked before the lock.
_PATCH_USER = sa.text(
    "UPDATE users SET "
    "display_name = CASE WHEN CAST(:set_name AS boolean) THEN CAST(:name AS text) "
    "ELSE display_name END, "
    "mfa_required = mfa_required OR CAST(:require_mfa AS boolean), "
    "status = CASE WHEN CAST(:enable AS boolean) AND status = 'disabled' "
    "THEN 'active'::user_status ELSE status END "
    "WHERE id = CAST(:id AS uuid)"
)
_NO_ROLES: frozenset[str] = frozenset()


def _columns(before: Mapping[str, Any], patch: UserPatch) -> dict[str, bool] | None:
    """The `_PATCH_USER` switches for the columns the patch changes; `None` when it changes none."""
    switches = {
        "set_name": patch.set_display_name and patch.display_name != before["display_name"],
        "require_mfa": patch.require_mfa and not before["mfa_required"],
        "enable": patch.enable and before["status"] == "disabled",
    }
    return switches if any(switches.values()) else None


class SqlAlchemyUserAdminStore:
    """The `User` read model and its locked update (E42-T09, #2649). The update is one
    transaction (R7): lock the user row, then every active-owner grant in key order (the owner lock
    the role and lifecycle stores take, so role and status changes queue and never deadlock);
    read the representation and hand it to the caller's precondition (`If-Match`, R6); apply
    what changes, re-checking the owner floor on the count read under the lock (a target that is
    not active holds no counted owner grant); fire the deferred owner-floor trigger; read the
    result; await the caller's write-ahead audit, bounded (C-2.9, #2510); commit. Any raise
    before the commit rolls it all back. A patch that changes nothing writes and audits nothing."""

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

    async def get_user(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        """The user's `User` representation; `None` when the user does not exist (or is deleted)."""
        async with self._relational.unit_of_work() as uow:
            return await read_user(uow.session, str(user_id))

    async def update_user(
        self,
        user_id: uuid.UUID,
        patch: UserPatch,
        *,
        actor: uuid.UUID,
        check: UserPrecondition,
        audit: UserUpdateAudit,
    ) -> UserUpdate | None:
        """Apply `patch` (new grants record `actor`); `None` if the user does not exist. Raises
        what `check`, the owner-floor check or `audit` raises, or `WriteAheadTimeout` when `audit`
        outlives its bound; each rolls the transaction back, so nothing changes."""
        uid, counted = str(user_id), _NO_ROLES
        wanted = _NO_ROLES if patch.roles is None else patch.roles
        try:
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                if (row := (await s.execute(LOCK_USER, {"id": uid})).first()) is None:
                    return None
                owners = await lock_active_owners(s)
                if (before := await read_user(s, uid)) is None:
                    return None
                check(before)
                roles = frozenset(before["roles"])
                regrant = patch.roles is not None and patch.roles != roles
                columns = _columns(before, patch)
                if not regrant and columns is None:
                    return UserUpdate(user_id, before, before)
                if regrant:
                    counted = counted_roles(str(row[0]), roles)
                    self._owner_floor(counted, wanted, owners)
                    await s.execute(DROP_ROLES, {"id": uid, "roles": sorted(wanted)})
                    grant = {"id": uid, "roles": sorted(wanted), "by": str(actor)}
                    await s.execute(GRANT_ROLES, grant)
                if columns is not None:
                    named: dict[str, object] = {"id": uid, "name": patch.display_name, **columns}
                    await s.execute(_PATCH_USER, named)
                await s.execute(CONSTRAINTS_NOW)  # the floor trigger fires before the audit
                change = UserUpdate(user_id, before, await read_user(s, uid) or before)
                await bounded_write_ahead(audit(change), self._audit_timeout_s)
                await uow.commit()
        except IntegrityError as exc:
            refuse_floor_violation(exc, self._owner_floor, counted, wanted)
            raise
        return change
