"""E29-T05's acceptance criteria (#848; 24-internal-schemas.md Sec.8.12), one test per Gherkin
scenario, each named in the scenario's own words: the consumer as S8b's runtime composes it, over
the real facade and its in-memory stores (`stream_world`), on a `VirtualTimeLoop`. Each row is
derived in-test from the corpus's docs transcriptions and read by the adapter's own parser:
derived, not evidence (the 2026-10-28 ruling Q1; the recorded rows are E29-K01's, #843). Scenario
8 runs on Postgres (`tests/integration/oms/test_private_stream_replay_pg.py`). Where the binding
contract leaves a clause to E29-T06 (24 Sec.8.12: the reconciliation pass, keeping a foreign
fill), the test proves T05's half (the ruling Q2). No network, no sleeps."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.exchange.base.models import AccountRef, Order, PrivateEvent
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.oms.errors import POST_TERMINAL_PUSH
from candleviewer.oms.stream_push import HANDOVER_BOUND_S
from candleviewer.storage.repositories.orders import NewOrder
from candleviewer.storage.repositories.positions import PositionRow
from tests.unit.audit.audit_waits import virtual
from tests.unit.exchange.bybit._private import linear_execution, linear_order, push, row
from tests.unit.oms.order_rig import T0
from tests.unit.oms.stream_world import (
    FILLS,
    ORDERS,
    REFUSED,
    RESYNCING,
    A,
    B,
    World,
    opened,
    ref,
    xid,
)
from tests.unit.oms.submission_contract import trading_stop

#: The transcribed fill's taker fee rate: a derived fill's fee is this rate of its own value, as
#: B1 bounds a fee by its value (`MAX_FEE_RATE`).
FEE_RATE = Decimal(row("execution")["feeRate"])
#: The recorded stop's TP/SL order (`test_stream_push.STOP`): a Partial stop-loss of a long.
STOP = {
    "stopOrderType": "PartialStopLoss", "tpslMode": "Partial", "triggerPrice": "94000",
    "qty": "0.5", "side": "Sell", "reduceOnly": True, "orderStatus": "Untriggered",
    "timeInForce": "GTC", "orderLinkId": "",
}  # fmt: skip


def parsed(
    topic: str, rows: Sequence[Mapping[str, Any]], account: AccountRef, now_us: int
) -> tuple[PrivateEvent, ...]:
    """The world's `Reader`: one frame of `rows` on `topic`, pushed at `now_us`, as the venue
    sends it, then the adapter's own read of it for the account."""
    frame = push(topic, *map(dict, rows), created=now_us // 1_000)
    pushed = pp.classify(frame)
    assert isinstance(pushed, pp.Push)
    return pp.read_push(pushed, account, now_us=now_us)


def order_row(order: NewOrder, status: str, filled: str = "0", **fields: Any) -> dict[str, Any]:
    """`order`'s row as the stream shows it at `status`, `filled` of it executed (derived)."""
    left = order.qty - Decimal(filled) if status in ("New", "PartiallyFilled") else Decimal(0)
    values: dict[str, Any] = {"orderId": xid(order), "orderLinkId": order.order_link_id}
    values |= {"side": order.side, "orderType": order.order_type, "price": str(order.price)}
    values |= {"qty": str(order.qty), "timeInForce": "GTC", "orderStatus": status}
    values |= {"cumExecQty": filled, "leavesQty": str(left), "createdTime": "1789134000000"}
    return linear_order(**(values | fields))


def fill_row(order: NewOrder, exec_id: str, qty: str, seq: int, **fields: Any) -> dict[str, Any]:
    """A trade fill of `order`, `qty` of it at its price, its fee the transcribed taker rate of
    its own value (derived)."""
    price = Decimal(str(fields.get("execPrice", order.price)))
    fee = format((Decimal(qty) * price * FEE_RATE).normalize(), "f")
    values: dict[str, Any] = {"orderId": xid(order), "orderLinkId": order.order_link_id}
    values |= {"execId": exec_id, "execQty": qty, "execPrice": str(order.price), "seq": seq}
    values |= {"side": order.side, "orderQty": str(order.qty), "orderType": order.order_type}
    values |= {"execFee": fee, "feeRate": str(FEE_RATE), "isMaker": False}
    return linear_execution(**(values | fields))


@virtual
async def test_ws_truth_overrides_the_rest_ack() -> None:
    """Gherkin "WS truth overrides the REST ack": the REST ack moves the order to `submitted`
    only, an acceptance; the stream's fill, then its `Filled` row, finish it. `filled` comes from
    the stream's fill alone, never the ack nor the `Filled` row, which moves nothing (24
    Sec.8.12)."""
    async with opened(parsed) as w:
        order = await w.submitted()
        assert (await w.row(order.id)).lifecycle_state == "submitted"
        acked = await w.events(order.id)
        assert acked[-1] == ("ack", "rest", "accepted")  # an acceptance: `submitted`, no fill
        w.send(FILLS, fill_row(order, "e1", "1", seq=1))
        w.send(ORDERS, order_row(order, "Filled", "1"))
        await w.settle()
        row = await w.row(order.id)
        assert (row.lifecycle_state, row.cum_exec_qty) == ("filled", Decimal(1))
        assert await w.events(order.id) == [*acked, ("fill", "ws_private", "filled")]
        assert w.count("push", "paired") == 1  # the fill; the `Filled` row sends no event


@virtual
async def test_bundled_fills_are_split() -> None:
    """Gherkin "Bundled fills are split": one `execution` push of three fills (derived) is read as
    three events, and each is stored as its own `executions` row, keyed by its own `exec_id`; the
    order's cumulative quantity is their sum."""
    async with opened(parsed) as w:
        order = await w.submitted(qty=Decimal(3))
        rows = [fill_row(order, f"e{n}", "1", seq=n) for n in (1, 2, 3)]
        assert len(w.send(FILLS, *rows)) == 3  # one frame, three events
        await w.settle()
        assert await w.fills("e1", "e2", "e3") == [(f"e{n}", Decimal(1)) for n in (1, 2, 3)]
        row = await w.row(order.id)
        assert (row.cum_exec_qty, row.lifecycle_state) == (Decimal(3), "filled")
        assert w.count("push", "paired") == 3


@virtual
async def test_stream_loss_is_visible_and_triggers_resync() -> None:
    """Gherkin "Stream loss is visible and triggers resync": A's stream reports `down`, then
    nothing for 30 s; B's adapter reports its pongs every 5 s. A alone is shown resyncing on the
    `system` topic and dropped from health; the silence bound ends its session, the 15 s refresh
    subscribes again, and the new stream's `resyncing` requests one reconciliation for A. The pass
    itself is E29-T06's (24 Sec.8.12): its stand-in refuses and pages once (the ruling Q2)."""
    async with opened(parsed, A, B) as w:
        await asyncio.sleep(1)
        w.status("down", "pong_timeout", 1)
        for _ in range(10):  # 50 s
            w.status("heartbeat", "evidence", who=B)
            await asyncio.sleep(5)
        assert w.trace.count(f"subscribe:{A}") == 2 and w.trace.count(f"subscribe:{B}") == 1
        w.status("resyncing", "connected", 1)
        await w.settle()
        assert [(f["reason"], f["exchange_account_ids"]) for f in w.frames] == [
            (RESYNCING, [str(A)])
        ]
        assert w.evidence.count(("ws_dropped", A)) == 2  # the `down`, then the silence
        assert ("ws_dropped", B) not in w.evidence and w.evidence.count(("ws_heartbeat", B)) == 10
        assert w.requests.asked == [(A, "connected")] and w.pages == [REFUSED]
        assert w.consumer.accounts() == {A, B} and w.count("consumer", "silence") == 1


@virtual
async def test_a_duplicate_push_changes_nothing() -> None:
    """Gherkin "A duplicate push changes nothing": the same `execution` frame delivered again,
    with the same `exec_id`, once its fill applied, leaves one `executions` row and the order's
    cumulative quantity as it was: no new event, no lockout and no page."""
    async with opened(parsed) as w:
        order = await w.submitted(qty=Decimal(2))
        fill = fill_row(order, "e1", "1", seq=1)
        w.send(FILLS, fill)
        await w.settle()
        before = (await w.row(order.id), await w.events(order.id))
        assert before[0].cum_exec_qty == Decimal(1)
        w.send(FILLS, fill)  # redelivered
        await w.settle()
        assert (await w.row(order.id), await w.events(order.id)) == before
        assert await w.fills("e1") == [("e1", Decimal(1))]
        assert w.emitted == [] and w.pages == [] and w.out.pager.calls == []


@virtual
async def test_a_push_after_the_order_ended_is_an_anomaly() -> None:
    """Gherkin "A push after the order ended is an anomaly": a `Cancelled` row for an order the
    stream filled leaves the order and its events as they were; the facade writes
    `oms.reconcile_anomaly` (`POST_TERMINAL_PUSH`) and raises an alert, and the push is counted an
    anomaly. A `Filled` or `New` echo maps to no event, so it is no anomaly (the ruling Q5)."""
    async with opened(parsed) as w:
        order = await w.submitted()
        w.send(FILLS, fill_row(order, "e1", "1", seq=1))
        await w.settle()
        before = (await w.row(order.id), await w.events(order.id))
        assert before[0].lifecycle_state == "filled"
        w.send(ORDERS, order_row(order, "Cancelled", "1"))
        await w.settle()
        assert (await w.row(order.id), await w.events(order.id)) == before
        anomalies = [r for r in w.out.audit.records if r.action == "oms.reconcile_anomaly"]
        assert [r.reason for r in anomalies] == [POST_TERMINAL_PUSH]
        assert list(zip(w.out.pager.severities, w.out.pager.calls, strict=True)) == [
            ("alert", "oms_reconcile_anomaly")
        ]
        assert w.count("push", "anomaly") == 1 and w.count("push", "paired") == 1


def foreign(exec_id: str = "eF") -> dict[str, Any]:
    """A trade fill of `xF`, an order of the account that no row is bound to (derived)."""
    values = {"orderId": "xF", "orderLinkId": "", "execId": exec_id, "execQty": "0.2"}
    return linear_execution(**(values | {"side": "Buy", "seq": 9}))


def manual_order(w: World) -> Order:
    """`xF` as the venue's order read shows it: a manual order of the account (derived)."""
    values = {"orderId": "xF", "orderLinkId": "", "side": "Buy", "orderStatus": "Filled"}
    [read] = parsed(ORDERS, [linear_order(**values)], ref(A), w.now_us())
    assert isinstance(read.payload, Order)
    return read.payload


@virtual
async def test_a_fill_with_no_oms_intent_opens_the_accounts_lockout() -> None:
    """Gherkin "A fill with no OMS intent opens the account's lockout": with every order of the
    account bound to its row, a trade fill of an order no row is bound to and no record matches
    opens the shipped stand-in lockout once, keyed by the fill's `exec_id`, within the 5 s
    hand-over bound: `oms.no_intent_detected` (`frozen: false` until E39-T04 #4208, SR-E27-19
    open), then one P1, then the hand-over, which `NoHandoverStore` refuses and counts. Keeping the
    fill for the next pass is E29-T06's (the ruling Q2); a redelivery pages nothing more."""
    async with opened(parsed) as w:
        order = await w.submitted()
        w.venue.seed_order(manual_order(w), uid="100001")
        began = asyncio.get_running_loop().time()
        w.send(FILLS, foreign())
        await w.settle()
        [(action, record)] = w.emitted
        assert action == "oms.no_intent_detected" and record["at"] - began <= HANDOVER_BOUND_S
        assert record["after_state"] == {
            "account_id": str(A), "finding": "execution", "key": "eF",
            "exchange_placed": False, "frozen": False,
        }  # fmt: skip
        assert w.trace[-3:] == ["emit", "page", "handover"]  # the record, the P1, the hand-over
        [(severity, kind, _)] = w.pages
        assert (severity, kind) == ("page", "oms.foreign_order_lockout")
        assert w.interim("foreign_order_lockout") == 1.0
        w.send(FILLS, foreign())  # redelivered: the lockout is open for its key
        await w.settle()
        assert len(w.emitted) == len(w.pages) == 1 and w.trace.count("handover") == 2
        assert (w.count("push", "no_intent"), w.count("push", "handover_unavailable")) == (2, 2)
        assert (await w.row(order.id)).lifecycle_state == "submitted"


@virtual
async def test_a_recorded_stops_order_is_materialised_never_foreign() -> None:
    """Gherkin "A recorded stop's order is materialised, never foreign": the TP/SL order of a stop
    the OMS recorded, which no row is bound to, is materialised as a `recorded_stop` row bound to
    its `orderId`, reduce-only, its record bound, and nothing is sent; its fill applies to that
    row, and no lockout opens."""
    async with opened(parsed) as w:
        values = {"tpsl_mode": "Partial", "size": Decimal("0.5"), "trigger_price": Decimal(94000)}
        [record] = await w.out.store.stops.insert([trading_stop(A, **values)])
        w.send(ORDERS, linear_order(**(STOP | {"orderId": "xS"})))
        await w.settle()
        row = await w.out.orders.get_by_exchange_order_id(A, "xS")
        assert row is not None and row.provenance == "recorded_stop"
        assert (row.reduce_only, row.close_on_trigger, row.intent) == (True, True, "stop_loss")
        bound = await w.out.store.stops.for_exchange_order(A, "xS")
        assert [r.id for r in bound] == [record.id] and w.out.commands.sent == []
        w.send(FILLS, linear_execution(orderId="xS", orderLinkId="", execId="eS", execQty="0.5"))
        await w.settle()
        assert await w.fills("eS") == [("eS", Decimal("0.5"))]
        assert (await w.row(row.id)).cum_exec_qty == Decimal("0.5")
        assert w.emitted == [] and w.pages == [] and w.trace.count("handover") == 0
        assert w.count("push", "stop_materialised") == 1


@virtual
async def test_an_empty_snapshot_is_not_an_empty_account() -> None:
    """Gherkin "An empty snapshot is not an empty account": a stream that reports `resyncing`,
    then only its pongs for 20 s, changes nothing local (the live order, the stored position and
    the live record) and asks one reconciliation pass for the account; the pass is E29-T06's (the
    ruling Q2). It is no `down`: no drop, no notice, no lockout."""
    async with opened(parsed) as w:
        order = await w.submitted()
        await w.out.store.stops.insert([trading_stop(A)])
        key = (A, "BTCUSDT", 0)
        w.book.rows[key] = PositionRow(
            exchange_account_id=A, symbol="BTCUSDT", size=Decimal(1), side="Buy",
            exchange_updated_ts=T0, id=UUID(int=1), recv_ts=T0, updated_at=T0,
        )  # fmt: skip
        before = (await w.row(order.id), await w.events(order.id), dict(w.book.rows))
        live = await w.out.store.stops.live_for_key(*key)
        w.status("resyncing", "reconnected", 2)
        for _ in range(4):  # 20 s of pongs
            await asyncio.sleep(5)
            w.status("heartbeat", "evidence", 2)
        await w.settle()
        after = (await w.row(order.id), await w.events(order.id), dict(w.book.rows))
        assert after == before and await w.out.store.stops.live_for_key(*key) == live
        assert w.requests.asked == [(A, "reconnected")] and w.pages == [REFUSED]
        assert w.frames == [] and w.emitted == [] and w.book.snaps == []
        assert [name for name, _ in w.evidence] == ["ws_heartbeat"] * 4


@virtual
async def test_a_fill_before_its_bind_waits_for_the_bind() -> None:
    """Gherkin "A fill before its bind waits for the bind": the fill of an order whose create was
    sent, its acknowledgement not yet bound, waits in the order's reorder buffer (counted `held`):
    nothing stored, nothing paged. Once the acknowledgement binds the row, it applies; no lockout
    opens."""
    async with opened(parsed) as w:
        order, ack = await w.unacked()
        assert (await w.row(order.id)).exchange_order_id is None
        w.send(FILLS, fill_row(order, "e1", "1", seq=1))
        await w.settle()
        assert w.count("push", "held") == 1 and await w.fills("e1") == []
        assert (await w.row(order.id)).lifecycle_state == "submitting"
        buffer = w.out.facade._orders[order.id].held  # the order's reorder buffer, not B1's
        assert [held.event for held in buffer] == ["EXEC"]
        ack.set()
        await w.settle()
        assert buffer == []
        row = await w.row(order.id)
        assert (row.exchange_order_id, row.cum_exec_qty) == (xid(order), Decimal(1))
        assert await w.fills("e1") == [("e1", Decimal(1))]
        assert w.emitted == [] and w.pages == [] and w.trace.count("handover") == 0
