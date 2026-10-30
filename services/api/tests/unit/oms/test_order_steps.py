"""`oms.order_steps.OrderStepWriter` (E29-T03 #847 slice 5): B1's write-ahead step over the OMS's
repositories, run on the in-memory stores (the Postgres twin is the write-ahead contract's)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from structlog.testing import capture_logs

from candleviewer.oms import ExecutionRepository, OrderRepository
from candleviewer.oms import order_steps as steps
from candleviewer.oms.errors import AnchorTaken, HolderNotRead
from candleviewer.oms.execution import apply_fields
from candleviewer.oms.fakes import InMemoryExecutionStore, InMemoryOrderStore
from candleviewer.oms.order_machine import Legality
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.oms.repository import SubmissionRepository
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.bindings.b01_order import Step
from candleviewer.statechart.config import CV_PERSIST_TIMEOUT
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.executions import NewExecution, OrderFill
from candleviewer.storage.repositories.idempotency_anchors import NewAnchor
from candleviewer.storage.repositories.recorded_stops import (
    REFUSED_BY,
    REFUSED_ENTRY,
    UNSENT_ENTRY,
)
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
)

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
ACCOUNT, ORDER_ID = UUID(int=0xA1), UUID(int=0x01)
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"
CONTEXT: dict[str, Any] = {
    "order_id": str(ORDER_ID), "order_link_id": LINK, "account_id": str(ACCOUNT),
    "symbol": "BTCUSDT", "side": "buy", "qty": "1", "price": "63000", "trigger_price": None,
    "take_profit": None, "stop_loss": "62000", "reduce_only": False, "exchange_order_id": None,
    "filled_qty": "0", "cum_exec_value": "0", "avg_price": None, "fee_paid": "0",
    "reject_code": None,
}  # fmt: skip
EXECUTION = {
    "exec_id": "e1", "exchange_order_id": "x1", "order_id": str(ORDER_ID), "order_link_id": LINK,
    "account_id": str(ACCOUNT), "symbol": "BTCUSDT", "side": "buy", "exec_type": "trade",
    "qty": "0.4", "price": "63000", "fee": "0", "fee_rate": "0.0002", "ts_exec": 1_000_000,
}  # fmt: skip
FILLED = {
    "filled_qty": "0.4",
    "cum_exec_value": "25200",
    "avg_price": "63000",
    "exchange_order_id": "x1",
}


def _step(frm: str | None, to: str, event: str, payload: Any = None, **ctx: Any) -> Step:
    context = CONTEXT | ctx
    return Step(
        order_id=context["order_id"], account_id=context["account_id"], order_link_id=LINK,
        from_state=frm, to_state=to, event=event, payload=payload or {}, context=context,
    )  # fmt: skip


def _order(**over: Any) -> port.NewOrder:
    base: dict[str, Any] = {
        "id": ORDER_ID, "exchange_account_id": ACCOUNT, "order_link_id": LINK,
        "symbol": "BTCUSDT", "side": "Buy", "intent": "entry", "order_type": "Limit",
        "qty": Decimal(1), "price": Decimal(63000), "stop_loss": Decimal(62000),
    }  # fmt: skip
    return port.NewOrder(**base | over)


@pytest.fixture
def db() -> InMemoryOrderStore:
    return InMemoryOrderStore(clock=lambda: T0)


@pytest.fixture
def writer(db: InMemoryOrderStore) -> OrderStepWriter:
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    out = OrderStepWriter(OrderRepository(db), executions, clock=lambda: T0)
    out.expect(_order())
    return out


async def _events(db: InMemoryOrderStore) -> list[tuple[Any, ...]]:
    rows = await db.list_for_order(ACCOUNT, ORDER_ID)
    return [(e.seq, e.kind, e.source, e.from_state, e.to_state, e.ret_code) for e in rows]


async def test_the_first_step_creates_the_registered_order(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """24 Sec.8.4: the row is inserted at `validated`, with the chart state beside `state`."""
    assert await writer(_step(None, "validated", "VALIDATE", {"gates": {}})) == 0
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and (row.state, row.lifecycle_state) == ("pending_submit", "validated")
    assert await _events(db) == [(0, "local_create", "local", None, "pending_submit", None)]
    with pytest.raises(ValueError, match="no registered order"):  # registered once, written once
        await writer(_step(None, "validated", "VALIDATE"))


@pytest.mark.parametrize(
    "over",
    [
        {"qty": "2"}, {"price": None}, {"stop_loss": "61000"}, {"symbol": "ETHUSDT"},
        {"side": "sell"}, {"reduce_only": True}, {"take_profit": "70000"},
    ],
)  # fmt: skip
async def test_a_registered_order_unlike_the_machines_is_refused(
    over: dict[str, Any], writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """The row and the machine agree on the identity and terms, or nothing is written; the
    refused step spends the registration (CR-2A-06), as the facade drops that machine (S7)."""
    with pytest.raises(ValueError, match="not the order the machine holds"):
        await writer(_step(None, "validated", "VALIDATE", **over))
    assert await db.get(ACCOUNT, ORDER_ID) is None
    with pytest.raises(ValueError, match="no registered order"):
        await writer(_step(None, "validated", "VALIDATE"))


@pytest.mark.parametrize(
    ("to", "event"), [("rejected", "VALIDATE"), ("submitted", "SEND"), ("validated", "SEND")]
)
async def test_no_row_without_a_registered_first_step(
    to: str, event: str, db: InMemoryOrderStore
) -> None:
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    bare = OrderStepWriter(OrderRepository(db), executions, clock=lambda: T0)
    with pytest.raises(ValueError, match="no registered order"):
        await bare(_step(None, to, event))
    assert await db.get(ACCOUNT, ORDER_ID) is None


async def test_an_untracked_order_is_created_as_reconciliation_found_it(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """S9: `DISCOVERED` creates the row in `untracked`, by reconciliation, with its exchange id."""
    found: dict[str, Any] = {"order_link_id": "ext-" + "a" * 32, "exchange_order_id": "x7"}
    found["id"] = UUID(int=7)
    writer.expect(_order(**found))
    ctx = {"order_id": str(UUID(int=7)), "exchange_order_id": "x7"}
    step = replace(
        _step(None, "untracked", "DISCOVERED", {"order": {}}, **ctx),
        order_link_id=found["order_link_id"],
    )
    assert await writer(step) == 0
    row = await db.get(ACCOUNT, UUID(int=7))
    assert row is not None and (row.state, row.exchange_order_id) == ("untracked", "x7")
    assert row.provenance == "reconciliation"  # E29-T04: how the row came to exist
    events = await db.list_for_order(ACCOUNT, UUID(int=7))
    assert [(e.kind, e.source) for e in events] == [("adopt", "reconcile")]


@pytest.mark.parametrize(
    ("source", "payload"), [("ws_private", {}), ("reconcile", {"pass_id": "p1"})]
)
async def test_a_recorded_stops_row_is_created_submitted_with_its_bound_id(
    source: str, payload: dict[str, Any], writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """24 Sec.8.3 rule 7: `MATERIALISED`, and only it, creates a row in `submitted`, bound to the
    exchange order id the machine stamped, which the registered order must hold too; its event is
    the exchange fact of the TP/SL order, from the path that met it."""
    stop: dict[str, Any] = {"id": UUID(int=8), "order_link_id": "ext-" + "c" * 32}
    stop |= {"side": "Sell", "intent": "stop_loss", "order_type": "Market", "price": None}
    stop |= {"stop_loss": None, "trigger_price": Decimal(62000), "reduce_only": True}
    writer.expect(_order(**stop, exchange_order_id="x8"))
    ctx: dict[str, Any] = {"order_id": str(UUID(int=8)), "exchange_order_id": "x8", "side": "sell"}
    ctx |= {"price": None, "stop_loss": None, "trigger_price": "62000", "reduce_only": True}
    found = {"order": {}} | payload | ({"source": source} if source == "reconcile" else {})

    def first(event: str, **over: Any) -> Step:
        step = _step(None, "submitted", event, found, **(ctx | over))
        return replace(step, order_link_id=stop["order_link_id"])

    with pytest.raises(ValueError, match="no registered order"):
        await writer(first("SEND"))  # no other trigger creates a `submitted` row
    writer.expect(_order(**stop, exchange_order_id="x8"))  # a refused step spent it (CR-2A-06)
    with pytest.raises(ValueError, match="not the order the machine holds"):
        await writer(first("MATERIALISED", exchange_order_id="x9"))
    writer.expect(_order(**stop, exchange_order_id="x8"))
    assert await writer(first("MATERIALISED")) == 0
    row = await db.get(ACCOUNT, UUID(int=8))
    assert row is not None and (row.state, row.lifecycle_state) == ("accepted", "submitted")
    assert (row.exchange_order_id, row.reduce_only) == ("x8", True)
    events = await db.list_for_order(ACCOUNT, UUID(int=8))
    assert [(e.kind, e.source, e.from_state) for e in events] == [("exchange_push", source, None)]


async def _submitted(writer: OrderStepWriter) -> None:
    await writer(_step(None, "validated", "VALIDATE"))
    await writer(_step("validated", "submitting", "SEND"))
    ack = {"ok": True, "exchange_order_id": "x1"}
    await writer(_step("submitting", "submitted", "done.invoke.place", ack, exchange_order_id="x1"))


async def test_each_step_records_its_kind_source_and_the_bound_id(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """S8, OM-R02, SR-E29-03: the trigger names the event's kind and source, the place ack's id is
    stored with the step that binds it, and `lifecycle_state` follows `state`."""
    await _submitted(writer)
    pushed = {"order_status": "Untriggered", "source": "rest"}
    assert (
        await writer(_step("submitted", "triggered", "TRIGGERED", pushed, exchange_order_id="x1"))
        == 3
    )
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and (row.exchange_order_id, row.lifecycle_state) == ("x1", "triggered")
    assert [e[1:3] for e in await _events(db)] == [
        ("local_create", "local"), ("submit_attempt", "local"), ("ack", "rest"),
        ("exchange_push", "rest"),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("to", "event", "payload", "ctx", "kind", "source", "code"),
    [
        ("rejected", "done.invoke.place", {"ok": False, "error_code": "RATE_LIMITED"},
         {"reject_code": "RATE_LIMITED"}, "reject", "rest", "RATE_LIMITED"),
        ("unknown", "error.platform.place", {"error": "TimeoutError"}, {}, "error", "local", None),
        ("held", "done.invoke.place", {"ok": False, "error_code": "DUPLICATE_CLIENT_ID",
         "lookup": {"exchange_order_id": "x9"}}, {}, "reject", "rest", "DUPLICATE_CLIENT_ID"),
        ("killed", "KILL", {}, {}, "kill", "local", None),
        ("rejected", "RECON_MISS", {"pass_id": "p1"}, {"reject_code": "UNRESOLVED_AFTER_RECONCILE"},
         "reconcile_diff", "reconcile", "UNRESOLVED_AFTER_RECONCILE"),
    ],
)  # fmt: skip
async def test_a_place_result_or_a_kill_is_recorded_as_it_ended(
    to: str,
    event: str,
    payload: dict[str, Any],
    ctx: dict[str, Any],
    kind: str,
    source: str,
    code: str | None,
    writer: OrderStepWriter,
    db: InMemoryOrderStore,
) -> None:
    """A reject's code is stored on the event and in `reject_code`, so a fold rebuilds both."""
    await writer(_step(None, "validated", "VALIDATE"))
    await writer(_step("validated", "submitting", "SEND"))
    await writer(_step("submitting", to, event, payload, **ctx))
    row, last = await db.get(ACCOUNT, ORDER_ID), (await _events(db))[-1]
    assert row is not None and (*last[1:3], last[5]) == (kind, source, code)
    assert row.reject_code == (code if to == "rejected" else None)


