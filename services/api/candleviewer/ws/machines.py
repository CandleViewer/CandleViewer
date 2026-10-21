"""`machines.{entity}.state` registry (E17-T08; `23-ws-protocol.md` §6.4): `sub` is authorised
synchronously against an entry (SR-189) and `snap`/`resync` are answered only from it, never from
an `Interpreter` (C-2.20). An entry keeps its first payload's `EntityScope` (immutable, §6.4).

Fan-out: a recorded payload reaches its topic's subscriptions through `SequencingHub.publish`, in
the publisher's own call, or its window timer's: one synchronous pass, with no task, await or
queue of its own. A subscription still pending its `snap` gets that `snap` (the first publish
wakes it, never an inbound frame); the others get a `d`. Each frame goes into its connection's
bounded outbound queue, which closes a slow consumer rather than wait (C-2.18), so a client never
blocks the publisher. A wake ignores `paused`, like `SequencingHub.resnapshot`; skipping a paused
one would also need a resume to snap what was pending before its `ctl` (E17-T03's call, #412).

Coalescing (§6.4), whatever the backpressure flag: with `call_later`, the first payload after a
quiet window of `coalesce_s` (100 ms) goes out at once; a later one is recorded at once, so a `snap`
reads it, and goes out in the call of the one timer that closes the window, the latest only.

Retention (§6.4): a terminal entry stays `retention_s` from its first terminal payload (a later one
replaces the payload, a parallel chart's next step), at most `terminal_max` of them (oldest first);
`remove` ends a live one when its machine stops. A removal sends what waits for its window (flag
on, §8.6 drops it with the queue), revokes each subscription, hands `on_revoked` the frames.

Bound (C-2.18): `MACHINE_ENTRIES_MAX` entries; a payload for a new entity past it is refused and
counted (no live state is evicted), so a `sub` to that entity gets the refusal a foreign one gets.
A refusal, a scope-less entry of a scoped kind and a scope change each log at most one line per
kind per `LOG_INTERVAL_S`; only a full registry and a scope-less entry are counted.
"""

from __future__ import annotations

import copy
import math
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Literal

import structlog

from candleviewer.auth.generated_permissions import Scope
from candleviewer.observability.metrics import Counter
from candleviewer.ws.limits import (
    MACHINE_ENTRIES_MAX,
    MACHINE_TERMINAL_MAX,
    MACHINE_TERMINAL_RETENTION_S,
)
from candleviewer.ws.machine_payload import check_machine_payload
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws.topics import FAMILIES, MACHINE_KINDS, EntityScope, TopicError, parse_topic

if TYPE_CHECKING:
    import asyncio

    from candleviewer.ws.permissions import ConnectionAuthz, Subscription

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
    kind: str
    scope: EntityScope
    payload: Mapping[str, Any] = field(default_factory=dict)
    terminal: bool = False
    owner: object = None  # the token the payload was recorded with (`remove` needs it)
    due: float = -math.inf  # when the window closes (`clock`)
    timer: asyncio.Handle | None = None  # armed while a payload waits for the window
    expires: float = math.inf  # when a terminal entry ends


