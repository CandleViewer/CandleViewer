"""E29-Q02 (#1147, C4b): 24 Sec.8.2's transition rules S6 to S9, driven black-box through the
composed app of C4a (`_world.py`; its helpers are `test_conformance_s1_s5.py`'s): REST requests as
the Owner, the frames a `/ws` client is sent, the rows the stores hold and the audit records the
order lane writes, as the plan's cases state them (`e29_q02_cases.txt` maps each test to its
E29-TC-nnn and names what a row leaves out). Pushes are derived in-test: derived, not evidence.
Every order is an entry and asserts its native stop (C-2.6): the create the venue receives carries
it and a filled order's position holds it. The store's faults are `InMemoryOrderStore.fail_next`'s;
Postgres's own cuts are T4's. S10 and S11 stay unit-level (ruling BQ-6)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.oms.reconciler import adopted_row
from candleviewer.storage.errors import StorageTierUnavailable
from tests.qa.oms._world import ACCOUNT, FILLS, ORDERS, REF, WAIT_S, OmsWorld, fill_row, order_row
from tests.qa.oms.test_conformance_s1_s5 import (
    channels,
    exec_ids,
    filled,
    items,
    kinds,
    placed,
    protection,
    stages,
)
from tests.unit.exchange.bybit._private import linear_execution, linear_order
from tests.unit.oms.submission_contract import trading_stop
from tests.unit.oms.test_e29_t05_acceptance import STOP

_D = Decimal
_DOWN = StorageTierUnavailable("postgres unreachable")


def written(world: OmsWorld, mark: int, action: str) -> list[dict[str, Any]]:
    """The fields of the `action` records the order lane wrote after the first `mark` of them."""
    return [fields for name, fields in world.oms.writer.records[mark:] if name == action]


def fresh(world: OmsWorld) -> uuid.UUID:
    """An id no test of the world used: the world's request keys never repeat."""
    return uuid.UUID(world.key()["Idempotency-Key"])


@pytest.mark.parametrize("ended", ["filled", "cancelled"])
def test_s6_a_push_after_the_order_ended_is_an_anomaly_and_changes_nothing(
    world: OmsWorld, ended: str
) -> None:
    """S6, E29-TC-454 and E29-TC-554: an order the stream filled, or the exchange cancelled with
    nothing filled, is sent a `Triggered` and a `Cancelled` row, then a `Filled` and a `New` echo.
    The order, its steps and its executions are as they were and no frame follows; each of the
    first two is an anomaly, audited `oms.reconcile_anomaly` (`POST_TERMINAL_PUSH`, `denied`, the
    state it met) and alerted, a ticket and not a page; the echoes map to no event. A cancel of
    the ended order is `202` as it stands and sends nothing (E29-TC-450's refusal, as
    E29-TC-652). Not here: the anomaly counter."""
    order, _ = placed(world)
    row = world.row(order)
    with world.socket("orders", "executions") as ws:
        if ended == "filled":
            world.fill(order, "e1", "0.010", seq=1)
            assert protection(ws, order) == "sl_present"
        else:
            world.deliver(ORDERS, order_row(row, "Cancelled"))
        ws.sent()
        assert world.order(order)["state"] == ended
        before = (world.order(order), world.chain(order), world.row(order))
        cancels, mark = len(world.sent("cancel_order")), len(world.oms.writer.records)
        pages = len(world.oms.pager.calls)
        for status in ("Triggered", "Cancelled", "Filled", "New"):
            world.deliver(ORDERS, order_row(row, status))
        frames = ws.sent()
    assert items(frames, "orders", order) == [] == items(frames, "executions", order)
    assert (world.order(order), world.chain(order), world.row(order)) == before
    anomalies = written(world, mark, "oms.reconcile_anomaly")
    assert [(a["reason"], a["outcome"]) for a in anomalies] == [
        ("POST_TERMINAL_PUSH", "denied")
    ] * 2
    assert [(a["after_state"]["state"], a["after_state"]["trigger"]) for a in anomalies] == [
        (ended, "TRIGGERED"), (ended, "REMOTE_CANCELLED"),
    ]  # fmt: skip
    assert world.oms.pager.calls[pages:] == ["oms_reconcile_anomaly"] * 2
    assert world.oms.pager.severities[pages:] == ["alert"] * 2
    answer = world.cancel(order)
    assert (answer.status_code, answer.json()["lifecycle_state"]) == (202, ended)
    assert len(world.sent("cancel_order")) == cancels


