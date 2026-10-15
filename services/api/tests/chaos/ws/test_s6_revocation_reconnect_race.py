"""#410 scenario 6: a grant withdrawn while the client is mid-reconnect is never resurrected.

E17-X02 elevation-of-privilege regression (E17 threat model WS-E02, AC-14's reconnect-race half).
The withdrawal takes the production path: the grant store the principal loader reads, then
`WsEvents.grants_changed`. The client resubscribes what it held before, so the server must refuse.
"""

from __future__ import annotations

import json

import pytest

from tests.chaos.ws._proxy import Fault
from tests.chaos.ws._server import BOOK, Stack
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER

pytestmark = pytest.mark.chaos

A, B = str(ACC_A), str(ACC_B)
TOPICS = {BOOK, "trades.BTCUSDT", "orders", "positions"}


async def test_s6_withdrawn_account_is_refused_on_resubscribe_and_never_emitted(
    stack: Stack,
) -> None:
    c = stack.client(await stack.sessions.mint(str(USER))).start(
        {"ch": BOOK},
        {"ch": "trades.BTCUSDT"},
        {"ch": "orders", "opts": {"exchange_account_ids": [A]}},
        {"ch": "positions", "opts": {"exchange_account_ids": [A, B]}},
    )
    await c.until(lambda: c.snapped == TOPICS, "first snapshots")
    assert stack.private("orders", ACC_A) == 1 and stack.book_step() == 1
    await c.until(lambda: c.seq.get(BOOK) == 2, "account A flows before the withdrawal")

    stack.proxy.inject(Fault.REFUSE)
    stack.proxy.inject(Fault.DROP)
    await stack.until_no_connections()  # the server saw the drop and unregistered the socket
    await stack.clock.advance(await c.next_backoff())  # attempt 1: refused at the proxy
    delay = await c.next_backoff()
    stack.granted.discard(ACC_A)  # the race: the grant goes between two attempts
    await stack.events.grants_changed(USER)
    mark = len(c.frames)
    stack.proxy.inject(Fault.HEAL)
    await stack.clock.advance(delay)
    await c.until(lambda: c.sessions == 2 and TOPICS - {"orders"} <= c.snapped, "resubscribed")

    assert c.denied == {"orders": "account_scope_denied"}  # the server refused the resubscription
    assert "orders" not in c.snapped  # (private topics resubscribe first, so it would be in)
    sub_ok = next(f for f in c.frames[mark:] if f["t"] == "sub_ok")
    assert [r["ch"] for r in sub_ok["p"]["results"]] == [
        "orders",
        "positions",
        BOOK,
        "trades.BTCUSDT",
    ]
    narrowed = next(r for r in sub_ok["p"]["results"] if r["ch"] == "positions")
    assert narrowed["effective"]["exchange_account_ids"] == [B]
    # Every emission for A now reaches nobody; B and the book still flow on the same socket.
    assert stack.private("orders", ACC_A) == 0 and stack.private("positions", ACC_A) == 0
    assert stack.private("positions", ACC_B) == 1 and stack.book_step() == 1
    await c.until(lambda: c.seq.get(BOOK) == 2, "post-race deltas")
    assert [f for f in c.frames[:mark] if f["t"] == "d" and A in json.dumps(f)]  # A did flow
    assert not [f for f in c.frames[mark:] if A in json.dumps(f)]  # and never after
    assert c.gaps == [] and c.closes == [1006]
    assert stack.proxy.trace == [
        ("open", 1), ("refuse", 1), ("drop", 1), ("refused", 2), ("heal", 0), ("open", 3)
    ]  # fmt: skip


async def test_s6b_grant_withdrawn_during_the_new_sockets_auth_is_not_reapplied(
    stack: Stack,
) -> None:
    c = stack.client(await stack.sessions.mint(str(USER))).start(
        {"ch": BOOK}, {"ch": "orders", "opts": {"exchange_account_ids": [A]}}
    )
    await c.until(lambda: c.snapped == {BOOK, "orders"}, "first snapshots")
    stack.proxy.inject(Fault.DROP)
    await stack.until_no_connections()
    release = stack.hold_next_read()
    await stack.clock.advance(await c.next_backoff())  # the reconnect's `auth` reads A, parks
    await stack.until_read_held()  # between the principal read and `registry.register`
    stack.granted.discard(ACC_A)
    await stack.events.grants_changed(USER)  # the new socket is not registered yet
    mark = len(c.frames)
    release.set()
    await c.until(lambda: c.sessions == 2 and BOOK in c.snapped, "resubscribed")
    delivered = stack.private("orders", ACC_A)
    assert stack.book_step() == 1
    await c.until(lambda: c.seq.get(BOOK) == 2, "post-race delta")
    assert c.denied == {"orders": "account_scope_denied"} and delivered == 0
    assert not [f for f in c.frames[mark:] if A in json.dumps(f)]
