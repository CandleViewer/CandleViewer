"""E29-T13 (#4207): the lane's half of the `orders`, `executions` and `positions` topics
(`oms/ws_topics.py`): the Sec.15 items each row builds, validated against 23-ws-protocol.md's
schemas; the step publisher's causal order (an execution before its order, a position after the
fills of its key, Sec.16.1 S5), its per-account hold and its bounds, each past-the-bound case
counted; the position store's hand-off; and the lane's snapshot reads. Recording doubles, a fake
clock and, for the hold's deadline, virtual time (`audit_waits.virtual`): no network, no sleeps."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.oms import ws_topics as wt
from candleviewer.oms.order_steps import CommittedOrderStep
from candleviewer.oms.ports import PositionKey
from candleviewer.storage.repositories.executions import ExecutionRow, NewExecution
from candleviewer.storage.repositories.orders import OrderEventKind, OrderRow, OrderState
from candleviewer.storage.repositories.positions import PositionRow, PositionState
from tests.unit.audit.audit_waits import virtual
from tests.unit.ws._seq_support import validate

A = UUID("a1000000-0000-4000-8000-000000000001")
B = UUID("a1000000-0000-4000-8000-000000000002")
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
T0_MS = wt.epoch_ms(T0)


def order(n: int = 1, account: UUID = A, **over: Any) -> OrderRow:
    """An `orders` row of `account` (every column; a test overrides what it reads)."""
    values: dict[str, Any] = {
        "id": UUID(int=n), "trade_group_leg_id": None, "exchange_account_id": account,
        "parent_order_id": None, "oco_group_ref": None, "order_link_id": f"cvl-test-{n:04d}",
        "exchange_order_id": f"x{n}", "symbol": "BTCUSDT", "side": "Buy", "intent": "entry",
        "order_type": "Limit", "qty": Decimal("1.000000000000000000"),
        "price": Decimal("63000.000000000000000000"), "trigger_price": None, "trigger_by": None,
        "trigger_direction": None, "take_profit": None, "stop_loss": Decimal("62000"),
        "tpsl_mode": "Full", "time_in_force": "GTC", "reduce_only": False,
        "close_on_trigger": False, "position_idx": 0, "state": "accepted",
        "cum_exec_qty": Decimal(0), "cum_exec_value": Decimal(0), "avg_price": None,
        "leaves_qty": Decimal(1), "fee_paid": Decimal(0), "reject_code": None,
        "reject_message": None, "submit_attempts": 1, "idempotency_state": "acked",
        "created_ts": T0, "submitted_ts": T0, "exchange_created_ts": None,
        "exchange_updated_ts": None, "last_reconciled_at": None, "is_paper": False,
        "lifecycle_state": "submitted", "provenance": "placed",
    }  # fmt: skip
    return OrderRow(**values | over)


def new_fill(exec_id: str = "e1", account: UUID = A, n: int = 1, qty: str = "0.4") -> NewExecution:
    return NewExecution(
        exchange_account_id=account, exec_id=exec_id, symbol="BTCUSDT", side="Buy",
        exec_qty=Decimal(qty), exec_price=Decimal(63000), exec_value=Decimal(qty) * 63000,
        exec_type="Trade", is_maker=False, exec_ts=T0, order_id=UUID(int=n),
        order_link_id=f"cvl-test-{n:04d}", exec_fee=Decimal("5.04"), fee_rate=Decimal("0.0002"),
    )  # fmt: skip


def stored(fill: NewExecution, **over: Any) -> ExecutionRow:
    values = {f.name: getattr(fill, f.name) for f in fields(NewExecution)}
    return ExecutionRow(**values | {"id": UUID(int=0xE0 + len(fill.exec_id)), "recv_ts": T0} | over)


def position(account: UUID = A, size: str = "0.4", **over: Any) -> PositionRow:
    values: dict[str, Any] = {
        "exchange_account_id": account, "symbol": "BTCUSDT", "size": Decimal(size),
        "position_idx": 0, "side": "Buy" if Decimal(size) else "None",
        "avg_price": Decimal(63000), "position_value": Decimal(size) * 63000,
        "leverage": Decimal(10), "mark_price": Decimal(63010), "liq_price": Decimal(57000),
        "unrealised_pnl": Decimal(4), "stop_loss": Decimal(62000), "tpsl_mode": "Full",
        "exchange_updated_ts": T0, "id": UUID(int=0xD0), "recv_ts": T0, "updated_at": T0,
    }  # fmt: skip
    return PositionRow(**values | over)


def step(
    row: OrderRow, kind: str = "ack", left: str | None = "pending_submit", **over: Any
) -> CommittedOrderStep:
    return CommittedOrderStep(
        row, cast(OrderEventKind, kind), cast(OrderState | None, left), **over
    )


def frame(ch: str, body: dict[str, Any]) -> dict[str, Any]:
    """`body` as a structured `d` on `ch`, as the gateway sends it (Sec.7.3), for the validator."""
    return {"t": "d", "ch": ch, "s": 2, "ts": T0_MS, "e": "j", "p": body}


class Topics:
    """The serving half as the lane reaches it: each call recorded, in arrival order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, tuple[Any, ...]]] = []

    def published(self, account: UUID, changes: Any) -> None:
        self.calls.append(("published", account, tuple(changes)))

    def resync(self, account: UUID, families: Any) -> None:
        self.calls.append(("resync", account, tuple(families)))

    def sent(self) -> list[tuple[str, str]]:
        """Each published change as (family, key), in order."""
        return [(c.family, c.key) for kind, _, cs in self.calls if kind == "published" for c in cs]

    def resyncs(self) -> list[tuple[UUID, tuple[str, ...]]]:
        return [(account, fams) for kind, account, fams in self.calls if kind == "resync"]


