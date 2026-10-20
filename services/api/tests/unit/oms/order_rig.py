"""The OMS facade's test rig (E29-T03 #847): `OrderMachines` on the real B1 binding over the
in-memory stores, with a recording double for every port. Shared by the facade's unit tests and
its recovery, model and performance tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from prometheus_client import generate_latest

from candleviewer.observability.metrics import Metrics
from candleviewer.oms import ExecutionRepository, OrderEventRepository, OrderRepository
from candleviewer.oms.fakes import InMemoryExecutionStore, InMemoryOrderStore
from candleviewer.oms.order_machine import (
    OrderAuditRecord,
    OrderMachinePorts,
    OrderMachines,
    OrderNotice,
)
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import NewOrder
from tests.xstate_contract.b01_ports import Commands

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
NOW_US = 1_789_134_000_000_000
ACCOUNT, OTHER = UUID(int=0xA1), UUID(int=0xA2)
GATES = dict.fromkeys(b01.GATES, b01.PASSED)
READ_BACK = {"ok": True, "position": {"updated_time": 100, "stop_loss": "62000", "size": "1"}}


def order_of(n: int = 1, **over: Any) -> NewOrder:
    """Order *n* of the account, as E29-T04's pipeline registers it."""
    link = f"cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-{n:02d}en"  # 24 Sec.8.3's example id, numbered
    fields: dict[str, Any] = {"id": UUID(int=n), "exchange_account_id": ACCOUNT}
    fields |= {"order_link_id": link, "symbol": "BTCUSDT", "side": "Buy", "intent": "entry"}
    fields |= {"order_type": "Limit", "qty": Decimal(1), "price": Decimal(63000)}
    return NewOrder(**fields | {"stop_loss": Decimal(62000)} | over)


def fill_of(order: NewOrder, exec_id: str, qty: str, **over: Any) -> dict[str, Any]:
    """An `EXEC` of *order* (24 Sec.8.1), on the exchange order its place ack bound (`placed`)."""
    pairing = {"order_id": str(order.id), "order_link_id": order.order_link_id}
    pairing |= {"account_id": str(ACCOUNT), "symbol": order.symbol, "side": "buy"}
    fill: dict[str, Any] = {"exec_id": exec_id, "exchange_order_id": f"x{order.id.int}"}
    fill["qty"] = qty
    fill["exec_type"] = "trade"
    fill |= {"price": "63000", "fee": "0", "fee_rate": "0.0002", "ts_exec": NOW_US}
    return pairing | fill | over


def gated(reply: Mapping[str, Any]) -> tuple[asyncio.Event, Callable[..., Awaitable[object]]]:
    """A port reply held until the event is set: the request stays in flight."""
    gate = asyncio.Event()

    async def held(_command: b01.Command) -> Mapping[str, Any]:
        await gate.wait()
        return reply

    return gate, held


async def placed(command: b01.Command) -> Mapping[str, Any]:
    """The exchange accepts order *n* as `x<n>`, one exchange order each (`ux_orders_exch_id`)."""
    return {"ok": True, "exchange_order_id": f"x{UUID(command.order['order_id']).int}"}


async def read_back(_command: b01.Command) -> Mapping[str, Any]:
    return READ_BACK


@dataclass
class Audit:
    records: list[OrderAuditRecord] = field(default_factory=list)
    refuse: bool = False

    async def write(self, record: OrderAuditRecord) -> None:
        if self.refuse:
            raise RuntimeError("the audit WAL refused the record")
        self.records.append(record)

    def reasons(self, action: str) -> list[str]:
        return [r.reason for r in self.records if r.action == action]


@dataclass
class Publish:
    calls: list[tuple[UUID, UUID, dict[str, Any], bool]] = field(default_factory=list)
    refuse: bool = False

    def publish(
        self, order_id: UUID, account_id: UUID, payload: Mapping[str, Any], *, last: bool
    ) -> None:
        if self.refuse:
            raise RuntimeError("the registry refused the payload")
        self.calls.append((order_id, account_id, dict(payload), last))


@dataclass
class Notices:
    got: list[OrderNotice] = field(default_factory=list)
    refuse: bool = False

    async def notify(self, notice: OrderNotice) -> None:
        if self.refuse:
            raise RuntimeError("the notice route is down")
        self.got.append(notice)

    def kinds(self) -> list[str]:
        return [n.kind for n in self.got]


@dataclass
class Pager:
    calls: list[str] = field(default_factory=list)
    severities: list[str] = field(default_factory=list)
    refuse: bool = False

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        if self.refuse:
            raise RuntimeError("the pager is down")
        self.calls.append(summary)
        self.severities.append(severity)


@dataclass
class Rig:
    facade: OrderMachines
    orders: OrderRepository
    store: InMemoryOrderStore
    commands: Commands
    audit: Audit
    publish: Publish
    notices: Notices
    pager: Pager
    metrics: Metrics
    fills: InMemoryExecutionStore
    events: OrderEventRepository

    async def start(self, order: NewOrder | None = None) -> str:
        return await self.facade.start(
            order or order_of(), environment="demo", gates=GATES, rate_reservation="rr-1"
        )

    async def submitted(self, order: NewOrder | None = None) -> NewOrder:
        """The order sent and acked as `x1`: `submitted`."""
        order = order or order_of()
        await self.start(order)
        await self.facade.command(ACCOUNT, order.id, "SEND", actor="user")
        await self.quiet()
        assert self.facade.state(order.id) == ("submitted", "not_required")
        return order

    async def quiet(self) -> None:
        """Until the in-flight invokes answered and the facade's turns settled them."""
        for _ in range(4):
            for _ in range(64):
                await asyncio.sleep(0)
            await self.facade.idle()

    def context(self, order: NewOrder) -> dict[str, Any]:
        context: dict[str, Any] = self.facade._orders[order.id].interp.context
        return context

    def count(self, name: str, **labels: str) -> float:
        lines = generate_latest(self.metrics.registry).decode().splitlines()
        wanted = [f'{key}="{value}"' for key, value in labels.items()]
        return sum(
            float(line.rsplit(" ", 1)[1])
            for line in lines
            if line.startswith(name + "{") and all(w in line for w in wanted)
        )

    async def restart(self) -> Rig:
        """A crash and a restart: this facade stops, the binding's command attempts are gone, as
        a process's memory is, and a new facade, with new doubles, runs over the same stores."""
        await self.facade.stop()
        b01._ATTEMPTS.clear()
        return build_rig(self.store)


def build_rig(store: InMemoryOrderStore | None = None, registry: Registry | None = None) -> Rig:
    """A facade over *store* (a new one by default), the place and attach answered at once."""
    store = store or InMemoryOrderStore(clock=lambda: T0)
    orders, events = OrderRepository(store), OrderEventRepository(store)
    fills = InMemoryExecutionStore(store)
    writer = OrderStepWriter(orders, ExecutionRepository(fills), clock=lambda: T0)
    commands = Commands(on_place=placed, on_attach=read_back)
    audit, publish, notices, pager = Audit(), Publish(), Notices(), Pager()
    sink = InMemoryMachineEventSink()
    ports = OrderMachinePorts(writer, orders, commands, audit, publish, notices, sink, events)
    metrics = Metrics("dev")
    facade = OrderMachines(
        ports, metrics=metrics, pager=pager, now_us=lambda: NOW_US, registry=registry
    )
    return Rig(
        facade, orders, store, commands, audit, publish, notices, pager, metrics, fills, events
    )
