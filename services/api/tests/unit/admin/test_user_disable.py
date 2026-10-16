"""E42-T04 S4 (#965): `UserDisableService` over the S3 store's fake unit of work (Postgres: S3's
integration tests). One log orders every port call; `!open` marks a call before the commit."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from prometheus_client import REGISTRY, generate_latest
from sqlalchemy.exc import IntegrityError
from structlog.testing import capture_logs

from candleviewer.admin import errors
from candleviewer.admin.lifecycle_metrics import export_user_lifecycle_metrics
from candleviewer.admin.user_disable import DisableResult, UserDisableService
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import InviteNotFound
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_chart import SessionChart, SessionChartError
from candleviewer.auth.session_service import SessionService
from candleviewer.observability.context import bind_context
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.storage.repositories.owner_floor_sqlalchemy import CONSTRAINTS_NOW
from candleviewer.storage.repositories.user_lifecycle import UserSelfTargetError, UserStatusChange
from candleviewer.ws.revocation import CLOSE_USER_DISABLED, RevocationHub
from tests.conftest import RecordingAuditSink
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_step_up import _T0 as _NOW
from tests.unit.auth.test_step_up import _session
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _A, _B, _S1, _S2, _Rel, _store

_OWNER = PrincipalSnapshot(uuid.uuid4(), frozenset({"owner"}), frozenset(Permission))
_MANAGER = PrincipalSnapshot(uuid.uuid4(), frozenset({"manager"}), frozenset())
_TARGET, _RID = uuid.uuid4(), uuid.uuid4()
_POST_COMMIT = ("socket", "sweep", "b16", "invite")
_STEPS = ("socket_close", "session_sweep", "b16_revoke", "invite_revoke")
_AUDIT_DOWN, _INVITE = errors.LifecycleAuditUnavailableError, ("invite_revoke",)
_OPEN, _CLOSE = ("success", None, "disabled"), ("failure", "not_applied", "active")
_TOTAL, _STEP = "cv_user_lifecycle_total", "cv_user_lifecycle_steps_total"


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _revoked(record: SessionRecord) -> SessionRecord:
    return record.model_copy(update={"revoked_at": _NOW, "revoked_reason": "user_disabled"})


class _World:
    """Every port but the S3 store (exposure: reads only, O2); `fail[action]` audit errors,
    `fails` keys and `invite` raise."""

    source = "not_deployed"  # the position provider's

    def __init__(
        self,
        rel: _Rel | None = None,
        *,
        fail: dict[str, list[BaseException]] | None = None,
        positions: int | Exception | None = 0,
        orders: int | None = 0,
        fails: frozenset[object] = frozenset(),
        invite: Exception | None = None,
        store: Any = None,
        **ports: Any,
    ) -> None:
        self.log, self.calls = list[str](), list[dict[str, Any]]()
        self.rel, self.fail, self.fails, self.invite = rel or _Rel(), fail or {}, fails, invite
        self.positions, self.orders = positions, orders
        self.svc = UserDisableService(
            store or _store(self.rel),
            self,
            positions=self,
            orders=self,
            sessions=ports.get("sessions", self),
            session_rows=ports.get("rows", self),
            chart=ports.get("chart", SimpleNamespace(revoke=self.record)),
            publish_revocation=ports.get("publish", self.publish),
            invites=ports.get("invites", SimpleNamespace(revoke=self.revoke_invite)),
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

    def mark(self, entry: str, key: object) -> None:
        self.log.append(entry if self.rel.committed else f"{entry}!open")
        if key in self.fails:
            raise (SessionChartError if entry.startswith("b16") else OSError)(entry)

    async def publish(self, session_id: str, reason: str) -> None:
        self.mark(f"socket:{reason}", uuid.UUID(session_id))

    async def revoke_all(self, user_id: str, *, reason: str) -> tuple[SessionRecord, ...]:
        self.mark(f"sweep:{reason}", "sweep")
        return ()

    async def find_by_id(self, session_id: str) -> SessionRecord | None:
        return _revoked(_session(_TARGET)).model_copy(update={"id": uuid.UUID(session_id)})

    async def record(self, record: SessionRecord, now: object, reason: str) -> None:
        self.mark(f"b16:{reason}", record.id)

    async def revoke_invite(self, user_id: uuid.UUID) -> None:
        self.mark("invite", None)
        if self.invite is not None:
            raise self.invite

    async def disable(self, actor: PrincipalSnapshot = _OWNER, **kw: Any) -> DisableResult:
        return await self.svc.disable(_TARGET, actor=actor, **kw)

    def post_commit(self) -> list[str]:
        return [entry for entry in self.log if entry.startswith(_POST_COMMIT)]


async def test_step_order() -> None:
    """R7: exposure, `users.disable` before the commit, then sockets, sweep, B16 and invite."""
    w = _World(_Rel(status="invited", sessions=(_S1, _S2)))
    assert await w.disable() == DisableResult(changed=True)
    assert w.log == [
        *("positions", "orders", "users.disable", "socket:user_disabled", "socket:user_disabled"),
        *("sweep:user_disabled", "b16:user_disabled", "b16:user_disabled", "users.invite_revoked"),
        "invite",
    ]
    (invite,) = w.of("users.invite_revoked")
    assert (invite["actor_user_id"], invite["object_id"]) == (_OWNER.user_id, str(_TARGET))


async def test_b16_revoke_per_session(b16_audit: RecordingAuditSink) -> None:
    """R5 on the real B16 chart and hub: one `auth.session_revoked` and one 4403 per session."""
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
    assert await w.disable() == DisableResult(changed=True)
    assert sorted((c["action"], c["session_id"], c["reason"]) for c in b16_audit.calls) == sorted(
        ("auth.session_revoked", str(r.id), "user_disabled") for r in rows
    )
    assert closed == {str(r.id): ("user_disabled", CLOSE_USER_DISABLED) for r in rows}


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


async def _commit_fails(*_: Any, audit: Any, **__: Any) -> UserStatusChange:
    await audit(UserStatusChange(_TARGET, "active", "disabled", frozenset({"manager"}), (_S1,)))
    raise ConnectionError("commit lost")


@pytest.mark.parametrize(
    ("fail", "store", "error", "records", "failed"),
    [
        ([TimeoutError()], None, _AUDIT_DOWN, [_CLOSE], 0),
        ([TimeoutError(), AuditUnavailable("down")], None, _AUDIT_DOWN, [], 1),
        ([], SimpleNamespace(disable=_commit_fails), ConnectionError, [_OPEN, _CLOSE], 0),
    ],
    ids=["hook_timeout", "closing_failed", "commit_failed"],
)
async def test_unapplied_record_is_closed(
    fail: list[BaseException], store: Any, error: type[Exception], records: list[Any], failed: int
) -> None:
    """AC8, S3: a timed-out hook (503) or failed commit is closed by a `not_applied` record."""
    before = _sample(_STEP, step="closing_record", outcome="failed")
    w = _World(fail={"users.disable": list(fail)}, store=store)
    with pytest.raises(error):
        await w.disable()
    assert [(c["outcome"], c.get("reason"), c["after_state"]["status"]) for c in w.calls] == records
    assert _sample(_STEP, step="closing_record", outcome="failed") == before + failed
    assert w.post_commit() == [] and not w.rel.committed


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
    counted = [_sample(_TOTAL, action="disable", result=r) for r in ("self_target", "error")]
    w = _World(store=SimpleNamespace(disable=AsyncMock(side_effect=UserSelfTargetError("self"))))
    with pytest.raises(errors.LifecycleForbiddenError, match="self_target"):
        await w.disable()
    assert [(c["action"], c["reason"]) for c in w.calls] == [("rbac.denied", "self_target")]
    after = [_sample(_TOTAL, action="disable", result=r) for r in ("self_target", "error")]
    assert after == [counted[0] + 1, counted[1]]


async def test_refusal_with_audit_down_is_503() -> None:
    w = _World(fail={"rbac.denied": [AuditUnavailable("down")]})
    with pytest.raises(errors.LifecycleAuditUnavailableError):
        await w.svc.disable(_OWNER.user_id, actor=_OWNER)
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


@pytest.mark.parametrize(
    ("status", "kw", "records", "failed"),
    [
        ("invited", {}, ["success"], ()),
        ("invited", {"invite": InviteNotFound("none open")}, ["success", "failure"], ()),
        ("invited", {"invite": OSError("invites down")}, ["success", "failure"], _INVITE),
        ("invited", {"fail": {"users.invite_revoked": [AuditUnavailable("down")]}}, [], _INVITE),
        ("active", {}, [], ()),
    ],
    ids=["invited", "invite_already_gone", "revoke_failed", "record_refused", "active"],
)
async def test_invited_revokes_invite(
    status: str, kw: dict[str, Any], records: list[str], failed: tuple[str, ...]
) -> None:
    """R6, UL1-E4, C-2.9: the invite is revoked after its record and closed if not applied."""
    w = _World(_Rel(status=status), **kw)
    assert await w.disable() == DisableResult(True, failed)
    assert [c.get("outcome", "success") for c in w.of("users.invite_revoked")] == records
    assert ("invite" in w.log) == bool(records)  # the revoke runs once its record is written


async def test_already_disabled_is_a_noop_that_sweeps_again() -> None:
    """AC5: a repeat needs no acknowledgement, commits nothing (`!open`), sweeps again (SR-029)."""
    noops = _sample(_TOTAL, action="disable", result="noop")
    w = _World(_Rel(status="disabled"), positions=None)
    assert await w.disable() == DisableResult(changed=False)
    assert w.calls == [] and w.log == ["positions", "orders", "sweep:user_disabled!open"]
    assert _sample(_TOTAL, action="disable", result="noop") == noops + 1


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
    assert w.post_commit() == ["sweep:user_disabled", "b16:user_disabled", "invite"]


async def _hang(*_: Any, **__: Any) -> Any:
    await asyncio.Event().wait()


@pytest.mark.parametrize(
    ("ports", "failed"),
    [
        ({"publish": _hang, "step_timeout_s": 0}, _STEPS[:1]),
        ({"sessions": SimpleNamespace(revoke_all=_hang), "step_timeout_s": 0}, _STEPS[1:2]),
        ({"chart": SimpleNamespace(revoke=_hang), "step_timeout_s": 0}, _STEPS[2:3]),
        ({"invites": SimpleNamespace(revoke=_hang), "step_timeout_s": 0}, _STEPS[3:]),
        ({"publish": _hang, "deadline_s": 0}, _STEPS),
    ],
    ids=[*_STEPS, "deadline"],
)
async def test_hung_step_fails_never_raises(ports: dict[str, Any], failed: tuple[str, ...]) -> None:
    """R7: each await after the commit and all of them are bounded; hung or unreached, it fails,
    and is counted and logged as failed."""
    before = [_sample(_STEP, step=s, outcome="failed") for s in _STEPS]
    w = _World(_Rel(status="invited", sessions=(_S1,)), **ports)
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(True, failed)
    after = [_sample(_STEP, step=s, outcome="failed") for s in _STEPS]
    assert tuple(s for s, b, a in zip(_STEPS, before, after, strict=True) if a == b + 1) == failed
    assert {e["error"] for e in logs if e.get("outcome") == "failed"} == {"TimeoutError"}


async def test_cancelled_steps_are_counted_failed() -> None:
    """R7: steps a cancellation of their task cuts off (shutdown) are counted failed first."""
    before = [_sample(_STEP, step=s, outcome="failed") for s in _STEPS]
    w = _World(_Rel(status="invited"), publish=AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await w.disable()
    assert [_sample(_STEP, step=s, outcome="failed") for s in _STEPS] == [n + 1 for n in before]


async def test_post_commit_failure_alerts() -> None:
    """R7: each failed step is counted and logged at error; nothing else stops or rolls back."""
    failed = [_sample(_STEP, step=s, outcome="failed") for s in _STEPS]
    rel = _Rel(status="invited", sessions=(_S1, _S2))
    w = _World(rel, fails=frozenset({_S1, "sweep"}), invite=OSError("invites down"))
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True, failed_steps=_STEPS)
    assert rel.committed and w.log.count("b16:user_disabled") == 2
    assert w.log.count("socket:user_disabled") == 2
    assert [_sample(_STEP, step=s, outcome="failed") for s in _STEPS] == [n + 1 for n in failed]
    lines = [(e["step"], e["error"], e["log_level"]) for e in logs if e.get("step") in _STEPS]
    kinds = ("OSError", "OSError", "SessionChartError", "OSError")
    assert lines == list(zip(_STEPS, kinds, ["error"] * 4, strict=True))


async def test_log_and_metrics_per_step() -> None:
    """One line and one count per step, the call counted, and the series served with `env`."""
    ok = [_sample(_STEP, step=s, outcome="ok") for s in _STEPS]
    disabled = _sample(_TOTAL, action="disable", result="disabled")
    with bind_context(request_id=str(_RID)), capture_logs() as logs:
        await _World(_Rel(status="invited")).disable()
    lines = [(e["step"], e["outcome"], e["request_id"]) for e in logs if "step" in e]
    assert lines == [(s, "ok", str(_RID)) for s in _STEPS]
    assert [_sample(_STEP, step=s, outcome="ok") for s in _STEPS] == [n + 1 for n in ok]
    assert _sample(_TOTAL, action="disable", result="disabled") == disabled + 1
    registry = CollectorRegistry()
    collector = export_user_lifecycle_metrics(registry, env="demo")
    text = generate_latest(registry).decode()
    collector.close()
    assert 'cv_user_lifecycle_total{action="disable",env="demo",result="disabled"}' in text
