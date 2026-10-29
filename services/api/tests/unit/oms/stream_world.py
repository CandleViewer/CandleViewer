"""The private-stream consumer's acceptance world (E29-T05 #848, S9): `build_stream_consumer` as
the OMS runtime composes it (S8b), over the real facade (`order_rig.build_rig`: `OrderMachines` on
B1 over the in-memory stores, the recorded stops' among them), `FakeTradingPort` as the venue (each
account's private stream and a fill's order read), `FakeClockHealth` as the clock guard, and a
recording double for every other port: account health, the serving loop, the gateway's hub, the
audit writer, the pager and the position stores. The stand-ins are the shipped ones; the
reconciliation and hand-over ones also note what they refuse. A test module hands in the rows'
`Reader`: it derives each frame in-test from the corpus's docs transcriptions and reads it through
the adapter's own parser (the 2026-10-28 ruling Q1, C-13.5): derived, not evidence. This module
names no venue and no venue field (C-2.2). A test runs on a `VirtualTimeLoop`
(`audit_waits.virtual`), so the 30 s silence, the 15 s refresh and every bound run on fake seconds.
No network, no sleeps."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.domain.primitives import AccountId, GroupId, Symbol
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import (
    AccountRef,
    Execution,
    Order,
    PrivateEvent,
    PrivateStreamStatus,
)
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.fakes import (
    FakeClockHealth,
    InMemoryStreamedAccounts,
    InMemoryTradingAccounts,
)
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.ports import (
    INTERIM_PORTS_METRIC,
    KeyedRecord,
    NoHandoverStore,
    NoReconciliation,
    ResyncReason,
)
from candleviewer.oms.positions import PositionWrites, SnapshotWrites
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.oms_stream_wiring import StreamWiring, build_stream_consumer
from candleviewer.settings import Environment as ProcessEnvironment
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.orders import NewOrder, OrderRow
from candleviewer.storage.repositories.positions import (
    NewPositionSnapshot,
    PositionRow,
    PositionSnapshotRow,
    PositionState,
)
from tests.unit.audit.audit_waits import VirtualTimeLoop
from tests.unit.oms.order_rig import GATES, NOW_US, T0, Rig, build_rig, gated, order_of

A = AccountId(UUID("a1000000-0000-4000-8000-000000000001"))
B = AccountId(UUID("a1000000-0000-4000-8000-000000000002"))
GROUP = GroupId(UUID("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f"))  # the trade group of every order
ORDERS, FILLS = "order.linear", "execution.linear"  # the topics the adapter subscribes
RESYNCING = "oms.account_resyncing"
#: The page the reconciliation stand-in's refusal raises, once per episode (E29-T06's pass).
REFUSED = ("page", "oms.stream_consumer", "an account's reconciliation request was refused")
#: The venue's and the host's time at fake second 0: the facade's own clock (`order_rig`).
WALL = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=NOW_US)
_STORES = ("positions", "snapshots")  # the projection's two stores, through `Written`
#: From a test module: the events the adapter reads from one frame of `rows` on a topic, pushed
#: for the account at `now_us`.
type Reader = Callable[
    [str, Sequence[Mapping[str, Any]], AccountRef, int], tuple[PrivateEvent, ...]
]


def ref(account_id: AccountId) -> AccountRef:
    """The account on the demo venue, as `TradingAccounts` resolves it."""
    uid = str(account_id.int % 10**15)
    return AccountRef(account_id=account_id, uid=uid, environment="demo", key_ref=str(account_id))


def link(account_id: AccountId, seq: int) -> str:
    """The id 24 Sec.8.3's generator makes for the account's order `seq` of `GROUP`."""
    parts = OrderLinkIdParts.generate(
        mode="exchange", environment="demo", group_id=GROUP, account_id=account_id, seq=seq,
        purpose="entry",
    )  # fmt: skip
    return parts.value


class Requests(NoReconciliation):
    """The shipped stand-in until E29-T06 (each request refused, paged once per episode), noting
    each request it refuses."""

    def __init__(self) -> None:
        self.asked: list[tuple[AccountId, ResyncReason]] = []

    async def request_reconciliation(self, account_id: AccountId, *, reason: ResyncReason) -> None:
        self.asked.append((account_id, reason))
        await super().request_reconciliation(account_id, reason=reason)


class Handovers(NoHandoverStore):
    """The shipped stand-in until E29-T06 (no hand-over kept), noting each fill it refuses in the
    world's trace."""

    def __init__(self, trace: list[str]) -> None:
        self._trace = trace

    async def hand_over_execution(
        self, account_id: AccountId, execution: Execution, *, empty_read: bool = False
    ) -> None:
        self._trace.append("handover")
        await super().hand_over_execution(account_id, execution, empty_read=empty_read)


