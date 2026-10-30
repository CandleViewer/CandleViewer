"""E29-T13 (#4207) on the real `/ws` router: the `orders`, `executions` and `positions` topics as
`ws_wiring.oms_topics` builds them over the gateway's hub, a fake lane answering their snapshot
reads. Every frame the client gets is validated against 23-ws-protocol.md Sec.13 to Sec.15 before a
test sees it (`_harness`), under both subprotocols. The Gherkin scenarios of the wire: a snapshot,
then deltas in sequence; the server's account scope (C-12.4); one account event in causal order on
one connection (Sec.16.1 S5); and a slow consumer of `orders` or of `executions`, closed
`slow_consumer` (4429) on the budgeted pipeline (#2409: the flag-off rows went), never coalesced
or dropped (S4, E17-T03's close)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from candleviewer.auth.scopes import AccountGrant
from candleviewer.oms import ws_topics as wt
from candleviewer.ws_wiring import SnapshotRouter, oms_topics
from tests.contract.ws._harness import World, connect
from tests.unit.oms.test_ws_topics import new_fill, order, position, stored
from tests.unit.ws._seq_support import ACC_A, ACC_B

#: §16.2 / §8.4: the spec's outbound budget (`test_ws_s2_s9.SPEC_QUEUE_FRAMES`).
SPEC_QUEUE_FRAMES = 2_000


class Lane:
    """The lane's snapshot reads: A's open order, its fill and its position, each stamped 1."""

    async def read(self, family: wt.Family, account: UUID) -> wt.View:
        if account != ACC_A:
            return wt.View(1, ())
        items = {
            "orders": wt.order_item(order(account=ACC_A), environment="demo", stamp=1),
            "executions": wt.execution_item(stored(new_fill(account=ACC_A)), environment="demo"),
            "positions": wt.position_item(position(account=ACC_A), environment="demo", stamp=1),
        }
        return wt.View(1, (items[family],))


def wired() -> tuple[World, wt.OmsTopics[Any]]:
    """The harness's gateway, its three families served by the production adapter."""
    world = World()
    topics = oms_topics(world.hub)
    topics.attach(Lane())
    world.registry.services.snapshots = SnapshotRouter(dict.fromkeys(wt.FAMILIES, topics))
    return world, topics


def changes(n: int, stamp: int) -> list[wt.Change]:
    """One fill of A's order `n`: its execution and its order's step, as the lane sends them."""
    row = order(n, account=ACC_A, state="partially_filled")
    fill = wt.execution_item(stored(new_fill(f"e{n}", account=ACC_A, n=n)), environment="demo")
    moved = wt.order_item(row, environment="demo", stamp=stamp, change="fill")
    assert fill is not None
    return [
        wt.Change("executions", fill, fill["id"], "BTCUSDT", stamp),
        wt.Change("orders", moved, str(row.id), "BTCUSDT", stamp),
    ]


def moved_position(stamp: int) -> wt.Change:
    item = wt.position_item(position(account=ACC_A, size="0.8"), environment="demo", stamp=stamp)
    return wt.Change("positions", item, item["id"], "BTCUSDT", stamp)


def subscribed(c: Any, *fams: str, account: UUID = ACC_A) -> dict[str, Any]:
    entries = [{"ch": f, "opts": {"exchange_account_ids": [str(account)]}} for f in fams]
    return c.sub(*entries)


def test_a_client_that_subscribes_gets_a_snapshot_then_deltas() -> None:
    """Gherkin "A client that subscribes gets a snapshot, then deltas", on the wire: each topic's
    `snap` first, its payload the account's open order, recent fill and position, then only `d`
    frames, each `s` one more than the last on its stream."""
    world, topics = wired()
    with connect(world) as c:
        results = subscribed(c, "orders", "executions", "positions")["p"]["results"]
        assert [r["ok"] for r in results] == [True] * 3
        snaps = {f["ch"]: f for f in (c.next_of("snap") for _ in range(3))}
        assert [len(snaps[ch]["p"][ch]) for ch in ("orders", "executions", "positions")] == [1] * 3
        for n in (2, 3):
            world.call(topics.published, ACC_A, changes(n, stamp=10 + n))
        seen = [c.next_of("d") for _ in range(4)]
        for ch in ("executions", "orders"):
            s = [f["s"] for f in seen if f["ch"] == ch]
            assert s == [snaps[ch]["s"] + 1, snaps[ch]["s"] + 2]


