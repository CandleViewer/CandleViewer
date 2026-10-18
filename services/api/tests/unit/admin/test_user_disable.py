"""E42-T04 S4, S5 (#965): `UserDisableService` over the S3 store's fake unit of work (Postgres:
S3's integration tests). One log orders every port call; `!open` marks a call before the commit.
The rule steps (S5) run here against fakes, and against the real rule engine through the
adapters in the last tests (`tests/unit/test_user_cascade_wiring.py` covers the adapters)."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError
from structlog.testing import capture_logs

from candleviewer.admin import errors
from candleviewer.admin.lifecycle_metrics import (
    ACTION_RESULTS,
    STEP_OUTCOMES,
    user_lifecycle_steps_total,
    user_lifecycle_total,
)
from candleviewer.admin.user_disable import DisableResult, UserDisableService
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import InviteNotFound
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.invite_repository import InviteAudit
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_chart import SessionChart, SessionChartError
from candleviewer.auth.session_service import SessionService
from candleviewer.observability.context import bind_context
from candleviewer.rules.manager import RuleError
from candleviewer.rules.scope_state import SnapshotScopeState
from candleviewer.storage.repositories.owner_floor_sqlalchemy import CONSTRAINTS_NOW, LOCK_USER
from candleviewer.storage.repositories.user_lifecycle import UserSelfTargetError, UserStatusChange
from candleviewer.user_cascade_wiring import ScopeRefreshAdapter
from candleviewer.ws.revocation import (
    CLOSE_USER_DISABLED,
    RevocationHub,
    auth_revocation_latency_seconds,
)
from tests.conftest import RecordingAuditSink
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_step_up import _T0 as _NOW
from tests.unit.auth.test_step_up import _session
from tests.unit.storage.test_user_lifecycle_sqlalchemy import (
    _A,
    _B,
    _GUARD_S,
    _S1,
    _S2,
    _Rel,
    _store,
)
from tests.unit.test_user_cascade_wiring import _actor, _Engine, _Source

_OWNER = PrincipalSnapshot(uuid.uuid4(), frozenset({"owner"}), frozenset(Permission))
_MANAGER = PrincipalSnapshot(uuid.uuid4(), frozenset({"manager"}), frozenset())
_TARGET, _RID = uuid.uuid4(), uuid.uuid4()
_POST_COMMIT = ("socket", "sweep", "b16", "scope", "rules", "disarm", "invite")
_STEPS = (
    *("socket_close", "session_sweep", "b16_revoke", "scope_refresh", "rule_disarm"),
    "invite_revoke",
)
_AUDIT_DOWN, _INVITE = errors.LifecycleAuditUnavailableError, ("invite_revoke",)
_OPEN, _CLOSE = ("success", None, "disabled"), ("failure", "not_applied", "active")
_UNKNOWN = ("failure", "outcome_unknown", None)  # the commit may have gone through: no after state


def _revoked(record: SessionRecord) -> SessionRecord:
    return record.model_copy(update={"revoked_at": _NOW, "revoked_reason": "user_disabled"})


class _World:
    """Every port but the S3 store (exposure: reads only, O2); `fail[action]` and `invite` raise.
    The user owns the `armed` rules, and disarming one of `refuse` raises its error (S5)."""

    source = "not_deployed"  # the position provider's

    def __init__(
        self,
        rel: _Rel | None = None,
        *,
        fail: dict[str, list[BaseException]] | None = None,
        positions: int | Exception | None = 0,
        orders: int | None = 0,
        invite: Exception | None = None,
        store: Any = None,
        armed: tuple[str, ...] = (),
        refuse: dict[str, Exception] | None = None,
        **ports: Any,
    ) -> None:
        self.log, self.calls = list[str](), list[dict[str, Any]]()
        self.rel, self.fail, self.invite = rel or _Rel(), fail or {}, invite
        self.positions, self.orders = positions, orders
        self.armed, self.refuse = armed, refuse or {}
        self.disarms = list[tuple[str, uuid.UUID, uuid.UUID, datetime]]()
        self.socket_users = list[uuid.UUID]()
        self.svc = UserDisableService(
            store or _store(self.rel),
            self,
            positions=self,
            orders=self,
            sessions=ports.get("sessions", self),
            session_rows=ports.get("rows", self),
            chart=ports.get("chart", SimpleNamespace(revoke=self.record)),
            publish_revocation=ports.get("publish", self.publish),
            close_user_sockets=ports.get("sockets", self.close_user_sockets),
            invites=ports.get("invites", SimpleNamespace(revoke=self.revoke_invite)),
            rules=ports.get("rules", self),
            scope=ports.get("scope", SimpleNamespace(refresh=self.refresh_scope)),
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

    def mark(self, entry: str) -> None:
        self.log.append(entry if self.rel.committed else f"{entry}!open")

    async def publish(self, session_id: str, reason: str) -> None:
        self.mark(f"socket:{reason}")

    async def close_user_sockets(self, user_id: uuid.UUID) -> int:
        self.mark("socket:user")  # every socket of the user, on whatever session (S7)
        self.socket_users.append(user_id)
        return 0

    async def revoke_all(self, user_id: str, *, reason: str) -> tuple[SessionRecord, ...]:
        self.mark(f"sweep:{reason}")
        return ()

    async def find_by_id(self, session_id: str) -> SessionRecord | None:
        return _revoked(_session(_TARGET)).model_copy(update={"id": uuid.UUID(session_id)})

    async def record(self, record: SessionRecord, now: object, reason: str) -> None:
        self.mark(f"b16:{reason}")

    async def revoke_invite(self, user_id: uuid.UUID, *, audit: InviteAudit) -> None:
        self.mark("invite")  # as `InviteService.revoke`: the hook runs only for an open invite
        if self.invite is not None:
            raise self.invite
        await audit(user_id, "viewer")

    async def refresh_scope(self, user_id: uuid.UUID) -> None:
        self.mark("scope")

    async def armed_rule_ids(self, user_id: uuid.UUID) -> tuple[str, ...]:
        self.mark("rules")
        return self.armed

    async def disarm(
        self, rule_id: str, *, user_id: uuid.UUID, actor: uuid.UUID, disabled_at: datetime
    ) -> None:
        self.mark(f"disarm:{rule_id}")
        self.disarms.append((rule_id, user_id, actor, disabled_at))
        if rule_id in self.refuse:
            raise self.refuse[rule_id]

    async def disable(self, actor: PrincipalSnapshot = _OWNER, **kw: Any) -> DisableResult:
        return await self.svc.disable(_TARGET, actor=actor, **kw)

    def post_commit(self) -> list[str]:
        return [entry for entry in self.log if entry.startswith(_POST_COMMIT)]


async def test_step_order() -> None:
    """R7: exposure, `users.disable` before the commit, then sockets (each revoked session's, then
    every one of the user's, S7), sweep, B16, the scope refresh, the rule disarm (list, then each
    rule) and the invite."""
    w = _World(_Rel(status="invited", sessions=(_S1, _S2)), armed=("r1", "r2"))
    assert await w.disable() == DisableResult(changed=True)
    assert w.log == [
        *("positions", "orders", "users.disable", "socket:user_disabled", "socket:user_disabled"),
        *("socket:user", "sweep:user_disabled", "b16:user_disabled", "b16:user_disabled"),
        *("scope", "rules", "disarm:r1", "disarm:r2", "rules", "invite"),
        "users.invite_revoked",
    ]
    assert w.socket_users == [_TARGET]
    (invite,) = w.of("users.invite_revoked")
    assert (invite["actor_user_id"], invite["object_id"]) == (_OWNER.user_id, str(_TARGET))
    assert (invite["reason"], invite["after_state"]) == ("user_disabled", {"role": "viewer"})


def _closes_timed() -> float:  # observations of the hub's close-latency histogram, as a delta
    (family,) = auth_revocation_latency_seconds.collect()
    return next(s.value for s in family.samples if s.name.endswith("_count"))


async def test_b16_revoke_per_session(b16_audit: RecordingAuditSink) -> None:
    """R5 on the real B16 chart and hub: one `auth.session_revoked` and one 4403 per session.
    #965 Observability: each session's close is timed once, on the hub's close-latency histogram
    (`ws_session_revocation_close_seconds`); the cascade adds no histogram of its own."""
    repo, hub, closed = FakeSessionRepository(), RevocationHub(), dict[str, tuple[str, int]]()
    rows = [_revoked(_session(_TARGET)), _revoked(_session(_TARGET)), _session(_TARGET)]
    for row in rows:
        await repo.create_session(row)

        async def close(frame: dict[str, Any], code: int, sid: str = str(row.id)) -> None:
            closed[sid] = (frame["p"]["reason"], code)

        hub.register(str(row.id), close)

    async def publish(session_id: str, reason: str) -> None:
        await hub.revoke(session_id, reason)

    sessions = SessionService(repo, Hasher(), clock=lambda: _NOW, publish_revocation=publish)
    rel = _Rel(sessions=[r.id for r in rows[:2]])
    w = _World(rel, sessions=sessions, rows=repo, chart=SessionChart(), publish=publish)
    timed = _closes_timed()
    assert await w.disable() == DisableResult(changed=True)
    assert sorted((c["action"], c["session_id"], c["reason"]) for c in b16_audit.calls) == sorted(
        ("auth.session_revoked", str(r.id), "user_disabled") for r in rows
    )
    assert closed == {str(r.id): ("user_disabled", CLOSE_USER_DISABLED) for r in rows}
    assert _closes_timed() - timed == len(rows)


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
    """UL1-T1, UL1-D1, AC8: no post-commit step and no record unless the change committed."""
    w = world()
    with pytest.raises(error):
        await w.disable()
    assert not w.rel.committed and w.calls == [] and w.post_commit() == []


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
    assert w.post_commit() == [] and not w.rel.committed


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
    assert not refused.rel.committed and refused.calls == [] == refused.post_commit()
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
    states = [set(call.get(name) or ()) for name in ("before_state", "after_state")]
    return call["action"], set(call), *states


async def test_lifecycle_audit_has_no_pii() -> None:
    """UL-F1, O6: lifecycle records carry ids, status, roles and counts only (no email, name or
    address; the actor label is the id), so any new key fails here."""
    done, closed = _World(_Rel(status="invited")), _World(fail={"users.disable": [TimeoutError()]})
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
        ("users.invite_revoked", who | {"after_state", "reason"}, set(), {"role"}),
        ("users.disable", record | {"reason"}, state, state),
        ("users.disable", record | {"reason"}, state, set()),
    ]
    assert {c["actor_label"] for c in calls} == {str(_OWNER.user_id)}


@pytest.mark.parametrize(
    ("status", "kw", "records", "failed"),
    [
        ("invited", {}, 1, ()),
        ("invited", {"invite": InviteNotFound("none open")}, 0, ()),
        ("invited", {"invite": OSError("invites down")}, 0, _INVITE),
        ("invited", {"fail": {"users.invite_revoked": [AuditUnavailable("down")]}}, 0, _INVITE),
        ("active", {}, 0, ()),
    ],
    ids=["invited", "invite_already_gone", "revoke_failed", "record_refused", "active"],
)
async def test_invited_revokes_invite(
    status: str, kw: dict[str, Any], records: int, failed: tuple[str, ...]
) -> None:
    """R6, UL1-E4, C-2.9: the invite store writes one record ahead, only if one is open."""
    w = _World(_Rel(status=status), **kw)
    assert await w.disable() == DisableResult(True, failed)
    assert len(w.of("users.invite_revoked")) == records
    assert ("invite" in w.log) == (status == "invited")


async def test_already_disabled_is_a_noop_that_sweeps_and_disarms_again() -> None:
    """AC5: a repeat needs no acknowledgement, commits nothing (`!open`), writes no record, and
    closes every socket of the user (S7), sweeps, refreshes the scope and looks for armed rules
    again (SR-029): all four are idempotent and keep the cascade re-drivable."""
    w = _World(_Rel(status="disabled"), positions=None)
    assert await w.disable() == DisableResult(changed=False)
    assert w.calls == [] and w.log == [
        *("positions", "orders", "socket:user!open", "sweep:user_disabled!open", "scope!open"),
        *("rules!open", "rules!open"),
    ]
    assert w.socket_users == [_TARGET]


async def test_repeat_disarms_a_rule_the_first_call_could_not() -> None:
    """R7: the first call's disarm of a rule failed (counted, alerted), so the user is disabled
    with the rule still armed; the same DELETE again disarms it, though it is AC5's no-op."""
    w = _World(_Rel(status="disabled"), armed=("r1",))
    assert await w.disable() == DisableResult(changed=False)
    assert w.disarms == [("r1", _TARGET, _OWNER.user_id, _NOW)]
    assert w.post_commit() == [
        *("socket:user!open", "sweep:user_disabled!open", "scope!open", "rules!open"),
        *("disarm:r1!open", "rules!open"),
    ]


