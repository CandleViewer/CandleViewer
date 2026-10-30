"""#4517 (`23-ws-protocol.md` 15.9, 13.4): the `feature_flags` snapshot after `auth_ok` through the
E17-Q01 conformance harness, whose client validates every frame against the §13-§15 schemas."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from candleviewer.admin.flags import MAINTENANCE_MODE, FlagService, FlagSpec, default_registry
from candleviewer.admin.flags.push import feature_flags_snapshot
from candleviewer.admin.flags.registry import FlagRegistry
from candleviewer.auth.scopes import AccountGrant
from candleviewer.ws.gateway import FlagSnapshot
from tests.contract.ws._harness import World, connect
from tests.unit.admin.flag_fakes import Clock, FakeFlagStore
from tests.unit.ws._seq_support import ACC_A

_MARK = {"kind": "notice", "severity": "info", "message": "marker", "reason": "test.marker"}


def _service(specs: list[FlagSpec] | None = None, *, maintenance: bool = False) -> FlagService:
    store = FakeFlagStore()
    registry = default_registry() if specs is None else FlagRegistry(specs)
    service = FlagService(registry, store, clock=Clock())
    asyncio.run(store.ensure(registry.values()))
    if maintenance:
        store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    return service


def _snapshot(service: FlagService) -> FlagSnapshot:
    return lambda user, roles: feature_flags_snapshot(service, user, roles)


def test_a_manager_with_one_grant_gets_the_flags_in_the_snap_while_maintenance_is_on() -> None:
    service = _service(maintenance=True)
    world = World(system_notices=lambda: [_MARK], flag_snapshot=_snapshot(service))
    world.grants = (AccountGrant(ACC_A, True, False, False),)  # one granted account
    with connect(world) as client:
        snap = client.system_snap  # validated: the envelope and `system.schema.json`
        after = client.recv()
    assert snap is not None
    assert (snap["t"], snap["ch"], snap["s"], snap["p"]["kind"]) == ("snap", "system", 1, "health")
    flags = snap["p"]["feature_flags"]
    assert flags[MAINTENANCE_MODE] is True
    seen = {k for k, s in service.registry.items() if s.visible_to(frozenset({"manager"}))}
    assert set(flags) == seen
    assert "killswitch.ingestion" not in flags
    # #4992: folded into the snap, never sent again as its own frame; the notice is the next delta
    assert (after["t"], after["s"], after["p"]["kind"]) == ("d", 2, "notice")


def test_a_role_that_may_see_no_flag_gets_a_snap_without_flags() -> None:
    hidden = [s for s in default_registry().values() if not s.visible_to(frozenset({"manager"}))]
    world = World(system_notices=lambda: [_MARK], flag_snapshot=_snapshot(_service(hidden)))
    with connect(world) as client:
        snap = client.system_snap
        frame = client.recv()
    assert snap is not None and "feature_flags" not in snap["p"]
    assert (frame["t"], frame["ch"], frame["s"], frame["p"]["kind"]) == ("d", "system", 2, "notice")


#: A health frame as `HealthSystemPublisher` builds one (`health_wiring._health_frame`).
_HEALTH = {
    "kind": "health",
    "health": "healthy",
    "components": [{"name": "bybit_rest", "state": "healthy", "detail": "ok"}],
    "exchange": {"public_ws": "connected", "private_ws": "connected", "rest": "healthy"},
    "clock_offset_ms": 4,
}


def test_the_snap_carries_the_section_12_1_baseline_and_matches_the_schema() -> None:
    """#4992 (§12.1): health, the kill switch `auth_ok` gave and the flags, in one snap, `s` 1;
    the Manager's cut leaves out a component's `detail` (§15.9)."""
    world = World(flag_snapshot=_snapshot(_service()), system_baseline=lambda: _HEALTH)
    with connect(world) as client:  # `open` validates the snap: the envelope and the §15.9 schema
        snap = client.system_snap
        auth_ok = next(f for f in client.seen if f["t"] == "auth_ok")
    assert snap is not None
    p = snap["p"]
    assert (snap["t"], snap["ch"], snap["s"], snap["e"]) == ("snap", "system", 1, "j")
    assert (p["kind"], p["health"], p["clock_offset_ms"]) == ("health", "healthy", 4)
    assert p["exchange"] == _HEALTH["exchange"]
    assert p["components"] == [{"name": "bybit_rest", "state": "healthy"}]
    assert p["kill_switch"] == auth_ok["p"]["kill_switch"]
    assert p["feature_flags"]
