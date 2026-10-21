"""E40-T04 PR-B: the `alerts` WS topic on the real gateway parts (`ConnectionAuthz`, `TopicEmitter`,
`SequencingHub`), every frame validated against §13-§15 (`AlertUpdate`, §15.7).

The #2521 acceptance criterion is `test_another_users_snapshot_and_deltas_are_empty`: the owner is
recorded on the subscription at admit, the snapshot is built for that owner alone, and a delta
reaches only the subscriptions its owner owns.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.alerts import ws_topic
from candleviewer.alerts.ws_topic import (
    LOAD_BACKOFF_S,
    LOAD_ROUNDS,
    LOAD_TRIES,
    MAX_ITEMS_PER_DELTA,
    SNAPSHOT_MAX,
    delivery_item,
)
from candleviewer.auth.generated_permissions import Permission
from tests.alerts._alerts_ws import ALERT_A, USER_A, USER_B, USER_C, World


@pytest.fixture
async def make_world() -> AsyncIterator[Callable[..., World]]:
    """Worlds whose worker the test starts when it wants one; each is stopped at the end."""
    made: list[World] = []

    def make(**kw: Any) -> World:
        made.append(World(**kw))
        return made[-1]

    yield make
    for w in made:
        await w.topic.stop()


@pytest.fixture
async def world(make_world: Callable[..., World]) -> World:
    w = make_world()
    w.topic.start()
    return w


def _events(logs: list[Any]) -> list[tuple[str, str]]:
    """The topic's own log lines (the hub's `ws resync` ones aside), as (event, level)."""
    return [(e["event"], e["log_level"]) for e in logs if e["event"].startswith("alerts_topic_")]


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
    assert conn.subscription().owner == USER_A


async def test_without_alerts_read_the_subscription_is_forbidden(world: World) -> None:
    conn = world.conn(USER_A, frozenset({Permission.RULES_READ}))
    result = conn.sub()
    assert result["ok"] is False and result["error"]["code"] == "forbidden"
    assert world.reader.calls == []


async def test_a_subscription_without_an_owner_gets_nothing(world: World) -> None:
    conn = world.conn(USER_A)
    conn.sub()
    sub = conn.subscription()
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
    w = World(attached=False)  # the fake storage backend never attaches a reader
    conn = w.conn(USER_A)
    assert conn.sub()["snapshot_pending"] is True
    assert w.loading() == [] and conn.take() == []


async def test_a_failed_load_stays_pending_and_the_next_flush_reads_again(world: World) -> None:
    """Every try failed and no timer is left: a flush (the gateway settling) asks again."""
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


async def test_a_failed_load_is_retried_by_the_owners_next_change(world: World) -> None:
    """No topic-owned retry otherwise: the change's delta is dropped by the pending subscription,
    and without the change's flush it would wait for an unrelated one or a resubscribe."""
    d = world.reader.add(USER_A)
    world.reader.fail.add("list_page")
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    assert conn.take() == []
    world.reader.fail.clear()
    await world.topic.deliveries_changed([d.id])
    await world.changes()
    await world.loads()
    assert conn.items() == [("snap", [d.id], 1)]


async def test_views_are_bounded_least_recently_used_first(
    make_world: Callable[..., World],
) -> None:
    w = make_world(views_max=1)
    w.reader.add(USER_A), w.reader.add(USER_B)
    w.conn(USER_A).sub()
    await w.loads()
    w.conn(USER_B).sub()
    await w.loads()
    assert w.views() == [USER_B]


async def test_the_topic_is_private_never_cached_and_never_continuous(world: World) -> None:
    conn = world.conn(USER_A)
    conn.sub()
    sub = conn.subscription()
    assert world.topic.generation(sub) == 0
    assert world.topic.continuity(sub, 1_790_000_000_000) is False


# --- snapshot loads: tried again, and bounded ---------------------------------------------


def test_the_load_retry_constants_match_the_contract_doc() -> None:
    """23-ws-protocol.md §6.2.1 (Integrity): a load whose read fails is "tried three times in all,
    backed off and jittered". `LOAD_TRIES` is that three and `LOAD_BACKOFF_S` (doubled per try) the
    first wait: changing either is a contract change, so the doc changes with it."""
    assert (LOAD_TRIES, LOAD_BACKOFF_S) == (3, 0.5)


