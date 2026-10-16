"""`SqlAlchemyAccountAccessStore` - replaces a user's account-access grants (E42-T08 S8, #2648).

One transaction (#965 R7): lock the user row (a disable of the same user queues behind it) and
refuse unless `active`; refuse the whole set if an account is unknown or deleted (the accounts
named are key-share locked); soft-revoke the removed grants and upsert the new or changed ones;
run the deferred constraints; only then write the `users.access_change` record ahead of the
commit. Any error, including an audit write that fails or exceeds `audit_timeout_s`, rolls
everything back. A commit that then fails or is cancelled appends `users.access_change_failed`
(outcome failure) to close that record, as `secrets/broker.py` closes a borrow (C-2.9). An
unchanged set writes and audits nothing. Each call logs one line naming its outcome. The audit
emitter is injected: storage (M10) may depend on M1 only (CONSTITUTION §3 module table).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.storage.repositories.account_access import (
    AccessAuditEmitter,
    AccessAuditUnavailableError,
    AccessChange,
    AccessLevel,
    AccessUnknownAccountError,
    AccessUserNotActiveError,
    AccessUserNotFoundError,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Bounds each audit append, as `secrets/service.py` bounds its audit sink.
AUDIT_TIMEOUT_S = 2.0
_CHANGE, _CHANGE_FAILED = "users.access_change", "users.access_change_failed"
#: The logged `outcome` of each refusal; nothing changed on any of them.
_REFUSALS: Mapping[type[BaseException], str] = {
    AccessUserNotFoundError: "user_not_found",
    AccessUserNotActiveError: "user_not_active",
    AccessUnknownAccountError: "unknown_account",
    AccessAuditUnavailableError: "audit_unavailable",
}
#: Logged at info; any other outcome (`audit_unavailable`, `commit_failed`, `cancelled`,
#: `error`) at warning.
_ROUTINE = frozenset(
    {"replaced", "unchanged", "user_not_found", "user_not_active", "unknown_account"}
)

_LOCK_USER = sa.text(
    "SELECT status::text FROM users WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL "
    "FOR NO KEY UPDATE"
)
_KNOWN_ACCOUNTS = sa.text(
    "SELECT id FROM exchange_accounts WHERE id = ANY(CAST(:ids AS uuid[])) "
    "AND deleted_at IS NULL ORDER BY id FOR KEY SHARE"
)
_CURRENT = sa.text(
    "SELECT exchange_account_id, can_view, can_trade FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid) ORDER BY exchange_account_id FOR NO KEY UPDATE"
)
# #965 O4: a soft revoke, never a DELETE; the freeze columns and the cap are never written.
_REVOKE = sa.text(
    "UPDATE user_account_access SET can_view = false, can_trade = false "
    "WHERE user_id = CAST(:id AS uuid) AND exchange_account_id = ANY(CAST(:revoked AS uuid[]))"
)
# A re-grant revives the soft-revoked row: only the access columns and `granted_by` change.
_UPSERT = sa.text(
    "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, can_trade, "
    "granted_by) SELECT CAST(:id AS uuid), g.account, true, g.trade, CAST(:actor AS uuid) "
    "FROM unnest(CAST(:accounts AS uuid[]), CAST(:trade AS boolean[])) AS g(account, trade) "
    "ON CONFLICT (user_id, exchange_account_id) DO UPDATE SET can_view = true, "
    "can_trade = EXCLUDED.can_trade, granted_by = EXCLUDED.granted_by"
)
_IMMEDIATE = sa.text("SET CONSTRAINTS ALL IMMEDIATE")


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _uuid(value: object) -> uuid.UUID:
    """asyncpg returns its own `uuid.UUID` subclass, which orjson refuses: make it plain."""
    return uuid.UUID(str(value))


def _state(grants: Mapping[uuid.UUID, AccessLevel]) -> dict[str, object]:
    """Audit `before_state`/`after_state`: the live grants in account-id order."""
    items = sorted(grants.items())
    return {"grants": [{"exchange_account_id": str(a), "level": lvl} for a, lvl in items]}


def _outcome(exc: BaseException, written: bool) -> str:
    """The bounded `outcome` of a call that raised: a code, never the error's text."""
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if written:  # only the commit runs between the write-ahead record and the outcome
        return "commit_failed"
    return _REFUSALS.get(type(exc), "error")


