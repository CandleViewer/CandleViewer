"""Per-connection throttling and adaptive classification (E17-T03, `23-ws-protocol.md` §8.1,
§8.3, §9.1).

`Pacer` sits between `SequencingHub.publish` and one connection's `TopicEmitter`. Each update of a
throttled topic lands in that subscription's `CoalescingQueue`, and at most one window per
effective `throttle_ms` leaves through `TopicEmitter.delta`, so a coalesced frame still consumes
exactly one sequence number. The first update after a quiet window leaves at once; later ones
leave when the window closes (`tick`). `orders` and `executions` bypass the pacer, frame by frame
(S4). A queue that refuses an update is dropped and its topic marked for a `backpressure` snapshot
(§8.4 step 1); the outbound budget decides when that snapshot may go (step 2). A full queue, or an
update its merge cannot represent (footprint bars sharing an open time, #2529), counts as
`cv_ws_overflow_total{reason="drop"}`; a malformed update is a producer bug, counted in
`cv_ws_malformed_updates_total` and logged (family and topic only), never as an overflow.

`Classifier` turns the outbound queue depth and the RTT (`RttProbe`, §9.1) into a class every
`CLASSIFY_INTERVAL_S`: a class worsens at once and improves only after two consecutive better
samples. `Pacer.apply` enforces it: `lagging` doubles throttles and forces coalescing; `saturated`
and `overflowing` quadruple them and hold `heatmap` and `profile` to at most one frame a second.

Plain synchronous code on the hot path (C-2.20). There is one clock domain, the emitter's
monotonic `TopicEmitter.clock`: `offer` reads it, and `tick`, `classify` and `apply` default `now`
to it (a caller passing `now` must take it from that clock).
"""

from __future__ import annotations

import math
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import structlog

from candleviewer.ws.binary import Frame
from candleviewer.ws.coalescing import CoalescingQueue
from candleviewer.ws.metrics import cv_ws_malformed_updates_total, cv_ws_overflow_total
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import TopicEmitter

CLASSIFY_INTERVAL_S: Final = 2.0
LAGGING_QUEUE_PCT: Final = 25.0
SATURATED_QUEUE_PCT: Final = 60.0
OVERFLOWING_QUEUE_PCT: Final = 90.0
LAGGING_RTT_MS: Final = 150.0
SATURATED_RTT_MS: Final = 500.0
#: Consecutive better samples before a class may improve.
IMPROVE_AFTER: Final = 2
#: §8.3 `saturated`: these families drop to at most one frame per `DEGRADED_THROTTLE_MS`.
DEGRADED_FAMILIES: Final = frozenset({"heatmap", "profile"})
DEGRADED_THROTTLE_MS: Final = 1000
RTT_PROBE_PREFIX: Final = "s-rtt-"
#: §9.1: a server `ping` is answered within 10 s; a probe left unanswered that long is retired.
PONG_TIMEOUT_S: Final = 10.0


class ConnectionClass(StrEnum):
    """§8.3 classes, best first."""

    HEALTHY = "healthy"
    LAGGING = "lagging"
    SATURATED = "saturated"
    OVERFLOWING = "overflowing"


_ORDER: Final = tuple(ConnectionClass)
_MULTIPLIER: Final = {
    ConnectionClass.HEALTHY: 1,
    ConnectionClass.LAGGING: 2,
    ConnectionClass.SATURATED: 4,
    ConnectionClass.OVERFLOWING: 4,
}


def _rank(cls: ConnectionClass) -> int:
    return _ORDER.index(cls)


def classify(queue_pct: float, rtt_ms: float | None) -> ConnectionClass:
    """The §8.3 table: the worse of what the queue depth and the RTT say."""
    rtt = 0.0 if rtt_ms is None else rtt_ms
    if queue_pct > OVERFLOWING_QUEUE_PCT:
        return ConnectionClass.OVERFLOWING
    if queue_pct >= SATURATED_QUEUE_PCT or rtt > SATURATED_RTT_MS:
        return ConnectionClass.SATURATED
    if queue_pct >= LAGGING_QUEUE_PCT or rtt >= LAGGING_RTT_MS:
        return ConnectionClass.LAGGING
    return ConnectionClass.HEALTHY


