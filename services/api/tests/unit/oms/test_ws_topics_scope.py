"""E29-T13 (#4207): whose rows a subscription's snapshot carries, on the real gateway parts
(`test_ws_topics_serving.World`), every frame validated against 23-ws-protocol.md Sec.13 to
Sec.15. The lane's reads (`TopicReads`, over recording stores and the OMS's own account read,
`TradingAccountsBinding`) are scoped to the process's environment, as every other read surface is
(C-2.11): an Owner's or a Manager's `sub` naming an account of another environment, a deleted one
or one no account row names is served what an account of this environment with no rows is, and
none of its rows is read. The views the serving half shares between connections serve each
subscription its own accounts' items alone (C-12.4), at its `sub` and at a resync. No network, no
sleeps."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.oms import ws_topics as wt
from candleviewer.oms_wiring import TradingAccountsBinding
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests.unit.oms.test_ws_topics import T0, T0_MS, A, B, new_fill, order, position, stored
from tests.unit.oms.test_ws_topics_serving import World, manager, owner, settled

#: Beside A (this process's environment, `demo`): QUIET is this environment's too, with no rows;
#: ELSEWHERE is another environment's, DELETED is soft-deleted and UNKNOWN has no account row,
#: each with rows the shared store would answer.
QUIET = UUID("a1000000-0000-4000-8000-0000000000a0")
ELSEWHERE = UUID("a1000000-0000-4000-8000-0000000000a1")
DELETED = UUID("a1000000-0000-4000-8000-0000000000a2")
UNKNOWN = UUID("a1000000-0000-4000-8000-0000000000a3")
KEY = UUID(int=0xBEEF)

UNSERVED = pytest.mark.parametrize(
    "account", [ELSEWHERE, DELETED, UNKNOWN], ids=["another_environment", "deleted", "unknown"]
)
WHO = pytest.mark.parametrize("who", ["owner", "manager"])
FAMILY = pytest.mark.parametrize("family", wt.FAMILIES)


def rows_of(family: str, account: UUID, n: int) -> tuple[Any, ...]:
    """`account`'s one row of `family`, as its store holds it (`n` keeps the ids apart)."""
    if family == "orders":
        return (order(n, account=account),)
    if family == "positions":
        return (position(account, id=UUID(int=0xD0 + n)),)
    return (stored(new_fill(f"e{n}", account=account, n=n), id=UUID(int=0xE0 + n)),)


def item_of(family: str, account: UUID, n: int) -> dict[str, Any]:
    """`account`'s one Sec.15 item of `family`, as the lane reads it."""
    [row] = rows_of(family, account, n)
    if family == "orders":
        return wt.order_item(row, environment="demo", stamp=T0_MS)
    if family == "positions":
        return wt.position_item(row, environment="demo", stamp=T0_MS)
    item = wt.execution_item(row, environment="demo")
    assert item is not None
    return item


class Store:
    """One family's store as `TopicReads` reads it (`list_open`, or `list_recent` for
    `executions`): one row of each account but QUIET, every read recorded in the shared `reads`."""

    def __init__(self, family: str, reads: list[tuple[str, UUID]]) -> None:
        self.family, self.reads = family, reads
        held = (A, ELSEWHERE, DELETED, UNKNOWN)
        self.rows = {account: rows_of(family, account, n) for n, account in enumerate(held, 1)}

    def _read(self, account_id: UUID) -> tuple[Any, ...]:
        self.reads.append((self.family, account_id))
        return self.rows.get(account_id, ())

    async def list_open(self, account_id: UUID, *, symbol: str | None = None) -> tuple[Any, ...]:
        return self._read(account_id)

    async def list_recent(self, account_id: UUID, *, limit: int = 100) -> tuple[Any, ...]:
        return self._read(account_id)


def scoped() -> tuple[World, list[tuple[str, UUID]]]:
    """A demo process's topics whose lane reads are `TopicReads` over the recording stores and the
    OMS's account read, and the store reads they made."""
    world, reads = World(attach=False), list[tuple[str, UUID]]()
    rows = InMemoryTradingAccountReads(
        TradingAccountRow(A, "demo", "1", False, KEY),
        TradingAccountRow(QUIET, "demo", "2", False, KEY),
        TradingAccountRow(ELSEWHERE, "live", "3", False, KEY),
        TradingAccountRow(DELETED, "demo", "4", True, KEY),
    )
    world.topics.attach(
        wt.TopicReads(
            Store("orders", reads), Store("positions", reads), Store("executions", reads),
            accounts=TradingAccountsBinding(rows, environment="demo"), environment="demo",
            clock=wt.LaneClock(lambda: T0),
        )
    )  # fmt: skip
    return world, reads


