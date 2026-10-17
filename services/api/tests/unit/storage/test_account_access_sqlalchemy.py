"""E42-T08 S8 and S9a (#2648): `SqlAlchemyAccountAccessStore` over a fake unit of work. Real
Postgres (transaction, rollback, races): tests/integration/storage/test_account_access_store_pg.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import orjson
import pytest
import structlog
from asyncpg.pgproto.pgproto import UUID as DriverUUID
from sqlalchemy.exc import DBAPIError

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories import account_access_sqlalchemy as m
from candleviewer.storage.repositories import onboarding_sqlalchemy as onboarding
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

_USER, _ACTOR, _RID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
_A, _B, _C, _D = sorted(uuid.uuid4() for _ in range(4))
_T1, _T2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
_Row = tuple[uuid.UUID, bool, bool]  # (exchange_account_id, can_view, can_trade), not frozen
_FrozenRow = tuple[uuid.UUID, bool, bool, bool, datetime | None]  # ..., frozen, frozen_at
#: What the listing selects: (exchange_account_id, can_trade, label, env, granted_by).
_ListedRow = tuple[uuid.UUID, bool, str, str, uuid.UUID | None]
_LIVE_A: tuple[_Row, ...] = ((_A, True, False),)
#: _A read, _B trade, and _D soft-revoked (not live).
_MIXED: tuple[_Row, ...] = ((_A, True, False), (_B, True, True), (_D, False, False))
#: Replaces `_MIXED`: _A left out, _B down to read, _C new, _D granted again.
_SET: dict[uuid.UUID, AccessLevel] = {_B: "read", _C: "trade", _D: "read"}
#: Both counts read and zero: a removal needs no acknowledgement.
_KNOWN = RemovalContext(open_position_count=0, open_order_count=0)
#: What a replacement naming accounts runs first: the wait bound, then the locks in order.
_LOCKED_READS = [m._LOCK_TIMEOUT, m._LOCK_USER, m._KNOWN_ACCOUNTS, m._CURRENT]
#: Bounds every wait on a fake: a regression fails fast instead of hanging CI.
_WAIT_S = 5.0
_CLOSE_FAILED = "account access closing audit record not written"


class _Rel:
    """Fake UoW keyed by statement: records each statement, its params and the commit. Ids come
    back as asyncpg's own `uuid.UUID` subclass, as the driver returns them."""

    def __init__(
        self,
        status: str | None = "active",
        rows: tuple[_Row | _FrozenRow, ...] = (),
        unknown: frozenset[uuid.UUID] = frozenset(),
        *,
        fail_on: object = None,
        error: Exception | None = None,
        on_commit: Callable[[], Awaitable[None]] | None = None,
        on_close: Exception | None = None,
        on_enter: Exception | None = None,
        listing: tuple[_ListedRow, ...] = (),
    ) -> None:
        self.status, self.rows, self.unknown = status, rows, unknown
        self.fail_on, self.error = fail_on, error
        self.on_commit, self.on_close, self.on_enter = on_commit, on_close, on_enter
        self.listing = listing
        self.log: list[tuple[Any, Any]] = []
        self.committed = False

    def _result(self, stmt: Any, params: Any) -> list[Any]:
        if stmt is self.fail_on:
            raise self.error or RuntimeError("deadlock detected")
        if stmt is m._LOCK_USER:
            return [] if self.status is None else [(self.status,)]
        if stmt is m._USER_EXISTS:
            return [] if self.status is None else [(1,)]
        if stmt is m._LIST_GRANTS:  # what the read selects, ids as the driver returns them
            return [
                (DriverUUID(str(r[0])), *r[1:4], r[4] and DriverUUID(str(r[4])))
                for r in self.listing
            ]
        if stmt is m._KNOWN_ACCOUNTS:
            return [(DriverUUID(i),) for i in params["ids"] if uuid.UUID(i) not in self.unknown]
        if stmt is m._CURRENT:  # a 3-tuple row reads back `frozen = false, frozen_at = NULL`
            pad = (False, None)
            return [(DriverUUID(str(r[0])), *r[1:], *pad[len(r) - 3 :]) for r in self.rows]
        return []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        if self.on_enter is not None:  # the real one runs two `SET LOCAL`s on entry
            raise self.on_enter

        async def execute(stmt: Any, params: Any = None) -> Any:
            self.log.append((stmt, params))
            rows = self._result(stmt, params)
            return SimpleNamespace(first=lambda: rows[0] if rows else None, all=lambda: rows)

        async def commit() -> None:
            if self.on_commit is not None:
                await self.on_commit()
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)
        if self.on_close is not None:  # closing the session fails after a clean body
            raise self.on_close

    def ran(self) -> list[Any]:
        return [stmt for stmt, _ in self.log]

    def params(self, stmt: Any) -> Any:
        return next(p for s, p in self.log if s is stmt)