def test_s6_a_fill_after_the_order_ended_is_consumed_and_its_position_handed_over(
    world: OmsWorld,
) -> None:
    """S6, E29-TC-454: an execution of a filled order, more than its quantity, is audited
    `oms.reconcile_anomaly` (the trigger `EXEC`, its `exec_id`) and alerted, and is stored nowhere,
    framed nowhere and added to nothing: the order is as it was. The position it may have opened
    is handed to B8 for its stop (C-2.6): the `request_fallback_sl` notice, which nothing owns
    until E32, so the world pages it. Not here: B8's attach."""
    order, _ = placed(world)
    row = world.row(order)
    with world.socket("orders", "executions") as ws:
        world.fill(order, "e1", "0.010", seq=1)
        assert protection(ws, order) == "sl_present"
        ws.sent()
        before = (world.order(order), world.chain(order))
        mark, pages = len(world.oms.writer.records), len(world.oms.pager.calls)
        world.deliver(FILLS, fill_row(row, "late", "0.002", seq=2))
        frames = ws.sent()
    assert items(frames, "orders", order) == [] == items(frames, "executions", order)
    assert (world.order(order), world.chain(order)) == before and world.fills(order) == ["e1"]
    [anomaly] = written(world, mark, "oms.reconcile_anomaly")
    assert (anomaly["reason"], anomaly["outcome"]) == ("POST_TERMINAL_PUSH", "denied")
    assert anomaly["after_state"]["trigger"] == "EXEC"
    assert anomaly["after_state"]["exec_id"] == f"{order['order_link_id']}-late"
    assert world.oms.pager.severities[pages:] == ["alert", "page"]
    assert "request_fallback_sl" in world.oms.pager.calls[-1]


def test_s7_an_order_the_store_cannot_record_is_refused_and_nothing_is_sent(
    world: OmsWorld,
) -> None:
    """S7, E29-TC-506 (once the OMS is ready) and E29-TC-456: the store refuses the write of the
    order's first step. `placeOrder` is `503 store_unavailable`, with no `Retry-After`, before any
    send; no order exists, as a row or a frame; the refusal is audited after the intent written
    ahead (C-2.9). The same `Idempotency-Key` sent once the store answers is a new request: one
    order and one create, carrying its stop (C-2.6). Not here: Postgres cut at boot
    (`oms_not_ready`), a store that hangs, a stopped container (T4, Q04 s12)."""
    key, sent, held = world.key(), len(world.sent("place_order")), len(world.oms.store._orders)
    mark = len(world.oms.writer.actions)
    with world.socket("orders") as ws:
        world.oms.store.fail_next(_DOWN)
        down = world.place(key=key)
        assert (down.status_code, down.json()["code"]) == (503, "store_unavailable")
        assert "retry-after" not in down.headers and len(world.sent("place_order")) == sent
        assert len(world.oms.store._orders) == held and channels(ws.sent()) == []
        assert world.oms.writer.actions[mark:][0] == ("orders.submit", "validated")  # ahead
        assert world.oms.writer.actions[mark:][-1] == ("orders.submit", "store_unavailable")
        again = world.place(key=key)
    assert (again.status_code, "idempotency-replayed" in again.headers) == (202, False)
    [order] = again.json()["trade_group"]["legs"][0]["order_details"]
    assert len(world.creates(order)) == 1 and len(world.oms.store._orders) == held + 1


def test_s7_a_cancel_the_store_cannot_record_is_refused_and_leaves_the_order_as_it_was(
    world: OmsWorld,
) -> None:
    """S7 and S8, E29-TC-456: the store refuses the write of the cancel's first step. The answer is
    `503 store_unavailable` and nothing is sent; the order is as it was on REST and in its steps,
    and no frame comes (a step whose row did not commit does not exist); the intent was written
    ahead, then the refusal (C-2.9). Once the store answers, the cancel goes through."""
    order, _ = placed(world, symbol="ADAUSDT")
    with world.socket("orders") as ws:
        before = (world.order(order), world.chain(order))
        cancels, mark = len(world.sent("cancel_order")), len(world.oms.writer.records)
        world.oms.store.fail_next(_DOWN)
        down = world.cancel(order)
        assert (down.status_code, down.json()["code"]) == (503, "store_unavailable")
        assert (world.order(order), world.chain(order)) == before
        assert len(world.sent("cancel_order")) == cancels and stages(ws.sent(), order) == []
        records = written(world, mark, "orders.cancel")
        assert [(r["outcome"], r["reason"]) for r in records] == [
            ("success", "user"), ("denied", "store_unavailable"),
        ]  # fmt: skip
        again = world.cancel(order)
    assert (again.status_code, again.json()["lifecycle_state"]) == (202, "cancelled")