@dataclass
class Book:
    """`positions` and `position_snapshots` in memory: one row per position, replaced only by a
    later exchange time (21 Sec.3.3.7's upsert), and each snapshot appended."""

    rows: dict[tuple[UUID, str, int], PositionRow] = field(default_factory=dict)
    snaps: list[NewPositionSnapshot] = field(default_factory=list)

    async def upsert(self, state: PositionState) -> PositionRow:
        key = (state.exchange_account_id, state.symbol, state.position_idx)
        kept = self.rows.get(key)
        stamp, held = state.exchange_updated_ts, None if kept is None else kept.exchange_updated_ts
        if kept is None or (stamp is not None and (held is None or held < stamp)):
            values = {f.name: getattr(state, f.name) for f in fields(state)}
            kept = PositionRow(**values, id=UUID(int=len(self.rows) + 1), recv_ts=T0, updated_at=T0)
            self.rows[key] = kept
        return kept

    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow:
        self.snaps.append(snapshot)
        values = {f.name: getattr(snapshot, f.name) for f in fields(snapshot)}
        return PositionSnapshotRow(**values, id=len(self.snaps), snap_ts=T0)


@dataclass
class Written:
    """The position double: the stores the projection writes through (the world's `Book`, or the
    ones a test names), each write, answered or refused, setting `wrote` as it returns, which
    `World.until` waits on."""

    positions: PositionWrites
    snapshots: SnapshotWrites
    wrote: asyncio.Event = field(default_factory=asyncio.Event)

    async def upsert(self, state: PositionState) -> PositionRow:
        try:
            return await self.positions.upsert(state)
        finally:
            self.wrote.set()

    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow:
        try:
            return await self.snapshots.append(snapshot)
        finally:
            self.wrote.set()


