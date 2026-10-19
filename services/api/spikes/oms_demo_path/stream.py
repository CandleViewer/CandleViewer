"""The demo account's private stream, for the measurement (23-ws S4/S5; ADR-0006 Spike S3).

One authenticated connection at a time to `DEMO_WS_URL` only, re-dialled with capped, jittered
backoff for as long as the run lasts. The `auth` op is signed by the adapter's `BybitSigner`
(`expires` 10 s ahead of the exchange clock). Each topic is subscribed in its own request, so a
topic the demo stream refuses does not take the others down. Bybit's application ping goes out
every 20 s; a socket silent for 60 s is dropped and re-dialled. Every frame but `pong` goes to
`on_frame` with its receipt time on the exchange clock.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import httpx
import structlog
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from candleviewer.exchange.bybit.signer import BybitSigner

from .safety import DEMO_WS_URL, check_ws_url

TOPICS: Final = ("order", "execution", "execution.fast", "position", "wallet")
PING_EVERY_S: Final = 20.0
SILENCE_S: Final = 60.0
MAX_FRAME_BYTES: Final = 1 << 20
_TLS: Final = httpx.create_ssl_context(verify=True, trust_env=False)
_DROPS: Final = (OSError, WebSocketException, TimeoutError, ValueError)


def _log() -> Any:
    return structlog.get_logger(__name__)


class Socket(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...


class StreamAuthRefused(RuntimeError):
    """The stream refused the run's first `auth`: the run stops instead of re-dialling."""


class _NoRedirect(connect):
    """A 3xx stays an error: the signed `auth` never reaches another host (as SR-040a)."""

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


async def dial(url: str) -> Socket:
    check_ws_url(url)
    return await _NoRedirect(
        url, open_timeout=10, close_timeout=2, ping_interval=None, max_size=MAX_FRAME_BYTES,
        proxy=None, ssl=_TLS,
    )  # fmt: skip


@dataclass
class StreamStats:
    connects: int = 0
    drops: list[tuple[int, str]] = field(default_factory=list)
    pong_rtt_ms: list[float] = field(default_factory=list)
    subscribed: dict[str, bool] = field(default_factory=dict)


class PrivateStream:
    def __init__(
        self,
        signer: BybitSigner,
        on_frame: Callable[[dict[str, Any], int], None],
        *,
        now_ms: Callable[[], int],
        topics: Sequence[str] = TOPICS,
        dial_fn: Callable[[str], Awaitable[Socket]] = dial,
    ) -> None:
        self._signer, self._on_frame, self._now_ms = signer, on_frame, now_ms
        self._topics, self._dial = tuple(topics), dial_fn
        self._pings: deque[float] = deque(maxlen=16)
        self._socket: Socket | None = None
        self._stop = asyncio.Event()
        self.ready = asyncio.Event()
        self.stats = StreamStats()

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                await self._session()
            except _DROPS as exc:
                if not self._stop.is_set():
                    self.stats.drops.append((self._now_ms(), type(exc).__name__))
                    _log().warning("private_stream_dropped", reason=type(exc).__name__)
            backoff = 1.0 if time.monotonic() - started > 60 else min(backoff * 2, 60.0)
            with contextlib.suppress(TimeoutError):
                jitter = 0.5 + secrets.randbelow(500) / 1000
                await asyncio.wait_for(self._stop.wait(), backoff * jitter)

    async def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            with contextlib.suppress(*_DROPS):
                await self._socket.close()

    async def _session(self) -> None:
        socket = self._socket = await self._dial(DEMO_WS_URL)
        self._pings.clear()
        try:
            if self._stop.is_set():  # stop() came while dialling
                return
            expires = self._now_ms() + 10_000
            signed = await self._signer.sign_ws_auth(expires_ms=expires)
            await socket.send(
                json.dumps({"op": "auth", "args": [signed.api_key, expires, signed.signature]})
            )
            async with asyncio.timeout(10):
                reply = json.loads(await socket.recv())
            if not isinstance(reply, dict) or reply.get("op") != "auth" or not reply.get("success"):
                if self.stats.connects == 0:  # the first auth decides; a later one is a drop
                    raise StreamAuthRefused("the private stream refused auth")
                raise ConnectionError("auth refused on a reconnect")
            self._on_frame(reply, self._now_ms())
            for topic in self._topics:
                await socket.send(json.dumps({"op": "subscribe", "req_id": topic, "args": [topic]}))
            self.stats.connects += 1
            self.ready.set()
            pinger = asyncio.create_task(self._ping(socket))
            try:
                await self._read(socket)
            finally:
                pinger.cancel()
                await asyncio.gather(pinger, return_exceptions=True)
        finally:
            self._socket = None
            with contextlib.suppress(*_DROPS):
                await socket.close()

    async def _ping(self, socket: Socket) -> None:
        n = 0
        while True:
            await asyncio.sleep(PING_EVERY_S)
            n += 1
            self._pings.append(time.monotonic())
            await socket.send(json.dumps({"op": "ping", "req_id": f"ping-{n}"}))

    async def _read(self, socket: Socket) -> None:
        while True:
            async with asyncio.timeout(SILENCE_S):
                raw = await socket.recv()
            received = self._now_ms()
            frame = json.loads(raw)
            if not isinstance(frame, dict):
                continue
            if frame.get("op") == "pong":
                if self._pings:
                    self.stats.pong_rtt_ms.append((time.monotonic() - self._pings.popleft()) * 1e3)
                continue
            if frame.get("op") == "subscribe":
                self.stats.subscribed[str(frame.get("req_id"))] = frame.get("success") is True
            self._on_frame(frame, received)
