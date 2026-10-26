"""A recorded stop's terms on the private stream (E29-T05 #848, S7a; 24-internal-schemas.md Sec.8.12
"Terms, at most one a second" and "A fill before its terms", Sec.8.3 rule 7's sixth item, the
orchestrator's 2026-10-25 rulings Q1 to Q3). `StreamPushes` over the scripted rig and over the real
facade (B1) with the in-memory stores; the pushes come from #4135's transcribed frame shapes
through the adapter's own parser (C-13.5). No network, no sleeps: the rig's clock is advanced."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Order, PrivateEvent
from candleviewer.oms import stop_terms
from candleviewer.oms.errors import OrderStepUnknown, ReconcileAnomaly
from candleviewer.oms.push_mapping import push_time_ms
from candleviewer.oms.stop_terms import PendingTerms, differs, terms_payload
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B
from tests.unit.oms.order_rig import build_rig
from tests.unit.oms.stream_rig import XID, Rig
from tests.unit.oms.test_recorded_stop_stream import ROW_ID, Ports, World
from tests.unit.oms.test_stream_push import STOP, event, order_row

ROW = order_row(
    state="submitted", provenance="recorded_stop", qty=Decimal("0.5"),
    trigger_price=Decimal(94000), cum_exec_qty=Decimal(0),
)  # fmt: skip
_FIELDS = ("state", "provenance", "qty", "trigger_price", "cum_exec_qty", "exchange_order_id")


def _row(**over: Any) -> Any:
    """`ROW` with `over` changed."""
    return order_row(**({f: getattr(ROW, f) for f in _FIELDS} | over))


OTHER = _row(id=UUID(int=2), exchange_order_id="x-other")  # another recorded stop's row


def moved(**over: Any) -> PrivateEvent:
    """The recorded stop's order pushed with `over` changed in place."""
    return event("order", **({"orderId": XID} | STOP | over))


def fill(qty: str) -> PrivateEvent:
    return event("execution", orderId=XID, execQty=qty)


def order(**over: Any) -> Order:
    out = moved(**over).payload
    assert isinstance(out, Order)
    return out


def sent(rig: Rig) -> list[tuple[str, Any, Any]]:
    """Each send's event and the terms its payload names."""
    return [(name, body.get("trigger_price"), body.get("qty")) for _, name, body in rig.pushed]


def stop_rig(row: Any = ROW, shown: Order | None = None) -> Rig:
    """The rig with `row` bound to the order, which a read shows as `shown`."""
    return Rig(answers={"bound": row} | ({} if shown is None else {"order": shown}))


class TwoRows(Rig):
    """`ROW` bound to `XID`, `OTHER` to any other order."""

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> Any:
        self.calls.append("bound")
        return ROW if xid == XID else OTHER


async def flush(rig: Rig, account_id: AccountId = ACCOUNT_A) -> None:
    assert rig._shared is not None
    await rig._shared.flush(account_id)


# --- The terms step (Sec.8.3 rule 7's sixth item) ------------------------------------------------


@pytest.mark.parametrize(
    ("over", "terms"),
    [({"triggerPrice": "93000"}, ("93000", "0.5")), ({"qty": "0.6"}, ("94000", "0.6"))],
    ids=["trigger", "qty"],
)
async def test_terms_changed_sent_for_a_recorded_stop_rows_changed_trigger_or_qty(
    over: dict[str, str], terms: tuple[str, str]
) -> None:
    rig = stop_rig()
    await rig.run(moved(**over))
    [(oid, name, body)] = rig.pushed
    assert (oid, name, rig.counts) == (ROW.id, "TERMS_CHANGED", ["terms"])
    assert body == {
        "exchange_order_id": XID, "order_link_id": ROW.order_link_id, "trigger_price": terms[0],
        "qty": terms[1], "updated_time": body["updated_time"], "source": "ws_private",
    }  # fmt: skip


async def test_terms_unchanged_push_sends_no_terms_step() -> None:
    rig = stop_rig()
    await rig.run(moved())
    assert (rig.pushed, rig.counts) == ([], [])


