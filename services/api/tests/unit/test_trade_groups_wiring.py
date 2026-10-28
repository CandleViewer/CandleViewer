"""E28-T05 S2a (#909): `GateReadiness`, trade-group readiness over the order-entry gate, the kill
switch, the live gate and the account row, the first reason winning. The ports are faked. S4b: the
composition root's `trade_groups` topic, served, fed and counted."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from structlog.testing import capture_logs

from candleviewer import app as appmod
from candleviewer import oms_wiring, trade_groups_wiring
from candleviewer.accounts.trade_group_readiness import ReadinessMember, ReadinessReason, readiness
from candleviewer.api.trade_group_preview import PREVIEW_PATH
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.domain.order_entry import REFUSAL_REASONS, OrderEntryRefusal, RefusalReason
from candleviewer.domain.primitives import Environment
from candleviewer.oms_wiring import InterimKillSwitch
from candleviewer.profiles_wiring import wire_profiles
from candleviewer.settings import Settings
from candleviewer.trade_groups_wiring import GATE_REASONS, GateReadiness, NoLockouts
from tests.csrf_helpers import arm_csrf, wire_fake_sessions
from tests.unit.accounts._fakes import ACC
from tests.unit.accounts.test_trade_group_topic import _stored
from tests.unit.api import test_trade_group_routes as groups
from tests.unit.api.test_trade_group_definition_create import PATH, caller, payload
from tests.unit.api.test_trade_group_definition_reads import CORE3, World
from tests.unit.ws._seq_support import Conn, Source

NOT_A_BOOL = cast(bool, 1)  # truthy, and not the bool the type promises


def _only(answer: Any) -> Callable[[UUID], Any]:
    """A port's answer for `ACC` alone: a lookup on any other account fails the test."""

    def ask(account_id: UUID) -> Any:
        assert account_id == ACC
        return answer

    return ask


def _source(
    gate: Any = None, lockouts: Any = None, env: Environment = "demo", **world: Any
) -> GateReadiness:
    """`world`: the kill switch's answer (`kill`: a refusal, none) and the live gate's `setting` and
    `flag` (on). The flag is read for a live account alone, as the OMS reads it."""

    def flag() -> Any:
        assert env not in ("demo", "testnet")
        return world.get("flag", True)

    return GateReadiness(
        gate,
        kill_switch=_only(world.get("kill")),
        live_enabled=world.get("setting", True),
        live_flag=flag,
        lockouts=lockouts or Mock(locked=_only(False)),
    )


def _reason(
    row: bool = True,
    gate: RefusalReason | None = None,
    locked: object = False,
    env: Environment = "demo",
    **world: Any,
) -> ReadinessReason | None:
    refusal = None if gate is None else OrderEntryRefusal(gate, "Refused.")
    source = _source(Mock(refusal=_only(refusal)), Mock(locked=_only(locked)), env, **world)
    return source.reason(ACC, env, account_enabled=row)


CASES: dict[str, tuple[dict[str, Any], ReadinessReason | None]] = {
    "ready": ({}, None),
    "row switched off": ({"row": False}, "account_disabled"),
    "row not a bool": ({"row": NOT_A_BOOL}, "account_disabled"),
    "no active key": ({"gate": "no_active_key"}, "key_invalid"),
    "disabled by policy": ({"gate": "account_disabled_by_policy"}, "account_disabled"),
    "unhealthy": ({"gate": "account_unhealthy"}, "account_unhealthy"),
    "maintenance": ({"gate": "maintenance"}, "trading_disabled"),
    "kill switch": ({"kill": True}, "kill_switch_engaged"),
    "kill switch answering 0": ({"kill": 0}, "kill_switch_engaged"),
    "kill switch answering False": ({"kill": False}, "kill_switch_engaged"),
    "kill switch answering an empty string": ({"kill": ""}, "kill_switch_engaged"),
    "live, setting off": ({"env": "live", "setting": False}, "trading_disabled"),
    "live, setting not a bool": ({"env": "live", "setting": NOT_A_BOOL}, "trading_disabled"),
    "live, flag off": ({"env": "live", "flag": False}, "trading_disabled"),
    "live, flag not a bool": ({"env": "live", "flag": NOT_A_BOOL}, "trading_disabled"),
    "live, both on": ({"env": "live"}, None),
    "an unknown environment is live": ({"env": "paper", "flag": False}, "trading_disabled"),
    "demo meets no live gate": ({"setting": False, "flag": False}, None),
    "testnet meets no live gate": ({"env": "testnet", "setting": False}, None),
    "locked": ({"locked": True}, "account_locked"),
    "lockout source cannot tell": ({"locked": None}, "account_locked"),
    "first: row, gate": ({"row": False, "gate": "no_active_key"}, "account_disabled"),
    "first: gate, switch": ({"gate": "maintenance", "kill": True}, "trading_disabled"),
    "first: switch, live": ({"kill": True, "env": "live", "flag": False}, "kill_switch_engaged"),
    "first: live, lock": ({"env": "live", "flag": False, "locked": True}, "trading_disabled"),
}


