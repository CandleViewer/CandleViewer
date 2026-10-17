"""SR-188 (#2175): the gateway queues each `system` frame as the socket's principal may see it at
that moment (`23-ws-protocol.md` §15.9, S3), on all three paths: a hub broadcast, the notices
after the first `auth_ok`, and the §9.4 planned shutdown. The kill-switch state in `auth_ok` is
cut the same way, on a first `auth` and on a re-`auth` (§4.3).

The real `/ws` router runs on the test's loop behind a fake socket: no threads, no sleeps. A client
`ping` is the barrier: one FIFO queue (flag off), so its `pong` follows every frame queued before
it, and a `pong` first proves nothing was."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute

from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub
from tests.unit.ws.test_system_filter import ACC_A, SAMPLES

_DEADLINE_S = 5.0
BASE_MS = 1_789_132_262_000
ORIGIN = "http://testserver"
KILL, KILL_NEUTRAL = SAMPLES["kill_switch"]
NOTICE, _ = SAMPLES["notice"]
assert KILL_NEUTRAL is not None
STATE, VIEW, GONE = KILL["kill_switch"], KILL_NEUTRAL["kill_switch"], "no kill_switch"


def _as(user: uuid.UUID, *roles: str) -> PrincipalSnapshot:
    grants = (AccountGrant(ACC_A, True, True, False),) if {"manager", "viewer"} & set(roles) else ()
    return PrincipalSnapshot(user, frozenset(roles), frozenset(), grants)


async def _no_sleep(_seconds: float) -> None:
    return None


class _Socket:
    """The slice of Starlette's `WebSocket` the handler uses (`cv.v1.json`, an allowed Origin)."""

    def __init__(self) -> None:
        self.scope = {"headers": [(b"origin", ORIGIN.encode())], "subprotocols": ["cv.v1.json"]}
        self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.auth_ok: dict[str, Any] = {}  # the first `auth_ok`, as `_Rig.connect` read it

    async def accept(self, subprotocol: str | None = None) -> None: ...

    async def receive(self) -> dict[str, Any]:
        return await self.inbound.get()

    async def send_text(self, text: str) -> None:
        self.sent.put_nowait(json.loads(text))

    async def close(self, code: int = 1000) -> None: ...

    def feed(self, frame: dict[str, Any]) -> None:
        self.inbound.put_nowait({"type": "websocket.receive", "text": json.dumps(frame)})


class _Rig:
    """The real router. `principals[user]` is what the registry loads for `user`, now."""

    def __init__(self, notices: list[dict[str, Any]] | None = None) -> None:
        self.hub = GatewayHub()
        self.principals: dict[uuid.UUID, PrincipalSnapshot] = {}
        self.handlers: list[tuple[_Socket, asyncio.Task[None]]] = []

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            return self.principals[uid]

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            return f"sess-{token}", uuid.UUID(token), datetime(2100, 1, 1, tzinfo=UTC)

        self.registry = ConnectionRegistry(resolve, lambda: BASE_MS)
        router = make_ws_router(
            authenticate=authenticate,
            registry=self.registry,
            revocation_hub=RevocationHub(),
            allowed_origins=frozenset({ORIGIN}),
            hub=self.hub,
            clock=lambda: 0.0,
            wall_ms=lambda: BASE_MS,
            tick_s=0.005,
            system_notices=None if notices is None else lambda: list(notices),
            kill_switch=lambda: STATE,
        )
        (route,) = router.routes
        assert isinstance(route, APIWebSocketRoute)
        self.endpoint = route.endpoint

    async def connect(self, principal: PrincipalSnapshot) -> _Socket:
        """A socket through `hello` and its first `auth`, as `principal`."""
        self.principals[principal.user_id] = principal
        sock = _Socket()
        self.handlers.append((sock, asyncio.create_task(self.endpoint(sock))))
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": str(principal.user_id)}})
        sock.auth_ok = await sock.sent.get()
        assert sock.auth_ok["t"] == "auth_ok"
        return sock

    async def close(self) -> None:
        for sock, _ in self.handlers:
            sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await asyncio.gather(*(task for _, task in self.handlers))


