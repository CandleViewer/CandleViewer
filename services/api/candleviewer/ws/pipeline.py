"""One connection's outbound pipeline while `CV_WS_BACKPRESSURE_ENABLED` is on (E17-T03, #412;
`23-ws-protocol.md` §4.4, §8.4, §10.1).

From `accept` on, `_Connection.push` hands every frame to `ConnectionPipeline.push`, the `welcome`
included. It is encoded once in the negotiated subprotocol (`outbound.encode`), queued on the
`OutboundQueue` lanes and counted against the connection's budget, which binds both lanes
(C-2.18). A push that leaves the queue over budget closes the connection `slow_consumer` (§8.4
step 3); the ladder's drop and re-snapshot steps before it arrive in a later slice. The writer
(`gateway.py`) sends each payload as it was encoded.

A close takes the terminal slot (`Terminal`), in no lane and never counted: its `bye` and close
marker are the only items admitted past the budget, one small frame, so the bound holds to within
one frame and the budget never refuses a `bye` (§8.4, WS-D01). A close that ends the
identity (token expiry, revocation, a disabled user) and every `slow_consumer` close clear both
lanes, so the `bye` is next; any other close keeps the priority lane ahead of the `bye` and
discards the normal lane. Nothing is queued after a close. The flush runs under one deadline,
`BackpressureConfig.close_flush_s` from the first close on (a later seal never extends it): the
writer `arm`s it, and past it gives up with no `bye` (§4.4). That expiry is counted once per
connection as `cv_ws_overflow_total{reason="close_flush_deadline"}`, whatever the close's reason,
on top of the `close_budget` a step 3 close has already counted (§8.4 step 4); the close audit's
fields for it arrive with the ladder's audit trigger.

The deadline is on the event loop's clock (`loop.time()`), not on the gateway's injected `clock`:
only an `asyncio.Timeout` can cancel a send that a peer which stopped reading has parked, and it
reads the loop's clock. So a test cannot advance it; it bounds it with a short `close_flush_s` and
a send that never completes, which leaves the deadline as the only way out.

A frame its encoder refuses is a server fault and fails closed: `internal_error` (§10.1). The
droppable case of §10.1 (a market-data frame drops its topic to a `backpressure` re-snapshot
instead) arrives with the ladder; until then it fails closed too. A NaN or an infinity is refused
on both subprotocols, a producer bug either way (§10.1): JSON refuses it as it encodes, and
`msgpack_payload` after packing, as a `ValueError` too. The log line names the frame's type,
family and error class, never its payload or the error's text (C-12.6). Whatever the encoder
raises is caught, so nothing raises into the caller and one bad frame never stops a fan-out.

Plain synchronous code: no I/O and no task of its own; the gateway's writer drives it.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

import structlog

from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.codec import encode_server_frame
from candleviewer.ws.lifecycle import SUBPROTOCOL_MSGPACK, bye_frame
from candleviewer.ws.metrics import cv_ws_overflow_total
from candleviewer.ws.outbound import FrameEncoder, OutboundQueue, encode, json_payload
from candleviewer.ws.sequencing import MAX_OUTBOUND_FRAME_BYTES
from candleviewer.ws.topics import FAMILIES

#: §8.4 step 3's `bye`: one fixed message for both triggers (a `redrop` close happens under budget).
SLOW_CONSUMER_RETRY_AFTER_MS: Final = 3000
SLOW_CONSUMER_MESSAGE: Final = "Client is not draining its outbound queue."
#: §8.4 step 4: a close whose flush deadline expired, whatever its reason.
CLOSE_FLUSH_DEADLINE: Final = "close_flush_deadline"
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


def slow_consumer_bye(now_ms: int) -> dict[str, Any]:
    """The step-3 `bye`: `retry_after_ms` 3 000 and the generic message, never a size. The
    `hint` naming the most expensive topics arrives with the ladder."""
    frame = bye_frame("slow_consumer", now_ms=now_ms, retry_after_ms=SLOW_CONSUMER_RETRY_AFTER_MS)
    frame["p"]["message"] = SLOW_CONSUMER_MESSAGE
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
        self._dumps: FrameEncoder = (
            msgpack_payload if encoding == SUBPROTOCOL_MSGPACK else json_payload
        )
        self._close = close
        self._wall_ms = wall_ms
        self._connection_id = connection_id
        #: The flush deadline on the loop's clock, from the first close; the writer's scope.
        self._deadline: float | None = None
        self._timeout: asyncio.Timeout | None = None

    @property
    def deadline(self) -> float | None:
        """The close's flush deadline on the loop's clock, from the first close; None before."""
        return self._deadline

    def push(self, frame: Mapping[str, Any], received: float | None = None) -> None:
        """Queue one frame; nothing once a close or `release` happened (WS-D01)."""
        if self.terminal is not None or self.released:
            return
        try:
            item = encode(frame, self._dumps, received=received)
        except Exception as exc:  # whatever the encoder raises: never into the fan-out (§10.1)
            _log().error("ws frame unencodable", **self._fields(frame), error=type(exc).__name__)
            self._close("internal_error")
            return
        if item.size > MAX_OUTBOUND_FRAME_BYTES:  # #2818: logged and sent, never refused
            _log().warning(
                "ws outbound frame over the frame limit", **self._fields(frame), size=item.size
            )
        self.queue.push(item)
        if self.queue.over_budget():  # §8.4 step 3; steps 1 and 2 arrive with the ladder
            cv_ws_overflow_total.labels(reason="close_budget").inc()
            self._close("slow_consumer", bye=slow_consumer_bye(self._wall_ms()))

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
        """Teardown: free both lanes; nothing is queued after it."""
        self.released = True
        self.queue.clear()
        self._timeout = None

    def _fields(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        """A frame as a log line may name it: bounded type and family, never the payload."""
        t, ch = frame.get("t"), frame.get("ch")
        family = ch.split(".", 1)[0] if isinstance(ch, str) else None
        return {
            "connection_id": self._connection_id,
            "t": t if isinstance(t, str) and t in _SERVER_TYPES else "other",
            "family": family if family is None or family in FAMILIES else "other",
        }


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)
