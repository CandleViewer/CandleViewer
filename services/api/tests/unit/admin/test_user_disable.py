"""E42-T04 S4 (#965): `UserDisableService` over the S3 store's fake unit of work (Postgres: S3's
integration tests). One log orders every port call."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from structlog.testing import capture_logs

from candleviewer.admin import errors
from candleviewer.admin.user_disable import DisableResult, UserDisableService
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.context import bind_context
from candleviewer.storage.repositories.owner_floor_sqlalchemy import CONSTRAINTS_NOW
from candleviewer.storage.repositories.user_lifecycle import UserSelfTargetError, UserStatusChange
from tests.unit.auth.test_step_up import _T0 as _NOW
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _A, _B, _GUARD_S, _S1, _Rel, _store

_OWNER = PrincipalSnapshot(uuid.uuid4(), frozenset({"owner"}), frozenset(Permission))
_MANAGER = PrincipalSnapshot(uuid.uuid4(), frozenset({"manager"}), frozenset())
_TARGET, _RID = uuid.uuid4(), uuid.uuid4()
_AUDIT_DOWN = errors.LifecycleAuditUnavailableError
_OPEN, _CLOSE = ("success", None, "disabled"), ("failure", "not_applied", "active")
_UNKNOWN = ("failure", "outcome_unknown", None)  # the commit may have gone through: no after state


class _World:
    """Every port but the S3 store (exposure: reads only, O2); `fail[action]` raises."""

    source = "not_deployed"  # the position provider's

    def __init__(
        self,
        rel: _Rel | None = None,
        *,
        fail: dict[str, list[BaseException]] | None = None,
        positions: int | Exception | None = 0,
        orders: int | None = 0,
        store: Any = None,
        **ports: Any,
    ) -> None:
        self.log, self.calls = list[str](), list[dict[str, Any]]()
        self.rel, self.fail = rel or _Rel(), fail or {}
        self.positions, self.orders = positions, orders
        self.svc = UserDisableService(
            store or _store(self.rel),
            self,
            positions=self,
            orders=self,
            clock=lambda: _NOW,
            **{k: v for k, v in ports.items() if k.endswith("_s")},
        )

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.log.append(action)
        if self.fail.get(action):
            raise self.fail[action].pop(0)
        self.calls.append({"action": action, **kwargs})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["action"] == action]

    async def open_position_count(self, user_id: str) -> int | None:
        self.log.append("positions")
        if isinstance(self.positions, Exception):
            raise self.positions
        return self.positions

    async def open_order_count(self, user_id: str) -> int | None:
        self.log.append("orders")
        return self.orders

    async def disable(self, actor: PrincipalSnapshot = _OWNER, **kw: Any) -> DisableResult:
        return await self.svc.disable(_TARGET, actor=actor, **kw)


@pytest.mark.parametrize(
    ("world", "error"),
    [
        (lambda: _World(_Rel(roles=("owner",), owners=1)), errors.LastOwnerError),
        (lambda: _World(fail={"users.disable": [AuditUnavailable("wal")]}), _AUDIT_DOWN),
        (lambda: _World(_Rel(raise_at=CONSTRAINTS_NOW, sqlstate="40001")), IntegrityError),
        (lambda: _World(_Rel(status=None)), errors.UserNotFoundError),
    ],
    ids=["last_owner", "audit_down", "store_error", "not_found"],
)
async def test_store_failure_no_post_commit(
    world: Callable[[], _World], error: type[Exception]
) -> None:
    """UL1-T1, UL1-D1, AC8: no record unless the change committed."""
    w = world()
    with pytest.raises(error):
        await w.disable()
    assert not w.rel.committed and w.calls == []


def _records(w: _World) -> list[tuple[Any, ...]]:  # each record's outcome, reason, after status
    return [
        (c["outcome"], c.get("reason"), (c["after_state"] or {}).get("status")) for c in w.calls
    ]


@pytest.mark.parametrize(
    ("fail", "error", "records"),
    [
        ([TimeoutError()], _AUDIT_DOWN, [_CLOSE]),
        ([ValueError("bad record")], ValueError, [_CLOSE]),
        ([asyncio.CancelledError()], asyncio.CancelledError, [_CLOSE]),
        ([TimeoutError(), AuditUnavailable("down")], _AUDIT_DOWN, []),
    ],
    ids=["hook_timeout", "hook_raise", "hook_cancelled", "closing_failed"],
)
async def test_unapplied_record_is_closed(
    fail: list[BaseException], error: type[BaseException], records: list[Any]
) -> None:
    """AC8, S3: a hook that timed out (503), raised or was cancelled never reached the commit:
    its record is closed by `not_applied`, rolled back, with the state before == after."""
    w = _World(fail={"users.disable": list(fail)})
    with pytest.raises(error):
        await w.disable()
    assert _records(w) == records
    assert not w.rel.committed


@pytest.mark.parametrize(
    "error", [TimeoutError("commit lost"), OSError("connection reset")], ids=["timeout", "reset"]
)
async def test_commit_failure_is_closed_as_outcome_unknown(error: Exception) -> None:
    """S3, C-2.9: the hook returned, so the commit was sent; that it failed (a driver timeout is
    not `WriteAheadTimeout`, so no 503) does not say it did not apply. The record says so, with
    the state before and no after state, and the caller still gets the error. A retry does not
    settle it: AC5's no-op returns no ids (the store's `disable` docstring)."""
    w = _World(_Rel(commit_error=error))
    with pytest.raises(type(error)):
        await w.disable()
    assert _records(w) == [_OPEN, _UNKNOWN]
    assert w.calls[-1]["before_state"] == {"status": "active", "roles": ["manager"]}
    assert w.calls[-1]["after_state"] is None and not w.rel.committed


async def test_cancelled_commit_is_closed_as_outcome_unknown() -> None:
    """S3, C-2.9: a request cancelled during the commit may have committed: not `not_applied`."""
    committing = asyncio.Event()

    async def commit_hangs(*_: Any, audit: Any, **__: Any) -> Any:
        await audit(UserStatusChange(_TARGET, "active", "disabled", frozenset({"manager"}), (_S1,)))
        committing.set()  # the hook returned: the store sends its commit
        return await _hang()

    w = _World(store=SimpleNamespace(disable=commit_hangs))
    call = asyncio.create_task(w.disable())
    await asyncio.wait_for(committing.wait(), _GUARD_S)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert _records(w) == [_OPEN, _UNKNOWN]


async def test_closing_record_that_raises_before_its_awaitable_is_a_failed_step_not_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7: an audit port that raises before it returns an awaitable (a plain function) fails the
    `closing_record` step; the commit's own error, not that one, still reaches the caller."""
    w = _World(_Rel(commit_error=TimeoutError("commit lost")))
    real = w.emit

    def emit(action: str, **kwargs: Any) -> Awaitable[None]:
        if kwargs["outcome"] == "failure":
            raise LookupError("closing record")
        return real(action, **kwargs)

    monkeypatch.setattr(w, "emit", emit)
    with capture_logs() as logs, pytest.raises(TimeoutError, match="commit lost"):
        await w.disable()
    lines = [(e["step"], e["outcome"], e["attempted"], e["error"]) for e in logs if "step" in e]
    assert lines == [("closing_record", "failed", 1, "LookupError")]


