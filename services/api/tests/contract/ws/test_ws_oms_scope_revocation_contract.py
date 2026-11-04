"""E29-Q02 (#1147), slice C3: the contract half of AC-06 on the OMS's private topics.

A Manager subscribed to `orders`, `executions`, `positions` and `wallet` for two accounts has the
grant on one of them withdrawn while subscribed (E29 threat model, seed AC-06; 23-ws-protocol.md
Sec.9.5, Sec.6.2). The real `/ws` router, with the OMS's own topic adapter and the accounts
module's `wallet` topic, each serving both accounts' rows; every frame is validated by the harness.

- A grant lost on one account of two: `permission_change` (the scope that is left), then `revoked`
  `account_scope_changed` naming the account, `resubscribe_allowed: true`, the subscription going
  on under its own `sub_id`; then a `reconfigure` snapshot of the kept account's rows alone. The
  frozen grant is the same (Sec.9.5).
- The other account's data never arrives once the change is made: asserted as the absence of its
  rows from every frame, snapshot or delta, that follows, a change of each account being published
  after it, the withdrawn account's first, and only the kept account's reaching the socket.
- The only grant lost: `resubscribe_allowed: false`, the subscription ends and no snapshot follows;
  a new `sub` for the account is `account_scope_denied`.
- The records of those legs are the gateway's (`ws.subscription.revoked` for the change,
  `ws.subscribe.denied` for the refusal; 23 Sec.9.5, Sec.5.2), written to the audit sink.
  `rbac.denied` is the REST route's refusal record (24 Sec.8.4), which E29-X02's matrix reads; a
  narrowed read writes none, and is asserted by the absence of the other account's rows.

What `sub` itself narrows or refuses, for every actor on the app as composed with its OMS, is
E29-X02's (`tests/security/oms/`): this is what the server does after the grant changes.
"""

from __future__ import annotations

import json
from typing import Any, Final
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
BARRIER: Final = "ticker.BTCUSDT"  # the topic `flushed` reads its barrier through


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


class Rig:
    """The harness gateway with the OMS's three topics and `wallet`, serving accounts A and B."""

    def __init__(self) -> None:
        self.world, self.audit, self.stamp = h.World(), Audit(), 100
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
        kind = next(f for f in wt.FAMILIES if f == family)
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
    return [(f["t"], f["ch"]) for f in frames if f["t"] in {"snap", "d"} and f["ch"] != BARRIER
            and (account is None or str(account) in json.dumps(f["p"]))]  # fmt: skip


def flushed(c: h.Client) -> None:
    """Everything the server queued for the socket so far, on either lane, has been read. The
    `pong` is on the priority lane, so it only proves that the writer has turned since the clock
    moved (a window that was open closes in it); the snapshot of a topic subscribed to now is the
    normal lane's last frame (`tests/security/ws/test_stale_grant.py`'s barrier)."""
    c.send({"t": "ping", "id": "tick"})
    c.next_of("pong")
    c.send({"t": "sub", "id": "barrier", "p": {"topics": [{"ch": BARRIER}]}})
    while (frame := c.recv())["t"] != "snap" or frame["ch"] != BARRIER:
        pass
    c.send({"t": "unsub", "id": "barrier", "p": {"topics": [BARRIER]}})
    c.next_of("unsub_ok")


@pytest.mark.parametrize("how", ["withdrawn", "frozen"])
@pytest.mark.parametrize("family", FAMILIES)
def test_a_grant_lost_on_one_of_two_accounts_narrows_the_topic_and_its_rows_never_arrive(
    family: str, how: str
) -> None:
    """E29-TC-011 (variant 1), E29-TC-752: A and B, then A's grant withdrawn (or frozen): the
    announcing frames, the subscription going on, B's rows alone in the `reconfigure` snapshot, and
    from then on no snapshot or delta naming A, though A's change is published before B's, whose
    delta is the very next frame, in sequence; the `revoked` row is audited."""
    rig = Rig()
    rig.world.grants = (grant(ACC_A), grant(ACC_B))
    with h.connect(rig.world) as c:
        [result] = c.sub(topic(family, ACC_A, ACC_B))["p"]["results"]
        before = c.next_of("snap")
        assert accounts_of(before) == {ACC_A, ACC_B}
        rig.publish(family, ACC_A)
        rig.world.clock.now += WINDOWS_S
        served = c.next_of("d")
        assert accounts_of(served) == {ACC_A}  # A's rows were served until the change
        lost = (grant(ACC_A, frozen=True), grant(ACC_B)) if how == "frozen" else (grant(ACC_B),)
        rig.world.grants = lost
        mark = len(c.seen)
        rig.world.call(rig.world.registry.grants_changed, USER)
        notice, revoked, snap = c.recv(), c.recv(), c.recv()
        assert (notice["t"], notice["p"]["account_scope"]) == ("permission_change", [str(ACC_B)])
        assert (revoked["t"], revoked["ch"], revoked["p"]["reason"]) == (
            "revoked", family, "account_scope_changed"
        )  # fmt: skip
        assert revoked["p"]["removed_accounts"] == [str(ACC_A)]
        assert (revoked["p"]["resubscribe_allowed"], revoked["p"]["sub_id"]) == (
            True,
            result["sub_id"],
        )
        assert (snap["t"], snap["ch"], snap["meta"]["reason"]) == ("snap", family, "reconfigure")
        assert (accounts_of(snap), snap["s"]) == ({ACC_B}, served["s"] + 1)
        rig.publish(family, ACC_A)
        rig.publish(family, ACC_B)
        rig.world.clock.now += WINDOWS_S
        moved = c.next_of("d")
        flushed(c)
    assert (accounts_of(moved), moved["s"]) == ({ACC_B}, snap["s"] + 1)
    assert data(c.seen[mark:], ACC_A) == []
    [row] = [r for r in rig.audit.records if r["action"] == "ws.subscription.revoked"]
    assert (row["object_id"], row["reason"], row["after_state"]["removed_accounts"]) == (
        family, "account_scope_changed", [str(ACC_A)]
    )  # fmt: skip


@pytest.mark.parametrize("family", FAMILIES)
def test_a_withdrawn_only_grant_ends_the_topic_and_a_new_sub_for_it_is_refused_and_audited(
    family: str,
) -> None:
    """E29-TC-011 (variant 2), E29-TC-752: the Manager's only grant, A's, withdrawn: `revoked` with
    `resubscribe_allowed: false`, no snapshot after it and nothing of A's published later reaches
    the socket; a fresh `sub` for A is `account_scope_denied` (23 Sec.6.2). The change and the
    refusal are each one audit row naming the topic, with the reason."""
    rig = Rig()
    rig.world.grants = (grant(ACC_A),)
    with h.connect(rig.world) as c:
        [result] = c.sub(topic(family, ACC_A))["p"]["results"]
        c.next_of("snap")
        rig.world.grants = ()
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
        flushed(c)
        assert data(c.seen[mark:]) == []
        [refused] = c.sub(topic(family, ACC_A))["p"]["results"]
        assert (refused["ok"], refused["error"]["code"]) == (False, "account_scope_denied")
        flushed(c)
    legs = [
        (r["action"], r["object_id"], r["reason"]) for r in rig.audit.records if r["action"] in LEGS
    ]
    assert legs == [
        ("ws.subscription.revoked", family, "account_scope_changed"),
        ("ws.subscribe.denied", family, "account_scope_denied"),
    ]