async def test_a_fill_commits_with_its_execution(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """S4, S8: the execution, the machine's totals, the state and the fill event, together."""
    await _submitted(writer)
    step = _step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED)
    assert await writer(step) == 3
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and (row.cum_exec_qty, row.avg_price) == (Decimal("0.4"), Decimal(63000))
    assert (await _events(db))[-1][1:3] == ("partial_fill", "ws_private")


async def test_an_exec_the_row_holds_already_finds_the_row_moved_on(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """S4, S7: the machine counted as new an `EXEC` whose execution the row holds
    (a COMMIT that landed after the machine was rebuilt), so the row is ahead of the machine:
    `StaleOrderState`, which rebuilds the machine, never a refusal that leaves it behind. A
    finding that carries a stored execution is still refused as counted twice, with nothing
    written."""
    await _submitted(writer)
    await writer(_step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED))
    before = await _events(db)
    with pytest.raises(port.StaleOrderState):
        await writer(_step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED))
    found = {"exchange_order_id": "x1", "execution": EXECUTION}
    finding = _step("partially_filled", "partially_filled", "RECON_FOUND_PARTIAL", found, **FILLED)
    with pytest.raises(ValueError, match="counted it twice"):
        await writer(finding)
    assert await _events(db) == before


async def test_an_exec_whose_id_another_execution_holds_rebuilds_nothing(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """S4, OM-T04: an `EXEC` that pairs with the order but whose `exec_id` the account holds for
    an execution of no order of this one's is refused with nothing written, never as the row
    moving on (`StaleOrderState`), which would rebuild the machine, and re-attach its stop, on
    every redelivery of the push."""
    await _submitted(writer)
    other = NewExecution(
        exchange_account_id=ACCOUNT, exec_id="e1", symbol="BTCUSDT", side="Buy",
        exec_qty=Decimal("0.4"), exec_price=Decimal(63000), exec_value=Decimal(25200),
        exec_type="Trade", is_maker=False, exec_ts=T0,
    )  # fmt: skip
    assert await InMemoryExecutionStore(db).insert(other)
    before = await _events(db)
    with pytest.raises(ValueError, match="for another order"):
        await writer(_step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED))
    assert await _events(db) == before


