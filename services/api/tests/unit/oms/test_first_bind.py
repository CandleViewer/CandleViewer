"""A recorded stop's first bind through the OMS (E29-T05 #848, S6a): the step writer passes a
registered record's bind to the order store only with `MATERIALISED`'s row, and the facade's
`materialise(binds=)` writes the bound row and the record's binding in one transaction (24 Sec.8.3
rule 7), with the record named beside the exchange order id in the step's records (C-2.9). The
stores' own contract is `first_bind_contract.py`."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from decimal import Decimal
from re import fullmatch
from typing import Any, Final
from uuid import UUID

import pytest

from candleviewer.oms import ExecutionRepository, OrderRepository
from candleviewer.oms.errors import OrderStepRefused
from candleviewer.oms.fakes import InMemoryExecutionStore, InMemoryOrderStore
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.bindings.b01_order import Step
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.storage.repositories.exchange_payload import redact_exchange_payload
from candleviewer.storage.repositories.orders import NewOrder, RecordedStopBind
from candleviewer.storage.repositories.recorded_stops import (
    RecordedStopNotBindable,
    RecordedStopRow,
)
from candleviewer.storage.repositories.submissions import FirstPersist
from tests.unit.oms.order_rig import ACCOUNT, T0, Rig, build_rig, order_of
from tests.unit.oms.submission_contract import trading_stop

XID: Final = "1b3c5d7e-9f01-4a23-b456-789abcdef012"  # made up: the shape of an exchange order id
STOP_ID: Final = UUID(int=8)
LINK: Final = f"ext-{XID.replace('-', '')}"


def stop_order(**over: Any) -> NewOrder:
    """The TP/SL order of a recorded stop-loss, as the consumer matched it (24 Sec.8.3 rule 7)."""
    values: dict[str, Any] = {
        "id": STOP_ID, "order_link_id": LINK, "side": "Sell", "intent": "stop_loss",
        "order_type": "Market", "price": None, "stop_loss": None,
        "trigger_price": Decimal(62000), "reduce_only": True, "close_on_trigger": True,
        "exchange_order_id": XID,
    }  # fmt: skip
    return order_of(**values | over)


async def recorded(store: InMemoryOrderStore) -> RecordedStopRow:
    """The account's recorded stop-loss for BTCUSDT 0, in flight."""
    [row] = await store.stops.insert([trading_stop(ACCOUNT, trigger_price=Decimal(62000))])
    return row


def bind_of(row: RecordedStopRow) -> RecordedStopBind:
    return RecordedStopBind(record_id=row.id, kind=row.kind)


def materialised_step(**ctx: Any) -> Step:
    """B1's first step of the stop order's row, as `record_materialised` stamps it."""
    context: dict[str, Any] = {
        "order_id": str(STOP_ID), "account_id": str(ACCOUNT), "symbol": "BTCUSDT",
        "side": "sell", "qty": "1", "price": None, "trigger_price": "62000", "take_profit": None,
        "stop_loss": None, "reduce_only": True, "exchange_order_id": XID,
    }  # fmt: skip
    return Step(
        order_id=str(STOP_ID), account_id=str(ACCOUNT), order_link_id=LINK, from_state=None,
        to_state="submitted", event="MATERIALISED", payload={"order": {}},
        context=context | ctx,
    )  # fmt: skip


@pytest.fixture
def db() -> InMemoryOrderStore:
    return InMemoryOrderStore(clock=lambda: T0)


@pytest.fixture
def writer(db: InMemoryOrderStore) -> OrderStepWriter:
    return OrderStepWriter(
        OrderRepository(db), ExecutionRepository(InMemoryExecutionStore(db)), clock=lambda: T0
    )


# -- the step writer ------------------------------------------------------------------------------


