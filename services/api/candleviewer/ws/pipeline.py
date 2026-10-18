"""One connection's outbound pipeline while `CV_WS_BACKPRESSURE_ENABLED` is on (E17-T03, #412;
`23-ws-protocol.md` §4.4, §8.4, §10.1).

From `accept` on, `_Connection.push` hands every frame to `ConnectionPipeline.push`, the `welcome`
included. It is encoded once in the negotiated subprotocol (`outbound.encode`), queued on the
`OutboundQueue` lanes and counted against the connection's budget, which binds both lanes
(C-2.18). The writer (`gateway.py`) sends each payload as it was encoded.

From the first `auth_ok` (`attach`) the §8.4 ladder (`outbound.Backpressure`) holds that budget:
`check` after every push but a non-final `snap` chunk (no check splits a chunk set, §3.6). A drop
wakes the writer, whose `service` drains before each pop, never from inside a push. A snapshot
that does not queue, or raises (D9: contained to its topic, logged at most once per family per
`classify_interval_ms`), is parked until a source rebuild names it or the coarse timer's pass,
which ends at its first failure, never retried once per send. Step 3's `bye` carries
`hint.most_expensive_topics`; the close audit's `after_state` its trigger and an expired flush
(§4.3). Before `auth_ok` there is no topic: over budget is step 3 alone.

From `attach` the pipeline is `ConnectionAuthz.on_drop` (§8.4 Lanes, §9.5): a control frame that
ends or resets a subscription's stream overtakes what the normal lane holds of it, so those frames
and its throttle window go before it is queued; its priority-lane frames stay, ahead of it.

The pipeline is also the connection's hub sink (`sequencing.Sink`, S3): the hub's deltas go
through the attached `Pacer` (§8.1, §8.2), `orders` and `executions` frame by frame, the rest in
windows the writer's `service` closes on time (its wait cut to the next, `wait_s`); `check` runs
after every routed update too (O(1)). An update, a window or a snapshot's build (flushed, or the
hub's re-snapshot, §7.4) that raises is contained to its subscription (D9, §10.1). A paced frame's
fan-out span runs from its release to the send (D7); a window carries a producer's own
`coalesced_count` (#3268).

From `attach` the writer's `service` also classifies the connection (§8.3, #412) once per
`classify_interval_ms`, on a drift-free schedule (a late turn takes one classification, not the
ones it missed), before it closes the due windows: a class change re-times them (`Pacer.apply`), so
the windows that change made due leave in the same turn and the writer's wait is read after it
(#2552). The depth is the queue's share of the budget, pending state included, and a class change,
in either direction, is announced through `_Connection.push_system` (§15.9's view of it) on the
priority lane, after a budget check, since `apply` may fold a window. Right after it the RTT probe
(§9.1) queues a `ping` on the priority lane when none is outstanding; its `pong` comes back
through `pong`, where any other id costs one comparison and keeps nothing (an unanswered probe is
retired after 10 s). The gateway's idle heartbeat `ping` is unchanged, but the probe keeps the
outbound traffic from idling for its 20 s, so it does not fire while the probe runs; a socket with
no inbound traffic for 45 s still closes `heartbeat_timeout` (§9.1). E17-T06 counts each attached
connection under its class in `cv_ws_connection_class` until `release`, and each classification
observes the depth it read; `Pacer` counts merged windows and each RTT sample (`ws/pacing.py`).

The frame cost series (E17-T06, `cv_ws_frame_encode_seconds` and `cv_ws_frame_bytes`) see that one
encode. For a data frame the hub stamped (`received`: one frame of a subscription in
`SAMPLE_EVERY`) the serialiser alone is timed with `perf_counter` and its output sized at its wire
length, once, under the connection's own kind (`json` or `msgpack`) with weight `SAMPLE_EVERY`, as
the flag-off writer does before its send. Any other frame reads no timer, and an encode that fails
is not observed. The encode happens at push, so a stamped frame that a close or a ladder drop
removes before the send is in these series but not in `cv_ws_fanout_seconds`, which the writer
observes once the socket has the frame. The observed size leaves out a frame's `sp` (23 §3.1).

A close takes the terminal slot (`Terminal`), in no lane and never counted: its `bye` and close
marker are the only items admitted past the budget, one small frame, so the bound holds to within
one frame, or one chunk set while it is being queued, since no check runs between its chunks; the
check after its last chunk drops it whole or closes in the same synchronous turn. The budget never
refuses a `bye` (§8.4, WS-D01). A close that ends the
identity (token expiry, revocation, a disabled user) and every `slow_consumer` close clear both
lanes, so the `bye` is next; any other close keeps the priority lane ahead of the `bye` and
discards the normal lane. Nothing is queued after a close. The flush runs under one deadline,
`BackpressureConfig.close_flush_s` from the first close on (a later seal never extends it): the
writer `arm`s it, and past it gives up with no `bye` (§4.4). That expiry is counted once per
connection as `cv_ws_overflow_total{reason="close_flush_deadline"}`, whatever the close's reason,
on top of the `close_budget` a step 3 close has already counted (§8.4 step 4).

The deadline is on the event loop's clock (`loop.time()`), not on the gateway's injected `clock`:
only an `asyncio.Timeout` can cancel a send that a peer which stopped reading has parked, and it
reads the loop's clock. So a test cannot advance it; it bounds it with a short `close_flush_s` and
a send that never completes, which leaves the deadline as the only way out.

A frame its encoder refuses is a server fault (§10.1). After `attach`, a droppable one (a `d` or
`snap` of a throttled topic the connection subscribes) drops its topic to a `backpressure`
re-snapshot: its queued frames go, the ladder's `drain` will snapshot it, the rest of its chunk set
is never queued, and it counts as a malformed update, logged at `warning` at most once per family
per `classify_interval_ms`; the connection stays open. Any other fails closed: `internal_error`,
before its log line (one that raises skips no close). A NaN or an infinity is refused on both
subprotocols, a producer bug either way (§10.1): JSON refuses it as it encodes, and
`msgpack_payload` after packing, as a `ValueError` too. The log line names the frame's type,
family and error class, never its payload or the error's text (C-12.6). Whatever the encoder
raises is caught, so nothing raises into the caller and one bad frame never stops a fan-out.

Plain synchronous code: no I/O and no task of its own; the gateway's writer drives it.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from time import perf_counter
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.codec import encode_server_frame
from candleviewer.ws.lifecycle import SUBPROTOCOL_MSGPACK, bye_frame
from candleviewer.ws.metrics import (
    JSON_ENCODE_SECONDS,
    JSON_FRAME_BYTES,
    MSGPACK_ENCODE_SECONDS,
    MSGPACK_FRAME_BYTES,
    SAMPLE_EVERY,
    cv_ws_malformed_updates_total,
    cv_ws_overflow_total,
    cv_ws_queue_bytes,
    cv_ws_queue_frames,
    frame_bytes,
)
from candleviewer.ws.outbound import (
    Backpressure,
    FrameEncoder,
    Key,
    LadderEvent,
    OutboundQueue,
    encode,
    json_payload,
)
from candleviewer.ws.pacing import CLASS_COUNTS, ConnectionClass, Pacer
from candleviewer.ws.sequencing import MAX_OUTBOUND_FRAME_BYTES, TopicEmitter
from candleviewer.ws.topics import FAMILIES

if TYPE_CHECKING:
    from candleviewer.ws.binary import Frame
    from candleviewer.ws.permissions import ConnectionAuthz, Subscription
    from candleviewer.ws.sequencing import SnapReason, SnapshotCache

#: §8.4 step 3's `bye`: one fixed message for both triggers (a `redrop` close happens under budget).
SLOW_CONSUMER_RETRY_AFTER_MS: Final = 3000
SLOW_CONSUMER_MESSAGE: Final = "Client is not draining its outbound queue."
#: §8.4 step 4: a close whose flush deadline expired, whatever its reason.
CLOSE_FLUSH_DEADLINE: Final = "close_flush_deadline"
#: §4.3: the close audit's `trigger` for an expired flush when step 3 gave none.
FLUSH_DEADLINE_TRIGGER: Final = "flush_deadline"
#: The frame types the server sends (§13.1): a log line names one of these, else `other`.
_SERVER_TYPES: Final = frozenset(
    (
        "welcome auth_ok sub_ok unsub_ok ctl_ok err permission_change revoked ping pong bye d snap"
    ).split()
)
#: A NaN or an infinity as `codec.encode_server_frame` packs a float: `0xcb` (float64), then a sign
#: bit and an exponent of all ones. Every non-finite float of a packed frame matches. A match can
#: also fall inside other bytes (a binary part, an integer, a finite float's mantissa), so it only
#: says that the frame itself must be looked at.
_NON_FINITE_FLOAT64: Final = re.compile(rb"\xcb[\x7f\xff][\xf0-\xff]")


class Close(Protocol):
    """`_Connection.close_with`, as the pipeline calls it."""

    def __call__(self, reason: str, *, bye: dict[str, Any] | None = None) -> None: ...


def slow_consumer_bye(now_ms: int, topics: Iterable[str] | None = None) -> dict[str, Any]:
    """The step-3 `bye`: `retry_after_ms` 3 000 and the generic message, never a size. Given
    `topics` (step 3's most expensive, empty when none held any), its `hint` names them."""
    frame = bye_frame("slow_consumer", now_ms=now_ms, retry_after_ms=SLOW_CONSUMER_RETRY_AFTER_MS)
    frame["p"]["message"] = SLOW_CONSUMER_MESSAGE
    if topics is not None:
        frame["p"]["hint"] = {"most_expensive_topics": list(topics)}
    return frame


def msgpack_payload(frame: Mapping[str, Any]) -> bytes:
    """`cv.v1.msgpack` with the flag on: `codec.encode_server_frame`, refusing a NaN or an
    infinity with `ValueError`, as `outbound.json_payload` does (§10.1). Only a frame whose packed
    bytes match `_NON_FINITE_FLOAT64` is walked, so any other costs one search of its bytes."""
    payload = encode_server_frame(frame)
    if _NON_FINITE_FLOAT64.search(payload) is not None and _holds_non_finite(frame):
        raise ValueError("non-finite number")
    return payload


def _holds_non_finite(value: Any) -> bool:
    """A NaN or an infinity anywhere the packer writes a float: map keys and values and array
    items, at any depth (the packer takes no other container). Iterative; the packer has already
    refused deeper nesting than it allows."""
    stack: list[Any] = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, float):
            if not math.isfinite(node):
                return True
        elif isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list | tuple):
            stack.extend(node)
    return False


