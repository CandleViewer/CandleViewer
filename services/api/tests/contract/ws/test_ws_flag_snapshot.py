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


def test_a_manager_with_one_grant_gets_the_snapshot_while_maintenance_is_on() -> None:
    service = _service(maintenance=True)
    world = World(flag_snapshot=_snapshot(service))
    world.grants = (AccountGrant(ACC_A, True, False, False),)  # one granted account
    with connect(world) as client:
        frame = client.recv()  # validated: the envelope and `system.schema.json`
    flags = frame["p"]["feature_flags"]
    assert (frame["ch"], frame["p"]["kind"]) == ("system", "feature_flags")
    assert flags[MAINTENANCE_MODE] is True
    seen = {k for k, s in service.registry.items() if s.visible_to(frozenset({"manager"}))}
    assert set(flags) == seen
    assert "killswitch.ingestion" not in flags


def test_a_role_that_may_see_no_flag_gets_no_snapshot() -> None:
    hidden = [s for s in default_registry().values() if not s.visible_to(frozenset({"manager"}))]
    world = World(system_notices=lambda: [_MARK], flag_snapshot=_snapshot(_service(hidden)))
    with connect(world) as client:
        frame = client.recv()
    assert (frame["ch"], frame["p"]["kind"]) == ("system", "notice")
