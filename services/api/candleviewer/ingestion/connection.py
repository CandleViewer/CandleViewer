"""`ConnectionManager`: transport runtime for the B13 `ws_conn` statechart (E08-T04).

The lifecycle is the B13 chart, built through `statechart.factory` (ADR-0016).
This class owns the sockets/tasks the chart's bindings
(`bindings/b13_ws_conn.py`) drive, and is the only sender of chart events.
Feed health (`FeedHealthEvent`) is published on the bus: `healthy` on entering
`live`, `stale` on staleness, `degraded` while backing off, `resubscribing`
while a re-established socket re-subscribes. Transport is injected
(`SocketFactory`) so tests use a fake server.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.base.reconnect import ConnectionGuard
from candleviewer.ingestion.metrics import ingest_subscribe_rejected_total, ingest_ws_up
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ReconnectPolicy
from candleviewer.ingestion.watchdog import (
    FeedHealthEvent,
    StalenessWatchdog,
    feed_health,
    ping_loop,
)
from candleviewer.observability.context import spawn
from candleviewer.observability.latency import StageRecorder, StageStamps
from candleviewer.statechart import build
from candleviewer.statechart.bindings.b13_ws_conn import register_runtime, unregister_runtime
from candleviewer.statechart.factory import default_clock

#: Plain enum published by the B13 chart's entry actions (INV-B13-d, C-2.20):
#: hot paths read `ConnectionManager.state()`; nothing queries the interpreter.
PHASE_CLOSED, PHASE_CONNECTING, PHASE_OPEN, PHASE_DEGRADED = (
    "closed",
    "connecting",
    "open",
    "degraded",
)
_conn_ids = itertools.count(1)


MAX_FRAME_BYTES = 1_048_576  # explicit cap on a single WS frame (E08-X01)
#: #1955: topic-level subscribe/unsubscribe acks awaited at once (oldest dropped past it) and
#: how long one may stay unanswered before it is counted `timeout`.
MAX_PENDING_ACKS = 256
ACK_TIMEOUT_S = 10.0
_ACK_PREFIX = '{"success"'  # Bybit op replies lead with it; data frames lead with `topic`


@dataclass(frozen=True, slots=True)
class _PendingAck:
    op: str
    topics: tuple[str, ...]
    deadline: float


class Socket(Protocol):
    async def send(self, frame: str) -> None: ...
    async def recv(self, max_bytes: int) -> str: ...
    async def close(self) -> None: ...


SocketFactory = Callable[[], Awaitable[Socket]]
Sleep = Callable[[float], Awaitable[None]]


class ConnectionManager:
    """Transport runtime for one B13 `ws_conn` interpreter."""

    def __init__(
        self,
        factory: SocketFactory,
        planner: SubscriptionPlanner,
        watchdog: StalenessWatchdog,
        policy: ReconnectPolicy,
        guard: ConnectionGuard,
        on_message: Callable[[str], None],
        *,
        sleep: Sleep = asyncio.sleep,
        ping_interval_s: float = 20.0,
        check_interval_s: float = 0.5,
        bus: Bus | None = None,
        env: str = "live",
        budget_recheck_s: float = 1.0,
        latency: StageRecorder | None = None,
        clock_offset_ms: Callable[[], int | None] = lambda: None,
        now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = lambda: time.time_ns() // 1000,
    ) -> None:
        self._factory = factory
        self._planner = planner
        self._watchdog = watchdog
        self._policy = policy
        self._guard = guard
        self._on_message = on_message
        self._sleep = sleep
        self._ping_interval = ping_interval_s
        self._check_interval = check_interval_s
        self._bus = bus
        self._env = env
        self._recheck_s = budget_recheck_s
        self._latency = latency
        self._clock_offset_ms = clock_offset_ms
        self._now_ms = now_ms
        self._now_us = now_us  # feed-health envelopes; `now_ms` stamps sampled latency only
        self._desired: set[str] = set()
        #: Topics subscribed on the current socket. A live `TOPICS_CHANGED` pass
        #: sends only the diff against it (#1913); `None` = fresh socket.
        self._subscribed: set[str] | None = None
        self._session_sock: Socket | None = None
        #: Per-topic stale resubscribes on the live socket (#1913); these are
        #: subscription ops, not dials, so they never touch the SR-039 budget.
        self.topic_resubscribes = 0
        #: #1955: `req_id` -> unanswered topic-level op; bounded, insertion-ordered (oldest first).
        self._pending: dict[str, _PendingAck] = {}
        self._req_ids = itertools.count(1)
        self._interp: Any = None
        self._key = f"public-{next(_conn_ids)}"
        self._sock: Socket | None = None
        self._session: list[asyncio.Task[Any]] = []
        self._timer: asyncio.Task[None] | None = None
        self._was_live = False
        self._clock = clock
        self._phase = PHASE_CLOSED
        self._phase_since = clock()
        self.attempt = 0
        self.opens = 0

    def _set_phase(self, phase: str) -> None:
        if phase != self._phase:
            self._phase_since = self._clock()
        self._phase = phase
        ingest_ws_up.labels(socket="public").set(1.0 if phase == PHASE_OPEN else 0.0)

    # ---- public API -----------------------------------------------------
    def state(self) -> str:
        """Phase published on chart state entry: open | connecting | degraded | closed."""
        return self._phase

    def phase_since(self) -> float:
        """#1919: `clock()` reading when the current phase was entered (plain value)."""
        return self._phase_since

    def set_desired(self, topics: set[str]) -> None:
        for gone in self._desired - topics:
            self._watchdog.unwatch(gone)
        for new in topics - self._desired:
            self._watchdog.watch(new)
        changed = self._desired != topics
        self._desired = set(topics)
        if changed and self._interp is not None and self.state() == "open":
            interp = self._interp

            async def _changed() -> None:  # `send` returns a Future, not a coroutine
                await interp.send("TOPICS_CHANGED")

            spawn(_changed(), name="ws-topics-changed")

    async def start(self) -> None:
        if self._interp is not None:
            return
        register_runtime(self._key, self)
        result = await build(
            "ws_conn",
            ctx={"conn_key": self._key, "kind": "public"},
            clock=default_clock(),
            lane="platform",
        )
        self._interp = result.interpreter
        await self._interp.send("CONNECT")

    async def stop(self) -> None:
        interp, self._interp = self._interp, None
        self._cancel_timer()
        if interp is not None:
            ids = {sid.rsplit(".", 1)[-1] for sid in interp.current_state_ids}
            event = "SHUTDOWN" if ids & {"live", "backing_off"} else "KILL"
            try:
                await interp.send(event)
            finally:
                await interp.stop()
        await self.teardown_session()
        self._set_phase(PHASE_CLOSED)
        unregister_runtime(self._key)

    def attach_latency(
        self, recorder: StageRecorder, clock_offset_ms: Callable[[], int | None]
    ) -> None:
        """E04-T06: record receive/decode/publish stages on sampled frames."""
        self._latency = recorder
        self._clock_offset_ms = clock_offset_ms

    # ---- B13 runtime hooks (called by bindings/b13_ws_conn.py) ----------
    def is_private(self) -> bool:
        return False

    def budget_exhausted(self) -> bool:
        return self._guard.remaining() == 0

    def bump_attempt(self) -> None:  # entry of `connecting`
        self.attempt += 1
        self._set_phase(PHASE_CONNECTING)

    def reset_attempt(self) -> None:
        self.attempt = 0

    async def open_socket(self) -> None:
        delay = self._guard.reserve()
        if delay > 0:
            await self._sleep(delay)
        self._sock = await self._factory()
        self._subscribed = None  # a fresh socket holds no subscriptions
        self._pending.clear()  # acks for a dead socket never arrive
        self.opens += 1

    async def authenticate(self) -> None:  # public feed: never reached
        return None

    async def subscribe(self) -> None:
        sock = self._sock
        if sock is None:
            raise ConnectionError("no socket to subscribe on")
        held = self._subscribed
        if held is not None:  # live demand change: send only the diff (#1913)
            while held != self._desired:  # demand may move again while we send
                want = set(self._desired)
                await self._send_op(sock, "unsubscribe", held - want)
                await self._send_op(sock, "subscribe", want - held)
                held = self._subscribed = want
            return
        self._set_phase(PHASE_CONNECTING)
        if self._was_live:  # only a (re)opened socket is a resubscribe
            await self.emit_health("resubscribing")
        await self._send_op(sock, "subscribe", self._desired)
        self._subscribed = set(self._desired)
        self._watchdog.reset()

    async def _send_op(self, sock: Socket, op: str, topics: set[str]) -> None:
        for batch in self._planner.plan(topics):
            await self._send_tracked(sock, op, list(batch.topics))

    async def _send_tracked(self, sock: Socket, op: str, topics: list[str]) -> None:
        """Send one topic-level op carrying a `req_id`, and await its ack (#1955)."""
        req_id = f"cv-{next(self._req_ids)}"
        if len(self._pending) >= MAX_PENDING_ACKS:  # never block: drop the oldest, count it
            del self._pending[next(iter(self._pending))]
            ingest_subscribe_rejected_total.labels(reason="overflow").inc()
        self._pending[req_id] = _PendingAck(op, tuple(topics), self._clock() + ACK_TIMEOUT_S)
        await sock.send(json.dumps({"op": op, "args": topics, "req_id": req_id}))

    def _on_ack(self, frame: str) -> None:
        """A `{"success": ...}` reply: settle the pending op it answers (others, e.g. the
        pong, carry no tracked `req_id`). A refused subscribe counts and marks its topics stale,
        so the existing per-topic stale resubscribe retries it."""
        try:
            msg = json.loads(frame)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        req_id = msg.get("req_id")
        pending = self._pending.pop(req_id, None) if isinstance(req_id, str) else None
        if pending is not None and msg.get("success") is not True:
            self._ack_failed(pending, "rejected")

    def _ack_failed(self, pending: _PendingAck, reason: str) -> None:
        ingest_subscribe_rejected_total.labels(reason=reason).inc()
        if pending.op == "subscribe":
            for topic in pending.topics:
                self._watchdog.force_stale(topic)

    def _expire_acks(self) -> None:
        now = self._clock()
        late = [rid for rid, p in self._pending.items() if p.deadline <= now]
        for rid in late:
            self._ack_failed(self._pending.pop(rid), "timeout")

    async def resubscribe_topic(self, topic: str) -> None:
        """Force a fresh snapshot for one topic: unsubscribe then subscribe, paced by the
        E08-T04 connection budget (the guard, `ConnectionGuard`). One the guard cannot book
        within a window is skipped (the guard counts it): the book's snapshot timeout asks
        again (24 §14.2 rule 13)."""
        sock = self._sock
        if sock is None or topic not in self._desired:
            return  # not connected: the (re)subscribe on connect yields the snapshot
        try:
            delay = self._guard.reserve()
        except RateBudgetExceededError:
            return
        if delay > 0:
            await self._sleep(delay)
        await self._send_tracked(sock, "unsubscribe", [topic])
        await self._send_tracked(sock, "subscribe", [topic])

    async def close_socket(self) -> None:
        await self.teardown_session()

    async def teardown_session(self) -> None:
        tasks, self._session = self._session, []
        current = asyncio.current_task()
        for t in tasks:
            if t is not current:
                t.cancel()
        await asyncio.gather(*(t for t in tasks if t is not current), return_exceptions=True)
        sock, self._sock = self._sock, None
        self._session_sock = None
        if sock is not None:
            with contextlib.suppress(Exception):
                await sock.close()

    def start_session(self, interp: Any) -> None:
        """Entered `live`: start reader/ping/watchdog; the supervisor turns the
        first one to finish into a chart event (it never recycles by itself)."""
        sock = self._sock
        if sock is None:
            return
        if sock is self._session_sock and any(not t.done() for t in self._session):
            return  # live -> subscribing -> live on the same socket: keep workers
        self._session_sock = sock
        self._was_live = True

        async def ping() -> None:
            await sock.send(json.dumps({"op": "ping"}))

        workers = {
            "ping": spawn(
                ping_loop(ping, self._sleep, interval_s=self._ping_interval), name="ws-ping"
            ),
            "read": spawn(self._read(sock), name="ws-reader"),
            "watch": spawn(self._watch(), name="ws-watchdog"),
        }

        async def supervise() -> None:
            done, _ = await asyncio.wait(workers.values(), return_when=asyncio.FIRST_COMPLETED)
            first = next(iter(done))
            if first is workers["watch"] and not first.cancelled() and first.exception() is None:
                await interp.send("TOPIC_STALE")
            else:
                await interp.send("SOCKET_CLOSED")

        self._session = [*workers.values(), spawn(supervise(), name="ws-supervisor")]

    def schedule_backoff(self, interp: Any) -> None:
        async def fire() -> None:
            await self._sleep(self._policy.next_delay(self.attempt))
            await interp.send("BACKOFF_DUE")

        self._cancel_timer()
        self._timer = spawn(fire(), name="ws-backoff")

    def schedule_budget_recheck(self, interp: Any) -> None:  # entry of `budget_blocked`
        self._set_phase(PHASE_DEGRADED)

        async def fire() -> None:
            await self._sleep(self._recheck_s)
            await interp.send("BUDGET_RECHECK")
            await interp.send("CONNECT")

        self._cancel_timer()
        self._timer = spawn(fire(), name="ws-budget-recheck")

    async def emit_health(self, state: str) -> None:
        if state == "healthy":
            self._set_phase(PHASE_OPEN)
        elif state == "degraded":
            self._set_phase(PHASE_DEGRADED)
        for topic in sorted(self._desired) or ["*"]:
            await self._publish(feed_health(topic, state, 0.0, now_us=self._now_us()))

    # ---- internals ------------------------------------------------------
    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()

    async def _publish(self, event: FeedHealthEvent) -> None:
        if self._bus is not None:
            await self._bus.publish(Topic(env=self._env, domain="health", detail="feed"), event)

    async def _read(self, sock: Socket) -> None:
        while True:
            frame = await sock.recv(MAX_FRAME_BYTES)
            if len(frame) > MAX_FRAME_BYTES:
                raise ValueError("ws frame exceeds MAX_FRAME_BYTES")
            if frame.startswith(_ACK_PREFIX):
                self._on_ack(frame)  # still forwarded below: the parsers ignore op replies
            rec = self._latency
            if rec is None or not rec.sample():
                self._on_message(frame)  # unsampled: no stamps, no allocation
                continue
            self._record_sampled(rec, frame)

    def _record_sampled(self, rec: StageRecorder, frame: str) -> None:
        """E04-T06: stage stamps for a 1-in-N sampled frame only.

        receive -> decode (`ts` extracted) -> hand-off to the bounded ingestion
        queue (the publish boundary). Exchange stage uses the injected
        ClockGuard offset; `None` (unmeasured) leaves it unavailable."""
        t_recv = self._now_ms()
        t_exchange = t_recv
        try:
            ts = json.loads(frame).get("ts")
            if isinstance(ts, int):
                t_exchange = ts
        except (ValueError, AttributeError):
            pass
        t_parsed = self._now_ms()
        self._on_message(frame)
        t_emitted = self._now_ms()
        rec.record(
            StageStamps(t_exchange, t_recv, t_parsed, t_parsed, t_emitted),
            self._clock_offset_ms(),
        )

    async def _watch(self) -> None:
        """Publish `stale` per topic and resubscribe just that topic on the live
        socket (#1913). Returns (-> B13 `TOPIC_STALE`, socket recycle) only when
        every watched topic is stale: then the socket itself is suspect."""
        while True:
            await self._sleep(self._check_interval)
            self._expire_acks()
            if stale := self._watchdog.check():
                for topic in stale:
                    await self._publish(feed_health(topic, "stale", 0.0, now_us=self._now_us()))
                if self._watchdog.all_stale():
                    return
                for topic in stale:
                    await self._resubscribe_stale(topic)

    async def _resubscribe_stale(self, topic: str) -> None:
        """One unsubscribe+subscribe for a newly stale topic. It stays marked
        stale until a frame arrives, so a silent (e.g. delisted) topic is
        resubscribed once per staleness episode, never in a loop."""
        sock = self._sock
        if sock is None or topic not in self._desired:
            return
        await self._send_tracked(sock, "unsubscribe", [topic])
        await self._send_tracked(sock, "subscribe", [topic])
        self.topic_resubscribes += 1
