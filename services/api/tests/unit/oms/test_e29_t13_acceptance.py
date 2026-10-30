"""E29-T13's acceptance criteria (#4207; 23-ws-protocol.md Sec.6.2.3, Sec.16.1 S5), the scenarios
that run through the OMS, each named in the scenario's own words: E29-T05's consumer as the runtime
composes it, over the real facade and its in-memory stores (`stream_world`), with E29-T13's step
publisher on the step writer's commits and the projection's position store, and the serving half
(`OmsTopics`) on a real hub, its subscriber's every frame validated against Sec.13 to Sec.15. Each
stream row is derived in-test from the corpus's docs transcriptions and read by the adapter's own
parser (C-13.5; derived, not evidence). The snapshot and scope scenarios are the serving half's
(`test_ws_topics_serving.py`), the slow consumer the gateway's (`test_ws_oms_topics_contract.py`).
Virtual time (`VirtualTimeLoop`): no network, no sleeps."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.primitives import AccountId
from candleviewer.oms import ws_topics as wt
from candleviewer.oms.fakes import InMemoryStreamedAccounts
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.positions import PositionRow
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices
from candleviewer.ws.sequencing import (
    PRIVATE_CAUSAL_ORDER,
    SequencingHub,
    SnapshotBody,
    TopicEmitter,
)
from tests.unit.audit.audit_waits import virtual
from tests.unit.exchange.bybit._private import row
from tests.unit.oms.order_rig import build_rig
from tests.unit.oms.stream_world import WALL, A, Book, World, ref
from tests.unit.oms.test_e29_t05_acceptance import FILLS, POSITIONS, fill_row, parsed
from tests.unit.ws._seq_support import validate

FAMILIES = ("executions", "orders", "positions")
READS = frozenset({Permission.ORDERS_READ, Permission.EXECUTIONS_READ, Permission.POSITIONS_READ})


class OpenPositions:
    """The world's position rows (`stream_world.Book`) as the snapshot reads them: open ones."""

    def __init__(self, book: Book) -> None:
        self._book = book

    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]:
        rows = self._book.rows.values()
        return tuple(r for r in rows if r.exchange_account_id == account_id and r.size > 0)


@dataclass
class Wired:
    """The world, and the topics it publishes to: one Manager of A subscribed to the three."""

    world: World
    hub: SequencingHub
    topics: wt.OmsTopics[SnapshotBody]
    frames: list[dict[str, Any]] = field(default_factory=list)
    overtakes: int = 0

    def subscribe(self) -> None:
        grant = (AccountGrant(A, True, False, False),)
        principal = PrincipalSnapshot(UUID(int=0x100), frozenset({"manager"}), READS, grant)
        authz = ConnectionAuthz(principal, SubscriptionServices(snapshots=self.topics))
        emitter = TopicEmitter(
            self._push, connection_id="ws_test", wall_ms=lambda: 0, clock=lambda: 0.0,
            source=self.topics,
        )  # fmt: skip
        self.hub.register(authz, emitter)
        for ch in FAMILIES:
            result, sub = authz.admit({"ch": ch, "opts": {"exchange_account_ids": [str(A)]}})
            assert sub is not None, result
            sub.announced = True
            emitter.flush_pending([sub])

    def _push(self, frame: dict[str, Any]) -> None:
        validate(frame)
        self.frames.append(frame)

    def deltas(self) -> list[tuple[str, dict[str, Any]]]:
        """Each `d` since the snapshots: its channel and payload, in arrival order."""
        return [(f["ch"], f["p"]) for f in self.frames if f["t"] == "d"]

    def counted(self) -> None:
        self.overtakes += 1


@asynccontextmanager
async def published() -> AsyncIterator[Wired]:
    """`stream_world.opened` for account A, with the step publisher on the rig's step writer and
    the projection's position store, its frames on a hub with A's subscriber, snapped first."""
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    loop = asyncio.get_running_loop()
    clock = wt.LaneClock(lambda: WALL + timedelta(seconds=loop.time()))
    hub, publishers = SequencingHub(), list[wt.StepPublisher]()
    topics = wt.OmsTopics(
        hub.publish, hub.flush_pending, hub.resnapshot, SnapshotBody, order=PRIVATE_CAUSAL_ORDER
    )
    rig = build_rig(on_commit=lambda step: publishers[0].committed(step))
    world = World(rig, parsed, InMemoryStreamedAccounts(A))
    world.trading.seed(ref(A))
    wired = Wired(world, hub, topics)
    publisher = wt.StepPublisher(
        topics, world.notify, rig.fills, environment="demo", clock=clock,
        overtaken=wired.counted,
    )  # fmt: skip
    publishers.append(publisher)
    publisher.bind(rig.facade.held_fills)
    topics.attach(
        wt.TopicReads(rig.orders, OpenPositions(world.book), rig.fills, environment="demo",
                      clock=clock)
    )  # fmt: skip
    world.wiring = world.compose(positions=wt.PublishedPositions(world.book, publisher))
    world.wiring.start()
    try:
        wired.subscribe()
        await world.settle()
        assert [f["t"] for f in wired.frames] == ["snap"] * 3
        yield wired
    finally:
        await world.wiring.stop()
        await publisher.aclose()
        await topics.detach()
        await world.out.facade.stop()
        b01._ATTEMPTS = saved