async def test_retry_after_an_unknown_commit_closes_the_sockets_not_b16() -> None:
    """AC5, S3, S7 (S6's Left item 7): the commit failed on the wire but had gone through
    (`outcome_unknown`), and the ids it revoked died with the error, so the call ran no step. The
    retry finds the user disabled: it writes no record, commits nothing and has no ids, so it
    closes every socket of the user, which ends the sockets of those two sessions, and sweeps
    (SR-029). B16 records neither session: a residual (`e42-user-lifecycle.md` §6)."""
    w = _World(_Rel(sessions=(_S1, _S2), commit_error=TimeoutError("commit lost")))
    with pytest.raises(TimeoutError):
        await w.disable()
    assert w.post_commit() == [] and w.calls[-1]["reason"] == "outcome_unknown"
    w.rel.rows[LOCK_USER] = [("disabled",)]  # the commit had gone through after all
    assert await w.disable() == DisableResult(changed=False)
    assert len(w.of("users.disable")) == 2 and w.post_commit() == [
        *("socket:user!open", "sweep:user_disabled!open", "scope!open", "rules!open"),
        "rules!open",
    ]
    assert w.socket_users == [_TARGET]


async def test_cancelled_caller_leaves_the_steps_to_finish() -> None:
    """R7: a request cancelled after the commit cannot cut the steps short: shielded, they run."""
    gate = asyncio.Event()

    async def publish(*_: Any) -> None:  # the request goes away while the first step runs
        call.cancel()
        await gate.wait()

    w = _World(_Rel(status="invited", sessions=(_S1,)), publish=publish)
    call = asyncio.create_task(w.disable())
    with pytest.raises(asyncio.CancelledError):
        await call
    gate.set()
    await w.svc.drain()
    assert w.post_commit() == [
        *("socket:user", "sweep:user_disabled", "b16:user_disabled", "scope", "rules", "rules"),
        "invite",
    ]


