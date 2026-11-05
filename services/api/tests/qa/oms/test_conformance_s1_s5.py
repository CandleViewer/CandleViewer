"""E29-Q02 (#1147, C4a): 24 Sec.8.2's transition rules S1 to S5, driven black-box through the
composed app (`_world.py`). Each scenario is REST requests as the Owner, the frames a `/ws` client
is sent and the rows the stores hold, as the plan's cases state them (the plan is
`docs/qa/e29-oms-test-plan.md`; `e29_q02_cases.txt` maps its E29-TC-nnn to each test and names
the clauses of each case that a row leaves out; the E29-Q02 report lists them). The venue's pushes
are derived in-test from the corpus's docs transcriptions: derived, not evidence. Every order is
an entry and each asserts its native stop (C-2.6): the create the venue receives carries it, the
order and its frames show it, and a filled order's position holds it, its machine's protection
region reading `sl_present`. The frames are read once the world has settled (`Socket.sent`), so a
frame that never comes is a missing item in an assertion, not a wait; a claim that nothing
happened is made of the stream's order: what a client would have been sent comes before the next
thing it is sent. An order a test leaves unresolved keeps its position key, so the two that park
one have a symbol of their own. S6 to S9 are C4b's."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.fakes import FakeReject, LandedThenAmbiguous
from tests.qa.oms._world import (
    ACCOUNT,
    FILLS,
    ORDERS,
    REF,
    T0_US,
    WAIT_S,
    OmsWorld,
    fill_row,
    named,
    order_row,
)

Frames = list[dict[str, Any]]
_BASE_MS = T0_US // 1_000  # the facade's clock, in the ms the venue stamps its rows with
_REFUSED = FakeReject(OmsErrorCode.PRICE_OUT_OF_BOUNDS, exchange_ret_code=110003)
_GONE = FakeReject(OmsErrorCode.ORDER_NOT_FOUND, exchange_ret_code=110001)
_D = Decimal
#: What the order lane records for a post-terminal push and for a fill no order of ours owns.
_ANOMALIES = {"oms.reconcile_anomaly", "oms.no_intent_detected"}


def placed(world: OmsWorld, **over: Any) -> tuple[dict[str, Any], str]:
    """An entry placed over REST, an acceptance (E29-TC-500): resting `accepted` with its stop and
    no fill claimed anywhere, the one create the venue was sent carrying the stop: the order and
    its `ETag`."""
    answer = world.place(**over)
    assert answer.status_code == 202, answer.text
    group = answer.json()["trade_group"]
    [order] = group["legs"][0]["order_details"]
    shown = (group["status"], order["state"], order["lifecycle_state"], order["stop_loss"])
    assert shown == ("submitting", "accepted", "submitted", "58000") and order["filled_qty"] == "0"
    assert order["avg_fill_price"] is None and len(world.creates(order)) == 1  # one create (C-2.6)
    assert _D(world.order(order)["filled_qty"]) == 0 and listed(world, order) == []
    return order, answer.headers["etag"]


def items(frames: Frames, channel: str, order: dict[str, Any]) -> list[dict[str, Any]]:
    """The order's items on `channel`'s deltas (`orders` or `executions`), in the order sent."""
    own = "id" if channel == "orders" else "order_id"
    return [
        item
        for frame in frames
        if frame.get("ch") == channel and frame["t"] == "d"
        for item in frame["p"][channel]
        if item[own] == order["id"]
    ]


def stages(frames: Frames, order: dict[str, Any]) -> list[tuple[str | None, str]]:
    """The order's `orders` frames as (`change`, `state`): a step with no change kind sends none."""
    return [(i.get("change"), i["state"]) for i in items(frames, "orders", order)]


def filled(frames: Frames, order: dict[str, Any]) -> list[str]:
    """`filled_qty` of each of the order's `orders` frames."""
    return [i["filled_qty"] for i in items(frames, "orders", order)]