@pytest.mark.parametrize(
    ("over", "expected"),
    [({}, []), ({"triggerPrice": "93000"}, [("TERMS_CHANGED", "93000", None)])],
    ids=["same_trigger", "trigger_moved"],
)
async def test_full_mode_order_showing_qty_zero_is_never_a_terms_change(
    over: dict[str, str], expected: list[tuple[str, Any, Any]]
) -> None:
    """The S6b review's carry: a Full-mode order shows `qty` 0 and its row takes the position's
    size, so that 0 is no terms change and names no quantity."""
    row = _row(qty=Decimal("0.7"), tpsl_mode="Full")
    rig = stop_rig(row)
    await rig.run(moved(stopOrderType="StopLoss", tpslMode="Full", qty="0", **over))
    assert sent(rig) == expected


def test_terms_payload_stamps_updated_time_from_the_venues_updated_at() -> None:
    """S1's F1: the venue's own time of the order's last change, never the receipt time."""
    shown = order(triggerPrice="93000")
    assert shown.updated_at is not None
    body = terms_payload(shown, ROW, ts_event=shown.updated_at + 9_000_000)
    assert body is not None and body["updated_time"] == shown.updated_at // 1_000


def test_terms_payload_falls_back_to_ts_event_only_without_one() -> None:
    shown = order(triggerPrice="93000").model_copy(update={"updated_at": None})
    body = terms_payload(shown, ROW, ts_event=1_700_000_000_123_456)
    assert body is not None and body["updated_time"] == 1_700_000_000_123
    assert body["updated_time"] == push_time_ms(shown, 1_700_000_000_123_456)


def test_terms_payload_names_no_term_the_order_does_not_show() -> None:
    bare = order(qty="0").model_copy(update={"trigger_price": None})
    assert terms_payload(bare, ROW, ts_event=0) is None and differs(bare, ROW) is False


@pytest.mark.parametrize("status", ["Triggered", "Cancelled"], ids=["trigger", "end"])
async def test_terms_step_goes_before_the_status_event_of_the_same_push(status: str) -> None:
    """Sent at once, never coalesced: any other push of the order goes after its terms."""
    rig = stop_rig()
    await rig.run(moved(triggerPrice="93000"))  # sent: the row's last terms are now recent
    await rig.run(moved(triggerPrice="92000", orderStatus=status))
    event_of = "TRIGGERED" if status == "Triggered" else "REMOTE_CANCELLED"
    assert [name for name, *_ in sent(rig)] == ["TERMS_CHANGED", "TERMS_CHANGED", event_of]
    assert sent(rig)[1][1] == "92000" and "terms_coalesced" not in rig.counts


# --- Coalescing (Q2) -----------------------------------------------------------------------------


async def test_terms_coalesce_to_the_latest_within_the_interval() -> None:
    rig = stop_rig()
    for trigger in ("93000", "92000", "91000"):
        await rig.run(moved(triggerPrice=trigger))
    assert sent(rig) == [("TERMS_CHANGED", "93000", "0.5")]
    assert rig.counts == ["terms", "terms_coalesced", "terms_coalesced"]
    rig.now += stop_terms.TERMS_MIN_INTERVAL_S - 0.001
    await flush(rig)
    assert len(rig.pushed) == 1  # not a second yet: it waits for the next row or heartbeat
    rig.now += 0.001
    await flush(rig)
    assert sent(rig)[1:] == [("TERMS_CHANGED", "91000", "0.5")]  # the latest won
    await flush(rig)
    assert len(rig.pushed) == 2  # a slot is sent once


async def test_pending_terms_flush_before_an_exec_of_that_order() -> None:
    rig = stop_rig()
    await rig.run(moved(triggerPrice="93000"))
    await rig.run(moved(triggerPrice="92000"))
    await rig.run(fill("0.2"))
    assert sent(rig) == [
        ("TERMS_CHANGED", "93000", "0.5"), ("TERMS_CHANGED", "92000", "0.5"),
        ("EXEC", None, "0.2"),
    ]  # fmt: skip
    assert "order" not in rig.calls  # the fill fits the row: no read


@pytest.mark.parametrize("by", ["row", "heartbeat"])
async def test_pending_terms_flush_at_the_accounts_next_row_or_heartbeat(by: str) -> None:
    """`StreamConsumer` calls `flush` at each row and `heartbeat` of the account (its own tests
    pin that); only that account's due slots are sent."""
    rig = stop_rig()
    await rig.run(moved(triggerPrice="93000"))
    await rig.run(moved(triggerPrice="92000"))
    rig.now += stop_terms.TERMS_MIN_INTERVAL_S
    await flush(rig, ACCOUNT_B)
    assert len(rig.pushed) == 1
    await flush(rig)
    assert sent(rig)[1:] == [("TERMS_CHANGED", "92000", "0.5")]