def position_row(size: str, seq: int, **fields: Any) -> dict[str, Any]:
    """A's one-way BTCUSDT position as the stream shows it, long `size` (derived)."""
    values: dict[str, Any] = {"positionIdx": 0, "side": "Buy", "size": size, "seq": seq}
    values |= {"entryPrice": "63000", "positionValue": "63000", "stopLoss": "62000"}
    return row("position") | values | fields


def families(deltas: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [ch for ch, _ in deltas]


@virtual
async def test_a_fill_reaches_clients_in_causal_order() -> None:
    """Gherkin "A fill reaches clients in causal order": the private stream's fill of A's open
    order is published as A's `executions` delta first, then the `orders` delta of the step it
    caused (Sec.16.1 S5)."""
    async with published() as w:
        order = await w.world.submitted()
        before = len(w.deltas())
        w.world.send(FILLS, fill_row(order, "e1", "0.4", seq=1))
        await w.world.settle()
        fill = w.deltas()[before:]
        assert families(fill) == ["executions", "orders"]
        (_, executions), (_, orders) = fill
        [item] = executions["executions"]
        assert (item["exec_id"], item["order_id"], item["exec_qty"]) == ("e1", str(order.id), "0.4")
        assert orders["orders"][0]["state"] == "partially_filled"
        assert orders["orders"][0]["change"] == "fill"


@virtual
async def test_causal_order_is_preserved() -> None:
    """Gherkin "Causal order is preserved": a fill that moves its order and its position reaches
    the subscriber as the execution frame, then the order frame, then the position frame, with the
    venue's position push right behind its fill (the position waits for the fill's read)."""
    async with published() as w:
        order = await w.world.submitted()
        before = len(w.deltas())
        w.world.send(FILLS, fill_row(order, "e1", "1", seq=1))
        w.world.send(POSITIONS, position_row("1", seq=2))
        await w.world.settle()
        event = w.deltas()[before:]
        assert families(event) == ["executions", "orders", "positions"]
        assert event[1][1]["orders"][0]["state"] == "filled"
        assert event[2][1]["positions"][0]["size"] == "1" and w.overtakes == 0


@virtual
async def test_edge_case_a_position_push_before_its_order_push() -> None:
    """Gherkin "Edge case - a position push before its order push", within the hold bound: the
    fill came before its order's acknowledgement bound the row, so it waits in the order's reorder
    buffer, and the position the venue pushed next would overtake the step the fill makes. It is
    held, and published after that step's order delta once the acknowledgement lands."""
    async with published() as w:
        order, ack = await w.world.unacked()
        w.world.send(FILLS, fill_row(order, "e1", "1", seq=1))
        w.world.send(POSITIONS, position_row("1", seq=2))
        await w.world.settle()
        before = len(w.deltas())
        assert "positions" not in families(w.deltas())  # held: its fill is not applied yet
        ack.set()
        await w.world.settle()
        assert families(w.deltas()[before:]) == ["orders", "executions", "orders", "positions"]
        assert w.overtakes == 0


@virtual
async def test_edge_case_a_position_push_before_its_order_push_past_the_bound() -> None:
    """Gherkin "Edge case - a position push before its order push", past the bound: with the
    acknowledgement still out at `HOLD_S`, the held position is published before its fill's
    frames, and the overtake is counted; the fill's frames follow once the bind applies it."""
    async with published() as w:
        order, ack = await w.world.unacked()
        w.world.send(FILLS, fill_row(order, "e1", "1", seq=1))
        w.world.send(POSITIONS, position_row("1", seq=2))
        await w.world.settle()
        before = len(w.deltas())
        await asyncio.sleep(wt.HOLD_S)
        assert families(w.deltas()[before:]) == ["positions"] and w.overtakes == 1
        ack.set()
        await w.world.settle()
        assert families(w.deltas()[before + 1 :]) == ["orders", "executions", "orders"]


@virtual
async def test_a_subscriber_of_another_account_sees_none_of_it() -> None:
    """C-12.4 through the whole path: a Manager of B alone gets no frame of A's fill or position."""
    async with published() as w:
        grant = (AccountGrant(B_ACCOUNT, True, False, False),)
        other = PrincipalSnapshot(UUID(int=0x101), frozenset({"manager"}), READS, grant)
        seen: list[dict[str, Any]] = []
        authz = ConnectionAuthz(other, SubscriptionServices(snapshots=w.topics))
        emitter = TopicEmitter(
            seen.append, connection_id="ws_b", wall_ms=lambda: 0, clock=lambda: 0.0,
            source=w.topics,
        )  # fmt: skip
        w.hub.register(authz, emitter)
        for ch in FAMILIES:
            _, sub = authz.admit({"ch": ch, "opts": {"exchange_account_ids": [str(B_ACCOUNT)]}})
            assert sub is not None
            sub.announced = True
            emitter.flush_pending([sub])
        order = await w.world.submitted()
        w.world.send(FILLS, fill_row(order, "e1", "1", seq=1))
        w.world.send(POSITIONS, position_row("1", seq=2))
        await w.world.settle()
        assert [f["t"] for f in seen] == ["snap"] * 3  # B's own empty snapshots, nothing of A
        assert families(w.deltas())[-3:] == ["executions", "orders", "positions"]


B_ACCOUNT = AccountId(UUID("a1000000-0000-4000-8000-000000000002"))