async def test_cancelled_steps_are_failed_then_reraised() -> None:
    """R7: steps that a cancellation of their task (shutdown) cuts off are failed, not skipped;
    the cancellation then reaches the caller, and `drain` returns."""

    async def publish(*_: Any) -> None:  # the steps' task is cancelled while a step runs
        (steps,) = [t for t in asyncio.all_tasks() if t.get_name() == "user-disable-steps"]
        steps.cancel()
        await asyncio.Event().wait()

    w = _World(_Rel(status="invited", sessions=(_S1,)), publish=publish)
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await w.disable()
    await w.svc.drain()
    lines = [(e["step"], e["outcome"], e["error"]) for e in logs if "step" in e]
    assert lines == [(step, "failed", "CancelledError") for step in _STEPS]


class _Fatal(BaseException):
    """Not an `Exception`: like a cancellation, it leaves the steps' task once counted."""


async def test_steps_raise_after_the_caller_left_is_logged() -> None:
    """R7: a raise out of the steps' task (only a non-`Exception` gets out) is logged at error,
    though no caller awaits it."""

    async def publish(*_: Any) -> None:  # the request goes away while the first step runs
        call.cancel()

    sweep = SimpleNamespace(revoke_all=Mock(side_effect=_Fatal))  # no step isolates a non-Exception
    w = _World(_Rel(sessions=(_S1,)), publish=publish, sessions=sweep)
    call = asyncio.create_task(w.disable())
    with capture_logs() as logs:
        with pytest.raises(asyncio.CancelledError):
            await call
        await w.svc.drain()
    lines = [(e["log_level"], e["error"]) for e in logs if e["event"].endswith("steps_failed")]
    assert lines == [("error", "_Fatal")]


