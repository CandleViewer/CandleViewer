"""The feature-flag composition (E42-T03): which store each backend gets, the read budget from its
system setting, the runtime's start and stop, the composed order-entry gate, and the user, session
and step-up adapters given to the writer and the push."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast, get_args
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
    StoredFlag,
    Visibility,
    default_registry,
)
from candleviewer.admin.flags.maintenance import MaintenanceController
from candleviewer.admin.flags.policy import StepUpClass
from candleviewer.admin.flags.store import FlagWrite, StoreUnavailableError
from candleviewer.api.step_up import StepUpRefused, step_up_port
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import StepUpMismatch, StepUpRequired
from candleviewer.auth.step_up import ACTION_CLASSES, NO_GRACE_ACTION_CLASSES, StepUpChallenge
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.settings import Environment, Settings
from candleviewer.statechart.bindings import b16_session
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.flags_sqlalchemy import FlagSeed, SqlAlchemyFlagRepository
from candleviewer.storage.repositories.system_settings import StoredSetting
from candleviewer.storage.testing.flags import InMemoryFlagRepository
from candleviewer.ws.gateway import GatewayHub
from tests.unit.admin.flag_fakes import Clock, FakeAudit, FakeFlagStore, FakeStepUp, FakeUsers

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


async def _settled(flag: wiring.BackendConnectionFlag) -> None:
    assert flag._task is not None
    await asyncio.wait_for(flag._task, 5)


_CONN = "desktop.backend_connection"


def _connection_flag(
    stored: StoredFlag,
) -> tuple[wiring.BackendConnectionFlag, FakeFlagStore, Clock]:
    """A `BackendConnectionFlag` over a fake store that holds `stored`, opened by `start()`."""
    registry, store, clock = FlagRegistry([default_registry()[_CONN]]), FakeFlagStore(), Clock()
    store.rows[_CONN] = stored
    runtime = SimpleNamespace(registry=registry, service=FlagService(registry, store, clock=clock))
    flag = wiring.BackendConnectionFlag(cast(wiring.FeatureFlagsRuntime, runtime), clock=clock)
    flag.reopen()
    return flag, store, clock


async def test_backend_connection_flag_before_start_answers_off_and_starts_no_refresh() -> None:
    """Closed until `start()`: a runtime that never starts (a bare `create_app`) answers off."""
    flag = _runtime().backend_connection
    assert flag() is False and flag._task is None


async def test_backend_connection_flag_start_primes_it_with_one_awaited_read() -> None:
    """`start()` reads the stored value before it returns, in no task (ADR-0038 2e, C-13.7)."""
    runtime, store = _runtime(), FakeFlagStore()
    store.rows[_CONN] = StoredFlag(True)
    runtime.service = FlagService(runtime.registry, store, clock=Clock())  # before `start()`
    await runtime.start()
    try:
        assert runtime.backend_connection.value is True
        assert runtime.backend_connection._task is None
    finally:
        await runtime.stop()


@pytest.mark.parametrize("fault", ["boot_outage", "outage", "unreadable"])
async def test_backend_connection_flag_store_or_row_fault_keeps_last_value(fault: str) -> None:
    """BC-D3: a boot during an outage keeps the default, off; an outage or an unreadable row after
    a read of on keeps on, where failing closed would turn it off."""
    flag, store, clock = _connection_flag(StoredFlag(True))
    last = fault != "boot_outage"  # the value read before the fault, if any
    if last:
        await flag.refresh()
        clock.now += 30  # the snapshot is stale: the next read reloads
    if fault == "unreadable":
        store.rows[_CONN] = StoredFlag("on")  # not a boolean
    else:
        store.down = True
    await flag.refresh()
    assert flag.value is last


async def test_backend_connection_flag_call_while_store_hangs_answers_at_once() -> None:
    """BC-D1: no request awaits the flag store; the refresh waits on it in its own task."""
    flag, store, _ = _connection_flag(StoredFlag(True))
    store.hold = asyncio.Event()
    assert flag() is False  # the last value, at once
    store.hold.set()
    await _settled(flag)
    assert flag.value is True


@pytest.mark.parametrize("down", [False, True])
async def test_backend_connection_flag_calls_within_30_s_start_no_second_refresh(
    down: bool,
) -> None:
    """At most one refresh per 30 s, outage or not, and one at a time; the priming read counts."""
    flag, store, clock = _connection_flag(StoredFlag(True))
    await flag.refresh()  # the priming read, at t0
    store.down, store.hold = down, asyncio.Event()
    clock.now += 29
    flag()
    assert flag._task is None  # 29 s after it
    clock.now += 1
    flag()
    first = flag._task
    flag()
    named = [t for t in asyncio.all_tasks() if t.get_name() == "desktop-backend-connection-flag"]
    assert first is not None and named == [first]  # one task, though called twice
    store.hold.set()
    await _settled(flag)
    clock.now += 29
    flag()
    assert flag._task is first  # it ended, but began 29 s ago
    clock.now += 1
    flag()
    assert flag._task is not first  # 30 s after it began
    await _settled(flag)


async def test_backend_connection_flag_role_override_is_ignored_read_with_no_principal() -> None:
    flag, store, _ = _connection_flag(StoredFlag(False, role_overrides={"owner": True}))
    await flag.refresh()
    assert flag.value is False and store.loads == 1  # read, and no role applies


async def test_backend_connection_flag_stop_cancels_refresh_and_restart_reopens() -> None:
    """A refresh in flight at stop is cancelled before the engine goes (C-2.18) and none starts
    after it; the next `start()` primes the reader again and opens it."""
    runtime, clock, store, ended = _runtime(), Clock(), FakeFlagStore(), list[bool]()
    runtime.backend_connection = flag = wiring.BackendConnectionFlag(runtime, clock=clock)
    runtime.service = FlagService(runtime.registry, store, clock=clock)
    await runtime.start()
    store.rows[_CONN], store.hold = StoredFlag(True), asyncio.Event()  # the next read hangs
    clock.now += 30
    flag()
    task = flag._task

    async def dispose() -> None:  # the real backend's engine
        ended.append(task is not None and task.done())

    runtime._relational = cast(Any, SimpleNamespace(dispose=dispose))
    await runtime.stop()
    assert task is not None and task.cancelled() and ended == [True]
    clock.now += 30  # the 30 s are up, so only being closed keeps a refresh from starting
    assert flag() is False and flag._task is task  # closed: the last value, no new refresh
    store.hold.set()
    await runtime.start()
    try:
        assert flag.value is True  # primed again
        clock.now += 30
        flag()
        assert flag._task is not task  # and open
    finally:
        await runtime.stop()


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


async def test_start_ensures_the_rows_and_the_poll_opens_the_maintenance_gate() -> None:
    runtime, account = _runtime(), uuid.uuid4()
    refusal = runtime.gate.refusal(account)
    assert refusal is not None and refusal.reason == "maintenance"  # unknown: engaged
    await runtime.start()
    poll = runtime._poll
    try:
        for _ in range(100):  # bounded: the poll's first read sees both gate flags off
            if not runtime.gate.engaged:
                break
            await asyncio.sleep(0)
        assert runtime.gate.refusal(account) is None
    finally:
        await runtime.stop()
    assert runtime._poll is None and poll is not None and poll.done()  # cancelled, awaited


class _AccountCheck:
    def refusal(self, account_id: uuid.UUID) -> OrderEntryRefusal | None:
        return None


def test_the_runtime_serves_no_order_entry_gate_until_one_is_composed() -> None:
    """#837 W3 (C-2.21): before `create_app` composes it there is no gate to take, so no holder
    ever gets one without the account check."""
    runtime = _runtime()
    with pytest.raises(RuntimeError, match="not composed"):
        _ = runtime.order_entry_gate


def test_the_order_entry_gate_is_never_composed_of_the_maintenance_check_alone() -> None:
    with pytest.raises(ValueError, match="account check"):
        _runtime().compose_order_entry_gate()


def test_the_runtime_serves_the_gate_it_composes_the_maintenance_check_first() -> None:
    runtime, check = _runtime(), _AccountCheck()
    gate = runtime.compose_order_entry_gate(check)
    assert runtime.order_entry_gate is gate and gate.checks == (runtime.gate, check)


def test_the_order_entry_gate_is_composed_once() -> None:
    """So a holder that took the gate always holds the one the runtime serves."""
    runtime = _runtime()
    runtime.compose_order_entry_gate(_AccountCheck())
    with pytest.raises(RuntimeError, match="once"):
        runtime.compose_order_entry_gate(_AccountCheck())


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


async def test_an_outage_of_the_users_or_the_step_up_store_is_the_writers_store_outage() -> None:
    down = AsyncMock(side_effect=StorageTierUnavailable("down"))
    auth = SimpleNamespace(step_up_is_active=True, step_up=SimpleNamespace(require_elevation=down))
    roles = SimpleNamespace(get_roles=down)
    with pytest.raises(StoreUnavailableError):
        await step_up_port(auth, wiring.restate_flag_write, None)(_OWNER, "flags", _CHANGE, _FP)
    with pytest.raises(StoreUnavailableError):
        await wiring.RoleStoreUsers(roles).unknown(frozenset({_OWNER.user_id}))


async def test_an_error_that_is_no_outage_passes_the_users_and_the_step_up_as_it_was() -> None:
    bug = AsyncMock(side_effect=RuntimeError("bug"))
    auth = SimpleNamespace(step_up_is_active=True, step_up=SimpleNamespace(require_elevation=bug))
    roles = SimpleNamespace(get_roles=bug)
    with pytest.raises(RuntimeError, match="bug"):
        await step_up_port(auth, wiring.restate_flag_write, None)(_OWNER, "flags", _CHANGE, _FP)
    with pytest.raises(RuntimeError, match="bug"):
        await wiring.RoleStoreUsers(roles).unknown(frozenset({_OWNER.user_id}))


def test_a_write_is_restated_from_its_validated_change_alone() -> None:
    change = FlagWrite("a.b", "v2", {_OWNER.user_id: "v1"}, _T0, _OWNER.user_id)
    assert wiring.restate_flag_write(change).action_summary.endswith("to v2, user overrides 1")