@pytest.mark.parametrize(("world", "expected"), CASES.values(), ids=CASES)
def test_each_order_entry_refusal_maps_to_its_reason(
    world: dict[str, Any], expected: ReadinessReason | None
) -> None:
    assert _reason(**world) == expected
    assert not inspect.iscoroutinefunction(GateReadiness.reason)  # no await: C-2.21


def test_a_refusal_the_table_does_not_hold_is_not_ready() -> None:
    assert set(GATE_REASONS) == REFUSAL_REASONS  # a reason E27 adds must be decided here
    newer = SimpleNamespace(reason="a_reason_e27_adds_later")  # a look-alike the real gate refuses
    gate = Mock(refusal=_only(newer))
    assert _source(gate).reason(ACC, "demo", account_enabled=True) == "trading_disabled"


def test_no_gate_means_no_member_is_ready() -> None:
    members = [ReadinessMember(UUID(int=n), True, n != 2) for n in (1, 2, 3)]  # row 2 switched off
    result = readiness(members, _source(None), "demo")
    assert (result.ready, result.total) == (0, 3)
    assert [(m.ready, m.reason) for m in result.members] == [(False, "trading_disabled")] * 3


def test_no_lockout_is_reported_until_e39() -> None:
    assert NoLockouts().locked(ACC) is False
    with capture_logs() as logs:
        assert _source(None, NoLockouts()).announce()
    announced = [(e["log_level"], e["port"], e["replaced_by"], e["serves"]) for e in logs]
    assert announced == [("warning", "risk_lockouts", "E39-S02", NoLockouts.serves)]
    with capture_logs() as logs:
        assert not _source(None).announce()  # a real lockout source: nothing to say
    assert logs == []


def test_the_root_wires_the_definition_reads_and_announces_the_interim_lockouts_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert trade_groups_wiring.definition_store(Settings(storage_backend="fake")) is None
    real = Settings(storage_backend="real", oms_statement_timeout_ms=3000)  # not the 2000 default
    store = trade_groups_wiring.definition_store(real)
    assert store is not None and (store._timeout, store._audit_timeout_s) == ("3000", 5.0)
    world = World()  # the reads' store, and an owner who may read
    monkeypatch.setattr(appmod, "definition_store", lambda _settings: world.store)
    with capture_logs() as logs:
        app = appmod.create_app(principal_resolver=world)
    source = app.state.trade_group_readiness
    assert source._gate is app.state.order_entry_gate and isinstance(source._lockouts, NoLockouts)
    assert [log["event"] for log in logs].count("trade_groups_interim_port") == 1
    assert source._live_enabled is False  # the setting's default
    assert source._live_flag is app.state.feature_flags.live_enabled  # the OMS's view of the flag
    assert isinstance(getattr(source._kill_switch, "__self__", None), InterimKillSwitch)
    gate = app.state.trade_groups_gate  # over the flag's view, the preview ready (S3c, ruling 6)
    assert (gate._enabled, gate._preview_ready) == (app.state.feature_flags.trade_groups, True)
    # a router given no store or no readiness answers 503, not this
    got = TestClient(app, client=("127.0.0.1", 50000)).get(f"/trade-group-definitions/{CORE3}")
    assert got.status_code == 200 and got.json()["readiness"]["total"] == 3


def test_the_root_mounts_the_definition_create_over_the_composed_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E28-T05 S2c (#909): with no profile wiring (the fake backend) an Owner's create answers 503;
    given one, the root hands the router the writes it composes, so the same POST reaches the flag's
    gate (off: 403 `trading_disabled`). The wiring's pool is lazy: nothing connects."""
    world = World()
    world.principal = caller("owner")
    monkeypatch.setattr(appmod, "definition_store", lambda _settings: world.store)

    def answer() -> tuple[int, str]:
        app = appmod.create_app(principal_resolver=world)
        wire_fake_sessions(app, "owner")  # SR-041: a state-changing request needs a bearer
        client = arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec)
        got = client.post(PATH, json=payload(), headers={"Authorization": "Bearer owner"})
        return got.status_code, got.json()["code"]

    assert answer() == (503, "store_unavailable")
    real = Settings(storage_backend="real")

    def wired(_settings: Settings, metrics: Any, bus: Any = None) -> Any:
        return wire_profiles(real, metrics, bus)

    monkeypatch.setattr(appmod, "wire_profiles", wired)
    assert answer() == (403, "trading_disabled")


