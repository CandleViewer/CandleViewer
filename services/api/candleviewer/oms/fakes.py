"""In-memory stand-ins for M14 ports, for unit tests (#846 ruling B1; E29-T03 #847; #913; #848)."""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Context, Decimal
from itertools import count
from typing import Any, Final, NamedTuple
from uuid import UUID

from candleviewer.domain.order_link import EXT_ID, OUR_ID
from candleviewer.domain.primitives import AccountId, Environment, OrderLinkId
from candleviewer.exchange.base.errors import ClockDriftError
from candleviewer.exchange.base.models import AccountRef
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories import exchange_payload as xp
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.executions import ExecutionRow, NewExecution, OrderFill
from candleviewer.storage.repositories.idempotency_anchors import (
    UX_IA_PRINCIPAL_REF,
    AnchorOperation,
    AnchorOutcome,
    AnchorRow,
    NewAnchor,
    require_client_ref,
    require_fingerprint,
)
from candleviewer.storage.repositories.recorded_stops import (
    EVERY_ACCOUNT,
    LIVE_STOP_STATUSES,
    REFUSED_BY,
    REFUSED_ENTRY,
    STOP_AUDIT_TIMEOUT_S,
    UNSENT_ENTRY,
    UX_RS_IN_FLIGHT,
    WAITING_ENTRY,
    FillPosition,
    InForce,
    InForceWriteAhead,
    InsertWriteAhead,
    NewRecordedStop,
    RecordedStopNotBindable,
    RecordedStopRow,
    ReleaseWriteAhead,
    ResolveOutcome,
    ResolveWriteAhead,
    SettleWriteAhead,
    StaleRecordedStop,
    StopOutcome,
    SweepScope,
    SweepWriteAhead,
    SweptStop,
    check_in_force,
    check_request,
    check_resolve,
    request_cutoff,
)
from candleviewer.storage.repositories.submissions import (
    UX_TG_CREATOR_REF,
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
    SubmissionRefusal,
)
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    NO_STOP_LEG_STATUSES,
    PROFILE_CHANGED,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupLegRow,
    TradeGroupRecord,
    TradeGroupRow,
    TradeGroupStoreRefusedError,
    render_json,
)

from .errors import AccountScopeDenied
from .ports import AccountNoticeReason, Finding, ResyncReason

__all__ = [
    "FakeClockHealth", "InMemoryAccountNotices", "InMemoryExecutionStore",
    "InMemoryForeignOrderLockout", "InMemoryIdempotencyAnchorStore", "InMemoryOrderLinkLookup",
    "InMemoryOrderStore", "InMemoryReconciliationRequests", "InMemoryRecordedStopStore",
    "InMemoryStreamedAccounts", "InMemorySubmissionStore", "InMemoryTradingAccounts",
]  # fmt: skip

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
#: E29-T04: numeric(38,18), and numeric(10,2) for a leg's `resolved_leverage`.
_STOP_SCALES: Final = dict.fromkeys(port.typed_fields(RecordedStopRow, Decimal), _E18)
_GROUP_SCALES: Final = dict.fromkeys(port.typed_fields(TradeGroupRow, Decimal), _E18)
_LEG_SCALES: Final = dict.fromkeys(port.typed_fields(TradeGroupLegRow, Decimal), _E18) | {
    "resolved_leverage": Decimal("0.01")
}
#: The `sha256_hex` domain (21 Sec.1.2) of a group's `client_body_sha256`.
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
#: The CHECKs of `trade_groups` and `trade_group_legs` (`0039_trade_groups`) a first persist's
#: values can break, each true where SQL's is false. The rest are the types' (a value outside its
#: column's `Literal`), the row's own (`NewTradeGroup`, `NewTradeGroupLeg` and `FirstPersist.check`
#: refuse them before any statement) or hold at an insert (the times, the store's defaults);
#: `test_submission_fake.py` pins the split against the schema.
_GROUP_CHECKS: Final[dict[str, Callable[[NewTradeGroup], bool]]] = {
    "tg_cond_px": lambda g: (
        g.entry_type == "Conditional"
        and not (g.trigger_price is not None and g.trigger_price > 0 and g.trigger_by is not None)
    ),
    "tg_limit_px": lambda g: (
        g.entry_type == "Limit" and not (g.entry_price is not None and g.entry_price > 0)
    ),
    "tg_ref_fmt": lambda g: not _canonical(g.client_group_ref),
}
_LEG_CHECKS: Final[dict[str, Callable[[NewTradeGroupLeg], bool]]] = {
    "tgl_filled_rng": lambda leg: leg.target_qty < 0,  # `filled_qty` starts at 0
    "tgl_lev": lambda leg: not 1 <= leg.resolved_leverage <= 100,
    "tgl_qty_pos": lambda leg: leg.target_qty <= 0,
    "tgl_seq": lambda leg: not 0 <= leg.sequence_no <= 100,
    "tgl_sl_px": lambda leg: (
        leg.status not in NO_STOP_LEG_STATUSES
        and not (leg.resolved_sl_price is not None and leg.resolved_sl_price > 0)
    ),
}
#: The leg trigger (`0039_trade_groups`, `USING CONSTRAINT`) that refuses a leg whose account is
#: outside its group's environment (C-2.11), by the name Postgres reports.
_TGL_ENV: Final = "trg_tgl_env"
#: The submissions' write-ahead hook default bound (s): `submissions_sqlalchemy`'s
#: `SUBMISSION_AUDIT_TIMEOUT_S`, which this driver-free module cannot import (ADR-0003); a unit
#: test pins them equal. The recorded stops' bound is `recorded_stops.STOP_AUDIT_TIMEOUT_S`.
SUBMISSION_AUDIT_TIMEOUT_S: Final = 0.5


def _canonical(ref: str) -> bool:
    """`tg_ref_fmt`'s rule, which `ia_ref_fmt` shares: canonical lower-case UUID text."""
    try:
        require_client_ref(ref)
    except ValueError:
        return False
    return True


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