async def test_an_exec_whose_holder_is_not_read_in_time_is_refused(
    writer: OrderStepWriter, db: InMemoryOrderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4, C-2.18: the read of which order holds a stored `exec_id` has its own bound,
    `HOLDER_READ_TIMEOUT`, a quarter of the step's `CV_PERSIST_TIMEOUT`: a read that does not
    answer in time refuses the step with nothing written (`HolderNotRead`), never running out the
    step's budget into an outcome in doubt, and never as a refusal of the fill's own data
    (`ValueError`), which a later delivery, when the read answers, may pass."""
    assert steps.HOLDER_READ_TIMEOUT == CV_PERSIST_TIMEOUT / 4
    await _submitted(writer)
    other = NewExecution(
        exchange_account_id=ACCOUNT, exec_id="e1", symbol="BTCUSDT", side="Buy",
        exec_qty=Decimal("0.4"), exec_price=Decimal(63000), exec_value=Decimal(25200),
        exec_type="Trade", is_maker=False, exec_ts=T0,
    )  # fmt: skip
    assert await InMemoryExecutionStore(db).insert(other)
    before = await _events(db)

    async def stalled(_account_id: UUID, _exec_id: str) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(writer._executions, "get", stalled)
    monkeypatch.setattr(steps, "HOLDER_READ_TIMEOUT", 0.0)
    with pytest.raises(HolderNotRead, match="its order was not read") as refused:
        await writer(_step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED))
    assert not isinstance(refused.value, ValueError)
    assert await _events(db) == before


@pytest.mark.parametrize("ts_exec", [253_402_300_800_000_000, 10**30])
async def test_an_execution_time_past_a_datetimes_range_is_refused_as_malformed(
    writer: OrderStepWriter, db: InMemoryOrderStore, ts_exec: int
) -> None:
    """OM-T04: B1's schema bounds `ts_exec`; behind it, a time no `datetime` holds is refused as a
    malformed one is (`ValueError`), never an `OverflowError`, with nothing written."""
    await _submitted(writer)
    before = await _events(db)
    late = EXECUTION | {"ts_exec": ts_exec}
    with pytest.raises(ValueError, match="past the last one a datetime holds"):
        await writer(_step("submitted", "partially_filled", "EXEC", late, **FILLED))
    assert await _events(db) == before


async def test_a_paper_fill_on_a_live_order_is_refused(writer: OrderStepWriter) -> None:
    """C-2.11: the fill's source sets its paper flag; the store refuses one unlike the order's."""
    await _submitted(writer)
    paper = EXECUTION | {"source": "paper"}
    with pytest.raises(port.FillRefused, match="paper_mismatch"):
        await writer(_step("submitted", "partially_filled", "EXEC", paper, **FILLED))


def _plain(value: Decimal) -> str:
    return format(value, "f")


#: An execution's money and time over what B1's closed schema takes (`_DECIMAL`: numeric(38,18)'s
#: 20 and 18 digits; `ts_exec` up to the last instant a `datetime` holds), with a qty and price
#: an order of `_ROOM` absorbs, so the guards admit enough of them; and its `exec_id` and fee
#: currency as text the schema takes (1 to `MAX_TEXT` characters of any kind), control
#: characters included, NUL among them, which no Postgres text column holds.
_MONEY = st.from_regex(b01._DECIMAL, fullmatch=True)
_TEXT = st.text(min_size=1, max_size=b01.MAX_TEXT)
_ADMISSIBLE = st.fixed_dictionaries(
    {
        "qty": st.decimals(min_value=Decimal("0.001"), max_value=1000, places=3).map(_plain),
        "price": st.decimals(min_value=Decimal("0.01"), max_value=10**5, places=2).map(_plain),
        "fee": st.one_of(st.just("0"), _MONEY),
        "fee_rate": st.one_of(st.sampled_from(("0.0002", "-0.0001")), _MONEY),
        "closed_pnl": st.one_of(st.none(), _MONEY),
        "ts_exec": st.integers(min_value=0, max_value=b01.MAX_EXCHANGE_US),
        "exec_id": st.one_of(st.just("e1"), _TEXT),
        "fee_currency": st.one_of(st.just("USDT"), _TEXT),
    }
)
_ROOM = "1000000"
_PLAIN: dict[str, Any] = {"qty": "0.4", "price": "63000", "fee": "0", "fee_rate": "0.0002"}
_PLAIN |= {"closed_pnl": None}
_PLAIN |= {"ts_exec": 1_000_000, "exec_id": "e1", "fee_currency": "USDT"}
_EXEC_SCHEMA = Draft202012Validator(b01.SCHEMAS["EXEC"])


@settings(max_examples=150, deadline=None, derandomize=True)
@given(fields=_ADMISSIBLE)
@example(fields=_PLAIN | {"exec_id": "e\x001"})
@example(fields=_PLAIN | {"fee_currency": "US\x00DT"})
async def test_every_fill_b1_admits_is_one_its_write_ahead_step_stores(
    fields: dict[str, Any],
) -> None:
    """OM-T04, C-2.19: B1's admission (its closed schema, then the EXEC guards over the OMS's
    `apply_execution`) bounds every field `_fill` writes at least as tightly as the `executions`
    row does (`NewExecution`: numeric(38,18), numeric(18,10) for `fee_rate`, and text with no
    NUL). So the store never refuses an admitted fill for its own data, which the machine would
    roll back on every delivery."""
    db = InMemoryOrderStore(clock=lambda: T0)
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    writer = OrderStepWriter(OrderRepository(db), executions, clock=lambda: T0)
    writer.expect(_order(qty=Decimal(_ROOM)))
    await writer(_step(None, "validated", "VALIDATE", qty=_ROOM))
    await writer(_step("validated", "submitting", "SEND", qty=_ROOM))
    ack = {"ok": True, "exchange_order_id": "x1"}
    await writer(_step("submitting", "submitted", "done.invoke.place", ack, qty=_ROOM))
    payload = EXECUTION | fields
    _EXEC_SCHEMA.validate(payload)
    context = CONTEXT | {"qty": _ROOM, "leaves_qty": _ROOM, "exchange_order_id": "x1"}
    context["seen_exec_ids"] = []
    event = SimpleNamespace(type="EXEC", payload=payload)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_core", apply_fields)
        closes = b01.exec_new_and_closes(context, event)
        if not (closes or b01.exec_new_and_partial(context, event)):
            return  # B1's deny arm refuses it, and the facade answers it (OM-T04)
        await b01.apply_fill(None, context, event, None)
    to = "filled" if closes else "partially_filled"
    fill = Step(
        order_id=str(ORDER_ID), account_id=str(ACCOUNT), order_link_id=LINK,
        from_state="submitted", to_state=to, event="EXEC", payload=payload, context=context,
    )  # fmt: skip
    assert await writer(fill) == 3


async def test_a_finding_applies_the_execution_it_carries(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """OM-R02: `RECON_FOUND_PARTIAL` with its execution is a fill, by reconciliation; `filled`
    without one is refused by the store (a fill comes with its execution)."""
    await _submitted(writer)
    await writer(_step("submitted", "unknown", "TRANSPORT_FAULT", exchange_order_id="x1"))
    found = {"exchange_order_id": "x1", "execution": EXECUTION}
    await writer(_step("unknown", "partially_filled", "RECON_FOUND_PARTIAL", found, **FILLED))
    assert (await _events(db))[-1][1:3] == ("partial_fill", "reconcile")
    with pytest.raises(ValueError, match="commit_fill"):
        await writer(_step("partially_filled", "filled", "RECON_FOUND_FILLED", {"pass_id": "p1"}))


@pytest.mark.parametrize(
    "step",
    [
        _step("submitted", "triggered", "NOT_AN_EVENT"),
        _step("submitted", "nowhere", "TRIGGERED"),
        _step("nowhere", "triggered", "TRIGGERED"),
        replace(_step("submitted", "triggered", "TRIGGERED"), order_id="o1"),
        replace(_step("submitted", "triggered", "TRIGGERED"), account_id=None),
        _step("submitted", "partially_filled", "EXEC", EXECUTION | {"ts_exec": -1}, **FILLED),
        _step("submitted", "partially_filled", "EXEC", EXECUTION | {"qty": 0.4}, **FILLED),
    ],
)
async def test_a_malformed_step_writes_nothing(
    step: Step, writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    await _submitted(writer)
    before = await _events(db)
    with pytest.raises(ValueError):
        await writer(step)
    assert await _events(db) == before


def test_the_registry_is_bounded(writer: OrderStepWriter) -> None:
    """C-2.18: orders registered and never written are dropped oldest first."""
    for n in range(steps.MAX_EXPECTED + 1):
        writer.expect(_order(id=UUID(int=1000 + n)))
    assert len(writer._expected) == steps.MAX_EXPECTED
    assert ORDER_ID not in writer._expected


async def test_an_execution_without_its_time_takes_the_steps(
    writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    await _submitted(writer)
    timeless = {k: v for k, v in EXECUTION.items() if k != "ts_exec"}
    await writer(_step("submitted", "partially_filled", "EXEC", timeless, **FILLED))
    stored = await InMemoryExecutionStore(db).get(ACCOUNT, "e1")
    assert stored is not None and stored.exec_ts == T0


@pytest.mark.parametrize(
    ("ok", "stored"), [(True, (Decimal(64000), Decimal(1))), (False, (Decimal(63000), Decimal(1)))]
)
async def test_an_accepted_amend_writes_its_terms(
    ok: bool, stored: tuple[Decimal, Decimal], writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """S2: the row takes an amend's terms only once the exchange accepted them, as the machine
    adopted them; a refused amend writes nothing of its terms."""
    await _submitted(writer)
    await writer(_step("submitted", "amend_pending", "AMEND", {"price": "64000"}))
    result = {"ok": ok, "terms": {"price": "64000"}}
    price = "64000" if ok else "63000"
    await writer(_step("amend_pending", "submitted", "done.invoke.amend", result, price=price))
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and (row.price, row.qty) == stored


PLAN = Path(__file__).resolve().parents[5] / "docs" / "plan"


def _kind_table() -> dict[str, tuple[str, str]]:
    """24 Sec.8.2's "Event kinds" table: trigger -> (kind, source)."""
    text = (PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
    block = text[text.index("**Event kinds (E29-T03") : text.index("**Recovery (E29-T03")]
    rows = re.findall(r"^\| `([\w.]+)` +\| `(\w+)` +\| `(\w+)` +\|$", block, re.M)
    return {trigger: (kind, source) for trigger, kind, source in rows}


def test_each_trigger_is_recorded_with_the_kind_and_source_24_names() -> None:
    """S8, OM-R02: the write-ahead row of every trigger B1 writes records the kind and source
    24 Sec.8.2 names (the `source` label of `oms_state_transitions_total` too); an exchange fact
    with no `source` of its own keeps its default. The table and `_KINDS` name the same
    triggers."""
    table = _kind_table()
    assert set(table) == set(steps._KINDS) and len(table) == 24
    for trigger, want in table.items():
        assert steps.event_kind(_step("submitted", "submitted", trigger)) == want, trigger


@pytest.mark.parametrize(
    ("extra", "source"),
    [({}, "ws_private"), ({"pass_id": "p1", "source": "reconcile"}, "reconcile")],
)
async def test_terms_changed_step_writes_the_terms_with_an_exchange_push_event(
    extra: dict[str, str], source: str, writer: OrderStepWriter, db: InMemoryOrderStore
) -> None:
    """24 Sec.8.3 rule 7, INV-B1-q: a terms step is an `exchange_push` that keeps its state, from
    the path that met it, and writes the terms its push names as the machine took them, and only
    those: a push naming only the trigger price leaves the row's quantity as it was."""
    await _submitted(writer)
    push = {"exchange_order_id": "x1", "trigger_price": "61000", "updated_time": 2} | extra
    ctx = {"exchange_order_id": "x1", "trigger_price": "61000", "qty": "5"}
    await writer(_step("submitted", "submitted", "TERMS_CHANGED", push, **ctx))
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and (row.trigger_price, row.qty) == (Decimal(61000), Decimal(1))
    assert (await _events(db))[-1] == (3, "exchange_push", source, "accepted", "accepted", None)


# -- E29-T04: the first persist, the create's idempotency and the entry's recorded stops ----------


async def _audited(persisted: FirstPersisted) -> None:
    return None  # the pipeline's write-ahead audit (C-2.9, CR-2A-02)


_FIRST = FirstPersist(
    anchor=NewAnchor(id=UUID(int=0xF1), created_by=UUID(int=0xB1), operation="placeOrder",
                     client_ref="9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59", request_sha256="ab" * 32,
                     order_id=ORDER_ID),
    write_ahead=_audited,
)  # fmt: skip


class _Submissions:
    """A `SubmissionStore` that records each first persist and stores its order on `db`."""

    def __init__(self, db: InMemoryOrderStore) -> None:
        self.db, self.calls = db, list[tuple[FirstPersist, port.NewOrder, port.NewOrderEvent]]()

    async def create_first(
        self, first: FirstPersist, order: port.NewOrder, event: port.NewOrderEvent
    ) -> FirstPersisted:
        self.calls.append((first, order, event))
        row = await self.db.create(order, event)
        return FirstPersisted(order=row, anchor_id=first.anchor.id, group=None, recorded_stops=())


async def test_a_registered_first_persist_writes_the_validated_row_through_its_store(
    db: InMemoryOrderStore,
) -> None:
    store = _Submissions(db)
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    writer = OrderStepWriter(
        OrderRepository(db), executions, clock=lambda: T0, submissions=SubmissionRepository(store)
    )
    writer.expect(_order(), first=_FIRST)
    assert await writer(_step(None, "validated", "VALIDATE")) == 0
    [(first, stored, event)] = store.calls
    assert first is _FIRST and (stored.state, stored.lifecycle_state) == (
        "pending_submit",
        "validated",
    )
    assert (stored.provenance, event.kind, event.source) == ("placed", "local_create", "local")
    assert await db.get(ACCOUNT, ORDER_ID) is not None


class _Refusing(_Submissions):
    """A `SubmissionStore` that refuses every first persist, as a held key would."""

    async def create_first(
        self, first: FirstPersist, order: port.NewOrder, event: port.NewOrderEvent
    ) -> FirstPersisted:
        self.calls.append((first, order, event))
        raise AnchorTakenError("ux_ia_principal_ref")


async def test_a_refused_first_persist_spends_its_registration(db: InMemoryOrderStore) -> None:
    """CR-2A-06: the request's key, fingerprint and audit hook leave the writer with the refusal,
    not at its FIFO eviction; a retry registers again."""
    store = _Refusing(db)
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    writer = OrderStepWriter(
        OrderRepository(db), executions, clock=lambda: T0, submissions=SubmissionRepository(store)
    )
    writer.expect(_order(), first=_FIRST)
    with pytest.raises(AnchorTaken):
        await writer(_step(None, "validated", "VALIDATE"))
    assert writer._expected == {} and len(store.calls) == 1
    with pytest.raises(ValueError, match="no registered order"):
        await writer(_step(None, "validated", "VALIDATE"))
    assert len(store.calls) == 1


@pytest.mark.parametrize("to", ["validated", "untracked"])
async def test_a_first_persist_needs_its_store_and_a_validated_row(
    writer: OrderStepWriter, db: InMemoryOrderStore, to: str
) -> None:
    """Without a store (or for an `untracked` row) nothing is written: the persist is refused."""
    writer.expect(_order(), first=_FIRST)
    with pytest.raises(ValueError, match="through its store"):
        await writer(_step(None, to, "VALIDATE" if to == "validated" else "DISCOVERED"))
    assert await db.get(ACCOUNT, ORDER_ID) is None


@pytest.mark.parametrize(
    ("frm", "to", "state"),
    [("validated", "submitting", "in_flight"), ("submitting", "submitted", "acked"),
     ("submitting", "rejected", "failed"), ("submitting", "held", "failed"),
     ("submitting", "unknown", None), ("unknown", "unknown", None),
     ("unknown", "partially_filled", "acked"), ("unknown", "filled", "acked"),
     ("unknown", "cancelled", "acked"), ("unknown", "rejected", "failed"),
     ("unknown", "triggered", "acked"), ("unknown", "expired", "acked"),  # any answer of it
     ("submitted", "partially_filled", None), ("validated", "killed", None)],
)  # fmt: skip
def test_a_step_says_what_became_of_the_create(frm: Any, to: Any, state: str | None) -> None:
    """24 Sec.8.4: in flight from the send, acked or failed by its answer, unchanged otherwise."""
    assert steps.idempotency_of(frm, to) == state


class _Moves(OrderRepository):
    """Records each step's transition, a fill's included, as the write-ahead store gets it."""

    moves: list[port.OrderTransition]

    async def transition(self, step: port.OrderTransition) -> port.CommittedStep:
        self.moves.append(step)
        return await super().transition(step)


async def test_each_step_counts_answers_and_settles_as_e29_t04_says(db: InMemoryOrderStore) -> None:
    orders = _Moves(db)
    orders.moves = []
    fills = InMemoryExecutionStore(db)

    async def commit_fill(fill: OrderFill) -> port.CommittedStep | None:
        orders.moves.append(fill.step)
        return await fills.commit_fill(fill)

    executions = ExecutionRepository(fills)
    executions.commit_fill = commit_fill  # type: ignore[method-assign]  # records the fill's step
    writer = OrderStepWriter(orders, executions, clock=lambda: T0)
    writer.expect(_order())
    await _submitted(writer)
    await writer(_step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED))
    await writer(_step("partially_filled", "cancel_pending", "CANCEL", {}, **FILLED))
    cancelled = {"ok": True, "status": "cancelled"}
    await writer(_step("cancel_pending", "cancelled", "done.invoke.cancel", cancelled, **FILLED))
    got = [(m.idempotency_state, m.bump_submit_attempts, m.entry_stops) for m in orders.moves]
    assert got == [
        ("in_flight", True, None),  # the send
        ("acked", False, "answered"),  # the ack answers the entry's stop request
        (None, False, None),  # a fill of an accepted entry settles nothing more
        (None, False, None),
        (None, False, None),  # a cancel's ack reports no fill: waiting for the complete read
    ]
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and (row.submit_attempts, row.idempotency_state) == (1, "acked")