def _writes(routes: Any, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Each definition write served, walked as `deny_by_default.served_operations` walks them."""
    for route in routes:
        if (inner := getattr(route, "original_router", None)) is not None:
            context = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _writes(inner.routes, prefix + context)
        elif isinstance(route, APIRoute) and route.path.startswith(PATH):
            for method in sorted((route.methods or set()) & {"POST", "PUT", "DELETE"}):
                yield f"{method} {prefix}{route.path}", route


def test_the_root_gates_each_definition_write_with_the_risk_caps_step_up() -> None:
    """SR-E28-02, PF-S02: each mounted write demands its step-up through the root's `elevation`,
    of class `risk_caps` as the registry declares, read off the closures as `test_suite_meta.py`
    reads a guard's permission (no route test sees the class: each injects its own)."""
    classes = {}
    for key, route in _writes(appmod.create_app(principal_resolver=World()).routes):
        elevation = inspect.getclosurevars(route.endpoint).nonlocals["elevation"]
        classes[key] = inspect.getclosurevars(elevation).nonlocals["action_class"]
    one = f"{PATH}/{{definitionId}}"
    assert classes == dict.fromkeys([f"POST {PATH}", f"PUT {one}", f"DELETE {one}"], "risk_caps")


def test_the_root_mounts_the_group_reads_over_a_pool_of_their_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E28-T05 S2f: the scoped group read on a pool of its own at the OMS stores' cap, none on the
    fake backend (503); the root mounts both routes over a reader of it, with no flag."""
    assert oms_wiring.group_reads(Settings(storage_backend="fake")) is None
    real = Settings(storage_backend="real", oms_statement_timeout_ms=3000)  # not the 2000 default
    store = oms_wiring.group_reads(real)
    assert store is not None and cast(Any, store)._timeout == "3000"
    world = groups.World()  # the routes' store, and an owner who may read
    monkeypatch.setattr(appmod, "group_reads", lambda _settings: world.store)
    client = TestClient(appmod.create_app(principal_resolver=world), client=("127.0.0.1", 50000))
    got = client.get(f"/trade-groups/{groups.PAIR.group.id}")
    assert got.status_code == 200 and got.json()["id"] == str(groups.PAIR.group.id)
    assert [i["id"] for i in client.get("/trade-groups").json()["items"]] == groups.ids_of(
        *groups.NEWEST_FIRST
    )


def test_the_root_mounts_the_preview_behind_the_flag_now_that_its_gate_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E28-T05 S3c (#909): the root mounts the preview over the OMS runtime, the profile wiring and
    the gate it builds `preview_ready`: with the flag's view unread, so off, an Owner's preview is
    `403 trading_disabled` with no `reason`, recorded; once the view reads the demo seed, on, the
    preview passes the gate to the body's 422. The wiring's pool is lazy: nothing connects."""
    world, recorded = World(), list[str]()
    world.principal = PrincipalSnapshot(UUID(int=7), frozenset({"owner"}), frozenset(Permission))
    real = Settings(storage_backend="real")

    def wired(_settings: Settings, metrics: Any, bus: Any = None) -> Any:
        return wire_profiles(real, metrics, bus)

    async def emit(action: str, **_fields: Any) -> None:
        recorded.append(action)

    monkeypatch.setattr(appmod, "wire_profiles", wired)
    runtime = SimpleNamespace(readiness="ok")  # never started here, never asked past the gate
    monkeypatch.setattr(appmod, "build_oms_runtime", lambda *_args, **_kwargs: runtime)
    app = appmod.create_app(principal_resolver=world)
    app.state.app_context.audit._writer = SimpleNamespace(emit=emit)
    wire_fake_sessions(app, "owner")  # SR-041: a state-changing request needs a bearer
    client = arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec)
    off = client.post(PREVIEW_PATH, json={}, headers={"Authorization": "Bearer owner"})
    assert (off.status_code, off.json()["code"], "reason" in off.json()) == (
        403, "trading_disabled", False,
    )  # fmt: skip
    asyncio.run(app.state.feature_flags.trade_groups.refresh())  # the demo seed: on
    on = client.post(PREVIEW_PATH, json={}, headers={"Authorization": "Bearer owner"})
    assert (on.status_code, recorded) == (422, ["trade_group.previewed"] * 2)


def test_the_root_hands_the_oms_runtime_the_topic_it_serves_and_counts_its_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4b's R1C-02: the `trade_groups` topic the snapshot router serves is the one the OMS runtime
    is handed to seed and feed; it publishes on the app's hub and counts on the app's facade."""
    build = Mock(return_value=None)  # the fake backend's runtime: none
    monkeypatch.setattr(appmod, "build_oms_runtime", build)
    app = appmod.create_app(Settings())
    services, facade = app.state.ws_registry.services, app.state.metrics_facade
    topic = services.snapshots._sources["trade_groups"]
    assert build.call_args.kwargs["trade_groups"] is topic
    conn = Conn(cast(Source, services.snapshots), ACC)  # a Manager granted ACC, on the app's hub
    services.sequencing.register(conn.authz, conn.emitter)
    conn.sub({"ch": "trade_groups", "opts": {"exchange_account_ids": [str(ACC)]}})
    topic.seed([])
    topic.created(_stored(1, ACC))
    assert [frame["t"] for frame in conn.take()] == ["snap", "d"]
    text = generate_latest(facade.registry).decode()
    for kind in ("snapshot", "delta"):
        assert f'cv_tradegroup_ws_frames_total{{env="{facade.env}",kind="{kind}"}} 1.0' in text
