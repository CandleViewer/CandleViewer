"""`machines.{entity}.state` registry (E17-T08; `23-ws-protocol.md` §6.4): `sub` is authorised
synchronously against an entry (SR-189) and `snap`/`resync` are answered only from it, never from
an `Interpreter` (C-2.20). An entry keeps its first payload's `EntityScope` (immutable, §6.4).
Bound (C-2.18): `MACHINE_ENTRIES_MAX` entries; a payload for a new entity past it is refused and
logged (no live state is evicted), so a `sub` to that entity gets the refusal a foreign one gets.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from candleviewer.ws.limits import MACHINE_ENTRIES_MAX
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.topics import EntityScope, TopicError, parse_topic

if TYPE_CHECKING:
    from candleviewer.ws.permissions import Subscription


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MachineEntity:
    """A machine's public id (its kind, plus a uuid or symbol unless a singleton) and the scope
    the owning module binds from its own record, never from the machine's context. Build it once
    per machine (at build and at restore) and reuse it for every publish: construction checks the
    id against the §6.4 grammar, and an id it refuses is a publisher bug (`ValueError`)."""

    kind: str
    ident: str | None = None
    scope: EntityScope = field(default_factory=EntityScope)
    ch: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        ch = f"machines.{self.kind}{'' if self.ident is None else ':' + self.ident}.state"
        try:
            parse_topic(ch)
        except TopicError as exc:
            raise ValueError(f"not a 23 section 6.4 machine entity: {exc.message}") from None
        object.__setattr__(self, "ch", ch)


@dataclass(slots=True)
class _Entry:
    scope: EntityScope
    payload: Mapping[str, Any] = field(default_factory=dict)
    terminal: bool = False


class MachineStateRegistry:
    """Latest payload per entity, and the `machines` family's `SnapshotSource`: never a `snap`
    without a published state (design S)."""

    def __init__(self, *, max_entries: int = MACHINE_ENTRIES_MAX) -> None:
        self.max_entries = max_entries
        self._entries: dict[str, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def scope(self, ch: str) -> EntityScope | None:
        """The entry's scope, or `None` when `ch` has no entry. Synchronous by design (SR-189)."""
        entry = self._entries.get(ch)
        return None if entry is None else entry.scope

    def publish(self, entity: MachineEntity, payload: Mapping[str, Any]) -> bool:
        """Record `payload` as the entity's state. False when refused."""
        return self._record(entity, payload, terminal=False)

    def terminal(self, entity: MachineEntity, payload: Mapping[str, Any]) -> bool:
        """Record the entity's last payload (its `tags` hold `terminal`); later ones are refused."""
        return self._record(entity, payload, terminal=True)

    def _record(self, entity: MachineEntity, payload: Mapping[str, Any], *, terminal: bool) -> bool:
        entry = self._entries.get(entity.ch)
        if entry is None:
            if len(self._entries) >= self.max_entries:
                _log().error("machine state refused: registry full", entity_kind=entity.kind)
                return False
            entry = self._entries[entity.ch] = _Entry(entity.scope)
        elif entry.terminal:
            return False
        entry.payload, entry.terminal = dict(payload), terminal
        return True

    # -- SnapshotSource --

    def build(self, sub: Subscription) -> SnapshotBody | None:
        entry = self._entries.get(sub.ch)
        return None if entry is None else SnapshotBody(entry.payload)

    def generation(self, sub: Subscription) -> int:
        return 0  # a private family's snapshot is never cached (SR-190)

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False  # no per-entity history: `snapshot: false` is always `snapshot_forced`