@pytest.mark.parametrize("reduce_only", [False, True])
async def test_an_entry_refused_unfilled_voids_its_stops_and_a_reduce_only_order_has_none(
    db: InMemoryOrderStore, reduce_only: bool
) -> None:
    orders = _Moves(db)
    orders.moves = []
    writer = OrderStepWriter(
        orders, ExecutionRepository(InMemoryExecutionStore(db)), clock=lambda: T0
    )
    writer.expect(_order(reduce_only=reduce_only))
    ctx = {"reduce_only": reduce_only}
    await writer(_step(None, "validated", "VALIDATE", **ctx))
    await writer(_step("validated", "submitting", "SEND", **ctx))
    said = {"ok": False, "error_code": "RATE_LIMITED"}
    code = {"reject_code": "RATE_LIMITED"}
    await writer(_step("submitting", "rejected", "done.invoke.place", said, **ctx, **code))
    assert [m.entry_stops for m in orders.moves] == [None, None if reduce_only else "void"]


_LIFECYCLE = Legality.of(Registry().get("order"))
_FILLS = frozenset({"partially_filled", "filled"})
#: The exchange's end pushes: the facade holds each until B1 holds every fill it reports
#: (INV-B1-k), and each reports the exchange's own cumulative fill, or omits it.
_END_PUSHES = frozenset({"REMOTE_CANCELLED", "EXPIRE"})
#: Where an entry ends, or is held (B1's final states and `held`).
_ENDS = _LIFECYCLE.finals | {"held"}
#: 21 Sec.3.3.11's table as a (from_state, to_state) matrix (R10, the 2026-10-21 ruling): every B1
#: `lifecycle` edge out of a persisted state, by each of its triggers (a first step settles
#: nothing: `_create`), and what the step does to the entry's pending attach rows (`-`: nothing).
#: The counts are the ones INV-B1-k leaves: B1 holds a fill out of or into a fill state, and an
#: end push reports what B1 holds. `_COUNTS` holds the counts that change an answer.
_MATRIX = """
amend_pending     cancelled         REMOTE_CANCELLED        void
amend_pending     killed            KILL                    waiting
amend_pending     partially_filled  AMEND_REJECTED          answered
amend_pending     partially_filled  done.invoke.amend       answered
amend_pending     submitted         AMEND_REJECTED          answered
amend_pending     submitted         done.invoke.amend       answered
amend_pending     unknown           error.platform.amend    -
cancel_pending    cancelled         REMOTE_CANCELLED        void
cancel_pending    cancelled         done.invoke.cancel      waiting
cancel_pending    filled            EXEC                    answered
cancel_pending    partially_filled  EXEC                    answered
cancel_pending    partially_filled  done.invoke.cancel      answered
cancel_pending    submitted         done.invoke.cancel      answered
cancel_pending    unknown           error.platform.cancel   -
held              rejected          OPERATOR_RESOLVED       waiting
partially_filled  amend_pending     AMEND                   -
partially_filled  cancel_pending    CANCEL                  -
partially_filled  cancelled         REMOTE_CANCELLED        waiting
partially_filled  expired           EXPIRE                  waiting
partially_filled  filled            EXEC                    -
partially_filled  killed            KILL                    waiting
partially_filled  partially_filled  EXEC                    -
partially_filled  partially_filled  TERMS_CHANGED           -
partially_filled  quarantined       FAULT                   -
quarantined       cancelled         RECON_FOUND_CANCELLED   waiting
quarantined       filled            RECON_FOUND_FILLED      answered
quarantined       held              MISMATCH                waiting
quarantined       killed            KILL                    waiting
quarantined       partially_filled  RECON_FOUND_PARTIAL     answered
quarantined       submitted         RECON_FOUND_LIVE        answered
submitted         amend_pending     AMEND                   -
submitted         cancel_pending    CANCEL                  -
submitted         cancelled         REMOTE_CANCELLED        void
submitted         expired           EXPIRE                  void
submitted         filled            EXEC                    -
submitted         held              MISMATCH                waiting
submitted         killed            KILL                    waiting
submitted         partially_filled  EXEC                    -
submitted         quarantined       FAULT                   -
submitted         submitted         TERMS_CHANGED           -
submitted         triggered         TRIGGERED               -
submitted         unknown           TRANSPORT_FAULT         -
submitting        held              done.invoke.place       waiting
submitting        killed            KILL                    waiting
submitting        rejected          done.invoke.place       void
submitting        submitted         done.invoke.place       answered
submitting        unknown           done.invoke.place       -
submitting        unknown           error.platform.place    -
triggered         cancel_pending    CANCEL                  -
triggered         cancelled         REMOTE_CANCELLED        void
triggered         expired           EXPIRE                  void
triggered         filled            EXEC                    -
triggered         killed            KILL                    waiting
triggered         partially_filled  EXEC                    -
triggered         triggered         TERMS_CHANGED           -
unknown           cancelled         RECON_FOUND_CANCELLED   waiting
unknown           filled            RECON_FOUND_FILLED      answered
unknown           held              MISMATCH                waiting
unknown           killed            KILL                    waiting
unknown           partially_filled  RECON_FOUND_PARTIAL     answered
unknown           rejected          RECON_MISS              waiting
unknown           submitted         RECON_FOUND_LIVE        answered
unknown           unknown           RECON_MISS              -
untracked         cancelled         RECON_FOUND_CANCELLED   waiting
untracked         cancelled         RECON_MISS              waiting
untracked         filled            RECON_FOUND_FILLED      answered
untracked         submitted         ADOPT                   answered
untracked         untracked         RECON_MISS              -
validated         killed            KILL                    void
validated         submitting        SEND                    -
"""
_ROWS = [tuple(line.split()) for line in _MATRIX.strip().splitlines()]