class Fills:
    """`ExecutionRepository.get` over stored rows; a read can be held (`gate`) or fail."""

    def __init__(self, *rows: ExecutionRow) -> None:
        self.rows = {(r.exchange_account_id, r.exec_id): r for r in rows}
        self.gate: asyncio.Event | None = None
        self.error: BaseException | None = None
        self.reads: list[str] = []

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None:
        self.reads.append(exec_id)
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.rows.get((account_id, exec_id))


class Rig:
    """A step publisher over the recording doubles, its notify a direct call (the serving loop runs
    each in arrival order), its clock the fake `now`, its overtakes counted."""

    def __init__(
        self, *rows: ExecutionRow, kind: type[wt.StepPublisher] = wt.StepPublisher, **bounds: Any
    ) -> None:
        self.now = T0
        self.topics, self.fills, self.overtakes = Topics(), Fills(*rows), 0
        self.held: dict[PositionKey, frozenset[str]] = {}
        self.refuse = False  # the serving loop has closed: each notify raises
        self.uncounted = False  # the counter's registry refuses each sample
        self.publisher = kind(
            self.topics, self._notify, self.fills, environment="demo",
            clock=wt.LaneClock(lambda: self.now), overtaken=self._overtaken, **bounds,
        )  # fmt: skip
        self.publisher.bind(lambda key: self.held.get(key, frozenset()))

    def _notify(self, fn: Callable[..., object], /, *args: Any) -> None:
        if self.refuse:
            raise RuntimeError("the serving loop has closed")
        fn(*args)

    def _overtaken(self) -> None:
        if self.uncounted:
            raise RuntimeError("the registry refused the sample")
        self.overtakes += 1


async def settled() -> None:
    """Until the drains in hand have run (their reads answer at once unless gated)."""
    for _ in range(8):
        await asyncio.sleep(0)


KEY = PositionKey(AccountId(A), "BTCUSDT", 0)


# -- the items ----------------------------------------------------------------------------------


def test_an_order_item_carries_the_rows_columns_and_validates() -> None:
    item = wt.order_item(order(), environment="demo", stamp=T0_MS, change="ack")
    validate(frame("orders", {"orders": [item]}))
    assert (item["side"], item["order_type"], item["state"], item["lifecycle_state"]) == (
        "buy", "limit", "accepted", "submitted"
    )  # fmt: skip
    assert (item["qty"], item["price"], item["filled_qty"]) == ("1", "63000", "0")
    assert (item["change"], item["updated_at_ms"], item["environment"]) == ("ack", T0_MS, "demo")
    assert "trade_group_id" not in item and "algo_kind" not in item  # not on the row