class _Audit:
    """Records each emit with the statements already run and whether the UoW had committed.
    `error` and `hang` apply to the emits of `action` only."""

    def __init__(
        self,
        rel: _Rel,
        error: Exception | None = None,
        hang: bool = False,
        action: str = "users.access_change",
    ) -> None:
        self.rel, self.error, self.hang, self.action = rel, error, hang, action
        self.calls: list[tuple[str, dict[str, Any], list[Any], bool]] = []
        self.entered = asyncio.Event()

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.calls.append((action, kwargs, self.rel.ran(), self.rel.committed))
        self.entered.set()
        if action != self.action:
            return
        if self.hang:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error


def _store(
    rel: _Rel, audit: AccessAuditEmitter, timeout_s: float = 2.0
) -> m.SqlAlchemyAccountAccessStore:
    return m.SqlAlchemyAccountAccessStore(
        rel,  # type: ignore[arg-type]  # fake unit of work
        audit=audit,
        audit_timeout_s=timeout_s,
    )


def _grants(
    *pairs: tuple[uuid.UUID, str], frozen: frozenset[uuid.UUID] = frozenset()
) -> dict[str, object]:
    items = [
        {"exchange_account_id": str(a), "level": lvl, "frozen": a in frozen} for a, lvl in pairs
    ]
    return {"grants": items}


def _leave(removal: RemovalContext) -> dict[str, object]:
    """What the record of a change that removes a grant adds to `after_state` (#965 O2)."""
    return {
        "positions_decision": "leave",
        "open_position_count": removal.open_position_count,
        "open_order_count": removal.open_order_count,
        "acknowledged_unknown_positions": removal.acknowledged_unknown_positions,
    }


async def _lose_connection() -> None:
    raise RuntimeError("connection lost")


async def _replace(
    rel: _Rel,
    audit: _Audit,
    grants: dict[uuid.UUID, AccessLevel],
    removal: RemovalContext | None = _KNOWN,
) -> AccessChange:
    return await _store(rel, audit).replace_grants(
        _USER, grants, actor_user_id=_ACTOR, request_id=_RID, removal=removal
    )


async def test_replace_reports_the_live_grants_before_and_after() -> None:
    rel = _Rel(rows=_MIXED)
    change = await _replace(rel, _Audit(rel), _SET)
    assert change.before == {_A: "read", _B: "trade"}  # the soft-revoked _D is not live
    assert change.after == _SET and change.changed


async def test_replace_soft_revokes_the_live_grants_left_out() -> None:
    rel = _Rel(rows=_MIXED)
    await _replace(rel, _Audit(rel), _SET)
    assert rel.params(m._REVOKE) == {"id": str(_USER), "revoked": [str(_A)]}


async def test_replace_upserts_the_new_changed_and_regranted_grants() -> None:
    rel = _Rel(rows=_MIXED)
    await _replace(rel, _Audit(rel), _SET)
    assert rel.params(m._UPSERT) == {
        "id": str(_USER),
        "actor": str(_ACTOR),
        "accounts": [str(_B), str(_C), str(_D)],
        "trade": [False, True, False],
    }


async def test_replace_audits_after_the_constraints_and_before_the_commit() -> None:
    rel = _Rel(rows=_MIXED)
    audit = _Audit(rel)
    await _replace(rel, audit, _SET)
    ((_, _, ran_before_emit, committed_before_emit),) = audit.calls
    order = [*_LOCKED_READS, m._REVOKE, m._UPSERT, m._IMMEDIATE]
    assert ran_before_emit == order and not committed_before_emit and rel.committed


async def test_replace_audit_record_names_the_grants_before_and_after() -> None:
    rel = _Rel(rows=_MIXED)
    audit = _Audit(rel)
    await _replace(rel, audit, _SET)
    ((action, kwargs, _, _),) = audit.calls
    assert action == "users.access_change" and action in AUDIT_ACTIONS
    assert kwargs == {
        "actor_label": str(_ACTOR),
        "actor_user_id": _ACTOR,
        "object_kind": "user",
        "object_id": str(_USER),
        "before_state": _grants((_A, "read"), (_B, "trade")),
        "after_state": _grants((_B, "read"), (_C, "trade"), (_D, "read")) | _leave(_KNOWN),
        "request_id": _RID,
        "outcome": "success",
        "reason": None,
    }


