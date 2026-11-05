"""E29-T13 (#4207): the OMS runtime's composition of its WS topics (`oms_wiring`, `app.py`): on the
real backend `build_oms_runtime` hands the runtime the topics; its start hooks the step publisher
into the step writer, so a step the startup sweep commits reaches the topics with its account; it
attaches the lane's snapshot reads once `ready`, each read hopped to the lane and scoped to the
process's environment (C-2.11); its stop detaches them; without topics none of it is composed.
`create_app` serves the three families from one adapter over the gateway's hub, in
`PRIVATE_CAUSAL_ORDER`, and hands that adapter to `build_oms_runtime`. Through the composed
consumer, a position row goes to the step publisher (the store it writes through), waits for a fill
the facade holds before its order's bind (`bind`), and an overtake is counted on the runtime's
metrics. The OMS runtime's own rig (`test_oms_runtime`), the private stream's rows derived in-test
from the corpus's transcriptions and read by the adapter's parser (C-13.5): no network, no
sleeps."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer import app as appmod
from candleviewer.bus.bus import Bus
from candleviewer.domain.primitives import AccountId
from candleviewer.domain.primitives import Environment as VenueEnvironment
from candleviewer.exchange.base.models import OrderAck, PlaceOrderRequest
from candleviewer.oms import ws_topics as wt
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.ports import PositionKey
from candleviewer.oms_wiring import OmsRuntime, OmsStores, OnLaneTopicReads, build_oms_runtime
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.orders import OPEN_STATES
from candleviewer.storage.repositories.positions import PositionRow
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from candleviewer.ws.sequencing import PRIVATE_CAUSAL_ORDER
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms import command_rig as cr
from tests.unit.oms.stream_world import Book
from tests.unit.oms.test_e29_t05_acceptance import FILLS, POSITIONS, fill_row, parsed
from tests.unit.oms.test_e29_t13_acceptance import position_row
from tests.unit.oms.test_oms_runtime import (
    KEY,
    LIVE_UNSENT,
    SENDING,
    T0,
    UNSENT,
    Hub,
    Port,
    Tracked,
    Venue,
    World,
    crashed,
    started,
    until,
)


class Topics:
    """The gateway's topics as the runtime holds them (`AttachedTopics`), every call recorded."""

    def __init__(self) -> None:
        self.changes: list[tuple[UUID, wt.Change]] = []
        self.resyncs: list[tuple[UUID, tuple[str, ...]]] = []
        self.attached: list[Any] = []
        self.detached = 0

    def published(self, account: UUID, changes: Any) -> None:
        self.changes += [(account, change) for change in changes]

    def resync(self, account: UUID, families: Any) -> None:
        self.resyncs.append((account, tuple(families)))

    def attach(self, reads: wt.SnapshotReads) -> None:
        self.attached.append(reads)

    async def detach(self) -> None:
        self.detached += 1


def test_the_families_are_the_causal_orders_private_prefix() -> None:
    """Sec.16.1 S5's one source is `ws/sequencing.py`; the OMS module, which may not import `ws`,
    names the same order for its three families."""
    assert wt.FAMILIES == PRIVATE_CAUSAL_ORDER[: len(wt.FAMILIES)]


def test_the_real_backends_runtime_holds_the_topics_it_was_handed() -> None:
    ctx = SimpleNamespace(
        exchange_bybit=Venue(), ingestion=None, oms_read_only_gate=None,
        bus=SimpleNamespace(bus=Bus()),  # the app's in-process bus (E29-T08's detector)
    )  # fmt: skip
    names = ("metrics", "gate", "standings", "oms_enabled", "live_enabled", "profiles")
    unused = dict.fromkeys((*names, "persistence", "feed", "lane_signing"))
    topics = Topics()
    runtime = build_oms_runtime(
        cast(Any, ctx), Settings(storage_backend="real"), **cast(Any, unused), health=Tracked(),
        hub=Hub(), topics=topics,
    )  # fmt: skip
    assert isinstance(runtime, OmsRuntime) and runtime._topics is topics


async def test_a_step_the_sweep_commits_reaches_the_topics_and_the_reads_attach_once_ready() -> (
    None
):
    """The startup sweep abandons the entry a crash left unsent (a KILL from `validated`): that
    committed step reaches the topics as its account's `orders` change, out of the open set; once
    `ready`, the topics hold the lane's reads, which answer the account's open order through the
    lane; the stop detaches them."""
    world, topics = World(), Topics()
    await crashed(world)
    async with started(world.runtime(topics=topics)) as runtime:
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok")
        killed = [c for _, c in topics.changes if c.key == str(UNSENT.id)]
        assert killed and killed[-1].item["state"] == "killed" and killed[-1].closed
        assert {account for account, _ in topics.changes} == {cr.ACCOUNT}
        [reads] = topics.attached
        assert isinstance(reads, OnLaneTopicReads)
        await until(lambda: world.store._orders[SENDING.id].lifecycle_state == "submitted")
        view = await reads.read("orders", cr.ACCOUNT)
        assert [item["id"] for item in view.items] == [str(SENDING.id)]
    assert topics.detached == 1


