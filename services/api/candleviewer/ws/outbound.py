"""Bounded outbound budget and the overflow ladder (E17-T03, `23-ws-protocol.md` §8.4).

`OutboundQueue` holds one connection's encoded frames on two lanes. The priority lane carries
`orders`, `executions`, `system` and ping / pong: never dropped, always drained first. The normal
lane carries everything else, in order. Every frame is counted at its exact encoded length, so
the budget, `max_bytes` (8 MiB) or `max_frames` (2 000) whichever binds first, is real. Only
market-data frames (`d` / `snap` of a throttled topic) can be dropped; control frames never are.

`Backpressure` runs the §8.4 ladder against that budget plus the pacer's pending state:

1. drop the queued frames and pending state of every throttled topic that holds any, and mark it
   `resnapshot_required` (its deltas are held until then); queued frames of a topic already
   awaiting its snapshot, or no longer subscribed, are dropped as well, and so is the pacer
   window of a topic awaiting another sender's snapshot (it predates that snapshot);
2. once the queue has drained below 50 %, send one `snap` with reason `backpressure` per marked
   topic, one at a time while the queue stays below 50 %;
3. if the queue is still over budget after the drop, what remains cannot be dropped (`orders` /
   `executions`, control and `system` frames): close the connection as a slow consumer, naming
   the topics that were the most expensive (queued plus pending) when the overflow began. A
   subscription whose `backpressure` snapshot is dropped `MAX_REDROPS` times in a row, each time
   before it was sent (a snapshot larger than the budget), ends in the same close.

Every step counts in `cv_ws_overflow_total{reason}` (step 4, `LadderEvent.reason`) and comes back
as a `LadderEvent`; the caller writes the warning audit entry when step 3 fires (with the close's
`trigger`) and performs the close. A close fires and counts once: `check` and `drain` return
nothing after it, so the `bye` push that runs `check` again is harmless. The bound holds only if
the caller runs `check` after every push and every pacer update; recovery needs `drain` after
every send and after every `check` that dropped. `drain` queues one snapshot per call; a `check`
from its pushes runs once it is whole, its events returned by `drain` (a drop is whole, and a
redrop). `drain` is the only sender of `backpressure` snapshots: the wiring must keep
`TopicEmitter.flush_pending` and `SequencingHub.resnapshot` off them.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Collection, Iterable, Mapping
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
#: Families whose frames ride the priority lane, with the ping / pong control frames.
PRIORITY_FAMILIES: Final = frozenset({"orders", "executions", "system"})
_PRIORITY_CONTROL: Final = frozenset({"ping", "pong"})
_DATA_FRAMES: Final = frozenset({"d", "snap"})


@dataclass(frozen=True, slots=True)
class Queued:
    """One encoded frame. `family` is its topic family (None for a frame without a channel);
    `topic` is set only on a droppable market-data frame; `resnap` marks a frame of a
    `backpressure` snapshot (step 2)."""

    text: str
    priority: bool = False
    family: str | None = None
    topic: str | None = None
    resnap: bool = False


def encode(frame: Mapping[str, Any]) -> Queued:
    """Serialise `frame` once, exactly as the writer sends it, and classify it for the lanes.
    ASCII-only output makes `len(text)` the byte count; a NaN or infinity raises `ValueError`
    rather than leave as invalid JSON."""
    text = json.dumps(frame, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    ch, kind, meta = frame.get("ch"), frame.get("t"), frame.get("meta")
    family = ch.split(".", 1)[0] if isinstance(ch, str) else None
    priority = family in PRIORITY_FAMILIES or kind in _PRIORITY_CONTROL
    droppable = kind in _DATA_FRAMES and family is not None and not priority
    resnap = (
        droppable
        and kind == "snap"
        and isinstance(meta, Mapping)
        and meta.get("reason") == "backpressure"
    )
    return Queued(text, priority, family, ch if droppable else None, resnap)


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
        self._topic_bytes: dict[str, int] = {}
        #: Queued `backpressure` snapshot frames (every chunk) per topic.
        self._resnaps: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._priority) + len(self._normal)

    def push(self, frame: Queued) -> None:
        lane = self._priority if frame.priority else self._normal
        lane.append(frame)
        self.bytes += len(frame.text)
        if frame.topic is not None:
            self._topic_bytes[frame.topic] = self._topic_bytes.get(frame.topic, 0) + len(frame.text)
            if frame.resnap:
                self._resnaps[frame.topic] = self._resnaps.get(frame.topic, 0) + 1
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
        self.bytes -= len(frame.text)
        if frame.topic is not None:
            left = self._topic_bytes[frame.topic] - len(frame.text)
            if left:
                self._topic_bytes[frame.topic] = left
            else:
                del self._topic_bytes[frame.topic]
            if frame.resnap:
                if self._resnaps[frame.topic] > 1:
                    self._resnaps[frame.topic] -= 1
                else:
                    del self._resnaps[frame.topic]

    def pct(self, pending_bytes: int = 0) -> float:
        """Depth as a share of the budget: the larger of the byte and frame fractions (§8.3)."""
        by_bytes = (self.bytes + pending_bytes) / self.max_bytes
        return 100 * max(by_bytes, len(self) / self.max_frames)

    def over_budget(self, pending_bytes: int = 0) -> bool:
        return self.bytes + pending_bytes > self.max_bytes or len(self) > self.max_frames

    def resnap_queued(self, topic: str) -> bool:
        """Whether any frame of a `backpressure` snapshot of `topic` is still waiting."""
        return topic in self._resnaps

    def topic_bytes(self) -> dict[str, int]:
        """Queued bytes of every topic with droppable frames."""
        return dict(self._topic_bytes)

    def drop(self, topics: Collection[str]) -> int:
        """Remove the droppable frames of `topics`; returns how many were dropped."""
        kept: deque[Queued] = deque()
        dropped = 0
        for frame in self._normal:
            if frame.topic is not None and frame.topic in topics:
                self._forget(frame)
                dropped += 1
            else:
                kept.append(frame)
        self._normal = kept
        if not self:
            self.ready.clear()
        return dropped


class Backpressure:
    """The §8.4 ladder for one connection: `check` after anything grows the queue or the pacer's
    pending state, `drain` after the writer sends and after a `check` that dropped."""

    def __init__(self, queue: OutboundQueue, pacer: Pacer) -> None:
        self.queue = queue
        self.pacer = pacer
        #: Subscriptions (id -> topic) whose `backpressure` snapshot may still be queued.
        #: Frames are kept per topic, so two subscriptions of one topic (live beside replay)
        #: settle together.
        self._snapped: dict[str, str] = {}
        #: Consecutive drops that found a subscription's `backpressure` snapshot unsent.
        self._redrops: dict[str, int] = {}
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
        queued = self.queue.topic_bytes().keys()
        offending = [
            sub
            for sub in subs
            if not sub.topic.family.never_throttled
            and not sub.snapshot_pending
            and (sub.ch in queued or self._pending(sub))
        ]
        for sub in offending:
            self.pacer.drop(sub)
        live = {sub.ch for sub in subs if not sub.snapshot_pending}
        # Frames of a topic awaiting another snapshot, or no longer subscribed, go too. That
        # drop is not a redrop: `_settle` forgets its record and the count starts afresh.
        self.queue.drop(
            {topic for topic in queued if topic not in live} | {s.ch for s in offending}
        )
        for sub in subs:
            self.pacer.shed(sub)  # a window that predates another sender's pending `snap`
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
        """Topics by queued plus pending bytes, largest first (`bye.hint`)."""
        costs = self.queue.topic_bytes()
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
        for sub_id, topic in list(self._snapped.items()):
            if not self.queue.resnap_queued(topic):
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

    def drain(self) -> list[LadderEvent]:
        """Step 2: below `DRAIN_PCT`, one `backpressure` snap per call (module docstring)."""
        if self._closed:
            return []
        self._settle()  # before a new snapshot replaces the record of a sent one
        sent: list[str] = []
        held: list[LadderEvent] = []
        for sub_id, sub in list(self.pacer.resnapshot_required.items()):
            if self.queue.pct(self.pacer.pending_bytes) >= DRAIN_PCT:
                break
            self._draining = True
            try:
                queued = self.pacer.emitter.snapshot(sub, "backpressure")
            finally:
                self._draining = False
            if queued:
                del self.pacer.resnapshot_required[sub_id]
                self._snapped[sub_id] = sub.ch  # before the held check, so a drop is a redrop
                sent.append(sub.ch)
            deferred, self._deferred = self._deferred, None
            if deferred is not None:
                held += self.check(deferred)
            if queued:
                break
        return _record([LadderEvent("resnapshot", tuple(sent))] if sent else []) + held