def test_an_order_item_names_its_reject_code_never_the_exchanges_text() -> None:
    row = order(state="rejected", reject_code="PRICE_OUT_OF_BOUNDS", reject_message="echo: key")
    item = wt.order_item(row, environment="live", stamp=T0_MS)
    validate(frame("orders", {"orders": [item], "removed": [item["id"]]}))
    assert item["rejected_reason"] == "PRICE_OUT_OF_BOUNDS"
    assert "echo" not in str(item) and "change" not in item


@pytest.mark.parametrize(("direction", "shown"), [(1, "rise"), (2, "fall"), (None, None)])
def test_a_trigger_direction_reads_as_rise_or_fall(direction: int | None, shown: str) -> None:
    row = order(trigger_price=Decimal(64000), trigger_by="MarkPrice", trigger_direction=direction)
    item = wt.order_item(row, environment="demo", stamp=T0_MS)
    validate(frame("orders", {"orders": [item]}))
    assert (item["trigger_direction"], item["trigger_by"]) == (shown, "MarkPrice")


def test_an_execution_item_is_the_stored_row_and_validates() -> None:
    row = stored(new_fill(), closed_pnl=Decimal("-1.5"))
    item = wt.execution_item(row, environment="demo")
    assert item is not None
    validate(frame("executions", {"executions": [item]}))
    assert (item["id"], item["order_id"], item["exec_id"]) == (str(row.id), str(UUID(int=1)), "e1")
    assert (item["exec_qty"], item["fee"], item["fee_rate"], item["exec_pnl"]) == (
        "0.4", "5.04", "0.0002", "-1.5"
    )  # fmt: skip
    assert item["ts_ms"] == T0_MS


@pytest.mark.parametrize(
    "over", [{"order_id": None}, {"exec_type": "SessionSettlePnl"}], ids=["no_order", "type"]
)
def test_an_execution_no_frame_carries_has_no_item(over: dict[str, Any]) -> None:
    assert wt.execution_item(stored(new_fill(), **over), environment="demo") is None


@pytest.mark.parametrize(
    ("over", "side"),
    [({}, "long"), ({"side": "Sell"}, "short"), ({"size": Decimal(0), "side": "None"}, "flat")],
)
def test_a_position_item_validates_with_its_side(over: dict[str, Any], side: str) -> None:
    item = wt.position_item(position(**over), environment="demo", stamp=T0_MS)
    validate(frame("positions", {"positions": [item]}))
    assert item["side"] == side
    assert "native_stop_present" not in item and "margin_mode" not in item  # the row cannot tell


def test_a_position_item_leaves_out_an_amount_the_row_lacks() -> None:
    item = wt.position_item(position(avg_price=None, leverage=None), environment="demo", stamp=1)
    validate(frame("positions", {"positions": [item]}))
    assert "avg_price" not in item and "leverage" not in item and item["liq_price"] == "57000"


@pytest.mark.parametrize(
    ("kind", "left", "state", "change"),
    [
        ("local_create", None, "pending_submit", "created"),
        ("submit_attempt", "pending_submit", "submitted", "submitted"),
        ("partial_fill", "accepted", "partially_filled", "fill"),
        ("kill", "accepted", "killed", "cancel"),
        ("adopt", None, "untracked", "reconcile"),
        ("exchange_push", None, "accepted", "created"),  # a recorded stop's order, materialised
        ("exchange_push", "accepted", "cancelled", "cancel"),  # REMOTE_CANCELLED
        ("exchange_push", "accepted", "accepted", "amend"),  # a terms step
        ("exchange_push", "accepted", "triggered", None),  # TRIGGERED
        ("error", "submitted", "unknown", None),
    ],
)
def test_the_change_follows_the_steps_kind_and_states(
    kind: str, left: str | None, state: str, change: str | None
) -> None:
    assert wt.change_of(step(order(state=state), kind, left)) == change


def test_the_lane_clock_never_goes_back() -> None:
    now = [T0]
    clock = wt.LaneClock(lambda: now[0])
    first = clock()
    now[0] = T0 - timedelta(seconds=5)  # the wall clock stepped back
    assert clock() == first == T0_MS
    now[0] = T0 + timedelta(milliseconds=7)
    assert clock() == T0_MS + 7


# -- the order steps ----------------------------------------------------------------------------


