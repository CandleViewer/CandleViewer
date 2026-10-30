"""E29-T13 (#4207): the serving loop's half of the `orders`, `executions` and `positions` topics
(`oms/ws_topics.py`, `OmsTopics`) on the real gateway parts (`ConnectionAuthz`, `TopicEmitter`,
`SequencingHub`), every frame validated against 23-ws-protocol.md Sec.13 to Sec.15: a snapshot
loaded beside the subscription, then deltas in sequence; the account scope the hub holds each
delta to (C-12.4, the IDOR case) and the permission each family needs; the `symbols` and
`open_only` options; the `executions` snapshot's newest 100; a load a delta races, one that fails,
a view a delta outdates; the causal order of one account's changes (Sec.16.1 S5); a resync. A fake
lane answers the reads: no network, no sleeps."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.oms import ws_topics as wt
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices
from candleviewer.ws.sequencing import (
    PRIVATE_CAUSAL_ORDER,
    SequencingHub,
    SnapshotBody,
    TopicEmitter,
)
from tests.unit.oms.test_ws_topics import (
    T0_MS,
    A,
    B,
    new_fill,
    order,
    position,
    stored,
)
from tests.unit.ws._seq_support import validate

USER = UUID(int=0x100)
READS = frozenset({Permission.ORDERS_READ, Permission.EXECUTIONS_READ, Permission.POSITIONS_READ})


def manager(*accounts: UUID, permissions: frozenset[Permission] = READS) -> PrincipalSnapshot:
    grants = tuple(AccountGrant(account, True, False, False) for account in accounts)
    return PrincipalSnapshot(USER, frozenset({"manager"}), permissions, grants)


def owner() -> PrincipalSnapshot:
    return PrincipalSnapshot(USER, frozenset({"owner"}), READS)


class Lane:
    """The lane's reads (`SnapshotReads`): each (family, account)'s items, stamped with `stamp`
    when the read starts; a read can be held (`gate`), fail (`error`), or run `during` meanwhile,
    as a delta landing on the serving loop while the read is on the lane."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, UUID], tuple[dict[str, Any], ...]] = {}
        self.stamp = T0_MS
        self.reads: list[tuple[str, UUID]] = []
        self.gate: asyncio.Event | None = None
        self.error: BaseException | None = None
        self.during: Callable[[], None] | None = None

    async def read(self, family: wt.Family, account: UUID) -> wt.View:
        self.reads.append((family, account))
        stamp = self.stamp
        if self.during is not None:
            self.during()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return wt.View(stamp, self.items.get((family, account), ()))


class Conn:
    """One authenticated socket on the hub: its subscriptions and every frame it was sent."""

    def __init__(self, world: World, principal: PrincipalSnapshot) -> None:
        self.frames: list[dict[str, Any]] = []
        services = SubscriptionServices(snapshots=world.topics, sequencing=world.hub)
        self.authz = ConnectionAuthz(principal, services)
        self.emitter = TopicEmitter(
            self._push, connection_id="ws_test", wall_ms=lambda: T0_MS, clock=lambda: 0.0,
            source=world.topics,
        )  # fmt: skip
        world.hub.register(self.authz, self.emitter)

    def _push(self, frame: dict[str, Any]) -> None:
        validate(frame)
        self.frames.append(frame)

    def sub(self, ch: str, *accounts: UUID, **opts: Any) -> dict[str, Any]:
        entry = {"ch": ch, "opts": {"exchange_account_ids": [str(a) for a in accounts], **opts}}
        result, sub = self.authz.admit(entry)
        if sub is not None:
            sub.announced = True  # the gateway's `sub_ok` is queued (#2831)
            self.emitter.flush_pending([sub])
        return result

    def take(self) -> list[tuple[str, str, dict[str, Any]]]:
        frames, self.frames = self.frames, []
        return [(f["t"], f["ch"], f["p"]) for f in frames]


class World:
    """The topics on a hub of their own, attached to a fake lane."""

    def __init__(self, *, attach: bool = True, refuse: str | None = None, **kw: Any) -> None:
        self.hub = SequencingHub()
        self.lane = Lane()
        self.refuse = refuse  # a family whose every non-empty publish the hub refuses
        self.topics = wt.OmsTopics(
            self._publish, self.hub.flush_pending, self.hub.resnapshot, SnapshotBody,
            order=PRIVATE_CAUSAL_ORDER, sleep=self._slept, rng=lambda: 1.0, **kw,
        )  # fmt: skip
        self.slept: list[float] = []
        if attach:
            self.topics.attach(self.lane)

    async def _slept(self, seconds: float) -> None:
        self.slept.append(seconds)

    def _publish(self, ch: str, body: Any = None, **kw: Any) -> int:
        if ch == self.refuse and body and body.get(ch):
            raise ValueError("echoed: key abc123")  # as the hub refuses a caller's error
        return self.hub.publish(ch, body, **kw)

    def conn(self, principal: PrincipalSnapshot) -> Conn:
        return Conn(self, principal)


