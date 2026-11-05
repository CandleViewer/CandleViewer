"""E29-Q02 (#1147), slice C3: the contract half of AC-06 on the OMS's private topics.

A Manager subscribed to `orders`, `executions`, `positions` and `wallet` for two accounts has the
grant on one of them withdrawn, or frozen (the same, 23 Sec.9.5), while subscribed (E29 threat
model, seed AC-06; 23-ws-protocol.md Sec.9.5, Sec.6.2). The real `/ws` router, with the OMS's own
topic adapter and the accounts module's `wallet` topic, each serving both accounts' rows; every
frame is validated by the harness. A test asserts one behaviour:

- A grant lost on one account of two: `permission_change` (the scope that is left), then `revoked`
  `account_scope_changed` naming the account, `resubscribe_allowed: true`, the subscription going
  on under its own `sub_id`; then a `reconfigure` snapshot of the kept account's rows alone.
- The other account's data never arrives once the change is made: asserted as the absence of its
  rows from every frame, snapshot or delta, that follows, a change of each account being published
  after it, the withdrawn account's first, and only the kept account's reaching the socket.
- The only grant lost: `resubscribe_allowed: false`, the subscription ends and no snapshot follows.
- In both, a new `sub` for the lost account is `account_scope_denied`.
- The records of those legs are the gateway's (`ws.subscription.revoked` for the change,
  `ws.subscribe.denied` for the refusal; 23 Sec.9.5, Sec.5.2), written to the audit sink.
  `rbac.denied` is the REST route's refusal record (24 Sec.8.4), which E29-X02's matrix reads; a
  narrowed read writes none, and is asserted by the absence of the other account's rows.

What `sub` itself narrows or refuses, for every actor on the app as composed with its OMS, is
E29-X02's (`tests/security/oms/`): this is what the server does after the grant changes.
"""

from __future__ import annotations

import json
from typing import Any, Final, NamedTuple, cast
from uuid import UUID

import pytest

from candleviewer.accounts.wallet_topic import WalletTopic
from candleviewer.auth.scopes import AccountGrant
from candleviewer.oms import ws_topics as wt
from candleviewer.ws.sequencing import SnapshotBody, SnapshotSource
from candleviewer.ws_wiring import SnapshotRouter, oms_topics
from tests.contract.ws import _harness as h
from tests.unit.accounts._fakes import T0
from tests.unit.accounts._runtime_rig import snapshot
from tests.unit.accounts._status_world import StatusWorld
from tests.unit.oms.test_ws_topics import new_fill, order, position, stored
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER

FAMILIES: Final = (*wt.FAMILIES, "wallet")
#: Past every window of these topics (`positions` 100 ms, `wallet` 500 ms): what one held leaves.
WINDOWS_S: Final = 1.0
#: The audit rows of the legs under test (the gateway writes others: the grant, the close).
LEGS: Final = frozenset({"ws.subscription.revoked", "ws.subscribe.denied"})


class Lane:
    """The lane's snapshot reads: each account's open order, fill and position, ids told apart."""

    async def read(self, family: wt.Family, account: UUID) -> wt.View:
        n = 1 if account == ACC_A else 2
        fill = wt.execution_item(stored(new_fill(f"e{n}", account, n)), environment="demo")
        assert fill is not None
        items = {
            "orders": wt.order_item(order(n, account=account), environment="demo", stamp=1),
            "executions": fill,
            "positions": wt.position_item(
                position(account, id=UUID(int=0xD0 + n)), environment="demo", stamp=1
            ),
        }
        return wt.View(1, (items[family],))


class Audit:
    """The gateway's audit sink: each `emit` is one record."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **row: Any) -> None:
        self.records.append({"action": action, **row})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["action"] == action]


class Rig:
    """The harness gateway with the OMS's three topics and `wallet`, serving accounts A and B."""

    def __init__(self, *grants: AccountGrant) -> None:
        self.world, self.audit, self.stamp = h.World(), Audit(), 100
        self.world.grants = grants  # resolved at the socket's `auth`, so set before it connects
        self.topics = oms_topics(self.world.hub)
        self.topics.attach(Lane())
        status = StatusWorld()
        for account in (ACC_A, ACC_B):
            status.monitor.track(account)
            status.wallets.track(account)
            status.monitor.ws_heartbeat(account)
            status.wallets.apply(account, snapshot(T0))
        self.wallet = WalletTopic(
            self.world.hub.publish, SnapshotBody, clock=status.clock.monotonic
        )
        self.wallet.attach(status.monitor, status.wallets)
        sources: dict[str, SnapshotSource] = dict.fromkeys(wt.FAMILIES, self.topics)
        sources["wallet"] = self.wallet
        sources["ticker"] = self.world.source  # the barrier's topic, served as the harness does
        self.world.registry.services.snapshots = SnapshotRouter(sources)
        self.world.registry.services.audit = self.audit

    def publish(self, family: str, account: UUID) -> None:
        """One change of `account`'s on `family`, on the serving loop, as its producer sends it."""
        self.stamp += 1
        if family == "wallet":
            self.world.call(self.wallet.balance_refreshed, account)
            return
        n, stamp = (1 if account == ACC_A else 2), self.stamp
        fill = wt.execution_item(stored(new_fill(f"e{n}", account, n)), environment="demo")
        assert fill is not None
        items = {
            "orders": wt.order_item(
                order(n, account=account, state="partially_filled"),
                environment="demo", stamp=stamp, change="fill",
            ),
            "executions": fill,
            "positions": wt.position_item(
                position(account, id=UUID(int=0xD0 + n)), environment="demo", stamp=stamp
            ),
        }  # fmt: skip
        kind = cast(wt.Family, family)
        item = items[kind]
        change = wt.Change(kind, item, item["id"], "BTCUSDT", stamp)
        self.world.call(self.topics.published, account, [change])