class Classifier:
    """Hysteresis over `classify` samples: worse at once; better only after `IMPROVE_AFTER`
    consecutive better samples, and then to the worst of them, so throttles and notices never
    flap."""

    def __init__(self) -> None:
        self.current = ConnectionClass.HEALTHY
        self._better: list[ConnectionClass] = []

    def observe(self, sample: ConnectionClass) -> bool:
        """Feed one sample; True when `current` changed."""
        if _rank(sample) > _rank(self.current):
            self.current, self._better = sample, []
            return True
        if sample is self.current:
            self._better = []
            return False
        self._better.append(sample)
        if len(self._better) < IMPROVE_AFTER:
            return False
        self.current, self._better = max(self._better, key=_rank), []
        return True


class RttProbe:
    """§9.1 RTT sampling: one server `ping` outstanding at a time, at most one per `interval_s`.
    While a probe is unanswered its age counts as the RTT, so a socket that stopped draining reads
    as slow at once rather than when (if ever) the `pong` arrives. After `PONG_TIMEOUT_S` the
    probe is retired: its age becomes one sample and a fresh probe follows, so one lost `pong`
    cannot hold the connection `saturated`."""

    def __init__(self, interval_s: float = CLASSIFY_INTERVAL_S, nonce: str | None = None) -> None:
        self.interval_s = interval_s
        #: Unpredictable per connection, so a client cannot answer a probe before it is sent.
        self.prefix = f"{RTT_PROBE_PREFIX}{secrets.token_hex(4) if nonce is None else nonce}-"
        self.sample_ms: float | None = None
        self._sent = 0
        self._outstanding: tuple[str, float] | None = None
        self._last_sent = -math.inf

    def ping_id(self, now: float) -> str | None:
        """The id of the probe to send now, or None when one is outstanding or not yet due."""
        self._retire(now)
        if self._outstanding is not None or now - self._last_sent < self.interval_s:
            return None
        self._sent += 1
        probe = f"{self.prefix}{self._sent}"
        self._outstanding, self._last_sent = (probe, now), now
        return probe

    def pong(self, probe: str, now: float) -> bool:
        """Record the answer to `probe`; False for any other id (a heartbeat `pong`, an answered
        or retired probe's): one comparison, no state kept for it."""
        self._retire(now)
        if self._outstanding is None or self._outstanding[0] != probe:
            return False
        self.sample_ms = (now - self._outstanding[1]) * 1000
        self._outstanding = None
        return True

    def rtt_ms(self, now: float) -> float | None:
        self._retire(now)
        if self._outstanding is None:
            return self.sample_ms
        age = (now - self._outstanding[1]) * 1000
        return age if self.sample_ms is None else max(self.sample_ms, age)

    def _retire(self, now: float) -> None:
        if self._outstanding is not None and now - self._outstanding[1] >= PONG_TIMEOUT_S:
            self.sample_ms = (now - self._outstanding[1]) * 1000
            self._outstanding = None


def quality_notice(
    cls: ConnectionClass, queue_pct: float, rtt_ms: float | None, applied: Mapping[str, Any]
) -> dict[str, Any]:
    """The `system` `connection_quality` payload (§8.3, §15.9)."""
    body: dict[str, Any] = {
        "kind": "connection_quality",
        "class": cls.value,
        "queue_pct": round(min(max(queue_pct, 0.0), 100.0)),
        "applied": dict(applied),
    }
    if rtt_ms is not None:
        body["rtt_ms"] = round(rtt_ms)
    return body


@dataclass(slots=True)
class _Lane:
    """One subscription's throttle window. `seq` is the topic's sequence number when the lane last
    emitted or started collecting: if anything else (a snapshot) moved it on, what the lane holds
    predates that and is discarded."""

    sub: Subscription
    queue: CoalescingQueue
    seq: int
    last_emit: float = -math.inf
    due: float | None = None