def test_the_matrix_is_every_step_b1_takes_out_of_a_persisted_state() -> None:
    """A chart edge or trigger the matrix does not name fails here first."""
    edges = {
        (frm, to, trigger)
        for (frm, to), triggers in _LIFECYCLE.triggers.items()
        for trigger in triggers
        if frm != "draft"
    }
    assert sorted(row[:3] for row in _ROWS) == sorted(edges)


@pytest.mark.parametrize(("frm", "to", "trigger", "effect"), _ROWS)
def test_each_step_does_to_the_entry_stops_what_the_matrix_says(
    frm: Any, to: Any, trigger: str, effect: str
) -> None:
    """Never void an attach row blind (C-2.6): only the exchange confirms an entry unfilled."""
    held = Decimal("0.4") if _FILLS & {frm, to} else Decimal(0)
    pushed = held if trigger in _END_PUSHES else None
    got = steps.entry_stop_settle(frm, to, held, trigger=trigger, reported_fill=pushed)
    assert got == (None if effect == "-" else effect)


#: The matrix's steps whose counts decide, with the counts that change the answer: an end push
#: that reports none (a locally timed expiry among them), one B1 has not caught up with, a zero
#: that a fill B1 holds contradicts, an answer that is no push, a fill B1 holds; and the states no
#: cancel, expiry or refusal is confirmed out of.
_COUNTS: list[tuple[str, str, str, str, str | None, str]] = [
    ("submitted", "cancelled", "REMOTE_CANCELLED", "0", None, "waiting"),
    ("submitted", "cancelled", "REMOTE_CANCELLED", "0", "0.4", "waiting"),
    ("partially_filled", "cancelled", "REMOTE_CANCELLED", "0.4", "0", "waiting"),
    ("amend_pending", "cancelled", "REMOTE_CANCELLED", "0", "0.000", "void"),
    ("cancel_pending", "cancelled", "done.invoke.cancel", "0", "0", "waiting"),
    ("submitted", "expired", "EXPIRE", "0", None, "waiting"),  # a locally timed expiry
    ("submitted", "expired", "EXPIRE", "0", "0.4", "waiting"),
    ("triggered", "expired", "EXPIRE", "0", "0.000", "void"),
    ("unknown", "expired", "EXPIRE", "0", "0", "waiting"),
    ("validated", "killed", "KILL", "0.4", None, "waiting"),
    ("unknown", "cancelled", "RECON_FOUND_CANCELLED", "0.4", None, "waiting"),
    ("unknown", "killed", "KILL", "0.4", None, "waiting"),
    ("submitting", "rejected", "done.invoke.place", "0.4", None, "waiting"),
    ("unknown", "cancelled", "REMOTE_CANCELLED", "0", "0", "waiting"),
    ("quarantined", "cancelled", "REMOTE_CANCELLED", "0", "0", "waiting"),
    ("untracked", "cancelled", "REMOTE_CANCELLED", "0", "0", "waiting"),
    ("unknown", "rejected", "done.invoke.place", "0", None, "waiting"),
]


