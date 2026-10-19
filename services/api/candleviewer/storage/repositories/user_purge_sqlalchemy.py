"""`SqlAlchemyUserPurgeStore` - the deferred PII purge on Postgres (E42-T10 #2650, #965 O6).

`schedule` (behind `DELETE /users/{userId}?purge=true`, after the E42-T04 disable) and `anonymise`
(the reaper's, one user per call) each run one transaction: bound every lock wait
(`lock_timeout`); lock the user row (`FOR NO KEY UPDATE`, as the lifecycle store does) and re-check
it; write; run the deferred constraints (the owner-floor trigger fires before any record); write the
record ahead of the commit (`users.delete` or `users.anonymise`, R5), bounded by `audit_timeout_s`;
commit. A refused or late record rolls everything back (`PurgeAuditUnavailableError`). A commit that
then fails or is cancelled may have landed, so its record is closed by a `failure` one, reason
`outcome_unknown`, best effort (C-2.9), and the error leaves as it was raised.

`anonymise` trusts nothing the batch read (`due`) saw: under the lock it acts only on a `disabled`
user whose `purge_after` has passed and who is not anonymised yet (UL-F5), so a re-enable or a
cancelled purge that commits in between keeps the user as they are. It never reads a PII column and
never touches `audit_log` (C-5.7, C-12.8). `cancel_pending_purge` is #965 R6's cancel for E42-T09's
enable path, run inside that path's own transaction. The audit emitter is injected: storage (M10)
may not import audit (M19).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.storage.repositories.owner_floor_sqlalchemy import CONSTRAINTS_NOW
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_purge import (
    PurgeAuditEmitter,
    PurgeAuditUnavailableError,
    PurgeSchedule,
    PurgeUserNotDisabledError,
    PurgeUserNotFoundError,
    anonymised_email,
    surrogate,
)
from candleviewer.storage.retention.policy import USERS_PURGE_AFTER_DAYS

#: Bounds each record, as the account-access store bounds its own (the row lock is held meanwhile).
AUDIT_TIMEOUT_S = 2.0
#: Bounds each lock wait; unbounded, it would last the 30 s `statement_timeout`.
LOCK_TIMEOUT_MS = 5000
#: The most users one `due` read returns; the reaper takes the backlog batch by batch.
MAX_ANONYMISE_BATCH = 50
#: The reaper's actor (SR-062: a system actor, never a user).
ACTOR: Final = "system:user-purge"
#: The closing record's reason: the commit was sent and failed, so it may have gone through.
OUTCOME_UNKNOWN: Final = "outcome_unknown"
_DELETE, _ANONYMISE_ACTION = "users.delete", "users.anonymise"

_LOCK_TIMEOUT = sa.text("SELECT set_config('lock_timeout', :timeout, true)")
_LOCK_FOR_SCHEDULE = sa.text(
    "SELECT status::text, purge_after, anonymised_at FROM users "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL FOR NO KEY UPDATE"
)
_SCHEDULE = sa.text("UPDATE users SET purge_after = :purge_after WHERE id = CAST(:id AS uuid)")
# The reaper's batch: oldest first, so a backlog drains in the order it fell due.
_DUE = sa.text(
    "SELECT id FROM users WHERE status = 'disabled' AND anonymised_at IS NULL "
    "AND purge_after <= :now ORDER BY purge_after, id LIMIT :limit"
)
# No `deleted_at` filter: a scheduled purge runs even if the row is soft-deleted later.
_LOCK_FOR_ANONYMISE = sa.text(
    "SELECT status::text, purge_after, anonymised_at FROM users "
    "WHERE id = CAST(:id AS uuid) FOR NO KEY UPDATE"
)
_ANONYMISE = sa.text(
    "UPDATE users SET username = :username, email = :email, display_name = NULL, "
    "last_login_ip = NULL, anonymised_at = :now WHERE id = CAST(:id AS uuid)"
)
_SCRUB_SESSIONS = sa.text(
    "UPDATE sessions SET ip = NULL, user_agent = NULL, device_label = NULL, "
    "tailscale_node = NULL WHERE user_id = CAST(:id AS uuid) RETURNING id"
)
_PENDING = sa.text(
    "SELECT purge_after FROM users WHERE id = CAST(:id AS uuid) "
    "AND purge_after IS NOT NULL AND anonymised_at IS NULL FOR NO KEY UPDATE"
)
_CANCEL = sa.text("UPDATE users SET purge_after = NULL WHERE id = CAST(:id AS uuid)")

#: A record's `before_state` and `after_state`: status, times and a count, never PII (O6).
_States = tuple[dict[str, Any], dict[str, Any]]


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _uuid(value: object) -> uuid.UUID:
    """asyncpg returns its own `uuid.UUID` subclass, which orjson refuses: make it plain."""
    return uuid.UUID(str(value))


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _due(row: Any, now: datetime) -> bool:
    """UL-F5, under the user-row lock: disabled, scheduled, the date passed, not yet anonymised."""
    status, purge_after, anonymised_at = row
    return (
        status == "disabled"
        and anonymised_at is None
        and purge_after is not None
        and purge_after <= now
    )


async def cancel_pending_purge(session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    """#965 R6, for E42-T09's enable path: in that path's own transaction, under its user-row
    lock and ahead of its `users.enable` record, which should name the returned date. Clears a
    pending purge and returns its `purge_after`; `None`, with nothing written, when none is pending
    (never scheduled, cancelled already, or run: `anonymised_at` set, and nothing is restored).
    Commits nothing: the caller's transaction does."""
    uid = {"id": str(user_id)}
    row = (await session.execute(_PENDING, uid)).first()
    if row is None:
        return None
    await session.execute(_CANCEL, uid)
    pending: datetime = row[0]
    return pending


