"""The reconciliation pass's test rig (E29-T06 #914 PR 2a): hand-built local and remote sets and a
recording double for every port the pass takes, over the real `TradingRouter` and
`FakeTradingPort` (each read and write lands in its call log with its lane). The B1 double answers
each command as B1 version 7 does, counting misses as `recon_misses` does, so a branch unit reads
the state a finding leaves. Every effect lands in one ordered `log`, so a test reads what was
written ahead of what. Names no venue (C-2.2). No network, no sleeps."""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.fakes import FakeTradingPort, fake_capabilities
from candleviewer.exchange.base.models import AccountRef, Execution, Order, Position
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import OrderStepRefused, ReconcileAnomaly
from candleviewer.oms.fakes import InMemoryTradingAccounts
from candleviewer.oms.handovers import HandoverRead, WaitingExecution, WaitingOrder
from candleviewer.oms.ports import Finding
from candleviewer.oms.reconcile_phases import ReconcilePhases
from candleviewer.oms.reconcile_report import Notice, ReconcileMetrics, ReconcileReport, Trigger
from candleviewer.oms.reconcile_standing import FailureTracker, ReconcileStanding
from candleviewer.oms.reconciler import (
    Plan,
    PositionDriftSeen,
    ReconcilePorts,
    Reconciler,
    StopWrite,
)
from candleviewer.oms.routing import TradingRouter
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.persistence import quiescent
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.orders import NewOrder, OrderRow, RecordedStopBind
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

ACCOUNT = AccountId(UUID(int=0xA1))
OTHER = AccountId(UUID(int=0xB2))
NOW_US = 1_790_000_000_000_000
T0 = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=NOW_US)
SWEEP_ID = "00000000-0000-4000-8000-0000000000a1"
#: Our own link ids, as 24 Sec.8.3 shapes them (the example id, numbered).
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-{:02d}en"


def ref(account: AccountId = ACCOUNT, environment: Environment = "demo") -> AccountRef:
    return AccountRef(
        account_id=account, uid="1001", environment=environment, key_ref=str(UUID(int=0x4E1))
    )


def remote(n: int = 1, **over: Any) -> Order:
    """A remote open order: limit, 1 BTCUSDT, unfilled, under our link id `n`, bound `x{n}`."""
    values: dict[str, Any] = {
        "order_link_id": LINK.format(n), "exchange_order_id": f"x{n}", "account_id": ACCOUNT,
        "symbol": "BTCUSDT", "side": "buy", "order_type": "limit", "qty": Decimal(1),
        "price": Decimal(63000), "state": "new", "filled_qty": Decimal(0),
        "leaves_qty": Decimal(1), "avg_fill_price": None, "created_at": NOW_US - 60_000_000,
        "terminal_at": None, "updated_at": NOW_US - 60_000_000, "stop_loss": Decimal(62000),
    }  # fmt: skip
    return Order(**(values | over))


def fill(exec_id: str = "e1", n: int = 1, **over: Any) -> Execution:
    """A trade fill of order `n` (`x{n}`), 0.4 at 63000."""
    values: dict[str, Any] = {
        "exec_id": exec_id, "exchange_order_id": f"x{n}", "order_link_id": LINK.format(n),
        "account_id": ACCOUNT, "symbol": "BTCUSDT", "side": "buy", "price": Decimal(63000),
        "qty": Decimal("0.4"), "fee": Decimal("0.01"), "fee_rate": Decimal("0.0002"),
        "fee_currency": "USDT", "is_maker": False, "exec_type": "trade", "closed_pnl": None,
        "ts_exec": NOW_US - 30_000_000, "ts_ingest": NOW_US - 29_000_000, "seq": 1,
    }  # fmt: skip
    return Execution(**(values | over))


def position(**over: Any) -> Position:
    """An open long of 0.2 BTCUSDT with a stop at 62000."""
    values: dict[str, Any] = {
        "account_id": ACCOUNT, "symbol": "BTCUSDT", "position_idx": 0, "side": "buy",
        "qty": Decimal("0.2"), "avg_entry_price": Decimal(63000), "mark_price": Decimal(63100),
        "liq_price": None, "leverage": Decimal(10), "unrealised_pnl": Decimal(20),
        "cum_realised_pnl": Decimal(0), "take_profit": None, "stop_loss": Decimal(62000),
        "trailing_stop_distance": None, "updated_at": NOW_US - 1_000_000,
    }  # fmt: skip
    return Position(**(values | over))