async def test_replace_returns_plain_uuid_keys_that_orjson_serialises() -> None:
    rel = _Rel(rows=_LIVE_A)  # read back as the driver's UUID subclass, which orjson refuses
    change = await _replace(rel, _Audit(rel), {_B: "trade"})
    body = orjson.dumps(
        {"before": change.before, "after": change.after}, option=orjson.OPT_NON_STR_KEYS
    )
    assert orjson.loads(body) == {"before": {str(_A): "read"}, "after": {str(_B): "trade"}}


async def test_replace_with_no_grants_soft_revokes_every_live_grant() -> None:
    rel = _Rel(rows=_MIXED)
    change = await _replace(rel, _Audit(rel), {})
    assert change.after == {} and change.changed and rel.committed
    assert rel.ran() == [m._LOCK_TIMEOUT, m._LOCK_USER, m._CURRENT, m._REVOKE, m._IMMEDIATE]
    assert rel.params(m._REVOKE)["revoked"] == [str(_A), str(_B)]


async def test_replace_adding_a_grant_leaves_the_unchanged_ones_unwritten() -> None:
    rel = _Rel(rows=_LIVE_A)
    change = await _replace(rel, _Audit(rel), {_A: "read", _B: "trade"})
    assert change.before == {_A: "read"} and rel.committed
    assert rel.ran() == [*_LOCKED_READS, m._UPSERT, m._IMMEDIATE]
    assert rel.params(m._UPSERT)["accounts"] == [str(_B)]  # _A keeps its granted_by


def test_grant_writes_never_delete_a_row_or_touch_its_freeze_state_or_cap() -> None:
    # #965 O4 / C-12.5: a revoke-then-regrant must not unfreeze a manager or drop its cap.
    for stmt in (m._REVOKE, m._UPSERT):
        sql = stmt.text.lower()
        assert "delete" not in sql and "frozen" not in sql and "max_daily_loss_usd" not in sql


async def test_replace_with_the_current_set_writes_and_audits_nothing() -> None:
    rel = _Rel(rows=((_A, True, True), (_B, False, False)))
    audit = _Audit(rel)
    change = await _replace(rel, audit, {_A: "trade"})
    assert not change.changed and change.after == {_A: "trade"}
    assert rel.ran() == _LOCKED_READS and not audit.calls and not rel.committed


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (None, AccessUserNotFoundError),
        ("invited", AccessUserNotActiveError),
        ("locked", AccessUserNotActiveError),
        ("disabled", AccessUserNotActiveError),
    ],
)
async def test_replace_for_a_missing_or_inactive_user_changes_nothing(
    status: str | None, error: type[Exception]
) -> None:
    rel = _Rel(status=status, rows=_LIVE_A)
    audit = _Audit(rel)
    with pytest.raises(error) as err:
        await _replace(rel, audit, {})
    assert getattr(err.value, "status", None) == status
    assert rel.ran() == [m._LOCK_TIMEOUT, m._LOCK_USER] and not audit.calls
    assert not rel.committed


async def test_replace_naming_an_unknown_account_reports_only_the_unknown_ones() -> None:
    rel = _Rel(unknown=frozenset({_C}))
    with pytest.raises(AccessUnknownAccountError) as err:
        await _replace(rel, _Audit(rel), {_B: "trade", _C: "read"})
    assert err.value.account_ids == frozenset({_C})
    assert rel.params(m._KNOWN_ACCOUNTS) == {"ids": [str(_B), str(_C)]}


async def test_replace_naming_an_unknown_account_rolls_back_the_whole_set() -> None:
    rel = _Rel(rows=_LIVE_A, unknown=frozenset({_C}))
    audit = _Audit(rel)
    with pytest.raises(AccessUnknownAccountError):
        await _replace(rel, audit, {_B: "trade", _C: "read"})
    assert rel.ran() == [m._LOCK_TIMEOUT, m._LOCK_USER, m._KNOWN_ACCOUNTS] and not audit.calls
    assert not rel.committed


