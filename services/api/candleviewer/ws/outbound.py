"""Bounded outbound budget and the overflow ladder (E17-T03, `23-ws-protocol.md` §8.4).

`OutboundQueue` holds one connection's encoded frames on two lanes. The priority lane carries
every control frame and `orders`, `executions`, `system` (D1): never dropped, sent first. The normal
lane carries everything else, in order. Every frame is encoded once, in the connection's
subprotocol (`encode`: MessagePack bytes, or JSON text that refuses a non-finite number), and
counted at that exact length, so the budget, `max_bytes` (8 MiB) or `max_frames` (2 000) whichever
binds first, is what the socket is sent. Only a `d` or `snap` of a throttled topic (any family
outside `PRIORITY_FAMILIES`) can be dropped; control frames never are. Data frames are keyed by
subscription, `(ch, replay session)`, so a drop never touches the live and the replay subscription
of one `ch` together.

`Backpressure` runs the §8.4 ladder against that budget plus the pacer's pending state:

1. drop the queued frames and pending state of every throttled topic that holds any, and mark it
   `resnapshot_required` (its deltas are held until then); queued frames of a topic already
   awaiting its snapshot, or no longer subscribed, are dropped as well, and so is the pacer
   window of a topic awaiting another sender's snapshot (it predates that snapshot); a paused
   topic is shed the same way, without the mark: its resume re-snapshots it (D16);
2. once the queue has drained below 50 %, send one `snap` with reason `backpressure` per marked
   topic, one at a time while the queue stays below 50 %;
3. if the queue is still over budget after the drop, what remains cannot be dropped (`orders` /
   `executions`, control and `system` frames): close the connection as a slow consumer, naming
   the topics that were the most expensive (queued plus pending) when the overflow began. A
   subscription whose `backpressure` snapshot is dropped `MAX_REDROPS` times in a row, each time
   before it was sent (a snapshot larger than the budget), ends in the same close.

Every step counts in `cv_ws_overflow_total{reason}` (step 4, `LadderEvent.reason`) and comes back
as a `LadderEvent`; the caller writes the warning audit entry when step 3 fires (with the close's
`trigger`) and performs the close. A close fires and counts once, and `check` and `drain` return
nothing after it: the caller must close at once and feed nothing after it but the `bye` (no push,
no `Pacer.offer` or `tick`), or the 8 MiB bound is gone. Otherwise the bound holds only if the
caller runs `check` after every push and every pacer update; recovery needs `drain` after every
send and after every `check` that dropped. `drain` queues one snapshot per call; a `check` from its
pushes runs once it is whole, its events returned by `drain` (a drop is whole, and a redrop).
`drain` is the only sender of `backpressure` snapshots: the wiring must keep
`TopicEmitter.flush_pending` and `SequencingHub.resnapshot` off them. It deletes, unsent, an entry
that no longer awaits that snapshot or (given the connection's subscriptions) is no longer
subscribed, and keeps a paused one, unsent, for its resume (§5.4). A snapshot that does not queue
(not ready, failed, or re-marked by its own pushes: §10.1) is parked, so `drain` tries one
snapshot per call and skips a parked one until `unpark` (its source rebuilt) or the coarse
timer's `retry` pass, which tries them in turn and ends at the first that does not queue.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from candleviewer.ws.metrics import cv_ws_overflow_total
from candleviewer.ws.pacing import Pacer
from candleviewer.ws.permissions import Subscription

QUEUE_BYTES: Final = 8 * 1024 * 1024
QUEUE_FRAMES: Final = 2000
#: §8.4 step 2: re-snapshots go out only while the queue is below this share of the budget.
DRAIN_PCT: Final = 50.0
#: Topics named in the slow-consumer `bye.hint.most_expensive_topics`.
MOST_EXPENSIVE: Final = 5
#: Consecutive drops of a subscription's unsent `backpressure` snapshot before the close.
MAX_REDROPS: Final = 3
#: The families whose `d` / `snap` frames ride the priority lane, with every control frame (D1).
PRIORITY_FAMILIES: Final = frozenset({"orders", "executions", "system"})
_DATA_FRAMES: Final = frozenset({"d", "snap"})

#: A subscription's frames: `(ch, replay_session_id)` (D13).
Key = tuple[str, str | None]
#: One frame, serialised as the socket is sent it: JSON text or MessagePack bytes.
FrameEncoder = Callable[[Mapping[str, Any]], str | bytes]


def json_payload(frame: Mapping[str, Any]) -> str:
    """`cv.v1.json`: the writer's serialisation, ASCII-only, so `len` is the byte count. A NaN or
    infinity raises `ValueError` rather than leave as invalid JSON."""
    return json.dumps(frame, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True, slots=True)
class Queued:
    """One encoded frame: `payload` is exactly what the writer sends. `family` is its topic
    family (None for a frame without a channel); `key` is set on every `d` / `snap` with a
    channel, whichever lane it rides; `resnap` marks a frame of a `backpressure` snapshot (step
    2); `received` is the fan-out stamp of a sampled data frame (`cv_ws_fanout_seconds`)."""

    payload: str | bytes
    priority: bool = False
    family: str | None = None
    key: Key | None = None
    resnap: bool = False
    received: float | None = None

    @property
    def size(self) -> int:
        """Wire bytes: `len` of the bytes, or of the JSON text, which is ASCII-only."""
        return len(self.payload)

    @property
    def droppable(self) -> bool:
        """A `d` or `snap` of a throttled topic (any family outside `PRIORITY_FAMILIES`): the
        only kind step 1 drops."""
        return self.key is not None and not self.priority


@dataclass(frozen=True, slots=True, kw_only=True)
class Spanned(Queued):
    """A sampled frame that carries a span id (23 §3.1): its `sp` and its sequence number `s`, which
    the writer's span record names. Only such a frame is built as one, so every other `Queued`,
    the 31 of 32 that are unsampled included, has neither field and costs what it did."""

    sp: str
    s: int | None


def encode(
    frame: Mapping[str, Any], dumps: FrameEncoder = json_payload, *, received: float | None = None
) -> Queued:
    """Serialise `frame` once with the connection's `dumps`, exactly as the writer sends it, and
    classify it for the lanes; a sampled frame that carries `sp` comes back as a `Spanned`. Raises
    what `dumps` raises."""
    payload = dumps(frame)
    ch, kind, meta, rs = frame.get("ch"), frame.get("t"), frame.get("meta"), frame.get("rs")
    family = ch.split(".", 1)[0] if isinstance(ch, str) else None
    key = None
    if kind in _DATA_FRAMES and isinstance(ch, str):
        key = (ch, rs if isinstance(rs, str) else None)
    priority = key is None or family in PRIORITY_FAMILIES  # D1: all but what step 1 may drop
    resnap = (
        not priority
        and kind == "snap"
        and isinstance(meta, Mapping)
        and meta.get("reason") == "backpressure"
    )
    if received is not None and (sp := frame.get("sp")) is not None:  # 23 §3.1
        return Spanned(payload, priority, family, key, resnap, received, sp=sp, s=frame.get("s"))
    return Queued(payload, priority, family, key, resnap, received)


@dataclass(frozen=True, slots=True)
class LadderEvent:
    """One §8.4 step that fired: `drop`, `resnapshot` or `close`, and the topics it concerned
    (for `close`, the most expensive ones). A `close` names its step-3 `trigger`: `budget` (still
    over budget after the drop) or `redrop` (`MAX_REDROPS`), for the metric label and the audit
    entry."""

    action: str
    topics: tuple[str, ...]
    trigger: str | None = None

    @property
    def reason(self) -> str:
        """The `cv_ws_overflow_total{reason}` label: `drop`, `resnapshot`, `close_budget` or
        `close_redrop` (§8.4 step 4)."""
        return self.action if self.trigger is None else f"{self.action}_{self.trigger}"


def _record(events: list[LadderEvent]) -> list[LadderEvent]:
    """Step 4: one count per topic dropped or re-snapshotted, one per close."""
    for event in events:
        n = 1 if event.action == "close" else len(event.topics)
        cv_ws_overflow_total.labels(reason=event.reason).inc(n)
    return events


class OutboundQueue:
    """One connection's encoded frames, accounted in bytes and frames (§8.4)."""

    def __init__(self, max_bytes: int = QUEUE_BYTES, max_frames: int = QUEUE_FRAMES) -> None:
        self.max_bytes = max_bytes
        self.max_frames = max_frames
        self.bytes = 0
        #: Set while a frame is waiting; the writer awaits it.
        self.ready = asyncio.Event()
        self._priority: deque[Queued] = deque()
        self._normal: deque[Queued] = deque()
        #: Queued bytes of each key's droppable frames: the ladder's costs.
        self._key_bytes: dict[Key, int] = {}
        #: Queued `backpressure` snapshot frames (every chunk) per key.
        self._resnaps: dict[Key, int] = {}

    def __len__(self) -> int:
        return len(self._priority) + len(self._normal)

    def push(self, frame: Queued) -> None:
        lane = self._priority if frame.priority else self._normal
        lane.append(frame)
        self.bytes += frame.size
        key = frame.key
        if key is not None and not frame.priority:  # droppable
            self._key_bytes[key] = self._key_bytes.get(key, 0) + frame.size
            if frame.resnap:
                self._resnaps[key] = self._resnaps.get(key, 0) + 1
        self.ready.set()

    def pop(self) -> Queued | None:
        """The next frame to send, priority lane first; None when empty."""
        lane = self._priority or self._normal
        if not lane:
            return None
        frame = lane.popleft()
        self._forget(frame)
        if not self:
            self.ready.clear()
        return frame

    def _forget(self, frame: Queued) -> None:
        self.bytes -= frame.size
        key = frame.key
        if key is not None and not frame.priority:  # droppable
            left = self._key_bytes[key] - frame.size
            if left:
                self._key_bytes[key] = left
            else:
                del self._key_bytes[key]
            if frame.resnap:
                if self._resnaps[key] > 1:
                    self._resnaps[key] -= 1
                else:
                    del self._resnaps[key]

    def pct(self, pending_bytes: int = 0) -> float:
        """Depth as a share of the budget: the larger of the byte and frame fractions (§8.3)."""
        by_bytes = (self.bytes + pending_bytes) / self.max_bytes
        return 100 * max(by_bytes, len(self) / self.max_frames)

    def over_budget(self, pending_bytes: int = 0) -> bool:
        return self.bytes + pending_bytes > self.max_bytes or len(self) > self.max_frames

    def resnap_queued(self, key: Key) -> bool:
        """Whether any frame of a `backpressure` snapshot of `key` is still waiting."""
        return key in self._resnaps

    def key_bytes(self) -> dict[Key, int]:
        """Queued bytes of every key with droppable frames."""
        return dict(self._key_bytes)

    def drop(self, keys: Collection[Key]) -> int:
        """Remove the droppable frames of `keys` (the normal lane only); returns how many were
        dropped."""
        if not any(key in self._key_bytes for key in keys):
            return 0
        kept: deque[Queued] = deque()
        dropped = 0
        for frame in self._normal:
            if frame.droppable and frame.key in keys:
                self._forget(frame)
                dropped += 1
            else:
                kept.append(frame)
        self._normal = kept
        if not self:
            self.ready.clear()
        return dropped

    def clear(self, *, normal_only: bool = False) -> int:
        """Discard the normal lane, and the priority lane unless `normal_only` (a close, §8.4);
        returns how many frames went. The accounting is exact afterwards."""
        dropped = len(self._normal)
        self._normal.clear()
        self._key_bytes.clear()  # droppable frames ride the normal lane only
        self._resnaps.clear()
        if not normal_only:
            dropped += len(self._priority)
            self._priority.clear()
        self.bytes = sum(frame.size for frame in self._priority)
        if not self:
            self.ready.clear()
        return dropped

    def wake(self) -> None:
        """Set `ready` with nothing queued: the writer has something to do (a close)."""
        self.ready.set()


