"""`SqlAlchemySessionRepository` — concrete Postgres implementation of
`candleviewer.auth.session_repository.SessionRepository` (E09-S03, QA #1634).

Lives in M10 (`storage`, allowed to import `sqlalchemy`) so `candleviewer.auth`
never imports a storage driver (ADR-0003). Structurally compatible with the
Protocol; it only needs the plain row model `SessionRecord` (same pattern as
`audit_sqlalchemy.py`). Every statement is parameterised. Revocation is a
single conditional `UPDATE ... WHERE revoked_at IS NULL RETURNING`, which is
what makes `SessionService.refresh()`'s claim-by-revoke race-free and keeps
the first revocation reason immutable (INV-B16-d). The step-up columns are
written only from a read taken under the row lock (`update_step_up_state`)
or by one conditional statement (`consume_step_up_key`), never from a stale
copy of the row (#2304). A session is inserted only for an `active` user, read
under the user-row lock in the insert's transaction, and the reads by id and by
refresh hash carry the user's status (#2911).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: `auth.session_repository.StepUpState`, restated: storage may not import `auth` (C-3.1).
_StepUpState = tuple[dict[str, datetime], int, datetime | None]

# Static column list (no caller data is ever interpolated into any statement).
_COLUMNS = (
    "id::text AS id, user_id::text AS user_id, refresh_token_hash, "
    "access_token_jti::text AS access_token_jti, issued_at, last_seen_at, expires_at, "
    "revoked_at, revoked_reason, ip::text AS ip, user_agent, device_label, is_electron, "
    "mfa_satisfied_at, idle_timeout_s, step_up_elevations::text AS step_up_elevations, "
    "step_up_failures, readonly_until"
)

# #2911: the user row's status, read `FOR SHARE` in the insert's own transaction. It conflicts
# with the disable's `FOR NO KEY UPDATE` (`owner_floor_sqlalchemy.LOCK_USER`), so a mint and a
# disable queue on the user row, user row first as in the disable: an insert that commits first
# is revoked by the disable's session revoke, and one that waits reads `disabled` and is refused.
_LOCK_USER_SQL = sa.text(
    "SELECT status::text AS status FROM users WHERE id = CAST(:id AS uuid) "
    "AND deleted_at IS NULL FOR SHARE"
)
_INSERT_SQL = sa.text("""
    INSERT INTO sessions (id, user_id, refresh_token_hash, access_token_jti, issued_at,
        last_seen_at, expires_at, revoked_at, revoked_reason, ip, user_agent, device_label,
        is_electron, mfa_satisfied_at, idle_timeout_s)
    VALUES (CAST(:id AS uuid), CAST(:user_id AS uuid), :refresh_token_hash,
        CAST(:access_token_jti AS uuid), :issued_at, :last_seen_at, :expires_at, NULL, NULL,
        CAST(:ip AS inet), :user_agent, :device_label, :is_electron, :mfa_satisfied_at,
        :idle_timeout_s)
    """)


# #2911: the owner's status in the same statement as the row (a `users_pkey` probe, no extra
# round trip); NULL when the user row is gone.
_USER_STATUS = (
    "(SELECT u.status::text FROM users u WHERE u.id = sessions.user_id "
    "AND u.deleted_at IS NULL) AS user_status"
)


def _sql(template: str) -> sa.TextClause:
    """Expand the static placeholders (never caller data) into a statement."""
    return sa.text(template.replace("@COLS@", _COLUMNS).replace("@STATUS@", _USER_STATUS))


_BY_ID_SQL = _sql("SELECT @COLS@, @STATUS@ FROM sessions WHERE id = CAST(:id AS uuid)")
_BY_HASH_SQL = _sql("SELECT @COLS@, @STATUS@ FROM sessions WHERE refresh_token_hash = :h")
_BY_JTI_SQL = _sql("SELECT @COLS@ FROM sessions WHERE access_token_jti = CAST(:j AS uuid)")
_LIVE_BY_USER_SQL = _sql(
    "SELECT @COLS@ FROM sessions WHERE user_id = CAST(:u AS uuid) "
    "AND revoked_at IS NULL ORDER BY issued_at DESC"
)
_TOUCH_SQL = _sql(
    "UPDATE sessions SET last_seen_at = :now WHERE id = CAST(:id AS uuid) "
    "AND revoked_at IS NULL RETURNING @COLS@"
)
_LIFT_IDLE_LOCK_SQL = _sql(
    "UPDATE sessions SET last_seen_at = :now, step_up_elevations = '{}'::jsonb "
    "WHERE id = CAST(:id AS uuid) AND revoked_at IS NULL RETURNING @COLS@"
)
_REVOKE_SQL = _sql(
    "UPDATE sessions SET revoked_at = :now, revoked_reason = :reason "
    "WHERE id = CAST(:id AS uuid) AND revoked_at IS NULL RETURNING @COLS@"
)
_REVOKE_ALL_SQL = _sql(
    "UPDATE sessions SET revoked_at = :now, revoked_reason = :reason "
    "WHERE user_id = CAST(:u AS uuid) AND revoked_at IS NULL "
    "AND (CAST(:except_id AS uuid) IS NULL OR id <> CAST(:except_id AS uuid)) "
    "RETURNING @COLS@"
)
# #2304: the step-up columns are only ever rewritten from a read taken under the row lock, in the
# same transaction (`update_step_up_state`). `FOR NO KEY UPDATE` is the lock an UPDATE of non-key
# columns takes, so every other write of the row (a grant consume, an idle unlock, a revoke)
# queues behind it or ahead of it, and none of them is undone by a stale copy of the row.
_LOCK_STEP_UP_SQL = sa.text(
    "SELECT step_up_elevations::text AS step_up_elevations, step_up_failures, readonly_until "
    "FROM sessions WHERE id = CAST(:id AS uuid) AND revoked_at IS NULL FOR NO KEY UPDATE"
)
_STEP_UP_SQL = _sql(
    "UPDATE sessions SET step_up_elevations = CAST(:elevations AS jsonb), "
    "step_up_failures = :failures, readonly_until = :readonly_until "
    "WHERE id = CAST(:id AS uuid) AND revoked_at IS NULL RETURNING @COLS@"
)
# #2304: consume a one-shot grant in one conditional statement. A concurrent consumer of the
# same key re-evaluates the predicate after the first commits, finds the key gone and updates
# no row, so the grant is used once.
_CONSUME_STEP_UP_SQL = _sql(
    "UPDATE sessions SET step_up_elevations = step_up_elevations - CAST(:key AS text) "
    "WHERE id = CAST(:id AS uuid) AND revoked_at IS NULL "
    "AND CAST(step_up_elevations ->> CAST(:key AS text) AS timestamptz) > :now "
    "RETURNING @COLS@"
)
_LINK_SQL = sa.text(
    "INSERT INTO sessions_rotation (prev_session_id, next_session_id) "
    "VALUES (CAST(:prev AS uuid), CAST(:next AS uuid))"
)
_FAMILY_SQL = sa.text("""
    WITH RECURSIVE fam(id) AS (
        SELECT CAST(:id AS uuid)
        UNION
        SELECT CASE WHEN r.prev_session_id = f.id THEN r.next_session_id
                    ELSE r.prev_session_id END
        FROM fam f
        JOIN sessions_rotation r ON r.prev_session_id = f.id OR r.next_session_id = f.id
    )
    SELECT id::text AS id FROM fam
    """)


def _elevations(stored: str | None) -> dict[str, datetime]:
    """`step_up_elevations` as read (`::text`): key -> ISO-8601 expiry."""
    return {k: datetime.fromisoformat(v) for k, v in json.loads(stored or "{}").items()}


def row_to_fields(row: Any) -> dict[str, Any]:
    """Map a result row (see `_COLUMNS`) to `SessionRecord` constructor kwargs."""
    m = row._mapping
    return dict(
        id=uuid.UUID(m["id"]),
        user_id=uuid.UUID(m["user_id"]),
        refresh_token_hash=m["refresh_token_hash"],
        access_token_jti=uuid.UUID(m["access_token_jti"]) if m["access_token_jti"] else None,
        issued_at=m["issued_at"],
        last_seen_at=m["last_seen_at"],
        expires_at=m["expires_at"],
        revoked_at=m["revoked_at"],
        revoked_reason=m["revoked_reason"],
        ip=m["ip"].split("/")[0] if m["ip"] else None,
        user_agent=m["user_agent"],
        device_label=m["device_label"],
        is_electron=m["is_electron"],
        mfa_satisfied_at=m["mfa_satisfied_at"],
        idle_timeout_s=m["idle_timeout_s"],
        step_up_elevations=_elevations(m["step_up_elevations"]),
        step_up_failures=m["step_up_failures"],
        readonly_until=m["readonly_until"],
        user_status=m.get("user_status"),
    )


class SqlAlchemySessionRepository:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        record_factory: Callable[..., Any],
    ) -> None:
        self._relational = relational
        self._make = record_factory

    async def create_session(self, session: Any) -> Any:
        """Insert *session*, or nothing and `None` unless its user is `active` (#2911)."""
        async with self._relational.unit_of_work() as uow:
            user = (await uow.session.execute(_LOCK_USER_SQL, {"id": str(session.user_id)})).first()
            if user is None or user._mapping["status"] != "active":
                return None  # rolled back: the lock goes, nothing was written
            await uow.session.execute(
                _INSERT_SQL,
                {
                    "id": str(session.id),
                    "user_id": str(session.user_id),
                    "refresh_token_hash": session.refresh_token_hash,
                    "access_token_jti": (
                        str(session.access_token_jti) if session.access_token_jti else None
                    ),
                    "issued_at": session.issued_at,
                    "last_seen_at": session.last_seen_at,
                    "expires_at": session.expires_at,
                    "ip": session.ip,
                    "user_agent": session.user_agent,
                    "device_label": session.device_label,
                    "is_electron": session.is_electron,
                    "mfa_satisfied_at": session.mfa_satisfied_at,
                    "idle_timeout_s": session.idle_timeout_s,
                },
            )
            await uow.commit()
        return session

    async def _one(self, stmt: sa.TextClause, params: dict[str, Any]) -> Any:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(stmt, params)).first()
            await uow.commit()
        return None if row is None else self._make(**row_to_fields(row))

    async def _many(self, stmt: sa.TextClause, params: dict[str, Any]) -> tuple[Any, ...]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).all()
            await uow.commit()
        return tuple(self._make(**row_to_fields(r)) for r in rows)

    async def find_by_id(self, session_id: str) -> Any:
        return await self._one(_BY_ID_SQL, {"id": session_id})

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> Any:
        return await self._one(_BY_HASH_SQL, {"h": refresh_token_hash})

    async def find_by_access_token_jti(self, access_token_jti: str) -> Any:
        return await self._one(_BY_JTI_SQL, {"j": access_token_jti})

    async def find_live_by_user(self, user_id: str) -> tuple[Any, ...]:
        return await self._many(_LIVE_BY_USER_SQL, {"u": user_id})

    async def touch_last_seen(self, session_id: str, *, now: datetime) -> Any:
        return await self._one(_TOUCH_SQL, {"id": session_id, "now": now})

    async def lift_idle_lock(self, session_id: str, *, now: datetime) -> Any:
        return await self._one(_LIFT_IDLE_LOCK_SQL, {"id": session_id, "now": now})

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> Any:
        return await self._one(_REVOKE_SQL, {"id": session_id, "reason": reason, "now": now})

    async def revoke_all_for_user(
        self, user_id: str, *, reason: str, now: datetime, except_session_id: str | None = None
    ) -> tuple[Any, ...]:
        return await self._many(
            _REVOKE_ALL_SQL,
            {"u": user_id, "reason": reason, "now": now, "except_id": except_session_id},
        )

    async def update_step_up_state(
        self, session_id: str, change: Callable[[_StepUpState], _StepUpState]
    ) -> Any:
        async with self._relational.unit_of_work() as uow:
            locked = (await uow.session.execute(_LOCK_STEP_UP_SQL, {"id": session_id})).first()
            if locked is None:  # revoked or absent: `change` is not called, nothing is written
                return None
            m = locked._mapping
            elevations, failures, readonly_until = change(
                (_elevations(m["step_up_elevations"]), m["step_up_failures"], m["readonly_until"])
            )
            payload = json.dumps({k: v.isoformat() for k, v in elevations.items()})
            params = {
                "id": session_id,
                "elevations": payload,
                "failures": failures,
                "readonly_until": readonly_until,
            }
            row = (await uow.session.execute(_STEP_UP_SQL, params)).first()
            await uow.commit()
        return None if row is None else self._make(**row_to_fields(row))

    async def consume_step_up_key(self, session_id: str, *, key: str, now: datetime) -> Any:
        return await self._one(_CONSUME_STEP_UP_SQL, {"id": session_id, "key": key, "now": now})

    async def link_rotation(self, *, prev_session_id: str, next_session_id: str) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_LINK_SQL, {"prev": prev_session_id, "next": next_session_id})
            await uow.commit()

    async def walk_rotation_family(self, session_id: str) -> tuple[str, ...]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_FAMILY_SQL, {"id": session_id})).all()
            await uow.commit()
        return tuple(str(r._mapping["id"]) for r in rows)