@pytest.mark.parametrize(
    ("error", "hang", "timeout_s"),
    [(RuntimeError("audit WAL unavailable"), False, 2.0), (None, True, 0.0)],
    ids=["writer-refuses", "writer-hangs"],
)
async def test_replace_never_commits_when_the_audit_record_cannot_be_written(
    error: Exception | None, hang: bool, timeout_s: float
) -> None:
    rel = _Rel(rows=_LIVE_A)
    audit = _Audit(rel, error=error, hang=hang)
    with pytest.raises(AccessAuditUnavailableError):
        async with asyncio.timeout(_WAIT_S):  # the store's own bound must fire first
            await _store(rel, audit, timeout_s).replace_grants(
                _USER, {}, actor_user_id=_ACTOR, removal=_KNOWN
            )
    # No closing record: a refused record never landed; a hung one may still (the writer
    # finishes an append it has started), and the uncommitted grant rows are the truth.
    assert len(audit.calls) == 1 and not rel.committed


async def test_replace_cancelled_while_auditing_propagates_and_never_commits() -> None:
    rel = _Rel(rows=_LIVE_A)
    audit = _Audit(rel, hang=True)
    task = asyncio.create_task(_replace(rel, audit, {}))
    async with asyncio.timeout(_WAIT_S):
        await audit.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(_WAIT_S):
            await task
    assert len(audit.calls) == 1 and not rel.committed  # unclosed: the rows are the truth


async def test_replace_whose_commit_fails_closes_the_write_ahead_record() -> None:
    rel = _Rel(rows=_LIVE_A, on_commit=_lose_connection)
    audit = _Audit(rel)
    with pytest.raises(RuntimeError, match="connection lost"):
        await _replace(rel, audit, {})
    (_, ahead, _, _), (action, closing, _, _) = audit.calls
    assert action == "users.access_change_failed" and action in AUDIT_ACTIONS
    assert closing == {**ahead, "outcome": "failure", "reason": "commit_failed"}


async def test_replace_cancelled_during_the_commit_closes_the_write_ahead_record() -> None:
    entered = asyncio.Event()

    async def hang() -> None:
        entered.set()
        await asyncio.Event().wait()

    rel = _Rel(rows=_LIVE_A, on_commit=hang)
    audit = _Audit(rel)
    task = asyncio.create_task(_replace(rel, audit, {}))
    async with asyncio.timeout(_WAIT_S):
        await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(_WAIT_S):
            await task
    assert [(a, kw["outcome"], kw["reason"]) for a, kw, _, _ in audit.calls] == [
        ("users.access_change", "success", None),
        ("users.access_change_failed", "failure", "cancelled"),
    ]


async def test_replace_whose_closing_record_fails_keeps_the_commit_error_and_logs_it() -> None:
    rel = _Rel(rows=_LIVE_A, on_commit=_lose_connection)
    audit = _Audit(rel, error=RuntimeError("audit WAL unavailable"), action=m._CHANGE_FAILED)
    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError, match="lost"):
        await _replace(rel, audit, {})
    assert [e["log_level"] for e in logs if e["event"] == _CLOSE_FAILED] == ["error"]


async def test_replace_whose_session_close_fails_after_the_commit_is_still_replaced() -> None:
    rel = _Rel(rows=_LIVE_A, on_close=RuntimeError("connection reset"))
    audit = _Audit(rel)
    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError, match="reset"):
        await _replace(rel, audit, {})
    assert [a for a, _, _, _ in audit.calls] == ["users.access_change"]  # nothing to close
    assert [e["outcome"] for e in logs] == ["replaced"]