def _steps(step: str, outcome: str) -> float:  # `cv_user_lifecycle_steps_total`, read as a delta
    return float(user_lifecycle_steps_total.labels(step=step, outcome=outcome)._value.get())


@pytest.mark.parametrize(
    ("ports", "failed"),
    [
        ({"publish": Mock(side_effect=LookupError)}, "socket_close"),
        ({"sessions": SimpleNamespace(revoke_all=Mock(side_effect=LookupError))}, "session_sweep"),
        ({"scope": SimpleNamespace(refresh=Mock(side_effect=LookupError))}, "scope_refresh"),
        ({"rules": SimpleNamespace(armed_rule_ids=Mock(side_effect=LookupError))}, "rule_disarm"),
        ({"sockets": Mock(side_effect=LookupError)}, "socket_close"),
    ],
    ids=["sink", "sweep", "scope", "rules", "user_sockets"],
)
async def test_port_that_raises_before_its_awaitable_fails_its_step_alone(
    ports: dict[str, Any], failed: str
) -> None:
    """R7: a port that raises before it returns an awaitable (a plain function) is a failed run
    of its own step, counted as failed (it was skipped, attempted 0); every other step still
    runs (an armed rule is disarmed after a failed scope refresh), and the committed disable
    still answers the caller."""
    w = _World(_Rel(status="invited", sessions=(_S1, _S2)), armed=("r1",), **ports)
    counted = _steps(failed, "failed")
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(True, (failed,))
    lines = [(e["step"], e["outcome"], e["error"]) for e in logs if "step" in e]
    assert lines == [
        (s, "failed", "LookupError") if s == failed else (s, "ok", None) for s in _STEPS
    ]
    assert _steps(failed, "failed") == counted + 1