async def test_a_step_with_no_fill_is_published_at_once_with_its_stamp() -> None:
    rig = Rig()
    rig.publisher.committed(step(order()))
    [(kind, account, (change,))] = rig.topics.calls
    assert (kind, account, change.family, change.key) == (
        "published",
        A,
        "orders",
        str(UUID(int=1)),
    )
    assert (change.stamp, change.item["updated_at_ms"], change.closed) == (T0_MS, T0_MS, False)
    assert rig.fills.reads == []


async def test_a_fill_publishes_its_execution_before_its_order() -> None:
    """Sec.16.1 S5: the fill's execution, read back for its `id`, goes before its order's step, in
    one call, so the serving loop publishes them back to back."""
    fill = new_fill()
    rig = Rig(stored(fill))
    filled = order(state="partially_filled", cum_exec_qty=Decimal("0.4"), leaves_qty=Decimal("0.6"))
    rig.publisher.committed(step(filled, "partial_fill", "accepted", fill=fill))
    await settled()
    [(_, _, changes)] = rig.topics.calls
    assert [c.family for c in changes] == ["executions", "orders"]
    execution, moved = changes
    assert execution.item["id"] == str(stored(fill).id) and moved.item["change"] == "fill"
    assert execution.stamp == moved.stamp == T0_MS


async def test_an_accounts_later_steps_wait_behind_its_fills_read_in_commit_order() -> None:
    fill = new_fill()
    rig = Rig(stored(fill))
    rig.fills.gate = asyncio.Event()
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
    rig.publisher.committed(step(order(state="pending_cancel"), "cancel_request", "accepted"))
    rig.publisher.committed(step(order(2, account=B), "ack"))  # another account: not held
    await settled()
    assert rig.topics.sent() == [("orders", str(UUID(int=2)))]
    rig.fills.gate.set()
    await settled()
    assert [f for f, _ in rig.topics.sent()] == ["orders", "executions", "orders", "orders"]
    moved = [c for _, _, cs in rig.topics.calls[1:] for c in cs if c.family == "orders"]
    assert [c.item["state"] for c in moved] == ["partially_filled", "pending_cancel"]


@pytest.mark.parametrize(
    "fault", ["raises", "missing", "another_order", "another_account"], ids=str
)
async def test_a_fill_whose_row_is_unread_goes_alone_and_resyncs_executions(fault: str) -> None:
    fill = new_fill()
    rows = {
        "raises": stored(fill), "missing": None,
        "another_order": stored(fill, order_id=UUID(int=9)),
        "another_account": stored(fill, exchange_account_id=B),
    }  # fmt: skip
    rig = Rig(*([r] if (r := rows[fault]) is not None else []))
    if fault == "another_account":
        rig.fills.rows = {(A, "e1"): stored(fill, exchange_account_id=B)}
    if fault == "raises":
        rig.fills.error = ConnectionError("echoed: key abc123")
    with capture_logs() as logs:
        rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
        await settled()
    assert rig.topics.sent() == [("orders", str(UUID(int=1)))]
    assert rig.topics.resyncs() == [(A, ("executions",))]
    [line] = [e for e in logs if e["event"] == "oms_ws_fill_unread"]
    assert line["exec_id"] == "e1" and "abc123" not in str(line)  # its class only (C-12.6)


@virtual
async def test_a_fill_read_past_its_bound_goes_alone() -> None:
    fill = new_fill()
    rig = Rig(stored(fill))
    rig.fills.gate = asyncio.Event()  # never answers
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
    await asyncio.sleep(wt.FILL_READ_S + 0.01)
    assert rig.topics.sent() == [("orders", str(UUID(int=1)))]
    assert rig.topics.resyncs() == [(A, ("executions",))]


async def test_a_full_queue_drops_the_account_and_resyncs_its_three_topics() -> None:
    """C-2.18: one step past `QUEUE_MAX` behind a pending read drops the account's queue and its
    holds and re-snapshots its three topics; nothing it held is published afterwards."""
    fill = new_fill()
    rig = Rig(stored(fill), queue_max=2)
    rig.fills.gate = asyncio.Event()
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
    rig.publisher.position(position())  # held behind the fill
    rig.publisher.committed(step(order(state="pending_cancel"), "cancel_request", "accepted"))
    with capture_logs() as logs:
        rig.publisher.committed(step(order(state="cancelled"), "cancel_ack", "pending_cancel"))
    assert rig.topics.resyncs() == [(A, ("executions", "orders", "positions"))]
    rig.fills.gate.set()
    await settled()
    assert rig.topics.sent() == [] and rig.overtakes == 0
    assert [e["event"] for e in logs] == ["oms_ws_queue_full"]
    rig.publisher.committed(step(order(), "ack"))  # the account starts again, at once
    assert rig.topics.sent() == [("orders", str(UUID(int=1)))]