def _at_scale[R: (Row, ExecutionRow, RecordedStopRow, TradeGroupRow, TradeGroupLegRow)](
    row: R, scales: Mapping[str, Decimal]
) -> R:
    """`row` as Postgres returns it, each number at its column's scale: exact, as every value fits
    its column (`port.require_money`)."""
    values = ((name, getattr(row, name)) for name in scales)
    scaled: dict[str, Any] = {n: _EXACT.quantize(v, scales[n]) for n, v in values if v is not None}
    return replace(row, **scaled)


def _jsonb_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """An object as `jsonb` keeps it: its keys shortest first, then by their bytes."""
    return dict(sorted(pairs, key=lambda pair: (len(pair[0].encode()), pair[0].encode())))


def _holds(row: object, proof: Mapping[str, object]) -> bool:
    """`recorded_stops`' proofs on an `orders` row (`UNSENT_ENTRY`, `WAITING_ENTRY`): each column
    holds its value, or one of a set of them."""
    for name, value in proof.items():
        held = getattr(row, name)
        if not (held in value if isinstance(value, frozenset) else held == value):
            return False
    return True


async def _write_ahead(hook: Awaitable[None], timeout_s: float) -> None:
    """`bounded_write_ahead`'s contract, which this driver-free module cannot import: past
    `timeout_s` the write rolls back with `WriteAheadTimeout`; an `OSError` from the hook leaves as
    the order stores' unit of work maps it, `StorageTierUnavailable`, naming only its type."""
    try:
        async with asyncio.timeout(timeout_s):
            await hook
    except TimeoutError as exc:
        raise WriteAheadTimeout(f"write-ahead audit exceeded {timeout_s} s") from exc
    except OSError as exc:
        raise StorageTierUnavailable(f"postgres unreachable ({type(exc).__name__})") from None


class _StoredEvent(NamedTuple):
    """An `order_events` row as kept, its payload as JSON text: append-only, as `trg_oe_append`
    keeps it on Postgres, so nothing a caller does to a copy changes it."""

    row: EventRow
    payload: str

    def fresh(self) -> EventRow:
        """A fresh copy, as each Postgres read is, its payload as `jsonb` returns it."""
        return replace(self.row, payload=json.loads(self.payload, object_pairs_hook=_jsonb_object))


class _StoredAnchor(NamedTuple):
    """An `idempotency_anchors` row as kept: the key and the fingerprint, which no read returns
    (SR-E29-07), its creation time and its outcome, once recorded."""

    anchor: NewAnchor
    created_at: datetime
    outcome: AnchorOutcome | None = None

    def key(self) -> tuple[UUID, AnchorOperation, str]:
        """`ux_ia_principal_ref`'s columns."""
        return (self.anchor.created_by, self.anchor.operation, self.anchor.client_ref)

    def read(self, request_sha256: str) -> AnchorRow:
        """The row `find` returns, the fingerprint compared and never returned."""
        anchor, outcome = self.anchor, self.outcome
        return AnchorRow(
            id=anchor.id, created_by=anchor.created_by, operation=anchor.operation,
            trade_group_id=anchor.trade_group_id, order_id=anchor.order_id,
            outcome_status=None if outcome is None else outcome.status,
            outcome_code=None if outcome is None else outcome.code,
            outcome_ret_code=None if outcome is None else outcome.ret_code,
            created_at=self.created_at, decided_at=None if outcome is None else outcome.decided_at,
            body_matches=anchor.request_sha256 == request_sha256,
        )  # fmt: skip


type _Stored = (
    Row | _StoredEvent | ExecutionRow | RecordedStopRow | TradeGroupRecord | _StoredAnchor
)


def _in_flight(row: RecordedStopRow) -> bool:
    """`ux_rs_in_flight`'s predicate: a pending stop-loss row the exchange has not answered."""
    return (row.status, row.kind) == ("pending", "stop_loss") and row.answered_at is None


def _age(row: RecordedStopRow) -> tuple[datetime, UUID]:
    """The recorded stops' read order: oldest first, then by id."""
    return (row.created_at, row.id)


def _leg_order(leg: TradeGroupLegRow) -> tuple[int, UUID]:
    """A group's legs in `(sequence_no, id)` order, as the trade-group store reads them."""
    return (leg.sequence_no, leg.id)