def exec_ids(frames: Frames, order: dict[str, Any]) -> list[str]:
    """The names of the order's executions on the `executions` frames, in the order sent."""
    return named(order, (item["exec_id"] for item in items(frames, "executions", order)))


def channels(frames: Frames) -> list[str]:
    """The channel of each `orders` and `executions` delta, in the order sent."""
    return [f["ch"] for f in frames if f["t"] == "d" and f["ch"] in ("orders", "executions")]


def kinds(world: OmsWorld, order: dict[str, Any], last: int) -> list[str]:
    """The kinds of the order's last `last` stored steps."""
    return [kind for kind, *_ in world.chain(order)[-last:]]


def listed(world: OmsWorld, order: dict[str, Any]) -> list[str]:
    """`listExecutions`' names of the order's executions, sorted."""
    answer = world.rest("GET", f"/executions?order_id={order['id']}").json()
    return sorted(named(order, (e["exec_id"] for e in answer["items"])))


def anomalies(world: OmsWorld, mark: int) -> list[str]:
    """The anomaly records the order lane wrote after the first `mark` of its audit records."""
    return [a for a, _ in world.oms.writer.records[mark:] if a in _ANOMALIES]


def protection(ws: Any, order: dict[str, Any]) -> str:
    """The order's protection region as its machine's topic shows it to a client."""
    return str(ws.sub(f"machines.order:{order['id']}.state")["regions"]["protection"])


def test_s1_a_create_whose_answer_is_lost_lands_unknown_and_is_never_resent(
    world: OmsWorld,
) -> None:
    """S1, E29-TC-503: the create lands at the venue and its answer is lost. The `202` holds the
    order `unknown` and `reconciling`; the frames and the stored steps end with the transport
    error, a step of the `local` source with no `change` kind; the row is `unknown` after one send
    attempt, bound to no exchange order; the venue received one create, carrying the native stop,
    and no later turn sends a second. Not here: the reconciliation that resolves the order, the
    alert and the retry of a create that never left the process (`e29_q02_cases.txt`)."""
    world.call(world.port.script, "place_order", LandedThenAmbiguous())
    with world.socket("orders") as ws:
        answer = world.place(symbol="ETHUSDT")
        body = answer.json()
        [order] = body["trade_group"]["legs"][0]["order_details"]
        shown = (answer.status_code, order["lifecycle_state"], body["reconciling"])
        assert shown == (202, "unknown", True)
        frames = ws.sent()
    created, sent = ("created", "pending_submit"), ("submitted", "submitted")
    assert stages(frames, order) == [created, sent, (None, "unknown")]
    assert world.chain(order) == [
        ("local_create", "local", "pending_submit"),
        ("submit_attempt", "local", "submitted"),
        ("error", "local", "unknown"),
    ]
    world.settle()
    row = world.row(order)
    held = (row.state, row.lifecycle_state, row.submit_attempts, row.exchange_order_id)
    assert held == ("unknown", "unknown", 1, None)
    assert world.order(order)["state"] == "unknown" and len(world.creates(order)) == 1


def test_s1_a_cancel_the_venue_answers_110001_parks_the_order_unknown_and_is_sent_once(
    world: OmsWorld,
) -> None:
    """S1, E29-TC-104 (b): the venue answers the cancel `110001`, so the order may have ended
    already. `cancelOrder` answers `202` with the order `unknown` and the cancel is never sent
    again. Not here: the reconciliation that then ends the order (E29-TC-600) and the diagnostics
    read."""
    order, _ = placed(world, symbol="SOLUSDT")
    world.call(world.port.script, "cancel_order", _GONE)
    with world.socket("orders") as ws:
        answer = world.cancel(order)
        assert (answer.status_code, answer.json()["lifecycle_state"]) == (202, "unknown")
        frames = ws.sent()
    assert stages(frames, order) == [("cancel", "pending_cancel"), (None, "unknown")]
    assert world.chain(order)[-2][::2] == ("cancel_request", "pending_cancel")
    world.settle()
    cancels = [r for r in world.sent("cancel_order") if r.order_link_id == order["order_link_id"]]
    assert len(cancels) == 1 and world.row(order).state == "unknown"
    assert world.order(order)["state"] == "unknown"


