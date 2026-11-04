"""E40-Q02 alert chaos 3, WS disconnect during a storm: the client reconnects, gets a snapshot
with an accurate `unacked_count`, and no delivery is lost or double-counted. In-process (no
network, fake clocks): the real evaluator's storm suppressor commits the 25 firings, the real
`alerts` topic publishes them on the real gateway parts (`tests.alerts._alerts_ws`), each frame
validated against 23-ws-protocol.md §15.7.

The client sees the first half of the storm as deltas, drops, and while it is gone the rest is
dispatched, five firings are suppressed (history only), the owner acknowledges three, and the
window ends in one summary delivery. The reconnect's snapshot must hold exactly the unacked `sent`
rows (each once) with their exact count, every dispatched firing must be in it or acknowledged,
and the count must keep moving by one per acknowledgement after it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from candleviewer.alerts.evaluator import AlertTick
from tests.alerts._alerts_ws import USER_A, World
from tests.alerts._evaluator_env import T0, Delivery, FakeStore, ir, make, row

pytestmark = pytest.mark.chaos
STORM, LIMIT = 25, 20  # firings inside one window; the suppressor's default deliveries per window


@pytest.fixture
async def world() -> AsyncIterator[World]:
    w = World()
    w.topic.start()
    yield w
    await w.topic.stop()


def landed(w: World, store: FakeStore, done: set[int]) -> list[int]:
    """The evaluator's new delivery rows as the deliveries reader sees them (queued, or suppressed
    history); their ids. `settle` is the dispatcher's `queued -> sent`."""
    ids = []
    for d in store.deliveries:
        if d.id not in done:
            done.add(d.id)
            ids.append(_land(w, d))
    return ids


def _land(w: World, d: Delivery) -> int:
    return w.reader.add(USER_A, id=1000 + d.id, status=d.status, title=d.title).id


async def settle(w: World, ids: list[int]) -> None:
    for i in ids:
        w.reader.set(i, status="sent")
    await w.topic.deliveries_changed(ids)


async def test_a_reconnect_mid_storm_gets_an_exact_snapshot_and_loses_nothing(
    world: World,
) -> None:
    rows = [row(f"a{i:02}", owner_user_id=str(USER_A), condition_ir=ir(const=i))
            for i in range(STORM)]  # fmt: skip
    ev, store, src, clock, metrics = make(*rows)
    await ev.warm_up()
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    assert conn.items() == [("snap", [], 0)]

    src.set("price", 70000, T0)
    await ev.process(AlertTick("on_price_update", T0, None))  # the storm: 25 firings at once
    done: set[int] = set()
    ids = landed(world, store, done)
    queued = [i for i, d in zip(ids, store.deliveries, strict=True) if d.status == "queued"]
    suppressed = sorted(set(ids) - set(queued))
    assert (len(queued), len(suppressed)) == (LIMIT, STORM - LIMIT)
    seen: list[int] = []
    for start in range(0, 10, 5):  # the first half reaches the client live, in two batches
        await settle(world, queued[start : start + 5])
        await world.changes()
        for kind, got, count in conn.items():
            assert kind == "d" and count == start + 5
            seen += got
    assert seen == queued[:10]

    world.hub.unregister(conn.authz)  # the socket drops mid-storm
    await settle(world, queued[10:])
    await world.topic.deliveries_changed(suppressed)
    acked = queued[:3]
    for i in acked:
        world.reader.ack(i)
    await world.topic.deliveries_changed(acked)
    clock.now = T0 + 60_000  # the window ends: one summary delivery for the five suppressed
    await ev.flush_storms()
    (summary,) = landed(world, store, done)
    assert store.deliveries[-1].context["suppressed"] == STORM - LIMIT
    await settle(world, [summary])
    await world.changes()
    assert conn.take() == []  # nothing reaches the dropped socket

    again = world.conn(USER_A)
    again.sub()
    await world.loads()
    ((kind, snap, count),) = again.items()
    unacked = set(queued[3:]) | {summary}
    assert kind == "snap" and len(snap) == len(set(snap)) == count == len(unacked) == 18
    assert set(snap) == unacked and not set(snap) & set(suppressed)
    assert set(queued) | {summary} <= set(snap) | set(acked)  # every dispatched firing: none lost
    assert count == await world.reader.unacked_count(str(USER_A))
    assert metrics.get("cv_alert_suppressed_total", "storm") == STORM - LIMIT
    assert len(world.reader.rows) == STORM + 1  # all 25 in history, plus the summary

    world.reader.ack(queued[3])  # after the snapshot, each acknowledgement moves the count by one
    await world.topic.deliveries_changed([queued[3]])
    await world.changes()
    assert again.items() == [("d", [queued[3]], 17)]