class _AuditTable:
    """`audit_log` as the real writer's flusher sees it: `insert` is the one call it makes."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def insert(self, record: dict[str, Any]) -> None:
        self.rows.append(record)


async def test_replace_writes_both_records_through_the_real_audit_writer(tmp_path: Path) -> None:
    # `_store` takes an `AccessAuditEmitter`: mypy --strict proves `AuditWriter` is one, and
    # the writer accepts the store's "success"/"failure" outcomes and both actions.
    table = _AuditTable()
    writer = AuditWriter(cast(AuditRepository, table), str(tmp_path / "audit.wal"))
    rel = _Rel(rows=_LIVE_A, on_commit=_lose_connection)
    await writer.start()
    try:
        with pytest.raises(RuntimeError, match="connection lost"):
            await _store(rel, writer).replace_grants(
                _USER, {}, actor_user_id=_ACTOR, removal=_KNOWN
            )
        await writer.flush(_WAIT_S)
    finally:
        await writer.stop(1)
    assert [(r["action"], r["outcome"]) for r in table.rows] == [
        ("users.access_change", "success"),
        ("users.access_change_failed", "failure"),
    ]


_LogCase = tuple[dict[str, Any], Exception | None, dict[uuid.UUID, AccessLevel], str, str]
#: (fake UoW, write-ahead error, grant set, logged outcome, log level) per exit of a call.
_LOG_CASES: list[_LogCase] = [
    ({"rows": _LIVE_A}, None, {_B: "read"}, "replaced", "info"),
    ({"rows": _LIVE_A}, None, {_A: "read"}, "unchanged", "info"),
    ({"status": None}, None, {}, "user_not_found", "info"),
    ({"status": "locked"}, None, {}, "user_not_active", "info"),
    ({"unknown": frozenset({_B})}, None, {_B: "read"}, "unknown_account", "info"),
    ({"rows": _LIVE_A}, RuntimeError("WAL full"), {}, "audit_unavailable", "warning"),
    ({"rows": _LIVE_A, "on_commit": _lose_connection}, None, {}, "commit_failed", "warning"),
    ({"rows": _LIVE_A, "fail_on": m._REVOKE}, None, {}, "error", "warning"),
]


@pytest.mark.parametrize(
    ("rel", "audit_error", "grants", "outcome", "level"),
    _LOG_CASES,
    ids=[case[3] for case in _LOG_CASES],
)
async def test_replace_logs_one_line_naming_its_outcome(
    rel: dict[str, Any],
    audit_error: Exception | None,
    grants: dict[uuid.UUID, AccessLevel],
    outcome: str,
    level: str,
) -> None:
    fake = _Rel(**rel)
    with structlog.testing.capture_logs() as logs, contextlib.suppress(Exception):
        await _replace(fake, _Audit(fake, error=audit_error), grants)
    assert logs == [
        {
            "event": "account access replace",
            "outcome": outcome,
            "target_user_id": str(_USER),
            "request_id": str(_RID),
            "log_level": level,
        }
    ]


def test_onboarding_binding_readers_ignore_revoked_grants() -> None:
    for stmt in (onboarding._BOUND, onboarding._LATEST_BINDING):
        assert "AND can_view" in stmt.text


# -- S9a: store hardening (#2648, design comment and rulings of 2026-10-16) --------------------


def test_replace_share_locks_the_accounts_so_their_soft_delete_queues() -> None:
    # An account soft delete updates no key column, so it takes `FOR NO KEY UPDATE`: only
    # `FOR SHARE` or stronger conflicts with it (`FOR KEY SHARE` let a grant race the delete).
    assert m._KNOWN_ACCOUNTS.text.endswith("AND deleted_at IS NULL ORDER BY id FOR SHARE")
    assert m._LOCK_USER.text.endswith("AND deleted_at IS NULL FOR NO KEY UPDATE")
    assert m._CURRENT.text.endswith("ORDER BY exchange_account_id FOR NO KEY UPDATE")


async def test_replace_bounds_its_lock_waits_before_taking_a_lock() -> None:
    rel = _Rel(rows=_LIVE_A)
    await _replace(rel, _Audit(rel), {_A: "read"})
    assert rel.ran()[:2] == [m._LOCK_TIMEOUT, m._LOCK_USER]
    assert rel.params(m._LOCK_TIMEOUT) == {"timeout": "5000ms"}


class _DriverError(Exception):
    """asyncpg's error as SQLAlchemy adapts it: a SQLSTATE, and text that may hold row values."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__("DETAIL: Failing row contains (drawdown)")
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("sqlstate", "stmt"),
    [("55P03", m._LOCK_USER), ("55P03", m._KNOWN_ACCOUNTS), ("40P01", m._CURRENT)],
    ids=["user-lock-timeout", "account-lock-timeout", "deadlock"],
)
async def test_replace_whose_lock_wait_fails_is_busy_and_changes_nothing(
    sqlstate: str, stmt: object
) -> None:
    error = DBAPIError("SELECT", None, _DriverError(sqlstate))
    rel = _Rel(rows=_LIVE_A, fail_on=stmt, error=error)
    audit = _Audit(rel)
    with structlog.testing.capture_logs() as logs, pytest.raises(AccessBusyError) as err:
        await _replace(rel, audit, {_B: "read"})
    assert err.value.__cause__ is None and err.value.__suppress_context__  # no driver text
    assert not audit.calls and not rel.committed
    assert [(e["outcome"], e["log_level"]) for e in logs] == [("busy", "warning")]


