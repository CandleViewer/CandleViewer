"""The private-stream push core's test rig (E29-T05 #848, S4b): one scripted double for every
port of `StreamPushes`, over a fake monotonic clock that its reads advance. It is venue-neutral:
the events and rows come from the test modules, which derive them from #4135's transcribed frames
through the adapter's own parser (C-13.5, C-2.2). No network."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from candleviewer.exchange.base.models import Execution, Order, PrivateEvent
from candleviewer.oms.pairing import ToRecordedStop
from candleviewer.oms.push_mapping import ForPairing, route
from candleviewer.oms.stream_push import StreamPushes
from candleviewer.storage.repositories.orders import OrderRow

GUARD_S = 2.0  # real seconds: the only wall clock, and only ever a failing test's
XID = "9aac161b-8ed6-450d-9cab-c5cc67c21784"


@dataclass
class Rig:
    """Answers by port name (a list answers its items in turn, the last one again); `cost` seconds
    pass per read; `raises` and `hang` script failures. The recorded-stop seam answers `take`."""

    answers: dict[str, Any] = field(default_factory=dict)
    raises: dict[str, BaseException] = field(default_factory=dict)
    hang: set[str] = field(default_factory=set)
    push_errors: list[BaseException] = field(default_factory=list)  # consumed, one per delivery
    cost: float = 0.0
    now: float = 100.0
    calls: list[str] = field(default_factory=list)
    pushed: list[tuple[UUID, str, dict[str, Any]]] = field(default_factory=list)
    counts: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    taken: list[ToRecordedStop] = field(default_factory=list)
    successors: list[tuple[UUID, str]] = field(default_factory=list)  # (row id, order status)
    opened: list[tuple[str, str]] = field(default_factory=list)
    stalled: asyncio.Event = field(default_factory=asyncio.Event)  # set once a port hangs
    _shared: StreamPushes | None = None

    def streams(self, **kw: Any) -> StreamPushes:
        ports: dict[str, Any] = dict.fromkeys(("target", "reads", "fill_orders", "lockout"), self)
        ports |= dict.fromkeys(("handovers", "stops", "no_intent", "counts", "pager"), self)
        ports["successors"] = self
        return StreamPushes(**(ports | {"monotonic": lambda: self.now} | kw))

    async def run(self, ev: PrivateEvent, **kw: Any) -> None:
        r = route(ev)
        assert isinstance(r, ForPairing)
        if kw or self._shared is None:
            self._shared = self.streams(**kw)  # one per rig: its paged-order set lives on it
        async with asyncio.timeout(GUARD_S):  # a bound the code lacks fails the test, never hangs
            await self._shared.handle(ev.account_id, ev, r)

    async def _hit(self, name: str) -> Any:
        self.calls.append(name)
        self.now += self.cost
        await self._stall(name)
        if name in self.raises:
            raise self.raises[name]
        answer = self.answers.get(name)
        if isinstance(answer, list):
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> Any:
        return await self._hit("bound")

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> Any:
        return await self._hit("named")

    async def order_of(self, account_id: UUID, xid: str, symbol: str) -> Any:
        return await self._hit("order")

    async def live_for_key(self, account_id: UUID, symbol: str, position_idx: int) -> Any:
        return await self._hit("stops") or ()

    async def for_exchange_order(self, account_id: UUID, xid: str) -> Any:
        return await self._hit("for_exchange_order") or ()

    async def push(self, account_id: UUID, order_id: UUID, event: str, payload: Any) -> None:
        self.calls.append("push")
        self.pushed.append((order_id, event, dict(payload)))
        await self._stall("push")
        if self.push_errors:
            raise self.push_errors.pop(0)

    async def open(self, account_id: UUID, *, finding: str, key: str) -> None:
        self.calls.append("lockout")
        self.opened.append((finding, key))
        await self._hit_raise("lockout")

    async def exchange_placed(self, account_id: UUID, *, finding: str, key: str) -> None:
        self.calls.append("exchange_placed")
        await self._hit_raise("lockout")

    async def hand_over_execution(
        self, account_id: UUID, execution: Execution, *, empty_read: bool = False
    ) -> None:
        self.calls.append(f"handover:{empty_read}")
        await self._hit_raise("handover")

    async def take(self, account_id: UUID, decision: ToRecordedStop, *rest: Any) -> Any:
        self.calls.append("take")
        self.taken.append(decision)
        await self._stall("take")
        if "on_take" in self.answers:
            self.answers["on_take"]()
        if "take" in self.raises:
            raise self.raises["take"]
        return self.answers.get("take")

    async def after_bind(self, account_id: UUID, decision: ToRecordedStop) -> None:
        self.calls.append("after_bind")
        await self._hit_raise("after_bind")

    async def check(self, account_id: UUID, row: OrderRow, order: Order) -> None:
        """The successor's check (S7b): noted apart from `calls`; `raises` and `hang` script it."""
        self.successors.append((row.id, order.state))
        await self._hit_raise("successor")

    async def _stall(self, name: str) -> None:
        if name in self.hang:
            self.stalled.set()
            await asyncio.Event().wait()

    async def _hit_raise(self, name: str) -> None:
        await self._stall(name)
        if name in self.raises:
            raise self.raises[name]

    def count(self, outcome: str) -> None:
        self.counts.append(outcome)

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.pages.append(summary)