def row(n: int = 1, state: str = "accepted", **over: Any) -> OrderRow:
    """Row `n` of the account: limit, 1 BTCUSDT at 63000 with its stop, bound to `x{n}`."""
    lifecycle = {"accepted": "submitted", "submitted": "submitting", "new": "draft"}
    lifecycle |= {"pending_submit": "validated", "pending_cancel": "cancel_pending"}
    lifecycle |= {"pending_amend": "amend_pending"}
    values: dict[str, Any] = {
        "id": UUID(int=n), "trade_group_leg_id": None, "exchange_account_id": ACCOUNT,
        "parent_order_id": None, "oco_group_ref": None, "order_link_id": LINK.format(n),
        "exchange_order_id": f"x{n}", "symbol": "BTCUSDT", "side": "Buy", "intent": "entry",
        "order_type": "Limit", "qty": Decimal(1), "price": Decimal(63000), "trigger_price": None,
        "trigger_by": None, "trigger_direction": None, "take_profit": None,
        "stop_loss": Decimal(62000), "tpsl_mode": "Full", "time_in_force": "GTC",
        "reduce_only": False, "close_on_trigger": False, "position_idx": 0, "state": state,
        "cum_exec_qty": Decimal(0), "cum_exec_value": Decimal(0), "avg_price": None,
        "leaves_qty": Decimal(1), "fee_paid": Decimal(0), "reject_code": None,
        "reject_message": None, "submit_attempts": 1, "idempotency_state": "acked",
        "created_ts": T0 - timedelta(minutes=5), "submitted_ts": None,
        "exchange_created_ts": None, "exchange_updated_ts": None, "last_reconciled_at": None,
        "is_paper": False, "lifecycle_state": lifecycle.get(state, state),
        "provenance": "placed",
    }  # fmt: skip
    return OrderRow(**(values | over))


def record(**over: Any) -> RecordedStopRow:
    """The in-force Full-mode stop-loss record of the long BTCUSDT position, at 62000."""
    values: dict[str, Any] = {
        "id": UUID(int=0x5701), "exchange_account_id": ACCOUNT, "symbol": "BTCUSDT",
        "position_idx": 0, "position_side": "Buy", "kind": "stop_loss", "source": "trading_stop",
        "order_id": None, "tpsl_mode": "Full", "trigger_price": Decimal(62000), "size": None,
        "trailing_distance": None, "trailing_active_price": None, "exchange_order_id": None,
        "status": "in_force", "audit_record_id": UUID(int=0xAD), "actor_user_id": None,
        "created_at": T0 - timedelta(hours=1), "answered_at": T0 - timedelta(hours=1),
        "in_force_at": T0 - timedelta(hours=1), "closed_at": None, "released_at": None,
        "position_marker": None,
    }  # fmt: skip
    return RecordedStopRow(**(values | over))


def waiting(execution: Execution, entry_id: int = 41, **over: Any) -> WaitingExecution:
    values: dict[str, Any] = {"empty_reads": 0, "first_empty_read_at": None, "decided": False}
    return WaitingExecution(entry_id, execution, **(values | over))


#: B1 version 7's answer to each command, by the row's persisted state (24 Sec.8.5's table).
_FOUND = {
    "RECON_FOUND_LIVE": "submitted",
    "RECON_FOUND_PARTIAL": "partially_filled",
    "RECON_FOUND_FILLED": "filled",
    "RECON_FOUND_CANCELLED": "cancelled",
}