@pytest.mark.parametrize(("jitter", "share"), [(0.0, 0.5), (1.0, 1.0)], ids=["floor", "ceiling"])
async def test_the_backoff_is_jittered_between_half_and_the_whole_of_each_wait(
    make_world: Callable[..., World], jitter: float, share: float
) -> None:
    """The owners a database blip failed together must not retry in lockstep: `rng` at 0 waits half
    of each doubled step (0.25 s, then 0.5 s), at 1 the whole of it, the range [0.5, 1.0]. Written
    on the constants, so a change to them fails the test that pins them and not this one."""
    w = make_world(rng=lambda: jitter)
    w.reader.add(USER_A)
    w.reader.fail.add("list_page")
    w.conn(USER_A).sub()
    await w.loads()
    assert w.slept == [LOAD_BACKOFF_S * 2**n * share for n in range(LOAD_TRIES - 1)]


@pytest.mark.parametrize("read", ["list_page", "unacked_count"])
async def test_a_load_that_fails_once_is_tried_again_after_a_backoff(
    world: World, read: str
) -> None:
    d = world.reader.add(USER_A)
    world.reader.flaky[read] = 1
    conn = world.conn(USER_A)
    with capture_logs() as logs:
        conn.sub()
        await world.loads()
    assert conn.items() == [("snap", [d.id], 1)]  # served once the second try had read it
    assert world.reader.count("list_page") == 2 and world.slept == [LOAD_BACKOFF_S]
    assert _events(logs) == [("alerts_topic_load_retry", "warning")]  # never the error


async def test_a_load_that_fails_every_try_is_logged_once_and_stays_pending(world: World) -> None:
    d = world.reader.add(USER_A)
    world.reader.fail.add("list_page")
    conn = world.conn(USER_A)
    with capture_logs() as logs:
        conn.sub()
        await world.loads()
    assert conn.take() == [] and conn.subscription().snapshot_pending
    assert world.reader.count("list_page") == LOAD_TRIES  # tried this often in all, no more
    assert world.slept == [LOAD_BACKOFF_S * 2**n for n in range(LOAD_TRIES - 1)]  # doubled
    assert _events(logs) == [("alerts_topic_load_retry", "warning")] * (LOAD_TRIES - 1) + [
        ("alerts_topic_load_failed", "error")
    ]
    (failed,) = [e for e in logs if e["event"] == "alerts_topic_load_failed"]
    assert (failed["error"], failed["tries"]) == ("RuntimeError", LOAD_TRIES)
    assert "list_page failed" not in repr(logs)  # the error's type, never its message (C-12.6)
    world.reader.fail.clear()
    await world.topic.deliveries_changed([d.id])  # the owner's next change loads again
    await world.changes()
    await world.loads()
    assert conn.items() == [("snap", [d.id], 1)]


async def test_a_load_backing_off_does_not_hold_its_slot(
    make_world: Callable[..., World],
) -> None:
    w = make_world(loads_max=1)
    mine, theirs = w.reader.add(USER_A), w.reader.add(USER_B)
    w.reader.flaky["list_page"] = 1  # A's read, the first, fails
    w.backoff_gate = asyncio.Event()  # and A waits between its tries until the test lets it
    a, b = w.conn(USER_A), w.conn(USER_B)
    a.sub()
    await asyncio.wait_for(w.backing_off.wait(), timeout=5)
    b.sub()
    await w.loaded(USER_B)  # B's load runs and serves while A is between tries
    assert b.items() == [("snap", [theirs.id], 1)] and a.take() == []
    assert w.loading() == [USER_A] and w.slept == [LOAD_BACKOFF_S]
    w.backoff_gate.set()
    await w.loads()
    assert a.items() == [("snap", [mine.id], 1)]


async def test_a_change_drops_the_owners_view_before_a_later_attach_reads(world: World) -> None:
    d = world.reader.add(USER_A)
    first = world.conn(USER_A)
    first.sub()
    await world.loads()
    first.take()
    world.reader.ack(d.id)
    await world.topic.deliveries_changed([d.id])
    await world.changes()
    assert first.items() == [("d", [d.id], 0)]
    second = world.conn(USER_A)  # a page reload: another connection of the same user
    second.sub()
    await world.loads()
    assert second.items() == [("snap", [], 0)]  # not the view cached before the ack
    assert world.reader.count("list_page") == 2


