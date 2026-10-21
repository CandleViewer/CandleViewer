"""Composition root of the machines feed (E17-T08; 23-ws-protocol.md §6.4): `RegistryFeed` is the
`MachineStatePort` that `CvStateFeedPlugin` publishes through, over the gateway's registry.

`ws` may not import `statechart` (C-2.20) and `statechart` may not import `ws`: an owning module
imports `statechart`, and every M-module but `api` forbids `ws` (C-3.1). This module imports both,
so the dependency graph gains no edge (C-3.4), as `statechart_wiring` does for storage.

The registry and the hub are single-threaded and lock-free, and a hook publishes from inside its
interpreter's step: a machine fed through this port runs on the serving loop. One on another loop
(the order lane's own, E29-T04) must hop with `call_soon_threadsafe` first.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from candleviewer.statechart.plugins.state_feed import FeedBinding, MachineStateHandle
from candleviewer.ws.machines import MachineEntity, MachineStateRegistry
from candleviewer.ws.topics import MACHINE_ENTITY_KIND, EntityScope


class RegistryFeed:
    """`MachineStatePort` over `registry`, for the process's `environment` and wall clock."""

    def __init__(
        self, registry: MachineStateRegistry, *, environment: str, now_ms: Callable[[], int]
    ) -> None:
        self.registry, self.environment, self.now_ms = registry, environment, now_ms

    def bind(self, binding: FeedBinding) -> MachineStateHandle:
        """The machine's slot. `ValueError` for a chart with no public entity (B8, B9, B13, B15:
        §16.6 W9) or an id off the §6.4 grammar: a wiring bug, met when the owner builds it."""
        kind = MACHINE_ENTITY_KIND.get(binding.machine_kind)
        if kind is None:
            raise ValueError(f"chart {binding.machine_kind!r} has no machines.{{entity}}.state")
        entity = MachineEntity(kind, binding.entity_id, EntityScope(binding.accounts, binding.user))
        return _Handle(self.registry, entity)


class _Handle:
    """One machine's slot, and the registry's `owner` token: a stopped machine removes only the
    entry it last published, never one a newer machine of the same entity took over."""

    def __init__(self, registry: MachineStateRegistry, entity: MachineEntity) -> None:
        self._registry, self._entity = registry, entity

    def publish(self, payload: Mapping[str, Any], *, last: bool) -> None:
        record = self._registry.terminal if last else self._registry.publish
        record(self._entity, payload, owner=self)

    def remove(self) -> None:
        self._registry.remove(self._entity, owner=self)