async def test_sink_that_raises_is_tried_for_every_session() -> None:
    """R7: one session's sink raising does not stop the next session's socket close, nor the close
    of every socket of the user after them (S7): three runs of the step."""
    w = _World(_Rel(sessions=(_S1, _S2)), publish=Mock(side_effect=LookupError))
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(True, _STEPS[:1])
    (socket,) = [e for e in logs if e.get("step") == "socket_close"]
    assert (socket["attempted"], socket["outcome"]) == (3, "failed")
    assert w.socket_users == [_TARGET]


async def test_raise_outside_a_step_fails_the_rest_never_the_caller() -> None:
    """R7: an `Exception` that no step isolates (here a sweep that answers with something the B16
    loop cannot unpack) fails every step not yet logged; the committed disable still answers."""
    sweep = SimpleNamespace(revoke_all=AsyncMock(return_value=7))
    w = _World(_Rel(status="invited", sessions=(_S1,)), sessions=sweep)
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(True, _STEPS[2:])
    lines = [(e["step"], e["outcome"], e["error"]) for e in logs if "step" in e]
    assert lines == [(s, "ok", None) for s in _STEPS[:2]] + [
        (s, "failed", "TypeError") for s in _STEPS[2:]
    ]


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


@pytest.mark.parametrize(
    ("ports", "failed"),
    [
        ({"publish": _hang, "step_timeout_s": 0}, _STEPS[:1]),
        ({"sessions": SimpleNamespace(revoke_all=_hang), "step_timeout_s": 0}, _STEPS[1:2]),
        ({"chart": SimpleNamespace(revoke=_hang), "step_timeout_s": 0}, _STEPS[2:3]),
        ({"scope": SimpleNamespace(refresh=_hang), "step_timeout_s": 0}, _STEPS[3:4]),
        ({"rules": SimpleNamespace(armed_rule_ids=_hang), "step_timeout_s": 0}, _STEPS[4:5]),
        ({"invites": SimpleNamespace(revoke=_hang), "step_timeout_s": 0}, _STEPS[5:]),
        ({"publish": _hang, "deadline_s": 0}, _STEPS),
        ({"publish": _hang, "deadline_s": 0, "status": "active"}, _STEPS[:5]),
        ({"rows": SimpleNamespace(find_by_id=AsyncMock(return_value=None))}, _STEPS[2:3]),
        ({"sockets": _hang, "step_timeout_s": 0}, _STEPS[:1]),
    ],
    ids=[*_STEPS, "deadline", "deadline_active", "b16_row_missing", "user_sockets"],
)
async def test_hung_step_fails_never_raises(ports: dict[str, Any], failed: tuple[str, ...]) -> None:
    """R7: each await after the commit and all of them are bounded; hung, unreached or broken, a
    step fails alone (an `active` user has no invite step to fail)."""
    w = _World(_Rel(status=ports.get("status", "invited"), sessions=(_S1,)), **ports)
    assert await w.disable() == DisableResult(True, failed)