@dataclass
class FakeOms:
    """Every OMS port the pass takes (`ReconcilePorts`), recording each effect in `log`, in
    order. `rows` is the account's order table (any account's rows may be seeded to test the
    pass's own checks); `fail` raises the named method's exception once per name."""

    rows: dict[UUID, OrderRow] = field(default_factory=dict)
    stored_ids: set[str] = field(default_factory=set)
    records: list[RecordedStopRow] = field(default_factory=list)
    handed_orders: list[WaitingOrder] = field(default_factory=list)
    handed_fills: list[WaitingExecution] = field(default_factory=list)
    unreadable: list[int] = field(default_factory=list)
    held: dict[tuple[str, int], PositionDriftSeen] = field(default_factory=dict)
    taken_elsewhere: set[str] = field(default_factory=set)
    stop_writes: dict[str, StopWrite] = field(default_factory=dict)
    fail: dict[str, BaseException] = field(default_factory=dict)
    anomaly_on_push: set[UUID] = field(default_factory=set)
    refuse_discover: bool = False
    misses: dict[UUID, int] = field(default_factory=dict)
    log: list[tuple[Any, ...]] = field(default_factory=list)
    pages: list[tuple[str, str]] = field(default_factory=list)

    def seed(self, *rows: OrderRow) -> None:
        for r in rows:
            self.rows[r.id] = r

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise self.fail.pop(name)

    def effects(self, *names: str) -> list[tuple[Any, ...]]:
        return [e for e in self.log if not names or e[0] in names]

    # LocalOrders
    async def unfinished_for(self, account_id: UUID) -> Sequence[OrderRow]:
        self._maybe_fail("unfinished_for")
        final = {"filled", "cancelled", "rejected", "expired", "killed", "new"}
        return tuple(r for r in self.rows.values() if r.state not in final)

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None:
        self._maybe_fail("get_by_exchange_order_id")
        return next((r for r in self.rows.values() if r.exchange_order_id == xid), None)

    async def get_by_link_id(self, account_id: UUID, link: str) -> OrderRow | None:
        self._maybe_fail("get_by_link_id")
        return next((r for r in self.rows.values() if r.order_link_id == link), None)

    async def link_id_taken(self, link: str) -> bool:
        return link in self.taken_elsewhere or any(
            r.order_link_id == link for r in self.rows.values()
        )

    # StoredExecutions
    async def stored(self, account_id: UUID, exec_ids: Collection[str]) -> frozenset[str]:
        self._maybe_fail("stored")
        return frozenset(i for i in exec_ids if i in self.stored_ids)

    async def insert(self, execution: NewExecution) -> bool:
        self.log.append(("insert", execution.exec_id))
        self.stored_ids.add(execution.exec_id)
        return True

    # RecordedStopCopy
    async def live_for_account(self, account_id: UUID) -> Sequence[RecordedStopRow]:
        self._maybe_fail("live_for_account")
        return tuple(self.records)

    # Handovers
    async def waiting_orders(self, account_id: AccountId) -> HandoverRead[WaitingOrder]:
        return HandoverRead(tuple(self.handed_orders), tuple(self.unreadable))

    async def waiting_executions(self, account_id: AccountId) -> HandoverRead[WaitingExecution]:
        return HandoverRead(tuple(self.handed_fills))

    async def hand_over_order(self, account_id: AccountId, order: Order) -> None:
        self.log.append(("hand_over_order", order.exchange_order_id))

    async def hand_over_execution(
        self, account_id: AccountId, execution: Execution, *, empty_read: bool = False
    ) -> None:
        self._maybe_fail("hand_over_execution")
        self.log.append(("hand_over_execution", execution.exec_id, empty_read))

    async def decide(self, account_id: AccountId, exec_id: str) -> bool:
        self.log.append(("decide", exec_id))
        return True

    async def prune(self, account_id: AccountId, entry_ids: Collection[int]) -> int:
        self.log.append(("prune", tuple(sorted(entry_ids))))
        return len(entry_ids)

    # OrderMachinesPort
    async def command(
        self, account_id: UUID, order_id: UUID, event: str,
        payload: Mapping[str, Any] | None = None, *, actor: str,
        expected_seq: int | None = None, on_taken: Any = None,
    ) -> str:  # fmt: skip
        self._maybe_fail(f"command:{event}")
        self.log.append(("command", order_id, event, dict(payload or {}), actor))
        r = self.rows[order_id]
        state = r.lifecycle_state or r.state
        if event in _FOUND:
            state = (
                state
                if r.state == "untracked" and event.endswith(("LIVE", "PARTIAL"))
                else _FOUND[event]
            )
        elif event == "MISMATCH":
            state = "held"
        elif event == "RECON_MISS":
            if r.state in ("unknown", "untracked"):
                seen = self.misses.get(order_id, 0) + 1
                self.misses[order_id] = seen
                if seen >= 2:
                    state = "rejected" if r.state == "unknown" else "cancelled"
            else:
                state = "unknown"
        return state

    async def push(
        self, account_id: UUID, order_id: UUID, event: str, payload: Mapping[str, Any]
    ) -> None:
        self._maybe_fail(f"push:{event}")
        if order_id in self.anomaly_on_push:
            raise ReconcileAnomaly("filled", event)
        self.log.append(("push", order_id, event, dict(payload)))

    async def discover(
        self, order: NewOrder, *, environment: str, pass_id: str | None = None
    ) -> str:
        self._maybe_fail("discover")
        if self.refuse_discover:
            raise OrderStepRefused("DISCOVERED", "OrderConstraintError", deterministic=True)
        self.log.append(("discover", order.order_link_id, order.exchange_order_id, pass_id))
        self.seed(row(99, "untracked", id=order.id, order_link_id=order.order_link_id,
                      exchange_order_id=order.exchange_order_id))  # fmt: skip
        return "untracked"

    async def materialise(
        self, order: NewOrder, *, environment: str, pass_id: str | None = None,
        binds: RecordedStopBind | None = None,
    ) -> str:  # fmt: skip
        self.log.append(("materialise", order.order_link_id, order.exchange_order_id, binds))
        materialised = row(98, "accepted", id=order.id, order_link_id=order.order_link_id)
        self.seed(replace(materialised, exchange_order_id=order.exchange_order_id,
                          provenance="recorded_stop"))  # fmt: skip
        return "submitted"

    # PositionTruth
    async def held_positions(self, account_id: UUID) -> Mapping[tuple[str, int], PositionDriftSeen]:
        self._maybe_fail("held")
        return dict(self.held)

    async def apply(self, p: Position, *, pass_id: str) -> PositionDriftSeen | None:
        self.log.append(("apply_position", p.symbol, p.position_idx, p.qty))
        before = self.held.get((p.symbol, p.position_idx))
        self.held[(p.symbol, p.position_idx)] = PositionDriftSeen(p.side, p.qty)
        return before if before is None or (before.side, before.qty) != (p.side, p.qty) else None

    # ProtectiveStops
    async def attach_recorded(
        self, account: AccountRef, p: Position, rec: RecordedStopRow, *, pass_id: str
    ) -> StopWrite:
        self._maybe_fail("attach_recorded")
        self.log.append(("attach_recorded", p.symbol, rec.trigger_price, pass_id))
        return self.stop_writes.get("attach", "sent")

    async def restore_recorded(
        self, account: AccountRef, p: Position, rec: RecordedStopRow, *, pass_id: str
    ) -> StopWrite:
        self.log.append(("restore_recorded", p.symbol, rec.trigger_price, pass_id))
        return self.stop_writes.get("restore", "sent")

    # ForeignOrderLockout, ExchangePlaced, AdoptionAudit, Pager
    async def open(self, account_id: UUID, *, finding: Finding, key: str) -> None:
        self._maybe_fail("open")
        self.log.append(("freeze", finding, key))

    async def exchange_placed(self, account_id: UUID, *, finding: Finding, key: str) -> None:
        self.log.append(("exchange_placed", finding, key))

    async def adopted(
        self, account_id: AccountId, *, row_id: UUID, order: Order, pass_id: str
    ) -> None:
        self._maybe_fail("adopted")
        self.log.append(("adopted", row_id, order.exchange_order_id, pass_id))

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.pages.append((severity, summary))


