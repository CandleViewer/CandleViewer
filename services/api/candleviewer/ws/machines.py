"""`machines.{entity}.state` registry (E17-T08; `23-ws-protocol.md` §6.4): `sub` is authorised
synchronously against an entry (SR-189) and `snap`/`resync` are answered only from it, never from
an `Interpreter` (C-2.20). An entry keeps its first payload's `EntityScope` (immutable, §6.4).

Fan-out: a recorded payload reaches its topic's subscriptions through `SequencingHub.publish`, in
the publisher's own call: one synchronous pass over the live connections, with no task, await or
queue of its own. A subscription still pending its `snap` gets that `snap` (the first publish
wakes it, never an inbound frame); the others get a `d`. Each frame goes into its connection's
bounded outbound queue, which closes a slow consumer rather than wait (C-2.18), so a client never
blocks the publisher. A wake ignores `paused`, like `SequencingHub.resnapshot`; skipping a paused
one would also need a resume to snap what was pending before its `ctl` (E17-T03's call, #412).

Bound (C-2.18): `MACHINE_ENTRIES_MAX` entries; a payload for a new entity past it is refused and
counted (no live state is evicted), so a `sub` to that entity gets the refusal a foreign one gets.
A refusal, a scope-less entry of a scoped kind and a scope change each log at most one line per
kind per `LOG_INTERVAL_S`; the counters carry the rate.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

import structlog

from candleviewer.auth.generated_permissions import Scope
from candleviewer.observability.metrics import Counter
from candleviewer.ws.limits import MACHINE_ENTRIES_MAX
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws.topics import MACHINE_KINDS, EntityScope, TopicError, parse_topic

if TYPE_CHECKING:
    from candleviewer.ws.permissions import Subscription

#: A kind's warning or error is logged at most once per this many seconds (C-2.18).
LOG_INTERVAL_S: Final = 60.0

cv_machine_ws_publish_total = Counter(
    "cv_machine_ws_publish_total",
    "Machine-state payloads the WS registry recorded, one per payload (23 section 6.4).",
    labelnames=("entity_kind",),
)
cv_machine_ws_scope_missing_total = Counter(
    "cv_machine_ws_scope_missing_total",
    "Payloads recorded for a scoped machine kind whose entry has no scope (refused to all).",
    labelnames=("entity_kind",),
)
cv_machine_ws_registry_full_total = Counter(
    "cv_machine_ws_registry_full_total",
    "Machine-state payloads for a new entity refused because the WS registry is full.",
    labelnames=("entity_kind",),
)
#: Bound once per closed kind, so each series exists at 0 from process start (an `increase()`
#: alert misses a series born at its first event, #2264) and a publish does no label lookup.
_PUBLISHED: Final = {k: cv_machine_ws_publish_total.labels(entity_kind=k) for k in MACHINE_KINDS}
_FULL: Final = {k: cv_machine_ws_registry_full_total.labels(entity_kind=k) for k in MACHINE_KINDS}
_SCOPE_MISSING: Final = {
    k: cv_machine_ws_scope_missing_total.labels(entity_kind=k)
    for k, rule in MACHINE_KINDS.items()
    if rule.scope != Scope.NONE
}
_UNSCOPED: Final = EntityScope()


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
    without a published state (design S). `hub` fans each recorded payload out; `None` records
    only (a registry no connection reads)."""

    def __init__(
        self,
        *,
        max_entries: int = MACHINE_ENTRIES_MAX,
        hub: SequencingHub | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max_entries
        self._hub = hub
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        #: (event, kind) -> when it was last logged; at most 3 events x 13 kinds.
        self._logged: dict[tuple[str, str], float] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def scope(self, ch: str) -> EntityScope | None:
        """The entry's scope, or `None` when `ch` has no entry. Synchronous by design (SR-189)."""
        entry = self._entries.get(ch)
        return None if entry is None else entry.scope

    def publish(self, entity: MachineEntity, payload: Mapping[str, Any]) -> bool:
        """Record `payload` as the entity's state and fan it out. False when refused. `publish` and
        `terminal` run on the event-loop thread: the fan-out queues onto `asyncio.Queue`s."""
        return self._record(entity, payload, terminal=False)

    def terminal(self, entity: MachineEntity, payload: Mapping[str, Any]) -> bool:
        """Record the entity's last payload (its `tags` hold `terminal`); later ones are refused."""
        return self._record(entity, payload, terminal=True)

    def _record(self, entity: MachineEntity, payload: Mapping[str, Any], *, terminal: bool) -> bool:
        kind, entry = entity.kind, self._entries.get(entity.ch)
        if entry is None:
            if len(self._entries) >= self.max_entries:
                _FULL[kind].inc()
                self._note("error", "machine state refused: registry full", kind)
                return False
            entry = _Entry(entity.scope)  # registered below, once its payload is stored
        elif entry.terminal:
            return False
        elif entity.scope != entry.scope:  # the first payload's scope stays (§6.4)
            self._note("warning", "machine scope change ignored", kind)
        # A deep copy: a producer that reuses or mutates its dict never changes what is served.
        entry.payload, entry.terminal = copy.deepcopy(dict(payload)), terminal
        self._entries[entity.ch] = entry  # last: a payload that cannot be copied leaves no entry
        _PUBLISHED[kind].inc()
        if kind in _SCOPE_MISSING and entry.scope == _UNSCOPED:  # a binding defect (§6.4)
            _SCOPE_MISSING[kind].inc()
            self._note("warning", "machine state without a scope: refused to every role", kind)
        if self._hub is not None:
            self._hub.publish(entity.ch, entry.payload, wake=True)
        return True

    def _note(self, level: Literal["error", "warning"], event: str, kind: str) -> None:
        """Log `event` for `kind` unless it was logged in the last `LOG_INTERVAL_S`: a producer
        stuck on a defect never floods the sink (C-2.18). The kind only, never an id (C-12.6)."""
        now, key = self._clock(), (event, kind)
        last = self._logged.get(key)
        if last is not None and now - last < LOG_INTERVAL_S:
            return
        self._logged[key] = now
        getattr(_log(), level)(event, entity_kind=kind)

    # -- SnapshotSource --

    def build(self, sub: Subscription) -> SnapshotBody | None:
        entry = self._entries.get(sub.ch)
        return None if entry is None else SnapshotBody(entry.payload)

    def generation(self, sub: Subscription) -> int:
        return 0  # a private family's snapshot is never cached (SR-190)

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False  # no per-entity history: `snapshot: false` is always `snapshot_forced`