async def test_refused_rule_does_not_stop_loop() -> None:
    """R7, UL1-E3: a rule the chart refuses (B9 handles DISARM only in `armed`, `cooling_down`
    and `paused_degraded`) fails its own run: every other rule is still tried, in order, and the
    step is counted failed (two runs to list the rules, one per rule)."""
    refusal = RuleError(422, "illegal_transition", "A rule cannot change from armed to disabled.")
    w = _World(armed=("r1", "r2", "r3"), refuse={"r2": refusal})
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(True, ("rule_disarm",))
    assert [rule for rule, *_ in w.disarms] == ["r1", "r2", "r3"]
    (line,) = [e for e in logs if e.get("step") == "rule_disarm"]
    assert (line["attempted"], line["outcome"], line["error"]) == (5, "failed", "RuleError")
    assert line["log_level"] == "error" and line["target_user_id"] == str(_TARGET)


async def test_a_rule_armed_after_the_first_listing_is_disarmed_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S7 (the S5b review's Low 3), SR-029: the user's rules are listed again once after the
    disarms, so a rule whose arm landed after the first listing (its gate passed before the
    commit) is disarmed too. A rule already tried, refused or not, is not tried again, and there
    is no third listing."""
    refusal = RuleError(422, "illegal_transition", "A rule cannot change from armed to disabled.")
    w = _World(refuse={"r2": refusal})
    listings = iter([("r1", "r2"), ("r2", "r3")])  # r1 disarmed, r2 refused and armed, r3 late

    async def armed_rule_ids(user_id: uuid.UUID) -> tuple[str, ...]:
        w.mark("rules")
        return next(listings)

    monkeypatch.setattr(w, "armed_rule_ids", armed_rule_ids)
    assert await w.disable() == DisableResult(True, ("rule_disarm",))
    assert [rule for rule, *_ in w.disarms] == ["r1", "r2", "r3"]
    assert [e for e in w.post_commit() if e.startswith(("rules", "disarm"))] == [
        *("rules", "disarm:r1", "disarm:r2", "rules", "disarm:r3"),
    ]


async def test_disable_disarms_the_users_armed_rules_through_b9_and_closes_their_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1, SR-029, O5: over the real rule engine (manager, store, B9 charts built by the
    statechart factory) the cascade disarms every armed rule the user owns, audited with the
    acting Owner, and leaves nothing of the user in the scope snapshot; another user's rule is
    not touched. One rule is refused, as its chart does while it evaluates (the real refusal is
    in `test_user_cascade_wiring`): it fails its own run and the step, and the rest are disarmed."""
    engine, source = _Engine(), _Source()
    mine = [await engine.rule(_TARGET, "t-one"), await engine.rule(_TARGET, "t-two")]
    busy, theirs = await engine.rule(_TARGET, "t-busy"), await engine.rule(uuid.uuid4(), "other")
    real = engine.manager.set_mode

    async def refuse_busy(rule_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if rule_id == busy:
            raise RuleError(422, "illegal_transition", "A rule cannot change from armed.")
        return await real(rule_id, *args, **kwargs)

    monkeypatch.setattr(engine.manager, "set_mode", refuse_busy)
    state = SnapshotScopeState(source, "demo")
    await state.refresh(_TARGET)
    assert state.can_arm_live(_TARGET)
    source.disabled = True  # what the store answers once the disable has committed
    w = _World(rules=engine.adapter, scope=ScopeRefreshAdapter(lambda: state))
    assert await w.disable() == DisableResult(True, ("rule_disarm",))
    for rid in mine:
        assert await engine.mode(rid) == ("disabled", "disarmed")
        assert engine.manager.lifecycle.leaf(rid) == "disarmed"
    assert [await engine.mode(rid) for rid in (busy, theirs)] == [("armed", None)] * 2
    assert engine.disarmed() == sorted((rid, str(_OWNER.user_id), "DISARM") for rid in mine)
    assert state.granted_accounts(_TARGET) == frozenset() and not state.can_arm_live(_TARGET)


async def test_overlapping_repeats_disarm_a_rule_once_and_park_nothing() -> None:
    """AC5, SR-029: a repeat of the DELETE can start while the first cascade still runs (a double
    submit, a client retry), and both list the rule while it is armed. Over the real rule engine
    the adapter runs one rule's disarms one at a time, so the second finds the rule disarmed and
    writes nothing: one `rule.disarmed` record, no failed step, no DISARM parked on the chart, and
    the rule arms again the first time. Unserialised, both sent DISARM: two records, one parked,
    and the next arm refused with 422 `illegal_transition`."""
    engine = _Engine()
    rid = await engine.rule(_TARGET, "t-one")
    w = _World(_Rel(status="disabled"), rules=engine.adapter)
    first, second = await asyncio.gather(w.disable(), w.disable())
    assert first == second == DisableResult(changed=False)
    assert engine.disarmed() == [(rid, str(_OWNER.user_id), "DISARM")]
    assert engine.manager.lifecycle._charts[rid].deferred_count == 0
    await engine.manager.set_mode(rid, "armed", _actor(_TARGET), "arm-again")
    assert await engine.mode(rid) == ("armed", None)


# --- #965 Observability (R7): what each call and each step counts and logs --------------------


def _calls(result: str) -> float:  # `cv_user_lifecycle_total`, read as a delta
    return float(user_lifecycle_total.labels(action="disable", result=result)._value.get())


def _store_self_target() -> _World:  # the store's own SR-055 refusal
    return _World(store=SimpleNamespace(disable=AsyncMock(side_effect=UserSelfTargetError("me"))))


def _audit_down() -> _World:  # a fresh list each call: `emit` pops the failures it raises
    return _World(fail={"users.disable": [AuditUnavailable("wal")]})


def _store_error() -> _World:  # the store raises at its deferred check: no refusal
    return _World(_Rel(raise_at=CONSTRAINTS_NOW, sqlstate="40001"))


#: (result, world, actor, error): one call per result of the closed set, in its order.
_RESULTS: list[tuple[str, Callable[[], _World], PrincipalSnapshot, Any]] = [
    ("disabled", _World, _OWNER, None),
    ("noop", lambda: _World(_Rel(status="disabled"), positions=None), _OWNER, None),
    ("forbidden", _World, _MANAGER, errors.LifecycleForbiddenError),
    ("self_target", _store_self_target, _OWNER, errors.LifecycleForbiddenError),
    ("not_found", lambda: _World(_Rel(status=None)), _OWNER, errors.UserNotFoundError),
    ("positions_unknown", lambda: _World(positions=None), _OWNER, errors.PositionsUnknownError),
    ("last_owner", lambda: _World(_Rel(roles=("owner",), owners=1)), _OWNER, errors.LastOwnerError),
    ("audit_unavailable", _audit_down, _OWNER, _AUDIT_DOWN),
    ("error", _store_error, _OWNER, IntegrityError),
]


def test_the_counted_results_are_the_closed_set() -> None:
    assert [result for result, *_ in _RESULTS] == list(ACTION_RESULTS["disable"])


@pytest.mark.parametrize(
    ("result", "world", "actor", "error"), _RESULTS, ids=[r[0] for r in _RESULTS]
)
async def test_each_call_is_counted_once_under_its_result(
    result: str, world: Callable[[], _World], actor: PrincipalSnapshot, error: Any
) -> None:
    """#965: one count per call, under its result only; a refusal is never an `error` (the
    store's own self-target is the audited 403, SR-055)."""
    w, before = world(), {r: _calls(r) for r in ACTION_RESULTS["disable"]}
    with pytest.raises(error) if error else contextlib.nullcontext():
        await w.svc.disable(_TARGET, actor=actor)
    moved = {r: _calls(r) - n for r, n in before.items() if _calls(r) != n}
    assert moved == {result: 1}


async def test_log_and_metrics_per_step() -> None:
    """#965: one line and one count per step, correlated by `request_id`, and the call counted
    (served with `env`: `test_user_lifecycle_series_are_bound_at_import_and_served_with_env`)."""
    ok, disabled = {s: _steps(s, "ok") for s in _STEPS}, _calls("disabled")
    with bind_context(request_id=str(_RID)), capture_logs() as logs:
        assert await _World(_Rel(status="invited")).disable() == DisableResult(changed=True)
    lines = [(e["step"], e["outcome"], e["request_id"]) for e in logs if "step" in e]
    assert lines == [(s, "ok", str(_RID)) for s in _STEPS]
    assert [_steps(s, "ok") - ok[s] for s in _STEPS] == [1] * len(_STEPS)
    assert _calls("disabled") == disabled + 1


async def test_post_commit_failure_alerts() -> None:
    """R7: every step fails, each alone (the scope refresh by outliving its bound). Each is
    counted `failed` once and logged at error with its error class (the `UserLifecycleStepFailed`
    signal); the commit stands and every other run still goes: the other session's socket and
    B16 record, the other rule's disarm."""
    refusal = RuleError(422, "illegal_transition", "A rule cannot change from armed.")
    failed = {s: _steps(s, "failed") for s in _STEPS}
    w = _World(
        _Rel(status="invited"),
        armed=("r1", "r2"),
        refuse={"r1": refusal},
        invite=OSError("invites down"),
        publish=AsyncMock(side_effect=[OSError("socket gone"), None]),
        sessions=SimpleNamespace(revoke_all=AsyncMock(side_effect=OSError("sweep down"))),
        chart=SimpleNamespace(revoke=AsyncMock(side_effect=[SessionChartError("refused"), None])),
        scope=SimpleNamespace(refresh=_hang),
        step_timeout_s=0,  # only the hung refresh suspends, so only it outlives the bound
    )
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True, failed_steps=_STEPS)
    assert w.rel.committed and [rule for rule, *_ in w.disarms] == ["r1", "r2"]
    assert [_steps(s, "failed") - failed[s] for s in _STEPS] == [1] * len(_STEPS)
    lines = [(e["step"], e["error"], e["log_level"]) for e in logs if "step" in e]
    kinds = ("OSError", "OSError", "SessionChartError", "TimeoutError", "RuleError", "OSError")
    assert lines == list(zip(_STEPS, kinds, ["error"] * len(_STEPS), strict=True))


async def test_cancelled_steps_are_counted_failed() -> None:
    """R7: steps that a cancellation of their task (shutdown) cuts off are counted failed first."""
    before = {s: _steps(s, "failed") for s in _STEPS}
    w = _World(_Rel(status="invited"), publish=AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await w.disable()
    assert [_steps(s, "failed") - before[s] for s in _STEPS] == [1] * len(_STEPS)


#: (the `users.disable` emits that fail, in order; the closing record's outcome): the write-ahead
#: record times out, so nothing commits, then the record that closes it is written or refused.
_CLOSINGS = [([TimeoutError()], "ok"), ([TimeoutError(), AuditUnavailable("down")], "failed")]


async def test_every_declared_step_outcome_is_reachable() -> None:
    """#965 R7: some call counts each outcome declared for a cascade step, so none is a series at
    0 for good (a step cut off is failed; only B16 and the invite revoke can have nothing to do).
    `_CLOSINGS` reach the closing record's two; `test_account_access_service` the push's three."""
    pairs = {(step, o) for step in _STEPS for o in STEP_OUTCOMES[step]}
    before = {pair: _steps(*pair) for pair in pairs}
    await _World(_Rel(status="invited")).disable()  # every step ok
    await _World(_Rel(status="invited"), publish=_hang, deadline_s=0).disable()  # all cut off
    await _World(_Rel(sessions=())).disable()  # no session to record, no invite to revoke
    assert {pair for pair in pairs if _steps(*pair) > before[pair]} == pairs
    assert [outcome for _, outcome in _CLOSINGS] == list(STEP_OUTCOMES["closing_record"])


@pytest.mark.parametrize(("fail", "outcome"), _CLOSINGS, ids=["closed", "closing_failed"])
async def test_closing_record_is_counted_and_a_failed_one_alerts(
    fail: list[BaseException], outcome: str
) -> None:
    """C-2.9, R7: the record closing a `users.disable` whose change never committed counts as
    the step `closing_record`; one that could not be written is `failed` and logged at error."""
    before = {o: _steps("closing_record", o) for o in STEP_OUTCOMES["closing_record"]}
    with capture_logs() as logs, pytest.raises(_AUDIT_DOWN):
        await _World(fail={"users.disable": list(fail)}).disable()
    moved = {o: _steps("closing_record", o) - n for o, n in before.items()}
    assert moved == {o: float(o == outcome) for o in before}
    (line,) = [e for e in logs if e.get("step") == "closing_record"]
    assert (line["outcome"], line["log_level"]) == (outcome, "info" if outcome == "ok" else "error")