class OmsPositions:
    """`PositionTruth` over the fake (its `held` read and its `apply`)."""

    def __init__(self, oms: FakeOms) -> None:
        self._oms = oms

    async def held(self, account_id: UUID) -> Mapping[tuple[str, int], PositionDriftSeen]:
        return await self._oms.held_positions(account_id)

    async def apply(self, p: Position, *, pass_id: str) -> PositionDriftSeen | None:
        return await self._oms.apply(p, pass_id=pass_id)


@dataclass
class World:
    """The pass over the fake OMS and the fake venue (demo, 7 days of order history)."""

    oms: FakeOms = field(default_factory=FakeOms)
    environment: Environment = "demo"
    now_us: int = NOW_US
    naked: int = 0

    def __post_init__(self) -> None:
        retention = 7 if self.environment == "demo" else None  # demo keeps 7 days (24 Sec.14.3)
        self.venue = FakeTradingPort(
            environment=self.environment,
            capabilities=fake_capabilities(self.environment, order_retention_days=retention),
            now_us=lambda: self.now_us,
        )
        router = TradingRouter(
            {self.environment: self.venue},
            lane_waits={"critical": 5.0, "entry": 5.0, "poll": 5.0},
        )
        account = ref(environment=self.environment)
        ports = ReconcilePorts(
            accounts=InMemoryTradingAccounts(account), router=router, orders=self.oms,
            executions=self.oms, stops=self.oms, handovers=self.oms, machines=self.oms,
            positions=OmsPositions(self.oms), protective=self.oms, lockout=self.oms,
            exchange_placed=self.oms, adoptions=self.oms, pager=self.oms,
        )  # fmt: skip
        ids = iter(UUID(int=0xC000 + n) for n in range(1, 1000))
        self.reconciler = Reconciler(
            ports, now_us=lambda: self.now_us, new_id=lambda: next(ids), on_naked=self._naked
        )

    def _naked(self) -> None:
        self.naked += 1

    async def plan(self, trigger: Trigger = "periodic") -> Plan:
        fetched = await self.reconciler.fetch(
            ACCOUNT,
            pass_id=SWEEP_ID,
            trigger=trigger,
            window=(self.now_us - 60_000_000, self.now_us),
        )
        return await self.reconciler.diff(fetched)

    async def run(self, trigger: Trigger = "periodic") -> ReconcileReport:
        plan = await self.plan(trigger)
        await self.reconciler.remediate(plan)
        return self.reconciler.finish(plan)

    def calls(self) -> list[tuple[str, str]]:
        """The venue's calls, each with its lane."""
        return [(c.method, c.lane) for c in self.venue.calls]