class Pacer:
    """Throttling and coalescing of one connection's subscriptions (§8.1, §8.3)."""

    def __init__(self, emitter: TopicEmitter) -> None:
        self.emitter = emitter
        self.classifier = Classifier()
        self.probe = RttProbe()
        self.lanes: dict[str, _Lane] = {}
        #: §8.4 step 1: dropped topics awaiting their `backpressure` snapshot, by `sub_id`; the
        #: outbound ladder (`Backpressure.drain`) sends them and removes them.
        self.resnapshot_required: dict[str, Subscription] = {}

    @property
    def cls(self) -> ConnectionClass:
        return self.classifier.current

    @property
    def pending_bytes(self) -> int:
        """Estimated size of every lane's pending state, for the connection budget (§8.4)."""
        return sum(lane.queue.pending_bytes for lane in self.lanes.values())

    def offer(
        self,
        sub: Subscription,
        body: Mapping[str, Any],
        *,
        part: Frame | None = None,
        ts_ms: int | None = None,
    ) -> bool:
        """Route one source update of `sub`; True when it was emitted or queued. A throttled
        topic needs the structured `body`; the CVWB `part` is optional."""
        if sub.topic.family.never_throttled:
            return self.emitter.delta(sub, body, part=part, ts_ms=ts_ms)
        if _held(sub):
            lane = self.lanes.get(sub.sub_id)
            if lane is not None and lane.queue.pending:
                self._restart(lane)  # stale: the pending `snap` carries this state
            return False
        lane = self.lanes.get(sub.sub_id)
        if lane is None:
            lane = self.lanes[sub.sub_id] = _Lane(sub, _queue(sub), sub.seq)
        elif lane.seq != sub.seq:
            self._restart(lane)  # a snapshot went out since: what the lane holds is stale
        lane.queue.set_coalesce(self._coalesce(sub))
        if not lane.queue.offer(body, part, ts_ms=ts_ms):
            self._refused(lane)
            return False
        now = self.emitter.clock()
        if lane.due is None:
            lane.due = max(now, lane.last_emit + self.throttle_ms(sub) / 1000)
        if now >= lane.due:
            self._flush(lane, now)
        return True

    def tick(self, now: float | None = None) -> int:
        """Flush every lane whose window has closed; returns the frames emitted."""
        now = self.emitter.clock() if now is None else now
        sent = 0
        for lane in list(self.lanes.values()):
            if lane.due is not None and now >= lane.due:
                sent += self._flush(lane, now)
        return sent

    def next_due(self) -> float | None:
        """When the earliest pending window closes (monotonic seconds), if any."""
        return min((lane.due for lane in self.lanes.values() if lane.due is not None), default=None)

    def _restart(self, lane: _Lane) -> None:
        """A snapshot went out or is pending: a new queue, since the old one's memory across
        windows (the heatmap's sent buckets, keyed by `t_ms` only) predates it (§8.2)."""
        lane.queue = _queue(lane.sub)
        lane.due, lane.seq = None, lane.sub.seq

    def _flush(self, lane: _Lane, now: float) -> int:
        lane.due = None  # first: a failing emit must not leave the window due forever
        if lane.seq != lane.sub.seq:
            self._restart(lane)  # never a pre-snapshot delta after the `snap`
            return 0
        emissions = lane.queue.take()
        if lane.queue.overflowed:  # defensive: `take` refused what it could not emit
            self._refused(lane)
            return 0
        sent = 0
        try:
            for emission in emissions:
                sent += self.emitter.delta(
                    lane.sub,
                    emission.body,
                    part=emission.part,
                    coalesced_count=emission.coalesced_count,
                    ts_ms=emission.ts_ms,
                )
        except Exception:
            self.drop(lane.sub)  # part of the window is lost: recover through a snapshot
            raise
        lane.seq = lane.sub.seq
        if sent:
            lane.last_emit = now
        return sent

    def _refused(self, lane: _Lane) -> None:
        """A lane's queue refused an update: count why, then drop the topic (§8.4 step 1)."""
        family = lane.sub.topic.family.family
        if lane.queue.refusal == "malformed":  # a producer bug, not an overflow
            cv_ws_malformed_updates_total.labels(topic=family).inc()
            _log().warning("ws producer update malformed", family=family, topic=lane.sub.ch)
        else:
            cv_ws_overflow_total.labels(reason="drop").inc()
        self.drop(lane.sub)

    def drop(self, sub: Subscription) -> None:
        """§8.4 step 1 for one topic: discard its pending state, hold its deltas, and mark it for
        a `backpressure` snapshot. `orders` / `executions` are refused: they are never dropped,
        so the ladder closes the connection instead (step 3)."""
        if sub.topic.family.never_throttled:
            raise ValueError(f"{sub.ch} is never dropped (S4)")
        lane = self.lanes.get(sub.sub_id)
        if lane is not None:
            lane.queue.clear()
            lane.due = None
        sub.snapshot_pending, sub.pending_reason = True, "backpressure"
        self.resnapshot_required[sub.sub_id] = sub

    def shed(self, sub: Subscription) -> None:
        """Discard the window of `sub` while it awaits a `snap` another sender queued: what the
        window holds predates that snapshot, so it must not count against the budget (§8.4)."""
        lane = self.lanes.get(sub.sub_id)
        if lane is not None and sub.snapshot_pending and lane.queue.pending_bytes:
            self._restart(lane)

    def forget(self, sub_id: str) -> None:
        """The subscription ended: nothing of it may be emitted or re-snapshotted."""
        self.lanes.pop(sub_id, None)
        self.resnapshot_required.pop(sub_id, None)

    def throttle_ms(self, sub: Subscription) -> float:
        """The subscription's `effective.throttle_ms` under the current class (§8.3)."""
        ms = float(sub.effective.get("throttle_ms") or 0) * _MULTIPLIER[self.cls]
        if self._degrades(sub):
            ms = max(ms, DEGRADED_THROTTLE_MS)
        return ms

    def _degrades(self, sub: Subscription) -> bool:
        saturated = _rank(self.cls) >= _rank(ConnectionClass.SATURATED)
        return saturated and sub.topic.family.family in DEGRADED_FAMILIES

    def _coalesce(self, sub: Subscription) -> bool:
        """`coalesce: false` is honoured only while the connection is healthy (§5.1)."""
        return self.cls is not ConnectionClass.HEALTHY or sub.effective.get("coalesce") is not False

    def classify(
        self, queue_pct: float, subs: Iterable[Subscription], now: float | None = None
    ) -> dict[str, Any] | None:
        """One §8.3 sample: on a class change, enforce it and return the `connection_quality`
        notice to send on `system`; None otherwise. `subs` is the connection's full subscription
        set, from which the notice's `degraded_topics` are named."""
        now = self.emitter.clock() if now is None else now
        rtt = self.probe.rtt_ms(now)
        if not self.classifier.observe(classify(queue_pct, rtt)):
            return None
        return quality_notice(self.cls, queue_pct, rtt, self.apply(subs, now))

    def apply(self, subs: Iterable[Subscription], now: float | None = None) -> dict[str, Any]:
        """Re-pace every lane under the current class; returns the notice's `applied` block."""
        now = self.emitter.clock() if now is None else now
        for lane in self.lanes.values():
            if _held(lane.sub) or lane.seq != lane.sub.seq:
                self._restart(lane)  # a dead window is shed (§8.4), never folded nor counted
                continue
            lane.queue.set_coalesce(self._coalesce(lane.sub))
            if lane.queue.overflowed:  # forced coalescing folded past a bound
                self._refused(lane)
            elif lane.due is not None:
                lane.due = max(now, lane.last_emit + self.throttle_ms(lane.sub) / 1000)
        return {
            "throttle_multiplier": _MULTIPLIER[self.cls],
            "forced_coalesce": self.cls is not ConnectionClass.HEALTHY,
            "degraded_topics": sorted(sub.ch for sub in subs if self._degrades(sub)),
        }


def _held(sub: Subscription) -> bool:
    """Its deltas are held: it awaits a `snap` (another sender's or the ladder's) or is paused."""
    return sub.snapshot_pending or sub.effective.get("paused") is True


def _queue(sub: Subscription) -> CoalescingQueue:
    return CoalescingQueue(sub.topic.family.family)


def _log() -> Any:
    return structlog.get_logger(__name__)