async def test_a_raising_notify_is_contained() -> None:
    rig = Rig()
    rig.refuse = True
    with capture_logs() as logs:
        rig.publisher.committed(step(order()))
        rig.publisher.position(position())
    assert [e["event"] for e in logs] == ["oms_ws_notify_failed", "oms_ws_notify_failed"]


async def test_a_closed_publisher_takes_nothing_and_cancels_its_drains() -> None:
    fill = new_fill()
    rig = Rig(stored(fill))
    rig.fills.gate = asyncio.Event()
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
    await settled()
    await rig.publisher.aclose()
    rig.publisher.committed(step(order()))
    rig.publisher.position(position())
    rig.fills.gate.set()
    await settled()
    assert rig.topics.calls == []


# -- the positions and their hold ---------------------------------------------------------------


async def test_a_position_with_no_unpublished_fill_is_published_at_once() -> None:
    rig = Rig()
    rig.publisher.position(position())
    assert rig.topics.sent() == [("positions", str(UUID(int=0xD0)))] and rig.overtakes == 0


async def test_a_flat_position_is_a_closed_change() -> None:
    rig = Rig()
    rig.publisher.position(position(size="0"))
    [(_, _, (change,))] = rig.topics.calls
    assert change.closed and change.item["side"] == "flat"


async def test_edge_case_a_position_push_before_its_order_push_within_the_bound() -> None:
    """Gherkin "Edge case - a position push before its order push", within the hold bound: the
    position of a key whose fill is committed and awaiting its read waits in the account's hold,
    then follows that fill's execution and order, uncounted."""
    fill = new_fill()
    rig = Rig(stored(fill))
    rig.fills.gate = asyncio.Event()
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
    rig.publisher.position(position())
    await settled()
    assert rig.topics.sent() == []  # held behind the fill's read
    rig.fills.gate.set()
    await settled()
    assert [f for f, _ in rig.topics.sent()] == ["executions", "orders", "positions"]
    assert rig.overtakes == 0


async def test_a_position_waits_for_a_fill_the_facade_holds_before_its_bind() -> None:
    """The EXEC that arrived before its order's REST ack waits in the facade's reorder buffer
    (`held_fills`); the position its venue pushed next waits for it, then follows its frames."""
    fill = new_fill()
    rig = Rig(stored(fill))
    rig.held[KEY] = frozenset({"e1"})
    rig.publisher.position(position())
    assert rig.topics.sent() == []
    rig.held.clear()  # the bind releases the EXEC: its step commits
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
    await settled()
    assert [f for f, _ in rig.topics.sent()] == ["executions", "orders", "positions"]
    assert rig.overtakes == 0


async def test_a_position_of_another_key_is_not_held() -> None:
    fill = new_fill()
    rig = Rig(stored(fill))
    rig.fills.gate = asyncio.Event()
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fill))
    rig.publisher.position(position(symbol="ETHUSDT", id=UUID(int=0xD1)))
    rig.publisher.position(position(position_idx=1, id=UUID(int=0xD2)))
    rig.publisher.position(position(account=B, id=UUID(int=0xD3)))
    assert [k for _, k in rig.topics.sent()] == [str(UUID(int=n)) for n in (0xD1, 0xD2, 0xD3)]


@virtual
async def test_edge_case_a_position_push_before_its_order_push_past_the_bound() -> None:
    """Gherkin "Edge case - a position push before its order push", past the bound: the position
    still waiting at `HOLD_S` leaves then, before its fill, and the overtake is counted."""
    fill = new_fill()
    rig = Rig(stored(fill))
    rig.held[KEY] = frozenset({"e1"})  # the fill never commits
    rig.publisher.position(position())
    await asyncio.sleep(wt.HOLD_S - 0.01)
    assert rig.topics.sent() == []
    with capture_logs() as logs:
        await asyncio.sleep(0.02)
    assert rig.topics.sent() == [("positions", str(UUID(int=0xD0)))] and rig.overtakes == 1
    [line] = [e for e in logs if e["event"] == "oms_ws_position_overtake"]
    assert (line["account_id"], line["symbol"], line["reason"]) == (
        str(A), "BTCUSDT", "hold_expired"
    )  # fmt: skip