def test_s2_a_refused_amend_leaves_the_prior_order_live_and_unchanged(world: OmsWorld) -> None:
    """S2, E29-TC-452, E29-TC-505 and, server half, E29-TC-102: the venue refuses an amend of price
    and quantity (`110003`). The answer is `502 exchange_error` with the venue's code alone and no
    `ETag`; the order returns to `accepted` at its prior price, quantity and stop, as `getOrder`,
    the stored row, the frames (`change: amend` for the request and for the restoration) and the
    venue's own order show; the amend was written ahead, then denied (read from the order lane's
    writer: `GET /admin/audit` serves the pack's stand-in), and one call was sent. Not here: the
    diagnostics read (`FakeTradingPort` keeps no call record for `exchange_calls[]`)."""
    order, etag = placed(world)
    link = order["order_link_id"]
    world.call(world.port.script, "amend_order", _REFUSED)
    mark = len(world.oms.writer.records)
    with world.socket("orders") as ws:
        answer = world.amend(order, etag, price="60100", qty="0.020")
        problem = answer.json()
        assert (answer.status_code, problem["code"]) == (502, "exchange_error")
        assert problem["exchange"] == {"ret_code": 110003} and "etag" not in answer.headers
        frames = ws.sent()
    assert stages(frames, order) == [("amend", "pending_amend"), ("amend", "accepted")]
    prior = ("60000", "0.01", "58000")
    terms = [(i["price"], i["qty"], i["stop_loss"]) for i in items(frames, "orders", order)]
    assert terms == [prior, prior]
    got, row = world.order(order), world.row(order)
    assert (got["state"], got["lifecycle_state"]) == ("accepted", "submitted")
    held = (row.state, row.price, row.qty, row.stop_loss)
    assert held == ("accepted", _D(60000), _D("0.01"), _D(58000))
    assert [e["kind"] for e in got["events"]][-2:] == ["amend_request", "amend_ack"]
    assert world.chain(order)[-1] == ("amend_ack", "rest", "accepted")
    assert [(a.price, a.qty) for a in world.sent("amend_order") if a.order_link_id == link] == [
        (60100, _D("0.02"))
    ]
    [resting] = [o for o in world.call(world.port.open_orders, REF) if o.order_link_id == link]
    assert (resting.price, resting.qty, resting.stop_loss) == (60000, _D("0.010"), 58000)
    amends = [f for a, f in world.oms.writer.records[mark:] if a == "orders.amend"]
    assert [f["outcome"] for f in amends] == ["success", "denied"]
    assert amends[-1]["reason"] == "exchange_error"


