"""In-memory stand-ins for M14 ports, for unit tests (#846 ruling B1; E29-T03 #847)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Context
from itertools import count
from typing import Any
from uuid import UUID

from candleviewer.domain.primitives import OrderLinkId
from candleviewer.storage.repositories import exchange_payload as xp
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.executions import ExecutionRow, NewExecution, OrderFill

__all__ = ["InMemoryExecutionStore", "InMemoryOrderLinkLookup", "InMemoryOrderStore"]

#: Wide enough that a sum or difference of numeric(38,18) values is exact, as in Postgres.
_EXACT = Context(prec=80)
Step = port.CommittedStep
Row = port.OrderRow
EventRow = port.OrderEventRow
NewEvent = port.NewOrderEvent
_PAGE = port.MAX_EVENT_PAGE


class InMemoryOrderLinkLookup:
    """An `OrderLinkLookup` over a set of taken ids, whatever their row's state;
    `lookups` records every id asked about, in order (one lookup per candidate)."""

    def __init__(self, taken: Iterable[OrderLinkId] = ()) -> None:
        self._taken = set(taken)
        self.lookups: list[OrderLinkId] = []

    def add(self, order_link_id: OrderLinkId) -> None:
        """Record a persisted row, as the order INSERT does."""
        self._taken.add(order_link_id)

    async def exists(self, order_link_id: OrderLinkId) -> bool:
        self.lookups.append(order_link_id)
        return order_link_id in self._taken


class InMemoryOrderStore:
    """`OrderStore`, `OrderEventStore` and, as `executions`, `ExecutionStore` over dicts, with the
    stores' contract (`tests/unit/oms/write_ahead_contract.py`): a write checks everything before
    it changes anything. `fail_next(error)` raises at the next commit, as an outage would (S7)."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._orders: dict[UUID, Row] = {}
        self._events: dict[UUID, list[EventRow]] = {}
        self._fills: dict[tuple[UUID, str], ExecutionRow] = {}
        self._ids = count(1)
        self._fault: BaseException | None = None
        self.executions = InMemoryExecutionStore(self)

    def fail_next(self, error: BaseException) -> None:
        self._fault = error

    async def create(self, order: port.NewOrder, first_event: NewEvent) -> Row:
        port.require_exchange_record(first_event)
        if await self.link_id_taken(order.order_link_id):
            raise port.OrderConstraintError(port.UX_ORDERS_LINK)
        row = Row(
            **asdict(order), leaves_qty=_EXACT.subtract(order.qty, order.cum_exec_qty),
            created_ts=self._clock(), submitted_ts=None, last_reconciled_at=None, reject_code=None,
            reject_message=None, submit_attempts=0, idempotency_state="unsent",
        )  # fmt: skip
        self._commit(row, self._event(row, first_event, (None, row.state)))
        return row

    async def transition(self, step: port.OrderTransition) -> Step:
        port.require_no_fill(step.event, step.to_state)
        row, event = self._moved(step)
        self._commit(row, event)
        return Step(row, event)

    async def get(self, account_id: UUID, order_id: UUID) -> Row | None:
        row = self._orders.get(order_id)
        return row if row is not None and row.exchange_account_id == account_id else None

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> Row | None:
        return next((r for r in self._rows(account_id) if r.order_link_id == order_link_id), None)

    async def list_open(self, account_id: UUID, *, symbol: str | None = None) -> tuple[Row, ...]:
        rows = self._rows(account_id)
        return tuple(r for r in rows if r.state in port.OPEN_STATES and symbol in {None, r.symbol})

    async def link_id_taken(self, order_link_id: str) -> bool:
        return any(row.order_link_id == order_link_id for row in self._orders.values())

    async def append(self, account_id: UUID, order_id: UUID, event: NewEvent) -> EventRow:
        port.require_no_fill(event)
        row = self._event(self._owned(account_id, order_id), event, (None, None))
        self._commit(row)
        return row

    async def list_for_order(
        self, account_id: UUID, order_id: UUID, *, after_seq: int = -1, limit: int = _PAGE
    ) -> tuple[EventRow, ...]:
        if after_seq < -1 or not 1 <= limit <= _PAGE:
            raise ValueError(f"after_seq must be >= -1 and limit 1..{_PAGE}")
        events = self._events[order_id] if await self.get(account_id, order_id) else []
        return tuple(e for e in events if e.seq > after_seq)[:limit]

    def _commit_fill(self, fill: OrderFill) -> Step | None:
        """Postgres's order: the lock in the account, the execution's CHECKs, its `exec_id`
        conflict (None, S4), `OrderFill.check`, then the compare-and-set and the step's event."""
        step, execution = fill.step, fill.execution
        order = self._owned(step.account_id, step.order_id)
        stored = self._execution(execution)
        if (execution.exchange_account_id, execution.exec_id) in self._fills:
            return None
        fill.check(order.qty, order.is_paper)
        if _EXACT.add(order.cum_exec_qty, execution.exec_qty) != fill.totals.cum_exec_qty:
            raise port.StaleOrderState(step.order_id, step.from_state)
        row, event = self._moved(step, asdict(fill.totals))
        self._commit(row, event, stored)
        return Step(row, event)

    def _insert(self, execution: NewExecution) -> bool:
        stored = self._execution(execution)
        if (execution.exchange_account_id, execution.exec_id) in self._fills:
            return False
        if execution.order_id is not None:
            self._owned(execution.exchange_account_id, execution.order_id)
        self._commit(stored)
        return True

    def _rows(self, account_id: UUID) -> list[Row]:
        rows = (row for row in self._orders.values() if row.exchange_account_id == account_id)
        return sorted(rows, key=lambda row: (row.created_ts, row.id))

    def _owned(self, account_id: UUID, order_id: UUID) -> Row:
        row = self._orders.get(order_id)
        if row is None or row.exchange_account_id != account_id:
            raise port.OrderNotFoundError
        return row

    def _moved(
        self, step: port.OrderTransition, totals: dict[str, Any] | None = None
    ) -> tuple[Row, EventRow]:
        """The compare-and-set and its event, or `StaleOrderState`."""
        order = self._owned(step.account_id, step.order_id)
        if order.state != step.from_state:
            raise port.StaleOrderState(step.order_id, step.from_state)
        changes: dict[str, Any] = {**step.changes(), **(totals or {})}
        row = replace(order, **changes)
        row = replace(row, leaves_qty=_EXACT.subtract(row.qty, row.cum_exec_qty))
        return row, self._event(row, step.event, (step.from_state, step.to_state))

    def _event(self, order: Row, event: NewEvent, states: tuple[str | None, ...]) -> EventRow:
        """`event` as stored: the next `seq`, the exchange's text redacted, `oe_latency` held."""
        if event.latency_ms is not None and event.latency_ms < 0:
            raise port.OrderConstraintError("oe_latency")
        stored: dict[str, Any] = {
            "id": next(self._ids), "order_id": order.id, "order_link_id": order.order_link_id,
            "seq": len(self._events.get(order.id, ())), "kind": event.kind, "source": event.source,
            "from_state": states[0], "to_state": states[1], "event_ts": event.event_ts,
            "payload": xp.redact_exchange_payload(event.payload), "latency_ms": event.latency_ms,
            "ret_code": xp.redact_exchange_text(event.ret_code, max_chars=xp.MAX_CODE_CHARS),
            "ret_msg": xp.redact_exchange_text(event.ret_msg, message=True),
            "recv_ts": self._clock(),
        }  # fmt: skip
        return EventRow(**stored)

    def _execution(self, execution: NewExecution) -> ExecutionRow:
        """The row an insert would store; its CHECKs come before its conflict, as in Postgres."""
        for check, value in (("ex_qty", execution.exec_qty), ("ex_px", execution.exec_price)):
            if value <= 0:
                raise port.OrderConstraintError(check)
        values = asdict(execution) | {"id": UUID(int=next(self._ids)), "recv_ts": self._clock()}
        return ExecutionRow(**values)

    def _commit(self, *rows: Row | EventRow | ExecutionRow) -> None:
        """A write's rows, all at once after its checks; or the injected fault, and none."""
        if self._fault is not None:
            error, self._fault = self._fault, None
            raise error
        for row in rows:
            if isinstance(row, Row):
                self._orders[row.id] = row
            elif isinstance(row, EventRow):
                self._events.setdefault(row.order_id, []).append(row)
            else:
                self._fills[(row.exchange_account_id, row.exec_id)] = row


class InMemoryExecutionStore:
    """`ExecutionStore` over an `InMemoryOrderStore`'s tables: a fill and its order commit
    together or not at all."""

    def __init__(self, db: InMemoryOrderStore) -> None:
        self._db = db

    async def insert(self, execution: NewExecution) -> bool:
        return self._db._insert(execution)

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None:
        return self._db._fills.get((account_id, exec_id))

    async def commit_fill(self, fill: OrderFill) -> Step | None:
        return self._db._commit_fill(fill)