class MachineStateRegistry:
    """Latest payload per entity, and the `machines` family's `SnapshotSource`: never a `snap`
    without a published state (design S). `hub` fans each recorded payload out; `None` records
    only (a registry no connection reads). Without `call_later` (the loop's timers) a payload goes
    out at once, and only `sweep` ends a terminal entry."""

    def __init__(
        self,
        *,
        max_entries: int = MACHINE_ENTRIES_MAX,
        hub: SequencingHub | None = None,
        clock: Callable[[], float] = time.monotonic,
        call_later: Callable[[float, Callable[[], None]], asyncio.Handle] | None = None,
        wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        on_revoked: Callable[[list[tuple[ConnectionAuthz, dict[str, Any]]]], None] | None = None,
        coalesce_s: float = FAMILIES["machines"].default_throttle_ms / 1000,
        retention_s: float = MACHINE_TERMINAL_RETENTION_S,
        terminal_max: int = MACHINE_TERMINAL_MAX,
    ) -> None:
        self.max_entries = max_entries
        self.coalesce_s, self.retention_s, self.terminal_max = coalesce_s, retention_s, terminal_max
        self.on_revoked = on_revoked
        self._hub = hub
        self._clock = clock
        self._call_later, self._wall_ms = call_later, wall_ms
        self._entries: dict[str, _Entry] = {}
        #: Terminal entries by `ch`, oldest first; one whose `ch` holds another entry is stale.
        self._terminal: OrderedDict[str, _Entry] = OrderedDict()
        self._sweep_timer: asyncio.Handle | None = None
        #: (event, kind) -> when it was last logged; at most 5 events x 13 kinds.
        self._logged: dict[tuple[str, str], float] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def scope(self, ch: str) -> EntityScope | None:
        """The entry's scope, or `None` when `ch` has no entry. Synchronous by design (SR-189)."""
        entry = self._entries.get(ch)
        return None if entry is None else entry.scope

    def publish(
        self, entity: MachineEntity, payload: Mapping[str, Any], *, owner: object = None
    ) -> bool:
        """Record `payload` as the entity's state and fan it out (coalesced). False when refused:
        invalid, after the terminal one, or past the bound. `owner` is the publisher's token. These
        methods run on the event-loop thread: the fan-out queues onto `asyncio.Queue`s."""
        return self._record(entity, payload, owner, terminal=False)

    def terminal(
        self, entity: MachineEntity, payload: Mapping[str, Any], *, owner: object = None
    ) -> bool:
        """Record the entity's last payload (its `tags` hold `terminal`): a `publish` after it is
        refused, a further `terminal` (a parallel chart's later step) replaces it."""
        return self._record(entity, payload, owner, terminal=True)

    def remove(self, entity: MachineEntity, *, owner: object = None) -> bool:
        """Remove a live entry now, its machine stopped; True when removed. A missing or terminal
        one (retention ends it), or one recorded with another `owner` (a newer machine), stays."""
        entry = self._entries.get(entity.ch)
        if entry is None or entry.terminal or entry.owner is not owner:
            return False
        self._remove(entity.ch, entry)
        return True

    def sweep(self) -> int:
        """Remove each terminal entry whose retention ended (how many), then re-arm the timer."""
        now, removed = self._clock(), 0
        while self._terminal and next(iter(self._terminal.values())).expires <= now:
            ch, entry = self._terminal.popitem(last=False)
            if self._entries.get(ch) is entry:  # else stale: `ch` holds another entry, or none
                self._remove(ch, entry)
                removed += 1
        self._arm_sweep()
        return removed

    def close(self) -> None:
        """Cancel every armed timer (`WsRuntime.stop`): a payload waiting for its window is dropped.
        A later payload arms its window again, a terminal one or `sweep` the retention timer."""
        for entry in self._entries.values():
            if entry.timer is not None:
                entry.timer.cancel()
                entry.timer = None
        if self._sweep_timer is not None:
            self._sweep_timer.cancel()
            self._sweep_timer = None

    def _record(
        self, entity: MachineEntity, payload: Mapping[str, Any], owner: object, *, terminal: bool
    ) -> bool:
        kind, entry = entity.kind, self._entries.get(entity.ch)
        ended = entry is not None and entry.terminal
        if ended and not terminal:
            self._note("warning", "machine state after terminal ignored", kind)
            return False
        if entry is None and len(self._entries) >= self.max_entries:
            _FULL[kind].inc()
            self._note("error", "machine state refused: registry full", kind)
            return False
        # A deep copy, checked, then stored: a producer that reuses or mutates its dict never
        # changes what is served, and one that cannot be copied or breaks §15.10 changes nothing.
        state = copy.deepcopy(dict(payload))
        if (bad := check_machine_payload(kind, state)) is not None:
            self._note("error", "machine state refused: invalid payload", kind, field=bad)
            return False
        if entry is None:
            entry = self._entries[entity.ch] = _Entry(kind, entity.scope)
        elif entity.scope != entry.scope:  # the first payload's scope stays (§6.4)
            self._note("warning", "machine scope change ignored", kind)
        entry.payload, entry.terminal, entry.owner = state, terminal, owner
        _PUBLISHED[kind].inc()
        if kind in _SCOPE_MISSING and entry.scope == _UNSCOPED:  # a binding defect (§6.4)
            _SCOPE_MISSING[kind].inc()
            self._note("warning", "machine state without a scope: refused to every role", kind)
        if terminal and not ended:  # indexed and timed first: a fan-out that raises cannot keep it
            entry.expires = self._clock() + self.retention_s
            self._terminal.pop(entity.ch, None)  # a stale index entry: this one goes last
            self._terminal[entity.ch] = entry
            self._arm_sweep()
        self._fan_out(entity.ch, entry)  # before the cap's removals: one that raises skips no `d`
        while len(self._terminal) > self.terminal_max:  # the oldest goes first, at once
            ch, old = self._terminal.popitem(last=False)
            if self._entries.get(ch) is old:
                self._remove(ch, old)
        return True

    def _fan_out(self, ch: str, entry: _Entry) -> None:
        """Send `entry` now, or when its window closes: one timer per window, the latest payload."""
        if entry.timer is None:
            delay = entry.due - self._clock()
            if self._call_later is None or delay <= 0:
                self._send(ch, entry)
            else:
                entry.timer = self._call_later(delay, partial(self._window_closed, ch, entry))

    def _window_closed(self, ch: str, entry: _Entry) -> None:
        entry.timer = None
        if self._entries.get(ch) is entry:  # else removed, which sent it, or cleared
            self._send(ch, entry)

    def _send(self, ch: str, entry: _Entry) -> None:
        entry.due = self._clock() + self.coalesce_s
        if self._hub is not None:
            self._hub.publish(ch, entry.payload, wake=True)

    def _arm_sweep(self) -> None:
        if self._sweep_timer is None and self._terminal and self._call_later is not None:
            delay = next(iter(self._terminal.values())).expires - self._clock()
            self._sweep_timer = self._call_later(max(0.0, delay), self._swept)

    def _swept(self) -> None:
        self._sweep_timer = None
        self.sweep()

    def _remove(self, ch: str, entry: _Entry) -> None:
        """Send what waits for its window, drop the entry, then revoke each live subscription
        (§6.4; no tombstone: a later `sub` is an unknown entity's) and report their frames."""
        if entry.timer is not None:
            entry.timer.cancel()
            entry.timer = None
            self._send(ch, entry)
        del self._entries[ch]
        self._terminal.pop(ch, None)
        if self._hub is not None:
            unscoped = MACHINE_KINDS[entry.kind].scope == Scope.NONE  # a fresh `sub` is pending
            revoked = self._hub.revoke_topic(
                ch, "topic_removed", resubscribe=unscoped, now_ms=self._wall_ms()
            )
            if revoked and self.on_revoked is not None:
                self.on_revoked(revoked)

    def _note(self, level: Literal["error", "warning"], event: str, kind: str, **kw: str) -> None:
        """Log `event` for `kind` unless it was logged in the last `LOG_INTERVAL_S`: a producer
        stuck on a defect never floods the sink (C-2.18). Names only, never an id (C-12.6)."""
        now, key = self._clock(), (event, kind)
        last = self._logged.get(key)
        if last is not None and now - last < LOG_INTERVAL_S:
            return
        self._logged[key] = now
        getattr(_log(), level)(event, entity_kind=kind, **kw)

    # -- SnapshotSource --

    def build(self, sub: Subscription) -> SnapshotBody | None:
        entry = self._entries.get(sub.ch)
        return None if entry is None else SnapshotBody(entry.payload)

    def generation(self, sub: Subscription) -> int:
        return 0  # a private family's snapshot is never cached (SR-190)

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False  # no per-entity history: `snapshot: false` is always `snapshot_forced`