async def test_a_push_showing_the_rows_terms_drops_the_pending_slot() -> None:
    """The latest terms win: when they are the row's again, nothing waits to be sent."""
    rig = stop_rig()
    await rig.run(moved(triggerPrice="93000"))
    await rig.run(moved(triggerPrice="92000"))
    await rig.run(moved())  # the row's own 94000 (the rig's row is the one first read)
    rig.now += stop_terms.TERMS_MIN_INTERVAL_S
    await flush(rig)
    assert len(rig.pushed) == 1


async def test_pending_terms_cap_sends_the_evicted_never_drops_it() -> None:
    rig = TwoRows()
    pushes = rig.streams()
    pushes._pending = PendingTerms(cap=1)
    rig._shared = pushes
    for trigger in ("93000", "92000"):  # each row's first is sent, its second waits
        for xid in (XID, "x-other"):
            await rig.run(moved(triggerPrice=trigger, orderId=xid))
    assert [(oid, body["trigger_price"]) for oid, _, body in rig.pushed] == [
        (ROW.id, "93000"), (OTHER.id, "93000"), (ROW.id, "92000"),
    ]  # fmt: skip
    rig.now += stop_terms.TERMS_MIN_INTERVAL_S
    await flush(rig)
    assert [(oid, body["trigger_price"]) for oid, _, body in rig.pushed[3:]] == [
        (OTHER.id, "92000")
    ]


def test_pending_terms_forgets_sends_past_the_interval_and_the_cap() -> None:
    pending: PendingTerms[str] = PendingTerms(cap=2, sent_cap=2)
    keys = [(ACCOUNT_A, UUID(int=n)) for n in range(3)]
    for n, key in enumerate(keys):
        pending.sent(key, float(n) * 0.1)
    assert pending.offer(keys[0], "a", 0.25) == ("a", None)  # forgotten past the cap
    assert pending.offer(keys[2], "c", 0.25) == (None, None) and len(pending) == 1
    pending.sent(keys[1], 5.0)  # every older send is a second old: forgotten
    assert pending.offer(keys[2], "c2", 5.0) == ("c2", None) and len(pending) == 0
    assert pending.take(keys[2]) is None


# --- A fill before its terms (Q3) ----------------------------------------------------------------


async def test_fill_over_the_rows_quantity_reads_the_order_and_sends_terms_first() -> None:
    rig = stop_rig(shown=order(qty="0.7", orderStatus="Triggered"))
    await rig.run(fill("0.6"))
    assert sent(rig) == [("TERMS_CHANGED", "94000", "0.7"), ("EXEC", None, "0.6")]
    assert rig.calls.count("order") == 1 and rig.counts == ["terms", "paired"]


async def test_fill_over_quantity_after_flushed_pending_terms_reads_nothing() -> None:
    rig = stop_rig()
    await rig.run(moved(triggerPrice="93000"))
    await rig.run(moved(qty="0.7"))
    await rig.run(fill("0.6"))
    assert [q for _, _, q in sent(rig)] == ["0.5", "0.7", "0.6"] and "order" not in rig.calls


@pytest.mark.parametrize(
    "case", ["read_failed", "no_order", "no_larger", "other_order", "terms_refused"]
)
async def test_fill_over_quantity_with_a_failed_read_is_delivered_and_counted(case: str) -> None:
    """A read that fails, or shows no larger quantity (or another order), or terms B1 does not
    take: the fill is delivered anyway, never dropped or held, and counted."""
    shown: Any = {
        "no_order": None, "no_larger": order(qty="0.5"),
        "other_order": order(qty="0.7").model_copy(update={"exchange_order_id": "x-other"}),
    }.get(case, order(qty="0.7"))  # fmt: skip
    rig = stop_rig(shown=shown)
    if case == "read_failed":
        rig.raises["order"] = RuntimeError("x")
    if case == "terms_refused":
        rig.push_errors.append(ReconcileAnomaly("submitted", "TERMS_CHANGED"))
    with capture_logs() as logs:
        await rig.run(fill("0.6"))
    assert [name for name, *_ in sent(rig)][-1] == "EXEC"
    assert "terms_before_fill_unread" in rig.counts and rig.counts[-1] == "paired"
    assert "stream_terms_before_fill_unread" in [e["event"] for e in logs]


