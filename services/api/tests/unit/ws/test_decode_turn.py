"""#4924 (23 §8.5): a user's decode turn, deterministically, on the rig's fake clock.

Two sockets of one user. A frame of more than one token is handled (decoded and dispatched) only
while its socket holds the user's turn, an `asyncio.Lock` the hub keeps with the user's decode
budget: the second socket waits for it and is served after the first, in order. The turn is free
again however the handling ends (an oversize close, a rate refusal, a fault in the dispatch), and
when a reader waiting for it is cancelled. Each test runs on a `VirtualTimeLoop` (`@virtual`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import pytest

import candleviewer.ws.gateway as gateway
from candleviewer.ws.lifecycle import DECODE_BUDGET_BURST
from tests.unit.audit.audit_waits import virtual
from tests.unit.ws._auth_rig import DEADLINE_S, Rig, Sock, user_of

# S105: "good-turn" is the rig's fake test token (`_auth_rig`), not a credential.
TOKEN = "good-turn"  # noqa: S105
USER = user_of(TOKEN)
#: A `ping` of 40 000 bytes: 2 tokens, so it takes the user's turn.
PAD = "x" * 40_000


def heavy(fid: str) -> dict[str, Any]:
    return {"t": "ping", "id": fid, "p": {"pad": PAD}}


def feed_text(sock: Sock, text: str) -> None:
    sock.inbound.put_nowait({"type": "websocket.receive", "text": text})


async def two_sockets(rig: Rig) -> tuple[Sock, Sock, asyncio.Lock, list[asyncio.Task[None]]]:
    """Two sockets of `USER`, each past `auth_ok`, and the user's turn."""
    socks, handlers = [Sock(), Sock()], []
    for sock in socks:
        handlers.append(await rig.open(sock))
        assert (await rig.auth(sock, TOKEN))["t"] == "auth_ok"
    return socks[0], socks[1], rig.hub.decode_turn(USER), handlers


async def turns(n: int = 20) -> None:
    """Let the loop run `n` turns (no time passes)."""
    for _ in range(n):
        await asyncio.sleep(0)


async def end(sock: Sock, handler: asyncio.Task[None]) -> None:
    sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
    with contextlib.suppress(Exception):
        await handler


@virtual
async def test_a_second_socket_waits_for_the_turn_and_is_served_after_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, order = Rig(), list[str]()
    handle = gateway._Connection.decode_weighed

    def spy(conn: gateway._Connection, weighed: Any) -> Any:
        order.append(weighed.raw[weighed.raw.index('"id"') :][7:9])
        return handle(conn, weighed)

    async with asyncio.timeout(DEADLINE_S):
        a, b, turn, handlers = await two_sockets(rig)
        monkeypatch.setattr(gateway._Connection, "decode_weighed", spy)
        await turn.acquire()  # the turn is taken: both wait
        a.feed(heavy("a1"))
        await turns()
        b.feed(heavy("b1"))
        await turns()
        assert order == [] and len(turn._waiters or ()) == 2
        turn.release()
        assert (await a.sent.get())["id"] == "a1"
        assert (await b.sent.get())["id"] == "b1"
        assert order == ["a1", "b1"] and not turn.locked()
        for sock, handler in zip((a, b), handlers, strict=True):
            await end(sock, handler)


@virtual
async def test_the_turn_is_free_after_an_oversize_close() -> None:
    """A frame over the `pong` bound whose `t` is not its first member: it takes the turn, is
    decoded, and is closed `protocol_violation`; the reader ends holding nothing."""
    rig = Rig()
    async with asyncio.timeout(DEADLINE_S):
        a, b, turn, handlers = await two_sockets(rig)
        feed_text(a, json.dumps({"id": "x", "t": "pong", "p": {"pad": PAD}}))
        await handlers[0]
        assert not turn.locked()
        b.feed(heavy("b1"))  # the other socket is served
        assert (await b.sent.get())["id"] == "b1"
        await end(b, handlers[1])


@virtual
async def test_the_turn_is_free_after_a_refusal() -> None:
    """The user's budget spent: the frame takes the turn, is refused `client_rate_limited`, and
    the turn is free."""
    rig = Rig()
    async with asyncio.timeout(DEADLINE_S):
        a, b, turn, handlers = await two_sockets(rig)
        budget = rig.hub.decode_budget(USER, rig.now)
        budget.take(DECODE_BUDGET_BURST)
        a.feed(heavy("a1"))
        frame = await a.sent.get()
        assert (frame["t"], frame["p"]["code"]) == ("err", "client_rate_limited")
        await turns()
        assert not turn.locked()
        for sock, handler in zip((a, b), handlers, strict=True):
            await end(sock, handler)


@virtual
async def test_the_turn_is_free_after_a_fault_in_the_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `ping`'s reply raises inside the dispatch: the handler ends `internal_error` and the
    turn is free for the other socket."""
    rig = Rig()

    def fault(_value: Any) -> Any:
        raise RuntimeError("dispatch fault")

    async with asyncio.timeout(DEADLINE_S):
        a, b, turn, handlers = await two_sockets(rig)
        monkeypatch.setattr(gateway, "client_epoch_ms", fault)
        a.feed({**heavy("a1"), "p": {"pad": PAD, "client_ms": 1}})
        with contextlib.suppress(Exception):
            await handlers[0]
        assert not turn.locked()
        monkeypatch.undo()
        b.feed(heavy("b1"))
        assert (await b.sent.get())["id"] == "b1"
        await end(b, handlers[1])


@virtual
async def test_a_reader_cancelled_while_waiting_leaves_the_turn_free() -> None:
    rig = Rig()
    async with asyncio.timeout(DEADLINE_S):
        a, b, turn, handlers = await two_sockets(rig)
        await turn.acquire()
        a.feed(heavy("a1"))
        await turns()
        assert len(turn._waiters or ()) == 1
        handlers[0].cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await handlers[0]
        turn.release()
        await turns()
        assert not turn.locked() and not turn._waiters
        b.feed(heavy("b1"))  # and the other socket takes it at once
        assert (await b.sent.get())["id"] == "b1"
        await end(b, handlers[1])