async def test_replace_whose_statement_fails_otherwise_raises_only_the_sqlstate() -> None:
    error = DBAPIError("INSERT", None, _DriverError("23514"))
    rel = _Rel(rows=_LIVE_A, fail_on=m._UPSERT, error=error)
    with pytest.raises(StorageQueryFailed) as err:
        await _replace(rel, _Audit(rel), {_B: "read"})
    assert err.value.sqlstate == "23514" and "drawdown" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert not rel.committed


async def _driver_commit_failure() -> None:
    raise DBAPIError("COMMIT", None, _DriverError("08006"))


@pytest.mark.parametrize(
    ("rel", "sqlstate", "records", "outcome"),
    [
        ({"on_enter": DBAPIError("SET LOCAL", None, _DriverError("57P01"))}, "57P01", [], "error"),
        (
            {"rows": _LIVE_A, "on_commit": _driver_commit_failure},
            "08006",
            ["users.access_change", "users.access_change_failed"],
            "commit_failed",
        ),
    ],
    ids=["unit-of-work-setup", "commit"],
)
async def test_replace_whose_setup_or_commit_fails_in_the_driver_raises_only_the_sqlstate(
    rel: dict[str, Any], sqlstate: str, records: list[str], outcome: str
) -> None:
    fake = _Rel(**rel)
    audit = _Audit(fake)
    with structlog.testing.capture_logs() as logs, pytest.raises(StorageQueryFailed) as err:
        await _replace(fake, audit, {_B: "read"})
    assert err.value.sqlstate == sqlstate and "drawdown" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert [action for action, _, _, _ in audit.calls] == records  # a failed commit is closed
    assert [e["outcome"] for e in logs] == [outcome]


async def test_replace_of_the_actors_own_grants_is_refused_before_any_statement() -> None:
    rel = _Rel(rows=_LIVE_A)
    audit = _Audit(rel)
    with structlog.testing.capture_logs() as logs, pytest.raises(AccessSelfTargetError):
        await _store(rel, audit).replace_grants(_ACTOR, {}, actor_user_id=_ACTOR, removal=_KNOWN)
    assert not rel.log and not audit.calls  # SR-055: the route refuses and audits it first
    assert [(e["outcome"], e["log_level"]) for e in logs] == [("self_target", "warning")]


@pytest.mark.parametrize(
    ("rows", "donor"),
    [
        (((_A, True, False, True, _T1), (_B, True, True, True, _T2)), _B),
        (((_A, True, False, True, _T2), (_B, True, True, True, _T2)), _A),
        (((_A, False, False, True, _T1), (_B, True, False, True, _T1)), _A),
        (((_A, False, False, True, _T1),), _A),
        (((_A, True, False, True, _T1), (_B, False, False, False, None)), _A),
        (((_A, True, False, True, _T1), (_B, True, False, False, None)), None),
        (((_A, False, False, True, _T1), (_B, True, False, False, None)), None),
        (((_A, True, False, False, None),), None),
        ((), None),
    ],
    ids=[
        "latest-freeze-donates",
        "tie-goes-to-the-lowest-account",
        "a-revoked-frozen-row-counts",
        "every-grant-revoked-still-frozen",
        "a-revoked-unfrozen-row-has-no-say",
        "partial-freeze-is-not-frozen",
        "a-live-unfrozen-row-is-not-frozen",
        "never-frozen",
        "no-rows",
    ],
)
def test_frozen_manager_rule_names_the_donor_row(
    rows: tuple[_FrozenRow, ...], donor: uuid.UUID | None
) -> None:
    # #2648 Q1: frozen = a frozen row, live or soft-revoked, and no live unfrozen row.
    assert m._donor(rows) == donor


async def test_replace_for_a_frozen_manager_freezes_each_row_it_inserts_or_revives() -> None:
    # _A live frozen, widened; _B revoked frozen; _D revoked and never frozen, revived; _C new.
    rows: tuple[_FrozenRow, ...] = (
        (_A, True, False, True, _T2),
        (_B, False, False, True, _T1),
        (_D, False, False, False, None),
    )
    rel = _Rel(rows=rows)
    await _replace(rel, _Audit(rel), {_A: "trade", _C: "read", _D: "read"})
    assert rel.ran()[-3:] == [m._UPSERT, m._INHERIT, m._IMMEDIATE]
    accounts = [str(_A), str(_C), str(_D)]  # `_INHERIT` leaves the already frozen _A alone
    assert rel.params(m._INHERIT) == {"id": str(_USER), "accounts": accounts, "donor": str(_A)}


