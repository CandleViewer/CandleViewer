"""A one-shot private-WS `auth` probe for one stored key (E27-T03, #836 slice 2b5).

`testApiKey`'s WebSocket half (`KeyTestResult.websocket`, served by slice 2b6): dial the private
stream of the key's own environment only (`PRIVATE_WS_URLS`, US-ACCT-007, C-2.11), send one `auth`
signed by M2 under `sign_ws_auth` with `expires` at most 10 s ahead (SR-E27-17), read one reply and
close. It never subscribes (#2877 and #848 own the streaming socket), never retries and never
falls back to another host; production's connector follows no redirect either, so a 3xx is a
`transport_error` and the signed `auth` reaches no other host (SR-040a). One 5 s bound covers the
dial, the signature and the reply; the socket is closed on every path under its own short bound,
aborted if the peer never finishes the close, and a cancellation propagates. Diagnostic only: it
enforces nothing (ruling 11 on #836).
SR-E27-05: at most `OPENS_PER_WINDOW` probes per `WINDOW_S` per deployment (the adapter holds one
probe), then `rate_limited` at once with nothing signed or dialled; the scheduled self-check never
names it (`test_ws_probe_callers.py`). Results are `KeyProbeError` names (SR-E27-08), never
exchange text: a refused `auth` is `auth_error`, no answer `timeout`, a failed or dropped
connection or a frame that does not decode as JSON `transport_error`, any other reply
`exchange_unknown`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from asyncio import timeout
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException
from websockets.protocol import State

from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS
from candleviewer.exchange.bybit.signer import BybitSigner

if TYPE_CHECKING:
    from candleviewer.secrets import SigningCapability

#: Ticket performance notes: 5 s per probe, the dial, M2's signature and the reply together.
PROBE_TIMEOUT_S: Final = 5.0
#: The close's own bound, after the probe's, so a stalled close cannot hold the caller.
CLOSE_TIMEOUT_S: Final = 1.0
#: The library's close bound, inside the probe's: its abort of an unanswered close comes first.
_LIBRARY_CLOSE_TIMEOUT_S: Final = CLOSE_TIMEOUT_S / 2
#: SR-E27-17: `expires` at most 10 s ahead of the exchange clock.
EXPIRES_AHEAD_MS: Final = 10_000
#: SR-E27-05: probes per window, per deployment (2 % of the venue's 500 per 5 minutes per IP).
OPENS_PER_WINDOW: Final = 10
WINDOW_S: Final = 300.0
#: Every read's bound: an `auth` reply is a few dozen bytes.
MAX_FRAME_BYTES: Final = 4096
#: The probe's vocabulary, a subset of `key_info.PROBE_ERRORS` (a test pins it).
WsProbeError = Literal[
    "auth_error", "timeout", "transport_error", "exchange_unknown", "rate_limited"
]
#: A failed dial or a dropped socket: the OS's (refused, reset, DNS, TLS) or the library's.
_TRANSPORT: Final = (OSError, WebSocketException)
#: websockets logs each frame at DEBUG (the `auth` op's key id and signature too) and takes a
#: stdlib logger only: this one never enables DEBUG; its other records reach the redacting handlers.
# nosemgrep: cv-obs-no-direct-getlogger reason=ws-stdlib-logger owner=@basiltt review=2027-03-25
_SOCKET_LOG: Final = logging.getLogger(f"{__name__}.socket")
_SOCKET_LOG.setLevel(logging.INFO)


class PrivateSocket(Protocol):
    """One private-stream connection: text frames out, frames of at most `max_bytes` in."""

    async def send(self, frame: str) -> None: ...
    async def recv(self, max_bytes: int) -> str: ...
    async def close(self) -> None: ...


#: Dials a `PRIVATE_WS_URLS` value; chosen when the adapter is built (#2893 S12 injects one).
PrivateWsConnect = Callable[[str], Awaitable[PrivateSocket]]


@dataclass(frozen=True, slots=True)
class WsProbeResult:
    """`KeyTestResult.websocket`; `latency_ms` is set only when a reply frame came back."""

    ok: bool
    error: WsProbeError | None
    latency_ms: int | None


class _Socket:
    """A `websockets` client connection as a `PrivateSocket`."""

    def __init__(self, conn: ClientConnection) -> None:
        self._conn = conn

    async def send(self, frame: str) -> None:
        await self._conn.send(frame)

    async def recv(self, max_bytes: int) -> str:
        """The library refuses a frame above `max_size` before buffering it; this bound holds
        whatever that is. A frame that is not UTF-8 decodes leniently and then fails as JSON."""
        frame = await self._conn.recv(decode=False)
        if len(frame) > max_bytes:
            raise ConnectionError("private ws frame above the read bound")
        return frame.decode("utf-8", "replace")

    async def close(self) -> None:
        """The library aborts a close the peer never finishes at its own bound; should the
        probe's bound cancel the close first, the `finally` aborts it (SR-E27-17)."""
        try:
            await self._conn.close()
        finally:
            if self._conn.state is not State.CLOSED:
                self._conn.transport.abort()


