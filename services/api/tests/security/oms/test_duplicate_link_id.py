"""E29-X02 (#982), Gherkin 2: a replayed `order_link_id` cannot create a second order (24 Sec.8.3
rules 3 and 6, SR-E29-03, OM-S05).

B1's order machine (`OrderMachines`, its real binding) over the OMS's command port
(`OmsCommandPort`, `command_rig`), whose demo venue is the adapter itself, `BybitTradingPort`,
over an `httpx.MockTransport` replaying the recorded replies (`packages/fixtures`, C-13.5): the
create meets the venue's `110072` (`trading-error-110072.json`), the command port looks the id up
(`trading-order-realtime.json`, then `trading-order-history.json`, each row's id set to ours: a
test input on a transcribed shape, #2877 R2), and B1 compares what it found with the order on
every SR-E29-03 field:

- a full match is adopted: the order is `submitted`, bound to the venue's order, the adoption
  audited ahead (`orders.submit`, `adopted_after_lookup`), and one create is on the wire;
- a mismatch is a squatted id: the order is `held` after the hand-over, never bound, nothing
  adopted, and still one create.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest

from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import ExecutionRepository, OrderEventRepository
from candleviewer.oms.fakes import InMemoryExecutionStore
from candleviewer.oms.order_machine import OrderMachinePorts, OrderMachines
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.storage.repositories.orders import NewOrder, OrderRow
from tests._corpus import rest
from tests.unit.exchange.bybit._trading import Venue, make_port, with_result
from tests.unit.oms import command_rig as cr
from tests.unit.oms import order_rig

DUPLICATE = rest("rest/trading-error-110072.json")
#: Where each lookup reads the id, and the recorded page it answers with.
LOOKUPS = {
    "realtime": "rest/trading-order-realtime.json",
    "history": "rest/trading-order-history.json",
}
_CREATE, _EMPTY = "/v5/order/create", {"list": [], "nextPageCursor": ""}


def _page(order: NewOrder, source: str, **over: str) -> dict[str, Any]:
    """The recorded page of `source`, its one row the venue's order under our id, with our
    order's terms (each `over` a term the squatter holds instead)."""
    page = rest(LOOKUPS[source])
    terms = {
        "orderLinkId": order.order_link_id, "symbol": order.symbol, "side": order.side,
        "qty": f"{order.qty}", "price": f"{order.price}", "orderType": order.order_type,
        "stopLoss": f"{order.stop_loss}", "takeProfit": f"{order.take_profit}",
        "reduceOnly": False, "positionIdx": 0, "orderStatus": "New", "triggerPrice": "0.00",
    }  # fmt: skip
    return with_result(page, list=[page["result"]["list"][0] | terms | over], nextPageCursor="")


def _venue(order: NewOrder, source: str, **over: str) -> Venue:
    venue = Venue().on(_CREATE, DUPLICATE)
    if source == "history":  # not open: the realtime read misses, history holds it
        venue.on("/v5/order/realtime", with_result(rest(LOOKUPS["realtime"]), **_EMPTY))
    return venue.on(f"/v5/order/{source}", _page(order, source, **over))


@dataclasses.dataclass
class Placed:
    rig: cr.Rig
    facade: OrderMachines
    audit: order_rig.Audit


@asynccontextmanager
async def _oms(venue: Venue, mp: pytest.MonkeyPatch) -> AsyncIterator[Placed]:
    """B1's facade over the command rig's port, its demo venue the adapter over `venue`."""
    fake = FakeTradingPort

    def port(*, environment: str, now_us: Any) -> Any:
        if environment == "demo":
            adapter = make_port(venue, now_us=now_us)
            adapter.calls = venue.sent  # type: ignore[attr-defined]  # the rig counts the wire
            return adapter
        return fake(environment=cast(Environment, environment), now_us=now_us)

    mp.setattr(cr, "FakeTradingPort", port)
    rig = cr.build_rig()
    writer = OrderStepWriter(
        rig.orders, ExecutionRepository(InMemoryExecutionStore(rig.store)), clock=lambda: cr.T0
    )
    audit, sink = order_rig.Audit(), InMemoryMachineEventSink()
    ports = OrderMachinePorts(
        writer, rig.orders, rig.port, audit, order_rig.Publish(), order_rig.Notices(), sink,
        OrderEventRepository(rig.store),
    )  # fmt: skip
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()  # one facade per process
    facade = OrderMachines(ports, metrics=Metrics("demo"), pager=order_rig.Pager(), now_us=rig.now)
    try:
        yield Placed(rig, facade, audit)
    finally:
        await facade.stop()
        b01._ATTEMPTS = saved


async def _sent(placed: Placed, order: NewOrder) -> OrderRow:
    """The pipeline's two steps (24 Sec.8.4), `VALIDATE` with every gate passed, then `SEND`;
    the row once the create's answer settled it (B1 places it as a service of `submitting`)."""
    await placed.facade.start(order, environment="demo", gates=order_rig.GATES)
    placed.rig.port.expect(order)
    await placed.facade.command(cr.ACCOUNT, order.id, "SEND", actor="user")
    for _ in range(10_000):  # a bound on the test, not a time
        row = await placed.rig.orders.get(cr.ACCOUNT, order.id)
        if row is not None and row.lifecycle_state != "submitting":
            return row
        await asyncio.sleep(0)
    raise AssertionError("the create's answer never settled the order")


@pytest.mark.parametrize("source", list(LOOKUPS))
async def test_a_replayed_link_id_is_adopted_on_its_full_match_and_never_sent_twice(
    source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    order, venue_order = cr.new_order(), rest(LOOKUPS[source])["result"]["list"][0]["orderId"]
    venue = _venue(order, source)
    async with _oms(venue, monkeypatch) as placed:
        row = await _sent(placed, order)
    assert (row.lifecycle_state, row.exchange_order_id) == ("submitted", venue_order)
    lookups = ["/v5/order/realtime", "/v5/order/history"][: 1 + (source == "history")]
    assert venue.paths() == [_CREATE, *lookups]  # one create, then the lookup: no second order
    assert venue.queries()[1]["orderLinkId"] == order.order_link_id
    assert placed.rig.audits.actions() == [("orders.submit", "adopted_after_lookup")]


@pytest.mark.parametrize(
    "squatted",
    [{"qty": "0.500"}, {"side": "Sell"}, {"price": "61000"}, {"stopLoss": "0"}],
    ids=["qty", "side", "price", "no_stop"],
)
async def test_a_squatted_link_id_is_held_never_bound_and_never_sent_twice(
    squatted: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    order = cr.new_order()
    venue = _venue(order, "realtime", **squatted)
    async with _oms(venue, monkeypatch) as placed:
        row = await _sent(placed, order)
    assert (row.lifecycle_state, row.exchange_order_id) == ("held", None)
    assert venue.paths() == [_CREATE, "/v5/order/realtime"]
    assert placed.rig.audits.actions() == []  # nothing adopted
    squatter = rest(LOOKUPS["realtime"])["result"]["list"][0]["orderId"]
    handed = placed.rig.handovers.handed  # type: ignore[attr-defined]  # the rig's recording fake
    assert handed == [(cr.ACCOUNT, squatter)]