@pytest.mark.parametrize(("frm", "to", "trigger", "filled", "reported", "effect"), _COUNTS)
def test_b1s_own_count_never_confirms_an_entry_unfilled(
    frm: Any, to: Any, trigger: str, filled: str, reported: str | None, effect: str
) -> None:
    """B1's `filled_qty` can lag a fill the exchange holds back, so its zero voids nothing unless
    the exchange's own answer confirms it, out of a state in which the exchange took the create."""
    told = None if reported is None else Decimal(reported)
    got = steps.entry_stop_settle(frm, to, Decimal(filled), trigger=trigger, reported_fill=told)
    assert got == effect


@pytest.mark.parametrize(
    ("event", "said", "settles"),
    [
        ("REMOTE_CANCELLED", {"cum_exec_qty": "0", "source": "ws_private"}, "void"),
        ("REMOTE_CANCELLED", {"cum_exec_qty": "0.000", "source": "rest"}, "void"),
        ("REMOTE_CANCELLED", {"source": "ws_private"}, None),  # no count reported: waiting
        ("REMOTE_CANCELLED", {"cum_exec_qty": "NaN", "source": "ws_private"}, None),
        ("REMOTE_CANCELLED", {"cum_exec_qty": 0, "source": "ws_private"}, None),  # not text
        ("REMOTE_CANCELLED", {"cum_exec_qty": "nil", "source": "ws_private"}, None),  # no number
        ("done.invoke.cancel", {"ok": True, "cum_exec_qty": "0"}, None),  # an ack is no push
    ],
)
async def test_only_the_exchanges_end_push_confirms_an_unfilled_cancel(
    db: InMemoryOrderStore, event: str, said: dict[str, Any], settles: str | None
) -> None:
    await _cancelled_by(db, event, said, settles)


