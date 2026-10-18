"""Per-connection throttling and adaptive classification (E17-T03, `23-ws-protocol.md` §8.1,
§8.3, §9.1).

`Pacer` sits between `SequencingHub.publish` and one connection's `TopicEmitter`. Each update of a
throttled topic lands in that subscription's `CoalescingQueue`, and at most one window per
effective `throttle_ms` leaves through `TopicEmitter.delta`, so a coalesced frame still consumes
exactly one sequence number. The first update after a quiet window leaves at once; later ones
leave when the window closes (`tick`). `orders` and `executions` bypass the pacer, frame by frame
(S4). A queue that overflows is dropped and its topic marked for a `backpressure` snapshot (§8.4
step 1); the outbound budget decides when that snapshot may go (step 2).
A full queue counts as `cv_ws_overflow_total{reason="drop"}`, an update that breaks its merge rule
(one to a confirmed footprint bar, #3297) as `reason="unmergeable"` and logged as a malformed update
is; a malformed update is a producer bug, counted in `cv_ws_malformed_updates_total` and logged
(family, topic and error class only), never as an overflow.

With the flag on `ws/pipeline.py` routes the hub's deltas here (S3), checking the budget per update:
`pending_bytes` is a total kept as the lanes change, and open windows are armed on a heap, so the
check, `tick` and `next_due` are O(1) until one is due (C-2.18). A window whose emit raises drops
its topic and tells `on_error` (the pipeline's containment, §10.1). §16.1 S5 between windows (D18):
windows that close together leave in causal order, and a `trade_groups` window never closes before
a `positions` window that was open when one of its updates arrived; `positions` never waits.

`Classifier` turns the outbound queue depth and the RTT (`RttProbe`, §9.1) into a class every
classification interval (`CV_WS_CLASSIFY_INTERVAL_MS`, `CLASSIFY_INTERVAL_S` by default): a class
worsens at once and improves only after two consecutive better samples. `Pacer.apply` enforces it:
`lagging` doubles throttles and forces coalescing; `saturated` and `overflowing` quadruple them and
hold `heatmap` and `profile` to at most one frame a second. A queue depth that is not finite reads
as a full queue, never as a healthy one (#2552). With the flag on the pipeline's writer turn runs
the classification and sends the probe (`ws/pipeline.py`, #412). E17-T06: a merged window that
leaves as one frame of n updates adds n - 1 to `cv_ws_conflated_total{topic}` and observes n in
`cv_ws_coalesced_updates`; each probe sample, answered or retired, is one `cv_ws_rtt_seconds`.

Plain synchronous code on the hot path (C-2.20). One clock domain, the emitter's monotonic
`TopicEmitter.clock`: `offer` reads it; `tick`, `classify` and `apply` default `now` to it.
"""

from __future__ import annotations

import heapq
import math
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import structlog

from candleviewer.ws.binary import Frame
from candleviewer.ws.coalescing import MERGED_FAMILIES, CoalescingQueue
from candleviewer.ws.metrics import (
    COALESCED_UPDATES,
    cv_ws_conflated_total,
    cv_ws_connection_class,
    cv_ws_malformed_updates_total,
    cv_ws_overflow_total,
    cv_ws_rtt_seconds,
)
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import PRIVATE_CAUSAL_ORDER, TopicEmitter

CLASSIFY_INTERVAL_S: Final = 1.0
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
#: Bytes from a CSPRNG in each probe id (§9.1): a fresh 48-bit token per probe.
PROBE_TOKEN_BYTES: Final = 6
#: §9.1: a server `ping` is answered within 10 s; a probe left unanswered that long is retired.
PONG_TIMEOUT_S: Final = 10.0
#: A probe is due once this share of its interval has passed since the last one: a classification
#: tick that runs early against the last probe (that tick ran late) still sends one, and a caller
#: that ticks faster sends at most two per interval.
PROBE_DUE_SHARE: Final = 0.5


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
#: E17-T06: every child bound now, so each series exists at 0 from the process start. A merged
#: window's updates count under its family: only a family with a §8.2 merge rule that is not an
#: append family can merge (`coalescing.MERGED_FAMILIES`); any other window leaves whole, count 1.
CONFLATED: Final = {f: cv_ws_conflated_total.labels(topic=f) for f in sorted(MERGED_FAMILIES)}
#: E17-T06: open connections per class; `ConnectionPipeline` moves its connection between them.
CLASS_COUNTS: Final = {c: cv_ws_connection_class.labels(state=c.value) for c in ConnectionClass}


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


