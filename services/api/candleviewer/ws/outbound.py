"""Bounded outbound budget and the overflow ladder (E17-T03, `23-ws-protocol.md` §8.4).

`OutboundQueue` holds one connection's encoded frames on two lanes. The priority lane carries
`orders`, `executions`, `system` and ping / pong: never dropped, always drained first. The normal
lane carries everything else, in order. Every frame is counted at its exact encoded length, so
the budget, `max_bytes` (8 MiB) or `max_frames` (2 000) whichever binds first, is real. Only
market-data frames (`d` / `snap` of a throttled topic) can be dropped; control frames never are.

`Backpressure` runs the §8.4 ladder against that budget plus the pacer's pending state:

1. drop the queued frames and pending state of every throttled topic that holds any, and mark it
   `resnapshot_required` (its deltas are held until then);
2. once the queue has drained below 50 %, send one `snap` with reason `backpressure` per marked
   topic, one at a time while the queue stays below 50 %;
3. if the queue is still over budget after the drop because `orders` / `executions` frames
   cannot be dropped, close the connection as a slow consumer, naming the topics that were the
   most expensive when the overflow began.

Every step comes back as a `LadderEvent`; the caller records step 4 (`cv_ws_overflow_total`, and
the warning audit entry when step 3 fires) and performs the close.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from candleviewer.ws.pacing import Pacer
from candleviewer.ws.permissions import Subscription

QUEUE_BYTES: Final = 8 * 1024 * 1024
QUEUE_FRAMES: Final = 2000
#: §8.4 step 2: re-snapshots go out only while the queue is below this share of the budget.
DRAIN_PCT: Final = 50.0
#: Topics named in the slow-consumer `bye.hint.most_expensive_topics`.
MOST_EXPENSIVE: Final = 5
#: Families whose frames ride the priority lane, with the ping / pong control frames.
PRIORITY_FAMILIES: Final = frozenset({"orders", "executions", "system"})
_PRIORITY_CONTROL: Final = frozenset({"ping", "pong"})
_DATA_FRAMES: Final = frozenset({"d", "snap"})
#: Families whose frames cannot be dropped (§8.4 step 3, S4).
UNDROPPABLE_FAMILIES: Final = frozenset({"orders", "executions"})


@dataclass(frozen=True, slots=True)
class Queued:
    """One encoded frame. `family` is its topic family (None for a frame without a channel);
    `topic` is set only on a droppable market-data frame."""

    text: str
    priority: bool = False
    family: str | None = None
    topic: str | None = None


def encode(frame: Mapping[str, Any]) -> Queued:
    """Serialise `frame` once, exactly as the writer sends it, and classify it for the lanes."""
    text = json.dumps(frame, separators=(",", ":"))
    ch = frame.get("ch")
    family = ch.split(".", 1)[0] if isinstance(ch, str) else None
    priority = family in PRIORITY_FAMILIES or frame.get("t") in _PRIORITY_CONTROL
    droppable = frame.get("t") in _DATA_FRAMES and family is not None and not priority
    return Queued(text, priority, family, ch if droppable else None)


@dataclass(frozen=True, slots=True)
class LadderEvent:
    """One §8.4 step that fired: `drop`, `resnapshot` or `close`, and the topics it concerned
    (for `close`, the most expensive ones)."""

    action: str
    topics: tuple[str, ...]


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

    def __len__(self) -> int:
        return len(self._priority) + len(self._normal)

    def push(self, frame: Queued) -> None:
        lane = self._priority if frame.priority else self._normal
        lane.append(frame)
        self.bytes += len(frame.text)
        if frame.topic is not None:
            self._topic_bytes[frame.topic] = self._topic_bytes.get(frame.topic, 0) + len(frame.text)
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

    def pct(self, pending_bytes: int = 0) -> float:
        """Depth as a share of the budget: the larger of the byte and frame fractions (§8.3)."""
        by_bytes = (self.bytes + pending_bytes) / self.max_bytes
        return 100 * max(by_bytes, len(self) / self.max_frames)

    def over_budget(self, pending_bytes: int = 0) -> bool:
        return self.bytes + pending_bytes > self.max_bytes or len(self) > self.max_frames

    def topics(self) -> frozenset[str]:
        """Topics with droppable frames queued."""
        return frozenset(self._topic_bytes)

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

    def most_expensive(self, n: int = MOST_EXPENSIVE) -> list[str]:
        """The `n` topics with the most queued bytes, largest first."""
        ranked = sorted(self._topic_bytes.items(), key=lambda item: (-item[1], item[0]))
        return [topic for topic, _ in ranked[:n]]

    def holds_undroppable(self) -> bool:
        """True while `orders` / `executions` frames wait in the queue."""
        return any(frame.family in UNDROPPABLE_FAMILIES for frame in self._priority)


class Backpressure:
    """The §8.4 ladder for one connection: `check` after anything grows the queue or the pacer's
    pending state, `drain` after the writer sends."""

    def __init__(self, queue: OutboundQueue, pacer: Pacer) -> None:
        self.queue = queue
        self.pacer = pacer

    def over_budget(self) -> bool:
        return self.queue.over_budget(self.pacer.pending_bytes)

    def check(self, subs: Iterable[Subscription]) -> list[LadderEvent]:
        """Steps 1 and 3, when the connection is over its budget."""
        if not self.over_budget():
            return []
        hint = self.queue.most_expensive()
        queued = self.queue.topics()
        offending = [
            sub
            for sub in subs
            if not sub.topic.family.never_throttled
            and not sub.snapshot_pending
            and (sub.ch in queued or self._pending(sub))
        ]
        for sub in offending:
            self.pacer.drop(sub)
        self.queue.drop({sub.ch for sub in offending})
        events = []
        if offending:
            events.append(LadderEvent("drop", tuple(sorted(sub.ch for sub in offending))))
        if self.over_budget() and self.queue.holds_undroppable():
            events.append(LadderEvent("close", tuple(hint)))
        return events

    def _pending(self, sub: Subscription) -> bool:
        lane = self.pacer.lanes.get(sub.sub_id)
        return lane is not None and lane.queue.pending

    def drain(self) -> list[LadderEvent]:
        """Step 2: below `DRAIN_PCT`, one `backpressure` snap per marked topic, one at a time."""
        sent: list[str] = []
        for sub_id, sub in list(self.pacer.resnapshot_required.items()):
            if self.queue.pct(self.pacer.pending_bytes) >= DRAIN_PCT:
                break
            if self.pacer.emitter.snapshot(sub, "backpressure"):
                del self.pacer.resnapshot_required[sub_id]
                sent.append(sub.ch)
        return [LadderEvent("resnapshot", tuple(sent))] if sent else []
