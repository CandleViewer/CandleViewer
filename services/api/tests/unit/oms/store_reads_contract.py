"""Contract of the stores' pairing reads (E29-T05 #848, 24 Sec.8.12): the order bound to an exchange
order id (`OrderStore.get_by_exchange_order_id`, 21 Sec.13.1 row 12), a position key's live
recorded stops (`RecordedStopStore.live_for_key`, row 45) and the recorded stops bound to an
exchange order (`for_exchange_order`, row 46). A mixin beside `SubmissionContract`, on its `h`, run
on the in-memory stores (`test_submission_fake.py`) and on Postgres
(`test_order_submission_contract_pg.py`), so the fake reads what Postgres reads (C-13.3). Every
case works in accounts of its own, so a shared database never mixes them."""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID, uuid4

import pytest

from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.orders import NewOrder
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.oms.submission_contract import (
    EVENT,
    SEND,
    T0,
    TP,
    Harness,
    Move,
    audited,
    entry,
    reduce_only,
    to,
    trading_stop,
)

XID: Final = "1b3c5d7e-9f01-4a23-b456-789abcdef012"  # made up: the shape of an exchange order id


def bound(xid: str) -> Move:
    """The create's ack, which binds the exchange's order id to the row (24 Sec.8.3 rule 7)."""
    return to("submitting", "submitted", idempotency_state="acked", exchange_order_id=xid)


async def placed(h: Harness, account: UUID, xid: str | None = XID, *then: Move) -> NewOrder:
    """A reduce-only order of the account, sent, bound to `xid` when one is given, then moved on."""
    first, order = reduce_only(h.new_user(), account)
    await h.submissions.create_first(first, order, EVENT)
    for move in (SEND, *([] if xid is None else [bound(xid)]), *then):
        await move(h, order)
    return order


async def advance(h: Harness, account: UUID, stop: RecordedStopRow, status: str) -> None:
    """Take `stop`, in flight, to `answered`, `in_force`, `replaced`, `ended` or `void`."""
    if status == "void":
        await h.stops.settle(account, [stop.id], "refused", at=T0, write_ahead=audited)
        return
    await h.stops.settle(account, [stop.id], "answered", at=T0)
    if status != "answered":
        h.move_stop(stop.id, "in_force")
        if status != "in_force":
            h.move_stop(stop.id, status)


async def live_stop(h: Harness, account: UUID, status: str = "pending") -> RecordedStopRow:
    """A system writer's stop-loss request for BTCUSDT 0, in flight (`pending`) or advanced."""
    [stop] = await h.stops.insert([trading_stop(account)])
    if status != "pending":
        await advance(h, account, stop, status)
    return stop


