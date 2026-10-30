"""The OMS's hand-overs to the next reconciliation pass (E29-T06 #914 PR 1; 24 Sec.8.3 rule 7,
Sec.8.5 steps 2, 3c and 3d): `StoreHandovers` serves the two ports E29-T04 and E29-T05 write
through over the `oms_handovers` store, refuses what it cannot keep as `HandoverUnavailable`, never
silently, and reads the entries back for the pass. It is not bound yet: `NoHandoverStore` stays
the one production binding until E29-T06's wiring."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Execution, Order
from candleviewer.oms.errors import HandoverUnavailable
from candleviewer.oms.handovers import (
    HANDOVER_TIMEOUT_S,
    HandoverRead,
    StoreHandovers,
    WaitingExecution,
    WaitingOrder,
)
from candleviewer.oms.ports import ExecutionHandovers, NoHandoverStore, OrderHandovers
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.oms_handovers import (
    AppendOutcome,
    HandoverKind,
    HandoverRow,
    HandoverStoreFull,
    NewHandover,
)
from candleviewer.storage.repositories.orders import OrderConstraintError

ACCOUNT = AccountId(UUID(int=0xA1))
OTHER = AccountId(UUID(int=0xA2))
_T = datetime(2026, 10, 30, 9, tzinfo=UTC)


def _order(account: UUID = ACCOUNT) -> Order:
    return Order(
        order_link_id="ext-" + "ab" * 16, exchange_order_id="x9", account_id=AccountId(account),
        symbol="BTCUSDT", side="buy", order_type="limit", qty=Decimal("0.010"),
        price=Decimal("60000"), state="new", filled_qty=Decimal(0), leaves_qty=Decimal("0.010"),
        avg_fill_price=None, created_at=1_790_000_000_000_000, terminal_at=None,
    )  # fmt: skip


def _fill(account: UUID = ACCOUNT, exec_id: str = "e1") -> Execution:
    return Execution.model_validate(
        {
            "exec_id": exec_id, "exchange_order_id": "x9", "order_link_id": "ext-" + "ab" * 16,
            "account_id": str(account), "symbol": "BTCUSDT", "side": "buy", "price": "60000",
            "qty": "0.01", "fee": "0.33", "fee_rate": "0.00055", "fee_currency": "USDT",
            "is_maker": False, "exec_type": "trade", "closed_pnl": None,
            "ts_exec": 1_790_000_000_000_000, "ts_ingest": 1_790_000_000_000_100, "seq": 3,
        }
    )  # fmt: skip


@dataclass
class _Store:
    """`OmsHandoverStore` in memory: each append answers *answer*, or raises *fail*, or never
    answers while *hold*; reads answer *rows*."""

    answer: AppendOutcome = "added"
    fail: BaseException | None = None
    hold: bool = False
    rows: tuple[HandoverRow, ...] = ()
    appended: list[NewHandover] = field(default_factory=list)
    calls: list[tuple[str, object, object]] = field(default_factory=list)

    async def append(self, entry: NewHandover) -> AppendOutcome:
        if self.hold:
            await asyncio.Event().wait()
        if self.fail is not None:
            raise self.fail
        self.appended.append(entry)
        return self.answer

    async def pending(self, account_id: UUID, kind: HandoverKind) -> tuple[HandoverRow, ...]:
        self.calls.append(("pending", account_id, kind))
        if self.fail is not None:
            raise self.fail
        return tuple(r for r in self.rows if r.kind == kind)

    async def decide(self, account_id: UUID, exec_id: str) -> bool:
        self.calls.append(("decide", account_id, exec_id))
        return True

    async def prune(self, account_id: UUID, ids: Collection[int]) -> int:
        self.calls.append(("prune", account_id, tuple(ids)))
        return len(set(ids))


def _row(entry_id: int, kind: HandoverKind, record: dict[str, Any], **over: Any) -> HandoverRow:
    values: dict[str, Any] = {
        "id": entry_id, "exchange_account_id": ACCOUNT, "kind": kind,
        "exchange_order_id": record["exchange_order_id"], "exec_id": record.get("exec_id"),
        "source": "ws_private", "record": record, "payload": {}, "empty_reads": 0,
        "first_empty_read_at": None, "decided_at": None, "created_at": _T,
    }  # fmt: skip
    return HandoverRow(**(values | over))


@pytest.mark.parametrize(
    ("port", "name"),
    [(OrderHandovers, "hand_over_order"), (ExecutionHandovers, "hand_over_execution")],
)
def test_it_takes_each_ports_call_as_the_stand_in_does(port: type[Any], name: str) -> None:
    """The binding its wiring will put in place of `NoHandoverStore` takes the same calls."""
    for binding in (StoreHandovers, NoHandoverStore):
        wanted, offered = getattr(port, name), getattr(binding, name)
        assert inspect.iscoroutinefunction(offered)
        shape = [(p.name, p.kind) for p in inspect.signature(wanted).parameters.values()]
        assert [(p.name, p.kind) for p in inspect.signature(offered).parameters.values()] == shape


async def test_an_order_is_kept_as_its_normalised_record_from_its_writer() -> None:
    store = _Store()
    await StoreHandovers(store, source="rest").hand_over_order(ACCOUNT, _order())
    [entry] = store.appended
    assert (entry.kind, entry.exchange_order_id, entry.exec_id, entry.source) == (
        "order", "x9", None, "rest",
    )  # fmt: skip
    assert dict(entry.record) == _order().model_dump(mode="json") and dict(entry.payload) == {}
    assert entry.exchange_account_id == ACCOUNT and entry.empty_read is False


@pytest.mark.parametrize("empty_read", [False, True])
async def test_an_execution_is_kept_by_its_exec_id_its_empty_read_counted(empty_read: bool) -> None:
    store = _Store(answer="counted" if empty_read else "added")
    handovers = StoreHandovers(store, source="ws_private")
    await handovers.hand_over_execution(ACCOUNT, _fill(), empty_read=empty_read)
    [entry] = store.appended
    assert (entry.kind, entry.exec_id, entry.empty_read) == ("execution", "e1", empty_read)
    assert dict(entry.record) == _fill().model_dump(mode="json")


async def test_a_record_of_another_account_is_refused_and_nothing_is_written() -> None:
    """C-2.11: the port names the account; a record naming another is a mix-up, refused fail
    closed and logged, never kept under the wrong account."""
    store = _Store()
    handovers = StoreHandovers(store, source="ws_private")
    with capture_logs() as logs, pytest.raises(HandoverUnavailable):
        await handovers.hand_over_execution(ACCOUNT, _fill(OTHER))
    with pytest.raises(HandoverUnavailable):
        await handovers.hand_over_order(ACCOUNT, _order(OTHER))
    assert store.appended == []
    assert [e["reason"] for e in logs if e["event"] == "oms_handover_refused"] == ["other_account"]


@pytest.mark.parametrize(
    ("fail", "reason"),
    [
        (HandoverStoreFull("the account holds MAX_HANDOVERS_PER_ACCOUNT entries"), "store_full"),
        (StorageTierUnavailable("postgres unreachable (OSError)"), "store_unavailable"),
        (StorageQueryFailed("23514"), "store_unavailable"),
        (OrderConstraintError("oh_record"), "store_unavailable"),
    ],
)
async def test_an_entry_the_store_cannot_keep_is_handover_unavailable(
    fail: BaseException, reason: str
) -> None:
    """21 Sec.3.3.12's overflow policy and an outage alike: never dropped silently, the port's
    `HandoverUnavailable`, which its caller logs and counts (24 Sec.8.12 step 4)."""
    handovers = StoreHandovers(_Store(fail=fail), source="ws_private")
    with capture_logs() as logs, pytest.raises(HandoverUnavailable) as refused:
        await handovers.hand_over_execution(ACCOUNT, _fill())
    assert refused.value.__cause__ is None and "BTCUSDT" not in str(refused.value)
    [entry] = [e for e in logs if e["event"] == "oms_handover_refused"]
    assert (entry["log_level"], entry["reason"], entry["kind"]) == ("error", reason, "execution")


async def test_a_store_that_does_not_answer_in_its_bound_is_handover_unavailable() -> None:
    handovers = StoreHandovers(_Store(hold=True), source="reconcile", timeout_s=0.01)
    with pytest.raises(HandoverUnavailable):
        await handovers.hand_over_order(ACCOUNT, _order())


@pytest.mark.parametrize("bound", [0, -1.0, float("nan"), float("inf"), True])
def test_the_bound_is_a_finite_number_of_seconds_above_zero(bound: Any) -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        StoreHandovers(_Store(), source="rest", timeout_s=bound)
    assert StoreHandovers(_Store(), source="rest")._timeout_s == HANDOVER_TIMEOUT_S


async def test_the_pass_reads_its_orders_and_executions_back_as_their_models() -> None:
    order, fill = _order(), _fill()
    rows = (
        _row(3, "order", order.model_dump(mode="json")),
        _row(5, "execution", fill.model_dump(mode="json"), empty_reads=1, first_empty_read_at=_T),
        _row(6, "execution", _fill(exec_id="e2").model_dump(mode="json"), decided_at=_T),
    )
    handovers = StoreHandovers(_Store(rows=rows), source="reconcile")
    assert await handovers.waiting_orders(ACCOUNT) == HandoverRead((WaitingOrder(3, order),))
    assert await handovers.waiting_executions(ACCOUNT) == HandoverRead(
        (
            WaitingExecution(5, fill, 1, _T, decided=False),
            WaitingExecution(6, _fill(exec_id="e2"), 0, None, decided=True),
        )
    )


async def test_an_unreadable_entry_is_answered_by_its_id_never_ending_the_read() -> None:
    """24 Sec.8.5 (BQ-18): the pass never fails over one row, and an entry that no longer reads is
    surfaced by its id for the report's `errors` (`handover_unreadable`), never its record. The
    entry stays in the table."""
    rows = (
        _row(
            4, "execution", {"account_id": str(ACCOUNT), "exchange_order_id": "x9", "exec_id": "e0"}
        ),
        _row(5, "execution", _fill().model_dump(mode="json")),
    )
    with capture_logs() as logs:
        read = await StoreHandovers(_Store(rows=rows), source="reconcile").waiting_executions(
            ACCOUNT
        )
    assert ([w.entry_id for w in read.entries], read.unreadable) == ([5], (4,))
    [entry] = [e for e in logs if e["event"] == "oms_handover_unreadable"]
    assert (entry["log_level"], entry["entry_id"]) == ("error", 4)
    assert "x9" not in repr(entry) and "e0" not in repr(entry)  # the id alone, never the record


async def test_an_unreadable_order_entry_is_answered_by_its_id() -> None:
    unreadable = {"account_id": str(ACCOUNT), "exchange_order_id": "x7"}
    rows = (_row(7, "order", unreadable), _row(8, "order", _order().model_dump(mode="json")))
    read = await StoreHandovers(_Store(rows=rows), source="reconcile").waiting_orders(ACCOUNT)
    assert ([w.entry_id for w in read.entries], read.unreadable) == ([8], (7,))


async def test_a_read_the_store_cannot_answer_is_handover_unavailable() -> None:
    handovers = StoreHandovers(_Store(fail=StorageTierUnavailable("down")), source="reconcile")
    with pytest.raises(HandoverUnavailable):
        await handovers.waiting_orders(ACCOUNT)


async def test_a_decision_and_a_prune_go_to_the_store_for_the_account() -> None:
    store = _Store()
    handovers = StoreHandovers(store, source="reconcile")
    assert await handovers.decide(ACCOUNT, "e1") is True
    assert await handovers.prune(ACCOUNT, [5, 3]) == 2
    assert store.calls == [("decide", ACCOUNT, "e1"), ("prune", ACCOUNT, (5, 3))]