async def test_a_change_racing_every_read_is_served_then_resnapshotted(world: World) -> None:
    d = world.reader.add(USER_A)
    conn = world.conn(USER_A)
    rows = [d]  # the owner's deliveries, oldest first, as the changes land
    snaps_at_read: list[int] = []  # the snaps the owner had when each read started

    async def a_change_lands() -> None:  # after the read took its rows, the worker publishes it
        snaps_at_read.append(len(conn.snap_reasons()))
        if len(snaps_at_read) <= LOAD_ROUNDS:
            rows.append(world.reader.add(USER_A))
            await world.topic.deliveries_changed([rows[-1].id])
            await world.changes()

    world.reader.on_list_page = a_change_lands
    conn.sub()
    await world.loads()
    # LOAD_ROUNDS reads, each outdated by a change, then it served; one read more after the snap
    assert snaps_at_read == [0] * LOAD_ROUNDS + [1]
    assert conn.snap_reasons() == ["initial", "upstream_desync"]  # `load_raced` re-snapshots
    assert conn.items() == [
        ("snap", [r.id for r in reversed(rows[:LOAD_ROUNDS])], len(rows)),  # the last read's rows
        ("snap", [r.id for r in reversed(rows)], len(rows)),  # the owner's current set
    ]


async def test_batches_queued_before_the_worker_starts_are_read_in_one_round(
    make_world: Callable[..., World],
) -> None:
    w = make_world()
    rows = [w.reader.add(USER_A) for _ in range(3)]
    conn = w.conn(USER_A)
    conn.sub()
    await w.loads()
    conn.take()
    for row in rows:  # three producers, three batches, nobody to take them yet
        await w.topic.deliveries_changed([row.id])
    assert w.queued() == 3
    w.topic.start()
    await w.changes()  # `Queue.join`: every batch counts as handled
    assert [c for c in w.reader.calls if c[0] == "get_many"] == [
        ("get_many", tuple(r.id for r in rows))  # one read of the union
    ]
    assert conn.items() == [("d", [r.id for r in rows], 3)] and w.running()


async def test_a_round_stops_taking_batches_once_it_holds_the_id_bound(
    make_world: Callable[..., World], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ws_topic, "BATCH_IDS_MAX", 3)
    w = make_world()
    ids = [w.reader.add(USER_A).id for _ in range(5)]
    for batch in (ids[:2], ids[2:4], ids[4:]):
        await w.topic.deliveries_changed(batch)
    w.topic.start()
    await w.changes()
    reads = [c[1] for c in w.reader.calls if c[0] == "get_many"]
    # the second batch took the round past the bound, so there is no third in it
    assert reads == [tuple(ids[:4]), tuple(ids[4:])]
    assert w.running()


@pytest.mark.parametrize("loads_max", [1, 2])
async def test_loads_never_run_more_than_loads_max_at_once(
    make_world: Callable[..., World], loads_max: int
) -> None:
    w = make_world(loads_max=loads_max)
    users = (USER_A, USER_B, USER_C)
    rows = {u: w.reader.add(u) for u in users}
    w.reader.gate = asyncio.Event()  # every read holds, as a slow query would
    conns = {u: w.conn(u) for u in users}
    for conn in conns.values():
        conn.sub()
    await asyncio.wait_for(w.reader.entered.wait(), timeout=5)
    for _ in range(3):  # the loads that can run have run
        await asyncio.sleep(0)
    assert w.reader.reading == loads_max == w.reader.count("list_page")
    w.reader.gate.set()
    await w.loads()
    assert w.reader.most_reading == loads_max and w.reader.count("list_page") == len(users)
    for user, conn in conns.items():
        assert conn.items() == [("snap", [rows[user].id], 1)]


async def test_a_round_that_fails_is_contained_and_every_subscription_reads_again(
    world: World,
) -> None:
    mine, theirs = world.reader.add(USER_A), world.reader.add(USER_B)
    poison = world.reader.add(USER_A, user_id="not-a-uuid")  # no owner can be built from it
    a, b = world.conn(USER_A), world.conn(USER_B)
    a.sub(), b.sub()
    await world.loads()
    a.take(), b.take()
    with capture_logs() as logs:
        await world.topic.deliveries_changed([poison.id])
        await world.changes()
        await world.loads()
    assert [(e["event"], e["error"]) for e in logs if e["event"].endswith("round_failed")] == [
        ("alerts_topic_round_failed", "ValueError")
    ]
    assert a.snap_reasons() == b.snap_reasons() == ["upstream_desync"]
    assert a.items() == [("snap", [mine.id], 1)] and b.items() == [("snap", [theirs.id], 1)]
    assert world.running()  # a later change is still published
    world.reader.ack(mine.id)
    await world.topic.deliveries_changed([mine.id])
    await world.changes()
    assert a.items() == [("d", [mine.id], 0)] and b.items() == []