@pytest.mark.parametrize(("qty", "state"), [("0.010", "filled"), ("0.004", "partially_filled")])
def test_s3_a_fill_that_arrives_during_a_cancel_wins_the_race(
    world: OmsWorld, qty: str, state: str
) -> None:
    """S3, E29-TC-451 and E29-TC-104 (a): the venue holds the cancel's answer while a fill arrives
    on the stream. The fill wins, `filled` after a full fill and `partially_filled` after a part.
    `cancelOrder` answers `202`, never `cancelled`: for the full fill with the order `filled`, as
    22 answers an order already final (22 names no answer for a part fill, so that state is read
    from the frames and `getOrder`). An `executions` frame comes before the order's `fill` frame,
    the stored steps end `cancel_request` then the fill, one cancel reached the venue's door and
    none follows it, opening the door afterwards changes nothing, and the native stop is confirmed
    (C-2.6). Not here: a cancel answer that comes later (B1 cuts the held call short) and the
    diagnostics read."""
    order, _ = placed(world)
    door = world.hold("cancel_order")
    with world.socket("orders", "executions") as ws:
        with world.pending(door, world.cancel, order) as cancelling:
            assert world.order(order)["state"] == "pending_cancel"
            world.fill(order, "e1", qty, seq=1)
            door.open()
            answer = cancelling.result(WAIT_S)
        body = answer.json()
        assert answer.status_code == 202 and body["lifecycle_state"] != "cancelled"
        assert state != "filled" or body["lifecycle_state"] == "filled"
        frames = ws.sent()
        assert protection(ws, order) == "sl_present"
    assert stages(frames, order) == [("cancel", "pending_cancel"), ("fill", state)]
    assert channels(frames) == ["orders", "executions", "orders"]
    assert exec_ids(frames, order) == ["e1"]
    assert world.chain(order)[-2][::2] == ("cancel_request", "pending_cancel")
    assert world.chain(order)[-1][1:] == ("ws_private", state)
    row, got = world.row(order), world.order(order)
    assert (row.state, row.cum_exec_qty, row.leaves_qty) == (state, _D(qty), _D("0.010") - _D(qty))
    assert (got["state"], _D(got["filled_qty"])) == (state, _D(qty))
    assert [r.order_link_id for r in door.requests] == [order["order_link_id"]]  # one, none after


def test_s4_a_repeated_exec_id_never_double_counts(world: OmsWorld) -> None:
    """S4, E29-TC-453, E29-TC-553 and, server half, E29-TC-202: an execution is delivered, then
    twice again in the next bundles, then a second one. The repeats are counted nowhere: no frame
    of theirs comes between the first fill's and the second's, no step, no anomaly, no lockout and
    no page; `filled_qty` is 0.004, then 0.006; `getOrder` and `listExecutions` hold each
    `exec_id` once. Not here: a repeat across a reconnect or by REST backfill."""
    order, _ = placed(world)
    with world.socket("orders", "executions") as ws:
        world.fill(order, "e1", "0.004", seq=1)
        steps, pages = len(world.chain(order)), len(world.oms.pager.calls)
        mark = len(world.oms.writer.records)
        for _ in range(2):
            world.fill(order, "e1", "0.004", seq=1)
        assert len(world.chain(order)) == steps
        world.fill(order, "e2", "0.002", seq=2)
        frames = ws.sent()
        assert protection(ws, order) == "sl_present"
    assert exec_ids(frames, order) == ["e1", "e2"]
    assert filled(frames, order) == ["0.004", "0.006"]
    assert stages(frames, order) == [("fill", "partially_filled")] * 2
    row = world.row(order)
    assert (row.state, row.cum_exec_qty) == ("partially_filled", _D("0.006"))
    assert world.fills(order) == ["e1", "e2"]
    assert len(world.oms.pager.calls) == pages and anomalies(world, mark) == []
    assert named(order, (e["exec_id"] for e in world.order(order)["executions"])) == ["e1", "e2"]
    assert listed(world, order) == ["e1", "e2"]


def test_s4_a_bundle_of_fills_is_split_one_row_each_and_a_repeat_adds_none(
    world: OmsWorld,
) -> None:
    """S4, E29-TC-551: one `execution` push of three fills is three `executions` rows, each under
    its own `exec_id`: `listExecutions` lists three, the `executions` topic carries three items
    and `filled_qty` is their sum. The same bundle again adds none: the next fill's frames follow
    the bundle's, and the order is `filled` by the four."""
    order, _ = placed(world)
    row = world.row(order)
    bundle = [fill_row(row, f"b{n}", "0.002", seq=n) for n in (1, 2, 3)]
    pages = len(world.oms.pager.calls)
    with world.socket("orders", "executions") as ws:
        world.venue_position(row, "0.010")
        world.deliver(FILLS, *bundle)
        world.deliver(FILLS, *bundle)
        world.deliver(FILLS, fill_row(row, "b4", "0.004", seq=4))
        frames = ws.sent()
        assert protection(ws, order) == "sl_present"
    ids = ["b1", "b2", "b3", "b4"]
    assert exec_ids(frames, order) == ids and listed(world, order) == ids
    assert filled(frames, order) == ["0.002", "0.004", "0.006", "0.01"]
    assert kinds(world, order, 4) == ["partial_fill"] * 3 + ["fill"]
    assert (world.row(order).state, world.row(order).cum_exec_qty) == ("filled", _D("0.010"))
    assert len(world.oms.pager.calls) == pages  # the repeats raised no page