class SqlAlchemyAccountAccessStore:
    """Postgres account-access store: replaces a user's grant set atomically."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        audit: AccessAuditEmitter,
        audit_timeout_s: float = AUDIT_TIMEOUT_S,
    ) -> None:
        self._relational = relational
        self._audit = audit
        self._audit_timeout_s = audit_timeout_s

    async def replace_grants(
        self,
        user_id: uuid.UUID,
        grants: Mapping[uuid.UUID, AccessLevel],
        *,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID | None = None,
    ) -> AccessChange:
        """Make `grants` the user's live set; every other live grant is soft-revoked.

        Raises `AccessUserNotFoundError`, `AccessUserNotActiveError`,
        `AccessUnknownAccountError` or `AccessAuditUnavailableError`; on any of them nothing
        changes. A write-ahead record whose emit timed out or was cancelled may still land, and
        no closing record follows (see `_write_ahead`): the grant rows are the truth."""
        outcome = "error"
        written: AccessChange | None = None  # recorded ahead, commit not yet confirmed
        try:
            async with self._relational.unit_of_work() as uow:
                change = await self._apply(uow.session, user_id, dict(grants), actor_user_id)
                if change.changed:
                    await self._write_ahead(change, actor_user_id, request_id)
                    written = change
                    await uow.commit()
                    outcome, written = "replaced", None
                else:
                    outcome = "unchanged"
        except BaseException as exc:
            if outcome == "error":  # once decided, only closing the session can still fail
                outcome = _outcome(exc, written is not None)
            if written is not None:  # close the write-ahead record (C-2.9)
                await self._close(written, actor_user_id, request_id, outcome)
            raise
        finally:
            rid = {} if request_id is None else {"request_id": str(request_id)}
            log = _log()
            (log.info if outcome in _ROUTINE else log.warning)(
                "account access replace", outcome=outcome, target_user_id=str(user_id), **rid
            )
        return change

    async def _apply(
        self,
        s: AsyncSession,
        user_id: uuid.UUID,
        wanted: dict[uuid.UUID, AccessLevel],
        actor: uuid.UUID,
    ) -> AccessChange:
        """Lock and check, then write the grant rows if the live set changes."""
        uid = str(user_id)
        user = (await s.execute(_LOCK_USER, {"id": uid})).first()
        if user is None:
            raise AccessUserNotFoundError(uid)
        if user[0] != "active":
            raise AccessUserNotActiveError(user[0])
        if wanted:
            ids = sorted(str(a) for a in wanted)
            found = {_uuid(r[0]) for r in (await s.execute(_KNOWN_ACCOUNTS, {"ids": ids})).all()}
            if missing := frozenset(wanted) - found:
                raise AccessUnknownAccountError(missing)
        rows = (await s.execute(_CURRENT, {"id": uid})).all()
        before: dict[uuid.UUID, AccessLevel] = {
            _uuid(r[0]): "trade" if r[2] else "read" for r in rows if r[1]
        }
        change = AccessChange(user_id, before, wanted)
        if not change.changed:
            return change
        if revoked := sorted(str(a) for a in before.keys() - wanted.keys()):
            await s.execute(_REVOKE, {"id": uid, "revoked": revoked})
        if upserts := sorted((a, lvl) for a, lvl in wanted.items() if before.get(a) != lvl):
            await s.execute(
                _UPSERT,
                {
                    "id": uid,
                    "actor": str(actor),
                    "accounts": [str(a) for a, _ in upserts],
                    "trade": [lvl == "trade" for _, lvl in upserts],
                },
            )
        await s.execute(_IMMEDIATE)
        return change

    async def _write_ahead(
        self, change: AccessChange, actor: uuid.UUID, request_id: uuid.UUID | None
    ) -> None:
        """A refused record was never written. After a timeout or a cancel it is unknown whether
        it landed (`AuditWriter.emit` finishes an append it has started), and nothing closes it:
        the transaction rolls back, and the grant rows are the truth."""
        try:
            await self._emit(_CHANGE, change, actor, request_id, "success", None)
        except Exception as exc:  # the writer's refusal (WAL full, stopped) or the timeout
            raise AccessAuditUnavailableError(str(change.user_id)) from exc

    async def _close(
        self, change: AccessChange, actor: uuid.UUID, request_id: uuid.UUID | None, reason: str
    ) -> None:
        """Best-effort closing record; it never replaces the original exception. A commit
        cancelled in flight may still have landed: the grant rows stay the truth."""
        try:
            await self._emit(_CHANGE_FAILED, change, actor, request_id, "failure", reason)
        except Exception:
            _log().exception("account access closing audit record not written", reason=reason)

    async def _emit(
        self,
        action: str,
        change: AccessChange,
        actor: uuid.UUID,
        request_id: uuid.UUID | None,
        outcome: str,
        reason: str | None,
    ) -> None:
        async with asyncio.timeout(self._audit_timeout_s):
            await self._audit.emit(
                action,
                actor_label=str(actor),
                actor_user_id=actor,
                object_kind="user",
                object_id=str(change.user_id),
                before_state=_state(change.before),
                after_state=_state(change.after),
                request_id=request_id,
                outcome=outcome,
                reason=reason,
            )