async def test_replace_audit_record_flags_the_frozen_and_the_inherited_grants() -> None:
    rel = _Rel(rows=((_A, True, False, True, _T1), (_B, False, False, True, _T1)))
    audit = _Audit(rel)
    change = await _replace(rel, audit, {_A: "read", _C: "trade"})
    ((_, kwargs, _, _),) = audit.calls
    assert kwargs["before_state"] == _grants((_A, "read"), frozen=frozenset({_A}))
    after = _grants((_A, "read"), (_C, "trade"), frozen=frozenset({_A, _C}))
    assert kwargs["after_state"] == after and change.frozen == {_A, _B, _C}


async def test_replace_does_not_extend_a_partial_freeze() -> None:
    rel = _Rel(rows=((_A, True, False, True, _T1), (_B, True, False)))
    audit = _Audit(rel)
    await _replace(rel, audit, {_A: "read", _B: "read", _C: "read"})
    assert m._INHERIT not in rel.ran()
    after = _grants((_A, "read"), (_B, "read"), (_C, "read"), frozen=frozenset({_A}))
    assert audit.calls[0][1]["after_state"] == after


def test_upsert_revives_a_row_writing_only_its_access_columns() -> None:
    # #2648 Q1: no grant write lowers a freeze or writes the cap; a revival keeps both.
    assignments = m._UPSERT.text.split("DO UPDATE SET ")[1].split(", ")
    assert [a.split(" = ")[0] for a in assignments] == ["can_view", "can_trade", "granted_by"]


def test_inherit_only_raises_a_freeze_and_never_copies_the_cap() -> None:
    sql = m._INHERIT.text
    assert (
        "SET frozen = true, frozen_at = d.frozen_at, frozen_by = d.frozen_by, "
        "frozen_reason = d.frozen_reason FROM " in sql
    )
    assert sql.endswith("AND NOT g.frozen")
    assert "false" not in sql and "max_daily_loss_usd" not in sql and "delete" not in sql.lower()


@pytest.mark.parametrize(
    "removal",
    [None, RemovalContext(None, 0), RemovalContext(0, None), RemovalContext(None, None)],
    ids=["nothing-read", "positions-unknown", "orders-unknown", "both-unknown"],
)
async def test_replace_removing_any_live_grant_while_a_count_is_unknown_changes_nothing(
    removal: RemovalContext | None,
) -> None:
    rel = _Rel(rows=_MIXED)  # _A and _B live: _A is not the last grant (#2648 Q2)
    audit = _Audit(rel)
    with structlog.testing.capture_logs() as logs, pytest.raises(AccessPositionsUnknownError):
        await _replace(rel, audit, {_B: "trade"}, removal)
    assert rel.ran() == _LOCKED_READS and not audit.calls and not rel.committed
    assert [(e["outcome"], e["log_level"]) for e in logs] == [("positions_unknown", "info")]


async def test_replace_removing_a_grant_records_the_leave_decision_and_the_counts() -> None:
    ack = RemovalContext(None, 3, acknowledged_unknown_positions=True)
    rel = _Rel(rows=_MIXED)
    audit = _Audit(rel)
    await _replace(rel, audit, {_B: "trade"}, ack)
    assert audit.calls[0][1]["after_state"] == _grants((_B, "trade")) | _leave(ack)
    assert rel.committed


async def test_replace_that_removes_no_grant_needs_no_acknowledgement() -> None:
    rel = _Rel(rows=_MIXED)
    audit = _Audit(rel)
    await _replace(rel, audit, {_A: "trade", _B: "read", _C: "read"}, None)  # widen, narrow, add
    assert audit.calls[0][1]["after_state"] == _grants((_A, "trade"), (_B, "read"), (_C, "read"))
    assert rel.committed


# -- S9b: the read behind `GET /users/{userId}/account-access` (#2648) ---------------------------

#: Two live grants as the listing selects them: _A read, granted by the actor; _B trade, whose
#: granting user was deleted since (`granted_by` is NULL).
_LISTED: tuple[_ListedRow, ...] = (
    (_A, False, "main", "live", _ACTOR),
    (_B, True, "sub-1", "demo", None),
)
_ROW_LOCK = re.compile(r"\bFOR\s+(NO\s+KEY\s+UPDATE|UPDATE|SHARE|KEY\s+SHARE)\b", re.IGNORECASE)


