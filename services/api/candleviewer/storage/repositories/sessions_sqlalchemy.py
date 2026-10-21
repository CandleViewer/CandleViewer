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
copy of the row (#2304). A session is inserted only for a user who exists and is
not `disabled`, read under the user-row lock in the insert's transaction, and the
reads by id and by refresh hash carry the user's status (#2911). Every record read
carries the row's view-as context (#3085, `0042_sessions_view_as`). The insert writes
the context a record carries (a refresh carries it to the successor row), and the
`ViewAsSessionStore` writes (`auth/view_as.py`) are one conditional statement each. The
insert also writes the step-up strikes and read-only window a refresh carries from the
claim's row (#4051): a new row, from a revoked source row whose step-up columns no writer
can change (`_STEP_UP_SQL` needs `revoked_at IS NULL`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: `auth.session_repository.StepUpState`, restated: storage may not import `auth` (C-3.1).
_StepUpState = tuple[dict[str, datetime], int, datetime | None]

# Static column list (no caller data is ever interpolated into any statement). Every read and
# every `RETURNING` that builds a record selects all of it, the view-as columns (#3085) included.
_COLUMNS = (
    "id::text AS id, user_id::text AS user_id, refresh_token_hash, "
    "access_token_jti::text AS access_token_jti, issued_at, last_seen_at, expires_at, "
    "revoked_at, revoked_reason, ip::text AS ip, user_agent, device_label, is_electron, "
    "mfa_satisfied_at, idle_timeout_s, step_up_elevations::text AS step_up_elevations, "
    "step_up_failures, readonly_until, view_as_context_id::text AS view_as_context_id, "
    "view_as_target_user_id::text AS view_as_target_user_id, view_as_started_at, "
    "view_as_expires_at, view_as_ended_at, view_as_end_recorded_at, view_as_cleared_at, "
    "view_as_end_reason"
)

# #2911: the user row's status, read `FOR SHARE` in the insert's own transaction. It conflicts
# with the disable's `FOR NO KEY UPDATE` (`owner_floor_sqlalchemy.LOCK_USER`), so a mint and a
# disable queue on the user row, user row first as in the disable: an insert that commits first
# is revoked by the disable's session revoke, and one that waits reads `disabled` and is refused.
_LOCK_USER_SQL = sa.text(
    "SELECT status::text AS status FROM users WHERE id = CAST(:id AS uuid) "
    "AND deleted_at IS NULL FOR SHARE"
)
# #3085: a record's view-as context goes in with it (eight NULLs when it holds none), so the
# successor a refresh mints carries the context as the claim returned it (SR-013).
_INSERT_SQL = sa.text("""
    INSERT INTO sessions (id, user_id, refresh_token_hash, access_token_jti, issued_at,
        last_seen_at, expires_at, revoked_at, revoked_reason, ip, user_agent, device_label,
        is_electron, mfa_satisfied_at, idle_timeout_s, view_as_context_id,
        view_as_target_user_id, view_as_started_at, view_as_expires_at, view_as_ended_at,
        view_as_end_recorded_at, view_as_cleared_at, view_as_end_reason, step_up_failures,
        readonly_until)
    VALUES (CAST(:id AS uuid), CAST(:user_id AS uuid), :refresh_token_hash,
        CAST(:access_token_jti AS uuid), :issued_at, :last_seen_at, :expires_at, NULL, NULL,
        CAST(:ip AS inet), :user_agent, :device_label, :is_electron, :mfa_satisfied_at,
        :idle_timeout_s, CAST(:view_as_context_id AS uuid),
        CAST(:view_as_target_user_id AS uuid), :view_as_started_at, :view_as_expires_at,
        :view_as_ended_at, :view_as_end_recorded_at, :view_as_cleared_at, :view_as_end_reason,
        :step_up_failures, :readonly_until)
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
#: Activity never lifts a lock (#2300): the row must still be unlocked at `:now`
#: (`SessionRecord.is_idle_locked` is `last_seen_at + idle_timeout_s <= now`).
_TOUCH_SQL = _sql(
    "UPDATE sessions SET last_seen_at = :now WHERE id = CAST(:id AS uuid) "
    "AND revoked_at IS NULL AND last_seen_at + make_interval(secs => idle_timeout_s) > :now "
    "RETURNING @COLS@"
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

# #3085, `auth.view_as.ViewAsSessionStore`: each write is one conditional UPDATE, exactly as the
# Protocol's docstrings state it, so of two racing writers the row lock lets one apply and the other
# finds its condition gone (None). Each RETURNING builds its record through `row_to_fields`, which
# validates the context. A start overwrites all eight columns, the end ones with NULL.
_VIEW_AS_START_SQL = _sql(
    "UPDATE sessions SET view_as_context_id = CAST(:context_id AS uuid), "
    "view_as_target_user_id = CAST(:target_user_id AS uuid), view_as_started_at = :started_at, "
    "view_as_expires_at = :view_as_expires_at, view_as_ended_at = NULL, view_as_end_reason = NULL, "
    "view_as_end_recorded_at = NULL, view_as_cleared_at = NULL "
    "WHERE id = CAST(:id AS uuid) AND revoked_at IS NULL AND expires_at > :now "
    "AND (view_as_context_id IS NULL "
    "OR (view_as_cleared_at IS NOT NULL AND view_as_end_recorded_at IS NOT NULL)) RETURNING @COLS@"
)
# An end applies to a revoked row only while no other unrevoked row holds its context: a refresh
# revokes the row but its successor carries the context on, so a stale end reaching the rotated copy
# would spend the context's one keyed record on it, early. Until the successor's insert commits (the
# gap `SessionService.refresh` bounds) the rotated row alone holds it and is ended; so is an orphan
# (no successor came) or a logged-out head, as the sweeper does. `o.id <> sessions.id` keeps the row
# from counting as its own holder.
_VIEW_AS_END_SQL = _sql(
    "UPDATE sessions SET view_as_ended_at = :ended_at, view_as_end_reason = :reason "
    "WHERE id = CAST(:id AS uuid) AND view_as_context_id = CAST(:context_id AS uuid) "
    "AND view_as_ended_at IS NULL AND (revoked_at IS NULL OR NOT EXISTS (SELECT 1 FROM sessions o "
    "WHERE o.view_as_context_id = sessions.view_as_context_id AND o.id <> sessions.id "
    "AND o.revoked_at IS NULL)) RETURNING @COLS@"
)
# RETURNING sees the row as updated, so whether this call set the end comes from `prev`: the row as
# locked before the update. Joined in FROM, `prev` runs before the update, and a racing write that
# holds the row makes it wait and then read the row as that write left it (READ COMMITTED returns
# a locked row's newest version). Its columns are renamed so the unqualified `@COLS@` stay
# unambiguous.
_VIEW_AS_LEAVE_SQL = _sql(
    "WITH prev AS (SELECT id AS prev_id, view_as_ended_at AS prev_ended_at FROM sessions "
    "WHERE id = CAST(:id AS uuid) FOR NO KEY UPDATE) "
    "UPDATE sessions SET view_as_ended_at = COALESCE(view_as_ended_at, :ended_at), "
    "view_as_end_reason = COALESCE(view_as_end_reason, :reason), view_as_cleared_at = :now "
    "FROM prev WHERE id = prev.prev_id AND view_as_context_id = CAST(:context_id AS uuid) "
    "AND view_as_cleared_at IS NULL AND revoked_at IS NULL "
    "RETURNING @COLS@, prev.prev_ended_at IS NULL AS ended_now"
)
_VIEW_AS_CLEAR_SQL = _sql(
    "UPDATE sessions SET view_as_cleared_at = :now "
    "WHERE id = CAST(:id AS uuid) AND view_as_context_id = CAST(:context_id AS uuid) "
    "AND view_as_ended_at IS NOT NULL AND view_as_cleared_at IS NULL RETURNING @COLS@"
)
_VIEW_AS_RECORDED_SQL = _sql(
    "UPDATE sessions SET view_as_end_recorded_at = :now "
    "WHERE id = CAST(:id AS uuid) AND view_as_context_id = CAST(:context_id AS uuid) "
    "AND view_as_ended_at IS NOT NULL AND view_as_end_recorded_at IS NULL RETURNING @COLS@"
)
# The sweeper's read. The first two conditions are `ix_sessions_view_as_due`'s predicate, which
# serves the scan in `ORDER BY` order; the NOT EXISTS probes `ix_sessions_view_as_context`. A row a
# refresh rotated keeps a copy of the context its successor carries (one row per refresh during a
# view, Owner-only), unrecorded, so it stays in that index and each scan steps past it here; it
# comes due only once no row carries the context (the last carrier rotated `:cutoff` or earlier).
# Nothing deletes `sessions` rows today (the 30-day purge is #3223 L2), so the copies stay, and they
# also sit in `ix_sessions_view_as_target`, which both live reads walk, filtered by their
# `revoked_at IS NULL`. A row revoked `rotated` with no `revoked_at` would be live: it carries.
_VIEW_AS_DUE_SQL = _sql(
    "SELECT @COLS@ FROM sessions s "
    "WHERE s.view_as_context_id IS NOT NULL AND s.view_as_end_recorded_at IS NULL "
    "AND (s.view_as_ended_at IS NOT NULL OR s.view_as_expires_at <= :now "
    "OR s.revoked_at IS NOT NULL OR s.expires_at <= :now) "
    "AND (s.revoked_reason IS DISTINCT FROM 'rotated' OR NOT EXISTS (SELECT 1 FROM sessions o "
    "WHERE o.view_as_context_id = s.view_as_context_id AND (o.revoked_reason IS DISTINCT FROM "
    "'rotated' OR o.revoked_at IS NULL OR o.revoked_at > :cutoff))) "
    "ORDER BY s.view_as_expires_at LIMIT :limit"
)
_VIEW_AS_LIVE_SQL = _sql(
    "SELECT @COLS@ FROM sessions WHERE view_as_context_id IS NOT NULL "
    "AND view_as_ended_at IS NULL AND revoked_at IS NULL ORDER BY view_as_expires_at LIMIT :limit"
)
_VIEW_AS_LIVE_BY_TARGET_SQL = _sql(
    "SELECT @COLS@ FROM sessions WHERE view_as_target_user_id = CAST(:target AS uuid) "
    "AND view_as_context_id IS NOT NULL AND view_as_ended_at IS NULL AND revoked_at IS NULL"
)
_VIEW_AS_LIVE_BY_VIEWER_SQL = _sql(
    "SELECT @COLS@ FROM sessions WHERE user_id = CAST(:viewer AS uuid) "
    "AND view_as_context_id IS NOT NULL AND view_as_ended_at IS NULL AND revoked_at IS NULL"
)


def _elevations(stored: str | None) -> dict[str, datetime]:
    """`step_up_elevations` as read (`::text`): key -> ISO-8601 expiry."""
    return {k: datetime.fromisoformat(v) for k, v in json.loads(stored or "{}").items()}


def _view_as(m: Any) -> dict[str, Any] | None:
    """The `view_as_*` columns as `ViewAsState`'s fields, which `SessionRecord` validates, or
    `None` while the row holds no context (storage never imports `auth`, C-3.1). Every column
    is read by key, so a read that missed one raises instead of reporting no context."""
    if m["view_as_context_id"] is None:
        return None
    return {
        "context_id": uuid.UUID(m["view_as_context_id"]),
        "target_user_id": uuid.UUID(m["view_as_target_user_id"]),
        "started_at": m["view_as_started_at"],
        "expires_at": m["view_as_expires_at"],
        "ended_at": m["view_as_ended_at"],
        "end_reason": m["view_as_end_reason"],
        "end_recorded_at": m["view_as_end_recorded_at"],
        "cleared_at": m["view_as_cleared_at"],
    }


#: `ViewAsState`'s fields, each stored in the column `view_as_<field>` (storage never imports auth).
_VIEW_AS_FIELDS = (
    "context_id",
    "target_user_id",
    "started_at",
    "expires_at",
    "ended_at",
    "end_recorded_at",
    "cleared_at",
    "end_reason",
)


def _view_as_params(state: Any) -> dict[str, Any]:
    """A record's context (`SessionRecord.view_as`) as the insert's eight parameters, uuids and the
    reason as text; all NULL when it holds none. The inverse of `_view_as`."""
    if state is None:
        return dict.fromkeys(f"view_as_{name}" for name in _VIEW_AS_FIELDS)
    text = {"context_id", "target_user_id", "end_reason"}
    values = {name: getattr(state, name) for name in _VIEW_AS_FIELDS}
    return {
        f"view_as_{name}": str(value) if name in text and value is not None else value
        for name, value in values.items()
    }


def _held(session_id: str, context_id: uuid.UUID, params: dict[str, Any]) -> dict[str, Any]:
    """A view-as write's parameters: the row and the context it must hold, plus `params`."""
    return {"id": session_id, "context_id": str(context_id), **params}


#: `0042_sessions_view_as`'s CHECK of a context's shape. A `ViewAsState` is valid on its own, so
#: what it can still refuse is a target that is the row's own user, which only the row knows.
_VIEW_AS_SHAPE = "sessions_view_as_shape"


def _violates(exc: sa.exc.IntegrityError, constraint: str) -> bool:
    """Whether the driver names `constraint` as the one violated (asyncpg's adapter keeps the name
    on the driver error it chains: `orders_sqlalchemy` reads it from the same places)."""
    orig: Any = exc.orig
    sources = (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None))
    return any(getattr(source, "constraint_name", None) == constraint for source in sources)


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
        view_as=_view_as(m),
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
        """Insert *session*, or nothing and `None` when its user is `disabled` or gone (absent
        or soft-deleted, #2911). `locked` and `invited` users still get their row, as at login."""
        async with self._relational.unit_of_work() as uow:
            user = (await uow.session.execute(_LOCK_USER_SQL, {"id": str(session.user_id)})).first()
            if user is None or user._mapping["status"] == "disabled":
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
                    # #4051: a refresh carries the step-up penalty (SR-025), so the insert binds
                    # the record's, never the columns' defaults.
                    "step_up_failures": session.step_up_failures,
                    "readonly_until": session.readonly_until,
                    **_view_as_params(session.view_as),
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

    # -- #3085 `ViewAsSessionStore`: one statement each; the Protocol's docstrings are the contract.

    async def start_view_as(self, session_id: str, state: Any, *, now: datetime) -> Any:
        if state.ended_at is not None:
            raise ValueError("a start puts a fresh context on the row, never an ended one")
        params = {
            "id": session_id,
            "now": now,
            "context_id": str(state.context_id),
            "target_user_id": str(state.target_user_id),
            "started_at": state.started_at,
            "view_as_expires_at": state.expires_at,
        }
        try:
            return await self._one(_VIEW_AS_START_SQL, params)
        except sa.exc.IntegrityError as exc:
            if not _violates(exc, _VIEW_AS_SHAPE):
                raise
            # Only the row knows its user, so a state naming it is refused here, by the CHECK, and
            # only where the write would apply (a row that refuses a start answers None before).
            # Never chained: the driver's DETAIL carries the failing row (C-12.6).
            raise ValueError("a session must never view as its own user") from None

    async def end_view_as(
        self, session_id: str, context_id: uuid.UUID, *, ended_at: datetime, reason: str
    ) -> Any:
        params = {"ended_at": ended_at, "reason": str(reason)}
        return await self._one(_VIEW_AS_END_SQL, _held(session_id, context_id, params))

    async def leave_view_as(
        self,
        session_id: str,
        context_id: uuid.UUID,
        *,
        ended_at: datetime,
        reason: str,
        now: datetime,
    ) -> tuple[Any, bool] | None:
        params = _held(session_id, context_id, {"ended_at": ended_at, "reason": str(reason)})
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_VIEW_AS_LEAVE_SQL, {**params, "now": now})).first()
            await uow.commit()
        if row is None:
            return None
        return self._make(**row_to_fields(row)), row._mapping["ended_now"] is True

    async def clear_view_as(self, session_id: str, context_id: uuid.UUID, *, now: datetime) -> Any:
        return await self._one(_VIEW_AS_CLEAR_SQL, _held(session_id, context_id, {"now": now}))

    async def mark_view_as_recorded(
        self, session_id: str, context_id: uuid.UUID, *, now: datetime
    ) -> Any:
        return await self._one(_VIEW_AS_RECORDED_SQL, _held(session_id, context_id, {"now": now}))

    async def list_view_as_due(
        self, *, now: datetime, rotated_grace: timedelta, limit: int
    ) -> tuple[Any, ...]:
        """See `ViewAsSessionStore.list_view_as_due`: `rotated_grace` must exceed the gap from a
        refresh's claim (its `revoked_at`) to its successor's insert (`SessionService.refresh`)."""
        params = {"now": now, "cutoff": now - rotated_grace, "limit": limit}
        return await self._many(_VIEW_AS_DUE_SQL, params)

    async def list_live_view_as(self, *, limit: int) -> tuple[Any, ...]:
        return await self._many(_VIEW_AS_LIVE_SQL, {"limit": limit})

    async def list_live_view_as_by_target(self, target_user_id: uuid.UUID) -> tuple[Any, ...]:
        return await self._many(_VIEW_AS_LIVE_BY_TARGET_SQL, {"target": str(target_user_id)})

    async def list_live_view_as_by_viewer(self, viewer_user_id: uuid.UUID) -> tuple[Any, ...]:
        return await self._many(_VIEW_AS_LIVE_BY_VIEWER_SQL, {"viewer": str(viewer_user_id)})
