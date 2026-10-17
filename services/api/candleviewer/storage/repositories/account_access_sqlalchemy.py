"""`SqlAlchemyAccountAccessStore` - replaces a user's account-access grants (E42-T08, #2648).

One transaction (#965 R7) that locks in the order of 21-database-schema.md §3.1.3, each wait
bounded by `lock_timeout` (a timeout or a deadlock refuses the change: `AccessBusyError`): the
user row (a disable or soft delete of the same user queues behind it), refused unless `active`;
the accounts named, `FOR SHARE` (an account soft delete queues behind it), the whole set refused
if one is unknown or deleted; every grant row of the user. A change that removes a live grant
while a count is unknown needs the acknowledgement (#965 O2, #2648 Q2). Then it soft-revokes the
removed grants and upserts the new or changed ones; a row it inserts or revives for a frozen
manager inherits the freeze, and no write lowers one (#2648 Q1). It runs the deferred
constraints, and only then writes the `users.access_change` record ahead of the commit. Any
error, including an audit write that fails or exceeds `audit_timeout_s`, rolls everything back.
A commit that then fails or is cancelled appends `users.access_change_failed` (outcome failure)
to close that record, as `secrets/broker.py` closes a borrow (C-2.9). An unchanged set writes and
audits nothing. Each call logs one line naming its outcome. The audit emitter is injected:
storage (M10) may depend on M1 only (CONSTITUTION §3 module table).

`list_grants`, the read behind `GET /users/{userId}/account-access`, takes no row lock.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.account_access import (
    AccessAuditEmitter,
    AccessAuditUnavailableError,
    AccessBusyError,
    AccessChange,
    AccessGrant,
    AccessLevel,
    AccessPositionsUnknownError,
    AccessSelfTargetError,
    AccessUnknownAccountError,
    AccessUserNotActiveError,
    AccessUserNotFoundError,
    RemovalContext,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Bounds each audit append, as `secrets/service.py` bounds its audit sink.
AUDIT_TIMEOUT_S = 2.0
#: Bounds each lock wait (#2648 Q5); unbounded, it would last the 30 s `statement_timeout`.
LOCK_TIMEOUT_MS = 5000
POSITIONS_DECISION: Final = "leave"  # #965 O2: positions and orders stay as they are
_CHANGE, _CHANGE_FAILED = "users.access_change", "users.access_change_failed"
_BUSY = frozenset({"55P03", "40P01"})  # lock_not_available, deadlock_detected
#: The logged `outcome` of each refusal; nothing changed on any of them.
_REFUSALS: Mapping[type[BaseException], str] = {
    AccessSelfTargetError: "self_target",
    AccessUserNotFoundError: "user_not_found",
    AccessUserNotActiveError: "user_not_active",
    AccessUnknownAccountError: "unknown_account",
    AccessBusyError: "busy",
    AccessPositionsUnknownError: "positions_unknown",
    AccessAuditUnavailableError: "audit_unavailable",
}
#: Logged at info; any other outcome (`self_target`, `busy`, `audit_unavailable`,
#: `commit_failed`, `cancelled`, `error`) at warning.
_ROUTINE = frozenset(
    {
        "replaced",
        "unchanged",
        "user_not_found",
        "user_not_active",
        "unknown_account",
        "positions_unknown",
    }
)

_LOCK_TIMEOUT = sa.text("SELECT set_config('lock_timeout', :timeout, true)")
_LOCK_USER = sa.text(
    "SELECT status::text FROM users WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL "
    "FOR NO KEY UPDATE"
)
# `FOR SHARE`, not `FOR KEY SHARE`: an account soft delete updates no key column, so it takes
# `FOR NO KEY UPDATE`, which only `FOR SHARE` or stronger conflicts with.
_KNOWN_ACCOUNTS = sa.text(
    "SELECT id FROM exchange_accounts WHERE id = ANY(CAST(:ids AS uuid[])) "
    "AND deleted_at IS NULL ORDER BY id FOR SHARE"
)
_CURRENT = sa.text(
    "SELECT exchange_account_id, can_view, can_trade, frozen, frozen_at FROM user_account_access "
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
# #2648 Q1: a row this write inserted or revived for a frozen manager copies the donor row's
# freeze. It only ever sets `frozen`, and `max_daily_loss_usd` is never copied.
_INHERIT = sa.text(
    "UPDATE user_account_access AS g SET frozen = true, frozen_at = d.frozen_at, "
    "frozen_by = d.frozen_by, frozen_reason = d.frozen_reason FROM user_account_access AS d "
    "WHERE d.user_id = CAST(:id AS uuid) AND d.exchange_account_id = CAST(:donor AS uuid) "
    "AND g.user_id = d.user_id AND g.exchange_account_id = ANY(CAST(:accounts AS uuid[])) "
    "AND NOT g.frozen"
)
_IMMEDIATE = sa.text("SET CONSTRAINTS ALL IMMEDIATE")
# The read (#2648 S9b): no row lock. `granted_by` is whoever last wrote the grant (an upsert
# overwrites it); `granted_at` is not selected, no column is truthful for it.
_USER_EXISTS = sa.text("SELECT 1 FROM users WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL")
_LIST_GRANTS = sa.text(
    "SELECT a.exchange_account_id, a.can_trade, e.label, e.env::text, a.granted_by "
    "FROM user_account_access AS a JOIN exchange_accounts AS e ON e.id = a.exchange_account_id "
    "WHERE a.user_id = CAST(:id AS uuid) AND a.can_view AND e.deleted_at IS NULL "
    "ORDER BY a.exchange_account_id"
)
#: The audit record's `before_state` and `after_state`.
_States = tuple[dict[str, object], dict[str, object]]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _uuid(value: object) -> uuid.UUID:
    """asyncpg returns its own `uuid.UUID` subclass, which orjson refuses: make it plain."""
    return uuid.UUID(str(value))


def _states(change: AccessChange, removal: RemovalContext) -> _States:
    """The live grants in account-id order with their level and `frozen` flag (never the free-text
    `frozen_reason`); a change that removes a grant adds the decision and the counts (#965 O2)."""

    def grants(side: Mapping[uuid.UUID, AccessLevel]) -> list[dict[str, object]]:
        return [
            {"exchange_account_id": str(a), "level": lvl, "frozen": a in change.frozen}
            for a, lvl in sorted(side.items())
        ]

    after: dict[str, object] = {"grants": grants(change.after)}
    if change.removed:
        after |= {
            "positions_decision": POSITIONS_DECISION,
            "open_position_count": removal.open_position_count,
            "open_order_count": removal.open_order_count,
            "acknowledged_unknown_positions": removal.acknowledged_unknown_positions,
        }
    return {"grants": grants(change.before)}, after


def _donor(rows: Sequence[Any]) -> uuid.UUID | None:
    """The account whose freeze a row this write inserts or revives inherits; `None` when the
    manager is not frozen (#2648 Q1). Frozen: one of their rows, live or soft-revoked, is frozen
    and no live row is not. Read under the locks before any write, so neither swapping every
    account nor revoking all and granting again escapes it. `rows` are `_CURRENT`'s, in account
    order: the latest `frozen_at` donates, and a tie goes to the lowest account id."""
    if any(view and not frozen for _, view, _, frozen, _ in rows):
        return None
    frozen_at = {account: at for account, _, _, frozen, at in rows if frozen}
    return _uuid(max(frozen_at, key=frozen_at.__getitem__)) if frozen_at else None


def _sqlstate(exc: DBAPIError) -> str | None:
    state = getattr(exc.orig, "sqlstate", None)
    return state if isinstance(state, str) else None


def _db_refusal(exc: DBAPIError) -> Exception:
    """A lock wait that timed out or deadlocked is `AccessBusyError`; any other driver error is
    `StorageQueryFailed` with its SQLSTATE alone. Raise either `from None`: the driver's text
    can carry row values (C-12.6)."""
    sqlstate = _sqlstate(exc)
    if sqlstate in _BUSY:
        return AccessBusyError()
    return StorageQueryFailed(sqlstate)


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
        lock_timeout_ms: int = LOCK_TIMEOUT_MS,
    ) -> None:
        self._relational = relational
        self._audit = audit
        self._audit_timeout_s = audit_timeout_s
        self._lock_timeout = f"{lock_timeout_ms}ms"

    async def replace_grants(
        self,
        user_id: uuid.UUID,
        grants: Mapping[uuid.UUID, AccessLevel],
        *,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID | None = None,
        removal: RemovalContext | None = None,
    ) -> AccessChange:
        """Make `grants` the user's live set; every other live grant is soft-revoked. `removal`
        is what the caller read of the user's exposure; `None` reads as both counts unknown.

        Raises `AccessSelfTargetError`, `AccessUserNotFoundError`, `AccessUserNotActiveError`,
        `AccessUnknownAccountError`, `AccessBusyError`, `AccessPositionsUnknownError`,
        `AccessAuditUnavailableError` or `StorageQueryFailed` (any driver error, its text
        dropped); on any of them nothing changes, bar a commit cut off in flight or a session
        that fails to close after it, which may leave the change committed. A write-ahead
        record whose emit timed out or was cancelled may still land (see `_write_ahead`): the
        grant rows are the truth."""
        outcome = "error"
        written: _States | None = None  # recorded ahead, commit not yet confirmed
        try:
            if user_id == actor_user_id:  # SR-055 backstop: before any statement
                raise AccessSelfTargetError(str(user_id))
            exposure = RemovalContext() if removal is None else removal
            async with self._relational.unit_of_work() as uow:
                change = await self._apply(
                    uow.session, user_id, dict(grants), actor_user_id, exposure
                )
                if change.changed:
                    states = _states(change, exposure)
                    await self._write_ahead(user_id, states, actor_user_id, request_id)
                    written = states
                    await uow.commit()
                    outcome, written = "replaced", None
                else:
                    outcome = "unchanged"
        except BaseException as exc:
            # A driver error from any statement, the unit of work's `SET LOCAL`s, its close or
            # the commit leaves as `AccessBusyError` or `StorageQueryFailed`, never the driver's.
            failure = _db_refusal(exc) if isinstance(exc, DBAPIError) else exc
            if outcome == "error":  # once decided, only closing the session can still fail
                outcome = _outcome(failure, written is not None)
            if written is not None:  # close the write-ahead record (C-2.9)
                await self._close(user_id, written, actor_user_id, request_id, outcome)
            if failure is not exc:
                raise failure from None
            raise
        finally:
            rid = {} if request_id is None else {"request_id": str(request_id)}
            log = _log()
            (log.info if outcome in _ROUTINE else log.warning)(
                "account access replace", outcome=outcome, target_user_id=str(user_id), **rid
            )
        return change

    async def list_grants(self, user_id: uuid.UUID) -> list[AccessGrant]:
        """The user's live grants of live accounts, in account-id order (a soft-revoked grant and
        a grant on a deleted account are not listed), whatever the user's status. Raises
        `AccessUserNotFoundError` for a missing or deleted user and `StorageQueryFailed` (its
        SQLSTATE alone) for a driver error; a refused connection raises the driver's `OSError`."""
        uid = str(user_id)
        try:
            async with self._relational.unit_of_work() as uow:
                if (await uow.session.execute(_USER_EXISTS, {"id": uid})).first() is None:
                    raise AccessUserNotFoundError(uid)
                rows = (await uow.session.execute(_LIST_GRANTS, {"id": uid})).all()
        except DBAPIError as exc:
            raise StorageQueryFailed(_sqlstate(exc)) from None
        return [
            AccessGrant(
                _uuid(account),
                "trade" if can_trade else "read",
                label,
                env,
                None if granter is None else _uuid(granter),
            )
            for account, can_trade, label, env, granter in rows
        ]

    async def _apply(
        self,
        s: AsyncSession,
        user_id: uuid.UUID,
        wanted: dict[uuid.UUID, AccessLevel],
        actor: uuid.UUID,
        removal: RemovalContext,
    ) -> AccessChange:
        """Lock and check, then write the grant rows if the live set changes."""
        uid = str(user_id)
        await s.execute(_LOCK_TIMEOUT, {"timeout": self._lock_timeout})
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
        upserts = sorted((a, lvl) for a, lvl in wanted.items() if before.get(a) != lvl)
        donor = _donor(rows)  # evaluated before any write
        inherited = {a for a, _ in upserts} if donor is not None else set()
        frozen = {_uuid(r[0]) for r in rows if r[3]} | inherited
        change = AccessChange(user_id, before, wanted, frozenset(frozen))
        if not change.changed:
            return change
        if change.removed and removal.blocks_removal:  # AC7: every removal (#2648 Q2)
            raise AccessPositionsUnknownError(uid)
        if revoked := sorted(str(a) for a in change.removed):
            await s.execute(_REVOKE, {"id": uid, "revoked": revoked})
        if upserts:
            accounts = [str(a) for a, _ in upserts]
            await s.execute(
                _UPSERT,
                {
                    "id": uid,
                    "actor": str(actor),
                    "accounts": accounts,
                    "trade": [lvl == "trade" for _, lvl in upserts],
                },
            )
            if donor is not None:
                await s.execute(_INHERIT, {"id": uid, "accounts": accounts, "donor": str(donor)})
        await s.execute(_IMMEDIATE)
        return change

    async def _write_ahead(
        self, user_id: uuid.UUID, states: _States, actor: uuid.UUID, request_id: uuid.UUID | None
    ) -> None:
        """A refused record was never written. After a timeout or a cancel it is unknown whether
        it landed (`AuditWriter.emit` finishes an append it has started), and nothing closes it:
        the transaction rolls back, and the grant rows are the truth."""
        try:
            await self._emit(_CHANGE, user_id, states, actor, request_id, "success", None)
        except Exception as exc:  # the writer's refusal (WAL full, stopped) or the timeout
            raise AccessAuditUnavailableError(str(user_id)) from exc

    async def _close(
        self,
        user_id: uuid.UUID,
        states: _States,
        actor: uuid.UUID,
        request_id: uuid.UUID | None,
        reason: str,
    ) -> None:
        """Best-effort closing record; it never replaces the original exception. A commit
        cancelled in flight may still have landed: the grant rows stay the truth."""
        try:
            await self._emit(_CHANGE_FAILED, user_id, states, actor, request_id, "failure", reason)
        except Exception:
            _log().exception("account access closing audit record not written", reason=reason)

    async def _emit(
        self,
        action: str,
        user_id: uuid.UUID,
        states: _States,
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
                object_id=str(user_id),
                before_state=states[0],
                after_state=states[1],
                request_id=request_id,
                outcome=outcome,
                reason=reason,
            )