class StoreReadsContract:
    @pytest.mark.parametrize(
        ("moves", "state"),
        [((), "accepted"), ((to("submitted", "cancelled"),), "cancelled"),
         ((to("submitted", "held"),), "held")],
        ids=["accepted", "cancelled", "held"],
    )  # fmt: skip
    async def test_get_by_exchange_order_id_bound_row_is_returned_in_any_state(
        self, h: Harness, moves: tuple[Move, ...], state: str
    ) -> None:
        """A final row's push is Sec.8.2's S6 anomaly and a held row waits for the operator: the
        store reads both, never hides them."""
        account, _ = h.new_account()
        order = await placed(h, account, XID, *moves)
        row = await h.orders.get_by_exchange_order_id(account, XID)
        assert row is not None and (row.exchange_order_id, row.state) == (XID, state)
        assert row == await h.orders.get(account, order.id)

    @pytest.mark.parametrize(
        "text",
        [XID.upper(), XID[:-1], XID + "0", "x-" + XID, f" {XID} "],
        ids=["upper_case", "a_prefix", "longer", "embedded", "padded"],
    )
    async def test_get_by_exchange_order_id_other_text_than_the_bound_one_reads_none(
        self, h: Harness, text: str
    ) -> None:
        """The exact text: no case folding, no prefix, no trimming (an empty text is refused)."""
        account, _ = h.new_account()
        await placed(h, account)
        assert await h.orders.get_by_exchange_order_id(account, text) is None

    @pytest.mark.parametrize("text", [None, "", "x" * 65], ids=["none", "empty", "overlong"])
    async def test_a_read_by_an_exchange_order_id_no_order_can_hold_is_refused(
        self, h: Harness, text: Any
    ) -> None:
        """`None` would read `IS NULL`, an arbitrary unbound row: both reads refuse an id the
        adapter cannot issue (1 to 64 characters of text), before any statement."""
        account, _ = h.new_account()
        await placed(h, account, None)
        await live_stop(h, account)
        for read in (h.orders.get_by_exchange_order_id, h.stops.for_exchange_order):
            with pytest.raises(ValueError, match="1 to 64 characters"):
                await read(account, text)

    async def test_get_by_exchange_order_id_unbound_order_is_never_found(self, h: Harness) -> None:
        """The store's half of "a fill before its bind": a sent row holds no exchange id yet."""
        account, _ = h.new_account()
        await placed(h, account, None)
        assert await h.orders.get_by_exchange_order_id(account, XID) is None

    async def test_get_by_exchange_order_id_each_account_reads_only_its_own_row(
        self, h: Harness
    ) -> None:
        """`ux_orders_exch_id` is per account, so two accounts may hold one id (C-12.4)."""
        (mine, _), (theirs, _), (third, _) = h.new_account(), h.new_account(), h.new_account()
        orders = [await placed(h, mine), await placed(h, theirs)]
        reads = [await h.orders.get_by_exchange_order_id(a, XID) for a in (mine, theirs, third)]
        assert [row and row.id for row in reads] == [orders[0].id, orders[1].id, None]

    async def test_get_by_exchange_order_id_text_holding_nul_is_refused_as_postgres_refuses_it(
        self, h: Harness
    ) -> None:
        account, _ = h.new_account()
        with pytest.raises(StorageQueryFailed):
            await h.orders.get_by_exchange_order_id(account, "a\x00b")

    async def test_live_for_key_pending_and_in_force_rows_are_listed_oldest_first(
        self, h: Harness
    ) -> None:
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile, take_profit=TP)
        sl, tp = (await h.submissions.create_first(first, order, EVENT)).recorded_stops
        await h.stops.settle(account, [sl.id, tp.id], "answered", at=T0)
        h.move_stop(sl.id, "in_force")
        [later] = await h.stops.insert([trading_stop(account)])
        listed = await h.stops.live_for_key(account, "BTCUSDT", 0)
        statuses = {row.id: row.status for row in listed}
        assert statuses == {sl.id: "in_force", tp.id: "pending", later.id: "pending"}
        ages = [(row.created_at, row.id) for row in listed]  # weak on the fake (constant clock)
        assert ages == sorted(ages)

    @pytest.mark.parametrize("end", ["void", "replaced", "ended"])
    async def test_live_for_key_void_replaced_and_ended_rows_are_left_out(
        self, h: Harness, end: str
    ) -> None:
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile)
        [stop] = (await h.submissions.create_first(first, order, EVENT)).recorded_stops
        assert [r.id for r in await h.stops.live_for_key(account, "BTCUSDT", 0)] == [stop.id]
        if end == "void":
            await h.stops.settle(account, [stop.id], "refused", at=T0, write_ahead=audited)
        else:
            await h.stops.settle(account, [stop.id], "answered", at=T0)
            h.move_stop(stop.id, "in_force")
            h.move_stop(stop.id, end)
        assert await h.stops.live_for_key(account, "BTCUSDT", 0) == ()

    async def test_live_for_key_other_account_symbol_or_position_index_reads_empty(
        self, h: Harness
    ) -> None:
        user, (mine, profile), (theirs, other) = h.new_user(), h.new_account(), h.new_account()
        persisted = await h.submissions.create_first(*entry(user, mine, profile), EVENT)
        await h.submissions.create_first(*entry(user, theirs, other), EVENT)
        listed = await h.stops.live_for_key(mine, "BTCUSDT", 0)
        assert [r.id for r in listed] == [s.id for s in persisted.recorded_stops]
        for key in ((uuid4(), "BTCUSDT", 0), (mine, "ETHUSDT", 0), (mine, "BTCUSD", 0),
                    (mine, "BTCUSDT", 1)):  # fmt: skip
            assert await h.stops.live_for_key(*key) == ()

    async def test_live_for_key_symbol_holding_nul_is_refused_as_postgres_refuses_it(
        self, h: Harness
    ) -> None:
        account, _ = h.new_account()
        with pytest.raises(StorageQueryFailed):
            await h.stops.live_for_key(account, "BTC\x00USDT", 0)

    # -- the rows bound to an exchange order (21 Sec.13.1 row 46) --

    async def test_for_exchange_order_text_holding_nul_is_refused_as_postgres_refuses_it(
        self, h: Harness
    ) -> None:
        account, _ = h.new_account()
        with pytest.raises(StorageQueryFailed):
            await h.stops.for_exchange_order(account, "a\x00b")

    @pytest.mark.parametrize("status", ["pending", "in_force", "replaced", "ended"])
    async def test_for_exchange_order_lists_the_row_bound_to_the_id_in_any_status(
        self, h: Harness, status: str
    ) -> None:
        """An end keeps the id, so the fills of a stop that closed its position still pair."""
        account, _ = h.new_account()
        stop = await live_stop(h, account)
        h.bind_stop(stop.id, XID)
        if status != "pending":
            await advance(h, account, stop, status)
        [row] = await h.stops.for_exchange_order(account, XID)
        assert (row.id, row.status, row.exchange_order_id) == (stop.id, status, XID)

    async def test_for_exchange_order_other_account_id_prefix_or_case_reads_empty(
        self, h: Harness
    ) -> None:
        (mine, _), (theirs, _) = h.new_account(), h.new_account()
        h.bind_stop((await live_stop(h, mine, "answered")).id, XID)
        for key in ((theirs, XID), (mine, XID.upper()), (mine, XID[:-1]), (mine, XID + "0")):
            assert await h.stops.for_exchange_order(*key) == ()