def test_s7_a_store_failure_after_the_send_is_never_a_503(world: OmsWorld) -> None:
    """S7, E29-TC-506: the create is at the venue's door and the store refuses the write of its
    acknowledgement. That is no refusal of entry: `placeOrder` answers `202` and the order
    reaches `accepted`, its acknowledgement written once and framed once, the failure paged, and
    the venue was sent one create (C-2.10), carrying the order's stop (C-2.6)."""
    door = world.hold("place_order")
    pages = len(world.oms.pager.calls)
    with world.socket("orders") as ws:
        with world.pending(door, world.place) as placing:
            world.oms.store.fail_next(_DOWN)
            door.open()
            answer = placing.result(WAIT_S)
        assert answer.status_code == 202
        [order] = answer.json()["trade_group"]["legs"][0]["order_details"]
        frames = ws.sent()
    assert stages(frames, order) == [
        ("created", "pending_submit"), ("submitted", "submitted"), ("ack", "accepted"),
    ]  # fmt: skip
    assert kinds(world, order, 3) == ["local_create", "submit_attempt", "ack"]
    assert (world.order(order)["state"], world.row(order).state) == ("accepted", "accepted")
    assert world.oms.pager.severities[pages:] == ["page"] and len(world.creates(order)) == 1


def test_s8_the_intent_is_stored_before_the_create_leaves_and_its_outcome_after(
    world: OmsWorld,
) -> None:
    """S8, E29-TC-500 (the intent before the send, its outcome after) and E29-TC-456: when the
    create reaches the venue its order's first two steps, `local_create` and `submit_attempt`,
    are stored and framed, REST shows the order `submitted`, and the audit log holds the intent
    (`orders.submit`, `validated`) and the stop's request (`sl.attached`); the acknowledgement's
    step and the outcome (`orders.submit`, `submitted`) come after the send. The create carries
    the stop (C-2.6)."""
    door = world.hold("place_order")
    mark = len(world.oms.writer.actions)
    with world.socket("orders") as ws:
        with world.pending(door, world.place) as placing:
            [create] = door.requests
            row = world.call(world.oms.store.get_by_link_id, ACCOUNT, create.order_link_id)
            unbound = {"id": str(row.id), "order_link_id": row.order_link_id}  # as REST names it
            assert world.chain(unbound) == [
                ("local_create", "local", "pending_submit"),
                ("submit_attempt", "local", "submitted"),
            ]
            assert (row.state, row.lifecycle_state, row.exchange_order_id) == (
                "submitted", "submitting", None,
            )  # fmt: skip
            assert world.order(unbound)["state"] == "submitted"
            assert stages(ws.sent(), unbound) == [
                ("created", "pending_submit"), ("submitted", "submitted"),
            ]  # fmt: skip
            assert world.oms.writer.actions[mark:] == [
                ("orders.submit", "validated"),
                ("trade_group.submit", "submitting"),
                ("sl.attached", "entry_attach"),
            ]
            door.open()
            answer = placing.result(WAIT_S)
        assert answer.status_code == 202
        [order] = answer.json()["trade_group"]["legs"][0]["order_details"]
    assert world.chain(order)[-1] == ("ack", "rest", "accepted")
    assert world.oms.writer.actions[mark:][-1] == ("orders.submit", "submitted")
    assert len(world.creates(order)) == 1


def test_s8_a_write_whose_answer_was_cut_is_rebuilt_from_its_row_and_never_applied_twice(
    world: OmsWorld,
) -> None:
    """S8 and S7, E29-TC-456 (24 Sec.8.2, an unknown outcome): the write of a fill's step commits
    and its answer is lost, so the machine is behind its row. The row decides: REST, the stored
    steps and the executions show the fill once, the unknown outcome is paged, and the next fill
    is added to it once, on the rebuilt machine, whose stop is confirmed (C-2.6). Not here: the
    frames of the cut step, which the rebuilt machine does not publish."""
    order, _ = placed(world)
    pages = len(world.oms.pager.calls)
    with world.socket("orders", "executions") as ws:
        world.oms.store.fail_next(TimeoutError("the answer was cut off"), committed=True)
        world.fill(order, "e1", "0.004", seq=1)
        row, got = world.row(order), world.order(order)
        assert (row.state, row.cum_exec_qty) == ("partially_filled", _D("0.004"))
        assert (got["state"], _D(got["filled_qty"])) == ("partially_filled", _D("0.004"))
        assert world.fills(order) == ["e1"] and kinds(world, order, 1) == ["partial_fill"]
        assert "oms_step_outcome_unknown" in world.oms.pager.calls[pages:]
        world.fill(order, "e2", "0.006", seq=2)
        frames = ws.sent()
        assert protection(ws, order) == "sl_present"
    assert (exec_ids(frames, order)[-1:], filled(frames, order)[-1:]) == (["e2"], ["0.01"])
    assert (world.row(order).state, world.row(order).cum_exec_qty) == ("filled", _D("0.010"))
    assert world.fills(order) == ["e1", "e2"] and kinds(world, order, 2) == ["partial_fill", "fill"]