async def test_a_fill_b1_holds_outweighs_a_pushed_zero(db: InMemoryOrderStore) -> None:
    """The two-source rule: the writer hands B1's own count to the rule, so a push reporting zero
    for an order B1 holds a fill of voids nothing (the rows are that position's stop)."""
    await _cancelled_by(db, "REMOTE_CANCELLED", {"cum_exec_qty": "0"}, None, **FILLED)


async def _cancelled_by(
    db: InMemoryOrderStore, event: str, said: dict[str, Any], settles: str | None, **ctx: Any
) -> None:
    """The writer reads the push's own `cum_exec_qty`, and a step that leaves the rows waiting
    for the complete read names no settle."""
    orders = _Moves(db)
    orders.moves = []
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    writer = OrderStepWriter(orders, executions, clock=lambda: T0)
    writer.expect(_order())
    await _submitted(writer)
    ctx = {"exchange_order_id": "x1", **ctx}
    await writer(_step("submitted", "cancel_pending", "CANCEL", {}, **ctx))
    await writer(_step("cancel_pending", "cancelled", event, said, **ctx))
    assert orders.moves[-1].entry_stops == settles


@pytest.mark.parametrize(
    ("said", "settles"),
    [({"cum_exec_qty": "0", "source": "ws_private"}, "void"),  # the exchange's own zero count
     ({"source": "ws_private"}, None)],  # no exchange count, as a locally timed expiry: it waits
)  # fmt: skip
async def test_an_expiry_voids_its_stops_only_on_the_exchanges_own_zero_count(
    db: InMemoryOrderStore, said: dict[str, Any], settles: str | None
) -> None:
    """The orchestrator's rulings of 14:26Z: `expired` is an exchange-confirmed terminal with zero
    count under the rule `cancelled` takes, and nothing else."""
    orders = _Moves(db)
    orders.moves = []
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    writer = OrderStepWriter(orders, executions, clock=lambda: T0)
    writer.expect(_order())
    await _submitted(writer)
    await writer(_step("submitted", "expired", "EXPIRE", said, exchange_order_id="x1"))
    assert orders.moves[-1].entry_stops == settles


@pytest.mark.parametrize(("sent", "settles"), [(False, "void"), (True, None)])
async def test_a_kill_voids_a_never_sent_entrys_stops_and_after_the_send_waits(
    db: InMemoryOrderStore, sent: bool, settles: str | None
) -> None:
    """The orchestrator's rulings of 14:26Z: a KILL out of `validated` (`abandon`) meets an order
    no request sent, as the send's step commits its attempt first, so its stops are voided; a
    KILL after the send leaves them waiting for the complete read."""
    orders = _Moves(db)
    orders.moves = []
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    writer = OrderStepWriter(orders, executions, clock=lambda: T0)
    writer.expect(_order())
    if sent:
        await _submitted(writer)
    else:
        await writer(_step(None, "validated", "VALIDATE"))
    frm = "submitted" if sent else "validated"
    await writer(_step(frm, "killed", "KILL", {"reason": "kill switch"}))
    assert orders.moves[-1].entry_stops == settles
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and row.state == "killed"


#: One draw: the edge and the trigger to take, whether the exchange fills the sent order unseen
#: before the step, and whether an end push reports its count.
Move = tuple[int, int, bool, bool]


def _moves(*path: tuple[str, str, bool, bool]) -> list[Move]:
    """The draws that walk *path* from `validated`: (target, trigger, held-back fill, reports)."""
    out, state = list[Move](), "validated"
    for target, trigger, hold, reports in path:
        targets = sorted(t for s, t in _LIFECYCLE.edges if s == state)
        triggers = sorted(_LIFECYCLE.triggers[(state, target)])
        out.append((targets.index(target), triggers.index(trigger), hold, reports))
        state = target
    return out


def _swept(
    state: str, attempts: int, idempotency: str, filled: Decimal, events: set[tuple[str, str]]
) -> bool:
    """Whether the startup sweep would void the order's rows now: its statement's EXISTS over the
    order row and the events the steps left (`UNSENT_ENTRY`, or `REFUSED_ENTRY`, `REFUSED_BY`)."""
    row: dict[str, object] = {
        "state": port.ORDER_STATE_OF[cast(Any, state)], "idempotency_state": idempotency,
        "submit_attempts": attempts, "cum_exec_qty": filled,
    }  # fmt: skip

    def holds(proof: Mapping[str, object]) -> bool:
        return all(
            row[name] in value if isinstance(value, frozenset) else row[name] == value
            for name, value in proof.items()
        )

    return holds(UNSENT_ENTRY) or (holds(REFUSED_ENTRY) and REFUSED_BY in events)


_SENT = ("submitting", "SEND", False, False)
_ACK = ("submitted", "done.invoke.place", False, False)


@settings(max_examples=500, deadline=None)
@given(
    moves=st.lists(
        st.tuples(st.integers(0, 1_000), st.integers(0, 1_000), st.booleans(), st.booleans()),
        min_size=1,
        max_size=30,
    )
)
@example(moves=_moves(("killed", "KILL", False, False)))  # never sent, then killed: void
@example(moves=_moves(_SENT, ("killed", "KILL", False, False)))  # killed after the send: waits
@example(moves=_moves(_SENT, _ACK, ("expired", "EXPIRE", False, True)))  # its own zero: void
@example(moves=_moves(_SENT, _ACK, ("expired", "EXPIRE", False, False)))  # no count: waits
@example(moves=_moves(_SENT, ("unknown", "error.platform.place", False, False),
                      ("cancelled", "RECON_FOUND_CANCELLED", False, False)))  # fmt: skip
@example(moves=_moves(_SENT, _ACK, ("cancel_pending", "CANCEL", True, False),
                      ("cancelled", "done.invoke.cancel", False, False)))  # fmt: skip