def test_s5_fills_delivered_before_the_bind_wait_for_it_and_apply_in_order(
    world: OmsWorld,
) -> None:
    """S5, E29-TC-559 and E29-TC-459: the create is at the venue's door, so its order is bound to
    no exchange order yet, and three fills arrive in an order that is neither their time's nor
    their `seq`'s: `e3` at +20 ms (`seq` 4), `e2` at +10 ms (`seq` 6), `e1` at +10 ms (`seq` 5).
    Each waits: stored nowhere, on no REST read, behind no `executions` or fill frame, with no
    page and no lockout. Once the acknowledgement binds the order they apply in `(ts_exec, seq)`
    order, `e1`, `e2`, `e3`, and give the in-order totals; the acknowledgement's frame comes before
    the first fill's. Only fills are driven: a push before the bind is not."""
    door = world.hold("place_order")
    pages, mark = len(world.oms.pager.calls), len(world.oms.writer.records)
    with world.socket("orders", "executions") as ws:
        with world.pending(door, world.place) as placing:
            [create] = door.requests
            row = world.call(world.oms.store.get_by_link_id, ACCOUNT, create.order_link_id)
            assert row.exchange_order_id is None
            unbound = {"id": str(row.id), "order_link_id": row.order_link_id}  # as REST names it
            xid = f"fake-{world.port._next_id + 1:012d}"  # the id the venue will give it
            world.venue_position(row, "0.010")
            for name, ms, seq, qty, price in (  # delivered in this order, applied by (ts_exec, seq)
                ("e3", 20, 4, "0.003", "60300"),
                ("e2", 10, 6, "0.003", "60200"),
                ("e1", 10, 5, "0.004", "60100"),
            ):
                at = str(_BASE_MS + ms)
                late = fill_row(row, name, qty, seq=seq, orderId=xid, execTime=at, execPrice=price)
                world.deliver(FILLS, late)
            waiting = ws.sent()
            assert stages(waiting, unbound) == [
                ("created", "pending_submit"),
                ("submitted", "submitted"),
            ]
            assert exec_ids(waiting, unbound) == [] and world.fills(unbound) == []
            assert _D(world.order(unbound)["filled_qty"]) == 0 and listed(world, unbound) == []
            assert len(world.oms.pager.calls) == pages and anomalies(world, mark) == []
            door.open()
            answer = placing.result(WAIT_S)
        assert answer.status_code == 202
        [order] = answer.json()["trade_group"]["legs"][0]["order_details"]
        frames = [*waiting, *ws.sent()]
        assert protection(ws, order) == "sl_present"
    opened = [("created", "pending_submit"), ("submitted", "submitted"), ("ack", "accepted")]
    assert stages(frames, order)[:3] == opened
    assert channels(frames)[:4] == ["orders"] * 3 + ["executions"]  # no fill before the ack's frame
    assert exec_ids(frames, order) == ["e1", "e2", "e3"]
    assert filled(frames, order)[3:] == ["0.004", "0.007", "0.01"]
    assert kinds(world, order, 3) == ["partial_fill", "partial_fill", "fill"]
    row = world.row(order)
    assert (row.state, row.cum_exec_qty, row.avg_price) == ("filled", _D("0.010"), _D(60_190))
    assert row.exchange_order_id == xid and len(world.creates(order)) == 1
    assert len(world.oms.pager.calls) == pages and anomalies(world, mark) == []  # no lockout