def test_s8_a_restarted_process_rebuilds_the_order_as_its_events_left_it(world: OmsWorld) -> None:
    """S8, E29-TC-455 (its first leg): an order took its submit, ack, an accepted amend and a part
    fill; the process ends and another starts over the same stores and venue. The order is as it
    was: its REST body (state, terms, filled quantity, average price, exchange order id, `events[]`
    and executions), its row and its stored steps are equal; no second create is sent and nothing
    is paged; the stop is confirmed again from the venue (C-2.6) and the next fill applies once
    on the rebuilt machine. Not here: a cancel or a create in flight (a stop waits the 10 s drain
    for a request still out) and the SIGKILL leg (Q04 s14)."""
    order, etag = placed(world)
    assert world.amend(order, etag, price="60100").status_code == 202
    world.fill(order, "e1", "0.004", seq=1)
    before = (world.order(order), world.chain(order), world.row(order))
    pages = len(world.oms.pager.calls)
    world.restart()
    assert (world.order(order), world.chain(order), world.row(order)) == before
    assert _D(before[0]["price"]) == 60_100 and before[2].cum_exec_qty == _D("0.004")
    assert len(world.creates(order)) == 1 and len(world.oms.pager.calls) == pages
    with world.socket("orders", "executions") as ws:
        assert protection(ws, order) == "sl_present"
        world.fill(order, "e2", "0.006", seq=2)
        frames = ws.sent()
    assert (exec_ids(frames, order), filled(frames, order)) == (["e2"], ["0.01"])
    assert (world.row(order).state, world.fills(order)) == ("filled", ["e1", "e2"])


def test_s9_a_fill_no_order_owns_opens_the_lockout_once_per_key_and_touches_no_order(
    world: OmsWorld,
) -> None:
    """S9, E29-TC-555: a trade fill of an order no row is bound to opens the account's lockout
    once per key, the fill's `exec_id`: `oms.no_intent_detected` is written (`frozen: false` until
    E39-T04) and one P1 is paged; a redelivery writes and pages nothing; the next fill, another
    key, opens it again. No order, step or frame is touched: it is never managed. Not here: the
    lockout's own state (E29-G-06) and the fill kept for the next pass (the world's stand-in
    keeps none)."""
    order, _ = placed(world)
    before = (world.order(order), world.chain(order))
    mark, pages = len(world.oms.writer.records), len(world.oms.pager.calls)

    def foreign(name: str) -> dict[str, Any]:
        link = order["order_link_id"]
        values = {"orderId": "xF", "orderLinkId": "", "execId": f"{link}-{name}", "seq": 9}
        return linear_execution(**values | {"execQty": "0.2", "side": "Buy"})

    with world.socket("orders", "executions") as ws:
        world.deliver(FILLS, foreign("eF"))
        [first] = written(world, mark, "oms.no_intent_detected")
        assert first["after_state"]["key"] == f"{order['order_link_id']}-eF"
        assert first["after_state"]["frozen"] is False
        assert world.oms.pager.severities[pages:] == ["page"]
        world.deliver(FILLS, foreign("eF"))  # redelivered
        assert len(written(world, mark, "oms.no_intent_detected")) == 1
        assert len(world.oms.pager.calls[pages:]) == 1
        world.deliver(FILLS, foreign("eG"))  # the next fill: its own key
        keys = [r["after_state"]["key"] for r in written(world, mark, "oms.no_intent_detected")]
        assert keys == [f"{order['order_link_id']}-{n}" for n in ("eF", "eG")]
        assert world.oms.pager.severities[pages:] == ["page", "page"]
        assert channels(ws.sent()) == []
    assert (world.order(order), world.chain(order)) == before


