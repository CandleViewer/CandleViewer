"""`SqlAlchemyInviteRepository` - Postgres `InviteRepository` (E09-S05).

Lives in M10 so `candleviewer.auth` never imports a storage driver (ADR-0003).
Static, parameterised SQL only. Single-use consumption and activation are
conditional UPDATE ... RETURNING statements, so concurrent redemptions cannot
both win. `user_account_access` is never written (a new user starts with zero
bindings; E27/E39 grant them). The raw token never reaches this layer.
Owner actions (create, reissue, revoke) await the caller's write-ahead audit hook
in their transaction, after staging and before commit (C-2.9, #2510), bounded as
in `user_roles_sqlalchemy`: a raise or a `WriteAheadTimeout` rolls every row back.
`activate_bootstrap_owner` (#4479) is the one path that grants `owner` at redemption: READ
COMMITTED, the bootstrap lock, the marked invite and its user locked, no active Owner, then the
grant, the activation, the critical `auth`/`owner_bootstrapped` event and its write-ahead record,
one commit.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.incident_grouping import incident_occurrence
from candleviewer.storage.repositories.incidents_sqlalchemy import record_occurrence
from candleviewer.storage.repositories.owner_floor_sqlalchemy import COUNT_OWNERS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

#: Write-ahead audit of an owner invite action, `(user_id, role)`; raises to refuse it.
AuditHook = Callable[[uuid.UUID, str], Awaitable[None]]
#: Write-ahead audit of the bootstrap Owner grant, `(invite_id, user_id)`; raises to refuse it.
BootstrapHook = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]
#: `auth.invite_repository.BootstrapActivation`, typed here: `storage` may not import `auth`.
BootstrapAnswer = Literal["activated", "owner_exists", "not_bootstrap", "not_invited"]
#: `auth.invite_repository.BootstrapOffer`, typed here for the same reason.
BootstrapOffer = Literal["open", "stale", "unmarked"]

#: The offline bootstrap invite (#4479): an `owner` invite whose inviter is its own user. No API
#: path writes it: `create` draws a fresh user id, `reissue` names the acting Owner.
BOOTSTRAP_MARKER = "(i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id)"
#: Serialises every bootstrap mint and activation (taken first, released at commit).
BOOTSTRAP_LOCK = sa.text("SELECT pg_advisory_xact_lock(hashtext('cv_bootstrap_owner'))")
#: First: under REPEATABLE READ the lock statement would fix a snapshot that misses a
#: concurrent activation's commit (DC-12).
_READ_COMMITTED = sa.text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
_BOOTSTRAP_EVENT = "owner_bootstrapped"  # `system_events.kind`, component `auth`
_BOOTSTRAP_MESSAGE = (
    "Bootstrap Owner activated from the offline invite (#4479); review it until that Owner signs in"
)
_BOOTSTRAP_INCIDENT = incident_occurrence(
    component="auth", kind=_BOOTSTRAP_EVENT, severity="critical", message=_BOOTSTRAP_MESSAGE
)
_INSERT_BOOTSTRAP_EVENT = sa.text(
    "INSERT INTO system_events (component, kind, severity, message, details, event_ts) "
    "VALUES ('auth', 'owner_bootstrapped', 'critical', :message, CAST(:details AS jsonb), :now)"
)
#: The bootstrap event of the user a signed-in session (MFA satisfied) is minted for: `:id` the
#: user's id, `:key` the same id as text (one bind per type: asyncpg deduces one type per bind).
RESOLVE_BOOTSTRAP_EVENT = sa.text(
    "UPDATE system_events SET resolved_at = :now, resolved_by = CAST(:id AS uuid) "
    "WHERE component = 'auth' AND kind = 'owner_bootstrapped' AND resolved_at IS NULL "
    "AND details ->> 'user_id' = :key"
)
_GRANT_OWNER = sa.text(
    "INSERT INTO user_roles (user_id, role_id) SELECT CAST(:id AS uuid), r.id FROM roles r "
    "WHERE r.name = 'owner' ON CONFLICT (user_id, role_id) DO NOTHING"
)


#: The invite and its user locked `FOR NO KEY UPDATE`, judged by `BOOTSTRAP_MARKER` (written out
#: in full: statements are whole literals, never spliced). The user row is where every activation
#: and delete of that user queues; the invite row is locked too because `_DOWNGRADE_INVITES`
#: rewrites `i.role` without the user's lock, and the marker must hold to the commit. NO KEY: a
#: child row's FK check (`FOR KEY SHARE`) does not wait on it. A unit test pins that both
#: statements below carry `BOOTSTRAP_MARKER` verbatim.
_BOOTSTRAP_ROW = sa.text(
    "SELECT (i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id) AS bootstrap, "
    "(i.consumed_at IS NOT NULL AND i.revoked_at IS NULL) AS usable, "
    "u.status::text AS status FROM user_invites i JOIN users u ON u.id = i.user_id "
    "AND u.deleted_at IS NULL WHERE i.id = CAST(:iid AS uuid) "
    "AND i.user_id = CAST(:id AS uuid) FOR NO KEY UPDATE OF i, u"
)
_IS_MARKED = sa.text(
    "SELECT (i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id) "
    "FROM user_invites i WHERE i.id = CAST(:iid AS uuid)"
)

_COLS = (
    "i.id::text AS id, i.user_id::text AS user_id, i.role::text AS role, "
    "u.username::text AS username, u.email::text AS email, u.display_name, "
    "u.status::text AS user_status, i.expires_at, i.consumed_at, i.revoked_at, "
    "i.created_at, i.pending_password_hash"
)
_FROM = "FROM user_invites i JOIN users u ON u.id = i.user_id AND u.deleted_at IS NULL"


def _sql(template: str) -> sa.TextClause:
    # Only the static column/from fragments above are substituted, never caller data.
    return sa.text(template.replace("@C@", _COLS).replace("@F@", _FROM))


INSERT_INVITED_USER = sa.text(
    "INSERT INTO users (id, email, username, display_name, password_hash, status, "
    "mfa_required, invited_by) VALUES (CAST(:id AS uuid), :email, :username, :dn, :ph, "
    "'invited', true, CAST(:by AS uuid))"
)
_INSERT_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id, granted_by) "
    "SELECT CAST(:id AS uuid), r.id, CAST(:by AS uuid) FROM roles r "
    "WHERE r.name = CAST(:role AS role_name)"
)
INSERT_INVITE = sa.text(
    "INSERT INTO user_invites (id, user_id, role, token_hash, invited_by, expires_at, "
    "created_at) VALUES (CAST(:iid AS uuid), CAST(:id AS uuid), CAST(:role AS role_name), "
    ":th, CAST(:by AS uuid), :exp, :now)"
)
_INSERT_INVITE_NOW = sa.text(
    "INSERT INTO user_invites (id, user_id, role, token_hash, invited_by, expires_at) "
    "VALUES (CAST(:iid AS uuid), CAST(:id AS uuid), CAST(:role AS role_name), :th, "
    "CAST(:by AS uuid), :exp)"
)
_FIND = _sql("SELECT @C@ @F@ WHERE i.token_hash = :h")
_CONSUME = sa.text(
    "WITH c AS (UPDATE user_invites SET consumed_at = :now, pending_password_hash = :pp "
    "WHERE token_hash = :h AND consumed_at IS NULL AND revoked_at IS NULL "
    "AND expires_at > :now RETURNING id) SELECT id::text FROM c"
)
_ACTIVATE = sa.text(
    "UPDATE users SET password_hash = :ph, password_algo_params = CAST(:ap AS jsonb), "
    "password_changed_at = :now, status = 'active', updated_at = :now "
    "WHERE id = CAST(:id AS uuid) AND status = 'invited' RETURNING 1"
)
_CLEAR_PENDING = sa.text(
    "UPDATE user_invites SET pending_password_hash = NULL WHERE user_id = CAST(:id AS uuid)"
)
_REVOKE = sa.text(
    "UPDATE user_invites SET revoked_at = :now WHERE user_id = CAST(:id AS uuid) "
    "AND consumed_at IS NULL AND revoked_at IS NULL RETURNING role::text AS role"
)
_IS_INVITED = sa.text(
    "SELECT role::text AS role FROM user_invites i JOIN users u ON u.id = i.user_id "
    "WHERE u.id = CAST(:id AS uuid) AND u.status = 'invited' AND u.deleted_at IS NULL "
    "ORDER BY i.created_at DESC LIMIT 1"
)
_PENDING = _sql(
    "SELECT @C@ @F@ WHERE i.consumed_at IS NULL AND i.revoked_at IS NULL "
    "AND u.status = 'invited' ORDER BY i.created_at DESC"
)
_FIND_BY_ID = _sql("SELECT @C@ @F@ WHERE i.id = CAST(:iid AS uuid)")


_DOWNGRADE_INVITES = sa.text(
    "UPDATE user_invites SET role = CAST('viewer' AS role_name) "
    "WHERE user_id = CAST(:id AS uuid) AND role <> CAST('viewer' AS role_name)"
)
_DOWNGRADE_ROLE = sa.text(
    "UPDATE user_roles SET role_id = "
    "(SELECT id FROM roles WHERE name = CAST('viewer' AS role_name)) "
    "WHERE user_id = CAST(:id AS uuid) AND role_id IN "
    "(SELECT id FROM roles WHERE name <> CAST('viewer' AS role_name))"
)


class SqlAlchemyInviteRepository:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        record_factory: Callable[..., Any],
        *,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        self._relational = relational
        self._record = record_factory
        self._audit_timeout_s = audit_timeout_s

    async def _write_ahead(self, audit: AuditHook, user_id: uuid.UUID, role: str) -> None:
        """Bounded: the open transaction holds row locks (see `user_roles_sqlalchemy`)."""
        await bounded_write_ahead(audit(user_id, role), self._audit_timeout_s)

    async def create_user_with_invite(
        self,
        *,
        user_id: uuid.UUID,
        invite_id: uuid.UUID,
        email: str,
        username: str,
        display_name: str | None,
        role: str,
        placeholder_password_hash: str,
        invited_by: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        audit: AuditHook,
    ) -> bool:
        try:
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                await s.execute(
                    INSERT_INVITED_USER,
                    {
                        "id": str(user_id),
                        "email": email,
                        "username": username,
                        "dn": display_name,
                        "ph": placeholder_password_hash,
                        "by": str(invited_by),
                    },
                )
                await s.execute(
                    _INSERT_ROLE, {"id": str(user_id), "by": str(invited_by), "role": role}
                )
                await s.execute(
                    _INSERT_INVITE_NOW,
                    {
                        "iid": str(invite_id),
                        "id": str(user_id),
                        "role": role,
                        "th": token_hash,
                        "by": str(invited_by),
                        "exp": expires_at,
                    },
                )
                await self._write_ahead(audit, user_id, role)
                await uow.commit()
        except IntegrityError:
            return False
        return True

    async def _rows(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[Any]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).all()
            await uow.commit()
        return list(rows)

    def _make(self, row: Any) -> Any:
        return self._record(**dict(row._mapping))

    async def find_by_token_hash(self, token_hash: str) -> Any:
        rows = await self._rows(_FIND, {"h": token_hash})
        return self._make(rows[0]) if rows else None

    async def consume(self, token_hash: str, *, now: datetime, pending_password_hash: str) -> Any:
        rows = await self._rows(
            _CONSUME, {"h": token_hash, "now": now, "pp": pending_password_hash}
        )
        if not rows:
            return None
        return await self.find_by_token_hash(token_hash)

    async def find_consumed_for_user(self, user_id: uuid.UUID) -> Any:
        rows = await self._rows(
            _sql(
                "SELECT @C@ @F@ WHERE i.user_id = CAST(:id AS uuid) AND i.consumed_at IS NOT NULL "
                "AND i.revoked_at IS NULL AND u.status = 'invited' "
                "ORDER BY i.created_at DESC LIMIT 1"
            ),
            {"id": str(user_id)},
        )
        return self._make(rows[0]) if rows else None

    async def activate_user(
        self, user_id: uuid.UUID, *, password_hash: str, algo_params: dict[str, int], now: datetime
    ) -> bool:
        async with self._relational.unit_of_work() as uow:
            won = (
                await uow.session.execute(
                    _ACTIVATE,
                    {
                        "id": str(user_id),
                        "ph": password_hash,
                        "ap": json.dumps(algo_params),
                        "now": now,
                    },
                )
            ).all()
            if won:
                await uow.session.execute(_CLEAR_PENDING, {"id": str(user_id)})
            await uow.commit()
        return bool(won)

    async def activate_bootstrap_owner(
        self,
        invite_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        password_hash: str,
        algo_params: dict[str, int],
        now: datetime,
        audit: BootstrapHook,
    ) -> BootstrapAnswer:
        """`activated` after one commit; else rolled back: `not_invited` (no such consumed,
        unrevoked invite of an `invited` user), `not_bootstrap`, `owner_exists`."""
        ids = {"iid": str(invite_id), "id": str(user_id)}
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            await run(_READ_COMMITTED)
            await run(BOOTSTRAP_LOCK)
            row = (await run(_BOOTSTRAP_ROW, ids)).first()
            verdict: BootstrapAnswer | None = None
            if row is None or not row.usable or row.status != "invited":
                verdict = "not_invited"
            elif not row.bootstrap:
                verdict = "not_bootstrap"
            elif int((await run(COUNT_OWNERS)).scalar_one()) > 0:  # a new statement: READ COMMITTED
                verdict = "owner_exists"
            if verdict is not None:
                await uow.rollback()
                return verdict
            await run(_GRANT_OWNER, {"id": ids["id"]})
            activated = await run(
                _ACTIVATE,
                {"id": ids["id"], "ph": password_hash, "ap": json.dumps(algo_params), "now": now},
            )
            if not activated.all():
                await uow.rollback()
                return "not_invited"
            await run(_CLEAR_PENDING, {"id": ids["id"]})
            details = json.dumps({"invite_id": ids["iid"], "user_id": ids["id"]}, sort_keys=True)
            await run(
                _INSERT_BOOTSTRAP_EVENT,
                {"message": _BOOTSTRAP_MESSAGE, "details": details, "now": now},
            )
            await record_occurrence(uow.session, _BOOTSTRAP_INCIDENT, seen_at=now)
            await bounded_write_ahead(audit(invite_id, user_id), self._audit_timeout_s)
            await uow.commit()
        return "activated"

    async def bootstrap_offer(self, invite_id: uuid.UUID) -> BootstrapOffer:
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            if not (await run(_IS_MARKED, {"iid": str(invite_id)})).scalar():
                return "unmarked"
            return "stale" if int((await run(COUNT_OWNERS)).scalar_one()) > 0 else "open"

    async def downgrade_to_viewer(self, user_id: uuid.UUID) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_DOWNGRADE_INVITES, {"id": str(user_id)})
            await uow.session.execute(_DOWNGRADE_ROLE, {"id": str(user_id)})
            await uow.commit()

    async def reissue(
        self,
        user_id: uuid.UUID,
        *,
        invite_id: uuid.UUID,
        token_hash: str,
        invited_by: uuid.UUID,
        expires_at: datetime,
        now: datetime,
        audit: AuditHook,
    ) -> Any:
        async with self._relational.unit_of_work() as uow:
            s = uow.session
            row = (await s.execute(_IS_INVITED, {"id": str(user_id)})).first()
            if row is None:
                return None
            await s.execute(
                sa.text(
                    "UPDATE user_invites SET revoked_at = :now WHERE user_id = CAST(:id AS uuid) "
                    "AND revoked_at IS NULL AND (consumed_at IS NULL OR pending_password_hash "
                    "IS NOT NULL)"
                ),
                {"id": str(user_id), "now": now},
            )
            await s.execute(
                INSERT_INVITE,
                {
                    "iid": str(invite_id),
                    "id": str(user_id),
                    "role": row.role,
                    "th": token_hash,
                    "by": str(invited_by),
                    "exp": expires_at,
                    "now": now,
                },
            )
            fresh = (await s.execute(_FIND_BY_ID, {"iid": str(invite_id)})).first()
            await self._write_ahead(audit, user_id, row.role)
            await uow.commit()
        return self._make(fresh) if fresh is not None else None

    async def revoke_open(self, user_id: uuid.UUID, *, now: datetime, audit: AuditHook) -> bool:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_REVOKE, {"id": str(user_id), "now": now})).all()
            if not rows:
                return False
            await self._write_ahead(audit, user_id, rows[0].role)
            await uow.commit()
        return True

    async def list_pending(self, *, now: datetime) -> tuple[Any, ...]:
        rows = await self._rows(_PENDING, {})
        return tuple(self._make(r) for r in rows)
