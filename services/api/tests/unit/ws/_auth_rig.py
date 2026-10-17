"""#2155 rig: one gateway on the test's loop, driven through a fake socket; no sleeps.

The token picks the outcome, so concurrent sockets share no switch: `good-<n>` is user n on
session `sess-good-<n>`, `good-<n>@<x>` the same user on a rotated session, `naive` has an expiry
with no zone (a server fault), `hang` never returns, `raises-timeout` raises its own
`TimeoutError`, anything else is refused. `hold(call)` parks that call of every later `auth`.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute
from starlette.websockets import WebSocketDisconnect

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.context import spawn
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.limits import AUTH_CALL_TIMEOUT_S
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub

BASE_MS = 1_789_132_262_000
ORIGIN = "http://testserver"  # §2.5: allow-listed and sent on every upgrade
DEADLINE_S = 5.0
#: `Rig.leftovers()` once every handler has ended.
NOTHING_LEFT: tuple[int, int, int, int, dict[str, int]] = (0, 0, 0, 0, {})
LATER = datetime(2100, 1, 1, tzinfo=UTC)
EXITS = "auth_ok auth_failed bad_client hang_up fault call_timeout rate_refused cancelled".split()


def user_of(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_OID, name)


class Sock:
    """The slice of Starlette's `WebSocket` the handler uses, on `cv.v1.json`. `codes` records
    each close code; a peer that `stops_reading` parks every send, one that `vanished` fails it."""

    def __init__(self) -> None:
        self.scope: dict[str, Any] = {
            "headers": [(b"origin", ORIGIN.encode())],
            "subprotocols": ["cv.v1.json"],
            "client": ("127.0.0.1", 50000),
        }
        self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.codes: list[int] = []
        self.stops_reading = self.vanished = False
        self.stalled = asyncio.Event()

    async def accept(self, subprotocol: str | None = None) -> None: ...

    async def receive(self) -> dict[str, Any]:
        return await self.inbound.get()

    async def send_text(self, text: str) -> None:
        if self.vanished:
            raise WebSocketDisconnect(1006)
        if self.stops_reading:
            self.stalled.set()
            await asyncio.Event().wait()  # never set: only a cancel ends it
        self.sent.put_nowait(json.loads(text))

    async def close(self, code: int = 1000) -> None:
        self.codes.append(code)

    def feed(self, frame: Any) -> None:
        self.inbound.put_nowait({"type": "websocket.receive", "text": json.dumps(frame)})


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


class Rig:
    """One gateway on the test's loop (module docstring); `now` is its fake clock. The auth call
    bound is production's, or 10 ms (loop clock) if a test's call `hangs`; `hub` goes to the hub."""

    def __init__(self, *, tick_s: float = 0.005, hangs: bool = False, **hub: int) -> None:
        self.audit, self.hub, self.now = _Audit(), GatewayHub(**hub), 0.0
        self.revocation = RevocationHub(wall_ms=lambda: BASE_MS)
        self.gates: dict[str, asyncio.Event] = {}
        self.parked: dict[str, asyncio.Event] = {}
        reads = itertools.count(1)

        async def authenticate(presented: str) -> tuple[str, uuid.UUID, datetime]:
            await self._held("authenticate")
            if presented == "hang":
                await asyncio.Event().wait()  # never set: only the bound ends it
            if presented == "raises-timeout":
                raise TimeoutError("the session store's own timeout")
            if presented == "naive":
                return "sess-naive", user_of(presented), LATER.replace(tzinfo=None)
            if not presented.startswith("good-"):
                raise PermissionError("bad token")
            return f"sess-{presented}", user_of(presented.partition("@")[0]), LATER

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            if "recheck" in self.gates:  # odd reads: an auth's own; even: its SR-189 re-read
                if next(reads) % 2:
                    await self.registry.roles_changed(uuid.UUID(int=7))  # a change mid-read
                else:
                    await self._held("recheck")
            await self._held("resolve")
            perms = frozenset({Permission.MARKETDATA_READ})
            return PrincipalSnapshot(uid, frozenset({"viewer"}), perms)

        self.sequencing = SequencingHub()
        services = SubscriptionServices(sequencing=self.sequencing)
        self.registry = ConnectionRegistry(resolve, lambda: BASE_MS, services=services)
        router = make_ws_router(
            authenticate=authenticate,
            registry=self.registry,
            revocation_hub=self.revocation,
            allowed_origins=frozenset({ORIGIN}),
            hub=self.hub,
            audit=self.audit,
            auth_call_timeout_s=0.01 if hangs else AUTH_CALL_TIMEOUT_S,  # on the loop's clock
            clock=lambda: self.now,
            wall_ms=lambda: BASE_MS + int(self.now * 1000),
            tick_s=tick_s,
        )
        (route,) = router.routes
        assert isinstance(route, APIWebSocketRoute)
        self.endpoint: Callable[[Sock], Any] = route.endpoint

    def hold(self, call: str) -> asyncio.Event:
        """Park `call` (`authenticate`, `resolve` or `recheck`) of every later `auth` until the
        returned gate is set; `parked[call]` is set once one is parked."""
        self.parked[call], self.gates[call] = asyncio.Event(), asyncio.Event()
        return self.gates[call]

    async def _held(self, call: str) -> None:
        if (gate := self.gates.get(call)) is not None:
            self.parked[call].set()
            await gate.wait()

    def start(self, sock: Sock) -> asyncio.Task[None]:
        return spawn(self.endpoint(sock), name="ws-test-handler")

    async def open(self, sock: Sock) -> asyncio.Task[None]:
        """Start the handler and take it through `hello`."""
        handler = self.start(sock)
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        return handler

    @staticmethod
    async def auth(sock: Sock, token: str, fid: str = "a") -> dict[str, Any]:
        """Send one `auth` and return the next frame."""
        sock.feed({"t": "auth", "id": fid, "p": {"access_token": token}})
        return await sock.sent.get()

    def registered(self) -> dict[str, int]:
        """How many closers the `RevocationHub` holds per session id."""
        return {session_id: len(c) for session_id, c in self.revocation._sockets.items()}

    def leftovers(self) -> tuple[int, int, int, int, dict[str, int]]:
        """(sockets counted, live, registry users, sequencing entries, `RevocationHub` sessions)."""
        counted, live, sequenced = self.hub.unauthenticated, len(self.hub), len(self.sequencing)
        return counted, live, len(self.registry._conns), sequenced, self.registered()


def hang_up(sock: Sock) -> None:
    sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})


def bye_of(frame: dict[str, Any]) -> tuple[str, str, int]:
    return frame["t"], frame["p"]["reason"], frame["p"]["code"]


_ids = itertools.count(1)
#: exit -> (what the client sends until the `bye`, that `bye`). `good-dup` has spent its user's
#: connect budget; `naive` faults the handler (its own `1011`); `hang` meets the call bound.
_ENDS = {
    "auth_failed": ("bad", ("bye", "auth_failed", 4401)),
    "bad_client": ([1], ("bye", "bad_client", 4400)),
    "fault": ("naive", ("bye", "internal_error", 1011)),
    "call_timeout": ("hang", ("bye", "internal_error", 1011)),
    "rate_refused": ("good-dup", ("bye", "client_rate_limited", 4429)),
}


async def end_through(rig: Rig, sock: Sock, handler: asyncio.Task[None], how: str) -> None:
    """Take an admitted socket, past `hello`, to its end along one exit; await its handler."""
    if how == "cancelled":
        handler.cancel()
        with pytest.raises(asyncio.CancelledError):
            await handler
        return
    if how == "auth_ok":  # authenticated, then the client leaves
        assert (await rig.auth(sock, f"good-{next(_ids)}"))["t"] == "auth_ok"
    elif how != "hang_up":
        sent, end = _ENDS[how]
        while True:
            if isinstance(sent, str):
                sock.feed({"t": "auth", "id": "a", "p": {"access_token": sent}})
            else:
                sock.feed(sent)
            if (frame := await sock.sent.get())["t"] == "bye":
                break
            assert frame["t"] == "err", frame  # strikes 1 and 2
        assert bye_of(frame) == end
    hang_up(sock)
    await handler
