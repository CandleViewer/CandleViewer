"""Contract of a recorded stop's first bind (E29-T05 #848, S6a): `OrderStore.create` with `binds`
inserts a recorded stop's materialised row and binds its record in that one transaction (24
Sec.8.3 rule 7, 21 Sec.3.3.11 "Binding"), or writes neither. A mixin beside `SubmissionContract`,
on its `h`, run on the in-memory stores (`test_submission_fake.py`) and on Postgres
(`test_order_submission_contract_pg.py`), so the fake binds what Postgres binds (C-13.3). Every
case works in accounts of its own, so a shared database never mixes them."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid4

import pytest

from candleviewer.storage.repositories.orders import (
    NewOrder,
    OrderConstraintError,
    RecordedStopBind,
)
from candleviewer.storage.repositories.recorded_stops import (
    RecordedStopNotBindable,
    RecordedStopRow,
)
from tests.unit.oms.store_reads_contract import RELEASED, XID, XID2, advance, live_stop
from tests.unit.oms.submission_contract import EVENT, Harness, audited

XID3: Final = "0f1e2d3c-4b5a-4968-8776-655443322110"  # made up: the shape of an exchange order id


def materialised(account: UUID, xid: str = XID, **over: Any) -> NewOrder:
    """A recorded stop-loss's TP/SL order as its row is materialised on BTCUSDT 0: provenance
    `recorded_stop`, at the chart's `submitted`, bound to `xid`, reduce-only and close-on-trigger
    (24 Sec.8.3 rule 7), under the id an adoption takes (`ext-`)."""
    values: dict[str, Any] = {
        "id": uuid4(), "exchange_account_id": account, "order_link_id": f"ext-{uuid4().hex}",
        "symbol": "BTCUSDT", "side": "Sell", "intent": "stop_loss", "order_type": "Market",
        "qty": Decimal("0.010"), "trigger_price": Decimal(62500), "reduce_only": True,
        "close_on_trigger": True, "state": "accepted", "lifecycle_state": "submitted",
        "provenance": "recorded_stop", "exchange_order_id": xid,
    }  # fmt: skip
    return NewOrder(**(values | over))


def binding(stop: RecordedStopRow) -> RecordedStopBind:
    return RecordedStopBind(record_id=stop.id, kind=stop.kind)


async def unchanged(h: Harness, account: UUID, order: NewOrder, stop: RecordedStopRow) -> None:
    """Nothing was written: no order row, the record holds what it held, and `XID`'s holders are
    the ones they were."""
    assert await h.orders.get(account, order.id) is None
    [now] = [r for r in await h.stops.live_for_key(account, "BTCUSDT", 0) if r.id == stop.id]
    assert now.exchange_order_id == stop.exchange_order_id


class FirstBindContract:
    async def test_materialise_create_binds_the_named_record_in_the_same_transaction(
        self, h: Harness
    ) -> None:
        """The row and the record's binding commit together: the order reads bound to its id and
        the record holds that id, the one holder `ix_rs_exch_id` pairs its fills with."""
        account, _ = h.new_account()
        stop = await live_stop(h, account, "answered")
        order = materialised(account)
        row = await h.orders.create(order, EVENT, binds=binding(stop))
        assert (row.exchange_order_id, row.provenance, row.lifecycle_state) == (
            XID, "recorded_stop", "submitted",
        )  # fmt: skip
        assert await h.orders.get_by_exchange_order_id(account, XID) == row
        [bound] = await h.stops.for_exchange_order(account, XID)
        assert (bound.id, bound.released_at, bound.status) == (stop.id, None, "pending")

    async def test_materialise_create_binds_a_take_profit_record_of_its_side(
        self, h: Harness
    ) -> None:
        account, _ = h.new_account()
        tp = await live_stop(h, account, kind="take_profit", trigger_price=Decimal(65000))
        order = materialised(account, intent="take_profit", trigger_price=Decimal(65000))
        await h.orders.create(order, EVENT, binds=binding(tp))
        assert [r.id for r in await h.stops.for_exchange_order(account, XID)] == [tp.id]

    @pytest.mark.parametrize("held_by", ["the_record_itself", "another_record", "an_ended_record"])
    async def test_materialise_create_refuses_a_record_already_bound_and_writes_nothing(
        self, h: Harness, held_by: str
    ) -> None:
        """One binding per record and one holder per order (never two): a record that holds an
        id, or an order id another record of the account holds, in any status, refuses the bind,
        and the order's insert is rolled back with it."""
        account, _ = h.new_account()
        stop = await live_stop(h, account, "answered")
        if held_by == "the_record_itself":
            h.bind_stop(stop.id, XID2)
            stop = replace(stop, exchange_order_id=XID2)
        else:
            other = await live_stop(h, account, "answered")
            h.bind_stop(other.id, XID)
            if held_by == "an_ended_record":
                h.move_stop(other.id, "ended")
        holders = await h.stops.for_exchange_order(account, XID)
        order = materialised(account)
        with pytest.raises(RecordedStopNotBindable):
            await h.orders.create(order, EVENT, binds=binding(stop))
        await unchanged(h, account, order, stop)
        assert await h.stops.for_exchange_order(account, XID) == holders

    @pytest.mark.parametrize("dead", ["released", "void", "replaced", "ended"])
    async def test_materialise_create_refuses_a_released_or_ended_record_and_writes_nothing(
        self, h: Harness, dead: str
    ) -> None:
        """A released record is never bound again (`rs_release`), and a first bind takes a live
        record only (`pending` or `in_force`)."""
        account, _ = h.new_account()
        stop = await live_stop(h, account)
        if dead == "released":
            h.bind_stop(stop.id, XID2)
            await advance(h, account, stop, "answered")
            younger = await live_stop(h, account)
            await h.stops.release_and_bind(
                account, stop.id, younger.id, XID2, at=RELEASED, write_ahead=audited
            )
        else:
            await advance(h, account, stop, dead)
        order = materialised(account, XID3)
        with pytest.raises(RecordedStopNotBindable):
            await h.orders.create(order, EVENT, binds=binding(stop))
        assert await h.orders.get(account, order.id) is None
        assert await h.stops.for_exchange_order(account, XID3) == ()

    @pytest.mark.parametrize(
        "other",
        ["account", "symbol", "position_idx", "kind", "side", "missing"],
    )
    async def test_materialise_create_refuses_another_accounts_or_keys_record_and_writes_nothing(
        self, h: Harness, other: str
    ) -> None:
        """The record must be the account's (C-12.4) and of the order's key and side, as the
        caller matched it, on the position the order closes (`side`: a sell order never binds a
        short position's record, the security lens's F1); a record id the table does not hold
        binds nothing either."""
        (account, _), (theirs, _) = h.new_account(), h.new_account()
        others: dict[str, dict[str, Any]] = {
            "account": {}, "symbol": {"symbol": "ETHUSDT"}, "position_idx": {"position_idx": 1},
            "kind": {"kind": "take_profit"}, "side": {"position_side": "Sell"}, "missing": {},
        }  # fmt: skip
        over = others[other]
        stop = await live_stop(h, theirs if other == "account" else account, **over)
        binds = binding(stop)
        if other == "kind":
            binds = RecordedStopBind(record_id=stop.id, kind="stop_loss")
        if other == "missing":
            binds = RecordedStopBind(record_id=uuid4(), kind="stop_loss")
        order = materialised(account)
        with pytest.raises(RecordedStopNotBindable):
            await h.orders.create(order, EVENT, binds=binds)
        assert await h.orders.get(account, order.id) is None
        assert await h.stops.for_exchange_order(stop.exchange_account_id, XID) == ()

    async def test_materialise_create_of_an_order_already_materialised_is_refused_by_the_index(
        self, h: Harness
    ) -> None:
        """Materialising is idempotent on (account, `orderId`): a second row for one exchange order
        meets `ux_orders_exch_id` at its insert, and its record stays unbound."""
        account, _ = h.new_account()
        first, second = await live_stop(h, account, "answered"), await live_stop(h, account)
        await h.orders.create(materialised(account), EVENT, binds=binding(first))
        again = materialised(account)
        with pytest.raises(OrderConstraintError) as err:
            await h.orders.create(again, EVENT, binds=binding(second))
        assert err.value.constraint == "ux_orders_exch_id"
        assert await h.orders.get(account, again.id) is None
        assert [r.id for r in await h.stops.for_exchange_order(account, XID)] == [first.id]

    @pytest.mark.parametrize(
        "over",
        [
            {"provenance": "placed"}, {"provenance": "reconciliation"},
            {"state": "untracked", "lifecycle_state": "untracked"},
            {"exchange_order_id": None}, {"intent": "take_profit"}, {"reduce_only": False},
            {"close_on_trigger": False}, {"trade_group_leg_id": UUID(int=7)},
        ],
        ids=["placed", "reconciliation", "untracked", "unbound", "other_side",
             "not_reduce_only", "not_close_on_trigger", "in_a_group"],
    )  # fmt: skip
    async def test_materialise_create_with_binds_of_another_row_is_refused_before_any_statement(
        self, h: Harness, over: dict[str, Any]
    ) -> None:
        """Only a recorded stop's materialised row binds its record, and that row only closes its
        position (C-2.6, INV-B1-o): reduce-only and close-on-trigger, in no trade group."""
        account, _ = h.new_account()
        stop = await live_stop(h, account)
        order = materialised(account, **over)
        with pytest.raises(ValueError, match="only a recorded stop's materialised row"):
            await h.orders.create(order, EVENT, binds=binding(stop))
        assert await h.orders.get(account, order.id) is None
        assert await h.stops.for_exchange_order(account, XID) == ()

    async def test_materialise_create_without_binds_writes_the_row_and_binds_no_record(
        self, h: Harness
    ) -> None:
        """E29-T04's create is unchanged: without `binds` no record is touched."""
        account, _ = h.new_account()
        stop = await live_stop(h, account)
        row = await h.orders.create(materialised(account), EVENT)
        assert row.exchange_order_id == XID
        assert await h.stops.for_exchange_order(account, XID) == ()
        [live] = await h.stops.live_for_key(account, "BTCUSDT", 0)
        assert (live.id, live.exchange_order_id) == (stop.id, None)