def _settled(row: RecordedStopRow, outcome: StopOutcome, at: datetime) -> RecordedStopRow:
    """`row` as a settle leaves it (`recorded_stops_sqlalchemy.settle_statement`)."""
    if outcome == "answered":
        return replace(row, answered_at=at)
    if outcome == "refused":
        return replace(row, status="void", answered_at=at, closed_at=at)
    return replace(row, status="void", closed_at=at)  # not_shown: a complete read decided it


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
    store does in SQL.

    E29-T04 (#913): the same tables hold the first persist's (`submissions`), with the trade
    groups and legs it writes, the replay anchors (`anchors`) and the recorded stops (`stops`),
    under their own contract (`tests/unit/oms/submission_contract.py`); a step's `entry_stops`
    settles the entry's recorded stops with the step, as the store does in SQL. A write whose
    write-ahead hook is awaited holds its rows, uncommitted, until it commits or rolls back: every
    other write waits for it, as one that meets a row it holds waits on Postgres (here any write
    waits), and a read never sees them."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._orders: dict[UUID, Row] = {}
        self._events: dict[UUID, list[_StoredEvent]] = {}
        self._fills: dict[tuple[UUID, str], ExecutionRow] = {}
        self._groups: dict[UUID, TradeGroupRecord] = {}
        self._anchors: dict[UUID, _StoredAnchor] = {}
        self._stops: dict[UUID, RecordedStopRow] = {}
        self._refusals: dict[UUID, SubmissionRefusal] = {}
        #: Each seeded account's `exchange_accounts.env` (`InMemorySubmissionStore.seed_account`).
        self._environments: dict[UUID, Environment] = {}
        self._held: asyncio.Event | None = None
        self._ids = count(1)
        self._fault: tuple[BaseException, bool] | None = None
        self.executions = InMemoryExecutionStore(self)
        self.submissions = InMemorySubmissionStore(self)
        self.anchors = InMemoryIdempotencyAnchorStore(self)
        self.stops = InMemoryRecordedStopStore(self)

    def fail_next(self, error: BaseException, *, committed: bool = False) -> None:
        """Raise `error` at the next commit: with nothing written, as an outage or a timeout
        before the commit; or, `committed`, once its rows are written, as a commit whose answer a
        lost connection cut off (`orders.py`), which a retry then meets."""
        self._fault = (error, committed)

    async def create(self, order: port.NewOrder, first_event: NewEvent) -> Row:
        await self._turn()
        port.require_exchange_record(first_event)
        row, event = self._new_order(order, first_event)
        self._commit_rows(row, event)
        return row

    async def transition(self, step: port.OrderTransition) -> Step:
        await self._turn()
        port.require_no_fill(step.event, step.to_state)
        row, event = self._moved(step)
        self._commit_rows(row, event, *self._entry_stops(step, row))
        return Step(row, event.fresh())

    async def get(self, account_id: UUID, order_id: UUID) -> Row | None:
        await asyncio.sleep(0)
        return self._find(account_id, order_id)

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> Row | None:
        await asyncio.sleep(0)
        return next((r for r in self._rows(account_id) if r.order_link_id == order_link_id), None)

    async def get_by_exchange_order_id(
        self, account_id: UUID, exchange_order_id: str
    ) -> Row | None:
        port.require_exchange_order_id(exchange_order_id)
        await asyncio.sleep(0)
        _bindable((exchange_order_id,))  # the statement's value is bound before it runs
        rows = self._rows(account_id)
        return next((r for r in rows if r.exchange_order_id == exchange_order_id), None)

    async def list_open(self, account_id: UUID, *, symbol: str | None = None) -> tuple[Row, ...]:
        await asyncio.sleep(0)
        rows = self._rows(account_id)
        return tuple(r for r in rows if r.state in port.OPEN_STATES and symbol in {None, r.symbol})

    async def list_unfinished(self, environment: Environment, *, limit: int) -> tuple[Row, ...]:
        """`UnfinishedOrders` over the accounts `InMemorySubmissionStore.seed_account` gave an
        environment, whatever `refuse` says of them (an unfinished order outlives its account's
        status); an account never seeded has none, so its orders are listed under none."""
        port.require_limit(limit)
        await asyncio.sleep(0)
        rows = (
            r
            for r in self._orders.values()
            if r.state in port.UNFINISHED_STATES
            and self._environments.get(r.exchange_account_id) == environment
        )
        return tuple(sorted(rows, key=lambda row: (row.created_ts, row.id)))[:limit]

    async def environment_accounts(self, environment: Environment) -> tuple[UUID, ...]:
        """`UnfinishedOrders` over the accounts `InMemorySubmissionStore.seed_account` gave
        `environment`."""
        await asyncio.sleep(0)
        return tuple(a for a, env in self._environments.items() if env == environment)

    async def link_id_taken(self, order_link_id: str) -> bool:
        await asyncio.sleep(0)
        return self._link_taken(order_link_id)

    async def append(self, account_id: UUID, order_id: UUID, event: NewEvent) -> EventRow:
        await self._turn()
        port.require_no_fill(event)
        stored = self._event(self._owned(account_id, order_id), event, (None, None))
        self._commit_rows(stored)
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
        self._commit_rows(row, event, stored, *self._entry_stops(step, row))
        return Step(row, event.fresh())

    def _insert(self, execution: NewExecution) -> bool:
        stored = self._execution(execution)
        if (execution.exchange_account_id, execution.exec_id) in self._fills:
            return False
        if execution.order_id is not None:
            self._owned(execution.exchange_account_id, execution.order_id)
        self._commit_rows(stored)
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

    async def _turn(self) -> None:
        """A write's one yield, as a driver call suspends, then its wait while another write holds
        its rows over a write-ahead hook: Postgres makes a write that meets them wait for that
        commit or rollback."""
        await asyncio.sleep(0)
        while self._held is not None:
            await self._held.wait()

    async def _audited_commit(
        self, hook: Awaitable[None] | None, timeout_s: float, *rows: _Stored
    ) -> None:
        """Await a write's write-ahead hook, bounded, while its rows are held, then commit them: a
        hook that raises or outlasts its bound commits nothing."""
        if hook is not None:
            held = self._held = asyncio.Event()
            try:
                await _write_ahead(hook, timeout_s)
            finally:
                self._held = None
                held.set()
        self._commit_rows(*rows)

    def _new_order(self, order: port.NewOrder, first_event: NewEvent) -> tuple[Row, _StoredEvent]:
        """An order's insert with its first event, refused as Postgres refuses it, uncommitted."""
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
        return row, event

    def _entry_stops(self, step: port.OrderTransition, order: Row) -> list[RecordedStopRow]:
        """The step's settle of its entry's pending attach rows, after its update and a fill's
        totals (`orders_sqlalchemy.settle_entry_stops_statement`): `answered` stamps the ones in
        flight; `void` ends them all, unless the order as the step leaves it holds a fill."""
        if step.entry_stops is None or (step.entry_stops == "void" and order.cum_exec_qty > 0):
            return []
        at, owner = step.event.event_ts, (step.account_id, step.order_id)
        mine = [
            row
            for row in self._stops.values()
            if (row.exchange_account_id, row.order_id) == owner
            and (row.source, row.status) == ("entry_attach", "pending")
        ]
        if step.entry_stops == "answered":
            return [replace(row, answered_at=at) for row in mine if row.answered_at is None]
        return [replace(row, status="void", closed_at=at) for row in mine]

    def _first_rows(
        self, first: FirstPersist, order: port.NewOrder, event: NewEvent
    ) -> tuple[FirstPersisted, list[_Stored]]:
        """A first persist's rows, uncommitted, refused at the statement `submissions_sqlalchemy`
        meets it in: the group, the share-locked re-check, the leg, the order and its first event,
        the recorded stops, then the anchor."""
        group: TradeGroupRecord | None = None
        if first.group is None:
            self._recheck({order.exchange_account_id}, ())
        else:
            head = self._new_group(first.group)
            self._recheck({leg.exchange_account_id for leg in first.legs}, first.legs)
            legs = self._new_legs(head.id, first.legs, environment=first.group.env)
            group = TradeGroupRecord(head, tuple(sorted(legs, key=_leg_order)))
        row, stored_event = self._new_order(order, event)
        stops = self._new_stops(first.recorded_stops, placed=order.id)
        anchor = self._new_anchor(first.anchor)
        rows: list[_Stored] = [row, stored_event, *stops, anchor]
        if group is not None:
            rows.append(group)
        return FirstPersisted(row, first.anchor.id, group, stops), rows

    def _new_group(self, group: NewTradeGroup) -> TradeGroupRow:
        """The group's insert (`insert_group_statement`): its text bound, its domains in column
        order, its CHECKs by name, then `ux_tg_creator_ref`, which writes nothing and answers
        `AnchorTakenError`, then its key."""
        values = asdict(group)
        _bindable(values.values())
        if _SHA256.fullmatch(values.pop("client_body_sha256")) is None:
            raise port.OrderConstraintError("sha256_hex_check")
        if _SYMBOL.fullmatch(group.symbol) is None:
            raise port.OrderConstraintError("symbol_code_check")
        for name in sorted(_GROUP_CHECKS):
            if _GROUP_CHECKS[name](group):
                raise port.OrderConstraintError(name)
        creator = (group.created_by, group.client_group_ref)
        if any(
            (g.group.created_by, g.group.client_group_ref) == creator for g in self._groups.values()
        ):
            raise AnchorTakenError(UX_TG_CREATOR_REF)
        if group.id in self._groups:
            raise port.OrderConstraintError("trade_groups_pkey")
        params = group.algo_params
        if params is not None:  # read back as `jsonb` keeps an object's keys
            values["algo_params"] = json.loads(render_json(params), object_pairs_hook=_jsonb_object)
        now = self._clock()
        row = TradeGroupRow(
            **values, submitted_at=None, opened_at=None, closed_at=None, created_at=now,
            updated_at=now,
        )  # fmt: skip
        return _at_scale(row, _GROUP_SCALES)

    def _recheck(self, accounts: set[UUID], legs: Sequence[NewTradeGroupLeg]) -> None:
        """`require_live` (SR-E28-15), as the injected refusals say (`InMemorySubmissionStore`'s
        `refuse`): the accounts first, then the legs' profiles; a reduce-only order locks its
        account and no profile. No live profile is at a version below 1."""
        if any(self._refusals.get(account) == ACCOUNT_NOT_LIVE for account in accounts):
            raise TradeGroupStoreRefusedError(ACCOUNT_NOT_LIVE)
        for leg in legs:
            moved = self._refusals.get(leg.exchange_account_id) == PROFILE_CHANGED
            if moved or leg.profile_version < 1:
                raise TradeGroupStoreRefusedError(PROFILE_CHANGED)

    def _new_legs(
        self, group_id: UUID, legs: Sequence[NewTradeGroupLeg], *, environment: Environment
    ) -> list[TradeGroupLegRow]:
        """The legs' insert (`insert_legs_statement`) into a group of `environment`: the rejection
        texts redacted and bound, then for each leg its row trigger `trg_tgl_env` (C-2.11: a leg
        on a seeded account of another environment, SEC-2B1-03), its CHECKs by name, its key and
        `ux_tgl_group_account`. An account never seeded passes the trigger here, as the fake
        holds no account rows; Postgres never reaches it for such an account (`env` is NOT NULL,
        and `require_live` refuses an unknown account first), so a rig that persists groups
        seeds every `AccountRef`."""
        texts = [
            {
                "rejection_code": xp.redact_exchange_text(
                    leg.rejection_code, max_chars=xp.MAX_CODE_CHARS
                ),
                "rejection_message": xp.redact_exchange_text(leg.rejection_message, message=True),
            }
            for leg in legs
        ]
        _bindable(
            v for leg, text in zip(legs, texts, strict=True) for v in (asdict(leg) | text).values()
        )
        taken = {leg.id for record in self._groups.values() for leg in record.legs}
        rows: list[TradeGroupLegRow] = []
        now = self._clock()
        for leg, text in zip(legs, texts, strict=True):
            if self._environments.get(leg.exchange_account_id, environment) != environment:
                raise port.OrderConstraintError(_TGL_ENV)  # a BEFORE ROW trigger: ahead of CHECKs
            for name in sorted(_LEG_CHECKS):
                if _LEG_CHECKS[name](leg):
                    raise port.OrderConstraintError(name)
            if leg.id in taken or any(row.id == leg.id for row in rows):
                raise port.OrderConstraintError("trade_group_legs_pkey")
            if any(row.exchange_account_id == leg.exchange_account_id for row in rows):
                raise port.OrderConstraintError("ux_tgl_group_account")
            values = asdict(leg) | text
            del values["profile_snapshot"]  # never read back with a row (SR-E28-07)
            row = TradeGroupLegRow(
                **values, trade_group_id=group_id, filled_qty=Decimal(0), avg_entry_price=None,
                avg_exit_price=None, native_sl_confirmed=False, native_sl_confirmed_at=None,
                realised_pnl=Decimal(0), fees_paid=Decimal(0), submitted_at=None, closed_at=None,
                created_at=now, updated_at=now,
            )  # fmt: skip
            rows.append(_at_scale(row, _LEG_SCALES))
        return rows

    def _new_stops(
        self, stops: Sequence[NewRecordedStop], *, placed: UUID | None = None
    ) -> tuple[RecordedStopRow, ...]:
        """One request's insert (`insert_stops_statement`): its text bound, then each row's
        `symbol_code` domain, key and `ux_rs_in_flight`, then the orders the rows name, a foreign
        key met at the statement's end; `placed` is the order its transaction wrote."""
        _bindable(value for stop in stops for value in asdict(stop).values())
        rows: list[RecordedStopRow] = []
        now = self._clock()
        for stop in stops:
            if _SYMBOL.fullmatch(stop.symbol) is None:
                raise port.OrderConstraintError("symbol_code_check")
            if stop.id in self._stops or any(row.id == stop.id for row in rows):
                raise port.OrderConstraintError("recorded_stops_pkey")
            key = (stop.exchange_account_id, stop.symbol, stop.position_idx)
            if stop.kind == "stop_loss" and any(
                _in_flight(row) and (row.exchange_account_id, row.symbol, row.position_idx) == key
                for row in (*self._stops.values(), *rows)
            ):
                raise port.OrderConstraintError(UX_RS_IN_FLIGHT)
            row = RecordedStopRow(
                **asdict(stop), exchange_order_id=None, status="pending", created_at=now,
                answered_at=None, in_force_at=None, closed_at=None, released_at=None,
            )  # fmt: skip
            rows.append(_at_scale(row, _STOP_SCALES))
        named = {stop.order_id for stop in stops} - {None, placed}
        if any(order_id not in self._orders for order_id in named):
            raise port.OrderConstraintError("recorded_stops_order_id_fkey")
        return tuple(rows)

    def _new_anchor(self, anchor: NewAnchor) -> _StoredAnchor:
        """The anchor's insert, last (`insert_anchor_statement`): `ux_ia_principal_ref` writes
        nothing and answers `AnchorTakenError`, then its key."""
        stored = _StoredAnchor(anchor, self._clock())
        if any(held.key() == stored.key() for held in self._anchors.values()):
            raise AnchorTakenError(UX_IA_PRINCIPAL_REF)
        if anchor.id in self._anchors:
            raise port.OrderConstraintError("idempotency_anchors_pkey")
        return stored

    def _order_of(self, row: RecordedStopRow) -> Row | None:
        """The order a recorded stop names, when it is an order of the row's account."""
        order = None if row.order_id is None else self._orders.get(row.order_id)
        if order is None or order.exchange_account_id != row.exchange_account_id:
            return None
        return order

    def _unplaced(self, row: RecordedStopRow) -> bool:
        """`void_orphans_statement`'s proof that the row's entry was never placed."""
        order = self._order_of(row)
        if order is None:
            return False
        events = self._events.get(order.id, ())
        refused = any((e.row.from_state, e.row.to_state) == REFUSED_BY for e in events)
        return _holds(order, UNSENT_ENTRY) or (_holds(order, REFUSED_ENTRY) and refused)

    def _waiting(
        self, account_id: UUID, symbol: str, position_idx: int, cutoff: datetime | None
    ) -> tuple[RecordedStopRow, ...]:
        """`waiting_for_key_statement`'s rows: an unanswered one created at or before `cutoff`
        (any, when there is none), and an entry's whose order `WAITING_ENTRY` holds."""
        key = (account_id, symbol, position_idx)

        def waits(row: RecordedStopRow) -> bool:
            here = (row.exchange_account_id, row.symbol, row.position_idx) == key
            if not here or row.status != "pending":
                return False
            if row.answered_at is None and (cutoff is None or row.created_at <= cutoff):
                return True
            order = self._order_of(row) if row.source == "entry_attach" else None
            return order is not None and _holds(order, WAITING_ENTRY)

        return tuple(sorted(filter(waits, self._stops.values()), key=_age))

    def _commit_rows(self, *rows: _Stored) -> None:
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
            elif isinstance(row, ExecutionRow):
                self._fills[(row.exchange_account_id, row.exec_id)] = row
            elif isinstance(row, RecordedStopRow):
                self._stops[row.id] = row
            elif isinstance(row, TradeGroupRecord):
                self._groups[row.group.id] = row
            else:
                self._anchors[row.anchor.id] = row
        if error is not None:
            raise error


class InMemoryExecutionStore:
    """`ExecutionStore` over an `InMemoryOrderStore`'s tables: a fill and its order commit
    together or not at all."""

    def __init__(self, db: InMemoryOrderStore) -> None:
        self._db = db

    async def insert(self, execution: NewExecution) -> bool:
        await self._db._turn()
        return self._db._insert(execution)

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None:
        await asyncio.sleep(0)
        _bindable((exec_id,))  # the SELECT's `exec_id` is bound before it runs
        return self._db._fills.get((account_id, exec_id))

    async def commit_fill(self, fill: OrderFill) -> Step | None:
        await self._db._turn()
        return self._db._commit_fill(fill)


class InMemorySubmissionStore:
    """`SubmissionStore` over an `InMemoryOrderStore`'s tables (`submissions_sqlalchemy.py`'s
    contract, `tests/unit/oms/submission_contract.py`): `FirstPersist.check` before anything,
    then the group, the share-locked re-check, the leg, the order and its first event, the
    recorded stops and the anchor, each refused by the name Postgres gives it, then the write-ahead
    hook, bounded, and the commit; all or nothing. It holds no account, user, profile or definition
    rows, so no foreign key to one, and no group fired from a definition (`trg_tg_env`): `refuse`
    stands in for the re-check, and `seed_account` gives an account its environment, so a leg
    outside its group's environment is refused by `trg_tgl_env` as on Postgres (C-2.11)."""

    def __init__(
        self, db: InMemoryOrderStore, *, audit_timeout_s: float = SUBMISSION_AUDIT_TIMEOUT_S
    ) -> None:
        self._db = db
        self._audit_timeout_s = audit_timeout_s

    def seed_account(self, account: AccountRef) -> None:
        """`account`'s environment as its `exchange_accounts` row holds it, read off the trading
        port's `AccountRef`, for `trg_tgl_env` (SEC-2B1-03). A leg on an account never seeded
        passes the trigger here, as the fake holds no account rows; Postgres refuses such an
        account before the leg insert (`require_live`)."""
        self._db._environments[account.account_id] = account.environment

    def refuse(self, account_id: UUID, reason: SubmissionRefusal) -> None:
        """From now on the re-check refuses a first persist on `account_id`, as Postgres's does
        (SR-E28-15): `account_not_live` any order's, as for a soft-deleted account;
        `profile_changed` an entry's, as for a profile moved past its leg's version (a reduce-only
        order locks no profile)."""
        self._db._refusals[account_id] = reason

    async def create_first(
        self, first: FirstPersist, order: port.NewOrder, event: NewEvent
    ) -> FirstPersisted:
        first.check(order)
        port.require_exchange_record(event)
        await self._db._turn()
        persisted, rows = self._db._first_rows(first, order, event)
        hook = None if first.write_ahead is None else first.write_ahead(persisted)
        await self._db._audited_commit(hook, self._audit_timeout_s, *rows)
        return persisted


class InMemoryIdempotencyAnchorStore:
    """`IdempotencyAnchorStore` over an `InMemoryOrderStore`'s anchors: `find` by the principal,
    the operation and the key, the fingerprint compared and never returned (SR-E29-07); the
    outcome recorded once, by compare-and-set from none."""

    def __init__(self, db: InMemoryOrderStore) -> None:
        self._db = db

    async def find(
        self,
        created_by: UUID,
        operation: AnchorOperation,
        client_ref: str,
        request_sha256: str,
    ) -> AnchorRow | None:
        require_client_ref(client_ref)
        require_fingerprint(request_sha256)
        await asyncio.sleep(0)
        key = (created_by, operation, client_ref)
        held = next((a for a in self._db._anchors.values() if a.key() == key), None)
        return None if held is None else held.read(request_sha256)

    async def record_outcome(self, anchor_id: UUID, outcome: AnchorOutcome) -> bool:
        await self._db._turn()
        held = self._db._anchors.get(anchor_id)
        if held is None or held.outcome is not None:
            return False
        self._db._commit_rows(held._replace(outcome=outcome))
        return True


class InMemoryRecordedStopStore:
    """`RecordedStopStore` over an `InMemoryOrderStore`'s recorded stops
    (`recorded_stops_sqlalchemy.py`'s contract): one request's rows inserted together, each
    refused by the name Postgres gives it (`ux_rs_in_flight` among them); a settle by
    compare-and-set, a void (`refused`, `not_shown`) refused before anything with no write-ahead
    hook (C-2.9), as the SQL store refuses it; every read and update inside the account but the
    startup sweep over every account. A write's write-ahead hook is awaited, bounded, before its
    commit. `put_in_force` and `resolve` compare-and-set on `(status, answered_at)` as read."""

    def __init__(
        self, db: InMemoryOrderStore, *, audit_timeout_s: float = STOP_AUDIT_TIMEOUT_S
    ) -> None:
        self._db = db
        self._audit_timeout_s = audit_timeout_s

    async def insert(
        self, stops: Sequence[NewRecordedStop], *, write_ahead: InsertWriteAhead | None = None
    ) -> tuple[RecordedStopRow, ...]:
        check_request(stops)
        await self._db._turn()
        rows = self._db._new_stops(stops)
        hook = None if write_ahead is None else write_ahead(rows)
        await self._db._audited_commit(hook, self._audit_timeout_s, *rows)
        return rows

    async def settle(
        self,
        account_id: UUID,
        record_ids: Sequence[UUID],
        outcome: StopOutcome,
        *,
        at: datetime,
        write_ahead: SettleWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        ids = tuple(record_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("a settle names each row of the request once")
        port.require_aware("at", at)
        if outcome != "answered" and write_ahead is None:  # 21 Sec.3.3.11: no void unaudited
            raise ValueError("a void is audited write-ahead (C-2.9): no hook was given")
        await self._db._turn()
        rows = [self._db._stops.get(record_id) for record_id in ids]
        live = [
            row
            for row in rows
            if row is not None
            and (row.exchange_account_id, row.status) == (account_id, "pending")
            and row.answered_at is None
        ]
        if len(live) != len(ids):
            raise StaleRecordedStop
        settled = tuple(_settled(row, outcome, at) for row in live)
        hook = None if write_ahead is None else write_ahead(settled)
        await self._db._audited_commit(hook, self._audit_timeout_s, *settled)
        return settled

    async def for_order(self, account_id: UUID, order_id: UUID) -> tuple[RecordedStopRow, ...]:
        await asyncio.sleep(0)
        mine = (account_id, order_id)
        rows = (r for r in self._db._stops.values() if (r.exchange_account_id, r.order_id) == mine)
        return tuple(sorted(rows, key=_age))

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        await asyncio.sleep(0)
        _bindable((symbol,))  # the statement's value is bound before it runs
        key = (account_id, symbol, position_idx)
        live = (r for r in self._db._stops.values() if r.status in LIVE_STOP_STATUSES)
        mine = (r for r in live if (r.exchange_account_id, r.symbol, r.position_idx) == key)
        return tuple(sorted(mine, key=_age))

    async def for_exchange_order(
        self, account_id: UUID, exchange_order_id: str
    ) -> tuple[RecordedStopRow, ...]:
        port.require_exchange_order_id(exchange_order_id)
        await asyncio.sleep(0)
        _bindable((exchange_order_id,))  # the statement's value is bound before it runs
        mine = (r for r in self._db._stops.values() if r.exchange_account_id == account_id)
        return tuple(
            sorted((r for r in mine if r.exchange_order_id == exchange_order_id), key=_age)
        )

    async def release_and_bind(
        self,
        account_id: UUID,
        predecessor_id: UUID,
        successor_id: UUID,
        exchange_order_id: str,
        *,
        at: datetime,
        write_ahead: ReleaseWriteAhead,
    ) -> tuple[RecordedStopRow, RecordedStopRow]:
        port.require_exchange_order_id(exchange_order_id)
        port.require_aware("at", at)
        if write_ahead is None:  # 21 Sec.3.3.11: no release unaudited
            raise ValueError("a release is audited write-ahead (C-2.9): no hook was given")
        await self._db._turn()
        _bindable((exchange_order_id,))
        stops = self._db._stops
        old, new = stops.get(predecessor_id), stops.get(successor_id)
        holds = (account_id, exchange_order_id)
        held = {
            r.id for r in stops.values() if (r.exchange_account_id, r.exchange_order_id) == holds
        }
        live = LIVE_STOP_STATUSES
        # `held == {old.id}` is two predicates: the predecessor holds the id, and no other row of
        # the account does (never two, in any status). The first makes the chain's `== account_id`
        # redundant: `old` is the account's already (`held` reads only its rows), and `new` is
        # `old`'s account. The check stays, as the SQL's release and bind each filter by account.
        if not (
            old and new and old.exchange_account_id == new.exchange_account_id == account_id
            and old.status in live and old.released_at is None and held == {old.id}  # one holder
            and new.status in live and new.released_at is None and new.exchange_order_id is None
            and (new.symbol, new.position_idx, new.kind) == (old.symbol, old.position_idx, old.kind)
            and (new.created_at, new.id) > (old.created_at, old.id)
        ):  # fmt: skip
            raise RecordedStopNotBindable
        released = replace(old, exchange_order_id=None, released_at=at)
        bound = replace(new, exchange_order_id=exchange_order_id)
        hook = write_ahead((released, bound))
        await self._db._audited_commit(hook, self._audit_timeout_s, released, bound)
        return released, bound

    async def waiting_for_key(
        self,
        account_id: UUID,
        symbol: str,
        position_idx: int,
        *,
        now: datetime,
        bound_s: float | None,
    ) -> tuple[RecordedStopRow, ...]:
        cutoff = request_cutoff(now, bound_s)  # a naive `now` is refused before the read
        await asyncio.sleep(0)
        return self._db._waiting(account_id, symbol, position_idx, cutoff)

    async def void_orphans(
        self, scope: UUID | SweepScope, *, at: datetime, write_ahead: SweepWriteAhead
    ) -> tuple[SweptStop, ...]:
        port.require_aware("at", at)
        if not isinstance(scope, UUID) and scope is not EVERY_ACCOUNT:
            raise TypeError("the sweep covers one account, or EVERY_ACCOUNT")
        await self._db._turn()
        voided: list[RecordedStopRow] = []
        swept: list[SweptStop] = []
        for row in sorted(self._db._stops.values(), key=_age):
            if scope != EVERY_ACCOUNT and scope != row.exchange_account_id:
                continue
            if (row.source, row.status) != ("entry_attach", "pending") or row.order_id is None:
                continue
            if self._db._unplaced(row):
                voided.append(replace(row, status="void", closed_at=at))
                swept.append(SweptStop(row.id, row.exchange_account_id, row.order_id, row.kind))
        hook = write_ahead(tuple(swept)) if swept else None
        await self._db._audited_commit(hook, self._audit_timeout_s, *voided)
        return tuple(swept)

    async def waiting_keys(
        self, account_id: UUID, *, now: datetime, bound_s: float | None
    ) -> tuple[tuple[str, int], ...]:
        cutoff = request_cutoff(now, bound_s)  # a naive `now` is refused before the read
        await asyncio.sleep(0)
        mine = {(r.symbol, r.position_idx) for r in self._db._stops.values()
                if r.exchange_account_id == account_id}  # fmt: skip
        rows = sorted(
            (r for k in mine for r in self._db._waiting(account_id, *k, cutoff)), key=_age
        )
        keys = ((r.symbol, r.position_idx) for r in rows)
        return tuple(dict.fromkeys(keys))

    async def in_force_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        await asyncio.sleep(0)
        key, rows = (account_id, symbol, position_idx, "in_force"), self._db._stops.values()
        shown = (
            r for r in rows if (r.exchange_account_id, r.symbol, r.position_idx, r.status) == key
        )
        return tuple(sorted(shown, key=lambda r: r.kind))

    async def database_now(self) -> datetime:
        await asyncio.sleep(0)
        return self._db._clock()

    async def put_in_force(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        *,
        at: datetime,
        write_ahead: InForceWriteAhead | None = None,
    ) -> InForce:
        check_in_force(account_id, rows)
        port.require_aware("at", at)
        await self._db._turn()
        held = self._as_read(account_id, rows)
        born = {r.kind: r.created_at for r in held}
        key, ids = (account_id, rows[0].symbol, rows[0].position_idx), {r.id for r in rows}
        replaced = tuple(
            replace(r, status="replaced", answered_at=r.answered_at or at, closed_at=at)
            for r in sorted(self._db._stops.values(), key=lambda r: r.id)
            if (r.exchange_account_id, r.symbol, r.position_idx) == key
            and r.id not in ids
            and r.kind in born
            and (r.status == "in_force" or (r.status == "pending" and r.answered_at is not None
                                            and r.created_at < born[r.kind]))
        )  # fmt: skip
        shown = tuple(
            replace(r, status="in_force", answered_at=r.answered_at or at, in_force_at=at)
            for r in held
        )
        hook = None if write_ahead is None else write_ahead((*replaced, *shown))
        await self._db._audited_commit(hook, self._audit_timeout_s, *replaced, *shown)
        return InForce(replaced=replaced, in_force=shown)

    async def resolve(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        outcome: ResolveOutcome,
        *,
        at: datetime,
        position_state: FillPosition | None = None,
        write_ahead: ResolveWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        check_resolve(rows, outcome, at, position_state, write_ahead)
        await self._db._turn()
        held = self._as_read(account_id, rows)
        if outcome in ("answered", "replaced"):
            done = tuple(replace(r, answered_at=r.answered_at or at) for r in held)
            if outcome == "replaced":
                done = tuple(replace(r, status="replaced", closed_at=at) for r in done)
        else:
            done = tuple(replace(r, status="void", closed_at=at) for r in held)
        hook = None if write_ahead is None else write_ahead(done, position_state)
        await self._db._audited_commit(hook, self._audit_timeout_s, *done)
        return done

    def _as_read(self, account_id: UUID, rows: Sequence[RecordedStopRow]) -> list[RecordedStopRow]:
        """The stored rows if each is as read (account, key, kind, `pending`, `answered_at`)."""
        held = [self._db._stops.get(row.id) for row in rows]
        if any(
            h is None
            or (h.exchange_account_id, h.symbol, h.position_idx, h.kind, h.status, h.answered_at)
            != (account_id, r.symbol, r.position_idx, r.kind, "pending", r.answered_at)
            for h, r in zip(held, rows, strict=True)
        ):
            raise StaleRecordedStop
        return [h for h in held if h is not None]


class FakeClockHealth:
    """A `ClockHealth` (`ports.py`) on the caller's monotonic clock, answering as
    `ingestion.clock.ClockGuard` does: before the first measurement `assert_healthy` raises
    `ClockDriftError` and the age is `inf`; `measure(offset_ms)` takes one at the clock's now,
    healthy while its offset is within `hard_threshold_ms`. `resync_after_signature_failure`
    records its reason in `resyncs`, then measures `resync_offset_ms`, or raises `resync_error`
    when one is set (a burst no sample answered), leaving the last measurement standing."""

    def __init__(
        self, monotonic: Callable[[], float], *, hard_threshold_ms: float = 2_000.0
    ) -> None:
        self._monotonic = monotonic
        self._hard_threshold_ms = hard_threshold_ms
        self._measured_at: float | None = None
        self._offset_ms = 0.0
        self.resync_offset_ms = 0.0
        self.resync_error: Exception | None = None
        self.resyncs: list[str] = []

    def measure(self, offset_ms: float = 0.0) -> None:
        """A successful measurement now: the server's clock minus ours, `offset_ms`."""
        self._measured_at, self._offset_ms = self._monotonic(), offset_ms

    def assert_healthy(self) -> None:
        if self._measured_at is None:
            raise ClockDriftError("clock offset has never been measured")
        if abs(self._offset_ms) > self._hard_threshold_ms:
            raise ClockDriftError("clock offset exceeds the hard threshold")

    def offset_age_s(self) -> float:
        if self._measured_at is None:
            return math.inf
        return max(0.0, self._monotonic() - self._measured_at)

    async def resync_after_signature_failure(self, *, reason: str) -> int:
        self.resyncs.append(reason)
        await asyncio.sleep(0)
        if self.resync_error is not None:
            raise self.resync_error
        self.measure(self.resync_offset_ms)
        return round(self.resync_offset_ms * 1_000)


class InMemoryTradingAccounts:
    """A `TradingAccounts` (`ports.py`) over the accounts a test seeds. `trading_account` records
    the id it is asked for in `asked` and answers that id's `AccountRef`; an id with none is
    `AccountScopeDenied`, nothing read, as the real port refuses an account the OMS does not
    trade. `seed(..., as_id=)` answers a ref for another id, a broken resolver."""

    def __init__(self, *accounts: AccountRef) -> None:
        self._accounts: dict[AccountId, AccountRef] = {}
        self.asked: list[AccountId] = []
        for account in accounts:
            self.seed(account)

    def seed(self, account: AccountRef, *, as_id: AccountId | None = None) -> None:
        self._accounts[account.account_id if as_id is None else as_id] = account

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        self.asked.append(account_id)
        await asyncio.sleep(0)
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountScopeDenied
        return account


class InMemoryForeignOrderLockout:
    """A `ForeignOrderLockout` (`ports.py`, 24 Sec.8.10): `findings` holds each account's
    findings, and an account is open while it holds any. An open that names a finding the account
    holds changes nothing; `opens` counts every call, so a test sees the repeats."""

    def __init__(self) -> None:
        self.findings: dict[AccountId, set[tuple[Finding, str]]] = {}
        self.opens = 0

    def is_open(self, account_id: AccountId) -> bool:
        return bool(self.findings.get(account_id))

    async def open(self, account_id: AccountId, *, finding: Finding, key: str) -> None:
        self.opens += 1
        await asyncio.sleep(0)
        self.findings.setdefault(account_id, set()).add((finding, key))


class InMemoryStreamedAccounts:
    """A `StreamedAccounts` (`ports.py`, 24 Sec.8.12) over the accounts a test seeds: each read
    counts in `reads` and answers them, or raises `error` when one is set (a store that cannot
    answer), leaving the seeded set as it was."""

    def __init__(self, *accounts: AccountId) -> None:
        self.accounts: set[AccountId] = set(accounts)
        self.error: Exception | None = None
        self.reads = 0

    async def streamed_accounts(self) -> frozenset[AccountId]:
        self.reads += 1
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return frozenset(self.accounts)


class InMemoryReconciliationRequests:
    """A `ReconciliationRequests` (`ports.py`): `requests` holds each request, in order, with its
    reason; nothing runs a pass."""

    def __init__(self) -> None:
        self.requests: list[tuple[AccountId, ResyncReason]] = []

    async def request_reconciliation(self, account_id: AccountId, *, reason: ResyncReason) -> None:
        await asyncio.sleep(0)
        self.requests.append((account_id, reason))


class InMemoryAccountNotices:
    """An `AccountNotices` (`ports.py`, 23-ws-protocol.md Sec.15.9): `published` holds each notice,
    in order. Synchronous, as the port is: it never awaits."""

    def __init__(self) -> None:
        self.published: list[tuple[AccountId, AccountNoticeReason]] = []

    def publish(self, account_id: AccountId, *, reason: AccountNoticeReason) -> None:
        self.published.append((account_id, reason))