async def settled() -> None:
    for _ in range(16):
        await asyncio.sleep(0)


def order_change(n: int = 1, account: UUID = A, stamp: int = T0_MS + 1, **over: Any) -> wt.Change:
    row = order(n, account=account, **over)
    item = wt.order_item(row, environment="demo", stamp=stamp, change="ack")
    closed = row.state not in ("accepted", "partially_filled", "pending_cancel")
    return wt.Change("orders", item, str(row.id), row.symbol, stamp, closed)


def fill_change(exec_id: str = "e1", account: UUID = A, stamp: int = T0_MS + 1) -> wt.Change:
    row = stored(new_fill(exec_id, account=account))
    item = wt.execution_item(row, environment="demo")
    assert item is not None
    return wt.Change("executions", item, str(row.id), row.symbol, stamp)


def position_change(stamp: int = T0_MS + 1, size: str = "0.4", **over: Any) -> wt.Change:
    row = position(size=size, **over)
    item = wt.position_item(row, environment="demo", stamp=stamp)
    return wt.Change("positions", item, str(row.id), row.symbol, stamp, size == "0")


def seeded(world: World) -> None:
    """A's open order, its fill and its position, as the lane reads them."""
    world.lane.items[("orders", A)] = (wt.order_item(order(), environment="demo", stamp=T0_MS),)
    fill = wt.execution_item(stored(new_fill()), environment="demo")
    assert fill is not None
    world.lane.items[("executions", A)] = (fill,)
    opened = wt.position_item(position(), environment="demo", stamp=T0_MS)
    world.lane.items[("positions", A)] = (opened,)


# -- the Gherkin scenarios this half carries -------------------------------------------------------


async def test_a_client_that_subscribes_gets_a_snapshot_then_deltas() -> None:
    """Gherkin "A client that subscribes gets a snapshot, then deltas": an authorised client
    subscribing to the three topics of an account with an open order, a recent fill and a position
    gets each topic's snapshot first, once its read lands (`snapshot_pending` until then), then only
    deltas, their sequence numbers each one higher."""
    world = World()
    seeded(world)
    conn = world.conn(manager(A))
    results = [conn.sub(ch, A) for ch in ("orders", "executions", "positions")]
    assert all(r["ok"] and r["snapshot_pending"] for r in results)
    assert conn.take() == []  # pending until the lane's reads land
    await settled()
    snaps = conn.take()
    assert [(t, ch) for t, ch, _ in snaps] == [
        ("snap", "orders"), ("snap", "executions"), ("snap", "positions")
    ]  # fmt: skip
    assert [len(p[ch]) for _, ch, p in snaps] == [1, 1, 1]
    for n in (2, 3):
        world.topics.published(A, [fill_change(f"e{n}"), order_change(state="partially_filled")])
        world.topics.published(A, [position_change(size=f"0.{n}")])
    deltas = [f for f in conn.frames if f["t"] == "d"]
    by_ch = {ch: [f["s"] for f in deltas if f["ch"] == ch] for ch in ("orders", "executions")}
    assert by_ch == {"orders": [2, 3], "executions": [2, 3]}  # each `snap` took s = 1
    assert [f["s"] for f in deltas if f["ch"] == "positions"] == [2, 3]


async def test_account_scoping_is_server_side() -> None:
    """Gherkin "Account scoping is server-side": a Manager assigned to A alone subscribing to B's
    `orders` is refused by the server (C-12.4), and nothing of B reaches its subscription of A."""
    world = World()
    conn = world.conn(manager(A))
    refused = conn.sub("orders", B)
    assert (refused["ok"], refused["error"]["code"]) == (False, "account_scope_denied")
    narrowed = conn.sub("orders", A, B)  # B is narrowed away silently (Sec.6.2)
    assert narrowed["effective"]["exchange_account_ids"] == [str(A)]
    await settled()
    conn.take()
    world.topics.published(B, [order_change(2, account=B)])  # the IDOR case: B's order
    assert conn.take() == []
    world.topics.published(A, [order_change(1)])
    assert [ch for _, ch, _ in conn.take()] == ["orders"]