def _probe_token() -> str:
    return secrets.token_hex(PROBE_TOKEN_BYTES)


class RttProbe:
    """§9.1 RTT sampling: one server `ping` outstanding at a time, one per classification tick
    (`interval_s` apart; a tick that runs early against the last probe still sends one,
    `PROBE_DUE_SHARE`). Each id ends in a fresh random token, so no id follows from an earlier
    one: only the one outstanding id, which a client learns from its `ping`, is a sample, and a
    `pong` for any other id stores nothing. While a probe is unanswered its age counts as the RTT,
    so a socket that stopped draining reads as slow at once rather than when (if ever) the `pong`
    arrives. After `PONG_TIMEOUT_S` the probe is retired: its age becomes one sample and a fresh
    probe follows, so one lost `pong` cannot hold the connection `saturated`. A sample is never
    negative (§15.9 `rtt_ms`), whatever clock stamps the `pong`."""

    def __init__(
        self, interval_s: float = CLASSIFY_INTERVAL_S, *, token: Callable[[], str] = _probe_token
    ) -> None:
        self.interval_s = interval_s
        #: Each probe id's token: a CSPRNG's (`secrets`) by default; tests inject a fixed source.
        self._token = token
        self.sample_ms: float | None = None
        self._sent = 0
        self._outstanding: tuple[str, float] | None = None
        self._last_sent = -math.inf

    def ping_id(self, now: float) -> str | None:
        """The id of the probe to send now, or None when one is outstanding or not yet due."""
        self._retire(now)
        due = self._last_sent + self.interval_s * PROBE_DUE_SHARE
        if self._outstanding is not None or now < due:
            return None
        self._sent += 1
        probe = f"{RTT_PROBE_PREFIX}{self._sent}-{self._token()}"
        self._outstanding, self._last_sent = (probe, now), now
        return probe

    def pong(self, probe: str, now: float) -> bool:
        """Record the answer to `probe`; False for any other id (a heartbeat `pong`, an answered
        or retired probe's): one comparison, no state kept for it."""
        self._retire(now)
        if self._outstanding is None or self._outstanding[0] != probe:
            return False
        self.sample_ms = max(0.0, (now - self._outstanding[1]) * 1000)
        cv_ws_rtt_seconds.observe(self.sample_ms / 1000)  # E17-T06: each sample, once
        self._outstanding = None
        return True

    def rtt_ms(self, now: float) -> float | None:
        self._retire(now)
        if self._outstanding is None:
            return self.sample_ms
        age = max(0.0, (now - self._outstanding[1]) * 1000)
        return age if self.sample_ms is None else max(self.sample_ms, age)

    def _retire(self, now: float) -> None:
        if self._outstanding is not None and now - self._outstanding[1] >= PONG_TIMEOUT_S:
            self.sample_ms = max(0.0, (now - self._outstanding[1]) * 1000)
            cv_ws_rtt_seconds.observe(self.sample_ms / 1000)
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
    predates that and is discarded. `bytes` is its queue's `pending_bytes` as last counted.
    `waited_on`: an update of the family behind this one in causal order arrived while this window
    was open, so that family's window closes after it (§16.1 S5, `Pacer._gate`)."""

    sub: Subscription
    queue: CoalescingQueue
    seq: int
    last_emit: float = -math.inf
    due: float | None = None
    bytes: int = 0
    waited_on: bool = False


