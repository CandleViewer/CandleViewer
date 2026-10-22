"""The private stream's venue end for the G-8b runtime tests (#3963): a fake connector whose sockets
answer `auth`, `subscribe` and `ping` with the docs-transcribed replies (`_private.py`), or what a
test scripts, and record every frame sent with the virtual time it was sent at; a stream registry
on the chaos suite's `VirtualClock`; and a consumer that keeps what a stream yields. No network and
no sleeps (C-13.5, C-13.7): time moves only when a test advances the clock.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from candleviewer.exchange.base.models import PrivateEvent, PrivateStreamStatus
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.exchange.base.reconnect import ConnectionBudget, ReconnectPolicy

# nosemgrep: cv-adapter-isolation reason=G-8b-harness owner=@CandleViewer/security review=2027-03-25
from candleviewer.exchange.bybit.private_stream import MAX_STREAMS, PrivateStreams
from candleviewer.observability.context import spawn
from candleviewer.secrets import CredentialBorrower
from tests._signing import Call, fake_capability
from tests.chaos.ingestion._clock import VirtualClock

# nosemgrep: cv-adapter-isolation reason=G-8b-harness owner=@CandleViewer/security review=2027-03-25
from tests.unit.exchange.bybit._private import raw, reply

# nosemgrep: cv-adapter-isolation reason=G-8b-harness owner=@CandleViewer/security review=2027-03-25
from tests.unit.exchange.bybit._trading import SIGNER_ID

#: What a socket's inbox holds to fail its next read: the peer dropped the connection.
DROP = "\x00drop"
#: Derived replies (no page shows them): a refused `auth` and a refused `subscribe`.
REFUSED_AUTH = reply("auth-ok", success=False)
REFUSED_SUBSCRIBE = reply("subscribe-ok", success=False)
UNKNOWN_AUTH = reply("auth-ok", success="no")


@dataclass
class VenueSocket:
    """One private socket: what the adapter sent (`sent`, with the virtual second it was sent
    at), what the venue queued for it to read (`push`), and whether it was closed."""

    venue: PrivateVenue
    url: str
    sent: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    inbox: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    closed: bool = False
    #: What the read that meets a drop fails with: the peer's text, as a library error carries it.
    drop_text: str = "the peer dropped the connection"

    async def send(self, frame: str) -> None:
        if self.closed:
            raise ConnectionError("socket closed")
        message = json.loads(frame)
        self.sent.append((self.venue.clock.now, message))
        self.venue.answer(self, message)

    async def recv(self, max_bytes: int) -> str:
        self.venue.bounds.append(max_bytes)
        frame = await self.inbox.get()
        if frame == DROP:
            raise ConnectionResetError(self.drop_text)
        return frame

    async def close(self) -> None:
        self.closed = True
        self.inbox.put_nowait(DROP)

    def push(self, *frames: str) -> None:
        for frame in frames:
            self.inbox.put_nowait(frame)

    def drop(self) -> None:
        self.inbox.put_nowait(DROP)

    def ops(self) -> list[str]:
        return [str(message["op"]) for _, message in self.sent]


@dataclass
class PrivateVenue:
    """The private stream's venue: each dial a new `VenueSocket`. Replies come from the queues a
    test scripts (`auth`, `subscribe`: a frame, or `None` for no reply), else the transcribed
    grants; a ping is answered with the transcribed pong unless `pongs` is off."""

    clock: VirtualClock
    sockets: list[VenueSocket] = field(default_factory=list)
    dialled: list[str] = field(default_factory=list)
    bounds: list[int] = field(default_factory=list)
    auth: deque[str | None] = field(default_factory=deque)
    subscribe: deque[str | None] = field(default_factory=deque)
    pongs: bool = True
    fail_dials: int = 0

    async def connect(self, url: str) -> VenueSocket:
        self.dialled.append(url)
        if self.fail_dials:
            self.fail_dials -= 1
            raise ConnectionRefusedError("the stream refused the connection")
        sock = VenueSocket(self, url)
        self.sockets.append(sock)
        return sock

    def answer(self, sock: VenueSocket, message: dict[str, Any]) -> None:
        op = message.get("op")
        answer: str | None = None
        if op == "auth":
            answer = self.auth.popleft() if self.auth else raw("auth-ok")
        elif op == "subscribe":
            answer = self.subscribe.popleft() if self.subscribe else raw("subscribe-ok")
        elif op == "ping" and self.pongs:
            answer = raw("pong")
        if answer is not None:
            sock.push(answer)

    @property
    def socket(self) -> VenueSocket:
        return self.sockets[-1]

    def sent(self, op: str) -> list[dict[str, Any]]:
        return [m for s in self.sockets for _, m in s.sent if m.get("op") == op]


def make_streams(
    venue: PrivateVenue,
    *,
    calls: list[Call] | None = None,
    credentials: CredentialBorrower | None = None,
    environment: Any = "demo",
    max_streams: int = MAX_STREAMS,
    seed: int = 7,
) -> PrivateStreams:
    """The registry over `venue`, signed by the M2 double, on `venue.clock`."""
    clock = venue.clock
    rng = random.Random(seed)  # noqa: S311 -- seeded test jitter, not a security primitive
    return PrivateStreams(
        environment=environment,
        credentials=credentials if credentials is not None else fake_capability(SIGNER_ID, calls),
        connect=venue.connect,
        budget=ConnectionBudget(clock),
        policy=ReconnectPolicy(rng=rng),
        sleep=clock.sleep,
        monotonic=clock,
        wall_ms=lambda: round(clock.wall_s() * 1000),
        now_us=clock.now_us,
        max_streams=max_streams,
    )


class Consumer:
    """Reads one stream in its own task and keeps every item, as E29-T05 would."""

    def __init__(self, stream: PrivateStream) -> None:
        self.stream = stream
        self.items: list[PrivateEvent | PrivateStreamStatus] = []
        self.task = spawn(self._run(), name="private-stream-consumer")

    async def _run(self) -> None:
        async for item in self.stream:
            self.items.append(item)

    def statuses(self) -> list[str]:
        """Each status as `state:reason:epoch`."""
        return [
            f"{item.state}:{item.reason}:{item.epoch}"
            for item in self.items
            if isinstance(item, PrivateStreamStatus)
        ]

    def shown(self) -> list[str]:
        """Every item in order: a status as `state:reason:epoch`, an event as its kind."""
        return [_shown(item) for item in self.items]

    def events(self) -> list[PrivateEvent]:
        return [item for item in self.items if isinstance(item, PrivateEvent)]

    async def stop(self) -> None:
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task
        await self.stream.aclose()


def _shown(item: PrivateEvent | PrivateStreamStatus) -> str:
    if isinstance(item, PrivateStreamStatus):
        return f"{item.state}:{item.reason}:{item.epoch}"
    return item.kind


async def until(clock: VirtualClock, predicate: Any, *, within_s: float, what: str) -> float:
    """Advance virtual time, timer by timer, until `predicate()` holds (a recovery bound)."""
    return await clock.run_until(predicate, within_s=within_s, what=what)