async def test_the_lanes_snapshot_reads_are_scoped_to_the_process_environment() -> None:
    """C-2.11 as composed: on the demo process, the live account's entry, open in the shared store,
    reads as an account with no rows in each family, as an account no row names does; the demo
    account's open order still reads."""
    world, topics = World(), Topics()
    await crashed(world, live=True)
    world.accounts.append(TradingAccountRow(cr.LIVE_ACCOUNT, "live", cr.UIDS["live"], False, KEY))
    async with started(world.runtime(topics=topics)) as runtime:
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok")
        [reads] = topics.attached
        assert world.store._orders[LIVE_UNSENT.id].state in OPEN_STATES
        for account in (cr.LIVE_ACCOUNT, UUID(int=0xFEED)):
            views = [await reads.read(family, account) for family in wt.FAMILIES]
            assert [view.items for view in views] == [(), (), ()]
        await until(lambda: world.store._orders[SENDING.id].lifecycle_state == "submitted")
        view = await reads.read("orders", cr.ACCOUNT)
        assert [item["id"] for item in view.items] == [str(SENDING.id)]


async def test_without_topics_nothing_is_published_or_read() -> None:
    world = World()
    await crashed(world)
    async with started(world.runtime()) as runtime:
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok")
        parts = runtime._composed()
        assert parts.topic_reads is None
        with pytest.raises(OmsNotReady):
            await OnLaneTopicReads(parts).read("orders", cr.ACCOUNT)


def test_create_app_serves_the_three_families_from_one_adapter_over_the_hub() -> None:
    app = appmod.create_app(Settings(environment=Environment.TESTNET))
    services = app.state.ws_registry.services
    sources: dict[str, Any] = services.snapshots._sources
    topic = sources["orders"]
    assert isinstance(topic, wt.OmsTopics)
    assert sources["executions"] is topic and sources["positions"] is topic
    assert topic._publish == services.sequencing.publish
    assert list(topic._rank) == list(PRIVATE_CAUSAL_ORDER)


def test_create_app_hands_the_oms_runtime_the_adapter_it_serves_the_three_families_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`app.py`'s `topics=ws_oms`: the adapter `create_app` registers for `orders`, `executions`
    and `positions` is the one `build_oms_runtime` is handed, so the runtime publishes to and
    attaches the reads of the topics the gateway serves; with another, or none, every such
    subscription would stay `snapshot_pending` and no delta would reach it."""
    calls: list[dict[str, Any]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return build_oms_runtime(*args, **kwargs)

    monkeypatch.setattr(appmod, "build_oms_runtime", spy)
    app = appmod.create_app(Settings(environment=Environment.TESTNET))
    [handed] = calls
    sources: dict[str, Any] = app.state.ws_registry.services.snapshots._sources
    assert isinstance(handed.get("topics"), wt.OmsTopics)
    assert [sources[family] for family in wt.FAMILIES] == [handed["topics"]] * 3


# -- through the composed consumer: the position store and the hold's two seams ----------------

#: `SENDING`'s position: the crashed demo account's one-way BTCUSDT.
SENT_KEY = PositionKey(AccountId(cr.ACCOUNT), cr.SYMBOL, 0)
#: The stream's frames are created at the runtime's own `now` (`T0`), never the host's clock.
T0_US = wt.epoch_ms(T0) * 1_000


class HeldAckPort(Port):
    """The lane's port whose create lands at the venue, and whose acknowledgement waits until its
    venue's `ack` is set: the fill can name the venue's order before the facade binds it."""

    venue: HeldAck

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        answer = await super().place_order(req)
        assert answer.exchange_order_id is not None
        self.venue.landed.append(answer.exchange_order_id)
        await self.venue.ack.wait()
        return answer


@dataclass
class HeldAck(Venue):
    """The adapter's service whose lane port holds each create's acknowledgement (`HeldAckPort`)."""

    ack: asyncio.Event = field(default_factory=asyncio.Event)
    landed: list[str] = field(default_factory=list)

    def port(self, env: str) -> Port:
        port = HeldAckPort(environment=cast(VenueEnvironment, env))
        port.venue = self
        return port


class PositionBook(Book):
    """The position store on the OMS pool, applying each row as the table does
    (`stream_world.Book`), with the reads the runtime's other surfaces make of it."""

    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]:
        rows = self.rows.values()
        return tuple(r for r in rows if r.exchange_account_id == account_id and r.size > 0)

    async def list_unprotected(self, account_id: UUID) -> tuple[()]:
        return ()