async def test_a_terms_send_unknown_twice_is_counted_and_never_sent_a_third_time() -> None:
    rig = stop_rig()
    rig.push_errors += [OrderStepUnknown("TERMS_CHANGED", "x")] * 2
    await rig.run(moved(triggerPrice="93000"))
    assert len(rig.pushed) == 2 and rig.counts == ["unknown_twice"]


@pytest.mark.parametrize("push", ["order", "fill"])
async def test_terms_not_sent_for_a_placed_rows_push(push: str) -> None:
    rig = stop_rig(_row(provenance="placed"), shown=order(qty="0.7"))
    await rig.run(moved(triggerPrice="93000") if push == "order" else fill("0.6"))
    assert [name for name, *_ in sent(rig)] == ([] if push == "order" else ["EXEC"])
    assert "order" not in rig.calls


# --- Through the real facade (B1 version 5) ------------------------------------------------------


@pytest.fixture
async def facade(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = World(build_rig(), Ports())
    yield out
    await out.rig.facade.stop()


async def test_terms_changed_moves_a_materialised_rows_terms_through_the_facade(
    facade: World,
) -> None:
    await facade.record()
    await facade.run(moved())  # materialised and bound
    await facade.run(moved(triggerPrice="93000", qty="0.6"))
    row = await facade.row()
    assert row is not None and (row.id, row.trigger_price, row.qty, row.leaves_qty) == (
        ROW_ID, Decimal(93000), Decimal("0.6"), Decimal("0.6"),
    )  # fmt: skip
    kinds = [e.kind for e in await facade.rig.events.list_for_order(ACCOUNT_A, ROW_ID)]
    assert kinds == ["exchange_push", "exchange_push"]
    assert facade.ports.counts == ["stop_materialised", "terms"]


async def test_terms_to_qty_equal_filled_is_refused_and_recorded_terms_refused(
    facade: World,
) -> None:
    """Q1 (refuse): a push to a quantity equal to the filled one would leave the row nothing to
    fill: B1 keeps the row's last terms and records `terms_refused`, which the facade audits as
    an anomaly; the row is never quarantined, and E29-T06's pass ends it from the venue."""
    await facade.record()
    await facade.run(moved())
    await facade.run(fill("0.2"))
    await facade.run(moved(qty="0.2", orderStatus="PartiallyFilled"))
    await facade.rig.quiet()
    row = await facade.row()
    assert row is not None and (row.qty, row.cum_exec_qty) == (Decimal("0.5"), Decimal("0.2"))
    assert facade.rig.facade.state(ROW_ID) == ("partially_filled", "not_required")
    [record] = [r for r in facade.rig.audit.records if r.reason == "terms_refused"]
    refusal = "the quantity is at or under the filled quantity (INV-1, INV-B1-q)"
    assert record.detail["refusal"] == refusal


async def test_fill_over_the_rows_quantity_applies_after_the_read_terms_through_the_facade(
    facade: World,
) -> None:
    """S1's race end to end: the fill of 0.7 against a row of 0.5 first moves the row to the
    0.7 the order read shows, then applies, so the row fills and nothing is quarantined."""
    await facade.record()
    await facade.run(moved())
    facade.ports.order = order(qty="0.7", orderStatus="Triggered")
    await facade.run(fill("0.7"))
    row = await facade.row()
    assert row is not None and (row.qty, row.cum_exec_qty, row.lifecycle_state) == (
        Decimal("0.7"), Decimal("0.7"), "filled",
    )  # fmt: skip
    assert facade.ports.counts[-2:] == ["terms", "paired"]


async def test_looser_foreign_terms_update_the_row_and_keep_the_records_binding(
    facade: World,
) -> None:
    """C-2.6, LANE-43 ruling (b): a foreign in-place change that loosens the stop is exchange
    truth the row follows; the record keeps its binding and its own terms, so E29-T06's pass
    compares and restores (its half, not this one's)."""
    record = await facade.record()
    await facade.run(moved())
    await facade.run(moved(triggerPrice="90000"))  # further from a long's price: looser
    row = await facade.row()
    assert row is not None and row.trigger_price == Decimal(90000)
    assert await facade.bound() == [record.id]
    kept = await facade.rig.store.stops.for_exchange_order(ACCOUNT_A, XID)
    assert [r.trigger_price for r in kept] == [Decimal(94000)]