def grant(account: UUID, *, frozen: bool = False) -> AccountGrant:
    """A trading grant (Manager(T)), frozen or not."""
    return AccountGrant(account, True, True, frozen)


def topic(family: str, *accounts: UUID) -> dict[str, Any]:
    return {"ch": family, "opts": {"exchange_account_ids": [str(a) for a in accounts]}}


def accounts_of(frame: dict[str, Any]) -> set[UUID]:
    """The accounts a data frame names: each row of its payload carries its own."""
    rows = [r for key in ("orders", "executions", "positions", "balances", "health")
            for r in frame["p"].get(key, [])]  # fmt: skip
    return {UUID(row["exchange_account_id"]) for row in rows}


def data(frames: list[dict[str, Any]], account: UUID | None = None) -> list[tuple[str, str]]:
    """The (type, topic) of each snapshot or delta among `frames`, the barrier's own aside, that
    names `account` (any, for None)."""
    return [(f["t"], f["ch"]) for f in frames if f["t"] in {"snap", "d"} and f["ch"] != h.BARRIER
            and (account is None or str(account) in json.dumps(f["p"]))]  # fmt: skip


def settled(c: h.Client) -> None:
    """The writer has turned since the clock moved, and everything it queued for `c` has been read
    (`_harness.flushed`). The turn is a `ping`'s: its `pong` is on the priority lane, so it proves
    nothing of the normal lane, but the window a moved clock leaves open closes in it."""
    c.send({"t": "ping", "id": "tick"})
    c.next_of("pong")
    h.flushed(c)


@pytest.fixture
def rig() -> Rig:
    """A Manager of A and B on the harness gateway, which serves both accounts' rows."""
    return Rig(grant(ACC_A), grant(ACC_B))


#: Each family a Manager is subscribed to, by the way its grant on an account is lost (Sec.9.5).
LOSSES: Final = [(family, how) for family in FAMILIES for how in ("withdrawn", "frozen")]
pytestmark = pytest.mark.parametrize(("family", "how"), LOSSES, ids=str)


class Narrowed(NamedTuple):
    """What the socket got as A's grant was lost on one of two accounts: the subscription's id, A's
    last delta before, the three frames that announce the change (`permission_change`, `revoked`,
    the `reconfigure` snapshot), B's delta after them and every frame from the change on."""

    sub_id: str
    served: dict[str, Any]
    announced: list[dict[str, Any]]
    moved: dict[str, Any]
    after: list[dict[str, Any]]


def narrow(rig: Rig, c: h.Client, family: str, how: str) -> Narrowed:
    """The setup the narrowing tests share, on the socket each opens itself (`conftest.py` runs only
    a test that names `connect` under both wires, so a fixture cannot open it): A and B subscribed
    to `family`, A's change served, then A's grant lost (B's kept) and each account's change
    published, A's first."""
    [result] = c.sub(topic(family, ACC_A, ACC_B))["p"]["results"]
    assert accounts_of(c.next_of("snap")) == {ACC_A, ACC_B}
    rig.publish(family, ACC_A)
    rig.world.clock.now += WINDOWS_S
    served = c.next_of("d")
    assert accounts_of(served) == {ACC_A}  # A's rows were served until the change
    lost = (grant(ACC_A, frozen=True), grant(ACC_B)) if how == "frozen" else (grant(ACC_B),)
    rig.world.grants = lost
    mark = len(c.seen)
    rig.world.call(rig.world.registry.grants_changed, USER)
    announced = [c.recv(), c.recv(), c.recv()]
    rig.publish(family, ACC_A)
    rig.publish(family, ACC_B)
    rig.world.clock.now += WINDOWS_S
    moved = c.next_of("d")
    settled(c)
    return Narrowed(result["sub_id"], served, announced, moved, c.seen[mark:])


def test_a_grant_lost_on_one_of_two_accounts_is_announced_and_the_subscription_goes_on(
    rig: Rig, family: str, how: str
) -> None:
    """E29-TC-011 (variant 1): A's grant lost, B's kept: `permission_change` with the scope that is
    left, then `revoked` `account_scope_changed` naming A, `resubscribe_allowed: true`, under the
    subscription's own `sub_id` (23 Sec.9.5)."""
    with h.connect(rig.world) as c:
        gone = narrow(rig, c, family, how)
    notice, revoked, _ = gone.announced
    assert (notice["t"], notice["p"]["account_scope"]) == ("permission_change", [str(ACC_B)])
    assert (revoked["t"], revoked["ch"], revoked["p"]["reason"]) == (
        "revoked", family, "account_scope_changed"
    )  # fmt: skip
    assert revoked["p"]["removed_accounts"] == [str(ACC_A)]
    assert (revoked["p"]["resubscribe_allowed"], revoked["p"]["sub_id"]) == (True, gone.sub_id)


