"""#4517 (E42 AD-F16, SR-E42-14; `23-ws-protocol.md` 15.9): the `feature_flags` snapshot sent after
`auth_ok` carries no owner-only key to a Manager, on the wire and through the real flag service."""

from __future__ import annotations

import asyncio

from candleviewer.admin.flags import FlagService, default_registry
from candleviewer.admin.flags.push import feature_flags_snapshot
from tests.contract.ws._harness import World, connect
from tests.unit.admin.flag_fakes import Clock, FakeFlagStore


def test_a_manager_snapshot_never_names_an_owner_only_flag(wire: str) -> None:
    store, registry = FakeFlagStore(), default_registry()
    service = FlagService(registry, store, clock=Clock())
    asyncio.run(store.ensure(registry.values()))
    owner_only = {k for k, s in registry.items() if not s.visible_to(frozenset({"manager"}))}
    world = World(flag_snapshot=lambda user, roles: feature_flags_snapshot(service, user, roles))
    assert wire
    with connect(world) as client:
        frame = client.system_snap  # §12.1 (#4992): the flag set is folded into the snap
    assert owner_only  # the catalogue has some, or this test proves nothing
    assert frame is not None and frame["p"]["kind"] == "health"
    assert frame["p"]["feature_flags"]  # a Manager sees some flags, or this proves nothing
    assert not owner_only & set(frame["p"]["feature_flags"])
