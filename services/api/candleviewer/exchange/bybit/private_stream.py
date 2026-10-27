"""The exchange's private stream (G-8b, #3963; 24 §14.2 rule 13): one socket per account, on B13.

`PrivateStreams` is the adapter's registry of private streams, one per account, at most
`MAX_STREAMS`, all drawing on the adapter's one `ConnectionBudget` (C-12.7). It serves the loop of
its first stream's `open` (#913 L1d-2a, D6). `open(account)` refuses before anything is signed,
dialled or built: a call from any other loop, another environment's account, a `key_ref` that is no
`api_keys` id, a key its `KeyTombstones` holds (closed by a revoke or rotation, or marked by three
`auth` refusals; the adapter shares one table with every registry it builds), an account that has
a stream, and a stream past the cap (`RateBudgetExceededError`, `reason` `stream_cap`). Then it
builds the account's B13 `ws_conn` chart through the factory (lane `platform`) and returns the
stream, which raises nothing more: it yields events and `PrivateStreamStatus`es in arrival order
and ends after its `closed` status. `close_key` returns within `KEY_CLOSE_BOUND_S`; past that it
pages and raises `PrivateStreamCloseOverran` while the close runs on.

`_PrivateConn` is B13's runtime for one stream. The chart drives its hooks on lifecycle edges
only (dial, `auth`, subscribe, live, back off, close); frames, pings and the watchdog are plain
tasks that never query the interpreter (C-2.20, INV-B13-d) and send it one event per socket,
only while that socket is current. Every dial signs a fresh `auth` through M2 (`sign_ws_auth`),
`expires` 10 s ahead of the exchange clock, signed just before it is sent and never sent once the
stream is closing. A ping goes out every 5 s; any frame re-arms an absolute 10 s deadline held
here, outside the chart (INV-B13-e). Backoff is `ReconnectPolicy`'s 0.5 s to 30 s with jitter;
the attempt count resets once an epoch has stayed live 30 s, and a new dial waits until the
consumer has read the last epoch's `down` (counted in `bybit_private_reconnect_waited_total` when
it has to wait). Three consecutive exchange refusals of `auth`, each
while the clock offset is measured, or M2's refusal to sign end the stream: the runtime sends
B13 `SHUTDOWN` instead of `BACKOFF_DUE`, and B13's close queues `closed`.

What leaves: the open's refusals, which are bare taxonomy errors (no cause, context or
traceback, SR-E29-08), a revoke's overrun (`PrivateStreamCloseOverran`, as bare), and the
stream's items. The hooks B13 invokes raise only fixed texts with no cause or context, so the
library's failure log (`Service ... failed`, with its traceback) holds no frame, reply or key. No
log line holds a frame, a reply's text, a key id or a signature.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, Environment, TsUs
from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.errors import (
    AuthError,
    ExchangeError,
    PrivateStreamCloseOverran,
    RateBudgetExceededError,
)
from candleviewer.exchange.base.guards import check_key_ref, key_ref_id
from candleviewer.exchange.base.models import (
    AccountRef,
    PrivateEvent,
    PrivateStreamReason,
    PrivateStreamState,
    PrivateStreamStatus,
)
from candleviewer.exchange.base.reconnect import (
    ConnectionBudget,
    ReconnectPolicy,
    ws_conn_budget_refused_total,
)
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS
from candleviewer.exchange.bybit.errors import FrameTooLarge
from candleviewer.exchange.bybit.metrics import (
    bybit_private_frames_rejected_total,
    bybit_private_reconnect_waited_total,
    bybit_private_subscribe_refused_total,
    bybit_private_ws_auth_total,
    bybit_private_ws_disconnects_total,
    bybit_private_ws_streams,
)
from candleviewer.exchange.bybit.private_parse import (
    FrameRejected,
    Push,
    Reply,
    classify,
    read_push,
)
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.exchange.bybit.trading import _bare
from candleviewer.observability.context import spawn
from candleviewer.secrets import KekUnavailable, SecretsError
from candleviewer.statechart import build
from candleviewer.statechart.bindings.b13_ws_conn import register_runtime, unregister_runtime
from candleviewer.statechart.factory import default_clock

if TYPE_CHECKING:
    from candleviewer.exchange.base.ports import PrivateStream
    from candleviewer.secrets import SigningCapability
    from candleviewer.statechart.bindings.b13_ws_conn import WsConnRuntime

__all__ = [
    "AUTH_TIMEOUT_S",
    "DATA_SLOTS",
    "FRAME_BYTES",
    "KEY_CLOSE_BOUND_S",
    "MAX_AUTH_REFUSALS",
    "MAX_STREAMS",
    "OPTIONAL_OPS",
    "PING_INTERVAL_S",
    "REQUIRED_OPS",
    "STABLE_RESET_S",
    "STATUS_SLOTS",
    "WATCHDOG_S",
    "KeyTombstones",
    "PrivateStreams",
    "StreamConnect",
    "StreamOpener",
    "StreamSocket",
]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: G-8b ruling 4: ping every 5 s; 10 s with no frame ends the socket (`PONG_DEADLINE`).
PING_INTERVAL_S: Final = 5.0
WATCHDOG_S: Final = 10.0
#: The dial, the `auth` reply (M2's signature included) and each subscribe acknowledgement.
DIAL_TIMEOUT_S: Final = 5.0
AUTH_TIMEOUT_S: Final = 5.0
SUBSCRIBE_TIMEOUT_S: Final = 5.0
#: A socket's close, so a stalled peer cannot hold a revoke (SR-E27-17: within 1 s).
CLOSE_TIMEOUT_S: Final = 1.0
#: How long `close_key` waits for its closes (#913 L1d-2a, ruling Q6): past it the revoke pages
#: and raises while the closes run on.
KEY_CLOSE_BOUND_S: Final = CLOSE_TIMEOUT_S + 1.0
#: A call from another loop pages at most once a window (D6's, #913 L2).
WRONG_LOOP_PAGE_S: Final = 5.0
#: The attempt count resets once an epoch has stayed live this long (ruling 4).
STABLE_RESET_S: Final = 30.0
#: How long `budget_blocked` waits before B13 asks the budget again.
BUDGET_RECHECK_S: Final = 1.0
#: SR-E27-17: `expires` at most 10 s ahead of the exchange clock (as the key probe signs).
EXPIRES_AHEAD_MS: Final = 10_000
#: Ruling 10: consecutive exchange refusals of `auth` that end the stream.
MAX_AUTH_REFUSALS: Final = 3
#: Ruling 9: the stream's queue, events and statuses; one frame's read bound (the connector's
#: `max_size` too).
DATA_SLOTS: Final = 2048
STATUS_SLOTS: Final = 8
FRAME_BYTES: Final = 1_048_576
#: Ruling 5: open private streams, at most.
MAX_STREAMS: Final = 64
#: A frame's copies of the key id and signature this socket's `auth` sent are masked before it is
#: read, as the REST client masks its answers (`rest._mask`): no venue echo of either can reach an
#: event or a record (SR-E29-08). Values shorter than this are never ours.
_MASK: Final = "**redacted**"
_MIN_MASKED_LEN: Final = 8
#: Keys `close_key` closed and keys three refusals marked, remembered at most (oldest dropped
#: first; M2 refuses a destroyed key either way).
KEYS_REMEMBERED: Final = 4096
#: The subscribe ops, sent one at a time, each acknowledged before the next (24 §14.2 rule 13):
#: the required ones, then the optional fast fills, whose refusal leaves the socket up (ruling 2).
REQUIRED_OPS: Final = (("order.linear", "execution.linear", "position.linear"), ("wallet",))
OPTIONAL_OPS: Final = (("execution.fast.linear",),)

type ClosedReason = Literal[
    "shutdown", "key_revoked", "key_rotated", "key_unusable", "auth_refused", "consumer_closed"
]
type DownReason = Literal["socket_closed", "pong_timeout", "subscribe_refused", "slow_consumer"]
type _AuthResult = Literal[
    "granted",
    "refused",
    "unknown",
    "timeout",
    "transport_error",
    "key_unusable",
    "vault_unavailable",
    "closing",
]
type _SubscribeResult = Literal["granted", "refused", "timeout", "transport_error", "overflow"]
type _Item = PrivateEvent | PrivateStreamStatus


class StreamSocket(Protocol):
    """One private-stream connection: text frames out, frames of at most `max_bytes` in."""

    async def send(self, frame: str) -> None: ...
    async def recv(self, max_bytes: int) -> str: ...
    async def close(self) -> None: ...


#: Dials a `PRIVATE_WS_URLS` value (the adapter injects its connector).
StreamConnect = Callable[[str], Awaitable[StreamSocket]]


class StreamOpener(Protocol):
    """What opens an account's private stream for a trading port (#913 L1d-2a): the adapter's
    registry, `PrivateStreams`, or the stream source the order lane's composition root gives its
    port (L1d-2b's bridge to the registry)."""

    async def open(
        self, account: AccountRef, *, clock_offset_ms: Callable[[], int | None] | None = None
    ) -> PrivateStream: ...


class _Closing(Exception):
    """The stream began closing while an `auth` was being signed: nothing is sent."""


class KeyTombstones:
    """The keys a revoke or a rotation closed, with the reason, and the keys three `auth` refusals
    marked, each remembered up to `KEYS_REMEMBERED`, oldest dropped first (M2 refuses a destroyed
    key either way). The adapter holds one and shares it, by reference, with every registry it
    builds (RC-G8B-03): a key closed before any registry existed, or through another one, is
    refused by all of them. Only an operator's `reopen` clears a mark; a closed key stays
    closed. It takes no lock: the serving loop owns it, as it owns the registries over it, and
    makes every write but one, a mis-wired `close_private_streams` from another loop, which still
    records its key here, fail-safe, before the registry refuses the call and pages."""

    def __init__(self) -> None:
        self._closed: OrderedDict[str, ClosedReason] = OrderedDict()
        self._refused: OrderedDict[str, None] = OrderedDict()

    def close(self, key_ref: str, reason: Literal["key_revoked", "key_rotated"]) -> None:
        """Tombstone the key; a `key_ref` that is no `api_keys` id is refused (`ValueError`) before
        anything is recorded."""
        key_ref_id(key_ref)
        _remember(self._closed, key_ref, reason)

    def mark_refused(self, key_ref: str) -> None:
        _remember(self._refused, key_ref, None)

    def reopen(self, key_ref: str) -> bool:
        """An operator's action (ruling 10): `True` when three refusals had marked the key, which
        may open streams again."""
        if key_ref not in self._refused:
            return False
        del self._refused[key_ref]
        logger().warning("bybit_private_key_reopened")
        return True

    def refuses(self, key_ref: str) -> bool:
        return key_ref in self._closed or key_ref in self._refused


def _wall_ms() -> int:
    return int(time.time() * 1000)


def _wall_us() -> TsUs:
    return int(time.time() * 1_000_000)


def _ops_label(topics: tuple[str, ...]) -> str:
    """A subscribe op's topics as one bounded `topic` label (`order+execution+position`)."""
    return "+".join(topic.removesuffix(".linear") for topic in topics)


_ids = itertools.count(1)


class _Queue:
    """A stream's queue (ruling 9): `DATA_SLOTS` events and `STATUS_SLOTS` statuses in one arrival
    order, for one consumer. An event batch that does not fit is refused whole (the epoch ends as
    `slow_consumer`); a `heartbeat` or a mid-epoch `resyncing` is not queued while one of its kind
    is pending. A stream queues at most five statuses unread: a new dial waits until no `down` is
    pending (`drained`), so an unread epoch's statuses never pile up behind the next one's."""

    def __init__(self) -> None:
        self._items: deque[_Item] = deque()
        self._events = 0
        self._statuses = 0
        self._downs = 0
        self._ready = asyncio.Event()
        self._no_down = asyncio.Event()
        self._no_down.set()
        self.heartbeat_pending = False
        self.rejected_pending = False
        self._ended = False

    def pending(self) -> int:
        """Items queued now: `get` returns that many with no wait."""
        return len(self._items)

    def fits(self, count: int) -> bool:
        return self._events + count <= DATA_SLOTS

    def put_events(self, events: tuple[PrivateEvent, ...] | list[PrivateEvent]) -> None:
        self._items.extend(events)
        self._events += len(events)
        if events:
            self._ready.set()

    def put_status(self, status: PrivateStreamStatus) -> None:
        if self._statuses >= STATUS_SLOTS:  # beyond the design bound: a defect, made visible
            logger().error("bybit_private_status_slots_exceeded", state=status.state)
        self._items.append(status)
        self._statuses += 1
        if status.state == "heartbeat":
            self.heartbeat_pending = True
        elif status.reason == "rejected_frame":
            self.rejected_pending = True
        elif status.state == "down":
            self._downs += 1
            self._no_down.clear()
        self._ready.set()

    def end(self) -> None:
        """The consumer closed the stream: a read waiting now, in any task, or any later one finds
        the stream over."""
        self._ended = True
        self._ready.set()

    async def get(self) -> _Item | None:
        """The next item in arrival order, or `None` once the consumer closed the stream."""
        while not self._items:
            if self._ended:
                return None
            self._ready.clear()
            await self._ready.wait()
        item = self._items.popleft()
        if isinstance(item, PrivateEvent):
            self._events -= 1
            return item
        self._statuses -= 1
        if item.state == "heartbeat":
            self.heartbeat_pending = False
        elif item.reason == "rejected_frame":
            self.rejected_pending = False
        elif item.state == "down":
            self._downs -= 1
            if not self._downs:
                self._no_down.set()
        return item

    @property
    def down_pending(self) -> bool:
        """A `down` is queued that the consumer has not read yet."""
        return not self._no_down.is_set()

    async def drained(self) -> None:
        """Until the consumer has read every `down` queued."""
        await self._no_down.wait()


class _PrivateConn:
    """B13's runtime for one account's stream: the `WsConnRuntime` hooks (`b13_ws_conn.py`), its
    socket and session tasks, and the plain phase hot paths read (`state()`, INV-B13-d).

    `epoch` counts the sockets this stream opened; a status carries the one it belongs to, and
    every event this runtime sends B13 names the epoch it was armed for, so one left from an
    earlier socket (the chart defers what a state does not take) never moves a later one."""

    def __init__(
        self,
        owner: PrivateStreams,
        account: AccountRef,
        key_id: UUID,
        clock_offset_ms: Callable[[], int | None] | None,
    ) -> None:
        self.attempt = 0
        self.account = account
        self.key_ref = account.key_ref
        self.conn_key = f"private-{next(_ids)}"
        self.queue = _Queue()
        self._owner = owner
        self._key_id = key_id
        self._offset = clock_offset_ms
        self._interp: Any = None
        self._sock: StreamSocket | None = None
        self._epoch = 0
        self._authed = False
        self._down_epoch = -1
        self._lives = 0
        self._refusals = 0
        self._down_reason: DownReason = "socket_closed"
        self._terminal: ClosedReason | None = None
        self._stop = False
        self._closed = False
        self._machine_stopping = False
        self._closing: asyncio.Task[None] | None = None
        self._pending: list[PrivateEvent] = []
        self._session: list[asyncio.Task[Any]] = []
        self._timer: asyncio.Task[None] | None = None
        self._stable: asyncio.Task[None] | None = None
        self._deadline = 0.0
        self._phase = "closed"
        #: What this socket's `auth` sent that a frame must never carry on: masked on read.
        self._masks: tuple[str, ...] = ()

    # -- plain state, never the interpreter (INV-B13-d) -------------------------------------------

    def state(self) -> str:
        """The phase B13's hooks publish: `connecting`, `open`, `degraded` or `closed`."""
        return self._phase

    @property
    def stopping(self) -> bool:
        """A close began (`halt`), or B13's own end queued `closed` (RC-G8B-04): either way a
        later `close_key` waits for the stream and does not name it."""
        return self._stop or self._closed

    def bind(self, interp: Any) -> None:
        self._interp = interp

    # -- B13 hooks --------------------------------------------------------------------------------

    def is_private(self) -> bool:
        return True

    def budget_exhausted(self) -> bool:
        return self._owner.budget.lane("private").remaining() == 0

    def bump_attempt(self) -> None:  # entry of `connecting`
        self.attempt += 1
        self._phase = "connecting"

    def reset_attempt(self) -> None:
        """Entering `live`: the attempt count resets once this epoch has stayed live 30 s, so a
        flapping socket keeps backing off (INV-B13-b)."""
        self._cancel_stable()
        epoch = self._epoch

        async def stable() -> None:
            await self._owner.sleep(STABLE_RESET_S)
            if epoch == self._epoch and self._phase == "open" and not self._stop:
                self.attempt = 0

        self._stable = self._owner.spawn(stable(), "private-ws-stable")

    async def open_socket(self) -> None:
        """Take a private slot of the budget, waiting its delay out, then dial this environment's
        private stream under its bound, unless the stream began closing meanwhile. A failed dial
        leaves as one fixed text."""
        if self._stop:
            raise _bare(ConnectionError("the private stream is closing"))
        delay = self._owner.budget.lane("private").reserve()
        if delay > 0:
            await self._owner.sleep(delay)
            if self._stop:  # closed while it waited: nothing is dialled
                raise _bare(ConnectionError("the private stream is closing"))
        sock = await self._owner.dial()
        if self._stop:
            await self._owner.close_quietly(sock)
            raise _bare(ConnectionError("the private stream is closing"))
        self._epoch += 1
        self._authed = False
        self._down_reason = "socket_closed"
        self._pending = []
        self._masks = ()
        self._sock = sock

    async def authenticate(self) -> None:
        """One `auth`, signed by M2 for this dial (ruling 10's count applied); anything but a grant
        raises one fixed text, and the chart backs off, or closes the stream when it is over. The
        third refusal marks the key at once, until an operator reopens it or the account takes a
        new key, whatever close queues first (RC-G8B-04)."""
        sock = self._sock
        if sock is None or self._stop:
            raise _bare(ConnectionError("the private stream is closing"))
        measured = None if self._offset is None else self._offset()
        result = await self._auth(sock, 0 if measured is None else measured)
        if result != "closing":
            bybit_private_ws_auth_total.labels(result=result).inc()
        if result == "granted":
            self._refusals = 0
            self._authed = True
            self._status("heartbeat", "evidence")
            return
        if result == "refused" and measured is not None:  # OQ-4: never on an unmeasured clock
            self._refusals += 1
            if self._refusals >= MAX_AUTH_REFUSALS:
                self._terminal = "auth_refused"
                self._owner.mark_refused(self.key_ref)
        elif result == "key_unusable":
            self._terminal = "key_unusable"
        logger().warning(
            "bybit_private_auth_failed",
            account_id=str(self.account.account_id),
            result=result,
            refusals=self._refusals,
            epoch=self._epoch,
        )
        raise _bare(ConnectionError("the private stream's auth was not granted"))

    async def subscribe(self) -> None:
        """The subscribe ops, one at a time, each acknowledged before the next; a required op
        refused or unanswered fails the socket, the optional one is only counted."""
        sock = self._sock
        if sock is None or self._stop:
            raise _bare(ConnectionError("the private stream is closing"))
        ops = [(topics, True) for topics in REQUIRED_OPS] + [(t, False) for t in OPTIONAL_OPS]
        for topics, required in ops:
            result = await self._subscribe_op(sock, topics)
            if result == "granted":
                continue
            if result in ("refused", "timeout"):
                bybit_private_subscribe_refused_total.labels(topic=_ops_label(topics)).inc()
                if not required:
                    continue
                self._down_reason = "subscribe_refused"
            else:
                self._down_reason = "slow_consumer" if result == "overflow" else "socket_closed"
            raise _bare(ConnectionError("the private stream's subscription failed"))

    def start_session(self, interp: Any) -> None:
        """Every required op acknowledged: queue `resyncing` ahead of the epoch's rows (the ones
        read while subscribing first), then start the reader, the pinger, the watchdog and the
        supervisor that turns the first of them to end into one chart event for this socket."""
        sock = self._sock
        if sock is None or self._stop:
            return
        self._status("resyncing", "connected" if self._lives == 0 else "reconnected")
        self._lives += 1
        pending, self._pending = self._pending, []
        self.queue.put_events(pending)
        self._deadline = self._owner.monotonic() + WATCHDOG_S
        epoch = self._epoch
        # The session's own tasks: a dropped socket ends them routinely, so their outcome is
        # read by `teardown_session` (never logged), not by the registry's failure log.
        workers = {
            "read": spawn(self._read(sock), name="private-ws-reader"),
            "ping": spawn(self._ping(sock), name="private-ws-ping"),
            "watch": spawn(self._watch(), name="private-ws-watchdog"),
        }
        supervisor = spawn(self._supervise(interp, epoch, workers), name="private-ws-supervisor")
        self._session = [*workers.values(), supervisor]
        self._phase = "open"

    def schedule_backoff(self, interp: Any) -> None:
        """Entering `backing_off`: a stream that is over is closed (`SHUTDOWN`, ruling 10); else
        `BACKOFF_DUE` after the jittered delay, once the consumer has read the last `down`."""
        self._cancel_timer()
        if self._stop:
            return
        epoch = self._epoch
        if self._terminal is not None:
            self._timer = self._owner.spawn(
                self._send_armed(interp, "SHUTDOWN", epoch), "private-ws-end"
            )
            return
        delay = self._owner.policy.next_delay(self.attempt)

        async def due() -> None:
            await self._owner.sleep(delay)
            if self.queue.down_pending:  # a stalled consumer holds the dial (OQ-D): counted once
                bybit_private_reconnect_waited_total.inc()
                await self.queue.drained()
            await self._send_armed(interp, "BACKOFF_DUE", epoch)

        self._timer = self._owner.spawn(due(), "private-ws-backoff")

    def schedule_budget_recheck(self, interp: Any) -> None:  # entry of `budget_blocked`
        self._phase = "degraded"
        self._cancel_timer()
        epoch = self._epoch

        async def recheck() -> None:
            await self._owner.sleep(BUDGET_RECHECK_S)
            await self._send_armed(interp, "BUDGET_RECHECK", epoch)
            await self._send_armed(interp, "CONNECT", epoch)

        self._timer = self._owner.spawn(recheck(), "private-ws-budget")

    async def emit_health(self, state: str) -> None:
        """`healthy` on `live`; `degraded` on `backing_off` or `budget_blocked`, which queues the
        epoch's `down` once, after its last row, if it authenticated."""
        if state == "healthy":
            self._phase = "open"
            return
        self._phase = "degraded"
        if self._authed and self._down_epoch != self._epoch and not self._stop:
            self._down_epoch = self._epoch
            self._status("down", self._down_reason)
            bybit_private_ws_disconnects_total.labels(reason=self._down_reason).inc()
            logger().warning(
                "bybit_private_stream_down",
                account_id=str(self.account.account_id),
                reason=self._down_reason,
                epoch=self._epoch,
            )

    async def teardown_session(self) -> None:
        """Entering `backing_off`, or closing: the session's tasks, then the socket."""
        tasks, self._session = self._session, []
        current = asyncio.current_task()
        for task in tasks:
            if task is not current:
                task.cancel()
        await asyncio.gather(*(t for t in tasks if t is not current), return_exceptions=True)
        self._cancel_stable()
        self._pending = []
        sock, self._sock = self._sock, None
        if sock is not None:
            await self._owner.close_quietly(sock)
        self._masks = ()

    async def close_socket(self) -> None:
        """B13's `closing`: the session ends, and a stream that is over queues its `closed`."""
        await self.teardown_session()
        if self._terminal is not None:
            self._end(self._terminal)

    # -- the closing path (consumer, shutdown, revoke) --------------------------------------------

    def halt(self) -> None:
        """Stop at once, with no await: no dial, `auth` or event is sent from now on, and the
        session's tasks and timers are cancelled (their awaiting is `close`'s)."""
        self._stop = True
        self._cancel_timer()
        self._cancel_stable()
        for task in self._session:
            task.cancel()

    def close_soon(self, reason: ClosedReason) -> asyncio.Task[None]:
        """Stop at once and close the stream in a task the registry owns, started once, by the
        first to ask, whose `reason` is the one queued: a caller cancelled while it awaits the
        close never leaves the stream stopped with its socket open (SR-E27-17)."""
        if self._closing is None:
            self.halt()
            self._closing = self._owner.spawn(self._close(reason), "private-ws-close")
        return self._closing

    async def close(self, reason: ClosedReason) -> None:
        """`close_soon(reason)`, returning once the socket is closed (SR-E27-17)."""
        await asyncio.shield(self.close_soon(reason))

    async def _close(self, reason: ClosedReason) -> None:
        """Close the socket within `CLOSE_TIMEOUT_S`, queue `closed` (not for the consumer's own
        close, which reads nothing more), and hand B13's stop to a task the registry owns."""
        tasks, self._session = self._session, []
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pending = []
        sock, self._sock = self._sock, None
        if sock is not None:
            await self._owner.close_quietly(sock)
        self._end(reason)
        if not self._machine_stopping:
            self._owner.spawn(self.stop_machine(), "private-ws-stop")

    async def stop_machine(self) -> None:
        """B13's own close: `SHUTDOWN` where the chart takes it (`live`, `backing_off`), else
        `KILL`, which cancels the service in flight; then the interpreter stops."""
        self._machine_stopping = True
        interp, self._interp = self._interp, None
        if interp is not None:
            if interp.status == "running":
                ids = {sid.rsplit(".", 1)[-1] for sid in interp.current_state_ids}
                event = "SHUTDOWN" if ids & {"live", "backing_off"} else "KILL"
                with contextlib.suppress(Exception):
                    await interp.send(event)
            with contextlib.suppress(Exception):
                await interp.stop(drain=True, timeout=CLOSE_TIMEOUT_S)
        await self.teardown_session()
        unregister_runtime(self.conn_key)

    def _end(self, reason: ClosedReason) -> None:
        """Queue `closed` once, last; count and log it."""
        if self._closed:
            return
        self._closed = True
        self._phase = "closed"
        if reason != "consumer_closed":
            self._status("closed", reason)
        bybit_private_ws_disconnects_total.labels(reason=reason).inc()
        logger().warning(
            "bybit_private_stream_closed",
            account_id=str(self.account.account_id),
            reason=reason,
            epoch=self._epoch,
        )

    # -- internals ---------------------------------------------------------------------------------

    def _status(self, state: PrivateStreamState, reason: PrivateStreamReason) -> None:
        if state == "heartbeat" and self.queue.heartbeat_pending:
            return  # coalesced: one pending at most
        if reason == "rejected_frame" and self.queue.rejected_pending:
            return
        status = PrivateStreamStatus(
            account_id=self.account.account_id,
            state=state,
            reason=reason,
            epoch=self._epoch,
            ts=self._owner.now_us(),
        )
        self.queue.put_status(status)

    async def _send_armed(self, interp: Any, event: str, epoch: int) -> None:
        """An event armed at `epoch`, sent only while that socket is current and the stream is
        not closing: one left from an earlier socket is dropped, never deferred into a later one."""
        if self._stop or epoch != self._epoch:
            return
        await interp.send(event)

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()

    def _cancel_stable(self) -> None:
        stable, self._stable = self._stable, None
        if stable is not None and stable is not asyncio.current_task():
            stable.cancel()

    async def _auth(self, sock: StreamSocket, offset_ms: int) -> _AuthResult:
        """The `auth` exchange under its bound, as a result; nothing it raises leaves."""
        signer = BybitSigner(self._owner.credentials, self._key_id, purpose="sign_ws_auth")
        result: _AuthResult
        try:
            exchange = self._auth_exchange(sock, signer, offset_ms)
            result = await self._owner.bounded(exchange, AUTH_TIMEOUT_S)
        except TimeoutError:  # an `OSError`: before the transport arm
            result = "timeout"
        except KekUnavailable:  # the vault, not the key: backed off, no verdict (24 §14.4)
            result = "vault_unavailable"
        except SecretsError:  # M2 will not sign with the key: the stream is over
            result = "key_unusable"
        except _Closing:
            result = "closing"
        except Exception:  # a dropped socket, a failed send: a transport error, never counted
            result = "transport_error"
        return result

    async def _auth_exchange(
        self, sock: StreamSocket, signer: BybitSigner, offset_ms: int
    ) -> _AuthResult:
        # Signed just before it is sent, and bound to no name here: no traceback holds it.
        await sock.send(await self._auth_frame(signer, offset_ms))
        while True:
            item = self._classify(await self._frame(sock))
            if isinstance(item, Reply) and item.op == "auth":
                if item.granted is None:
                    return "unknown"
                return "granted" if item.granted else "refused"

    async def _auth_frame(self, signer: BybitSigner, offset_ms: int) -> str:
        """The `auth` op (24 §14.3 "Auth (WS)"), `expires` 10 s ahead of the exchange clock; a
        stream that began closing during M2's borrow sends nothing (SR-E27-17)."""
        expires = self._owner.wall_ms() + offset_ms + EXPIRES_AHEAD_MS
        signed = await signer.sign_ws_auth(expires_ms=expires)
        if self._stop:
            raise _Closing
        sent = (signed.api_key, signed.signature)
        self._masks = tuple(value for value in sent if len(value) >= _MIN_MASKED_LEN)
        return json.dumps({"op": "auth", "args": [signed.api_key, expires, signed.signature]})

    async def _subscribe_op(self, sock: StreamSocket, topics: tuple[str, ...]) -> _SubscribeResult:
        result: _SubscribeResult
        try:
            exchange = self._subscribe_exchange(sock, topics)
            result = await self._owner.bounded(exchange, SUBSCRIBE_TIMEOUT_S)
        except TimeoutError:
            result = "timeout"
        except Exception:
            result = "transport_error"
        return result

    async def _subscribe_exchange(
        self, sock: StreamSocket, topics: tuple[str, ...]
    ) -> _SubscribeResult:
        """One op and its acknowledgement; pushes read meanwhile wait for `resyncing`, a frame
        that cannot be read is counted (the coming `resyncing` covers it)."""
        await sock.send(json.dumps({"op": "subscribe", "args": list(topics)}))
        while True:
            item = self._classify(await self._frame(sock))
            if isinstance(item, Reply):
                if item.op == "subscribe":
                    return "granted" if item.granted is True else "refused"
                continue
            if item is None:
                continue
            events = self._rows(item)
            if events is None:
                continue
            if len(self._pending) + len(events) > DATA_SLOTS:
                return "overflow"
            self._pending.extend(events)

    async def _frame(self, sock: StreamSocket) -> str:
        """The next frame, of at most `FRAME_BYTES`. One above it ends the socket, counted as
        `oversize`, whether the socket refused it (`FrameTooLarge`: production's library closes
        it 1009 first) or handed it over whole."""
        try:
            frame: str | None = await sock.recv(FRAME_BYTES)
        except FrameTooLarge:
            frame = None  # raised below, outside this handler: no socket error rides on it
        if frame is None or len(frame) > FRAME_BYTES:
            bybit_private_frames_rejected_total.labels(reason="oversize").inc()
            raise _bare(ConnectionError("a private frame above the read bound"))
        return frame

    def _classify(self, frame: str) -> Reply | Push | None:
        """The frame read, our own key id and signature masked first, or `None` when it is
        rejected (counted)."""
        for value in self._masks:
            frame = frame.replace(value, _MASK)
        try:
            return classify(frame)
        except FrameRejected as rejected:
            bybit_private_frames_rejected_total.labels(reason=rejected.reason).inc()
        return None

    def _rows(self, push: Push) -> tuple[PrivateEvent, ...] | None:
        try:
            return read_push(push, self.account, now_us=self._owner.now_us())
        except FrameRejected as rejected:
            bybit_private_frames_rejected_total.labels(reason=rejected.reason).inc()
        return None

    async def _read(self, sock: StreamSocket) -> None:
        """The live reader: every frame re-arms the watchdog; a pong is evidence, a push's rows
        are queued whole, a frame it cannot read is followed by `resyncing`. It returns, ending
        the socket, when an event finds the queue full (`slow_consumer`)."""
        while True:
            frame = await self._frame(sock)
            self._deadline = self._owner.monotonic() + WATCHDOG_S
            item = self._classify(frame)
            if isinstance(item, Reply):
                if item.op == "pong":
                    self._status("heartbeat", "evidence")
                elif item.op == "auth":  # no `auth` reply is due on a live socket
                    bybit_private_frames_rejected_total.labels(reason="unknown_frame").inc()
                    self._status("resyncing", "rejected_frame")
                continue  # a late `subscribe` reply: the optional op's
            events = None if item is None else self._rows(item)
            if events is None:
                self._status("resyncing", "rejected_frame")
                continue
            if not self.queue.fits(len(events)):
                self._down_reason = "slow_consumer"
                return
            self.queue.put_events(events)

    async def _ping(self, sock: StreamSocket) -> None:
        while True:
            await self._owner.sleep(PING_INTERVAL_S)
            await sock.send('{"op":"ping"}')

    async def _watch(self) -> None:
        """Returns once `WATCHDOG_S` has passed with no frame: the absolute deadline the reader
        re-arms (INV-B13-e)."""
        while (left := self._deadline - self._owner.monotonic()) > 0:
            await self._owner.sleep(left)

    async def _supervise(
        self, interp: Any, epoch: int, workers: dict[str, asyncio.Task[None]]
    ) -> None:
        done, _ = await asyncio.wait(workers.values(), return_when=asyncio.FIRST_COMPLETED)
        watch = workers["watch"]
        if watch in done and not watch.cancelled() and watch.exception() is None:
            self._down_reason = "pong_timeout"
            await self._send_armed(interp, "PONG_DEADLINE", epoch)
        else:
            await self._send_armed(interp, "SOCKET_CLOSED", epoch)


class _Stream:
    """What `subscribe_private` returns (`PrivateStream`): the account's items in arrival order,
    ending after its `closed` status. `aclose()`, even before a read or from another task
    (a read waiting there ends), or the consumer's task being cancelled mid-read closes the
    stream, in a task the registry owns, and frees the account once the socket is closed."""

    def __init__(self, owner: PrivateStreams, conn: _PrivateConn) -> None:
        self._owner = owner
        self._conn = conn
        self._done = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> _Item:
        if self._done:
            raise StopAsyncIteration
        try:
            item = await self._conn.queue.get()
        except asyncio.CancelledError:
            self._abandon()
            raise
        if item is None:  # the consumer closed the stream, from another task
            raise StopAsyncIteration
        if isinstance(item, PrivateStreamStatus) and item.state == "closed":
            self._done = True
            self._owner.release(self._conn)
        return item

    def ready(self) -> int:
        """How many items `__anext__` returns now, each with no wait, in arrival order: the batch
        the order lane's bridge takes in one hop (#913 L1d-2b); 0 once the stream is done."""
        return 0 if self._done else self._conn.queue.pending()

    async def aclose(self) -> None:
        """Close the stream; idempotent. Returns once the socket is closed; should this call be
        cancelled first, the registry's task still finishes the close and frees the account."""
        if not self._done:
            self._done = True
            await asyncio.shield(self._close())
        self._owner.release(self._conn)

    def _abandon(self) -> None:
        """Cancelled mid-read: stop now, with no await, and let the registry finish the close."""
        if not self._done:
            self._done = True
            self._close()

    def _close(self) -> asyncio.Task[None]:
        """The consumer's own close: the queue ends at once, the close runs in the registry's
        task, and the account is freed once it is done."""
        self._conn.queue.end()
        closing = self._conn.close_soon("consumer_closed")
        closing.add_done_callback(lambda _: self._owner.release(self._conn))
        return closing


class PrivateStreams:
    """The adapter's private streams, one per account (24 §14.2 rule 13), built by
    `ExchangeBybitService` for its environment, on its connector and its connection budget, over
    its `KeyTombstones` (else a table of its own), refusing a stream on a key the table holds. It
    owns the tasks it hands off (a closed stream's B13 stop), and serves the loop of the `open`
    that creates its first stream (D6, #913 L1d-2a)."""

    def __init__(
        self,
        *,
        environment: Environment,
        credentials: SigningCapability,
        connect: StreamConnect,
        budget: ConnectionBudget,
        policy: ReconnectPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_ms: Callable[[], int] = _wall_ms,
        now_us: Callable[[], TsUs] = _wall_us,
        max_streams: int = MAX_STREAMS,
        tombstones: KeyTombstones | None = None,
    ) -> None:
        if environment not in PRIVATE_WS_URLS:
            raise ValueError("unknown environment")
        self.environment = environment
        self.credentials = credentials
        self.budget = budget
        self.policy = policy if policy is not None else ReconnectPolicy()
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall_ms = wall_ms
        self.now_us = now_us
        self._connect = connect
        self._url = PRIVATE_WS_URLS[environment]
        self._max = max_streams
        self._conns: dict[AccountId, _PrivateConn] = {}
        #: The keys it refuses: the adapter's table, shared by reference (RC-G8B-03).
        self.tombstones = tombstones if tombstones is not None else KeyTombstones()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._shut = False
        #: D6: the loop of its first stream's `open`, taken under the lock so two loops never both
        #: take it, and when a refusal from another loop last paged (`_on_its_loop`).
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()
        self._wrong_loop_paged_at: float | None = None

    def count(self) -> int:
        """Streams open now (released once their consumer read `closed` or closed them)."""
        return len(self._conns)

    async def open(
        self, account: AccountRef, *, clock_offset_ms: Callable[[], int | None] | None = None
    ) -> PrivateStream:
        """The account's stream. Every refusal comes before anything is signed, dialled or built,
        and a call from any loop but the registry's own is refused first (`_on_its_loop`). The
        open that creates the registry's first stream binds its loop, after every refusal, so a
        refused one binds none. `clock_offset_ms` is the exchange clock's offset (exchange minus
        host, ms), `None` while unmeasured, as `auth` signs on it and ruling 10 counts only on a
        measured one."""
        self._on_its_loop()
        if self._shut:
            raise RuntimeError("the private streams are shut down")
        if account.environment != self.environment:
            raise ValueError("the account belongs to another environment")
        key_id = check_key_ref(account)
        if self.tombstones.refuses(account.key_ref):
            raise self._refused(AuthError("the account's key may not open a private stream"))
        if account.account_id in self._conns:
            raise ValueError("the account already has a private stream")
        if len(self._conns) >= self._max:
            ws_conn_budget_refused_total.labels(scope="streams").inc()
            capped = RateBudgetExceededError(
                "the private stream cap is reached; nothing was opened", reason="stream_cap"
            )
            raise self._refused(capped)
        self._on_its_loop(binds=True)  # a loop that took it meanwhile refuses this one here
        conn = _PrivateConn(self, account, key_id, clock_offset_ms)
        self._conns[account.account_id] = conn
        bybit_private_ws_streams.set(len(self._conns))
        runtime: WsConnRuntime = conn
        register_runtime(conn.conn_key, runtime)
        try:
            built = await build(
                "ws_conn",
                ctx={"conn_key": conn.conn_key, "kind": "private"},
                clock=default_clock(),
                lane="platform",
            )
            conn.bind(built.interpreter)
            await built.interpreter.send("CONNECT")
        except BaseException:
            conn.halt()
            self.release(conn)
            raise
        return _Stream(self, conn)

    def release(self, conn: _PrivateConn) -> None:
        """Free the account once its consumer is done with the stream; idempotent."""
        if self._conns.get(conn.account.account_id) is conn:
            del self._conns[conn.account.account_id]
            bybit_private_ws_streams.set(len(self._conns))
            self.spawn(conn.stop_machine(), "private-ws-release")

    def mark_refused(self, key_ref: str) -> None:
        self.tombstones.mark_refused(key_ref)

    async def close_key(
        self, key_ref: str, *, reason: Literal["key_revoked", "key_rotated"]
    ) -> tuple[AccountId, ...]:
        """SR-E27-17 (KV-E13, AC-28): close every stream on `key_ref` before returning, and name
        their accounts for the caller's audit. The key is tombstoned first, so no dial or `auth`
        uses it from then on and a stream on it is refused (`AuthError`); each stream stops at
        once, its socket closes within `CLOSE_TIMEOUT_S`, `closed(reason)` is its last item, and
        B13's stop is a task this registry owns (it is not awaited here). Each close runs in a
        task this registry owns, so a caller cancelled meanwhile leaves no stream stopped with its
        socket open, and a stream already closing for another reason, or ended, is waited for,
        not named. Past `KEY_CLOSE_BOUND_S` it pages and raises `PrivateStreamCloseOverran` while
        the closes run on (ruling Q6; the retry is 24 §14.2 rule 13's). A call from another loop,
        and a `key_ref` that is no `api_keys` id (`ValueError`), are refused before anything is
        done."""
        self._on_its_loop()
        self.tombstones.close(key_ref, reason)
        conns = [c for c in self._conns.values() if c.key_ref == key_ref]
        started = [c for c in conns if not c.stopping]
        closes = {c: c.close_soon(reason) for c in conns}  # each stops before any is awaited
        still: tuple[AccountId, ...] = ()
        if closes:
            try:  # past the bound only this wait is cancelled, never the closes
                await self.bounded(asyncio.wait(closes.values()), KEY_CLOSE_BOUND_S)
            except TimeoutError:
                still = tuple(c.account.account_id for c, task in closes.items() if not task.done())
        if still:
            closed = tuple(c.account.account_id for c in started if closes[c].done())
            logger().critical(
                "bybit_private_key_close_overran",
                cv_page=True,
                reason=reason,
                accounts=[str(account_id) for account_id in still],
            )
            raise _bare(PrivateStreamCloseOverran(still, closed=closed))
        if started:
            logger().warning("bybit_private_key_closed", reason=reason, streams=len(started))
        return tuple(conn.account.account_id for conn in started)

    def reopen(self, key_ref: str) -> bool:
        """An operator's action (ruling 10): a key three `auth` refusals marked may open streams
        again. `True` when it was marked. A key `close_key` closed stays closed."""
        return self.tombstones.reopen(key_ref)

    def _on_its_loop(self, *, binds: bool = False) -> None:
        """D6 (#913 L2; ruling Q5): the registry serves the loop of the `open` that creates its
        first stream, which `binds` it under the lock, after every refusal, so two loops never
        both take it and a refused `open` takes none. An `open` or a `close_key` from any other
        loop is refused (`RuntimeError`) before anything is signed, dialled, built or closed:
        M2's binding would refuse that loop's `auth` as the key's own fault (`key_unusable`).
        The first refusal of each `WRONG_LOOP_PAGE_S` window, on the injected clock, pages: a
        wiring defect."""
        running = asyncio.get_running_loop()
        with self._loop_lock:
            if binds and self._loop is None:
                self._loop = running
            foreign = self._loop is not None and running is not self._loop
            page = False
            if foreign:
                now, paged = self.monotonic(), self._wrong_loop_paged_at
                if paged is None or not 0 <= now - paged < WRONG_LOOP_PAGE_S:
                    self._wrong_loop_paged_at, page = now, True
        if page:
            logger().critical("bybit_private_streams_wrong_loop", cv_page=True)
        if foreign:
            raise RuntimeError("the private streams serve another event loop")

    async def aclose(self) -> None:
        """Shut down: every stream closes with `closed(shutdown)`, later opens are refused, and
        the tasks handed off are awaited."""
        self._shut = True
        conns = list(self._conns.values())
        await asyncio.gather(*(c.close("shutdown") for c in conns), return_exceptions=True)
        await self.drain()

    async def drain(self) -> None:
        """Until every task this registry handed off has ended."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # -- the connection's I/O, bounded on the injected clock ---------------------------------------

    async def dial(self) -> StreamSocket:
        """This environment's private stream, within `DIAL_TIMEOUT_S`; any failure is one text.
        A socket dialled past the bound, or as the caller was cancelled, is closed, never left
        open with no owner."""
        sock: StreamSocket | None = None
        try:
            dialling = self._connect(self._url)
            sock = await self.bounded(dialling, DIAL_TIMEOUT_S, leftover=self.close_quietly)
        except Exception:  # every failed dial leaves as one fixed text, raised outside this handler
            sock = None
        if sock is None:
            raise _bare(ConnectionError("the private stream could not be dialled"))
        return sock

    async def close_quietly(self, sock: StreamSocket) -> None:
        """A socket's close within `CLOSE_TIMEOUT_S`; a failing or stalled close is let go (the
        production socket aborts its transport then). A cancellation still propagates."""
        with contextlib.suppress(Exception):
            await self.bounded(sock.close(), CLOSE_TIMEOUT_S)

    async def bounded[T](
        self,
        work: Awaitable[T],
        seconds: float,
        *,
        leftover: Callable[[T], Coroutine[Any, Any, None]] | None = None,
    ) -> T:
        """`work` within `seconds` on the injected clock, else `TimeoutError` (`work` cancelled).
        What `work` yields that the caller never takes (past the bound, or as the caller was
        cancelled) goes to `leftover`, in a task this registry owns."""
        task = spawn(_awaited(work), name="private-ws-bounded")
        timer = spawn(_awaited(self.sleep(seconds)), name="private-ws-bound")
        taken = False
        try:
            done, _ = await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                taken = True
                return task.result()
        finally:
            timer.cancel()
            if not task.done():
                task.cancel()
            if not taken and leftover is not None:
                discard = leftover
                task.add_done_callback(lambda ended: self._discard(ended, discard))
        raise TimeoutError

    def _discard[T](
        self, ended: asyncio.Task[T], leftover: Callable[[T], Coroutine[Any, Any, None]]
    ) -> None:
        if not ended.cancelled() and ended.exception() is None:
            self.spawn(leftover(ended.result()), "private-ws-leftover")

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
        """A task this registry owns: kept until it ends, its failure logged by type only."""
        task = spawn(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._ended)
        return task

    def _ended(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            failed = type(error).__name__
            logger().error("bybit_private_task_failed", task=task.get_name(), error=failed)

    def _refused[E: ExchangeError](self, error: E) -> E:
        """An open refused before anything left: counted and logged by class, raised bare."""
        exchange_errors_total.labels(**{"class": error.code.value}).inc()
        logger().warning("bybit_private_stream_refused", error=error.code.value)
        return _bare(error)


async def _awaited[T](work: Awaitable[T]) -> T:
    return await work


def _remember[V](table: OrderedDict[str, V], key: str, value: V) -> None:
    table[key] = value
    table.move_to_end(key)
    while len(table) > KEYS_REMEMBERED:
        table.popitem(last=False)
