"""#410 scenario 7, gateway half: the kill switch reaches every socket within 1 s under chaos.

E17 threat model WS-E04 / AC-26: `WsEvents.kill_switch_changed` puts the `system` frame on every
connected socket (§12.5) within 1 s, whatever a stalled consumer or a reconnecting client is doing,
and a client that connects afterwards gets the live state in its `auth_ok` (§4.3). Nothing calls it
yet (#956 E39-S03), so the test fires it. The bound is wall time (`loop.time()`): delivery is
socket I/O, which no virtual clock measures. Chaos: a `PAUSE`d consumer; a redial, `auth` parked.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.chaos.ws._client import Client, each
from tests.chaos.ws._proxy import Fault
from tests.chaos.ws._server import BOOK, ORDERS, SEED, WORKSPACES, Stack
from tests.unit.ws._seq_support import USER, validate

pytestmark = pytest.mark.chaos

BOUND_S = 1.0  # WS-E04 / AC-26
STATE = {"engaged": True, "scope": "global", "reason": "chaos"}  # as the producer engages it
VIEW = {"engaged": True, "scope": "global"}  # what a manager's `system` frame carries (§15.9)


async def flip(stack: Stack) -> float:
    """Engage the kill switch as its producer will; the loop time it was fired at."""
    t0 = asyncio.get_running_loop().time()
    await stack.events.kill_switch_changed(engaged=True, reason="chaos")
    return t0


def seen(c: Client) -> bool:
    return c.system("kill_switch") != []


async def test_s7_kill_switch_reaches_healthy_sockets_within_1s_past_a_stall(stack: Stack) -> None:
    healthy = [
        stack.client(await stack.sessions.mint(str(USER)), SEED + n).start(*topics)
        for n, topics in enumerate(WORKSPACES)
    ]
    lane = await stack.lane()
    stalled = stack.client(await stack.sessions.mint(str(USER)), SEED + 9, via=lane)
    everyone = [*healthy, stalled.start({"ch": BOOK})]
    await each(everyone, lambda c: c.synced, "first snapshots")
    lane.inject(Fault.PAUSE)  # one consumer stops reading; the server keeps its frames queued
    assert stack.book_step() == len(everyone)
    await each(healthy, lambda c: c.seq.get(BOOK) == 2, "delta")
    assert stalled.seq.get(BOOK) == 1  # the stall holds: its delta is stuck in the proxy

    t0 = await flip(stack)
    await each(healthy, seen, "kill_switch frame")
    for c in healthy:
        (i,) = c.system("kill_switch")
        validate(c.frames[i])
        kill = c.frames[i]["p"]
        assert kill["kill_switch"] == VIEW and kill["severity"] == "critical"
        assert c.rx_at[i] - t0 < BOUND_S and not c.order_entry  # C12 on this frame alone
    await each(healthy, lambda c: any(f["t"] == "permission_change" for f in c.frames), "re-eval")
    for c in healthy:  # §12.5: the system frame first, then the re-evaluation
        assert [f["t"] for f in c.frames].index("permission_change") > c.system("kill_switch")[0]
    assert not seen(stalled) and stalled.order_entry  # nothing got through the stall

    lane.inject(Fault.HEAL)  # not lost: the stalled client gets the delta, then the switch
    await stalled.until(lambda: seen(stalled), "kill_switch frame after the stall")
    assert stalled.frames[stalled.system("kill_switch")[0]]["p"]["kill_switch"] == VIEW
    assert stalled.seq.get(BOOK) == 2 and not stalled.order_entry
    assert all(c.gaps == [] and c.closes == [] for c in everyone) and len(stack.gateway) == 4


async def test_s7b_kill_switch_flipped_mid_auth_is_in_the_auth_ok(stack: Stack) -> None:
    lane = await stack.lane()
    r = stack.client(await stack.sessions.mint(str(USER)), SEED + 9, via=lane)
    r.start(ORDERS, {"ch": BOOK})
    await r.until(lambda: r.synced, "first snapshots")
    lane.inject(Fault.DROP)  # R is cut off and backing off; time is frozen, so it stays there
    await stack.until_no_connections()
    healthy = [
        stack.client(await stack.sessions.mint(str(USER)), SEED + n).start(*topics)
        for n, topics in enumerate(WORKSPACES[:2])
    ]
    await each(healthy, lambda c: c.synced, "first snapshots")
    delay = await r.next_backoff()
    release = stack.hold_next_read()  # R's reconnect parks in its `auth`, before `auth_ok`
    await stack.clock.advance(delay)
    await stack.until_read_held()

    t0 = await flip(stack)  # the switch flips while R's `auth` is in flight
    await each(healthy, seen, "kill_switch frame")
    assert all(c.rx_at[c.system("kill_switch")[0]] - t0 < BOUND_S for c in healthy)
    assert r.sessions == 1 and r.order_entry  # R knows nothing yet
    release.set()
    await r.until(lambda: r.sessions == 2 and r.synced, "resubscribed")
    auth_oks = [f["p"]["kill_switch"] for f in r.frames if f["t"] == "auth_ok"]
    assert auth_oks == [{"engaged": False, "scope": "global"}, STATE]  # the live state, not stale
    assert not seen(r) and not r.order_entry  # the broadcast missed R; its `auth_ok` carried it
    assert all(c.gaps == [] and c.closes == [] for c in healthy) and r.gaps == []
    assert r.closes == [1006] and len(stack.gateway) == 3
