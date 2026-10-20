"""`oms.order_steps.OrderStepWriter` (E29-T03 #847 slice 5): B1's write-ahead step over the OMS's
repositories, run on the in-memory stores (the Postgres twin is the write-ahead contract's)."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from candleviewer.oms import ExecutionRepository, OrderRepository
from candleviewer.oms import order_steps as steps
from candleviewer.oms.fakes import InMemoryExecutionStore, InMemoryOrderStore
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.statechart.bindings.b01_order import Step
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.executions import NewExecution

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
    """The row and the machine agree on the identity and terms, or nothing is written."""
    with pytest.raises(ValueError, match="not the order the machine holds"):
        await writer(_step(None, "validated", "VALIDATE", **over))
    assert await db.get(ACCOUNT, ORDER_ID) is None
    assert await writer(_step(None, "validated", "VALIDATE")) == 0  # it stays registered


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
    events = await db.list_for_order(ACCOUNT, UUID(int=7))
    assert [(e.kind, e.source) for e in events] == [("adopt", "reconcile")]


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
    assert set(table) == set(steps._KINDS) and len(table) == 22
    for trigger, want in table.items():
        assert steps.event_kind(_step("submitted", "submitted", trigger)) == want, trigger