@pytest.mark.parametrize("family", ["orders", "executions", "positions"])
async def test_a_manager_without_the_familys_permission_is_refused(family: str) -> None:
    others = READS - {wt_permission(family)}
    conn = World().conn(manager(A, permissions=others))
    result = conn.sub(family, A)
    assert (result["ok"], result["error"]["code"]) == (False, "forbidden")


def wt_permission(family: str) -> Permission:
    return {
        "orders": Permission.ORDERS_READ, "executions": Permission.EXECUTIONS_READ,
        "positions": Permission.POSITIONS_READ,
    }[family]  # fmt: skip


async def test_a_snapshot_reads_only_the_subscriptions_accounts() -> None:
    world = World()
    world.lane.items[("orders", B)] = (
        wt.order_item(order(2, account=B), environment="d", stamp=1),
    )
    conn = world.conn(manager(A))
    conn.sub("orders", A, B)
    await settled()
    [(kind, _, body)] = conn.take()
    assert (kind, body) == ("snap", {"orders": []}) and world.lane.reads == [("orders", A)]


# -- the options ----------------------------------------------------------------------------------


async def test_a_subscriptions_symbols_narrow_its_snapshot_and_its_deltas() -> None:
    world = World()
    seeded(world)
    conn = world.conn(owner())
    conn.sub("orders", A, symbols=["ETHUSDT"])
    await settled()
    assert conn.take() == [("snap", "orders", {"orders": []})]
    world.topics.published(A, [order_change()])  # a BTCUSDT order
    assert conn.take() == []


async def test_a_closed_order_is_removed_and_open_only_gets_the_removal_alone() -> None:
    world = World()
    every, open_only = world.conn(owner()), world.conn(owner())
    every.sub("orders", A)
    open_only.sub("orders", A, open_only=True)
    await settled()
    every.take(), open_only.take()
    change = order_change(state="cancelled")
    world.topics.published(A, [change])
    [(_, _, full)] = every.take()
    assert (full["orders"][0]["state"], full["removed"]) == ("cancelled", [change.key])
    assert open_only.take() == [("d", "orders", {"orders": [], "removed": [change.key]})]


async def test_a_flat_position_is_a_removal() -> None:
    world = World()
    conn = world.conn(owner())
    conn.sub("positions", A)
    await settled()
    conn.take()
    change = position_change(size="0")
    world.topics.published(A, [change])
    assert conn.take() == [("d", "positions", {"positions": [], "removed": [change.key]})]


async def test_the_executions_snapshot_is_the_newest_hundred_oldest_first() -> None:
    world = World()
    for account, base in ((A, 0), (B, 60)):
        items = []
        for n in range(80):
            row = stored(new_fill(f"{account}-{n}", account=account))
            item = wt.execution_item(row, environment="demo")
            assert item is not None
            items.append(item | {"id": str(UUID(int=base * 1000 + n)), "ts_ms": T0_MS + base + n})
        world.lane.items[("executions", account)] = tuple(reversed(items))  # newest first
    conn = world.conn(owner())
    conn.sub("executions", A, B)
    await settled()
    [(_, _, body)] = conn.take()
    stamps = [item["ts_ms"] for item in body["executions"]]
    assert len(stamps) == wt.SNAPSHOT_FILLS and stamps == sorted(stamps)
    # every fill at or after A's 61st: A's last 20 and B's 80, the newest last
    assert (stamps[0], stamps[-1]) == (T0_MS + 60, T0_MS + 139)


# -- the loads -----------------------------------------------------------------------------------


async def test_build_answers_nothing_until_the_topics_are_attached() -> None:
    world = World(attach=False)
    seeded(world)
    conn = world.conn(owner())
    conn.sub("orders", A)
    await settled()
    assert conn.take() == [] and world.lane.reads == []
    world.topics.attach(world.lane)  # the OMS is ready: the pending subscription is read
    await settled()
    assert [t for t, _, _ in conn.take()] == ["snap"]


async def test_a_load_a_delta_raced_reads_again_before_it_is_served() -> None:
    """A delta stamped at or after the read's start reached the serving loop while the read was
    on the lane: the pending subscription dropped it, so the load reads again."""
    world = World()
    conn = world.conn(owner())
    raced = [order_change(stamp=T0_MS)]  # stamped at the read's start: maybe missed

    def during() -> None:
        if raced:
            world.topics.published(A, [raced.pop()])

    world.lane.during = during
    conn.sub("orders", A)
    await settled()
    assert world.lane.reads == [("orders", A), ("orders", A)]
    assert [t for t, _, _ in conn.take()] == ["snap"]


