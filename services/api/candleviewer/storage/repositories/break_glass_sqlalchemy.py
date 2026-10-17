"""`SqlAlchemyBreakGlassRepository`: Postgres side of the
`candleviewer.auth.break_glass.BreakGlassResetStore` port (E09-S11 #2119, decision R4).
`SqlAlchemyBreakGlassEvents` is the read-only side of
`candleviewer.auth.break_glass_notice.BreakGlassEvents` (slice 6, decision O4; two counts, one
statement each): cv-api constructs only that one, so the running server holds no object that
can reset.

Every other repository call commits its own unit of work, so chaining
`revoke_method`, `revoke_all_for_user` and an event write could leave a half
reset. This runs the whole reset as ONE unit of work: lock the target `users` row
and match the owner-floor predicate of migration 0001, consume the code, revoke
every unrevoked method and live session, insert the critical event, commit once.
A refusal or any error rolls back and changes zero rows. In M10 so `auth` imports
no storage driver (ADR-0003). Static, parameterised statements; the recovery code
arrives as its keyed hash, never in clear, and only the consume statement binds it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, NamedTuple

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_LOCK_OWNER = sa.text(
    "SELECT u.id FROM users u WHERE u.id = CAST(:u AS uuid) AND u.deleted_at IS NULL "
    "AND u.status = 'active' AND EXISTS (SELECT 1 FROM user_roles ur "
    "JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id AND r.name = 'owner' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > :now)) FOR UPDATE OF u"
)
_CONSUME_CODE = sa.text(
    "UPDATE recovery_codes SET used_at = :now WHERE user_id = CAST(:u AS uuid) "
    "AND code_hash = :h AND used_at IS NULL RETURNING id"
)
_REVOKE_METHODS = sa.text(
    "UPDATE mfa_methods SET revoked_at = :now WHERE user_id = CAST(:u AS uuid) "
    "AND revoked_at IS NULL RETURNING id"
)
_REVOKE_SESSIONS = sa.text(
    "UPDATE sessions SET revoked_at = :now, revoked_reason = 'break_glass' "
    "WHERE user_id = CAST(:u AS uuid) AND revoked_at IS NULL RETURNING id"
)
_INSERT_EVENT = sa.text(
    "INSERT INTO system_events (component, kind, severity, message, details, correlation_id, "
    "event_ts) VALUES ('auth', 'break_glass_used', 'critical', :message, "
    "CAST(:details AS jsonb), CAST(:corr AS uuid), :now) RETURNING id"
)
_MESSAGE = (
    "Break-glass used: the Owner's MFA methods and sessions were revoked offline (SR-023); "
    "the Owner must enrol TOTP again"
)
_UNRESOLVED = sa.text(
    "SELECT count(*) FROM system_events WHERE component = 'auth' "
    "AND kind = 'break_glass_used' AND resolved_at IS NULL"
)
#: One `auth.break_glass_attempt` row per CLI run (its write-ahead first record), whatever the
#: run's outcome. `audit_log` is append-only, so the count only rises. Served by `ix_audit_action`.
_ATTEMPTS = sa.text("SELECT count(*) FROM audit_log WHERE action = 'auth.break_glass_attempt'")

#: The port's refusal channel (`auth.break_glass.BreakGlassStoreRefusal`), typed here
#: as a `Literal` because `storage` may not import the `auth` enum.
BreakGlassStoreRefusal = Literal["not_owner", "recovery_code_invalid"]


class BreakGlassResetRow(NamedTuple):
    methods_revoked: int
    sessions_revoked: int
    system_event_id: int


class SqlAlchemyBreakGlassRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def reset_owner_mfa(
        self,
        target_user_id: str,
        *,
        now: datetime,
        recovery_code_hash: str | None,
        correlation_id: str,
    ) -> BreakGlassResetRow | BreakGlassStoreRefusal:
        """`not_owner` / `recovery_code_invalid` after rolling back, else the counts."""
        params = {"u": target_user_id, "now": now}  # the lock and revokes: no hash bind
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            refusal: BreakGlassStoreRefusal | None = None
            if (await run(_LOCK_OWNER, params)).first() is None:
                refusal = "not_owner"
            elif (
                recovery_code_hash is not None
                and not (await run(_CONSUME_CODE, {**params, "h": recovery_code_hash})).all()
            ):
                refusal = "recovery_code_invalid"
            if refusal is not None:
                await uow.rollback()
                return refusal
            methods = len((await run(_REVOKE_METHODS, params)).all())
            sessions = len((await run(_REVOKE_SESSIONS, params)).all())
            details = {
                "target_user_id": target_user_id,
                "methods_revoked": methods,
                "sessions_revoked": sessions,
                "recovery_code_consumed": recovery_code_hash is not None,
            }
            event = await run(
                _INSERT_EVENT,
                {
                    "message": _MESSAGE,
                    "details": json.dumps(details, sort_keys=True),
                    "corr": correlation_id,
                    "now": now,
                },
            )
            row = BreakGlassResetRow(methods, sessions, int(event.scalar_one()))
            await uow.commit()
        return row


class SqlAlchemyBreakGlassEvents:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def unresolved_break_glass_count(self) -> int:
        """How many `auth`/`break_glass_used` events are still unresolved: one count."""
        async with self._relational.unit_of_work() as uow:
            return int((await uow.session.execute(_UNRESOLVED)).scalar_one())

    async def break_glass_attempt_count(self) -> int:
        """How many CLI runs `audit_log` has a record of: its `auth.break_glass_attempt` rows."""
        async with self._relational.unit_of_work() as uow:
            return int((await uow.session.execute(_ATTEMPTS)).scalar_one())