def test_s9_an_order_no_row_is_bound_to_is_listed_not_snapshotted_and_never_commanded(
    world: OmsWorld,
) -> None:
    """S9, E29-TC-460 (the Owner's half), E29-TC-603 (what a client reads) and E29-TC-450 (the
    refusal): an order placed in the Bybit app, held by the venue and bound to no row, is recorded
    `untracked` under its `ext_key`, as the pass records one (the world's pass is the stand-in
    that finds nothing, so the test makes the finding). REST lists it and `getOrder` shows it;
    the step into it is a `reconcile` frame carrying its id in `removed`, and a new subscription's
    snapshot lacks it; the Owner's cancel is `409 conflict`, nothing is sent and the refusal is
    audited. Not here: the pass, a Manager's `403` and a held order (X02, slice C)."""
    xid, row_id = f"x-{fresh(world).hex[-12:]}", fresh(world)
    [event] = world.parsed(ORDERS, linear_order(orderId=xid, orderLinkId="", orderStatus="New"))
    world.port.seed_order(event.payload, uid=REF.uid)  # the venue holds it, no row is bound to it
    manual = adopted_row(row_id, ACCOUNT, event.payload, ext_key(xid), stop=False)
    order = {"id": str(row_id), "order_link_id": manual.order_link_id}
    mark, cancels = len(world.oms.writer.records), len(world.sent("cancel_order"))
    with world.socket("orders") as ws:
        assert world.discover(manual) == "untracked"
        frames = ws.sent()
        assert stages(frames, order) == [("reconcile", "untracked")]
        [removed] = [f["p"]["removed"] for f in frames if f.get("ch") == "orders"]
        assert removed == [order["id"]]
        listing = world.rest("GET", "/orders").json()["items"]
        assert [o["state"] for o in listing if o["id"] == order["id"]] == ["untracked"]
        got = world.order(order)
        assert (got["state"], got["lifecycle_state"], got["order_link_id"]) == (
            "untracked", "untracked", ext_key(xid),
        )  # fmt: skip
        assert got["exchange_order_id"] == xid
        assert [e["kind"] for e in got["events"]] == ["adopt"]
        answer = world.cancel(order)
        assert (answer.status_code, answer.json()["code"]) == (409, "conflict")
        assert len(world.sent("cancel_order")) == cancels and world.row(order).state == "untracked"
        [denied] = written(world, mark, "orders.cancel")
        assert (denied["outcome"], denied["reason"]) == ("denied", "conflict")
    with world.socket() as later:
        assert order["id"] not in [o["id"] for o in later.sub("orders")["orders"]]


def test_s9_a_recorded_stops_order_is_materialised_never_foreign(world: OmsWorld) -> None:
    """S9, E29-TC-556: the venue shows the TP/SL order of a stop the OMS recorded, which no row is
    bound to. A `recorded_stop` row is materialised, bound to its `orderId`, reduce-only, its
    record bound, and nothing is sent: REST lists it and a frame carries it. Its fill applies to
    that row, an `executions` frame then an `orders` frame, with no audit record and no page, so
    no lockout opens. The symbol is its own: the record holds the position's key. Not here: the
    stop's cancel while its position is open (E29-TC-109)."""
    xid = f"x-{fresh(world).hex[-12:]}"
    values = {"symbol": "XRPUSDT", "tpsl_mode": "Partial", "size": _D("0.5")}
    values |= {"trigger_price": _D(str(STOP["triggerPrice"]))}
    [record] = world.call(world.oms.store.stops.insert, [trading_stop(ACCOUNT, **values)])
    mark, pages = len(world.oms.writer.records), len(world.oms.pager.calls)
    sent = len(world.port.calls)
    with world.socket("orders", "executions") as ws:
        world.deliver(ORDERS, linear_order(**STOP | {"orderId": xid, "symbol": "XRPUSDT"}))
        row = world.call(world.oms.store.get_by_exchange_order_id, ACCOUNT, xid)
        assert (row.provenance, row.intent, row.reduce_only, row.close_on_trigger) == (
            "recorded_stop", "stop_loss", True, True,
        )  # fmt: skip
        bound = world.call(world.oms.store.stops.for_exchange_order, ACCOUNT, xid)
        assert [r.id for r in bound] == [record.id] and len(world.port.calls) == sent
        fill = linear_execution(orderId=xid, orderLinkId="", execId=f"{xid}-e", execQty="0.5")
        world.deliver(FILLS, fill | {"symbol": "XRPUSDT"})
        frames = ws.sent()
    stop = {"id": str(row.id), "order_link_id": row.order_link_id}
    assert stages(frames, stop) == [("created", "accepted"), ("fill", "filled")]
    assert channels(frames) == ["orders", "executions", "orders"]
    got = world.order(stop)
    assert (got["provenance"], got["state"], _D(got["filled_qty"])) == (
        "recorded_stop", "filled", _D("0.5"),
    )  # fmt: skip
    assert [e["kind"] for e in got["events"]] == ["exchange_push", "fill"]
    assert [o["id"] for o in world.rest("GET", "/orders").json()["items"]].count(stop["id"]) == 1
    assert world.oms.writer.records[mark:] == [] and len(world.oms.pager.calls) == pages
