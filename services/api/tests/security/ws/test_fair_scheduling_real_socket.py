"""Fair scheduling between connections and constant-time cap checks on a real gateway (#415).

One user's eight sockets each send 28 `sub` frames of 50 topics within one second of gateway time,
every topic refused by a cap: four sockets hold 200 subscriptions, four hold 40 symbols. Meanwhile
another user's `book.BTCUSDT.50` update is published, 0 to 6 loop turns after the last of those
writes, for three seeds of the order the sockets write in. Of its 21 server-side spans (budget #6's
definition: the publish to the end of the frame's `send_payload`), the second-worst, their 95th
percentile, stays under the budget's 20 ms and the worst under a 100 ms bound; both are reported.

On the E17-Q02 chaos rig (real uvicorn, the outbound pipeline), unchanged; its listening socket
gets `TCP_NODELAY`, as uvicorn's own binding gives the sockets it accepts. Timed on the loop clock
(the gateway's is virtual), with the collector off while timing. `perf`: runs in `py-perf`.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import random
import socket
import uuid
from collections import Counter

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin, Subprotocol

from candleviewer.observability.context import spawn
from candleviewer.ws import gateway
from tests.chaos.ws._proxy import HOST
from tests.chaos.ws._server import BOOK, SEED, Stack, granted
from tests.contract.ws._support import ORIGIN

pytestmark = pytest.mark.perf

BUDGET_MS = 20.0  # budget #6 (06-performance-and-load-standard.md §2), a 95th percentile
#: The worst span's bound. One pause of a shared runner may take a single span past the budget, so
#: the worst is held only to five times it, which the gateway without fair scheduling exceeds here.
WORST_MS = 100.0
SOCKETS, FRAMES = 8, 28  # the user's connection limit; each sends this many, under 30 a second
SEEDS, ALIGNMENTS = (1, 2, 3), range(7)
STEP_S = 6.5  # gateway time between rounds: a socket stays under 300 frames a minute
TIMEOUT_S = 10.0  # a hang guard on each wait, never a latency bound
VIEWER, SENDER = uuid.UUID(int=0x415B), uuid.UUID(int=0x415C)
HELD_SUBS = [f"footprint.BTCUSDT.tick.{n}" for n in range(1, 201)]  # the 200-subscription cap
OVER_SUBS = [f"footprint.BTCUSDT.tick.{n}" for n in range(201, 251)]
HELD_SYMS = [f"trades.S{n:02d}USDT" for n in range(40)]  # the 40-symbol cap
OVER_SYMS = [f"trades.S{n:02d}USDT" for n in range(40, 90)]


def sub(topics: list[str], fid: str) -> str:
    return json.dumps({"t": "sub", "id": fid, "p": {"topics": [{"ch": ch} for ch in topics]}})


#: What each socket holds, and the 50-topic `sub` it sends past that cap.
CAPS = [(HELD_SUBS, sub(OVER_SUBS, "over")), (HELD_SYMS, sub(OVER_SYMS, "over"))]


class Raw:
    """A socket of the sending user, dialled straight at the gateway. It counts the frames it gets
    by type, read off the front of each text, and keeps the last `sub_ok`."""

    def __init__(self, ws: ClientConnection, over: str) -> None:
        self.ws, self.over, self.got, self.last = ws, over, Counter[str](), ""
        self._tick = asyncio.Event()
        self.task = spawn(self._read(), name="refused-subs-reader")

    async def _read(self) -> None:
        with contextlib.suppress(ConnectionClosed):
            async for text in self.ws:
                head = text if isinstance(text, str) and text.startswith('{"t":"') else '{"t":"?"'
                kind = head[6 : head.index('"', 6)]  # every frame of the gateway leads with `t`
                self.got[kind] += 1
                if kind == "sub_ok":
                    self.last = head
                self._tick.set()
        self._tick.set()

    async def until(self, kind: str, n: int) -> None:
        async with asyncio.timeout(TIMEOUT_S):
            while self.got[kind] < n:
                self._tick.clear()
                await self._tick.wait()


async def dial(stack: Stack, token: str, held: list[str], over: str) -> Raw:
    """A socket past `hello` and `auth`, holding `held` with every snapshot in."""
    ws = await connect(
        f"ws://{HOST}:{stack.port}/ws",
        origin=Origin(ORIGIN),
        subprotocols=[Subprotocol("cv.v1.json")],
        proxy=None,
        ping_interval=None,
        open_timeout=TIMEOUT_S,
        max_size=4 * 1024 * 1024,
    )
    raw = Raw(ws, over)
    await ws.send(json.dumps({"t": "hello", "id": "h", "p": {"protocol": "cv.v1"}}))
    await raw.until("welcome", 1)
    await ws.send(json.dumps({"t": "auth", "id": "a", "p": {"access_token": token}}))
    await raw.until("auth_ok", 1)
    for i in range(0, len(held), 50):
        await ws.send(sub(held[i : i + 50], f"f{i}"))
    await raw.until("snap", len(held))
    return raw


async def test_anothers_book_frames_stay_in_budget_beside_eight_sockets_of_refused_subs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    sent: list[float] = []
    out = asyncio.Event()
    send_payload = gateway._Connection.send_payload

    async def traced(conn: gateway._Connection, payload: str | bytes) -> None:
        await send_payload(conn, payload)
        if isinstance(payload, str) and f'"ch":"{BOOK}"' in payload[:80]:
            sent.append(loop.time())
            out.set()

    monkeypatch.setattr(gateway._Connection, "send_payload", traced)
    async with granted() as stack:
        stack._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        viewer = stack.client(await stack.sessions.mint(str(VIEWER)), SEED)
        await viewer.start({"ch": BOOK}).until(lambda: viewer.synced, "the book's snapshot")
        token = (await stack.sessions.mint(str(SENDER))).access_token
        socks: list[Raw] = []
        for k in range(SOCKETS):
            socks.append(await dial(stack, token, *CAPS[k % 2]))
        replies = {raw: raw.got["sub_ok"] for raw in socks}
        spans: list[tuple[float, int, int]] = []
        gc.collect()
        gc.disable()  # a full collection of this process's heap would pause the loop once
        try:
            for seed in SEEDS:
                order = random.Random(seed)  # noqa: S311  (a seeded write order, not security)
                for lead in ALIGNMENTS:
                    await stack.clock.advance(STEP_S)
                    for raw in order.sample(socks, len(socks)):
                        for _ in range(FRAMES):
                            await raw.ws.send(raw.over)
                        replies[raw] += FRAMES
                    for _ in range(lead):
                        await asyncio.sleep(0)  # one loop turn, not a wait
                    out.clear()
                    published, before = loop.time(), len(sent)
                    stack.book_step()
                    async with asyncio.timeout(TIMEOUT_S):
                        await out.wait()
                    spans.append(((sent[before] - published) * 1000, seed, lead))
                    for raw in socks:
                        await raw.until("sub_ok", replies[raw])
        finally:
            gc.enable()
        for raw in socks:
            assert (raw.got["err"], raw.got["bye"]) == (0, 0)
            codes = {r["error"]["code"] for r in json.loads(raw.last)["p"]["results"]}
            assert codes == {"subscription_limit"}
            await raw.ws.close()
        await asyncio.gather(*(raw.task for raw in socks))
        assert (viewer.gaps, viewer.closes) == ([], [])
    spans.sort()
    p95, worst = spans[-2], spans[-1]  # of 21, the 20th is the nearest-rank 95th percentile
    print(
        f"#415: server-side spans over {len(spans)} publishes: second-worst {p95[0]:.2f} ms,"
        f" worst {worst[0]:.2f} ms"
    )
    assert p95[0] < BUDGET_MS, f"{p95[0]:.2f} ms at seed {p95[1]}, alignment {p95[2]}"
    assert worst[0] < WORST_MS, f"{worst[0]:.2f} ms at seed {worst[1]}, alignment {worst[2]}"