@dataclass(frozen=True, slots=True)
class Terminal:
    """The close under way: its `bye` (encoded when the writer sends it) and close code. `flush`:
    the priority lane goes out before the `bye`; otherwise the `bye` is next."""

    bye: dict[str, Any]
    code: int
    flush: bool


class ConnectionPipeline:
    """Encoding, lanes, budget and close slot of one connection (module docstring)."""

    def __init__(
        self,
        *,
        encoding: str,
        config: BackpressureConfig,
        close: Close,
        wall_ms: Callable[[], int],
        connection_id: str,
    ) -> None:
        self.config = config
        self.queue = OutboundQueue(config.max_bytes, config.max_frames)
        self.terminal: Terminal | None = None
        self.released = False
        #: A flush deadline expired and was counted: one count per connection (`abandon`).
        self.abandoned = False
        #: The §8.4 ladder, from the first `auth_ok` (`attach`); before it, step 3 alone.
        self.ladder: Backpressure | None = None
        #: The step 3 trigger of this connection's close (`budget` | `redrop`), for its audit.
        self.trigger: str | None = None
        #: The connection's codec, for everything below that depends on it.
        self._msgpack = encoding == SUBPROTOCOL_MSGPACK
        self._dumps: FrameEncoder = msgpack_payload if self._msgpack else json_payload
        #: E17-T06: `_dumps` timed, bound once, so a stamped frame's encode seconds are its
        #: serialiser's alone (`_encode_s`) and no frame allocates a wrapper.
        self._timed_dumps: FrameEncoder = self._timed
        self._encode_s = 0.0
        #: E17-T06: the frame cost pair (encode seconds, frame bytes) of this connection's codec.
        self._cost = (
            (MSGPACK_ENCODE_SECONDS, MSGPACK_FRAME_BYTES)
            if self._msgpack
            else (JSON_ENCODE_SECONDS, JSON_FRAME_BYTES)
        )
        self._close = close
        self._wall_ms = wall_ms
        self._connection_id = connection_id
        #: The flush deadline on the loop's clock, from the first close; the writer's scope.
        self._deadline: float | None = None
        self._timeout: asyncio.Timeout | None = None
        #: From `attach`: the connection's subscriptions by id (the ladder's `subs` and `live`).
        self._live: Mapping[str, Subscription] = {}
        #: `classify_interval_ms` in seconds, on the gateway's clock (`service`): the classification
        #: tick (§8.3), the coarse retry of parked snapshots and the log window (`_quiet`).
        self._interval_s = config.classify_interval_ms / 1000
        self._retry_at: float | None = None
        #: §8.3: when the next classification is due, from `attach` on (none before it).
        self._classify_at = math.inf
        #: From `attach`: `_Connection.push_system`, for the `connection_quality` notice.
        self._notify: Callable[[dict[str, Any]], None] | None = None
        #: Per log line and family: when it may log again, and the lines held back (`_quiet`).
        self._now, self._held = 0.0, dict[tuple[str, str], tuple[float, int]]()
        #: From `attach`: the authorisation (its `on_drop` is `_invalidate`) and the pacer.
        self._attached: tuple[ConnectionAuthz, Pacer] | None = None
        #: §10.1: per key, a chunk set whose chunk its encoder refused; its rest is never queued.
        self._skips: dict[Key, str] = {}
        #: When the writer's last idle wait ends (`wait_s`); None once a window armed to close
        #: sooner has woken it (`_wake_for`).
        self._wake_by: float | None = None
        #: E17-T06: the class this connection counts under in `cv_ws_connection_class`, from
        #: `attach` to `release`; None while it counts under none.
        self._counted: ConnectionClass | None = None

    @property
    def deadline(self) -> float | None:
        """The close's flush deadline on the loop's clock, from the first close; None before."""
        return self._deadline

    def attach(
        self,
        authz: ConnectionAuthz,
        emitter: TopicEmitter,
        notify: Callable[[dict[str, Any]], None],
    ) -> None:
        """The first `auth_ok`: the ladder over this queue, and the `Pacer` that the hub's deltas
        go through from now on (this pipeline is the connection's sink, module docstring). The
        first classification is one interval on; `notify` queues its notices on `system`."""
        self._live, pacer = authz.by_id, Pacer(emitter, self._interval_s)
        pacer.on_error = partial(self._failed, "update", pacer)
        pacer.on_arm = self._wake_for
        self.ladder = Backpressure(self.queue, pacer, partial(self._snapshot, emitter))
        emitter.on_rebuild = self._rebuilt
        emitter.on_snapshot = pacer.snapshotted
        authz.on_drop, self._attached = partial(self._invalidate, pacer), (authz, pacer)
        self._notify, self._classify_at = notify, emitter.clock() + self._interval_s
        self._count_as(pacer.cls)

    def push(self, frame: Mapping[str, Any], received: float | None = None) -> None:
        """Queue one frame; nothing once a close or `release` happened (WS-D01). A frame the hub
        stamped (`received`) has its encode timed and sized here, once, its size without its `sp`
        (23 §3.1; module docstring)."""
        if self.terminal is not None or self.released or (self._skips and self._skipped(frame)):
            return
        try:
            item = encode(
                frame, self._dumps if received is None else self._timed_dumps, received=received
            )
        except Exception as exc:  # whatever the encoder raises: never into the fan-out (§10.1)
            if self._recovers(frame, exc):
                return
            self._close("internal_error")  # first: a log line that raises skips no close
            with contextlib.suppress(Exception):  # nor reaches the caller (`_failed`'s guard)
                _log().error(
                    "ws frame unencodable", **self._fields(frame), error=type(exc).__name__
                )
            return
        if received is not None:  # E17-T06: the stamped frame's encode time and wire bytes
            seconds, size = self._cost
            seconds.observe(self._encode_s, SAMPLE_EVERY)
            sp = frame.get("sp")  # left out of the size (23 §3.1)
            size.observe(frame_bytes(item.payload, sp, msgpack=self._msgpack), SAMPLE_EVERY)
        if item.size > MAX_OUTBOUND_FRAME_BYTES:  # #2818: logged and sent, never refused
            _log().warning(
                "ws outbound frame over the frame limit", **self._fields(frame), size=item.size
            )
        self.queue.push(item)
        if frame.get("t") == "snap" and frame.get("s") is None:
            return  # a non-final chunk: the set is checked whole, after its last one (§3.6)
        if self.ladder is not None:
            self._apply(self.ladder.check(self._live.values()))
        elif self.queue.over_budget():  # before `auth_ok`: no topic to drop, so step 3 alone
            cv_ws_overflow_total.labels(reason="close_budget").inc()
            self._step3("budget", ())

    def service(self, now: float) -> None:
        """The writer's turn before each pop (after every send and wake): the classification when
        one is due (`_classify`), then the throttle windows closed by `now` (`Pacer.tick`, O(1)
        while none is), then `drain` while a topic awaits its snapshot, opening the ladder's
        `retry` pass over the parked ones once per `classify_interval_ms` (the coarse timer)."""
        ladder, notify = self.ladder, self._notify
        self._now = now  # `_quiet`'s clock, as of the writer's last turn
        if ladder is not None and notify is not None and self.terminal is None:
            if now >= self._classify_at:
                self._classify(ladder, notify, now)
            if self.terminal is None:  # its budget check may have closed: nothing after it
                ladder.pacer.tick(now)
        if ladder is None or self.terminal is not None or not ladder.pacer.resnapshot_required:
            self._retry_at = None
            return
        if self._retry_at is None:
            self._retry_at = now + self._interval_s
        elif now >= self._retry_at:
            self._retry_at = now + self._interval_s
            ladder.retry()
        self._apply(ladder.drain(self._live))

    def _classify(
        self, ladder: Backpressure, notify: Callable[[dict[str, Any]], None], now: float
    ) -> None:
        """One §8.3 sample (module docstring): the depth with the pending state, observed once
        (E17-T06: `cv_ws_queue_bytes`, `cv_ws_queue_frames`), the class, which the connection's
        `cv_ws_connection_class` count follows, and on a change the budget check and the notice;
        then the probe's `ping`, if one is due and neither closed the connection. The next
        classification is the schedule's first tick after `now`. Nothing once `released`: the
        connection stays out of the class count, takes no depth sample and retires no probe."""
        if self.released:  # `release` parks the schedule: this is the second line
            return
        step = self._interval_s
        self._classify_at += step * (1 + (now - self._classify_at) // step)
        if self._classify_at <= now:  # the float sum rounded onto `now`: one sample per tick
            self._classify_at += step
        pacer, queue = ladder.pacer, self.queue
        pending = pacer.pending_bytes
        cv_ws_queue_bytes.observe(queue.bytes + pending)  # E17-T06: the depth this sample reads
        cv_ws_queue_frames.observe(len(queue))
        notice = pacer.classify(queue.pct(pending), self._live.values(), now)
        if pacer.cls is not self._counted:
            self._count_as(pacer.cls)
        if notice is not None:
            self._apply(ladder.check(self._live.values()))  # `apply` may have folded a window
            notify(notice)  # never dropped: over the budget, it closes (§8.4 step 3)
        if self.terminal is not None:
            return  # nothing after the close
        probe = pacer.probe.ping_id(now)
        if probe is not None:
            wall = self._wall_ms()
            self.push({"t": "ping", "id": probe, "ts": wall, "p": {"server_ms": wall}})

    def pong(self, probe: str, now: float) -> None:
        """A client `pong` (`dispatch`, §9.1) received at `now`: the outstanding probe's answer,
        an RTT sample. Any other id (a heartbeat's, an answered or retired probe's, or made up) is
        ignored at the cost of one comparison and keeps nothing. Within its own budget a client
        answers at will, and its `pong`s are exempt from the inbound rate limit (§8.5)."""
        if self.released:  # E17-T06: a late `pong` is no RTT sample, and retires no probe
            return
        if self.ladder is not None:
            self.ladder.pacer.probe.pong(probe, now)

    def _recovers(self, frame: Mapping[str, Any], exc: Exception) -> bool:
        """§10.1 (module docstring): True when `frame`, refused by its encoder, is a `d` or `snap`
        of a throttled topic the connection subscribes, dropped to a re-snapshot; else False."""
        attached, key = self._attached, _droppable(frame)
        if attached is None or key is None:
            return False
        authz, pacer = attached
        sub = authz.find(*key)
        if sub is None:
            return False
        family = sub.topic.family.family
        cv_ws_malformed_updates_total.labels(topic=family).inc()
        if (held := self._quiet(("unencodable", family))) is not None:
            fields = {**self._fields(frame), "error": type(exc).__name__, "suppressed": held}
            _log().warning("ws frame unencodable", **fields)
        self.queue.drop({key})
        pacer.drop(sub)  # held for the ladder's `drain` (§8.4 steps 1 and 2)
        if frame.get("s") is None:  # a snapshot chunk with more to come (§3.6)
            self._skips[key] = str(frame.get("id"))
        self.queue.wake()
        return True

    def _quiet(self, key: tuple[str, str]) -> int | None:
        """None holds a log line back: one per `key` (event, family) per `classify_interval_ms`, on
        `service`'s clock. Else how many it held back since the last line (`suppressed`)."""
        until, held = self._held.get(key, (-math.inf, 0))
        self._held[key] = (
            (until, held + 1) if self._now < until else (self._now + self._interval_s, 0)
        )
        return None if self._now < until else held

    def _skipped(self, frame: Mapping[str, Any]) -> bool:
        """The rest of a chunk set whose chunk its encoder refused: never queued, as no client
        could assemble it (§3.6, §7.2). Its last chunk ends the skip."""
        key = _droppable(frame)
        if key is None or self._skips.get(key, "") != frame.get("id"):
            return False
        if frame.get("s") is not None:
            del self._skips[key]
        return True

    def _invalidate(self, pacer: Pacer, subs: Sequence[Subscription]) -> None:
        """`ConnectionAuthz.on_drop` (module docstring). A `backpressure` mark stays: `drain`
        deletes an ended subscription's entry unsent, and snapshots a held one that is not
        paused, as it is then."""
        self.queue.drop({(sub.ch, sub.replay_session_id) for sub in subs})
        for sub in subs:
            pacer.discard(sub.sub_id)

    # -- the hub's `Sink` (module docstring) ------------------------------------------------------

    @property
    def cache(self) -> SnapshotCache:
        return self._paced().emitter.cache

    @property
    def on_rebuild(self) -> Callable[[list[Subscription]], None]:
        return self._rebuilt

    def delta(
        self,
        sub: Subscription,
        body: Mapping[str, Any] | None = None,
        *,
        part: Frame | None = None,
        coalesced_count: int = 1,
        ts_ms: int | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> bool:
        """One source update of `sub` through the pacer, then the budget check: its pending
        state counts (§8.4). Nothing once a close or `release` happened. Never raises."""
        ladder = self.ladder
        if ladder is None or self.terminal is not None or self.released:
            return False
        try:
            sent = ladder.pacer.offer(
                sub, body, part=part, ts_ms=ts_ms, meta=meta, count=coalesced_count
            )
        except Exception as exc:  # contained to `sub`: the fan-out goes on
            self._failed("update", ladder.pacer, sub, exc)
            return False
        self._apply(ladder.check(self._live.values()))
        return sent

    def snapshot(self, sub: Subscription, reason: SnapReason) -> bool:
        """The hub's re-snapshot of `sub` (§7.4): a build that raises is `_failed`, as in
        `flush_pending` (#3262)."""
        pacer = self._paced()
        try:
            return pacer.emitter.snapshot(sub, reason)
        except Exception as exc:  # contained to `sub`: the fan-out goes on
            self._failed("snapshot", pacer, sub, exc)
            return False

    def flush_pending(self, subs: Iterable[Subscription]) -> int:
        """The emitter's, one subscription at a time: a build that raises is `_failed`."""
        pacer, sent = self._paced(), 0
        for sub in subs:
            try:
                sent += pacer.emitter.flush_pending((sub,))
            except Exception as exc:
                self._failed("snapshot", pacer, sub, exc)
        return sent

    def wait_s(self, now: float, tick_s: float) -> float:
        """The idle writer's wait: `tick_s`, or less when a window closes or the classification
        is due sooner (§8.1, §8.3). Read after `service`, so after a classification re-timed the
        windows (#2552). A window armed during it to close before it ends wakes the writer
        (`_wake_for`)."""
        due = None if self.ladder is None else self.ladder.pacer.next_due()
        wake = self._classify_at if due is None else min(due, self._classify_at)
        wait = min(tick_s, max(0.0, wake - now))
        self._wake_by = now + wait
        return wait

    def _wake_for(self, due: float) -> None:
        """`Pacer.on_arm`: wake the idle writer, once per wait, for a window that closes
        before its wait ends, so it re-reads the wait; any other arm wakes nothing (§8.1)."""
        if self._wake_by is not None and due < self._wake_by:
            self._wake_by = None
            self.queue.wake()

    def _paced(self) -> Pacer:
        if self.ladder is None:  # the gateway registers the pipeline at the `attach`
            raise RuntimeError("the pipeline is not attached")
        return self.ladder.pacer

    def _failed(self, what: str, pacer: Pacer, sub: Subscription, exc: Exception) -> None:
        """An `update` (or window) or a `snapshot` build of `sub` that raised (D9, §10.1): a
        throttled topic (any family outside `PRIORITY_FAMILIES`) drops to a `backpressure`
        re-snapshot (`drain` parks one that fails), the connection open; `orders` and `executions`
        fail closed. Logged by family and error class (C-12.6); a failing logger changes nothing."""
        family, error = sub.topic.family.family, type(exc).__name__
        fields = {"connection_id": self._connection_id, "family": family, "error": error}
        if sub.topic.family.never_throttled:
            self._close("internal_error")
            with contextlib.suppress(Exception):  # never into the caller (`delta`: the fan-out)
                _log().error(f"ws {what} failed", **fields)
            return
        if what == "update":
            cv_ws_malformed_updates_total.labels(topic=family).inc()
        if (held := self._quiet((what, family))) is not None:
            with contextlib.suppress(Exception):  # nor may it skip the drop below
                _log().warning(f"ws {what} failed", **fields, suppressed=held)
        self.queue.drop({(sub.ch, sub.replay_session_id)})
        pacer.drop(sub)  # held for the ladder's `drain` (§8.4 steps 1 and 2)
        self.queue.wake()

    def _apply(self, events: list[LadderEvent]) -> None:
        """A drop wakes the writer, whose `service` drains (never a drain from here); a close is
        step 3. The ladder has counted both (§8.4 step 4)."""
        for event in events:
            if event.action == "drop":
                self.queue.wake()
            elif event.action == "close":
                self._step3(event.trigger, event.topics)

    def _step3(self, trigger: str | None, topics: tuple[str, ...]) -> None:
        self.trigger = trigger
        self._close("slow_consumer", bye=slow_consumer_bye(self._wall_ms(), topics))

    def _snapshot(self, emitter: TopicEmitter, sub: Subscription) -> bool:
        """`drain`'s emitter wrapper (D9): a snapshot that raises reads as not queued, so `drain`
        parks it. Logged by family and error class only (C-12.6), at most once per family per
        `classify_interval_ms`; the next line counts those held back (`suppressed`)."""
        try:
            return emitter.snapshot(sub, "backpressure")
        except Exception as exc:
            family = sub.topic.family.family
            if (held := self._quiet(("snapshot", family))) is not None:
                _log().error(
                    "ws backpressure snapshot failed",
                    connection_id=self._connection_id,
                    family=family,
                    error=type(exc).__name__,
                    suppressed=held,
                )
            return False

    def _rebuilt(self, subs: Iterable[Subscription]) -> None:
        """A hub `flush_pending` (a source rebuild) named `subs`: retry their parked snapshots."""
        if self.ladder is not None and self.ladder.unpark(sub.sub_id for sub in subs):
            self.queue.wake()

    def audit_state(self) -> dict[str, Any] | None:
        """The close audit's `after_state` (§4.3): `trigger` (step 3's `budget` or `redrop`, else
        `flush_deadline` for an expired flush) and `flush_abandoned: true`; None for neither."""
        state: dict[str, Any] = {}
        if self.trigger is not None:
            state["trigger"] = self.trigger
        if self.abandoned:
            state.setdefault("trigger", FLUSH_DEADLINE_TRIGGER)
            state["flush_abandoned"] = True
        return state or None

    def _timed(self, frame: Mapping[str, Any]) -> str | bytes:
        began = perf_counter()
        payload = self._dumps(frame)
        self._encode_s = perf_counter() - began
        return payload

    def close(self, bye: dict[str, Any], code: int, *, flush: bool) -> int:
        """Take the terminal slot (`_Connection.close_with`; a later call changes nothing) and
        start the flush deadline. `flush` keeps the priority lane ahead of the `bye`; otherwise
        both lanes go. Returns how many queued frames were discarded."""
        if self.terminal is not None:
            return 0
        self.terminal = Terminal(bye, code, flush)
        dropped = self.queue.clear(normal_only=flush)
        self.queue.wake()
        self._deadline = asyncio.get_running_loop().time() + self.config.close_flush_s
        if self._timeout is not None:
            self._timeout.reschedule(self._deadline)
        return dropped

    def seal(self) -> int:
        """The identity ended during a close: the priority lane goes too, and the close's own
        `bye` is next. The deadline stays the first close's. Returns how many were discarded."""
        if self.terminal is not None:
            self.terminal = Terminal(self.terminal.bye, self.terminal.code, flush=False)
        dropped = self.queue.clear()
        self.queue.wake()
        return dropped

    def arm(self, timeout: asyncio.Timeout) -> None:
        """The writer's deadline scope; a close taken before the writer started applies now."""
        self._timeout = timeout
        if self._deadline is not None:
            timeout.reschedule(self._deadline)

    def disarm(self) -> None:
        self._timeout = None

    def abandon(self, reason: str | None) -> None:
        """A flush deadline expired: the flush is abandoned with no `bye` (§4.4). Counted once per
        connection, whatever the close's `reason` (the `bye`'s), in addition to a step 3 value
        (§8.4 step 4). A second expiry on the same connection (a fault's flush that starts after
        the writer's deadline passed) is logged, not counted again."""
        if not self.abandoned:
            self.abandoned = True
            cv_ws_overflow_total.labels(reason=CLOSE_FLUSH_DEADLINE).inc()
        _log().warning(
            "ws close deadline passed",
            connection_id=self._connection_id,
            reason=reason,
            queued=len(self.queue),
        )

    def release(self) -> None:
        """Teardown: free both lanes and the subscriptions' hook; nothing is queued after it. The
        connection leaves `cv_ws_connection_class` first, once (E17-T06), and the classification
        schedule is parked, as before `attach`: a writer turn classifies nothing, and an idle one
        waits its tick."""
        self._count_as(None)
        self.released = True
        self._classify_at = math.inf
        self.queue.clear()
        self._timeout = None
        if self._attached is not None:
            self._attached[0].on_drop = None

    def _count_as(self, cls: ConnectionClass | None) -> None:
        """E17-T06: move this connection's count in `cv_ws_connection_class` to `cls` (None: out
        of it), so the gauge is exact across `attach`, each class change and `release`."""
        if self._counted is not None:
            CLASS_COUNTS[self._counted].dec()
        if cls is not None:
            CLASS_COUNTS[cls].inc()
        self._counted = cls

    def _fields(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        """A frame as a log line may name it: bounded type and family, never the payload."""
        t, ch = frame.get("t"), frame.get("ch")
        family = ch.split(".", 1)[0] if isinstance(ch, str) else None
        return {
            "connection_id": self._connection_id,
            "t": t if isinstance(t, str) and t in _SERVER_TYPES else "other",
            "family": family if family is None or family in FAMILIES else "other",
        }


def _droppable(frame: Mapping[str, Any]) -> Key | None:
    """The key of a frame step 1 may drop, as `encode` lays it out (D1), without serialising it."""
    probe = encode(frame, lambda _: "")
    return probe.key if probe.droppable else None


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)
