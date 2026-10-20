"""E40-T04 PR-B: the `alerts` WS topic on the real gateway parts (`ConnectionAuthz`, `TopicEmitter`,
`SequencingHub`), every frame validated against §13-§15 (`AlertUpdate`, §15.7).

The #2521 acceptance criterion is `test_another_users_snapshot_and_deltas_are_empty`: the owner is
recorded on the subscription at admit, the snapshot is built for that owner alone, and a delta
reaches only the subscriptions its owner owns.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _alerts_ws import ALERT_A, USER_A, USER_B, World

from candleviewer.alerts import ws_topic
from candleviewer.alerts.ws_topic import MAX_ITEMS_PER_DELTA, SNAPSHOT_MAX, delivery_item
from candleviewer.auth.generated_permissions import Permission


@pytest.fixture
async def world() -> Any:
    w = World()
    w.topic.start()
    yield w
    await w.topic.stop()


# --- scope (#2521) ------------------------------------------------------------------------


async def test_another_users_snapshot_and_deltas_are_empty(world: World) -> None:
    mine = world.reader.add(USER_A)
    theirs = world.reader.add(USER_B)
    a, b = world.conn(USER_A), world.conn(USER_B)
    a.sub(), b.sub()
    await world.loads()
    assert a.items() == [("snap", [mine.id], 1)]
    assert b.items() == [("snap", [theirs.id], 1)]
    assert ("list_page", str(USER_A)) in world.reader.calls
    assert {c for c in world.reader.calls if c[0] == "list_page"} == {
        ("list_page", str(USER_A)), ("list_page", str(USER_B)),
    }  # fmt: skip  # each owner's load reads that owner's rows alone
    await world.topic.deliveries_changed([mine.id])
    await world.changes()
    assert a.items() == [("d", [mine.id], 1)]
    assert b.items() == []  # A's delta reaches none of B's subscriptions


async def test_the_owner_is_the_principal_never_a_client_value(world: World) -> None:
    conn = world.conn(USER_A)
    result = conn.sub(user_id=str(USER_B))
    assert result["ok"] is False and result["error"]["code"] == "invalid_options"
    conn.sub()
    (sub,) = conn.authz.by_id.values()
    assert sub.owner == USER_A


async def test_without_alerts_read_the_subscription_is_forbidden(world: World) -> None:
    conn = world.conn(USER_A, frozenset({Permission.RULES_READ}))
    result = conn.sub()
    assert result["ok"] is False and result["error"]["code"] == "forbidden"
    assert world.reader.calls == []


async def test_a_subscription_without_an_owner_gets_nothing(world: World) -> None:
    conn = world.conn(USER_A)
    conn.sub()
    (sub,) = conn.authz.by_id.values()
    sub.owner = None  # as a defect would leave it: fail closed, no read
    world.reader.calls.clear()
    assert world.topic.build(sub) is None and world.reader.calls == []


# --- snapshot -----------------------------------------------------------------------------


async def test_a_snapshot_is_the_owners_unacked_deliveries_newest_first(world: World) -> None:
    older, newer = world.reader.add(USER_A), world.reader.add(USER_A)
    world.reader.add(USER_A, status="acked")
    world.reader.add(USER_A, status="queued")
    world.reader.add(USER_A, channel="email", status="failed")
    conn = world.conn(USER_A)
    result = conn.sub()
    assert result["ok"] is True and result["snapshot_pending"] is True
    assert conn.take() == []  # pending until the load lands (§7.7)
    await world.loads()
    assert conn.items() == [("snap", [newer.id, older.id], 2)]


async def test_the_snapshot_is_bounded_and_the_count_exact(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ws_topic, "SNAPSHOT_MAX", 3)
    for _ in range(5):
        world.reader.add(USER_A)
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    ((kind, ids, count),) = conn.items()
    assert kind == "snap" and len(ids) == 3 and count == 5
    assert SNAPSHOT_MAX == 500  # the module's own bound, SCR-014's 500


async def test_a_second_attach_is_served_from_the_view_without_a_read(world: World) -> None:
    world.reader.add(USER_A)
    first, second = world.conn(USER_A), world.conn(USER_A)
    first.sub()
    await world.loads()
    reads = len(world.reader.calls)
    second.sub()
    assert [t for t, _ in second.take()] == ["snap"] and len(world.reader.calls) == reads


async def test_an_unattached_topic_keeps_its_subscriptions_pending() -> None:
    w = World()
    w.topic._reader = None  # the fake storage backend never attaches one
    conn = w.conn(USER_A)
    assert conn.sub()["snapshot_pending"] is True
    assert w.topic._loads == {} and conn.take() == []


async def test_a_failed_load_stays_pending_and_the_next_flush_reads_again(world: World) -> None:
    world.reader.add(USER_A)
    world.reader.fail.add("list_page")
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    assert conn.take() == []
    world.reader.fail.clear()
    world.hub.flush_pending()
    await world.loads()
    assert [t for t, _ in conn.take()] == ["snap"]


async def test_views_are_bounded_least_recently_used_first() -> None:
    w = World(views_max=1)
    w.reader.add(USER_A), w.reader.add(USER_B)
    w.conn(USER_A).sub()
    await w.loads()
    w.conn(USER_B).sub()
    await w.loads()
    assert list(w.topic._views) == [USER_B]


async def test_the_topic_is_private_never_cached_and_never_continuous(world: World) -> None:
    conn = world.conn(USER_A)
    conn.sub()
    (sub,) = conn.authz.by_id.values()
    assert world.topic.generation(sub) == 0
    assert world.topic.continuity(sub, 1_790_000_000_000) is False


# --- deltas -------------------------------------------------------------------------------


async def test_an_ack_is_a_delta_with_the_new_count(world: World) -> None:
    d = world.reader.add(USER_A)
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    conn.take()
    world.reader.set(d.id, status="acked", acked_at=world.reader.rows[d.id].queued_at)
    await world.topic.deliveries_changed([d.id])
    await world.changes()
    ((kind, payload),) = conn.take()
    assert kind == "d" and payload["unacked_count"] == 0
    assert payload["deliveries"] == [delivery_item(world.reader.rows[d.id])]


async def test_unacked_only_gets_only_what_enters_or_leaves_the_unacked_set(world: World) -> None:
    sent = world.reader.add(USER_A)
    failed = world.reader.add(USER_A, channel="email", status="failed")
    queued = world.reader.add(USER_A, channel="desktop", status="queued")
    every, unacked = world.conn(USER_A), world.conn(USER_A)
    every.sub(), unacked.sub(unacked_only=True)
    await world.loads()
    every.take(), unacked.take()
    await world.topic.deliveries_changed([sent.id, failed.id, queued.id])
    await world.changes()
    assert every.items() == [("d", [sent.id, failed.id, queued.id], 1)]
    assert unacked.items() == [("d", [sent.id], 1)]
    await world.topic.deliveries_changed([failed.id])  # nothing for the unacked set
    await world.changes()
    assert len(every.take()) == 1 and unacked.take() == []


async def test_a_failure_brings_its_channel_failure_notice(world: World) -> None:
    failed = world.reader.add(USER_A, channel="desktop", status="failed")
    notice = world.reader.add(USER_A, context={"channel_failure": True,
                                               "failed_delivery_id": failed.id})  # fmt: skip
    conn = world.conn(USER_A)
    conn.sub(unacked_only=True)
    await world.loads()
    conn.take()
    await world.topic.deliveries_changed([failed.id])  # the producer names the failed row only
    await world.changes()
    assert conn.items() == [("d", [notice.id], 1)]


async def test_a_large_change_goes_out_in_frames_of_at_most_100_items(world: World) -> None:
    rows = [world.reader.add(USER_A) for _ in range(MAX_ITEMS_PER_DELTA * 2 + 5)]
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    conn.take()
    await world.topic.deliveries_changed([r.id for r in rows])
    await world.changes()
    sizes = [len(ids) for _, ids, _ in conn.items()]
    assert sizes == [MAX_ITEMS_PER_DELTA, MAX_ITEMS_PER_DELTA, 5]


async def test_a_deleted_users_row_is_published_to_nobody(world: World) -> None:
    orphan = world.reader.add(None)
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    conn.take()
    await world.topic.deliveries_changed([orphan.id])
    await world.changes()
    assert conn.take() == []


async def test_changes_are_only_queued_by_the_producer(world: World) -> None:
    """The producers (`on_change`) never wait on the fan-out: nothing is read before they return."""
    d = world.reader.add(USER_A)
    await world.topic.stop()  # no worker: the change stays queued
    world.reader.calls.clear()
    await world.topic.deliveries_changed([d.id])
    assert world.reader.calls == [] and world.topic._queue.qsize() == 1


# --- integrity: what could not be published is re-snapshotted ------------------------------


async def test_a_change_that_cannot_be_read_resyncs_every_alerts_subscription(
    world: World,
) -> None:
    a, b = world.conn(USER_A), world.conn(USER_B)
    world.reader.add(USER_A), world.reader.add(USER_B)
    a.sub(), b.sub()
    await world.loads()
    a.take(), b.take()
    world.reader.fail.add("get_many")
    await world.topic.deliveries_changed([1])
    await world.changes()
    world.reader.fail.clear()
    await world.loads()
    for conn in (a, b):
        frames = conn.take()
        assert [t for t, _ in frames][-1] == "snap"  # read again, as an upstream desync


async def test_a_full_queue_resyncs_instead_of_dropping_silently() -> None:
    w = World(queue_max=1)
    w.reader.add(USER_A)
    conn = w.conn(USER_A)
    conn.sub()
    await w.loads()
    conn.take()
    await w.topic.deliveries_changed([1])
    await w.topic.deliveries_changed([2])  # no worker yet: the queue is full
    assert w.topic._overflowed is True
    w.topic.start()
    await w.changes()
    await w.loads()
    assert "snap" in [t for t, _ in conn.take()]
    await w.topic.stop()


async def test_a_change_racing_a_load_makes_it_read_again(world: World) -> None:
    d = world.reader.add(USER_A)
    world.reader.gate = asyncio.Event()  # the load holds mid-read
    conn = world.conn(USER_A)
    conn.sub()
    await asyncio.wait_for(world.reader.entered.wait(), timeout=5)  # the load is mid-read
    world.reader.set(d.id, status="acked", acked_at=world.reader.rows[d.id].queued_at)
    await world.topic.deliveries_changed([d.id])  # its delta finds the subscription pending
    await world.changes()
    world.reader.gate.set()
    await world.loads()
    assert conn.items() == [("snap", [], 0)]  # the second read, which sees the ack
    assert [c for c in world.reader.calls if c[0] == "list_page"] == [
        ("list_page", str(USER_A)), ("list_page", str(USER_A)),
    ]  # fmt: skip


async def test_a_failing_publish_resyncs_that_owners_subscriptions(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = world.reader.add(USER_A)
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    conn.take()

    def boom(*_a: object, **_kw: object) -> int:
        raise RuntimeError("hub down")

    monkeypatch.setattr(world.topic, "_publish", boom)
    await world.topic.deliveries_changed([d.id])
    await world.changes()
    await world.loads()
    assert [t for t, _ in conn.take()][-1] == "snap"


# --- lifecycle ----------------------------------------------------------------------------


async def test_stop_cancels_the_worker_and_the_loads() -> None:
    w = World()
    w.reader.add(USER_A)
    w.reader.gate = asyncio.Event()  # a load that never finishes on its own
    w.topic.start()
    w.conn(USER_A).sub()
    worker, loads = w.topic._worker, list(w.topic._loads.values())
    assert worker is not None and loads
    await w.topic.stop()
    assert worker.cancelled() and all(t.cancelled() for t in loads)
    assert w.topic._loads == {}


def test_attach_is_once() -> None:
    w = World()
    with pytest.raises(ValueError, match="already attached"):
        w.topic.attach(w.reader)


def test_an_item_never_carries_a_withheld_field() -> None:
    w = World()
    row = w.reader.add(USER_A, context={"symbol": "BTCUSDT", "webhook_url_enc": "x"})
    item = delivery_item(row)
    assert set(item) == {"id", "alert_id", "channel", "status", "severity", "title", "message",
                         "symbol", "fired_at_ms", "acked_at_ms", "error"}  # fmt: skip
    assert item["alert_id"] == ALERT_A and "context" not in item
