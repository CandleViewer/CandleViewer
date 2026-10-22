"""In-memory stand-ins for M14 ports, for unit tests (#846 ruling B1; E29-T03 #847)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Context, Decimal
from itertools import count
from typing import Any, Final, NamedTuple
from uuid import UUID

from candleviewer.domain.order_link import EXT_ID, OUR_ID
from candleviewer.domain.primitives import OrderLinkId
from candleviewer.storage.errors import StorageQueryFailed
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
#: The `symbol_code` domain (`0004_instruments`) of both tables' `symbol`.
_SYMBOL: Final = re.compile(r"[A-Z0-9]{4,20}")
#: The SQLSTATE Postgres refuses text holding NUL with, as it decodes the bound value (22021).
_NUL_TEXT: Final = "22021"
#: The CHECKs (`0029_oms_core`'s, and `ord_lifecycle`, which the order vocabulary's revision adds)
#: a value of the types can break, each true where SQL's is false: a NULL leaves a CHECK unknown,
#: which passes it.
_ORDER_CHECKS: Final[dict[str, Callable[[port.NewOrder | Row], bool]]] = {
    # a `NewOrder` has no count: the column's default, 0
    "ord_attempts": lambda o: not 0 <= getattr(o, "submit_attempts", 0) <= 10,
    "ord_cum": lambda o: not 0 <= o.cum_exec_qty <= o.qty,
    "ord_lifecycle": lambda o: (
        o.lifecycle_state is not None and port.ORDER_STATE_OF.get(o.lifecycle_state) != o.state
    ),
    "ord_limit_px": lambda o: o.order_type == "Limit" and o.price is not None and o.price <= 0,
    "ord_link_fmt": lambda o: not any(p.fullmatch(o.order_link_id) for p in (OUR_ID, EXT_ID)),
    "ord_no_self": lambda o: o.parent_order_id == o.id,
    "ord_qty": lambda o: o.qty <= 0,
    "ord_sl_px": lambda o: o.stop_loss is not None and o.stop_loss <= 0,
    "ord_tp_px": lambda o: o.take_profit is not None and o.take_profit <= 0,
}
_EXECUTION_CHECKS: Final[dict[str, Callable[[NewExecution], bool]]] = {
    "ex_px": lambda x: x.exec_price <= 0,
    "ex_qty": lambda x: x.exec_qty <= 0,
}
#: The scale Postgres returns each number at: numeric(38,18), but numeric(18,10) for `fee_rate`.
_E18: Final = Decimal(10) ** -18
_ORDER_SCALES: Final = dict.fromkeys(port.typed_fields(Row, Decimal), _E18)
_EXECUTION_SCALES: Final = dict.fromkeys(port.typed_fields(ExecutionRow, Decimal), _E18) | {
    "fee_rate": Decimal(10) ** -10
}


def _bindable(values: Iterable[object]) -> None:
    """Postgres decodes every bound text before the statement runs, and text cannot hold NUL: the
    whole statement is refused (22021), before any check, with nothing written."""
    if any(isinstance(value, str) and "\x00" in value for value in values):
        raise StorageQueryFailed(_NUL_TEXT)


def _refuse[T: (port.NewOrder, NewExecution)](
    row: T, checks: Mapping[str, Callable[[T], bool]]
) -> None:
    """Refuse `row` as Postgres does: its text as it is bound, by the `symbol_code` domain as the
    row is built, then by its table's CHECKs in name order."""
    _bindable(asdict(row).values())
    if _SYMBOL.fullmatch(row.symbol) is None:
        raise port.OrderConstraintError("symbol_code_check")
    for name in sorted(checks):
        if checks[name](row):
            raise port.OrderConstraintError(name)


def _at_scale[R: (Row, ExecutionRow)](row: R, scales: Mapping[str, Decimal]) -> R:
    """`row` as Postgres returns it, each number at its column's scale: exact, as every value fits
    its column (`port.require_money`)."""
    values = ((name, getattr(row, name)) for name in scales)
    scaled: dict[str, Any] = {n: _EXACT.quantize(v, scales[n]) for n, v in values if v is not None}
    return replace(row, **scaled)


def _jsonb_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """An object as `jsonb` keeps it: its keys shortest first, then by their bytes."""
    return dict(sorted(pairs, key=lambda pair: (len(pair[0].encode()), pair[0].encode())))