# --- B19's port over the pass (`ReconcilePhases`), with recording doubles ----------------------


@dataclass
class Notices:
    published: list[tuple[AccountId, Notice]] = field(default_factory=list)

    def publish(self, account_id: AccountId, notice: Notice) -> None:
        self.published.append((account_id, notice))


@dataclass
class Records:
    rows: list[tuple[AccountId, str, Mapping[str, object]]] = field(default_factory=list)
    refuse: bool = False

    async def finished(
        self, account_id: AccountId, *, pass_id: str, state: Mapping[str, object]
    ) -> None:
        if self.refuse:
            raise ConnectionError("the audit store is down")
        self.rows.append((account_id, pass_id, state))


@dataclass
class Marks:
    last: int | None = None

    def last_message_us(self, account_id: AccountId) -> int | None:
        return self.last


@dataclass
class Watermarks:
    stored: int | None = None
    advanced: list[int] = field(default_factory=list)
    refuse_read: bool = False

    async def last_reconciled_us(self, account_id: AccountId) -> int | None:
        if self.refuse_read:
            raise ConnectionError("the account store is down")
        return self.stored

    async def advance(self, account_id: AccountId, to_us: int) -> None:
        self.advanced.append(to_us)
        self.stored = to_us


@dataclass
class Retries:
    asked: list[int] = field(default_factory=list)

    def retry(self, account_id: AccountId, *, attempt: int) -> None:
        self.asked.append(attempt)


@dataclass
class Job:
    """The pass as B19 reaches it: `phases` is `b19_reconciliation.JobPorts`."""

    world: World = field(default_factory=World)
    standing: ReconcileStanding = field(default_factory=ReconcileStanding)
    tracker: FailureTracker = field(default_factory=FailureTracker)
    notices: Notices = field(default_factory=Notices)
    records: Records = field(default_factory=Records)
    marks: Marks = field(default_factory=Marks)
    watermarks: Watermarks = field(default_factory=Watermarks)
    retries: Retries = field(default_factory=Retries)
    #: The requests the startup resumed (`ResumedRequests`), none unless a test holds some.
    resumed: Any = None

    def __post_init__(self) -> None:
        self.metrics = Metrics("dev")
        self.phases = ReconcilePhases(
            self.world.reconciler, standing=self.standing, tracker=self.tracker,
            marks=self.marks, watermarks=self.watermarks, records=self.records,
            notices=self.notices, retries=self.retries, metrics=ReconcileMetrics(self.metrics),
            pager=self.world.oms, now_us=lambda: self.world.now_us, resumed=self.resumed,
        )  # fmt: skip


async def started(*, auto_remediate: bool = True) -> Any:
    """The account's B19, built through `cv.statechart.factory` only (BQ-1), resting in `idle`;
    its binding's port is the caller's (`b19_reconciliation.set_ports`)."""
    built = await build(
        "reconciliation",
        ctx={"account_id": str(ACCOUNT), "auto_remediate": auto_remediate},
        clock=default_clock(),
        lane="order",
    )
    return built.interpreter


def leaf(interp: Any) -> str:
    """B19's one active leaf (`reconciliation.<state>`)."""
    ids = [s for s in interp.current_state_ids if s.startswith("reconciliation.")]
    return str(ids[0]).rsplit(".", 1)[1]


async def rest(interp: Any, budget: int = 4000) -> str:
    """Yields (never sleeps) until B19 rests in a state where no service runs."""
    for _ in range(budget):
        await asyncio.sleep(0)
        if leaf(interp) in b19.REST_STATES and quiescent(interp):
            break
    return leaf(interp)