async def test_a_resync_of_everyone_makes_a_load_in_flight_read_again(world: World) -> None:
    d = world.reader.add(USER_A)
    world.reader.gate = asyncio.Event()  # the load holds mid-read
    conn = world.conn(USER_A)
    conn.sub()
    await asyncio.wait_for(world.reader.entered.wait(), timeout=5)
    world.reader.ack(d.id)  # after the read took its rows
    world.reader.fail.add("get_many")  # the change cannot be read: every subscription resyncs
    await world.topic.deliveries_changed([d.id])
    await world.changes()
    world.reader.fail.clear()
    world.reader.gate.set()
    await world.loads()
    assert world.reader.pages == [[d.id], []]  # the read in flight was outdated by the resync
    assert conn.items() == [("snap", [], 0)]


async def test_a_failing_flush_after_a_load_is_contained(world: World) -> None:
    d = world.reader.add(USER_A)
    conn = world.conn(USER_A)
    world.broken.add("flush_pending")
    with capture_logs() as logs:
        conn.sub()
        await world.loads()
    assert _events(logs) == [("alerts_topic_flush_failed", "warning")] and conn.take() == []
    world.broken.clear()
    world.hub.flush_pending()  # the view the load stored serves the next flush, without a read
    assert conn.items() == [("snap", [d.id], 1)] and world.reader.count("list_page") == 1


async def test_a_failing_flush_after_a_change_does_not_fail_the_round(world: World) -> None:
    d = world.reader.add(USER_A)
    world.reader.fail.add("list_page")
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()  # every try failed: the subscription stays pending
    world.reader.fail.clear()
    world.broken.add("flush_pending")
    with capture_logs() as logs:
        await world.topic.deliveries_changed([d.id])
        await world.changes()
    # contained where it happened: no `round_failed`, no resync of anyone
    assert _events(logs) == [("alerts_topic_flush_failed", "warning")]
    assert conn.take() == [] and world.loading() == [] and world.running()


# --- deltas -------------------------------------------------------------------------------


async def test_an_ack_is_a_delta_with_the_new_count(world: World) -> None:
    d = world.reader.add(USER_A)
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    conn.take()
    world.reader.ack(d.id)
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
    assert world.reader.calls == [] and world.queued() == 1


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


async def test_a_full_queue_resyncs_instead_of_dropping_silently(
    make_world: Callable[..., World],
) -> None:
    w = make_world(queue_max=1)
    w.reader.add(USER_A)
    conn = w.conn(USER_A)
    conn.sub()
    await w.loads()
    conn.take()
    with capture_logs() as logs:
        await w.topic.deliveries_changed([1])
        await w.topic.deliveries_changed([2])  # no worker yet: the queue is full
        await w.topic.deliveries_changed([3])
    assert [(e["event"], e["queue_max"]) for e in logs] == [("alerts_topic_queue_full", 1)]  # once
    w.topic.start()
    await w.changes()
    await w.loads()
    assert "snap" in [t for t, _ in conn.take()]


async def test_a_change_racing_a_load_makes_it_read_again(world: World) -> None:
    d = world.reader.add(USER_A)
    world.reader.gate = asyncio.Event()  # the load holds mid-read
    conn = world.conn(USER_A)
    conn.sub()
    await asyncio.wait_for(world.reader.entered.wait(), timeout=5)  # the load is mid-read
    world.reader.ack(d.id)  # after the read took its rows: they still carry the delivery
    await world.topic.deliveries_changed([d.id])  # its delta finds the subscription pending
    await world.changes()
    world.reader.gate.set()
    await world.loads()
    assert world.reader.pages == [[d.id], []]  # the first read is outdated, the second is served
    assert conn.items() == [("snap", [], 0)]  # the second read, which sees the ack


async def test_a_failing_publish_resyncs_that_owners_subscriptions(world: World) -> None:
    d = world.reader.add(USER_A)
    conn = world.conn(USER_A)
    conn.sub()
    await world.loads()
    conn.take()
    world.broken.add("publish")
    with capture_logs() as logs:
        await world.topic.deliveries_changed([d.id])
        await world.changes()
        await world.loads()
    assert _events(logs) == [("alerts_topic_publish_failed", "warning")]
    assert [t for t, _ in conn.take()][-1] == "snap"


# --- lifecycle ----------------------------------------------------------------------------


async def test_stop_cancels_the_worker_and_the_loads(make_world: Callable[..., World]) -> None:
    w = make_world()
    w.reader.add(USER_A)
    w.reader.gate = asyncio.Event()  # a load that never finishes on its own
    w.topic.start()
    w.conn(USER_A).sub()
    tasks = w.tasks()
    assert len(tasks) == 2  # the worker and the load
    await w.topic.stop()
    assert all(t.cancelled() for t in tasks)
    assert w.tasks() == [] and not w.running()


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