async def test_self_target_403_audited() -> None:
    """AC6, SR-055: disabling oneself is refused before any read, audited `self_target`."""
    w = _World()
    with pytest.raises(errors.LifecycleForbiddenError) as refused:
        await w.svc.disable(_OWNER.user_id, actor=_OWNER)
    assert (refused.value.reason, refused.value.code) == ("self_target", "forbidden")
    assert w.log == ["rbac.denied"] and w.rel.ran == []
    (call,) = w.calls
    assert (call["reason"], call["outcome"]) == ("self_target", "denied")
    assert call["object_id"] == call["actor_label"] == str(_OWNER.user_id)


@pytest.mark.parametrize("target", [_TARGET, uuid.uuid4()], ids=["existing", "missing"])
async def test_forbidden_role_refused_before_lookup_audited(target: uuid.UUID) -> None:
    """D1, U25: a Manager is refused and audited (request, target) before any read of the id."""
    w = _World()
    with bind_context(request_id=str(_RID)), pytest.raises(errors.LifecycleForbiddenError) as no:
        await w.svc.disable(target, actor=_MANAGER)
    assert no.value.reason == "forbidden_role" and w.rel.ran == [] and w.log == ["rbac.denied"]
    (call,) = w.calls
    assert (call["reason"], call["request_id"]) == ("missing_permission:users:write:none", _RID)
    assert (call["object_kind"], call["object_id"]) == ("user", str(target))


async def test_store_self_target_is_the_audited_403() -> None:
    """SR-055: the store's own self-target refusal is the same audited 403, not an error."""
    w = _World(store=SimpleNamespace(disable=AsyncMock(side_effect=UserSelfTargetError("self"))))
    with pytest.raises(errors.LifecycleForbiddenError, match="self_target"):
        await w.disable()
    assert [(c["action"], c["reason"]) for c in w.calls] == [("rbac.denied", "self_target")]


@pytest.mark.parametrize(
    ("actor", "target"), [(_OWNER, _OWNER.user_id), (_MANAGER, _TARGET)], ids=["self", "role"]
)
async def test_refusal_with_audit_down_is_503(actor: PrincipalSnapshot, target: uuid.UUID) -> None:
    """AC8: a refusal (self-target or role) whose record cannot be written is a 503."""
    w = _World(fail={"rbac.denied": [AuditUnavailable("down")]})
    with pytest.raises(errors.LifecycleAuditUnavailableError):
        await w.svc.disable(target, actor=actor)
    assert w.rel.ran == []