@virtual
async def test_a_held_keys_later_row_replaces_it_and_keeps_the_first_deadline() -> None:
    rig = Rig()
    rig.held[KEY] = frozenset({"e1"})
    rig.publisher.position(position(size="0.4"))
    await asyncio.sleep(wt.HOLD_S / 2)
    rig.held[KEY] = frozenset({"e2"})
    rig.publisher.position(position(size="0.7"))
    await asyncio.sleep(wt.HOLD_S / 2 + 0.01)  # the first row's deadline
    [(_, _, (change,))] = rig.topics.calls
    assert change.item["size"] == "0.7" and rig.overtakes == 1


async def test_a_held_key_leaves_only_once_every_fill_it_awaits_is_out() -> None:
    fills = (new_fill("e1"), new_fill("e2", qty="0.3"))
    rig = Rig(*(stored(f) for f in fills))
    rig.fills.gate = asyncio.Event()
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fills[0]))
    rig.held[KEY] = frozenset({"e2"})  # the second waits for its bind
    rig.publisher.position(position(size="0.7"))
    rig.fills.gate.set()
    await settled()
    assert [f for f, _ in rig.topics.sent()] == ["executions", "orders"]  # e1 alone is out
    rig.held.clear()
    rig.publisher.committed(step(order(state="partially_filled"), "partial_fill", fill=fills[1]))
    await settled()
    assert [f for f, _ in rig.topics.sent()][2:] == ["executions", "orders", "positions"]


async def test_a_position_finding_its_accounts_hold_full_leaves_at_once_counted() -> None:
    """`HOLD_MAX` keys an account: a held key's later row still waits; a new key's row leaves at
    once, before its fill, and is counted (C-2.18)."""
    rig = Rig(hold_max=1)
    other = PositionKey(AccountId(A), "ETHUSDT", 0)
    rig.held.update({KEY: frozenset({"e1"}), other: frozenset({"e9"})})
    rig.publisher.position(position())
    rig.publisher.position(position(size="0.5"))  # the same key: replaced, still held
    with capture_logs() as logs:
        rig.publisher.position(position(symbol="ETHUSDT", id=UUID(int=0xD1)))
    assert rig.topics.sent() == [("positions", str(UUID(int=0xD1)))] and rig.overtakes == 1
    assert [e["reason"] for e in logs if e["event"] == "oms_ws_position_overtake"] == ["hold_full"]


async def test_a_raising_facade_read_counts_as_no_held_fill() -> None:
    rig = Rig()

    def broken(key: PositionKey) -> frozenset[str]:
        raise RuntimeError("echoed: key abc123")

    rig.publisher.bind(broken)
    with capture_logs() as logs:
        rig.publisher.position(position())
    assert rig.topics.sent() == [("positions", str(UUID(int=0xD0)))]
    [line] = [e for e in logs if e["event"] == "oms_ws_held_fills_failed"]
    assert line["error"] == "RuntimeError" and "abc123" not in str(line)


@virtual
async def test_a_closed_publisher_cancels_its_hold_timers() -> None:
    rig = Rig()
    rig.held[KEY] = frozenset({"e1"})
    rig.publisher.position(position())
    await rig.publisher.aclose()
    await asyncio.sleep(wt.HOLD_S * 2)
    assert rig.topics.calls == [] and rig.overtakes == 0


# -- the position store's hand-off and the lane's reads -----------------------------------------


class Store:
    """`PositionWrites`: answers the row it is given, or the stored newer one (a stale write)."""

    def __init__(self, newer: PositionRow | None = None) -> None:
        self.newer = newer

    async def upsert(self, state: PositionState) -> PositionRow:
        if self.newer is not None:
            return self.newer
        values = {f.name: getattr(state, f.name) for f in fields(PositionState)}
        return PositionRow(**values, id=UUID(int=0xD0), recv_ts=T0, updated_at=T0)


