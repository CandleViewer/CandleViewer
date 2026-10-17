"""The feature-flag composition (E42-T03): which store each backend gets, the read budget from its
system setting, the runtime's start and stop, the composed order-entry gate, and the user, session
and step-up adapters given to the writer and the push."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, get_args
from unittest.mock import AsyncMock, call

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

import candleviewer.flags_wiring as wiring
from candleviewer.admin.flags import (
    MAINTENANCE_MODE,
    Category,
    FlagKind,
    FlagRegistry,
    FlagService,
    FlagSpec,
    Visibility,
)
from candleviewer.admin.flags.maintenance import MaintenanceController
from candleviewer.admin.flags.policy import StepUpClass
from candleviewer.admin.flags.store import FlagWrite
from candleviewer.api.step_up import StepUpRefused, step_up_port
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import StepUpMismatch, StepUpRequired
from candleviewer.auth.step_up import ACTION_CLASSES, NO_GRACE_ACTION_CLASSES, StepUpChallenge
from candleviewer.settings import Environment, Settings
from candleviewer.statechart.bindings import b16_session
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.flags_sqlalchemy import FlagSeed, SqlAlchemyFlagRepository
from candleviewer.storage.repositories.system_settings import StoredSetting
from candleviewer.storage.testing.flags import InMemoryFlagRepository
from candleviewer.ws.gateway import GatewayHub
from tests.unit.admin.flag_fakes import FakeAudit, FakeStepUp, FakeUsers

_FLAGS = frozenset({"flags:read", "flags:write"})
_OWNER = AuditPrincipal(uuid.UUID(int=1), "owner", _FLAGS, uuid.UUID(int=2), is_owner=True)
_ALL, _ROLES = Visibility.ALL_ROLES, frozenset({"owner"})
_T0 = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)


class _Settings:
    """The system settings store: `value` is the stored text, `error` what a read raises."""

    def __init__(self, value: str | None = None, error: BaseException | None = None) -> None:
        self.value, self.error = value, error

    async def get_string(self, key: str) -> StoredSetting | None:
        assert key == "flags.read_budget_ms"
        if self.error is not None:
            raise self.error
        return None if self.value is None else StoredSetting(self.value, _T0)


class _Sessions:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def authenticated(self) -> list[Any]:
        return [
            SimpleNamespace(user_id=_OWNER.user_id, roles=_ROLES, push_system=self.frames.append)
        ]


def _runtime(settings: _Settings | None = None) -> wiring.FeatureFlagsRuntime:
    return wiring.FeatureFlagsRuntime(
        None,
        settings=settings,
        audit=FakeAudit(),
        step_up=FakeStepUp(),
        users=FakeUsers(),
        sessions=_Sessions(),
    )


def test_every_step_up_class_a_flag_write_demands_is_registered() -> None:
    assert set(get_args(StepUpClass)) <= ACTION_CLASSES
    assert set(get_args(StepUpClass)) <= b16_session.ACTION_CLASSES  # the B16 mirror


async def test_the_fake_backend_reads_every_flag_at_its_default_from_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "SqlAlchemyFlagRepository", None)  # never Postgres here
    runtime = wiring.build_feature_flags(
        Settings(storage_backend="fake"), audit=FakeAudit(), step_up=FakeStepUp(),
        hub=GatewayHub(), users=None,
    )  # fmt: skip
    listed = await runtime.service.visible(_OWNER.user_id, _ROLES)
    assert listed.resolution.value == "stored"
    assert {f.spec.key: f.value for f in listed.items} == {
        k: s.default for k, s in runtime.registry.items()
    }
    assert all(f.stored is not None and f.stored.updated_at for f in listed.items)


@pytest.mark.parametrize("env", list(Environment))
async def test_the_real_backend_never_gets_the_in_memory_store(
    monkeypatch: pytest.MonkeyPatch, env: Environment
) -> None:
    monkeypatch.setattr(wiring, "InMemoryFlagRepository", None)  # constructing it would fail
    live_ok = SecretStr("not-the-dev-default")  # live and real refuse the dev default
    settings = Settings(storage_backend="real", environment=env, questdb_pg_password=live_ok)
    runtime = wiring.build_feature_flags(
        settings, audit=FakeAudit(), step_up=FakeStepUp(), hub=GatewayHub(), users=None
    )
    disposed = AsyncMock()
    monkeypatch.setattr(type(runtime._relational), "dispose", disposed)
    try:
        assert isinstance(runtime._repository(500), SqlAlchemyFlagRepository)
    finally:
        await runtime.stop()
    disposed.assert_awaited_once()  # the never-connected engine goes with the runtime


@pytest.mark.parametrize(
    ("stored", "budget"),
    [(None, 500), ("750", 750), ("50", 50), ("2000", 2000), ("49", None), ("2001", None)]
    + [(bad, None) for bad in ("7.5", "1e3", "-1", "", " 500")],
)
async def test_the_read_budget_is_its_system_setting_or_boot_is_refused(
    stored: str | None, budget: int | None
) -> None:
    runtime = _runtime(_Settings(stored))
    if budget is None:
        with pytest.raises(ValueError, match=r"flags\.read_budget_ms"):
            await runtime.start()
        return
    await runtime.start()
    try:
        assert runtime.budget_ms == budget
        assert runtime.service is runtime.writer._service  # the writer reads the rebuilt service
        assert isinstance(store := runtime.service.store, wiring.StorageFlagStore)
        assert store._bound_s == wiring.write_bound_s(budget)
    finally:
        await runtime.stop()


@pytest.mark.parametrize("error", [StorageTierUnavailable("down"), TimeoutError()])
async def test_an_unreadable_setting_at_boot_falls_back_to_the_default(error: Exception) -> None:
    with capture_logs() as logs:
        assert await wiring.read_budget_ms(_Settings(error=error)) == 500
    assert logs[-1]["event"] == "feature_flag_read_budget_unread"
    assert await wiring.read_budget_ms(None) == 500


async def test_start_ensures_the_rows_and_the_poll_opens_the_order_gate() -> None:
    runtime, account = _runtime(), uuid.uuid4()
    refusal = runtime.order_entry_gate.refusal(account)
    assert refusal is not None and refusal.reason == "maintenance"  # unknown: engaged
    await runtime.start()
    poll = runtime._poll
    try:
        for _ in range(100):  # bounded: the poll's first read sees both gate flags off
            if not runtime.gate.engaged:
                break
            await asyncio.sleep(0)
        assert runtime.order_entry_gate.refusal(account) is None
    finally:
        await runtime.stop()
    assert runtime._poll is None and poll is not None and poll.done()  # cancelled, awaited


async def test_a_write_runs_the_gate_then_the_push_then_the_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, effects = _Sessions(), list[tuple[bool, int]]()

    async def effects_hook(self: MaintenanceController, *_: object) -> None:
        effects.append((runtime.gate.engaged, len(sessions.frames)))

    monkeypatch.setattr(MaintenanceController, "effects_hook", effects_hook)
    runtime = wiring.FeatureFlagsRuntime(
        None, audit=FakeAudit(), step_up=FakeStepUp(), users=FakeUsers(), sessions=sessions
    )
    runtime.gate.set(False)
    row = await runtime.service.stored(runtime.registry[MAINTENANCE_MODE])
    assert row is not None and row.updated_at is not None
    await runtime.writer.set(
        MAINTENANCE_MODE, _OWNER, value=True, reason="drill", expected_updated_at=row.updated_at
    )
    assert runtime.gate.engaged  # the gate hook ran first, on the committed row
    assert {"kind": "feature_flags", "feature_flags": {MAINTENANCE_MODE: True}} in sessions.frames
    assert effects == [(True, len(sessions.frames))]  # the effects last


async def test_a_flag_whose_kind_changed_reads_unreadable_alone() -> None:
    pct = FlagSpec("algo.pct", FlagKind.PERCENTAGE, "P", Category.FEATURE_ROLLOUT, 25, _ALL)
    form = FlagSpec("rules.form_editor", FlagKind.BOOLEAN, "F", Category.UI_SURFACE, True, _ALL)
    old = [
        FlagSeed(pct.key, "boolean", "P", False, False),
        FlagSeed(form.key, "boolean", "", True, False),
    ]
    store = wiring.StorageFlagStore(InMemoryFlagRepository(old), bound_s=1.0)  # old code's rows
    listed = await FlagService(FlagRegistry([pct, form]), store).visible(
        _OWNER.user_id, frozenset()
    )
    assert listed.resolution.value == "stored"
    assert {f.spec.key: f.unreadable for f in listed.items} == {"algo.pct": True, form.key: False}


async def test_the_user_directory_asks_the_role_store_and_knows_no_one_without_it() -> None:
    known = uuid.uuid4()
    roles = SimpleNamespace(
        get_roles=AsyncMock(side_effect=lambda u: _ROLES if u == known else None)
    )
    ids = frozenset({known, uuid.uuid4()})
    assert await wiring.RoleStoreUsers(roles).unknown(ids) == ids - {known}
    assert await wiring.RoleStoreUsers(None).unknown(ids) == ids


class _Sock:
    def __init__(self, signed_in: bool, pushed: list[dict[str, Any]]) -> None:
        self.user_id, self.push_system = _OWNER.user_id, pushed.append
        self.authz = SimpleNamespace(principal=SimpleNamespace(roles=_ROLES))
        self.lifecycle = SimpleNamespace(authenticated=signed_in)


def test_the_sessions_are_the_hubs_authenticated_sockets() -> None:
    hub, pushed = GatewayHub(), list[dict[str, Any]]()
    live: set[Any] = hub._live
    live.update({_Sock(True, pushed), _Sock(False, pushed)})
    [session] = wiring.HubSessions(hub).authenticated()
    session.push_system({"kind": "notice"})
    assert (session.user_id, session.roles, pushed) == (
        _OWNER.user_id,
        _ROLES,
        [{"kind": "notice"}],
    )


_CHANGE = FlagWrite("a.b", False, {}, _T0, _OWNER.user_id)
_FP = "f" * 64  # the route's fingerprint of its request


@pytest.mark.parametrize("action_class", ["flags", "killswitch", "live_enablement"])
@pytest.mark.parametrize(
    ("elevated", "session", "status"),
    [(True, _OWNER.session_id, None), (False, _OWNER.session_id, 403), (True, None, 401)],
)
async def test_the_step_up_port_demands_the_writers_class_and_raises_what_a_refusal_answers(
    action_class: str, elevated: bool, session: uuid.UUID | None, status: int | None
) -> None:
    challenge = StepUpChallenge(uuid.uuid4(), action_class, _T0 + timedelta(minutes=5))
    gate = AsyncMock(side_effect=None if elevated else StepUpRequired(action_class))
    single = action_class in NO_GRACE_ACTION_CLASSES  # spends a single-use grant: no grace
    step_up = SimpleNamespace(**{"consume_single_use" if single else "require_elevation": gate})
    step_up.record_pending = AsyncMock(return_value=challenge)
    auth = SimpleNamespace(step_up_is_active=True, step_up=step_up)
    who = AuditPrincipal(_OWNER.user_id, "owner", _FLAGS, session)
    demand = step_up_port(auth, wiring.restate_flag_write, None)(who, action_class, _CHANGE, _FP)
    if status is None:  # elevated: let through
        await demand
    else:
        with pytest.raises(StepUpRefused) as refused:
            await demand
        assert refused.value.response.status_code == status
    bound = {"fingerprint": _FP} if single else {}  # a no-grace grant is bound to the request
    assert gate.await_args_list == (
        [] if session is None else [call(str(session), action_class, **bound)]
    )
    if status == 403:
        assert step_up.record_pending.await_args_list == [call(str(session), action_class, **bound)]
    if status == 403:  # the challenge restates the change (#2304)
        body = json.loads(bytes(refused.value.response.body))
        assert (body["action_class"], body["target"]) == (action_class, None)
        assert body["action_summary"] == "Set feature flag 'a.b' to false, user overrides 0"


@pytest.mark.parametrize(
    "action_class", sorted(NO_GRACE_ACTION_CLASSES & {"killswitch", "live_enablement"})
)
async def test_a_grant_bound_to_another_request_is_audited_through_the_ports_emitter(
    action_class: str,
) -> None:
    other = StepUpMismatch(action_class, user_id="u", challenge_id="c", bound="a" * 64, refused=_FP)
    step_up = SimpleNamespace(consume_single_use=AsyncMock(side_effect=other))
    step_up.record_pending = AsyncMock(
        return_value=StepUpChallenge(uuid.uuid4(), action_class, _T0)
    )
    auth, emitter = SimpleNamespace(step_up_is_active=True, step_up=step_up), AsyncMock()
    demand = step_up_port(auth, wiring.restate_flag_write, emitter)(
        _OWNER, action_class, _CHANGE, _FP
    )
    with pytest.raises(StepUpRefused):
        await demand
    [mismatch] = emitter.emit.await_args_list
    assert mismatch.args == ("auth.step_up_mismatch",)
    assert mismatch.kwargs["after_state"] == {
        "bound_request_sha256": "a" * 64,
        "refused_request_sha256": _FP,
    }


def test_a_write_is_restated_from_its_validated_change_alone() -> None:
    change = FlagWrite("a.b", "v2", {_OWNER.user_id: "v1"}, _T0, _OWNER.user_id)
    assert wiring.restate_flag_write(change).action_summary.endswith("to v2, user overrides 1")
