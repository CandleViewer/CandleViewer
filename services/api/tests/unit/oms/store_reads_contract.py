"""Contract of the stores' pairing reads (E29-T05 #848, 24 Sec.8.12): the order bound to an exchange
order id (`OrderStore.get_by_exchange_order_id`, 21 Sec.13.1 row 12), a position key's live
recorded stops (`RecordedStopStore.live_for_key`, row 45), the recorded stops bound to an
exchange order (`for_exchange_order`, row 46) and a stop's successor taking that binding
(`release_and_bind`, 24 Sec.8.3 rule 7); and the exit routes' scoped reads (E29-T04 slice 4,
`get_in_scope` and `accounts_in_scope`), the scope in one SQL predicate (C-12.4). A mixin beside
`SubmissionContract`, on its `h`, run on the in-memory stores (`test_submission_fake.py`) and on
Postgres (`test_order_submission_contract_pg.py`), so the fake reads what Postgres reads (C-13.3).
Every case works in accounts of its own, so a shared database never mixes them."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pytest

from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.orders import (
    AccountsOutOfScope,
    NewOrder,
    OutOfScope,
    ScopedOrder,
)
from candleviewer.storage.repositories.recorded_stops import (
    RecordedStopNotBindable,
    RecordedStopRow,
)
from tests.unit.oms.submission_contract import (
    EVENT,
    HOOKS,
    SEND,
    T0,
    TP,
    Harness,
    Move,
    audited,
    entry,
    reduce_only,
    refuses,
    to,
    trading_stop,
)

XID: Final = "1b3c5d7e-9f01-4a23-b456-789abcdef012"  # made up: the shape of an exchange order id
XID2: Final = "7d6c5b4a-3210-4fed-8cba-987654321098"
RELEASED: Final = T0 + timedelta(minutes=1)
LOW, HIGH, TOP = UUID(int=1), UUID(int=(1 << 128) - 2), UUID(int=(1 << 128) - 1)  # beyond a uuid4


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


async def live_stop(
    h: Harness, account: UUID, status: str = "pending", **over: Any
) -> RecordedStopRow:
    """A system writer's request for BTCUSDT 0, its stop-loss or, as `over` says, its take-profit
    (with the stop-loss every request carries), in flight (`pending`) or advanced. Each row is
    younger than the last."""
    h.tick()
    stops = [trading_stop(account, **over)]
    if stops[0].kind == "take_profit":
        stops.insert(0, trading_stop(account))
    stop = (await h.stops.insert(stops))[-1]
    if status != "pending":
        await advance(h, account, stop, status)
    return stop


async def bound_stop(h: Harness, account: UUID, end: str | None = None) -> RecordedStopRow:
    """A stop-loss bound to `XID`, answered, or taken on to `end` (it keeps the id)."""
    stop = await live_stop(h, account)
    h.bind_stop(stop.id, XID)
    await advance(h, account, stop, end or "answered")
    [row] = await h.stops.for_exchange_order(account, XID)
    return row


async def refused(
    h: Harness, home: UUID, old: UUID, new: UUID, *, caller: UUID | None = None, xid: str = XID
) -> None:
    """The pair is refused before its audit and writes nothing: `XID`'s holders read as before."""
    held = await h.stops.for_exchange_order(home, XID)
    with pytest.raises(RecordedStopNotBindable):
        await h.stops.release_and_bind(
            caller or home, old, new, xid, at=RELEASED, write_ahead=refuses
        )
    assert await h.stops.for_exchange_order(home, XID) == held


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

    async def test_live_for_key_lists_a_row_once_it_is_bound(self, h: Harness) -> None:
        """A bound row stays live: S6 reads it as a successor's predecessor (24 Sec.8.3 rule 7)."""
        account, _ = h.new_account()
        stop = await live_stop(h, account)
        h.bind_stop(stop.id, XID)
        [row] = await h.stops.live_for_key(account, "BTCUSDT", 0)
        assert (row.id, row.exchange_order_id) == (stop.id, XID)

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

    async def test_for_exchange_order_lists_every_holder_oldest_first(self, h: Harness) -> None:
        """`ix_rs_exch_id` is not unique, so the read keeps its order, whatever it holds."""
        account, _ = h.new_account()
        held = [await live_stop(h, account, "answered") for _ in range(3)]
        for stop in held:
            h.bind_stop(stop.id, XID)
        rows = await h.stops.for_exchange_order(account, XID)
        ages = [(row.created_at, row.id) for row in rows]
        assert {row.id for row in rows} == {stop.id for stop in held} and ages == sorted(ages)

    async def test_for_exchange_order_other_account_id_prefix_or_case_reads_empty(
        self, h: Harness
    ) -> None:
        (mine, _), (theirs, _) = h.new_account(), h.new_account()
        h.bind_stop((await live_stop(h, mine, "answered")).id, XID)
        for key in ((theirs, XID), (mine, XID.upper()), (mine, XID[:-1]), (mine, XID + "0")):
            assert await h.stops.for_exchange_order(*key) == ()

    # -- a stop's successor takes its order's binding (24 Sec.8.3 rule 7) ----------------------

    @pytest.mark.parametrize(
        ("held", "taking"),
        [("answered", "pending"), ("in_force", "pending"), ("answered", "in_force")],
        ids=["answered_to_pending", "in_force_to_pending", "answered_to_in_force"],
    )
    async def test_release_and_bind_moves_the_binding_to_the_successor_in_one_commit(
        self, h: Harness, held: str, taking: str
    ) -> None:
        """Only `exchange_order_id` and `released_at` change, whichever live status the two rows
        are in, in the transaction the audit is awaited in, where every other reader still sees the
        old holder; after it the id lists the successor only, never the released predecessor."""
        account, _ = h.new_account()
        old, new = await bound_stop(h, account, held), await live_stop(h, account, taking)
        [new] = [r for r in await h.stops.live_for_key(account, "BTCUSDT", 0) if r.id == new.id]
        seen: list[tuple[tuple[RecordedStopRow, RecordedStopRow], tuple[RecordedStopRow, ...]]] = []

        async def audit(rows: tuple[RecordedStopRow, RecordedStopRow]) -> None:
            seen.append((rows, await h.stops.for_exchange_order(account, XID)))

        released, bound = await h.stops.release_and_bind(
            account, old.id, new.id, XID, at=RELEASED, write_ahead=audit
        )
        assert released == replace(old, exchange_order_id=None, released_at=RELEASED)
        assert bound == replace(new, exchange_order_id=XID)
        assert await h.stops.for_exchange_order(account, XID) == (bound,)
        assert seen == [((released, bound), (old,))]

    async def test_release_and_bind_replay_of_a_committed_pair_is_refused(self, h: Harness) -> None:
        account, _ = h.new_account()
        old, new = await bound_stop(h, account), await live_stop(h, account)
        await h.stops.release_and_bind(
            account, old.id, new.id, XID, at=RELEASED, write_ahead=audited
        )
        await refused(h, account, old.id, new.id)

    @pytest.mark.parametrize("end", ["void", "replaced", "ended"])
    async def test_release_and_bind_dead_or_ended_predecessor_is_refused(
        self, h: Harness, end: str
    ) -> None:
        """An end keeps its id, and `trg_rs_guard` would admit the release of an ended row, so the
        store refuses it (R-5)."""
        account, _ = h.new_account()
        old = await bound_stop(h, account, end)
        await refused(h, account, old.id, (await live_stop(h, account)).id)

    async def test_release_and_bind_names_the_id_its_predecessor_holds(self, h: Harness) -> None:
        account, _ = h.new_account()
        old, new = await bound_stop(h, account), await live_stop(h, account)
        await refused(h, account, old.id, new.id, xid=XID2)

    @pytest.mark.parametrize(
        "state", ["itself", "bound_elsewhere", "released", "void", "replaced", "ended"]
    )
    async def test_release_and_bind_successor_must_be_live_unbound_and_unreleased(
        self, h: Harness, state: str
    ) -> None:
        account, _ = h.new_account()
        old = await bound_stop(h, account)
        new = old if state == "itself" else await live_stop(h, account)
        if state in {"bound_elsewhere", "released"}:
            h.bind_stop(new.id, XID2)
        if state == "released":  # answered, then a younger row took XID2 from it
            await advance(h, account, new, "answered")
            younger = await live_stop(h, account)
            await h.stops.release_and_bind(
                account, new.id, younger.id, XID2, at=RELEASED, write_ahead=audited
            )
        elif state not in {"itself", "bound_elsewhere"}:
            await advance(h, account, new, state)
        await refused(h, account, old.id, new.id)

    @pytest.mark.parametrize("who", ["caller", "predecessor", "successor"])
    async def test_release_and_bind_across_accounts_is_refused(self, h: Harness, who: str) -> None:
        (mine, _), (theirs, _) = h.new_account(), h.new_account()
        home, other, caller = {
            "caller": (mine, mine, theirs), "predecessor": (theirs, mine, mine),
            "successor": (mine, theirs, mine),
        }[who]  # fmt: skip
        old, new = await bound_stop(h, home), await live_stop(h, other)
        await refused(h, home, old.id, new.id, caller=caller)

    @pytest.mark.parametrize(
        "over",
        [{"symbol": "ETHUSDT"}, {"position_idx": 1}, {"kind": "take_profit"}],
        ids=["symbol", "position_idx", "kind"],
    )
    async def test_release_and_bind_successor_of_another_side_is_refused(
        self, h: Harness, over: dict[str, Any]
    ) -> None:
        account, _ = h.new_account()
        old = await bound_stop(h, account)
        await refused(h, account, old.id, (await live_stop(h, account, **over)).id)

    async def test_release_and_bind_earlier_successor_is_refused(self, h: Harness) -> None:
        """Later is by age first: a larger id does not make an older row a successor."""
        account, _ = h.new_account()
        early = await live_stop(h, account, "answered", id=TOP)
        await refused(h, account, (await bound_stop(h, account)).id, early.id)

    async def test_release_and_bind_of_equal_age_takes_the_larger_id_only(self, h: Harness) -> None:
        """Later is by `created_at`, then `id`: a successor of the same age takes the id only if
        its own is larger."""
        account, _ = h.new_account()
        old = await live_stop(h, account, "answered")
        h.twin_stop(old.id, LOW)
        h.twin_stop(old.id, HIGH)
        h.bind_stop(old.id, XID)
        await refused(h, account, old.id, LOW)
        _, bound = await h.stops.release_and_bind(
            account, old.id, HIGH, XID, at=RELEASED, write_ahead=audited
        )
        assert bound.id == HIGH

    async def test_release_and_bind_where_another_row_holds_the_id_is_refused(
        self, h: Harness
    ) -> None:
        """One holder per order, never two: the release clears the predecessor, not the third."""
        account, _ = h.new_account()
        old = await bound_stop(h, account)
        h.bind_stop((await live_stop(h, account, "answered")).id, XID)
        await refused(h, account, old.id, (await live_stop(h, account)).id)

    async def test_release_and_bind_where_an_ended_row_holds_the_id_is_refused(
        self, h: Harness
    ) -> None:
        """Never two counts a holder in any status: an end keeps its id (24 Sec.8.3 rule 7), so a
        third row of the account that ended holding it still refuses the pair."""
        account, _ = h.new_account()
        old, ended = await bound_stop(h, account), await live_stop(h, account)
        h.bind_stop(ended.id, XID)
        await advance(h, account, ended, "ended")
        await refused(h, account, old.id, (await live_stop(h, account)).id)

    async def test_release_and_bind_where_another_account_holds_the_id_is_not_blocked(
        self, h: Harness
    ) -> None:
        """Never two is the account's own: a row of another account that holds the same exchange
        order id is no holder here, so the pair moves the binding and leaves that row as it was."""
        (mine, _), (theirs, _) = h.new_account(), h.new_account()
        h.bind_stop((await live_stop(h, theirs, "answered")).id, XID)
        [foreign] = await h.stops.for_exchange_order(theirs, XID)
        old, new = await bound_stop(h, mine), await live_stop(h, mine)
        released, bound = await h.stops.release_and_bind(
            mine, old.id, new.id, XID, at=RELEASED, write_ahead=audited
        )
        assert (released.id, bound.id) == (old.id, new.id)
        assert await h.stops.for_exchange_order(mine, XID) == (bound,)
        assert await h.stops.for_exchange_order(theirs, XID) == (foreign,)

    async def test_release_and_bind_two_successors_at_once_one_wins_and_the_other_is_refused(
        self, h: Harness
    ) -> None:
        account, _ = h.new_account()
        old = await bound_stop(h, account)
        successors = [await live_stop(h, account, "answered") for _ in range(2)]
        both = await asyncio.gather(
            *(h.stops.release_and_bind(account, old.id, s.id, XID, at=RELEASED, write_ahead=audited)
              for s in successors),
            return_exceptions=True,
        )  # fmt: skip
        [(released, bound)] = [r for r in both if isinstance(r, tuple)]
        assert sum(isinstance(r, RecordedStopNotBindable) for r in both) == 1
        assert released.id == old.id and bound.id in {s.id for s in successors}
        assert await h.stops.for_exchange_order(account, XID) == (bound,)

    @pytest.mark.parametrize(
        ("xid", "at", "hook", "error"),
        [
            ("", RELEASED, audited, ValueError),
            ("x" * 65, RELEASED, audited, ValueError),
            ("a\x00b", RELEASED, audited, StorageQueryFailed),
            (XID, RELEASED.replace(tzinfo=None), audited, ValueError),
            (XID, RELEASED, None, ValueError),
        ],
        ids=["empty_id", "overlong_id", "nul_id", "naive_time", "no_hook"],
    )
    async def test_release_and_bind_malformed_call_is_refused_before_it_writes(
        self, h: Harness, xid: str, at: Any, hook: Any, error: type[Exception]
    ) -> None:
        account, _ = h.new_account()
        old, new = await bound_stop(h, account), await live_stop(h, account)
        with pytest.raises(error):
            await h.stops.release_and_bind(account, old.id, new.id, xid, at=at, write_ahead=hook)
        assert await h.stops.for_exchange_order(account, XID) == (old,)

    @pytest.mark.parametrize("hook", sorted(HOOKS))
    async def test_release_and_bind_whose_audit_fails_writes_nothing(
        self, h: Harness, hook: str
    ) -> None:
        account, _ = h.new_account()
        old, new = await bound_stop(h, account), await live_stop(h, account)
        audit, raised = HOOKS[hook]
        with pytest.raises(raised):
            await h.bounded(0.05).stops.release_and_bind(
                account, old.id, new.id, XID, at=RELEASED, write_ahead=audit
            )
        assert await h.stops.for_exchange_order(account, XID) == (old,)
        await h.stops.release_and_bind(
            account, old.id, new.id, XID, at=RELEASED, write_ahead=audited
        )

    # -- the exit routes' scope (E29-T04 slice 4; 24 Sec.8.4 "The exit routes", step 4) --

    async def test_get_in_scope_owner_and_trade_grant_read_the_order_its_group_and_creator(
        self, h: Harness
    ) -> None:
        """Ruling Q6: an entry's creator is its group's `created_by`; the leg names its profile."""
        creator, owner, manager, (account, profile) = (*_users(h, 3), h.new_account())
        first, order = entry(creator, account, profile)
        await h.submissions.create_first(first, order, EVENT)
        h.owner(owner)
        h.grant(manager, account, True, False)
        assert first.group is not None
        for scope in (OwnerScope(owner), GrantScope(manager, frozenset({account}))):
            got = await h.orders.get_in_scope(scope, order.id, environment="demo")
            assert isinstance(got, ScopedOrder) and got.order.id == order.id
            seen = (got.trade_group_id, got.profile_id, got.created_by, got.can_trade)
            assert seen == (first.group.id, profile, creator, True)

    async def test_get_in_scope_a_view_only_grant_reads_an_order_it_may_not_trade(
        self, h: Harness
    ) -> None:
        """Ruling Q7: answered 403 by the exit service, as the caller reads the order already; a
        reduce-only order has no group, so its creator is its anchor's."""
        creator, viewer, (account, _) = (*_users(h, 2), h.new_account())
        first, order = reduce_only(creator, account)
        await h.submissions.create_first(first, order, EVENT)
        h.grant(viewer, account, False, False)
        got = await h.orders.get_in_scope(
            GrantScope(viewer, frozenset({account})), order.id, environment="demo"
        )
        assert isinstance(got, ScopedOrder)
        assert (got.trade_group_id, got.profile_id, got.created_by, got.can_trade) == (
            None, None, creator, False,
        )  # fmt: skip

    @pytest.mark.parametrize(
        "case", ["no_grant", "frozen", "deleted", "other_environment", "not_in_the_snapshot"]
    )
    async def test_get_in_scope_outside_the_scope_reads_only_the_holders_account(
        self, h: Harness, case: str
    ) -> None:
        """SR-E29-13: no row leaves the scope; the account that holds the id is for the audit of
        the 404 alone (ruling Q12). An Owner reads no deleted or other environment's order."""
        user = h.new_user()
        account, _ = h.elsewhere() if case == "other_environment" else h.new_account()
        first, order = reduce_only(h.new_user(), account)
        await h.submissions.create_first(first, order, EVENT)
        if case != "no_grant":
            h.grant(user, account, True, case == "frozen")
        if case == "deleted":
            h.refuse(account, "account_not_live")
        ids = frozenset({uuid4() if case == "not_in_the_snapshot" else account})
        scopes: list[AccountScope] = [GrantScope(user, ids)]
        if case in ("deleted", "other_environment"):
            h.owner(owner := h.new_user())
            scopes.append(OwnerScope(owner))
        for scope in scopes:
            assert await h.orders.get_in_scope(scope, order.id, environment="demo") == OutOfScope(
                account
            )

    async def test_get_in_scope_a_missing_id_or_a_user_who_is_no_owner_reads_none(
        self, h: Harness
    ) -> None:
        """SR-051's owner predicate: an `OwnerScope` is the live owner role's, not the type's."""
        account, _ = h.new_account()
        first, order = reduce_only(h.new_user(), account)
        await h.submissions.create_first(first, order, EVENT)
        h.owner(owner := h.new_user())
        missing = await h.orders.get_in_scope(OwnerScope(owner), uuid4(), environment="demo")
        assert missing == OutOfScope(None)
        posing = await h.orders.get_in_scope(OwnerScope(h.new_user()), order.id, environment="demo")
        assert posing == OutOfScope(account)

    async def test_accounts_in_scope_none_requested_is_the_environments_trade_grants(
        self, h: Harness
    ) -> None:
        """An Owner's are every live account of the environment, a frozen grant's too."""
        user, owner = _users(h, 2)
        names = ("trade", "view", "frozen", "deleted")
        held = {name: h.new_account()[0] for name in names} | {"live": h.elsewhere()[0]}
        for name, account in held.items():
            h.grant(user, account, name != "view", name == "frozen")
        h.refuse(held["deleted"], "account_not_live")
        scope = GrantScope(user, frozenset(held.values()))
        assert await h.orders.accounts_in_scope(scope, "demo", ()) == (held["trade"],)
        h.owner(owner)
        reach = set(await h.orders.accounts_in_scope(OwnerScope(owner), "demo", ()))
        assert {held["trade"], held["view"], held["frozen"]} <= reach
        assert not {held["deleted"], held["live"]} & reach

    @pytest.mark.parametrize(
        "case", ["foreign", "view_only", "frozen", "deleted", "other_environment", "missing"]
    )
    async def test_accounts_in_scope_one_account_outside_refuses_the_whole_request(
        self, h: Harness, case: str
    ) -> None:
        """SR-E29-13, all or nothing; a request inside it is answered as asked, once each."""
        user, (granted, _) = h.new_user(), h.new_account()
        h.grant(user, granted, True, False)
        other = uuid4()
        if case != "missing":
            other = (h.elsewhere() if case == "other_environment" else h.new_account())[0]
        if case not in ("foreign", "missing"):
            h.grant(user, other, case != "view_only", case == "frozen")
        if case == "deleted":
            h.refuse(other, "account_not_live")
        scope = GrantScope(user, frozenset({granted, other}))
        with pytest.raises(AccountsOutOfScope):
            await h.orders.accounts_in_scope(scope, "demo", (granted, other))
        assert await h.orders.accounts_in_scope(scope, "demo", (granted, granted)) == (granted,)

    async def test_accounts_in_scope_the_owner_names_live_accounts_of_the_environment_only(
        self, h: Harness
    ) -> None:
        (mine, _), (deleted, _), (live, _) = h.new_account(), h.new_account(), h.elsewhere()
        h.refuse(deleted, "account_not_live")
        h.owner(owner := h.new_user())
        scope = OwnerScope(owner)
        assert await h.orders.accounts_in_scope(scope, "demo", (mine,)) == (mine,)
        for outside in (deleted, live, uuid4()):
            with pytest.raises(AccountsOutOfScope):
                await h.orders.accounts_in_scope(scope, "demo", (mine, outside))
        with pytest.raises(AccountsOutOfScope):  # a user who is no owner reaches nothing
            await h.orders.accounts_in_scope(OwnerScope(h.new_user()), "demo", (mine,))


def _users(h: Harness, n: int) -> list[UUID]:
    return [h.new_user() for _ in range(n)]