@example(moves=_moves(_SENT, _ACK, ("cancelled", "REMOTE_CANCELLED", False, True)))
@example(moves=_moves(_SENT, ("rejected", "done.invoke.place", False, False)))
def test_no_entry_stop_is_voided_blind_and_none_outlives_its_order_unsettled(
    moves: list[Move],
) -> None:
    """R10 over B1's lifecycle edges from `validated`: each step's effect is applied as the
    store's `settle_entry_stops_statement` runs it, and the startup sweep's predicate is tried
    after every step, as a restart may come at any point. The claims: a row is voided, by the step
    or the sweep, only while the exchange holds no fill of its entry; a KILL after the send, or
    any end out of `unknown`, leaves every row `pending`, waiting for the complete read, and
    neither the step nor the sweep voids it (the 2026-10-21 ruling); a KILL before the send, and
    an exchange-confirmed terminal with zero count (`cancelled` or `expired` by the exchange's own
    push), void it (the rulings of 14:26Z); and once the order is final, a row is still in flight
    only if its end left it for the complete read.

    What the claims rest on is modelled here, no more: B1's count (`applied`) lags the
    exchange's (`truth`) by the fills the exchange makes unseen once the create is sent, and only
    then, as the send's step commits its attempt before the create can leave (the facade test
    `test_the_attempt_is_committed_before_the_create_leaves` pins that order); an end push
    reports `truth`, or no count (a locally timed expiry), and the facade delivers it only once
    `applied` has caught up (INV-B1-k); a cancel's ack, a KILL and reconciliation's findings
    report no count. An exchange count that is itself wrong is not modelled, nor is the store's
    own check that a void never meets a recorded fill (SEC-2A-01), which the order-store tests
    pin."""
    rows: list[dict[str, Any]] = [
        {"status": "pending", "answered": False} for _ in ("stop_loss", "take_profit")
    ]
    state, applied, truth, attempts, idempotency = "validated", Decimal(0), Decimal(0), 0, "unsent"
    events: set[tuple[str, str]] = set()
    effect: str | None = None
    waits = False
    for pick, how, hold_back, reports in moves:
        targets = sorted(t for s, t in _LIFECYCLE.edges if s == state)
        if state in _LIFECYCLE.finals or not targets:
            break
        if hold_back and attempts:  # the exchange fills the sent order; B1 has not heard of it
            truth += 1
        target = targets[pick % len(targets)]
        triggers = sorted(_LIFECYCLE.triggers[(state, target)])
        trigger = triggers[how % len(triggers)]
        if trigger in _END_PUSHES and truth > applied:
            continue  # INV-B1-k: the facade holds the end until B1 holds every fill it reports
        if (state, target) == ("submitting", "rejected") and truth:
            continue  # the exchange took the create, so its answer refused nothing
        if target in _FILLS:
            applied += 1
            truth = max(truth, applied)
        reported = truth if trigger in _END_PUSHES and reports else None
        effect = steps.entry_stop_settle(
            cast(Any, state), cast(Any, target), applied, trigger=trigger, reported_fill=reported
        )
        assert effect != "void" or truth == 0, "a stop was voided while its entry held a fill"
        for row in (r for r in rows if r["status"] == "pending"):
            if effect == "answered":
                row["answered"] = True
            elif effect == "void":
                row["status"] = "void"
        # The ruling's branch: a KILL after the send, or any end out of `unknown`, waits; a KILL
        # out of `validated` meets an order never sent, as the send's step commits first.
        killed_sent = target == "killed" and state != "validated"
        waits = waits or killed_sent or (state == "unknown" and target in _ENDS)
        if (state, target) == ("validated", "submitting"):
            attempts += 1
        idempotency = steps.idempotency_of(cast(Any, state), cast(Any, target)) or idempotency
        events.add((port.ORDER_STATE_OF[cast(Any, state)], port.ORDER_STATE_OF[cast(Any, target)]))
        state = target
        if waits or truth:  # the ruling's branch, and a fill's: every row is still pending
            assert all(r["status"] == "pending" for r in rows), "a stop was voided blind"
        swept = _swept(state, attempts, idempotency, applied, events)
        assert not (swept and waits), "the sweep would void a stop left for the complete read"
        assert not swept or truth == 0, "the sweep would void the stop of an entry that filled"
    if state in _LIFECYCLE.finals:
        in_flight = [r for r in rows if r["status"] == "pending" and not r["answered"]]
        assert not in_flight or effect == "waiting", "a stop in flight outlived its order"


# -- E29-T13: each committed step reported (`on_commit`) ------------------------------------------


def _reporting(
    db: InMemoryOrderStore, reported: list[steps.CommittedOrderStep], **kw: Any
) -> OrderStepWriter:
    executions = ExecutionRepository(InMemoryExecutionStore(db))
    out = OrderStepWriter(
        OrderRepository(db), executions, clock=lambda: T0, on_commit=reported.append, **kw
    )
    out.expect(_order())
    return out


async def test_each_committed_step_is_reported_with_its_row_a_second_partial_fill_included(
    db: InMemoryOrderStore,
) -> None:
    """E29-T13 (23 Sec.6.2.3): every step whose write committed is reported once, in commit order,
    with the row as it then stands, its kind, the state it left and a fill's execution: a second
    partial fill, which leaves B1's view as it was, is a report of its own (S4)."""
    reported: list[steps.CommittedOrderStep] = []
    writer = _reporting(db, reported)
    await _submitted(writer)
    second = EXECUTION | {"exec_id": "e2", "qty": "0.3"}
    more = {"filled_qty": "0.7", "cum_exec_value": "44100", "avg_price": "63000"}
    await writer(_step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED))
    await writer(_step("partially_filled", "partially_filled", "EXEC", second, **FILLED | more))
    kinds = [(r.kind, r.from_state, r.order.state) for r in reported]
    assert kinds == [
        ("local_create", None, "pending_submit"), ("submit_attempt", "pending_submit", "submitted"),
        ("ack", "submitted", "accepted"), ("partial_fill", "accepted", "partially_filled"),
        ("partial_fill", "partially_filled", "partially_filled"),
    ]  # fmt: skip
    assert [r.order.cum_exec_qty for r in reported[-2:]] == [Decimal("0.4"), Decimal("0.7")]
    assert [None if r.fill is None else r.fill.exec_id for r in reported] == [None] * 3 + [
        "e1",
        "e2",
    ]


async def test_a_step_refused_or_a_duplicate_fill_is_not_reported(db: InMemoryOrderStore) -> None:
    reported: list[steps.CommittedOrderStep] = []
    writer = _reporting(db, reported)
    await _submitted(writer)
    await writer(_step("submitted", "partially_filled", "EXEC", EXECUTION, **FILLED))
    count = len(reported)
    with pytest.raises(port.StaleOrderState):  # the row moved on: nothing committed
        await writer(_step("submitted", "cancel_pending", "CANCEL"))
    with pytest.raises(port.StaleOrderState):  # e1 is stored: S4, nothing committed
        await writer(_step("partially_filled", "partially_filled", "EXEC", EXECUTION, **FILLED))
    assert len(reported) == count


async def test_a_first_persist_is_reported_with_its_row(db: InMemoryOrderStore) -> None:
    reported: list[steps.CommittedOrderStep] = []
    store = _Submissions(db)
    writer = _reporting(db, reported, submissions=SubmissionRepository(store))
    writer.expect(_order(), first=_FIRST)
    await writer(_step(None, "validated", "VALIDATE"))
    [first] = reported
    assert (first.order.id, first.kind, first.from_state) == (ORDER_ID, "local_create", None)


async def test_a_report_that_raises_leaves_the_step_committed(db: InMemoryOrderStore) -> None:
    """The report is the WS topics' view: what it raises is logged by its class and ids, never
    raised into B1's write-ahead step, which has committed (24 Sec.8.2 S7)."""

    def broken(step: steps.CommittedOrderStep) -> None:
        raise RuntimeError("echoed: key abc123")

    writer = OrderStepWriter(
        OrderRepository(db), ExecutionRepository(InMemoryExecutionStore(db)),
        clock=lambda: T0, on_commit=broken,
    )  # fmt: skip
    writer.expect(_order())
    with capture_logs() as logs:
        assert await writer(_step(None, "validated", "VALIDATE")) == 0
    row = await db.get(ACCOUNT, ORDER_ID)
    assert row is not None and row.state == "pending_submit"
    [line] = [entry for entry in logs if entry["event"] == "oms_step_report_failed"]
    assert (line["error"], line["order_id"]) == ("RuntimeError", str(ORDER_ID))
    assert "abc123" not in str(logs)