class _NoRedirectConnect(ws_connect):
    """`connect` follows a 3xx to any host (it refuses only a TLS downgrade). This one follows
    none, as `rest.py` sets `follow_redirects=False` (SR-040a): a 3xx stays the `InvalidStatus`
    it is, a transport error, and the signed `auth` is never sent elsewhere."""

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


async def connect_private_ws(url: str) -> PrivateSocket:
    """Production's connector: no redirect, no keepalive pings (the socket lives for one reply),
    small frames, the library's close bound inside the probe's, and the quiet logger above. As
    `rest.py`'s `_assert_same_host`, defence in depth: a handshake that did not go to `url`
    itself is aborted before anything is sent on it."""
    conn = await _NoRedirectConnect(
        url, open_timeout=PROBE_TIMEOUT_S, close_timeout=_LIBRARY_CLOSE_TIMEOUT_S,
        ping_interval=None, max_size=MAX_FRAME_BYTES, logger=_SOCKET_LOG,
    )  # fmt: skip
    wanted, request = urlsplit(url), conn.request
    asked = None if request is None else (request.headers.get("Host"), request.path)
    if asked != (wanted.netloc, wanted.path):
        conn.transport.abort()
        raise ConnectionError("private ws handshake left the requested stream")
    return _Socket(conn)


def _wall_ms() -> int:
    return int(time.time() * 1000)


class KeyWsProbe:
    """The adapter's one private-WS `auth` probe, holding the deployment's open budget."""

    def __init__(
        self,
        connect: PrivateWsConnect = connect_private_ws,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wall_ms: Callable[[], int] = _wall_ms,
    ) -> None:
        self._connect, self._monotonic, self._wall_ms = connect, monotonic, wall_ms
        #: When each of the last `OPENS_PER_WINDOW` probes was admitted; bounded.
        self._opened: deque[float] = deque(maxlen=OPENS_PER_WINDOW)

    def _admit(self) -> bool:
        """A sliding window that refuses at once, and never queues, while it is full."""
        now = self._monotonic()
        if len(self._opened) == OPENS_PER_WINDOW and now - self._opened[0] < WINDOW_S:
            return False
        self._opened.append(now)
        return True

    async def probe(
        self,
        credentials: SigningCapability,
        env: str,
        credential_id: UUID,
        *,
        clock_offset_ms: Callable[[], int] | None = None,
    ) -> WsProbeResult:
        """One `auth` for `credential_id` on `env`'s private stream. An unknown `env` is refused,
        never defaulted; M2's refusals propagate once the socket is closed. `clock_offset_ms`
        (exchange minus host, as `key_verification_calls` takes it) puts `expires` on the
        exchange's clock."""
        url = PRIVATE_WS_URLS.get(env)
        if url is None:
            raise ValueError("unknown environment")
        if not self._admit():
            return WsProbeResult(ok=False, error="rate_limited", latency_ms=None)
        signer = BybitSigner(credentials, credential_id, purpose="sign_ws_auth")
        offset_ms = 0 if clock_offset_ms is None else clock_offset_ms()
        started = self._monotonic()
        socket: PrivateSocket | None = None
        try:
            async with timeout(PROBE_TIMEOUT_S):
                socket = await self._connect(url)
                # Signed just before it is sent, and bound to no name here: no traceback holds it.
                await socket.send(await self._auth_frame(signer, offset_ms))
                reply = await socket.recv(MAX_FRAME_BYTES)
            answered = self._monotonic()
        except TimeoutError:  # an `OSError`: before the transport arm
            return WsProbeResult(ok=False, error="timeout", latency_ms=None)
        except _TRANSPORT:
            return WsProbeResult(ok=False, error="transport_error", latency_ms=None)
        finally:
            if socket is not None:
                await _close(socket)
        error = _reply_error(reply)
        latency_ms = round((answered - started) * 1000)
        return WsProbeResult(ok=error is None, error=error, latency_ms=latency_ms)

    async def _auth_frame(self, signer: BybitSigner, offset_ms: int) -> str:
        """The `auth` op (24 §14.3 "Auth (WS)"), `expires` 10 s ahead of the exchange clock."""
        expires = self._wall_ms() + offset_ms + EXPIRES_AHEAD_MS
        signed = await signer.sign_ws_auth(expires_ms=expires)
        return json.dumps({"op": "auth", "args": [signed.api_key, expires, signed.signature]})


def _reply_error(frame: str) -> WsProbeError | None:
    """None when the stream granted `auth`. Its `ret_msg`, exchange text, is never read."""
    try:
        reply = json.loads(frame)
    except (ValueError, RecursionError):  # nested past the decoder's recursion limit
        return "transport_error"
    if not isinstance(reply, dict) or reply.get("op") != "auth":
        return "exchange_unknown"
    granted = reply.get("success")
    if type(granted) is not bool:
        return "exchange_unknown"
    return None if granted else "auth_error"


async def _close(socket: PrivateSocket) -> None:
    """Bounded on its own; a close that fails or stalls (`TimeoutError` is an `OSError`) leaves
    the result as it was. A cancellation still propagates."""
    with contextlib.suppress(*_TRANSPORT):
        async with timeout(CLOSE_TIMEOUT_S):
            await socket.close()