async def _system(sock: _Socket) -> list[tuple[int, Any]]:
    """`(s, p)` of every `system` frame queued for `sock` before now."""
    sock.feed({"t": "ping", "id": "barrier"})
    frames: list[dict[str, Any]] = []
    while (frame := await sock.sent.get())["t"] != "pong":
        frames.append(frame)
    return [(f["s"], f["p"]) for f in frames if f.get("ch") == "system"]


async def test_one_broadcast_reaches_each_role_as_its_own_view() -> None:
    rig = _Rig()
    async with asyncio.timeout(_DEADLINE_S):
        socks = [await rig.connect(_as(uuid.uuid4(), r)) for r in ("owner", "manager", "viewer")]
        nobody = await rig.connect(_as(uuid.uuid4()))  # the deny-all principal
        rig.hub.broadcast_system(KILL)
        assert [await _system(s) for s in socks] == [[(1, KILL)], *[[(1, KILL_NEUTRAL)]] * 2]
        assert await _system(nobody) == []
        await rig.close()


async def test_a_role_change_applies_to_the_next_frame_and_a_left_out_frame_takes_no_s() -> None:
    """Swaps by the registry (§9.5) and by an in-place re-`auth`; one broadcast after each."""
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "owner"))
        seen = []
        for by_auth, roles in [(0, ("manager",)), (0, ()), (0, ("owner",)), (1, ("viewer",))]:
            rig.principals[user] = _as(user, *roles)
            if by_auth:
                sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
                assert (await sock.sent.get())["t"] == "auth_ok"
            else:
                await rig.registry.grants_changed(user)
            rig.hub.broadcast_system(KILL)
            seen.append(await _system(sock))
        assert seen == [[(1, KILL_NEUTRAL)], [], [(2, KILL)], [(3, KILL_NEUTRAL)]]
        await rig.close()


@pytest.mark.parametrize(("roles", "expected"), [(("viewer",), [(1, NOTICE)]), ((), [])])
async def test_the_notices_after_the_first_auth_ok_follow_the_principal(
    roles: tuple[str, ...], expected: list[tuple[int, Any]]
) -> None:
    rig = _Rig(notices=[{"kind": "tick"}, NOTICE])  # an unknown kind reaches nobody
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), *roles))
        assert await _system(sock) == expected
        await rig.close()


@pytest.mark.parametrize("roles", [("viewer",), ()], ids=["viewer", "no-role"])
async def test_the_planned_shutdown_notice_goes_through_the_same_filter(
    roles: tuple[str, ...],
) -> None:
    rig = _Rig()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), *roles))
        await rig.hub.shutdown(grace_ms=0, sleep=_no_sleep)
        frame = await sock.sent.get()
        if roles:
            assert (frame["ch"], frame["p"]["kind"]) == ("system", "shutdown_notice")
            frame = await sock.sent.get()
        assert (frame["t"], frame["p"]["reason"]) == ("bye", "shutdown")
        await rig.close()


@pytest.mark.parametrize(
    ("first", "then", "want"),
    [
        (("owner",), ("manager",), [STATE, VIEW]),
        (("manager",), ("viewer",), [VIEW, VIEW]),
        (("viewer",), (), [VIEW, GONE]),
        ((), ("owner",), [GONE, STATE]),
    ],
    ids=["owner-manager", "manager-viewer", "viewer-no-role", "no-role-owner"],
)
async def test_auth_ok_carries_the_kill_switch_cut_as_the_system_topic_cuts_it(
    first: tuple[str, ...], then: tuple[str, ...], want: list[Any]
) -> None:
    """The first `auth`, then an in-place re-`auth` under another principal (§4.3): the Owner's
    is whole, a Manager's and a Viewer's is cut to their own accounts, no role gets none."""
    rig, user = _Rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, *first))
        rig.principals[user] = _as(user, *then)
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        oks = [sock.auth_ok, await sock.sent.get()]
        assert [ok["t"] for ok in oks] == ["auth_ok"] * 2
        assert [ok["p"].get("kill_switch", GONE) for ok in oks] == want
        await rig.close()