def principal(who: str, *accounts: UUID) -> PrincipalSnapshot:
    """The Owner (every account), or a Manager granted `accounts`."""
    return owner() if who == "owner" else manager(*accounts)


# -- the environment scope of the snapshot reads (C-2.11) ---------------------------------------


@FAMILY
@WHO
@UNSERVED
async def test_a_sub_naming_an_account_the_process_does_not_serve_is_served_no_rows(
    family: wt.Family, who: str, account: UUID
) -> None:
    """The gateway admits the `sub` (the Owner's scope, or the Manager's grant), and the snapshot is
    what an account of this environment with no rows gets, `{family: []}`, frame for frame. None of
    the account's rows is read; one line names it."""
    world, reads = scoped()
    asked, quiet = world.conn(principal(who, account)), world.conn(principal(who, QUIET))
    with capture_logs() as logs:
        results = [asked.sub(family, account), quiet.sub(family, QUIET)]
        await settled()
    assert [(r["ok"], r["snapshot_pending"]) for r in results] == [(True, True)] * 2
    assert asked.take() == quiet.take() == [("snap", family, {family: []})]
    assert reads == [(family, QUIET)]
    lines = [e for e in logs if e["event"] == "oms_ws_topic_account_unserved"]
    assert [(e["account_id"], e["family"]) for e in lines] == [(str(account), family)]


@FAMILY
@WHO
async def test_a_sub_naming_this_environments_account_beside_another_gets_its_rows_alone(
    family: wt.Family, who: str
) -> None:
    """The process's own account still reads: a `sub` naming it and another environment's account
    is served its rows alone, and only its rows are read."""
    world, reads = scoped()
    conn = world.conn(principal(who, A, ELSEWHERE))
    conn.sub(family, A, ELSEWHERE)
    await settled()
    [(kind, _, body)] = conn.take()
    assert kind == "snap" and body == {family: [item_of(family, A, 1)]}
    assert reads == [(family, A)]


async def test_an_unserved_accounts_view_is_shared_so_it_is_read_and_logged_once() -> None:
    """No storm of loads: the empty view is kept as any view is, so another connection's `sub` of
    the account is served from it, nothing resolved, read or logged again."""
    world, reads = scoped()
    with capture_logs() as logs:
        for who in ("owner", "manager"):
            conn = world.conn(principal(who, ELSEWHERE))
            conn.sub("orders", ELSEWHERE)
            await settled()
            assert conn.take() == [("snap", "orders", {"orders": []})]
    lines = [e for e in logs if e["event"] == "oms_ws_topic_account_unserved"]
    assert len(lines) == 1 and reads == []


# -- the views every connection shares (C-12.4) -------------------------------------------------


def two_accounts(family: str) -> tuple[World, dict[str, Any], dict[str, Any]]:
    """A world whose lane holds one item of A and one of B for `family`, and those items."""
    world = World()
    mine, theirs = item_of(family, A, 1), item_of(family, B, 2)
    world.lane.items.update({(family, A): (mine,), (family, B): (theirs,)})
    return world, mine, theirs


@FAMILY
async def test_a_managers_snapshot_holds_its_accounts_items_alone_beside_a_shared_view(
    family: wt.Family,
) -> None:
    """An Owner's `sub` of B loads B's view, which every connection shares; a Manager of A then
    subscribing to A is served A's items alone."""
    world, mine, theirs = two_accounts(family)
    boss = world.conn(owner())
    boss.sub(family, B)
    await settled()
    assert boss.take() == [("snap", family, {family: [theirs]})]
    assert (family, B) in world.topics._views  # loaded, and kept for every connection
    clerk = world.conn(manager(A))
    clerk.sub(family, A)
    await settled()
    assert clerk.take() == [("snap", family, {family: [mine]})]
    assert world.lane.reads == [(family, B), (family, A)]


@FAMILY
async def test_a_managers_resync_beside_a_shared_view_holds_its_accounts_items_alone(
    family: wt.Family,
) -> None:
    """The same at a resync (Sec.7.4): with B's view kept from an Owner's `sub`, A's re-snapshot
    serves the Manager of A A's items alone, and leaves the Owner's subscription of B as it was."""
    world, mine, _ = two_accounts(family)
    boss, clerk = world.conn(owner()), world.conn(manager(A))
    boss.sub(family, B)
    clerk.sub(family, A)
    await settled()
    boss.take(), clerk.take()
    world.topics.resync(A, (family,))
    await settled()
    assert (family, B) in world.topics._views
    [frame] = clerk.frames
    assert (frame["t"], frame["meta"]["reason"]) == ("snap", "upstream_desync")
    assert frame["p"] == {family: [mine]}
    assert boss.frames == []