class Pacer:
    """Throttling and coalescing of one connection's subscriptions (§8.1, §8.3)."""

    def __init__(self, emitter: TopicEmitter, interval_s: float = CLASSIFY_INTERVAL_S) -> None:
        self.emitter = emitter
        #: Told of a window whose emit raised, after its topic is dropped; without it the error
        #: propagates out of `offer` / `tick`.
        self.on_error: Callable[[Subscription, Exception], None] | None = None
        #: Told the close of each window it arms: the pipeline wakes its idle writer for one that
        #: closes before the writer's wait ends (§8.1).
        self.on_arm: Callable[[float], None] | None = None
        self.classifier = Classifier()
        #: Probed once per classification tick: `interval_s` is the connection's classification
        #: interval (`BackpressureConfig.classify_interval_ms`).
        self.probe = RttProbe(interval_s)
        self.lanes: dict[str, _Lane] = {}
        #: §8.4 step 1: dropped topics awaiting their `backpressure` snapshot, by `sub_id`; the
        #: outbound ladder (`Backpressure.drain`) sends them and removes them.
        self.resnapshot_required: dict[str, Subscription] = {}
        #: Every lane's `bytes`, summed as they change.
        self._pending = 0
        #: Armed windows, `(due, rank, sub_id)`, earliest first, then in §16.1 S5 causal order
        #: (`_causal_rank`); one whose lane no longer has that `due` is stale and skipped.
        #: Rebuilt from the lanes once mostly stale (bounded, C-2.18).
        self._dues: list[tuple[float, int, str]] = []
        #: §16.1 S5: the `positions` and `trade_groups` lanes by causal rank (`_CAUSAL`). A private
        #: topic has one name and no replay, so a connection has at most one lane of each.
        self._ranked: dict[int, _Lane] = {}

    @property
    def cls(self) -> ConnectionClass:
        return self.classifier.current

    @property
    def pending_bytes(self) -> int:
        """Estimated size of every lane's pending state, for the connection budget (§8.4): O(1),
        kept as the lanes change, never summed per call."""
        return self._pending

    def offer(
        self,
        sub: Subscription,
        body: Mapping[str, Any] | None,
        *,
        part: Frame | None = None,
        ts_ms: int | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> bool:
        """Route one source update of `sub`; True when it was emitted or queued. A throttled
        topic needs the structured `body` (malformed without it); the CVWB `part` is optional.
        `meta` rides on the envelope: a window carries its last update's."""
        if sub.topic.family.never_throttled:
            return self.emitter.delta(sub, body, part=part, ts_ms=ts_ms, meta=meta)
        if _held(sub):
            lane = self.lanes.get(sub.sub_id)
            if lane is not None and lane.queue.pending:
                self._restart(lane)  # stale: the pending `snap` carries this state
            return False
        lane = self.lanes.get(sub.sub_id)
        if lane is None:
            lane = self.lanes[sub.sub_id] = _Lane(sub, _queue(sub), sub.seq)
            if (rank := _CAUSAL.get(sub.topic.family.family)) is not None:
                self._ranked[rank] = lane
        elif lane.seq != sub.seq:
            self._restart(lane)  # a snapshot went out since: what the lane holds is stale
        lane.queue.set_coalesce(self._coalesce(sub))
        if not lane.queue.offer(body, part, ts_ms=ts_ms, meta=meta):
            self._refused(lane)
            return False
        self._account(lane)
        now, armed = self.emitter.clock(), lane.due
        due = max(now, lane.last_emit + self.throttle_ms(sub) / 1000) if armed is None else armed
        hold = self._gate(lane, arrived=True)
        if hold is not None:  # §16.1 S5: it closes after that window, never inline before it
            if max(due, hold) != armed:
                self._arm(lane, max(due, hold))
        elif now >= due:  # the leading edge, or a window whose close has passed: it leaves now
            self._flush(lane, now)
        elif armed is None:
            self._arm(lane, due)
        return True

    def tick(self, now: float | None = None) -> int:
        """Flush every lane whose window has closed; returns the frames emitted."""
        now = self.emitter.clock() if now is None else now
        sent = 0
        while self._dues and self._dues[0][0] <= now:  # read each time: `_arm` may rebuild it
            lane = self._armed(heapq.heappop(self._dues))
            if lane is not None:
                sent += self._flush(lane, now)
        return sent

    def next_due(self) -> float | None:
        """When the earliest pending window closes (monotonic seconds), if any."""
        dues = self._dues
        while dues and self._armed(dues[0]) is None:
            heapq.heappop(dues)  # stale: its lane was flushed, re-timed or let go
        return dues[0][0] if dues else None

    def _armed(self, entry: tuple[float, int, str]) -> _Lane | None:
        """The lane `entry` still times; None when the entry is stale."""
        lane = self.lanes.get(entry[2])
        return lane if lane is not None and lane.due == entry[0] else None

    def _gate(self, lane: _Lane, *, arrived: bool) -> float | None:
        """§16.1 S5 between windows (D18): the close of the open window of the family just ahead
        of `lane`'s in causal order (`positions`, for `trade_groups`; adjacent in
        `PRIVATE_CAUSAL_ORDER`, as a test pins) when one of `lane`'s updates arrived while it was
        open (`arrived`: one does now), else None; `lane`'s window never closes before it. It
        marks that window `waited_on` when `arrived`, and moves and flushes no window, so
        `positions` is never delayed and the gate pushes nothing from inside an `offer`."""
        rank = _CAUSAL.get(lane.sub.topic.family.family)
        ahead = None if rank is None else self._ranked.get(rank - 1)
        if ahead is None or ahead.due is None:
            return None
        ahead.waited_on |= arrived
        return ahead.due if ahead.waited_on else None

    def _arm(self, lane: _Lane, due: float) -> None:
        if lane.due is None:  # a new window: no later family's update has arrived in it yet
            lane.waited_on = False
        lane.due = due
        heapq.heappush(self._dues, (due, _causal_rank(lane.sub), lane.sub.sub_id))
        if len(self._dues) > 2 * len(self.lanes) + 64:  # mostly stale: rebuild from the lanes
            self._dues = [
                (ln.due, _causal_rank(ln.sub), sid)
                for sid, ln in self.lanes.items()
                if ln.due is not None
            ]
            heapq.heapify(self._dues)
        if self.on_arm is not None:
            self.on_arm(due)

    def _account(self, lane: _Lane) -> None:
        """`pending_bytes` follows `lane`'s queue after anything changed it."""
        size = lane.queue.pending_bytes
        self._pending += size - lane.bytes
        lane.bytes = size

    def _restart(self, lane: _Lane) -> None:
        """A snapshot went out or is pending: a new queue, since the old one's memory across
        windows (the heatmap's sent buckets, keyed by `t_ms` only) predates it (§8.2)."""
        lane.queue = _queue(lane.sub)
        lane.due, lane.seq = None, lane.sub.seq
        self._account(lane)

    def _flush(self, lane: _Lane, now: float) -> int:
        lane.due = None  # first: a failing emit must not leave the window due forever
        if lane.seq != lane.sub.seq:
            self._restart(lane)  # never a pre-snapshot delta after the `snap`
            return 0
        emissions = lane.queue.take()
        self._account(lane)
        if lane.queue.overflowed:  # defensive: `take` refused what it could not emit
            self._refused(lane)
            return 0
        sent = 0
        try:
            for emission in emissions:
                count = emission.coalesced_count
                if self.emitter.delta(
                    lane.sub,
                    emission.body,
                    part=emission.part,
                    coalesced_count=count,
                    ts_ms=emission.ts_ms,
                    meta=emission.meta,
                ):
                    sent += 1
                    if count > 1:  # E17-T06: `count` updates left as one frame
                        CONFLATED[lane.queue.family].inc(count - 1)
                        COALESCED_UPDATES.observe(count)
        except Exception as exc:
            self.drop(lane.sub)  # part of the window is lost: recover through a snapshot
            if self.on_error is None:
                raise
            self.on_error(lane.sub, exc)
            return sent
        lane.seq = lane.sub.seq
        if sent:
            lane.last_emit = now
        return sent

    def _refused(self, lane: _Lane) -> None:
        """A lane's queue refused an update: count why, then drop the topic (§8.4 step 1)."""
        queue, family = lane.queue, lane.sub.topic.family.family
        if queue.refusal == "malformed":  # a producer bug, not an overflow
            cv_ws_malformed_updates_total.labels(topic=family).inc()
            _log().warning("ws update malformed", family=family, ch=lane.sub.ch, error=queue.error)
        else:  # `unmergeable` counts apart from a slow consumer's drops (a producer bug, #3297)
            reason = "drop" if queue.refusal == "full" else "unmergeable"
            cv_ws_overflow_total.labels(reason=reason).inc()
            if reason == "unmergeable":  # a producer bug, logged as a malformed update is
                ch, error = lane.sub.ch, queue.error
                _log().warning("ws update unmergeable", family=family, ch=ch, error=error)
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
            self._account(lane)
        sub.snapshot_pending, sub.pending_reason = True, "backpressure"
        self.resnapshot_required[sub.sub_id] = sub

    def shed(self, sub: Subscription) -> None:
        """Discard the window of `sub` while its deltas are held: it awaits a `snap` another
        sender queued (what the window holds predates it), or it is paused (D16: its resume
        re-snapshots it), so the window must not count against the budget (§8.4)."""
        lane = self.lanes.get(sub.sub_id)
        if lane is not None and _held(sub) and lane.queue.pending_bytes:
            self._restart(lane)

    def forget(self, sub_id: str) -> None:
        """The subscription ended: nothing of it may be emitted or re-snapshotted."""
        self.discard(sub_id)
        self.resnapshot_required.pop(sub_id, None)

    def discard(self, sub_id: str) -> None:
        """Drop the window of `sub_id`, if any, but not its `backpressure` mark (§8.4 Lanes)."""
        lane = self.lanes.pop(sub_id, None)
        if lane is not None:
            self._pending -= lane.bytes
            rank = _CAUSAL.get(lane.sub.topic.family.family)
            if rank is not None and self._ranked.get(rank) is lane:  # never a newer lane's entry
                del self._ranked[rank]

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
        set, from which the notice's `degraded_topics` are named. A `queue_pct` that is not finite
        reads as a full queue (100 %): never as healthy, and never a NaN for the notice (#2552)."""
        now = self.emitter.clock() if now is None else now
        if not math.isfinite(queue_pct):
            queue_pct = 100.0
        rtt = self.probe.rtt_ms(now)
        if not self.classifier.observe(classify(queue_pct, rtt)):
            return None
        return quality_notice(self.cls, queue_pct, rtt, self.apply(subs, now))

    def apply(self, subs: Iterable[Subscription], now: float | None = None) -> dict[str, Any]:
        """Re-pace every lane under the current class, then keep §16.1 S5: a window still closes
        after the one it waits for (`_gate`); returns the notice's `applied` block."""
        now = self.emitter.clock() if now is None else now
        for lane in self.lanes.values():
            if _held(lane.sub) or lane.seq != lane.sub.seq:
                self._restart(lane)  # a dead window is shed (§8.4), never folded nor counted
                continue
            lane.queue.set_coalesce(self._coalesce(lane.sub))
            if lane.queue.overflowed:  # forced coalescing folded past a bound
                self._refused(lane)
                continue
            self._account(lane)  # a fold re-estimates the pending state
            if lane.due is not None:
                self._arm(lane, max(now, lane.last_emit + self.throttle_ms(lane.sub) / 1000))
        for lane in self._ranked.values():  # after the loop: the window waited for is re-timed
            hold = self._gate(lane, arrived=False)
            if hold is not None and lane.due is not None and lane.due < hold:
                self._arm(lane, hold)
        return {
            "throttle_multiplier": _MULTIPLIER[self.cls],
            "forced_coalesce": self.cls is not ConnectionClass.HEALTHY,
            "degraded_topics": sorted(sub.ch for sub in subs if self._degrades(sub)),
        }


def _held(sub: Subscription) -> bool:
    """Its deltas are held: it awaits a `snap` (another sender's or the ladder's) or is paused. A
    pause ends in a re-snapshot (`Subscriptions.ctl`, §5.4): a window shed meanwhile is not lost."""
    return sub.snapshot_pending or sub.effective.get("paused") is True


def _queue(sub: Subscription) -> CoalescingQueue:
    return CoalescingQueue(sub.topic.family.family)


#: §16.1 S5: windows that close together leave in causal order (`sequencing.causal_sort`'s), the
#: other families after them.
_CAUSAL: Final = {family: i for i, family in enumerate(PRIVATE_CAUSAL_ORDER)}


def _causal_rank(sub: Subscription) -> int:
    return _CAUSAL.get(sub.topic.family.family, len(_CAUSAL))


def _log() -> Any:
    return structlog.get_logger(__name__)