class Backpressure:
    """The §8.4 ladder for one connection: `check` after anything grows the queue or the pacer's
    pending state, `drain` after the writer sends and after a `check` that dropped."""

    def __init__(
        self,
        queue: OutboundQueue,
        pacer: Pacer,
        snapshot: Callable[[Subscription], bool] | None = None,
    ) -> None:
        self.queue = queue
        self.pacer = pacer
        #: Queues one `backpressure` snapshot, True when it did; the wiring passes one that
        #: contains the emitter's failures (a failure then reads as not queued).
        self._snapshot = snapshot or (lambda sub: pacer.emitter.snapshot(sub, "backpressure"))
        #: Subscriptions (id -> key) whose `backpressure` snapshot may still be queued.
        self._snapped: dict[str, Key] = {}
        #: Consecutive drops that found a subscription's `backpressure` snapshot unsent.
        self._redrops: dict[str, int] = {}
        #: Marked subscriptions whose snapshot did not queue: `drain` skips them until `unpark`,
        #: or tries them in turn while the coarse timer's pass (`retry`) is open.
        self._parked: set[str] = set()
        self._retrying = False
        #: While `drain` queues a snapshot, a `check` from its pushes is held here (module doc).
        self._draining = False
        self._deferred: list[Subscription] | None = None
        #: Step 3 fired: the connection is going away, so nothing fires (or counts) again.
        self._closed = False

    def over_budget(self) -> bool:
        return self.queue.over_budget(self.pacer.pending_bytes)

    def check(self, subs: Iterable[Subscription]) -> list[LadderEvent]:
        """Steps 1 and 3, when the connection is over its budget. `subs` is the connection's full
        subscription set."""
        if self._draining:
            self._deferred = list(subs)
            return []
        if self._closed or not self.over_budget():
            return []
        subs = list(subs)
        self._settle()
        current = {sub.sub_id for sub in subs}  # forget the subscriptions that ended
        for sub_id in [s for s in self._redrops if s not in current]:
            del self._redrops[sub_id]
        for sub_id in [s for s in self._snapped if s not in current]:
            del self._snapped[sub_id]
        hint = self._most_expensive(subs)
        queued = self.queue.key_bytes().keys()
        offending = [
            sub
            for sub in subs
            if not sub.topic.family.never_throttled
            and not sub.snapshot_pending
            and not _paused(sub)
            and (_key(sub) in queued or self._pending(sub))
        ]
        for sub in offending:
            self.pacer.drop(sub)
        live = {_key(sub) for sub in subs if not sub.snapshot_pending and not _paused(sub)}
        # Frames of a topic awaiting another snapshot, paused (D16: no mark, its resume
        # re-snapshots it), or no longer subscribed, go too. That drop is not a redrop:
        # `_settle` forgets its record and the count starts afresh.
        self.queue.drop({key for key in queued if key not in live} | {_key(s) for s in offending})
        for sub in subs:
            self.pacer.shed(sub)  # a window that predates a pending `snap`, or a paused one
        events = []
        if offending:
            events.append(LadderEvent("drop", tuple(sorted(sub.ch for sub in offending))))
        if self.over_budget():
            events.append(LadderEvent("close", hint, "budget"))
        elif self._looping(offending):
            events.append(LadderEvent("close", hint, "redrop"))
        self._closed = any(event.action == "close" for event in events)
        return _record(events)

    def _pending(self, sub: Subscription) -> bool:
        lane = self.pacer.lanes.get(sub.sub_id)
        return lane is not None and lane.queue.pending

    def _most_expensive(self, subs: list[Subscription]) -> tuple[str, ...]:
        """Topics by queued plus pending bytes, largest first (`bye.hint`): a live and a replay
        subscription of one topic count together."""
        costs: dict[str, int] = {}
        for (ch, _), size in self.queue.key_bytes().items():
            costs[ch] = costs.get(ch, 0) + size
        for sub in subs:
            lane = self.pacer.lanes.get(sub.sub_id)
            if lane is not None and lane.queue.pending_bytes:
                costs[sub.ch] = costs.get(sub.ch, 0) + lane.queue.pending_bytes
        ranked = sorted(costs.items(), key=lambda item: (-item[1], item[0]))
        return tuple(topic for topic, _ in ranked[:MOST_EXPENSIVE])

    def _settle(self) -> None:
        """Forget each recorded `backpressure` snapshot that is no longer queued: the writer sent
        it (or its subscription was re-pended or ended), so that subscription's count starts
        afresh. A ladder drop of a queued one is counted by `_looping`, which removes the record
        first."""
        for sub_id, key in list(self._snapped.items()):
            if not self.queue.resnap_queued(key):
                del self._snapped[sub_id]
                self._redrops.pop(sub_id, None)

    def _looping(self, dropped: Iterable[Subscription]) -> bool:
        """Count each drop that removed a subscription's unsent `backpressure` snapshot (after
        `_settle`, every one still recorded is queued); True at `MAX_REDROPS`."""
        looping = False
        for sub in dropped:
            if self._snapped.pop(sub.sub_id, None) is not None:
                self._redrops[sub.sub_id] = self._redrops.get(sub.sub_id, 0) + 1
                looping = looping or self._redrops[sub.sub_id] >= MAX_REDROPS
        return looping

    def drain(self, live: Mapping[str, Subscription] | None = None) -> list[LadderEvent]:
        """Step 2: below `DRAIN_PCT`, one `backpressure` snap per call (module docstring). `live`
        is the connection's subscriptions by id: an entry not among them is deleted unsent."""
        if self._closed or self._draining:  # #2998: never re-entered from a snapshot's push
            return []
        self._settle()  # before a new snapshot replaces the record of a sent one
        sent: list[str] = []
        held: list[LadderEvent] = []
        required = self.pacer.resnapshot_required
        for sub_id, sub in list(required.items()):
            if not _awaits(sub) or (live is not None and live.get(sub_id) is not sub):
                del required[sub_id]  # resnapshotted by another path, or ended: never sent
                self._parked.discard(sub_id)
                continue
            if _paused(sub) or (sub_id in self._parked and not self._retrying):
                continue  # paused: no `s` until its resume (§5.4); parked: until a retry
            if self.queue.pct(self.pacer.pending_bytes) >= DRAIN_PCT:
                break
            self._parked.discard(sub_id)  # parked again below if it does not queue
            self._draining = True
            try:
                queued = self._snapshot(sub)
            finally:  # #2998: a snapshot that raises leaves no held check behind
                self._draining = False
                deferred, self._deferred = self._deferred, None
            if queued and not _awaits(sub):  # its own pushes may have re-marked it (§10.1)
                del required[sub_id]
                self._snapped[sub_id] = _key(sub)  # before the held check: a drop is a redrop
                sent.append(sub.ch)
            else:  # not ready, failed or re-marked: parked behind the others, so none starves
                required[sub_id] = required.pop(sub_id)
                self._parked.add(sub_id)
                self._retrying = False  # the timer's pass ends at its first failure
            if deferred is not None:
                held += self.check(deferred)
            break  # one snapshot per call, queued or not
        return _record([LadderEvent("resnapshot", tuple(sent))] if sent else []) + held

    def retry(self) -> None:
        """The coarse timer: a pass over the parked snapshots, which `drain` tries in turn, one per
        call, until the first that does not queue; the rest wait for the next pass."""
        self._retrying = True

    def unpark(self, sub_ids: Iterable[str]) -> bool:
        """Let `drain` retry the parked snapshots of `sub_ids` (their source rebuilt); True when
        one was parked."""
        before = len(self._parked)
        self._parked.difference_update(sub_ids)
        return len(self._parked) < before


def _awaits(sub: Subscription) -> bool:
    """Still marked for its `backpressure` snapshot (`Pacer.drop`)."""
    return sub.snapshot_pending and sub.pending_reason == "backpressure"


def _paused(sub: Subscription) -> bool:
    return sub.effective.get("paused") is True


def _key(sub: Subscription) -> Key:
    return (sub.ch, sub.replay_session_id)