@dataclass
class Streamed(World):
    """The runtime's world, its consumer streaming the crashed demo account, its position store
    one that applies rows (`PositionBook`)."""

    book: PositionBook = field(default_factory=PositionBook)

    def stores(self) -> OmsStores:
        def positions(clock: Callable[[], datetime]) -> PositionBook:
            self.position_clocks.append(clock)
            return self.book

        return replace(super().stores(), positions=positions)


@dataclass
class Composed:
    """A started runtime over `Streamed`, its topics recorded, and the venue's held create."""

    world: Streamed
    venue: HeldAck
    runtime: OmsRuntime
    topics: Topics

    def push(self, topic: str, row: dict[str, Any]) -> None:
        """One frame of `row` on the account's private stream, read by the adapter's parser."""
        [port] = self.venue.ports
        for event in parsed(topic, [row], cr.ref(), T0_US):
            port.push(event)

    async def held(self) -> None:
        """The venue's fill of `SENDING`, then its position: the fill waits in the facade's
        reorder buffer, the order not yet bound, and the position is applied."""
        [venue_id] = self.venue.landed
        self.push(FILLS, fill_row(SENDING, "e1", "0.010", seq=1, orderId=venue_id))
        machines = self.runtime._composed().machines
        await until(lambda: machines.held_fills(SENT_KEY) == frozenset({"e1"}))
        self.push(POSITIONS, position_row("0.010", seq=2, symbol=cr.SYMBOL))
        await until(lambda: bool(self.world.book.rows))

    def changes(self) -> list[wt.Change]:
        """The account's changes the topics got, in arrival order."""
        return [change for account, change in self.topics.changes if account == cr.ACCOUNT]

    def families(self) -> list[str]:
        return [change.family for change in self.changes()]


@asynccontextmanager
async def composed() -> AsyncIterator[Composed]:
    """The crashed world's runtime with recorded topics, ready, its consumer streaming the demo
    account: `SENDING`, resumed by the sweep, has landed at the venue, its acknowledgement held,
    so the facade has not bound it."""
    venue = HeldAck()
    world = Streamed(venue=venue)
    await crashed(world)
    world.tracked.accounts = frozenset({cr.ACCOUNT})
    topics = Topics()
    async with started(world.runtime(topics=topics)) as runtime:
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok" and bool(venue.landed))
        try:
            yield Composed(world, venue, runtime, topics)
        finally:
            venue.ack.set()  # the stop's machines end on an answered create


async def test_a_position_waits_for_a_fill_the_composed_facade_holds_before_its_bind() -> None:
    """`oms_wiring`'s `_published(PositionRepository(...), published)` and
    `published.bind(machines.held_fills)`, through the composed consumer: the venue's fill of
    `SENDING`, its create landed and its acknowledgement not yet bound, waits in the facade's
    reorder buffer; the position the venue pushes next is applied, handed to the step publisher,
    and held for that fill. Once the acknowledgement binds the order, the fill's execution and
    order frames go, then the position's, uncounted (Sec.16.1 S5)."""
    async with composed() as c:
        await c.held()
        assert "positions" not in c.families()  # applied, and held for the fill
        before = len(c.changes())
        c.venue.ack.set()
        await until(lambda: "positions" in c.families())
        acked, fill, filled, moved = c.changes()[before:]
        assert [x.family for x in (acked, fill, filled, moved)] == [
            "orders", "executions", "orders", "positions",
        ]  # fmt: skip
        assert (acked.item["change"], fill.item["exec_id"], filled.item["change"]) == (
            "ack", "e1", "fill",
        )  # fmt: skip
        assert overtakes(c.world) == 0.0


@virtual
async def test_an_overtake_through_the_composed_publisher_is_counted_on_the_runtimes_metrics() -> (
    None
):
    """`oms_wiring`'s `overtaken=_counter(metrics, OVERTAKES)`: the composed hold's real bound,
    on virtual time. With `SENDING`'s acknowledgement still held at `HOLD_S`, the position waiting
    for its fill leaves alone, and `oms_ws_position_overtakes_total` on the runtime's metrics
    counts it (20 Sec.12.1)."""
    async with composed() as c:
        await c.held()
        before = len(c.changes())
        assert "positions" not in c.families() and overtakes(c.world) == 0.0
        await asyncio.sleep(wt.HOLD_S + 0.01)
        assert [x.family for x in c.changes()[before:]] == ["positions"]
        assert overtakes(c.world) == 1.0


def overtakes(world: World) -> float:
    """`oms_ws_position_overtakes_total` as a scrape reads it."""
    sample = world.metrics.registry.get_sample_value(wt.OVERTAKES, {"env": "demo"})
    return 0.0 if sample is None else sample