def test_a_grant_lost_on_one_of_two_accounts_re_snapshots_the_kept_account_alone(
    rig: Rig, family: str, how: str
) -> None:
    """E29-TC-011 (variant 1), E29-TC-752: the frame after `revoked` is a `reconfigure` snapshot of
    the topic with B's rows alone, the next number after the last frame of the old scope."""
    with h.connect(rig.world) as c:
        gone = narrow(rig, c, family, how)
    snap = gone.announced[2]
    assert (snap["t"], snap["ch"], snap["meta"]["reason"]) == ("snap", family, "reconfigure")
    assert (accounts_of(snap), snap["s"]) == ({ACC_B}, gone.served["s"] + 1)


def test_a_grant_lost_on_one_of_two_accounts_its_rows_never_arrive_after_the_change(
    rig: Rig, family: str, how: str
) -> None:
    """E29-TC-011 (variant 1), E29-TC-752: A's change published before B's, after the change: B's
    delta is the very next frame, in sequence, and no snapshot or delta from then on names A."""
    with h.connect(rig.world) as c:
        gone = narrow(rig, c, family, how)
    assert (accounts_of(gone.moved), gone.moved["s"]) == ({ACC_B}, gone.announced[2]["s"] + 1)
    assert data(gone.after, ACC_A) == []


def test_a_grant_lost_on_one_of_two_accounts_is_audited_as_one_revocation(
    rig: Rig, family: str, how: str
) -> None:
    """E29-TC-011 (variant 1): one `ws.subscription.revoked` row, naming the topic, the reason and
    the account removed (23 Sec.9.5)."""
    with h.connect(rig.world) as c:
        narrow(rig, c, family, how)
    [row] = rig.audit.of("ws.subscription.revoked")
    assert (row["object_id"], row["reason"], row["after_state"]["removed_accounts"]) == (
        family, "account_scope_changed", [str(ACC_A)]
    )  # fmt: skip


def test_a_new_sub_for_the_account_lost_beside_a_kept_one_is_refused_and_audited(
    rig: Rig, family: str, how: str
) -> None:
    """E29-TC-011 (variant 1): once A's grant is lost, a fresh `sub` for A alone is
    `account_scope_denied` (23 Sec.6.2), its refusal one `ws.subscribe.denied` row naming the
    topic."""
    with h.connect(rig.world) as c:
        narrow(rig, c, family, how)
        [refused] = c.sub(topic(family, ACC_A))["p"]["results"]
        settled(c)
    assert (refused["ok"], refused["error"]["code"]) == (False, "account_scope_denied")
    [row] = rig.audit.of("ws.subscribe.denied")
    assert (row["object_id"], row["reason"]) == (family, "account_scope_denied")


def test_a_lost_only_grant_ends_the_topic_and_a_new_sub_for_it_is_refused_and_audited(
    family: str, how: str
) -> None:
    """E29-TC-011 (variant 2), E29-TC-752: the Manager's only grant, A's, withdrawn or frozen:
    `revoked` with `resubscribe_allowed: false`, no snapshot after it and nothing of A's published
    later reaches the socket; a fresh `sub` for A is `account_scope_denied` (23 Sec.6.2). The change
    and the refusal are each one audit row naming the topic, with the reason."""
    rig = Rig(grant(ACC_A))
    with h.connect(rig.world) as c:
        [result] = c.sub(topic(family, ACC_A))["p"]["results"]
        c.next_of("snap")
        rig.world.grants = (grant(ACC_A, frozen=True),) if how == "frozen" else ()
        mark = len(c.seen)
        rig.world.call(rig.world.registry.grants_changed, USER)
        notice, revoked = c.recv(), c.recv()
        assert (notice["t"], notice["p"]["account_scope"]) == ("permission_change", [])
        assert (revoked["t"], revoked["ch"], revoked["p"]["reason"]) == (
            "revoked", family, "account_scope_changed"
        )  # fmt: skip
        assert revoked["p"]["removed_accounts"] == [str(ACC_A)]
        assert (revoked["p"]["resubscribe_allowed"], revoked["p"]["sub_id"]) == (
            False,
            result["sub_id"],
        )
        rig.publish(family, ACC_A)
        rig.world.clock.now += WINDOWS_S
        settled(c)
        assert data(c.seen[mark:]) == []
        [refused] = c.sub(topic(family, ACC_A))["p"]["results"]
        assert (refused["ok"], refused["error"]["code"]) == (False, "account_scope_denied")
        settled(c)
    legs = [
        (r["action"], r["object_id"], r["reason"]) for r in rig.audit.records if r["action"] in LEGS
    ]
    assert legs == [
        ("ws.subscription.revoked", family, "account_scope_changed"),
        ("ws.subscribe.denied", family, "account_scope_denied"),
    ]