def test_account_scoping_is_server_side() -> None:
    """Gherkin "Account scoping is server-side", on the wire: a Manager assigned to A only asking
    for B's `orders` is refused `account_scope_denied` by the server (C-12.4)."""
    world, _ = wired()
    world.grants = (AccountGrant(ACC_A, True, False, False),)
    with connect(world) as c:
        [result] = subscribed(c, "orders", account=ACC_B)["p"]["results"]
        assert (result["ok"], result["error"]["code"]) == (False, "account_scope_denied")


def test_one_account_event_reaches_a_connection_in_causal_order() -> None:
    """Sec.16.1 S5 on one connection: a fill's execution, then its order's step, then the position
    it moved, whatever the topics' lanes and windows (Sec.8.4)."""
    world, topics = wired()
    with connect(world) as c:
        subscribed(c, "positions", "orders", "executions")
        [c.next_of("snap") for _ in range(3)]
        world.call(topics.published, ACC_A, changes(2, stamp=20))
        world.call(topics.published, ACC_A, [moved_position(stamp=20)])
        world.clock.now += 0.2  # past the `positions` window (100 ms): it leaves on time
        assert [c.next_of("d")["ch"] for _ in range(3)] == ["executions", "orders", "positions"]


@pytest.mark.parametrize("family", ["orders", "executions"])
def test_a_slow_consumer_of_orders_or_executions_is_closed_never_coalesced_or_dropped(
    family: str,
) -> None:
    """Sec.6.2, Sec.8.4 step 3 (E17-T03): `orders` and `executions` ride the priority lane and are
    never coalesced or dropped, so a client of either that cannot keep up is closed
    `bye slow_consumer` / 4429; every `d` it got before is whole and in sequence. Produced in one
    event-loop turn, so the writer cannot drain."""
    world, topics = wired()
    with connect(world) as c:
        subscribed(c, family)
        snap = c.next_of("snap")
        fills = (changes(1, stamp=30 + n) for n in range(SPEC_QUEUE_FRAMES + 500))
        flood = [next(change for change in fill if change.family == family) for fill in fills]
        world.call(lambda: [topics.published(ACC_A, [change]) for change in flood])
        s = [snap["s"]]
        while (f := c.recv())["t"] != "bye":
            if f["t"] == "d":
                assert f["ch"] == family and len(f["p"][family]) == 1  # never merged
                s.append(f["s"])
        assert s == list(range(s[0], s[0] + len(s))) and len(s) - 1 <= SPEC_QUEUE_FRAMES
        assert (f["p"]["reason"], f["p"]["code"]) == ("slow_consumer", 4429)
        assert c.closed() == 4429


def test_a_client_resync_gets_a_fresh_snapshot_and_the_deltas_go_on_in_sequence() -> None:
    """Sec.7.5 on these topics: after a delta, a client `resync` of `orders` is answered with a
    `snap` (`client_resync`) built afresh, its `s` the next number, and the next delta follows it
    with `s` + 1 (Sec.7.1)."""
    world, topics = wired()
    with connect(world) as c:
        subscribed(c, "orders")
        first = c.next_of("snap")
        world.call(topics.published, ACC_A, changes(2, stamp=40)[1:])
        delta = c.next_of("d")
        c.send(
            {
                "t": "resync",
                "id": "r1",
                "ch": "orders",
                "p": {"last_seq": delta["s"], "reason": "sequence_gap"},
            }
        )
        again = c.next_of("snap")
        assert (again["meta"]["reason"], again["s"]) == ("client_resync", delta["s"] + 1)
        assert len(again["p"]["orders"]) == 1 and delta["s"] == first["s"] + 1
        world.call(topics.published, ACC_A, changes(3, stamp=41)[1:])
        assert c.next_of("d")["s"] == again["s"] + 1