async def test_a_load_an_older_delta_raced_is_served_as_read() -> None:
    """A delta stamped before the read's start is in what it read: no second read."""
    world = World()
    conn = world.conn(owner())
    world.lane.during = lambda: world.topics.published(A, [order_change(stamp=T0_MS - 1)])
    conn.sub("orders", A)
    await settled()
    assert world.lane.reads == [("orders", A)]
    assert [t for t, _, _ in conn.take()] == ["snap"]


async def test_a_load_raced_every_round_is_served_then_resnapshotted() -> None:
    world = World()
    conn = world.conn(owner())
    rounds = [0]

    def during() -> None:
        rounds[0] += 1
        if rounds[0] <= wt.LOAD_ROUNDS:  # every round of the first load
            world.topics.published(A, [order_change(stamp=world.lane.stamp)])

    world.lane.during = during
    conn.sub("orders", A)
    await settled()
    reasons = [f.get("meta", {}).get("reason") for f in conn.frames if f["t"] == "snap"]
    assert reasons == ["initial", "upstream_desync"]
    assert len(world.lane.reads) == wt.LOAD_ROUNDS + 1


async def test_a_load_that_fails_is_tried_again_then_left_pending() -> None:
    world = World()
    world.lane.error = ConnectionError("echoed: key abc123")
    conn = world.conn(owner())
    with capture_logs() as logs:
        conn.sub("orders", A)
        await settled()
    assert conn.take() == [] and len(world.lane.reads) == wt.LOAD_TRIES
    assert world.slept == [wt.LOAD_BACKOFF_S, 2 * wt.LOAD_BACKOFF_S]  # jitter at its top
    assert [e["event"] for e in logs][-1] == "oms_ws_topic_load_failed"
    assert "abc123" not in str(logs)
    world.lane.error = None
    world.topics.resync(A, ("orders",))  # the next change or resync reads again
    await settled()
    assert [t for t, _, _ in conn.take()] == ["snap"]


async def test_a_view_serves_the_next_attach_until_a_newer_delta_outdates_it() -> None:
    world = World()
    seeded(world)
    first, second, third = (world.conn(owner()) for _ in range(3))
    first.sub("orders", A)
    await settled()
    world.topics.published(A, [order_change(stamp=T0_MS - 1)])  # older than the view: kept
    second.sub("orders", A)
    assert world.lane.reads == [("orders", A)]
    world.topics.published(A, [order_change(stamp=T0_MS)])  # at the view's read: dropped
    third.sub("orders", A)
    await settled()
    assert world.lane.reads == [("orders", A), ("orders", A)]


async def test_detach_cancels_the_loads_and_answers_nothing_after() -> None:
    world = World()
    world.lane.gate = asyncio.Event()
    conn = world.conn(owner())
    conn.sub("orders", A)
    await settled()
    await world.topics.detach()
    world.lane.gate.set()
    await settled()
    sub = conn.authz.find("orders")
    assert conn.take() == [] and sub is not None and world.topics.build(sub) is None


# -- the deltas ----------------------------------------------------------------------------------


async def test_one_accounts_changes_go_out_in_causal_order() -> None:
    """Sec.16.1 S5 on the serving side: whatever order the lane lists them in, the changes of one
    account event go out executions, then orders, then positions."""
    world = World()
    conn = world.conn(owner())
    for ch in ("positions", "orders", "executions"):
        conn.sub(ch, A)
    await settled()
    conn.take()
    world.topics.published(A, [position_change(), order_change(), fill_change()])
    assert [ch for _, ch, _ in conn.take()] == ["executions", "orders", "positions"]


async def test_a_resync_resnapshots_the_accounts_subscriptions_of_those_families() -> None:
    world = World()
    seeded(world)
    a, b = world.conn(owner()), world.conn(owner())
    a.sub("executions", A)
    a.sub("orders", A)
    b.sub("executions", B)
    await settled()
    a.take(), b.take()
    world.topics.resync(A, ("executions",))
    await settled()
    assert [(f["ch"], f["meta"]["reason"]) for f in a.frames] == [("executions", "upstream_desync")]
    assert b.frames == []