async def test_writer_create_binds_the_registered_record_with_materialiseds_row(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    record = await recorded(db)
    writer.expect(stop_order(), binds=bind_of(record))
    assert await writer(materialised_step()) == 0
    row = await db.get(ACCOUNT, STOP_ID)
    assert row is not None and (row.provenance, row.exchange_order_id) == ("recorded_stop", XID)
    assert [r.id for r in await db.stops.for_exchange_order(ACCOUNT, XID)] == [record.id]


@pytest.mark.parametrize(
    ("to", "event", "over"),
    [
        ("validated", "VALIDATE", {"order_id": str(STOP_ID)}),
        ("untracked", "DISCOVERED", {}),
    ],
    ids=["validated", "untracked"],
)
async def test_writer_create_passes_binds_only_for_materialised(
    writer: OrderStepWriter, db: InMemoryOrderStore, to: str, event: str, over: dict[str, Any]
) -> None:
    """A bind registered with any other first row is a defect: refused before the store, with
    nothing written and the registration spent (CR-2A-06)."""
    record = await recorded(db)
    writer.expect(stop_order(), binds=bind_of(record))
    step = replace(materialised_step(**over), to_state=to, event=event)
    with pytest.raises(ValueError, match="binds with MATERIALISED's row only"):
        await writer(step)
    assert await db.get(ACCOUNT, STOP_ID) is None
    assert await db.stops.for_exchange_order(ACCOUNT, XID) == ()
    with pytest.raises(ValueError, match="no registered order"):
        await writer(materialised_step())


async def test_writer_expect_refuses_a_first_persist_with_a_bind(writer: OrderStepWriter) -> None:
    first = FirstPersist.__new__(FirstPersist)  # never read: refused before it is kept
    binds = RecordedStopBind(record_id=STOP_ID, kind="stop_loss")
    with pytest.raises(ValueError, match="a first persist binds no recorded stop"):
        writer.expect(stop_order(), first=first, binds=binds)


async def test_writer_create_whose_bind_is_refused_writes_nothing(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """A record that holds another order's id binds nothing, and the row is not written either
    (24 Sec.8.2 S7): the facade drops the machine."""
    record = await recorded(db)
    db._stops[record.id] = replace(record, exchange_order_id="another-order")
    writer.expect(stop_order(), binds=bind_of(record))
    with pytest.raises(RecordedStopNotBindable):
        await writer(materialised_step())
    assert await db.get(ACCOUNT, STOP_ID) is None


# -- the facade, its records and C-2.6 -----------------------------------------------------------


def _order_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    """The `order` object a stored `MATERIALISED` payload carries."""
    order = payload["order"]
    assert isinstance(order, Mapping)
    return order


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = build_rig()
    yield out
    await out.facade.stop()


async def test_materialise_with_binds_writes_the_bound_row_and_record(rig: Rig) -> None:
    record = await recorded(rig.store)
    lifecycle = await rig.facade.materialise(
        stop_order(), environment="demo", binds=bind_of(record)
    )
    assert lifecycle == "submitted"
    row = await rig.store.get(ACCOUNT, STOP_ID)
    assert row is not None and (row.lifecycle_state, row.exchange_order_id) == ("submitted", XID)
    [bound] = await rig.store.stops.for_exchange_order(ACCOUNT, XID)
    assert bound.id == record.id


async def test_materialise_whose_bind_is_refused_leaves_no_row_and_no_machine(rig: Rig) -> None:
    """S7: a refused first step drops its machine, so a later materialise of the order may run."""
    record = await recorded(rig.store)
    rig.store._stops[record.id] = replace(record, status="void", closed_at=T0)
    with pytest.raises(OrderStepRefused, match="RecordedStopNotBindable"):
        await rig.facade.materialise(stop_order(), environment="demo", binds=bind_of(record))
    assert await rig.store.get(ACCOUNT, STOP_ID) is None
    assert rig.facade.state(STOP_ID) is None


async def test_materialised_steps_audit_record_carries_the_bound_exchange_order_id(
    rig: Rig,
) -> None:
    """The audit rider (LANE-38, the 21:11Z ruling Q16): the step that binds names the record it
    bound beside the exchange order id, in its machine-event rows and in its first `order_events`
    row, both written ahead (C-2.9)."""
    record = await recorded(rig.store)
    await rig.facade.materialise(stop_order(), environment="demo", binds=bind_of(record))
    sink = rig.facade._ports.sink
    assert isinstance(sink, InMemoryMachineEventSink)
    rows = [r for r in sink.rows if r.event_type == "MATERIALISED"]
    assert {r.phase for r in rows} == {"ahead", "commit"}
    for r in rows:
        assert r.payload["recorded_stop_id"] == str(record.id)
        assert r.payload["order"]["exchange_order_id"] == XID
    [first] = await rig.store.list_for_order(ACCOUNT, STOP_ID)
    assert first.payload["recorded_stop_id"] == str(record.id)
    assert _order_payload(first.payload)["exchange_order_id"] == XID


async def test_materialise_without_binds_names_no_record(rig: Rig) -> None:
    await rig.facade.materialise(stop_order(), environment="demo")
    [plain] = await rig.store.list_for_order(ACCOUNT, STOP_ID)
    assert "recorded_stop_id" not in plain.payload
    assert _order_payload(plain.payload)["exchange_order_id"] == XID


def test_materialised_event_schema_takes_a_recorded_stop_id_as_a_uuid_only() -> None:
    """Q16: an optional key of `MATERIALISED`'s closed schema, no chart change; anything but a
    row id's text is refused at the interpreter."""
    schema = b01.SCHEMAS["MATERIALISED"]
    assert schema["additionalProperties"] is False and "required" not in schema
    pattern = schema["properties"]["recorded_stop_id"]["pattern"]
    an_id = "8f14e45f-ceea-467a-9575-1d2f0e4c8b0a"
    assert fullmatch(pattern, an_id)
    assert not any(fullmatch(pattern, bad) for bad in ("x-1", an_id.upper(), an_id + "0", ""))


async def test_materialised_payload_is_redacted_in_order_events(rig: Rig) -> None:
    """The step's record is its message as the store redacts it (21 Sec.3.3.5): what is stored is
    the redactor's fixed point, and the row ids, in UUID form, pass it unchanged."""
    record = await recorded(rig.store)
    await rig.facade.materialise(stop_order(), environment="demo", binds=bind_of(record))
    [first] = await rig.store.list_for_order(ACCOUNT, STOP_ID)
    stored = dict(first.payload)
    assert stored == redact_exchange_payload(stored)
    assert (stored["recorded_stop_id"], _order_payload(stored)["exchange_order_id"]) == (
        str(record.id), XID,
    )  # fmt: skip


async def test_materialised_row_is_reduce_only_close_on_trigger_and_kill_spares_it(
    rig: Rig,
) -> None:
    """C-2.6, INV-B1-p: the bound row only closes its position, and a KILL never cancels it, so
    the record keeps its binding; a row that is not reduce-only binds nothing."""
    record = await recorded(rig.store)
    with pytest.raises(OrderStepRefused):  # B1 refuses it first, the store would too
        await rig.facade.materialise(
            stop_order(reduce_only=False), environment="demo", binds=bind_of(record)
        )
    assert await rig.store.get(ACCOUNT, STOP_ID) is None
    assert await rig.store.stops.for_exchange_order(ACCOUNT, XID) == ()
    await rig.facade.materialise(stop_order(), environment="demo", binds=bind_of(record))
    row = await rig.store.get(ACCOUNT, STOP_ID)
    assert row is not None and (row.reduce_only, row.close_on_trigger) == (True, True)
    assert await rig.facade.kill("kill switch engaged") == ()
    state = rig.facade.state(STOP_ID)
    assert state is not None and state[0] == "submitted"
    assert [r.id for r in await rig.store.stops.for_exchange_order(ACCOUNT, XID)] == [record.id]
    assert "kill_spared_recorded_stop" in rig.audit.reasons("orders.cancel")


async def test_materialise_by_reconciliation_with_binds_records_its_source(rig: Rig) -> None:
    """E29-T06's path (24 Sec.8.5 step 3c or 3d) binds alike; its first row names the pass."""
    record, run = await recorded(rig.store), "p-1"  # a reconciliation pass's id
    await rig.facade.materialise(
        stop_order(), environment="demo", pass_id=run, binds=bind_of(record)
    )
    [first] = await rig.store.list_for_order(ACCOUNT, STOP_ID)
    assert (first.source, first.payload["pass_id"]) == ("reconcile", run)
    assert first.payload["recorded_stop_id"] == str(record.id)
    assert [r.id for r in await rig.store.stops.for_exchange_order(ACCOUNT, XID)] == [record.id]