class _StoredEvent(NamedTuple):
    """An `order_events` row as kept, its payload as JSON text: append-only, as `trg_oe_append`
    keeps it on Postgres, so nothing a caller does to a copy changes it."""

    row: EventRow
    payload: str

    def fresh(self) -> EventRow:
        """A fresh copy, as each Postgres read is, its payload as `jsonb` returns it."""
        return replace(self.row, payload=json.loads(self.payload, object_pairs_hook=_jsonb_object))


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
    it changes anything. It meets Postgres's constraints (`0029_oms_core`) by the names Postgres
    reports, in the order Postgres meets them: the `symbol_code` domain, the CHECKs by name, the
    unique indexes in the order they were made, `oe_latency`, then the parent order's foreign key.
    It holds no accounts, so no foreign key to one, and leaves a value outside its column's
    `Literal` to the types. As Postgres does, it returns every number at its column's scale and
    every event as a fresh copy, and refuses text holding NUL (22021). Each call yields to the
    event loop once, before it reads or checks anything, as a driver call suspends: a timeout or
    another task can come between two calls, never between a check and its commit. `fail_next`
    injects a fault at the next commit (S7). The send's step counts `submit_attempts` up, as the
    store does in SQL; a step's `entry_stops` settles recorded stops, which this fake does not
    hold (E29-T04's Postgres tests prove that settle)."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._orders: dict[UUID, Row] = {}
        self._events: dict[UUID, list[_StoredEvent]] = {}
        self._fills: dict[tuple[UUID, str], ExecutionRow] = {}
        self._ids = count(1)
        self._fault: tuple[BaseException, bool] | None = None
        self.executions = InMemoryExecutionStore(self)

    def fail_next(self, error: BaseException, *, committed: bool = False) -> None:
        """Raise `error` at the next commit: with nothing written, as an outage or a timeout
        before the commit; or, `committed`, once its rows are written, as a commit whose answer a
        lost connection cut off (`orders.py`), which a retry then meets."""
        self._fault = (error, committed)

    async def create(self, order: port.NewOrder, first_event: NewEvent) -> Row:
        await asyncio.sleep(0)
        port.require_exchange_record(first_event)
        _refuse(order, _ORDER_CHECKS)
        if order.id in self._orders:  # the unique indexes, the key first, as Postgres checks them
            raise port.OrderConstraintError("orders_pkey")
        if self._link_taken(order.order_link_id):
            raise port.OrderConstraintError(port.UX_ORDERS_LINK)
        held = (order.exchange_account_id, order.exchange_order_id)
        if order.exchange_order_id is not None and any(
            (r.exchange_account_id, r.exchange_order_id) == held for r in self._orders.values()
        ):
            raise port.OrderConstraintError("ux_orders_exch_id")
        row = Row(
            **asdict(order), leaves_qty=_EXACT.subtract(order.qty, order.cum_exec_qty),
            created_ts=self._clock(), submitted_ts=None, last_reconciled_at=None, reject_code=None,
            reject_message=None, submit_attempts=0, idempotency_state="unsent",
        )  # fmt: skip
        row = _at_scale(row, _ORDER_SCALES)
        event = self._event(row, first_event, (None, row.state))
        if order.parent_order_id is not None and order.parent_order_id not in self._orders:
            raise port.OrderConstraintError("orders_parent_order_id_fkey")  # at the statement end
        self._commit(row, event)
        return row

    async def transition(self, step: port.OrderTransition) -> Step:
        await asyncio.sleep(0)
        port.require_no_fill(step.event, step.to_state)
        row, event = self._moved(step)
        self._commit(row, event)
        return Step(row, event.fresh())

    async def get(self, account_id: UUID, order_id: UUID) -> Row | None:
        await asyncio.sleep(0)
        return self._find(account_id, order_id)

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> Row | None:
        await asyncio.sleep(0)
        return next((r for r in self._rows(account_id) if r.order_link_id == order_link_id), None)

    async def list_open(self, account_id: UUID, *, symbol: str | None = None) -> tuple[Row, ...]:
        await asyncio.sleep(0)
        rows = self._rows(account_id)
        return tuple(r for r in rows if r.state in port.OPEN_STATES and symbol in {None, r.symbol})

    async def link_id_taken(self, order_link_id: str) -> bool:
        await asyncio.sleep(0)
        return self._link_taken(order_link_id)

    async def append(self, account_id: UUID, order_id: UUID, event: NewEvent) -> EventRow:
        await asyncio.sleep(0)
        port.require_no_fill(event)
        stored = self._event(self._owned(account_id, order_id), event, (None, None))
        self._commit(stored)
        return stored.fresh()

    async def list_for_order(
        self, account_id: UUID, order_id: UUID, *, after_seq: int = -1, limit: int = _PAGE
    ) -> tuple[EventRow, ...]:
        await asyncio.sleep(0)
        if after_seq < -1 or not 1 <= limit <= _PAGE:
            raise ValueError(f"after_seq must be >= -1 and limit 1..{_PAGE}")
        events = self._events[order_id] if self._find(account_id, order_id) is not None else []
        return tuple(e.fresh() for e in events if e.row.seq > after_seq)[:limit]

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
        return Step(row, event.fresh())

    def _insert(self, execution: NewExecution) -> bool:
        stored = self._execution(execution)
        if (execution.exchange_account_id, execution.exec_id) in self._fills:
            return False
        if execution.order_id is not None:
            self._owned(execution.exchange_account_id, execution.order_id)
        self._commit(stored)
        return True

    def _find(self, account_id: UUID, order_id: UUID) -> Row | None:
        row = self._orders.get(order_id)
        return row if row is not None and row.exchange_account_id == account_id else None

    def _link_taken(self, order_link_id: str) -> bool:
        return any(row.order_link_id == order_link_id for row in self._orders.values())

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
    ) -> tuple[Row, _StoredEvent]:
        """The compare-and-set and its event, or `StaleOrderState`."""
        order = self._owned(step.account_id, step.order_id)
        changes: dict[str, Any] = {**step.changes(), **(totals or {})}
        if step.bump_submit_attempts:
            changes["submit_attempts"] = order.submit_attempts + 1
        _bindable(changes.values())  # the UPDATE's values are bound before it runs
        if order.state != step.from_state:
            raise port.StaleOrderState(step.order_id, step.from_state)
        row = replace(order, **changes)
        for name, broken in sorted(_ORDER_CHECKS.items()):  # an UPDATE meets the CHECKs first,
            if broken(row):
                raise port.OrderConstraintError(name)
        bound = changes.get("exchange_order_id")
        if bound is not None and any(  # then the unique index
            (r.exchange_account_id, r.exchange_order_id) == (order.exchange_account_id, bound)
            for r in self._orders.values()
            if r.id != order.id
        ):
            raise port.OrderConstraintError("ux_orders_exch_id")
        leaves = _EXACT.subtract(row.qty, row.cum_exec_qty)
        row = _at_scale(replace(row, leaves_qty=leaves), _ORDER_SCALES)
        return row, self._event(row, step.event, (step.from_state, step.to_state))

    def _event(self, order: Row, event: NewEvent, states: tuple[str | None, ...]) -> _StoredEvent:
        """`event` as stored: the next `seq`, the exchange's text redacted, `oe_latency` held."""
        if event.latency_ms is not None and event.latency_ms < 0:
            raise port.OrderConstraintError("oe_latency")
        stored: dict[str, Any] = {
            "id": next(self._ids), "order_id": order.id, "order_link_id": order.order_link_id,
            "seq": len(self._events.get(order.id, ())), "kind": event.kind, "source": event.source,
            "from_state": states[0], "to_state": states[1], "event_ts": event.event_ts,
            "payload": {}, "latency_ms": event.latency_ms,  # `_StoredEvent.fresh` fills `payload`
            "ret_code": xp.redact_exchange_text(event.ret_code, max_chars=xp.MAX_CODE_CHARS),
            "ret_msg": xp.redact_exchange_text(event.ret_msg, message=True),
            "recv_ts": self._clock(),
        }  # fmt: skip
        payload = json.dumps(xp.redact_exchange_payload(event.payload))
        return _StoredEvent(EventRow(**stored), payload)

    def _execution(self, execution: NewExecution) -> ExecutionRow:
        """The row an insert would store, refused as Postgres refuses it, before its conflict."""
        _refuse(execution, _EXECUTION_CHECKS)
        values = asdict(execution) | {"id": UUID(int=next(self._ids)), "recv_ts": self._clock()}
        return _at_scale(ExecutionRow(**values), _EXECUTION_SCALES)

    def _commit(self, *rows: Row | _StoredEvent | ExecutionRow) -> None:
        """A write's rows, all at once after its checks; an injected fault before them, or after
        them when it was `committed`."""
        fault, self._fault = self._fault, None
        error, committed = fault or (None, False)
        if error is not None and not committed:
            raise error
        for row in rows:
            if isinstance(row, Row):
                self._orders[row.id] = row
            elif isinstance(row, _StoredEvent):
                self._events.setdefault(row.row.order_id, []).append(row)
            else:
                self._fills[(row.exchange_account_id, row.exec_id)] = row
        if error is not None:
            raise error


class InMemoryExecutionStore:
    """`ExecutionStore` over an `InMemoryOrderStore`'s tables: a fill and its order commit
    together or not at all."""

    def __init__(self, db: InMemoryOrderStore) -> None:
        self._db = db

    async def insert(self, execution: NewExecution) -> bool:
        await asyncio.sleep(0)
        return self._db._insert(execution)

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None:
        await asyncio.sleep(0)
        _bindable((exec_id,))  # the SELECT's `exec_id` is bound before it runs
        return self._db._fills.get((account_id, exec_id))

    async def commit_fill(self, fill: OrderFill) -> Step | None:
        await asyncio.sleep(0)
        return self._db._commit_fill(fill)