async def test_list_grants_returns_each_live_grant_with_its_label_environment_and_granter() -> None:
    rel = _Rel(listing=_LISTED)
    audit = _Audit(rel)
    grants = await _store(rel, audit).list_grants(_USER)
    assert grants == [
        AccessGrant(_A, "read", "main", "live", _ACTOR),
        AccessGrant(_B, "trade", "sub-1", "demo", None),
    ]
    assert rel.ran() == [m._USER_EXISTS, m._LIST_GRANTS]
    assert rel.params(m._LIST_GRANTS) == {"id": str(_USER)}
    assert not audit.calls and not rel.committed  # a read writes and audits nothing
    # the driver's UUID subclass, which orjson refuses, never leaves the store
    assert {type(g.exchange_account_id) for g in grants} == {uuid.UUID}
    assert orjson.loads(orjson.dumps(grants))[0]["granted_by"] == str(_ACTOR)


async def test_list_grants_for_a_missing_or_deleted_user_raises_not_found_and_reads_no_grants() -> (
    None
):
    rel = _Rel(status=None, listing=_LISTED)
    with pytest.raises(AccessUserNotFoundError):
        await _store(rel, _Audit(rel)).list_grants(_USER)
    assert rel.ran() == [m._USER_EXISTS]


def test_the_read_statements_take_no_row_lock_and_write_nothing() -> None:
    # A read must neither queue behind a grant writer nor hold up one (lock order, 21 §3.1.3).
    for stmt in (m._USER_EXISTS, m._LIST_GRANTS):
        assert not _ROW_LOCK.search(stmt.text)
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|SET)\b", stmt.text, re.IGNORECASE)


def test_the_listing_selects_only_the_users_live_grants_of_live_accounts() -> None:
    sql = m._LIST_GRANTS.text
    assert "a.user_id = CAST(:id AS uuid) AND a.can_view AND e.deleted_at IS NULL" in sql
    assert "JOIN exchange_accounts AS e ON e.id = a.exchange_account_id" in sql
    assert sql.endswith("ORDER BY a.exchange_account_id")
    assert m._USER_EXISTS.text.endswith("AND deleted_at IS NULL")
    # no column is truthful for `granted_at`, and freeze state and the cap are not shown
    for column in ("granted_at", "created_at", "updated_at", "frozen", "max_daily_loss_usd"):
        assert column not in sql


@pytest.mark.parametrize("sqlstate", ["55P03", "40P01", "57014"])
async def test_list_grants_whose_statement_fails_raises_only_the_sqlstate(sqlstate: str) -> None:
    error = DBAPIError("SELECT", None, _DriverError(sqlstate))
    rel = _Rel(listing=_LISTED, fail_on=m._LIST_GRANTS, error=error)
    with pytest.raises(StorageQueryFailed) as err:  # a read is never "busy": no lock was taken
        await _store(rel, _Audit(rel)).list_grants(_USER)
    assert err.value.sqlstate == sqlstate and "drawdown" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


async def test_list_grants_whose_unit_of_work_fails_to_open_raises_only_the_sqlstate() -> None:
    rel = _Rel(on_enter=DBAPIError("SET LOCAL", None, _DriverError("57P01")))
    with pytest.raises(StorageQueryFailed) as err:
        await _store(rel, _Audit(rel)).list_grants(_USER)
    assert err.value.sqlstate == "57P01" and "drawdown" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


async def test_list_grants_then_replacing_with_the_same_set_changes_nothing() -> None:
    """The listed grants, sent back as they are, are a no-op, but for a live grant on a
    soft-deleted account: it is not listed, so replacing with the listing revokes it (#3027)."""
    rows: tuple[_Row, ...] = ((_A, True, False), (_B, True, True), (_D, False, False))
    rel = _Rel(rows=rows, listing=_LISTED)  # _D is soft-revoked: not live, not listed
    audit = _Audit(rel)
    store = _store(rel, audit)
    listed = await store.list_grants(_USER)
    again = {g.exchange_account_id: g.level for g in listed}
    change = await store.replace_grants(_USER, again, actor_user_id=_ACTOR, removal=_KNOWN)
    assert not change.changed and not audit.calls and not rel.committed