class SqlAlchemyUserPurgeStore:
    """Postgres store of the deferred PII purge: its schedule and the reaper's reads and writes."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        audit: PurgeAuditEmitter,
        clock: Callable[[], datetime],
        audit_timeout_s: float = AUDIT_TIMEOUT_S,
        lock_timeout_ms: int = LOCK_TIMEOUT_MS,
    ) -> None:
        """`clock` is the app's (tz-aware UTC); `purge_after` is its time plus the window."""
        self._relational, self._audit, self._clock = relational, audit, clock
        self._audit_timeout_s = audit_timeout_s
        self._lock_timeout = f"{lock_timeout_ms}ms"
        self._window = timedelta(days=USERS_PURGE_AFTER_DAYS)

    async def schedule(
        self,
        user_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> PurgeSchedule:
        """S14: schedule a disabled user's purge `USERS_PURGE_AFTER_DAYS` from now, `users.delete`
        ahead, naming the actor, their session and the request. A purge already scheduled or run
        is kept as it is (no second record). Raises `PurgeUserNotFoundError`,
        `PurgeUserNotDisabledError` or `PurgeAuditUnavailableError` with nothing changed, or what
        the driver raises (a failed commit's outcome is unknown, and its record is closed)."""
        uid, purge_after = str(user_id), self._clock() + self._window
        who = {
            "actor_label": str(actor_user_id),
            "actor_user_id": actor_user_id,
            "session_id": session_id,
            "request_id": request_id,
        }
        written: _States | None = None  # recorded ahead, the commit not confirmed yet
        try:
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                await s.execute(_LOCK_TIMEOUT, {"timeout": self._lock_timeout})
                row = (await s.execute(_LOCK_FOR_SCHEDULE, {"id": uid})).first()
                if row is None:
                    raise PurgeUserNotFoundError(uid)
                status, scheduled, _ = row
                if status != "disabled":
                    raise PurgeUserNotDisabledError(str(status))
                if scheduled is not None:  # scheduled or run already: its first date stands
                    return PurgeSchedule(user_id, scheduled, changed=False)
                await s.execute(_SCHEDULE, {"id": uid, "purge_after": purge_after})
                await s.execute(CONSTRAINTS_NOW)
                states: _States = (
                    {"status": status, "purge_after": None},
                    {"status": status, "purge_after": purge_after.isoformat()},
                )
                await self._write_ahead(_DELETE, uid, states, who)
                written = states
                await uow.commit()
                written = None
        except BaseException:
            if written is not None:
                await self._close(_DELETE, uid, written, who)
            raise
        return PurgeSchedule(user_id, purge_after, changed=True)

    async def due(self, limit: int) -> tuple[uuid.UUID, ...]:
        """S13: at most `limit` users whose purge is due now, oldest date first. Takes no lock:
        `anonymise` re-checks each one under its own."""
        if not 1 <= limit <= MAX_ANONYMISE_BATCH:
            raise ValueError(f"limit must be 1..{MAX_ANONYMISE_BATCH}, got {limit}")
        async with self._relational.unit_of_work() as uow:
            params = {"now": self._clock(), "limit": limit}
            rows = (await uow.session.execute(_DUE, params)).all()
        return tuple(_uuid(r[0]) for r in rows)

    async def anonymise(self, user_id: uuid.UUID) -> bool:
        """S13: anonymise one user (O6) in one transaction, `users.anonymise` ahead, if the locked
        re-check still finds the purge due; True once committed, False when it found nothing to do
        (re-enabled, cancelled, not due, or run already). Raises as `schedule` does."""
        uid, now = str(user_id), self._clock()
        who = {"actor_label": ACTOR, "actor_user_id": None, "session_id": None, "request_id": None}
        written: _States | None = None
        try:
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                await s.execute(_LOCK_TIMEOUT, {"timeout": self._lock_timeout})
                row = (await s.execute(_LOCK_FOR_ANONYMISE, {"id": uid})).first()
                if row is None or not _due(row, now):
                    return False
                status, purge_after, _ = row
                await s.execute(
                    _ANONYMISE,
                    {
                        "id": uid,
                        "username": surrogate(user_id),
                        "email": anonymised_email(user_id),
                        "now": now,
                    },
                )
                scrubbed = len((await s.execute(_SCRUB_SESSIONS, {"id": uid})).all())
                await s.execute(CONSTRAINTS_NOW)
                before = {"status": status, "purge_after": _iso(purge_after), "anonymised_at": None}
                after = before | {"anonymised_at": now.isoformat(), "sessions_scrubbed": scrubbed}
                await self._write_ahead(_ANONYMISE_ACTION, uid, (before, after), who)
                written = (before, after)
                await uow.commit()
                written = None
        except BaseException:
            if written is not None:
                await self._close(_ANONYMISE_ACTION, uid, written, who)
            raise
        return True

    async def _write_ahead(
        self, action: str, user_id: str, states: _States, who: dict[str, Any]
    ) -> None:
        """A refused record was never written. After a timeout or a cancellation it is unknown
        whether it landed (`AuditWriter.emit` finishes an append it has started), and nothing
        closes it: the transaction rolls back, and the user row is the truth."""
        try:
            await self._emit(action, user_id, states, who, "success", "warning", None)
        except Exception as exc:  # the writer's refusal (WAL full, stopped) or the bound
            raise PurgeAuditUnavailableError(user_id) from exc

    async def _close(self, action: str, user_id: str, states: _States, who: dict[str, Any]) -> None:
        """Best effort; it never replaces the commit's own error."""
        try:
            closing = (states[0], None)
            await self._emit(action, user_id, closing, who, "failure", "error", OUTCOME_UNKNOWN)
        except Exception:
            _log().exception("user purge closing audit record not written", action=action)

    async def _emit(
        self,
        action: str,
        user_id: str,
        states: tuple[dict[str, Any], dict[str, Any] | None],
        who: dict[str, Any],
        outcome: str,
        severity: str,
        reason: str | None,
    ) -> None:
        async with asyncio.timeout(self._audit_timeout_s):
            await self._audit.emit(
                action,
                **who,
                object_kind="user",
                object_id=user_id,
                outcome=outcome,
                severity=severity,
                reason=reason,
                before_state=states[0],
                after_state=states[1],
            )
