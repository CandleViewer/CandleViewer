"""Model-based test of the OMS facade (E29-T03 #847, the ticket's test plan): Hypothesis drives an
order through random commands and exchange pushes, legal or not, on the real binding with the
in-memory stores, and crashes and hydrates it at random points. After every step: `0 <= filled_qty
<= qty` (INV-1), a final order never changes (INV-2, S6), its events' `seq`s are dense and
increasing, and the fold of its events equals its row (OM-T03); after a crash, the hydrated machine
equals the one that crashed (A7). Bounded examples, so the unit lane stays quick."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Coroutine, Mapping
from decimal import Decimal
from typing import Any, TypeVar

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from candleviewer.oms.errors import (
    IllegalTransition,
    OrderBufferFull,
    OrderNotLoaded,
    OrderStepRefused,
    ReconcileAnomaly,
)
from candleviewer.oms.recovery import FINALS, RebuiltOrder, rebuild
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from tests.unit.oms.order_rig import ACCOUNT, Rig, build_rig, fill_of, order_of

REGISTRY = Registry()
T = TypeVar("T")
#: What the facade answers a command or push the order cannot take: each is the model's to expect.
REFUSED = (IllegalTransition, ReconcileAnomaly, OrderNotLoaded, OrderStepRefused, OrderBufferFull)
#: The context the `protection` region and the outbox own: not in the order's events.
PROTECTION_KEYS = ("sl_deadline_us", "sl_reading", "outbox")


def _reply(ok: bool) -> Any:
    async def answer(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": True, "exchange_order_id": "x1"} if ok else {"ok": False, "error_code": "X"}

    return answer


async def _lost(_command: b01.Command) -> Mapping[str, Any]:
    raise TimeoutError  # an ambiguous outcome: the order waits in `unknown` (S1)


class OrderModel(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.attempts, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
        self.rig: Rig = build_rig(registry=REGISTRY)
        self.order = order_of()
        self.ended: tuple[Any, ...] | None = None

    def run(self, step: Coroutine[Any, Any, T]) -> T:
        return self.loop.run_until_complete(step)

    async def _quietly(self, step: Coroutine[Any, Any, object]) -> None:
        try:
            await step
        except REFUSED:
            pass
        await self.rig.quiet()

    def teardown(self) -> None:
        try:
            self.run(self.rig.facade.stop())
        finally:
            self.loop.close()
            b01._ATTEMPTS = self.attempts

    @initialize(sent=st.sampled_from(("not", "acked", "lost")))
    def start(self, sent: str) -> None:
        """The order validated, and sent: acked as `x1`, or lost in transit (`unknown`)."""
        self.run(self._quietly(self.rig.start(self.order)))
        if sent != "not":
            self.rig.commands.on_place = _reply(True) if sent == "acked" else _lost
            self._command("SEND")

    def _command(self, event: Any, payload: dict[str, Any] | None = None) -> None:
        step = self.rig.facade.command(ACCOUNT, self.order.id, event, payload, actor="user")
        self.run(self._quietly(step))

    def _push(self, event: Any, payload: dict[str, Any]) -> None:
        self.run(self._quietly(self.rig.facade.push(ACCOUNT, self.order.id, event, payload)))

    @rule(
        exec_id=st.sampled_from(("e1", "e2", "e3", "e4")),
        qty=st.sampled_from(("0.1", "0.3", "0.6", "1.2")),
        foreign=st.booleans(),
    )
    def fill(self, exec_id: str, qty: str, foreign: bool) -> None:
        bound = "x-foreign" if foreign else "x1"
        self._push("EXEC", fill_of(self.order, exec_id, qty, exchange_order_id=bound))

    @rule(ok=st.booleans())
    def cancel(self, ok: bool) -> None:
        self.rig.commands.on_cancel = _reply(ok)
        self._command("CANCEL")

    @rule(ok=st.booleans(), price=st.sampled_from(("62500", "64000")))
    def amend(self, ok: bool, price: str) -> None:
        self.rig.commands.on_amend = _reply(ok)
        self._command("AMEND", {"price": price})

    @rule(
        event=st.sampled_from(("TRIGGERED", "EXPIRE", "REMOTE_CANCELLED", "AMEND_REJECTED")),
        stamp=st.integers(min_value=1, max_value=4),
    )
    def exchange_push(self, event: str, stamp: int) -> None:
        payload: dict[str, Any] = {"updated_time": stamp}
        if event == "AMEND_REJECTED":
            payload = {"error_code": "PRICE_OUT_OF_BOUNDS"}
        self._push(event, payload)

    @rule(event=st.sampled_from(("TRANSPORT_FAULT", "RECON_FOUND_LIVE", "RECON_MISS", "MISMATCH")))
    def reconcile(self, event: str) -> None:
        payload = {"TRANSPORT_FAULT": {"reason": "socket closed"}, "RECON_MISS": {"pass_id": "p"}}
        found = {"exchange_order_id": "x1"}
        step = self.rig.facade.command(
            ACCOUNT, self.order.id, event, payload.get(event, found), actor="system"
        )
        self.run(self._quietly(step))

    @rule(dice=st.integers(min_value=0, max_value=4))
    def kill(self, dice: int) -> None:
        """B18's kill switch, one draw in five, so most runs explore a live order first."""
        if dice == 0:
            self.run(self._quietly(self.rig.facade.kill("kill switch engaged")))

    @precondition(lambda self: self.rig.facade.state(self.order.id) is not None)
    @rule()
    def crash_and_hydrate(self) -> None:
        """A7: the machine hydrated after a crash is the one that crashed. One thing no event
        holds (24 Sec.8.2 "Recovery"): a stop that only a fill a held order consumed (S6) started,
        with no fill of the order's own; its position is B8's and reconciliation's after the
        restart (Sec.8.5 step 5), so the hydrated region rests in `not_required`."""
        state, context = self.rig.facade.state(self.order.id), dict(self.rig.context(self.order))
        self.rig = self.run(self.rig.restart())
        self.run(self.rig.facade.hydrate(ACCOUNT, self.order.id, environment="demo"))
        self.run(self.rig.quiet())
        assert state is not None
        hydrated = self.rig.facade.state(self.order.id), self.rig.context(self.order)
        if state[1] != "not_required" and Decimal(context["filled_qty"]) == 0:
            assert hydrated[0] == (state[0], "not_required")
            kept = {k: v for k, v in context.items() if k not in PROTECTION_KEYS}
            assert {k: v for k, v in hydrated[1].items() if k not in PROTECTION_KEYS} == kept
        else:
            assert hydrated == (state, context)

    def _stored(self) -> tuple[Any, ...]:
        events = self.run(self.rig.events.list_for_order(ACCOUNT, self.order.id))
        return self.run(self.rig.orders.get(ACCOUNT, self.order.id)), events

    @invariant()
    def filled_qty_never_exceeds_qty(self) -> None:
        row, _events = self._stored()
        if row is not None:
            assert 0 <= row.cum_exec_qty <= row.qty
        if self.rig.facade.state(self.order.id) is not None:
            context = self.rig.context(self.order)
            assert 0 <= Decimal(context["filled_qty"]) <= Decimal(context["qty"])

    @invariant()
    def events_are_dense_and_fold_into_the_row(self) -> None:
        row, events = self._stored()
        assert [e.seq for e in events] == list(range(len(events)))
        if row is not None:
            assert rebuild(events) == RebuiltOrder.of_row(row)

    @invariant()
    def a_final_order_never_changes(self) -> None:
        stored = self._stored()
        row = stored[0]
        if self.ended is not None:
            assert stored == self.ended
        elif row is not None and RebuiltOrder.of_row(row).lifecycle_state in FINALS:
            self.ended = stored


TestOrderModel = OrderModel.TestCase
TestOrderModel.settings = settings(max_examples=40, stateful_step_count=15, deadline=None)
