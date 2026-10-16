"""E42-T08 S8 (#2648): `SqlAlchemyAccountAccessStore` over a fake unit of work. Real Postgres
(transaction, rollback, races): tests/integration/storage/test_account_access_store_pg.py."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import orjson
import pytest
import structlog
from asyncpg.pgproto.pgproto import UUID as DriverUUID

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.storage.repositories import account_access_sqlalchemy as m
from candleviewer.storage.repositories import onboarding_sqlalchemy as onboarding
from candleviewer.storage.repositories.account_access import (
    AccessAuditUnavailableError,
    AccessChange,
    AccessLevel,
    AccessUnknownAccountError,
    AccessUserNotActiveError,
    AccessUserNotFoundError,
)

_USER, _ACTOR, _RID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
_A, _B, _C, _D = sorted(uuid.uuid4() for _ in range(4))
_Row = tuple[uuid.UUID, bool, bool]  # (exchange_account_id, can_view, can_trade)
_LIVE_A: tuple[_Row, ...] = ((_A, True, False),)
#: _A read, _B trade, and _D soft-revoked (not live).
_MIXED: tuple[_Row, ...] = ((_A, True, False), (_B, True, True), (_D, False, False))
#: Replaces `_MIXED`: _A left out, _B down to read, _C new, _D granted again.
_SET: dict[uuid.UUID, AccessLevel] = {_B: "read", _C: "trade", _D: "read"}
#: Bounds every wait on a fake: a regression fails fast instead of hanging CI.
_WAIT_S = 5.0
_CLOSE_FAILED = "account access closing audit record not written"


class _Rel:
    """Fake UoW keyed by statement: records each statement, its params and the commit. Ids come
    back as asyncpg's own `uuid.UUID` subclass, as the driver returns them."""

    def __init__(
        self,
        status: str | None = "active",
        rows: tuple[_Row, ...] = (),
        unknown: frozenset[uuid.UUID] = frozenset(),
        *,
        fail_on: object = None,
        on_commit: Callable[[], Awaitable[None]] | None = None,
        on_close: Exception | None = None,
    ) -> None:
        self.status, self.rows, self.unknown = status, rows, unknown
        self.fail_on, self.on_commit, self.on_close = fail_on, on_commit, on_close
        self.log: list[tuple[Any, Any]] = []
        self.committed = False

    def _result(self, stmt: Any, params: Any) -> list[Any]:
        if stmt is self.fail_on:
            raise RuntimeError("deadlock detected")
        if stmt is m._LOCK_USER:
            return [] if self.status is None else [(self.status,)]
        if stmt is m._KNOWN_ACCOUNTS:
            return [(DriverUUID(i),) for i in params["ids"] if uuid.UUID(i) not in self.unknown]
        if stmt is m._CURRENT:
            return [(DriverUUID(str(a)), view, trade) for a, view, trade in self.rows]
        return []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
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


def _store(rel: _Rel, audit: _Audit, timeout_s: float = 2.0) -> m.SqlAlchemyAccountAccessStore:
    return m.SqlAlchemyAccountAccessStore(
        rel,  # type: ignore[arg-type]  # fake unit of work
        audit=audit,
        audit_timeout_s=timeout_s,
    )


def _grants(*pairs: tuple[uuid.UUID, str]) -> dict[str, object]:
    return {"grants": [{"exchange_account_id": str(a), "level": lvl} for a, lvl in pairs]}


async def _lose_connection() -> None:
    raise RuntimeError("connection lost")


async def _replace(rel: _Rel, audit: _Audit, grants: dict[uuid.UUID, AccessLevel]) -> AccessChange:
    return await _store(rel, audit).replace_grants(
        _USER, grants, actor_user_id=_ACTOR, request_id=_RID
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
    order = [m._LOCK_USER, m._KNOWN_ACCOUNTS, m._CURRENT, m._REVOKE, m._UPSERT, m._IMMEDIATE]
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
        "after_state": _grants((_B, "read"), (_C, "trade"), (_D, "read")),
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
    assert rel.ran() == [m._LOCK_USER, m._CURRENT, m._REVOKE, m._IMMEDIATE]
    assert rel.params(m._REVOKE)["revoked"] == [str(_A), str(_B)]


async def test_replace_adding_a_grant_leaves_the_unchanged_ones_unwritten() -> None:
    rel = _Rel(rows=_LIVE_A)
    change = await _replace(rel, _Audit(rel), {_A: "read", _B: "trade"})
    assert change.before == {_A: "read"} and rel.committed
    assert rel.ran() == [m._LOCK_USER, m._KNOWN_ACCOUNTS, m._CURRENT, m._UPSERT, m._IMMEDIATE]
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
    assert rel.ran() == [m._LOCK_USER, m._KNOWN_ACCOUNTS, m._CURRENT]
    assert not audit.calls and not rel.committed


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
    assert rel.ran() == [m._LOCK_USER] and not audit.calls and not rel.committed


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
    assert rel.ran() == [m._LOCK_USER, m._KNOWN_ACCOUNTS] and not audit.calls
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
            await _store(rel, audit, timeout_s).replace_grants(_USER, {}, actor_user_id=_ACTOR)
    assert len(audit.calls) == 1 and not rel.committed  # nothing written ahead: nothing to close


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
    assert not rel.committed


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