def test_s5_a_stale_push_is_ignored_and_a_fill_never_is(world: OmsWorld) -> None:
    """S5, E29-TC-459: the order took a push stamped +2 s (`Triggered`); an order push stamped
    +1 s (`Cancelled`) arrives after it. It is stale: ignored, no step, no frame, no anomaly. A
    fill stamped +0.5 s, older than both, is applied all the same: its frames come straight
    after the `Triggered` one, and the native stop is confirmed."""
    order, _ = placed(world)
    row = world.row(order)
    mark = len(world.oms.writer.records)
    with world.socket("orders", "executions") as ws:
        world.deliver(ORDERS, order_row(row, "Triggered", updatedTime=str(_BASE_MS + 2_000)))
        world.deliver(ORDERS, order_row(row, "Cancelled", updatedTime=str(_BASE_MS + 1_000)))
        assert world.order(order)["state"] == "triggered"
        world.fill(order, "late", "0.004", seq=1, execTime=str(_BASE_MS + 500))
        frames = ws.sent()
        assert protection(ws, order) == "sl_present"
    assert stages(frames, order) == [(None, "triggered"), ("fill", "partially_filled")]
    assert exec_ids(frames, order) == ["late"]
    assert kinds(world, order, 2) == ["exchange_push", "partial_fill"]
    assert world.row(order).state == "partially_filled"
    assert anomalies(world, mark) == []


def test_s5_a_push_stamped_far_ahead_of_the_clock_does_not_hide_a_later_one(
    world: OmsWorld,
) -> None:
    """S5, E29-TC-459 (step 3): the order took a push stamped ten minutes ahead of the facade's
    clock (`Triggered`). A push stamped more than 60 s ahead moves the order's watermark only to
    that lead, so a `Cancelled` stamped 90 s ahead, older than the first push but past the lead,
    is not stale: it is taken and the order is `cancelled`."""
    order, _ = placed(world)
    row = world.row(order)
    with world.socket("orders") as ws:
        world.deliver(ORDERS, order_row(row, "Triggered", updatedTime=str(_BASE_MS + 600_000)))
        world.deliver(ORDERS, order_row(row, "Cancelled", updatedTime=str(_BASE_MS + 90_000)))
        frames = ws.sent()
    assert [state for _, state in stages(frames, order)] == ["triggered", "cancelled"]
    assert world.order(order)["state"] == "cancelled"


def test_s5_the_rest_ack_only_accepts_and_the_stream_alone_fills(world: OmsWorld) -> None:
    """S5, E29-TC-550 and, client-visible half, E29-TC-500: the REST acknowledgement moves the
    order to `accepted` only (the group `submitting`, no fill, no average price; the create the
    venue was sent carried the stop). The stream's fill finishes it, and the `Filled` order row
    after it moves nothing: one `fill` step and one `orders` frame, after the `executions` one,
    and `getOrder` shows the fill's totals."""
    order, _ = placed(world)
    row = world.row(order)
    assert world.chain(order)[-1] == ("ack", "rest", "accepted")
    with world.socket("orders", "executions") as ws:
        world.fill(order, "full", "0.010", seq=1)
        world.deliver(ORDERS, order_row(row, "Filled", "0.010", updatedTime=str(_BASE_MS + 5_000)))
        frames = ws.sent()
        assert protection(ws, order) == "sl_present"
    assert stages(frames, order) == [("fill", "filled")] and exec_ids(frames, order) == ["full"]
    assert channels(frames) == ["executions", "orders"]
    assert world.chain(order)[-2:] == [
        ("ack", "rest", "accepted"),
        ("fill", "ws_private", "filled"),
    ]
    got = world.order(order)
    fills = (world.row(order).state, got["state"], _D(got["filled_qty"]))
    assert fills == ("filled", "filled", _D("0.010"))