async def test_a_publish_that_raises_resyncs_its_family_of_the_account() -> None:
    """The hub raises only a caller's error (a paced frame without its body, a refused `meta`);
    whatever it raises is contained, logged by its class, and the family's subscriptions of the
    account re-snapshot, so a client never silently misses the change."""
    world = World(refuse="orders")
    conn = world.conn(owner())
    conn.sub("orders", A)
    await settled()
    conn.take()
    with capture_logs() as logs:
        world.topics.published(A, [order_change()])
        await settled()
    [line] = [e for e in logs if e["event"] == "oms_ws_publish_failed"]
    assert line["family"] == "orders" and "abc123" not in str(line)
    assert [f["meta"]["reason"] for f in conn.frames if f["t"] == "snap"] == ["upstream_desync"]


def test_a_private_snapshot_is_never_cached_and_claims_no_continuity() -> None:
    topics = World().topics
    sub = SimpleSub("orders")
    assert topics.generation(sub) == 0 and topics.continuity(sub, 1) is False
    assert topics.build(SimpleSub("wallet")) is None  # not one of the OMS's families


async def test_a_resync_while_a_load_reads_makes_it_read_again() -> None:
    """A resync of a key whose load is on the lane: what that read sees may predate the change, so
    it reads again before it is served."""
    world = World()
    conn = world.conn(owner())
    resynced = [False]

    def during() -> None:
        if not resynced[0]:
            resynced[0] = True
            world.topics.resync(A, ("orders",))

    world.lane.during = during
    conn.sub("orders", A)
    await settled()
    assert world.lane.reads == [("orders", A), ("orders", A)]
    assert [t for t, _, _ in conn.take()] == ["snap"]


async def test_the_views_are_bounded_least_recently_used_first() -> None:
    world = World(views_max=1)
    seeded(world)
    first, second = world.conn(owner()), world.conn(owner())
    first.sub("orders", A)
    await settled()
    first.sub("positions", A)  # its view evicts the `orders` view
    await settled()
    second.sub("orders", A)
    await settled()
    assert world.lane.reads == [("orders", A), ("positions", A), ("orders", A)]


async def test_a_hub_that_raises_on_a_resync_or_a_flush_is_contained() -> None:
    world = World()

    def refused(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("the hub refused")

    topics = wt.OmsTopics(refused, refused, refused, SnapshotBody)
    with capture_logs() as logs:
        topics.attach(world.lane)  # its flush raises
        topics.resync(A, ("orders",))
    assert [e["event"] for e in logs] == ["oms_ws_flush_failed", "oms_ws_resync_failed"]


class SimpleSub:
    def __init__(self, ch: str) -> None:
        self.ch, self.accounts, self.effective = ch, frozenset({A}), {}


@pytest.mark.parametrize("family", ["orders", "executions", "positions"])
async def test_a_manager_asking_for_an_ungranted_account_is_refused_and_sees_none_of_it(
    family: str,
) -> None:
    """C-12.4 for each topic: B alone is `account_scope_denied`; with A and B asked, B is narrowed
    away, B's snapshot rows are never read, and a delta of B never reaches the subscription."""
    world = World()
    world.lane.items[(family, B)] = ({"exchange_account_id": str(B)},)  # never to be read
    conn = world.conn(manager(A))
    refused = conn.sub(family, B)
    assert (refused["ok"], refused["error"]["code"]) == (False, "account_scope_denied")
    conn.sub(family, A, B)
    await settled()
    assert world.lane.reads == [(family, A)]
    conn.take()
    other = {
        "orders": order_change(2, account=B),
        "executions": fill_change("eB", account=B),
        "positions": position_change(account=B, id=UUID(int=0xDB)),
    }[family]
    world.topics.published(B, [other])
    assert conn.take() == []


async def test_a_load_that_gave_up_reads_again_at_its_accounts_next_change() -> None:
    """As `alerts` does: after its last try, a subscription stays pending until a change of its
    account (or a resync); that change snapshots it, read afresh."""
    world = World()
    world.lane.error = ConnectionError("the pool is down")
    conn = world.conn(owner())
    conn.sub("orders", A)
    await settled()
    assert conn.take() == [] and len(world.lane.reads) == wt.LOAD_TRIES
    world.lane.error = None
    world.topics.published(B, [order_change(2, account=B)])  # another account: nothing read
    await settled()
    assert len(world.lane.reads) == wt.LOAD_TRIES
    world.topics.published(A, [order_change()])
    await settled()
    assert [t for t, _, _ in conn.take()] == ["snap"]
    assert len(world.lane.reads) == wt.LOAD_TRIES + 1