@pytest.mark.parametrize(
    ("positions", "orders", "recorded"),
    [(None, 0, (None, 0)), (0, None, (0, None)), (RuntimeError("down"), 3, (None, 3))],
    ids=["positions_unknown", "orders_unknown", "positions_unreadable"],
)
async def test_open_orders_left_and_counted(
    positions: int | Exception | None, orders: int | None, recorded: tuple[int | None, ...]
) -> None:
    """AC7, UL-F9: an unknown count needs the acknowledgement, then is recorded as null."""
    refused = _World(positions=positions, orders=orders)
    with pytest.raises(errors.PositionsUnknownError) as error:
        await refused.disable()
    assert (error.value.code, error.value.source) == ("positions_unknown", "not_deployed")
    assert not refused.rel.committed and refused.calls == []
    acked = _World(positions=positions, orders=orders)
    assert await acked.disable(acknowledge_unknown_positions=True) == DisableResult(changed=True)
    after = acked.of("users.disable")[0]["after_state"]
    assert (after["open_position_count"], after["open_order_count"]) == recorded
    assert (after["positions_decision"], after["acknowledged_unknown_positions"]) == ("leave", True)


async def test_positions_decision_never_flattens() -> None:
    """O2, O6, UL-F1: known counts need no acknowledgement and are recorded with `leave` (reads
    only), in a `users.disable` of ids, status, roles and counts only."""
    w = _World(positions=2, orders=1)
    with bind_context(request_id=str(_RID)):
        assert await w.disable() == DisableResult(changed=True)
    who = {"actor_label": str(_OWNER.user_id), "actor_user_id": _OWNER.user_id, "request_id": _RID}
    who |= {"action": "users.disable", "object_kind": "user", "object_id": str(_TARGET)}
    who |= {"outcome": "success", "severity": "warning"}
    old = {"status": "active", "roles": ["manager"], "grants": {str(_A): "trade", str(_B): "read"}}
    new = {"status": "disabled", "roles": ["manager"], "grants": {}, "sessions_revoked": 2}
    new |= {"positions_decision": "leave", "open_position_count": 2, "open_order_count": 1}
    new |= {"acknowledged_unknown_positions": False}
    assert w.of("users.disable") == [who | {"before_state": old, "after_state": new}]


def _keys(call: dict[str, Any]) -> tuple[Any, ...]:  # the record's keys, then its states'
    return call["action"], set(call), set(call["before_state"]), set(call["after_state"] or ())


async def test_lifecycle_audit_has_no_pii() -> None:
    """UL-F1, O6: lifecycle records carry ids, status, roles and counts only (no email, name or
    address; the actor label is the id), so any new key fails here."""
    done, closed = _World(), _World(fail={"users.disable": [TimeoutError()]})
    lost = _World(_Rel(commit_error=TimeoutError("commit lost")))
    assert await done.disable() == DisableResult(changed=True)
    with pytest.raises(_AUDIT_DOWN):
        await closed.disable()
    with pytest.raises(TimeoutError):
        await lost.disable()
    calls = done.calls + closed.calls + lost.calls[-1:]  # `lost`: its closing record only
    who = {"action", "actor_label", "actor_user_id", "object_kind", "object_id", "request_id"}
    record = who | {"outcome", "severity", "before_state", "after_state"}
    state = {"status", "roles"}
    after = state | {"grants", "sessions_revoked", "positions_decision", "open_position_count"}
    after |= {"open_order_count", "acknowledged_unknown_positions"}
    assert [_keys(c) for c in calls] == [
        ("users.disable", record, state | {"grants"}, after),
        ("users.disable", record | {"reason"}, state, state),
        ("users.disable", record | {"reason"}, state, set()),
    ]
    assert {c["actor_label"] for c in calls} == {str(_OWNER.user_id)}


async def test_already_disabled_is_a_noop() -> None:
    """AC5: a repeat needs no acknowledgement and commits nothing, unaudited."""
    w = _World(_Rel(status="disabled"), positions=None)
    assert await w.disable() == DisableResult(changed=False)
    assert w.calls == [] and w.log == ["positions", "orders"] and not w.rel.committed


async def _hang(*_: Any, **__: Any) -> Any:
    await asyncio.Event().wait()


@pytest.mark.parametrize("read", ["open_position_count", "open_order_count"])
async def test_hung_count_is_unknown(read: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC7: a count read past its bound is unknown, never a hang: refused without the
    acknowledgement, recorded as null with it (the guard only ends a regression's hang)."""
    refused, acked = _World(count_timeout_s=0), _World(count_timeout_s=0)
    for w in (refused, acked):
        monkeypatch.setattr(w, read, _hang)
    with pytest.raises(errors.PositionsUnknownError):
        await asyncio.wait_for(refused.disable(), _GUARD_S)
    assert not refused.rel.committed and refused.calls == []
    ack = acked.disable(acknowledge_unknown_positions=True)
    assert await asyncio.wait_for(ack, _GUARD_S) == DisableResult(changed=True)
    assert acked.of("users.disable")[0]["after_state"][read] is None