@dataclass
class World:
    """One process's consumer and facade, and what its doubles saw, in one ordered `trace`."""

    out: Rig
    read: Reader
    streamed: InMemoryStreamedAccounts
    venue: FakeTradingPort = field(default_factory=FakeTradingPort)
    trading: InMemoryTradingAccounts = field(
        default_factory=lambda: InMemoryTradingAccounts(ref(A), ref(B))
    )
    metrics: Metrics = field(default_factory=lambda: Metrics("demo"))
    book: Book = field(default_factory=Book)
    trace: list[str] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)  # the hub's `system` notices
    evidence: list[tuple[str, AccountId]] = field(default_factory=list)  # account health's
    pages: list[tuple[str, str, str]] = field(default_factory=list)  # severity, kind, summary
    emitted: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # the audit writer's
    keyed: list[KeyedRecord] = field(default_factory=list)  # the successor's release records
    requests: Requests = field(default_factory=Requests)
    clock: FakeClockHealth | None = None
    written: Written | None = None
    wiring: StreamWiring | None = None

    def compose(self, **over: Any) -> StreamWiring:
        """The consumer as S8b's runtime builds it, every port this world's but those `over`
        names: the clock guard measured, the offset 0, the host's time the loop's. The position
        stores, the world's or those `over` names, are written through the position double."""
        loop = asyncio.get_running_loop()
        self.clock = FakeClockHealth(loop.time)
        self.clock.measure()
        ports: dict[str, Any] = dict.fromkeys(("ports", "health", "hub", "serving"), self)
        ports |= dict.fromkeys(("credentials", "audit", "emitter", "pager"), self)
        ports |= dict.fromkeys(_STORES, self.book)
        built: dict[str, Any] = {
            "facade": self.out.facade, "orders": self.out.orders,
            "stops": RecordedStopRepository(self.out.store.stops), "accounts": self.streamed,
            "trading": self.trading, "environment": ProcessEnvironment.DEMO,
            "metrics": self.metrics, "now": lambda: T0, "offset_ms": lambda: 0,
            "clock_health": self.clock, "monotonic": loop.time,
            "wall_now": lambda: WALL + timedelta(seconds=loop.time()),
            "reconciliation": self.requests, "handovers": Handovers(self.trace),
        }  # fmt: skip
        composed = ports | built | over
        self.written = Written(composed["positions"], composed["snapshots"])
        return build_stream_consumer(**(composed | dict.fromkeys(_STORES, self.written)))

    @property
    def consumer(self) -> Any:
        assert self.wiring is not None
        return self.wiring.consumer

    # the serving loop, account health, the hub, the credential report and the venue's port
    def notify(self, fn: Callable[..., object], /, *args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)  # the serving loop runs each in arrival order

    def ws_heartbeat(self, account_id: AccountId) -> None:
        self.evidence.append(("ws_heartbeat", account_id))

    def ws_dropped(self, account_id: AccountId) -> None:
        self.evidence.append(("ws_dropped", account_id))

    def wallet_pushed(self, account_id: AccountId, snapshot: object) -> bool:
        self.evidence.append(("wallet_pushed", account_id))
        return True

    def broadcast_system(self, body: dict[str, Any]) -> int:
        self.frames.append(body)
        return 1

    async def refused(
        self, account_id: AccountId, *, error_code: str, exchange_ret_code: int | None
    ) -> None:
        self.trace.append("credential_refused")

    def port_for(self, environment: str) -> World:
        return self  # the venue's port, its subscribes noted

    async def order_history(
        self, account: AccountRef, *, exchange_order_id: str | None = None
    ) -> Sequence[Order]:
        return await self.venue.order_history(account, exchange_order_id=exchange_order_id)

    async def open_orders(self, account: AccountRef, symbol: str | None = None) -> Sequence[Order]:
        return await self.venue.open_orders(account, None if symbol is None else Symbol(symbol))

    async def subscribe_private(self, account: AccountRef) -> PrivateStream:
        self.trace.append(f"subscribe:{account.account_id}")
        return await self.venue.subscribe_private(account)

    # the audit writer, the successor's release audit and the pager
    async def emit(self, action: str, **values: Any) -> None:
        self.trace.append("emit")
        self.emitted.append((action, values | {"at": asyncio.get_running_loop().time()}))

    async def write(self, record: KeyedRecord) -> None:
        self.keyed.append(record)

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.trace.append("page")
        self.pages.append((severity, machine_kind, summary))

    # the stream's rows, derived in-test and read by the adapter's parser (C-13.5)
    def now_us(self) -> int:
        """The venue's and the host's time now, on the loop's fake clock."""
        return NOW_US + round(asyncio.get_running_loop().time() * 1_000_000)

    def send(
        self, topic: str, *rows: dict[str, Any], who: AccountId = A, at_us: int | None = None
    ) -> list[PrivateEvent]:
        """One frame of `rows` on the account's stream, created now (or `at_us`): each row's event,
        as the adapter reads it, queued in order. Answers the events."""
        now = self.now_us() if at_us is None else at_us
        events = list(self.read(topic, rows, ref(who), now))
        for event in events:
            self.venue.push(event)
        return events

    def status(self, state: str, reason: str, epoch: int = 1, who: AccountId = A) -> None:
        """One status of the account's stream (24 Sec.14.2 rule 13), reported now."""
        values = {"account_id": who, "state": state, "reason": reason, "epoch": epoch}
        self.venue.push(PrivateStreamStatus.model_validate(values | {"ts": self.now_us()}))

    # the account's orders, sent through the real facade
    async def submitted(self, n: int = 1, **over: Any) -> NewOrder:
        """Account A's order `n`, sent and acknowledged over REST: `submitted`, bound to `x<n>`
        (`order_rig.placed`)."""
        order = await self.sending(n, **over)
        await self.out.facade.command(A, order.id, "SEND", actor="user")
        await self.settle()
        return order

    async def sending(self, n: int = 1, **over: Any) -> NewOrder:
        """Account A's order `n`, validated, not yet sent, under a link id of A's (24 Sec.8.3)."""
        order = order_of(n, exchange_account_id=A, order_link_id=link(A, n), **over)
        await self.out.facade.start(order, environment="demo", gates=GATES, rate_reservation="rr")
        return order

    async def unacked(self, n: int = 1, **over: Any) -> tuple[NewOrder, asyncio.Event]:
        """Account A's order `n`, sent, its acknowledgement held until the event is set:
        `submitting`, no exchange order id bound."""
        order = await self.sending(n, **over)
        gate, self.out.commands.on_place = gated({"ok": True, "exchange_order_id": xid(order)})
        await self.out.facade.command(A, order.id, "SEND", actor="user")
        await self.settle()
        return order, gate

    async def settle(self) -> None:
        """Until the consumer's and the facade's work in hand is done. On a `VirtualTimeLoop`, the
        next point where nothing is ready (`idle`, after a pass of its own, as it answers once per
        progress), so no fake second passes: a facade turn waiting on a held reply or a bound
        waits, as it would. On a real loop, loop turns and the facade's pending turns, a store's
        I/O landing between them."""
        loop = asyncio.get_running_loop()
        if isinstance(loop, VirtualTimeLoop):
            await asyncio.sleep(0)
            await loop.idle()
            return
        for _ in range(4):
            for _ in range(64):
                await asyncio.sleep(0)
            await self.out.facade.idle()

    async def until(self, done: Callable[[], bool], bound_s: float = 10.0) -> None:
        """Until `done()`, read again each time the position double (`Written`) notes a write:
        on a real loop, where a store's I/O takes real time, the loop waits on that I/O between
        writes, never spinning, and the bound turns a hang into a failure, never a wait for time
        to pass (03 Sec.14). So `done()` must hold once a write returns: the projection counts
        `future_dated` as the upsert raises, and `reapplied` as the snapshot's append returns,
        with no await between."""
        assert self.written is not None
        async with asyncio.timeout(bound_s):
            while not done():
                self.written.wrote.clear()
                await self.written.wrote.wait()

    # what the stores and the metrics hold
    async def row(self, order_id: UUID) -> OrderRow:
        row = await self.out.orders.get(A, order_id)
        assert row is not None
        return row

    async def events(self, order_id: UUID) -> list[tuple[str, str, str | None]]:
        """The order's `order_events` as (kind, source, to_state), in `seq` order."""
        rows = await self.out.events.list_for_order(A, order_id)
        return [(e.kind, e.source, e.to_state) for e in rows]

    async def fills(self, *exec_ids: str) -> list[tuple[str, Decimal]]:
        """The stored `executions` rows of these ids, as (exec_id, qty)."""
        rows = [await self.out.fills.get(A, exec_id) for exec_id in exec_ids]
        return [(r.exec_id, r.exec_qty) for r in rows if r is not None]

    def interim(self, port: str) -> float | None:
        """`oms_interim_ports{port}` as a scrape reads it."""
        labels = {"env": "demo", "port": port}
        return self.metrics.registry.get_sample_value(INTERIM_PORTS_METRIC, labels)

    def count(self, stage: str, outcome: str) -> float:
        """`oms_stream_outcomes_total{stage,outcome}` as a scrape reads it."""
        labels = {"env": "demo", "stage": stage, "outcome": outcome}
        return self.metrics.registry.get_sample_value("oms_stream_outcomes_total", labels) or 0.0


def xid(order: NewOrder) -> str:
    """The exchange order id the REST ack binds to `order` (`order_rig.placed`)."""
    return f"x{order.id.int}"


@asynccontextmanager
async def opened(read: Reader, *streamed: AccountId, **over: Any) -> AsyncIterator[World]:
    """A world whose consumer streams `streamed` (A alone by default), each resolvable, its ports
    `over` names in place of the world's (`World.compose`), started as the runtime starts it once
    ready; at the end its consumer stops first, then the facade (20 Sec.6.2), which holds B1's
    ports, one per process, B1's command attempts its own meanwhile."""
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    streamed = streamed or (A,)
    world = World(build_rig(), read, InMemoryStreamedAccounts(*streamed))
    for account_id in streamed:
        world.trading.seed(ref(account_id))
    world.wiring = world.compose(**over)
    world.wiring.start()
    try:
        await world.settle()
        yield world
    finally:
        await world.wiring.stop()
        await world.out.facade.stop()
        b01._ATTEMPTS = saved