def state(**over: Any) -> PositionState:
    values = {f.name: getattr(position(), f.name) for f in fields(PositionState)}
    return PositionState(**values | over)


async def test_an_applied_position_row_is_handed_on() -> None:
    rig = Rig()
    row = await wt.PublishedPositions(Store(), rig.publisher).upsert(state())
    assert rig.topics.sent() == [("positions", str(row.id))]


async def test_a_stale_writes_stored_row_is_not_handed_on() -> None:
    rig = Rig()
    newer = position(exchange_updated_ts=T0 + timedelta(seconds=1))
    assert await wt.PublishedPositions(Store(newer), rig.publisher).upsert(state()) == newer
    assert rig.topics.calls == []


class Raising(wt.StepPublisher):
    def position(self, row: PositionRow) -> None:
        raise RuntimeError("echoed: key abc123")


async def test_a_hand_off_that_raises_leaves_the_write_as_it_was() -> None:
    rig = Rig(kind=Raising)
    with capture_logs() as logs:
        row = await wt.PublishedPositions(Store(), rig.publisher).upsert(state())
    assert row.id == UUID(int=0xD0)
    [line] = logs
    assert line["event"] == "oms_ws_position_failed" and "abc123" not in str(line)


class Reads:
    """The three stores' reads: every row given, another account's among them."""

    def __init__(self) -> None:
        self.orders = (order(), order(2, account=B))
        self.positions = (position(), position(size="0", id=UUID(int=0xD9)), position(account=B))
        self.fills = (stored(new_fill()), stored(new_fill("e2"), order_id=None))

    async def list_open(self, account_id: UUID, *, symbol: str | None = None) -> tuple[Any, ...]:
        return self.orders

    async def list_recent(self, account_id: UUID, *, limit: int = 100) -> tuple[Any, ...]:
        assert limit == wt.SNAPSHOT_FILLS
        return self.fills


class PositionReads:
    def __init__(self, reads: Reads) -> None:
        self.reads = reads

    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]:
        return self.reads.positions


@pytest.mark.parametrize(("family", "count"), [("orders", 1), ("positions", 1), ("executions", 1)])
async def test_a_snapshot_read_keeps_the_accounts_rows_each_frame_carries(
    family: Any, count: int
) -> None:
    """C-12.4 beside the store's own scope: another account's row is left out, and so are a flat
    position and a fill of no order; each item carries the read's stamp."""
    reads = Reads()
    view = await wt.TopicReads(
        reads, PositionReads(reads), reads, environment="demo", clock=wt.LaneClock(lambda: T0)
    ).read(family, A)
    assert view.stamp == T0_MS and len(view.items) == count
    assert all(item["exchange_account_id"] == str(A) for item in view.items)
    validate(frame(family, {family: list(view.items)}))


@virtual
async def test_held_positions_expire_each_at_its_own_deadline() -> None:
    """One timer an account, re-armed for the next deadline once the earliest has passed: a key
    held later leaves at its own `HOLD_S`, not the first's."""
    rig = Rig()
    other = PositionKey(AccountId(A), "ETHUSDT", 0)
    rig.held.update({KEY: frozenset({"e1"}), other: frozenset({"e9"})})
    rig.publisher.position(position())
    await asyncio.sleep(wt.HOLD_S / 2)
    rig.publisher.position(position(symbol="ETHUSDT", id=UUID(int=0xD1)))
    await asyncio.sleep(wt.HOLD_S / 2 + 0.01)
    assert rig.topics.sent() == [("positions", str(UUID(int=0xD0)))]
    await asyncio.sleep(wt.HOLD_S / 2)
    assert [k for _, k in rig.topics.sent()] == [str(UUID(int=0xD0)), str(UUID(int=0xD1))]
    assert rig.overtakes == 2


@virtual
async def test_an_overtake_counter_that_raises_still_publishes_the_position() -> None:
    rig = Rig()
    rig.held[KEY] = frozenset({"e1"})
    rig.uncounted = True
    with capture_logs() as logs:
        rig.publisher.position(position())
        await asyncio.sleep(wt.HOLD_S + 0.01)
    assert rig.topics.sent() == [("positions", str(UUID(int=0xD0)))]
    assert "oms_ws_overtake_uncounted" in [e["event"] for e in logs]
