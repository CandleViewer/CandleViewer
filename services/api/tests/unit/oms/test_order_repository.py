"""M14 `OrderRepository` / `OrderEventRepository` over a stub store (E29-T01 #845).

The facade's own behaviour: `DuplicateOrderLinkId` for the unique index (Gherkin "Idempotency is
enforced by the database", unit half), the 24 Sec.8.3 rule 5 lookup the #846 allocator uses, the
account passed through on every read, and the `order_link_id` logged on every write (ADR-0006
rule 1). The stores themselves are tested in `tests/unit/storage/test_orders_store.py` and against
Postgres in `tests/integration/storage/test_orders_store_pg.py`. Below them: the execution,
position and snapshot repositories and `oms_db_write_seconds{table}` on every write. Last, E29-T04's
first persist, replay anchor and recorded stops: their refusals as the OMS's typed errors, raised
`from None`, and log lines that carry ids only.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE, OMS_WRITE_BUCKETS
from candleviewer.oms import (
    DuplicateOrderLinkId,
    ExecutionRepository,
    OrderEventRepository,
    OrderRepository,
    PositionRepository,
    PositionSnapshotRepository,
    WriteTimer,
)
from candleviewer.oms.errors import (
    AnchorTaken,
    AuditNotDurable,
    OmsError,
    StopRequestInFlight,
    SubmissionRefused,
)
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_link_allocator import OrderLinkIdAllocator, OrderLinkLookup
from candleviewer.oms.repository import (
    WRITE_TABLES,
    IdempotencyAnchorRepository,
    RecordedStopRepository,
    SubmissionRepository,
)
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.idempotency_anchors import AnchorOutcome, NewAnchor
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    CommittedStep,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderRow,
    OrderTransition,
)
from candleviewer.storage.repositories.orders_sqlalchemy import OMS_STATEMENT_TIMEOUT_MS
from candleviewer.storage.repositories.positions import NewPositionSnapshot, PositionState
from candleviewer.storage.repositories.recorded_stops import (
    NewRecordedStop,
    RecordedStopRow,
    SweptStop,
)
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
)
from candleviewer.storage.repositories.trade_groups import TradeGroupStoreRefusedError

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ACCOUNT, ORDER = uuid.UUID(int=1), uuid.UUID(int=2)
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id


def _row(**over: Any) -> OrderRow:
    values: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    values |= {"id": ORDER, "exchange_account_id": ACCOUNT, "order_link_id": LINK}
    return OrderRow(**(values | {"state": "pending_submit", "qty": Decimal("0.010")} | over))


def _event_row(**over: Any) -> OrderEventRow:
    values: dict[str, Any] = {name: None for name in EVENT_FIELDS}
    values |= {"id": 9, "order_id": ORDER, "seq": 1, "kind": "ack", "order_link_id": LINK}
    return OrderEventRow(**(values | over))


ORDER_IN = NewOrder(
    id=ORDER, exchange_account_id=ACCOUNT, order_link_id=LINK, symbol="BTCUSDT", side="Buy",
    intent="entry", order_type="Market", qty=Decimal("0.010"), stop_loss=Decimal("62000"),
)  # fmt: skip
EVENT_IN = NewOrderEvent(kind="local_create", source="local", event_ts=T0)


class _Store:
    """Stub `OrderStore` and `OrderEventStore`: records calls, returns canned rows."""

    def __init__(self, *, error: Exception | None = None, taken: frozenset[str] = frozenset()):
        self.error, self.taken = error, taken
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if self.error is not None:
            raise self.error

    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        self._call("create", order, first_event)
        return _row(stop_loss=order.stop_loss)

    async def transition(self, step: OrderTransition) -> CommittedStep:
        raise NotImplementedError  # the write-ahead step's tests: write_ahead_contract.py

    async def get(self, account_id: uuid.UUID, order_id: uuid.UUID) -> OrderRow | None:
        self._call("get", account_id, order_id)
        return _row()

    async def get_by_link_id(self, account_id: uuid.UUID, order_link_id: str) -> OrderRow | None:
        self._call("get_by_link_id", account_id, order_link_id)
        return None

    async def list_open(
        self, account_id: uuid.UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        self._call("list_open", account_id, symbol=symbol)
        return (_row(),)

    async def link_id_taken(self, order_link_id: str) -> bool:
        self._call("link_id_taken", order_link_id)
        return order_link_id in self.taken

    async def append(
        self, account_id: uuid.UUID, order_id: uuid.UUID, event: NewOrderEvent
    ) -> OrderEventRow:
        self._call("append", account_id, order_id, event)
        return _event_row(kind=event.kind, seq=3)

    async def list_for_order(
        self, account_id: uuid.UUID, order_id: uuid.UUID, *, after_seq: int = -1, limit: int = 500
    ) -> tuple[OrderEventRow, ...]:
        self._call("list_for_order", account_id, order_id, after_seq=after_seq, limit=limit)
        return (_event_row(),)


async def test_create_returns_the_stored_row_and_logs_its_order_link_id() -> None:
    store = _Store()
    with capture_logs() as logs:
        row = await OrderRepository(store).create(ORDER_IN, EVENT_IN)
    assert row.stop_loss == Decimal("62000")  # the native stop travels with the row (C-2.6)
    assert store.calls == [("create", (ORDER_IN, EVENT_IN), {})]
    assert logs == [
        {
            "event": "oms_order_created",
            "log_level": "info",
            "order_link_id": LINK,
            "order_id": str(ORDER),
            "account_id": str(ACCOUNT),
            "state": "pending_submit",
        }
    ]


async def test_idempotency_is_enforced_by_the_database_as_duplicate_order_link_id() -> None:
    """Gherkin "Idempotency is enforced by the database": the unique index's refusal surfaces as
    `DuplicateOrderLinkId`, an `OmsError`, and nothing is logged as written."""
    store = _Store(error=OrderConstraintError("ux_orders_link"))
    with capture_logs() as logs, pytest.raises(DuplicateOrderLinkId) as err:
        await OrderRepository(store).create(ORDER_IN, EVENT_IN)
    assert isinstance(err.value, OmsError) and err.value.order_link_id == LINK
    assert str(err.value) == f"order_link_id {LINK} is already stored"
    assert (err.value.__cause__, err.value.__suppress_context__, logs) == (None, True, [])


@pytest.mark.parametrize("constraint", ["ux_orders_exch_id", "orders_pkey", "ord_cum"])
async def test_any_other_constraint_error_passes_through_unchanged(constraint: str) -> None:
    error = OrderConstraintError(constraint)
    with pytest.raises(OrderConstraintError) as err:
        await OrderRepository(_Store(error=error)).create(ORDER_IN, EVENT_IN)
    assert err.value is error


async def test_reads_pass_the_account_through() -> None:
    store = _Store()
    repo = OrderRepository(store)
    assert (await repo.get(ACCOUNT, ORDER)) == _row()
    assert await repo.get_by_link_id(ACCOUNT, LINK) is None
    assert await repo.list_open(ACCOUNT, symbol="ETHUSDT") == (_row(),)
    assert store.calls == [
        ("get", (ACCOUNT, ORDER), {}),
        ("get_by_link_id", (ACCOUNT, LINK), {}),
        ("list_open", (ACCOUNT,), {"symbol": "ETHUSDT"}),
    ]


async def test_exists_is_the_rule_5_lookup_the_allocator_uses() -> None:
    def link(seq: int) -> OrderLinkIdParts:
        return OrderLinkIdParts.generate(
            mode="exchange", environment="demo", group_id=GroupId(uuid.UUID(int=7)),
            account_id=AccountId(ACCOUNT), seq=seq, purpose="entry",
        )  # fmt: skip

    store = _Store(taken=frozenset({link(0).value}))
    lookup: OrderLinkLookup = OrderRepository(store)  # mypy checks the structural match
    allocated = await OrderLinkIdAllocator(lookup).allocate(link(0))
    assert allocated.order_link_id == link(1).value
    assert [c[1] for c in store.calls] == [(link(0).value,), (link(1).value,)]


async def test_append_returns_the_event_and_logs_order_link_id_seq_and_kind() -> None:
    store = _Store()
    event = NewOrderEvent(kind="ack", source="rest", event_ts=T0, payload={"retCode": 0})
    with capture_logs() as logs:
        got = await OrderEventRepository(store).append(ACCOUNT, ORDER, event)
    assert (got.seq, got.kind, store.calls) == (3, "ack", [("append", (ACCOUNT, ORDER, event), {})])
    assert logs == [
        {
            "event": "oms_order_event_appended",
            "log_level": "info",
            "order_link_id": LINK,
            "order_id": str(ORDER),
            "seq": 3,
            "kind": "ack",
        }
    ]


async def test_list_for_order_passes_the_account_and_the_page_through() -> None:
    store = _Store()
    got = await OrderEventRepository(store).list_for_order(ACCOUNT, ORDER, after_seq=4, limit=20)
    assert got == (_event_row(),)
    assert store.calls == [("list_for_order", (ACCOUNT, ORDER), {"after_seq": 4, "limit": 20})]


async def test_a_failed_append_logs_nothing() -> None:
    with capture_logs() as logs, pytest.raises(OrderConstraintError):
        await OrderEventRepository(_Store(error=OrderConstraintError("oe_latency"))).append(
            ACCOUNT, ORDER, EVENT_IN
        )
    assert logs == []


# -- executions, positions, snapshots, and `oms_db_write_seconds` -------------------------------

FILL = NewExecution(
    exchange_account_id=ACCOUNT, exec_id="E1", symbol="BTCUSDT", side="Buy",
    exec_qty=Decimal("0.010"), exec_price=Decimal("63099.80"), exec_value=Decimal("630.998"),
    exec_type="Trade", is_maker=False, exec_ts=T0, order_id=ORDER, order_link_id=LINK,
)  # fmt: skip
STATE = PositionState(exchange_account_id=ACCOUNT, symbol="BTCUSDT", size=Decimal("0.010"))
SNAP = NewPositionSnapshot(
    exchange_account_id=ACCOUNT, symbol="BTCUSDT", size=Decimal("0.010"), reason="ws_push"
)


class _AnyStore:
    """A stub of any store: records each call and answers `result`, or raises `error`."""

    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result, self.error = result, error
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Callable[..., Awaitable[object]]:
        async def call(*args: Any, **kwargs: Any) -> object:  # a keyword (`at=`) is not recorded
            self.calls.append((name, args))
            if self.error is not None:
                raise self.error
            return self.result

        return call


#: What a write-ahead step's store returns: the order moved from `pending_submit` to `accepted`.
_DONE = CommittedStep(
    _row(state="accepted"), _event_row(from_state="pending_submit", source="rest")
)
_FILLED = cast(Any, SimpleNamespace(execution=FILL, step=SimpleNamespace(order_id=ORDER)))
#: E29-T04's writes: a reduce-only order's first persist, its anchor's outcome, a stop request.
REF, SHA = "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59", "ab" * 32
ANCHOR = uuid.UUID(int=3)
REDUCE = replace(
    ORDER_IN, reduce_only=True, stop_loss=None, state="pending_submit", lifecycle_state="validated"
)
FIRST = FirstPersist(
    anchor=NewAnchor(id=ANCHOR, created_by=uuid.UUID(int=4), operation="placeOrder",
                     client_ref=REF, request_sha256=SHA, order_id=ORDER),
)  # fmt: skip
STOP = NewRecordedStop(
    id=uuid.UUID(int=5), exchange_account_id=ACCOUNT, symbol="BTCUSDT", position_idx=0,
    position_side="Buy", kind="stop_loss", source="trading_stop", order_id=None,
    tpsl_mode="Full", trigger_price=Decimal("62000"), size=None,
    audit_record_id=uuid.UUID(int=6), actor_user_id=None,
)  # fmt: skip
STOP_ROW = RecordedStopRow(
    **{f.name: getattr(STOP, f.name) for f in fields(NewRecordedStop)},
    exchange_order_id=None, status="pending", created_at=T0, answered_at=None, in_force_at=None,
    closed_at=None, released_at=None,
)  # fmt: skip
OUTCOME = AnchorOutcome(status=202, decided_at=T0)
PERSISTED = FirstPersisted(order=_row(), anchor_id=ANCHOR, group=None, recorded_stops=())
#: Each write by its table (the label it is timed on), and the call where a table has two.
_WRITES: dict[str, tuple[Callable[[Any, WriteTimer], Awaitable[object]], object]] = {
    "orders": (lambda s, t: OrderRepository(s, t).create(ORDER_IN, EVENT_IN), _row()),
    "orders transition": (lambda s, t: OrderRepository(s, t).transition(cast(Any, None)), _DONE),
    "executions commit_fill": (lambda s, t: ExecutionRepository(s, t).commit_fill(_FILLED), _DONE),
    "order_events": (lambda s, t: OrderEventRepository(s, t).append(ACCOUNT, ORDER, EVENT_IN),
                     _event_row()),
    "executions": (lambda s, t: ExecutionRepository(s, t).insert(FILL), True),
    "positions": (lambda s, t: PositionRepository(s, t).upsert(STATE), object()),
    "position_snapshots": (lambda s, t: PositionSnapshotRepository(s, t).append(SNAP), object()),
    "orders create_first": (lambda s, t: SubmissionRepository(s, t).create_first(FIRST, REDUCE,
                            EVENT_IN), PERSISTED),
    "idempotency_anchors": (lambda s, t: IdempotencyAnchorRepository(s, t).record_outcome(ANCHOR,
                            OUTCOME), True),
    "recorded_stops": (lambda s, t: RecordedStopRepository(s, t).record([STOP]), (STOP_ROW,)),
    "recorded_stops settle": (lambda s, t: RecordedStopRepository(s, t).settle(ACCOUNT,
                              [STOP.id], "answered", at=T0), (STOP_ROW,)),
}  # fmt: skip


@pytest.mark.parametrize("table", sorted(_WRITES))
async def test_every_write_is_timed_on_its_table_a_failed_one_too(table: str) -> None:
    """One observation per store call, its clock delta, a refused write included: it held the
    order path as long."""
    metrics = Metrics("dev")
    histogram = metrics.histogram(
        "oms_db_write_seconds", "OMS writes", ("table",), buckets=OMS_WRITE_BUCKETS, max_series=7
    )
    ticks = iter([10.0, 10.25, 20.0, 22.0])
    timer = WriteTimer(histogram, clock=lambda: next(ticks))
    write, result = _WRITES[table]
    assert await write(_AnyStore(result), timer) is result
    with pytest.raises(OrderConstraintError):
        await write(_AnyStore(error=OrderConstraintError("ord_cum")), timer)
    sample, labels = metrics.registry.get_sample_value, {"env": "dev", "table": table.split()[0]}
    assert sample("oms_db_write_seconds_count", labels) == 2
    assert sample("oms_db_write_seconds_sum", labels) == 2.25


def test_the_catalogue_bounds_the_table_label_by_the_tables_written() -> None:
    (spec,) = (s for s in CATALOGUE if s.name == "oms_db_write_seconds")
    assert (spec.kind, spec.labels, spec.buckets) == ("histogram", ("table",), OMS_WRITE_BUCKETS)
    assert spec.max_series == len(WRITE_TABLES) == len({table.split()[0] for table in _WRITES})
    cap = OMS_STATEMENT_TIMEOUT_MS / 1000  # a p99 near the store's statement cap shows apart
    assert {cap - 0.5, cap, cap + 0.5} <= set(OMS_WRITE_BUCKETS)


@pytest.mark.parametrize(
    ("fill", "stored", "event", "level"),
    [(FILL, True, "oms_execution_stored", "info"),
     (replace(FILL, order_id=None, order_link_id=None), False, "oms_execution_duplicate", "debug")],
)  # fmt: skip
async def test_an_execution_write_logs_its_ids(
    fill: NewExecution, stored: bool, event: str, level: str
) -> None:
    with capture_logs() as logs:
        assert await ExecutionRepository(cast(Any, _AnyStore(stored))).insert(fill) is stored
    order = {"order_link_id": fill.order_link_id, "order_id": fill.order_id and str(fill.order_id)}
    ids = order | {"account_id": str(ACCOUNT), "exec_id": "E1"}
    assert logs == [{"event": event, "log_level": level, **ids}]


_IDS = {"order_link_id": LINK, "order_id": str(ORDER), "account_id": str(ACCOUNT)}
_STEP = {"state": "accepted", "from_state": "pending_submit", "seq": 1, "source": "rest"}
_MOVED = {"log_level": "info", **_IDS, **_STEP}


@pytest.mark.parametrize(
    ("repo", "call", "result", "line"),
    [(OrderRepository, "transition", _DONE, {"event": "oms_order_transitioned", **_MOVED}),
     (ExecutionRepository, "commit_fill", _DONE,
      {"event": "oms_order_filled", **_MOVED, "exec_id": "E1"}),
     (ExecutionRepository, "commit_fill", None,
      {"event": "oms_execution_duplicate", "log_level": "debug", **_IDS, "exec_id": "E1"})],
)  # fmt: skip
async def test_a_step_logs_its_ids_and_state(
    repo: Any, call: str, result: object, line: dict[str, object]
) -> None:
    """ADR-0006 rule 1 and E29-T08's fields: a step's line carries its order's ids, account and
    state, with the state it left; a duplicate fill's line its ids and account."""
    with capture_logs() as logs:
        assert await getattr(repo(_AnyStore(result)), call)(_FILLED) is result
    assert logs == [line]


async def test_the_execution_and_position_reads_pass_the_account_through() -> None:
    store = _AnyStore(rows := object())
    got: list[object] = [
        await ExecutionRepository(cast(Any, store)).get(ACCOUNT, "E7"),
        await PositionRepository(cast(Any, store)).list_open(ACCOUNT),
        await PositionRepository(cast(Any, store)).list_unprotected(ACCOUNT),
    ]
    assert all(answer is rows for answer in got)
    reads = [("get", (ACCOUNT, "E7")), ("list_open", (ACCOUNT,)), ("list_unprotected", (ACCOUNT,))]
    assert store.calls == reads


# -- E29-T04: the first persist, the replay anchor and the recorded stops -------------------------

_TYPED = [
    (OrderConstraintError("ux_orders_link"), DuplicateOrderLinkId),
    (OrderConstraintError("ux_rs_in_flight"), StopRequestInFlight),
    (AnchorTakenError("ux_ia_principal_ref"), AnchorTaken),
    (AnchorTakenError("ux_tg_creator_ref"), AnchorTaken),
    (TradeGroupStoreRefusedError("account_not_live"), SubmissionRefused),
    (TradeGroupStoreRefusedError("profile_changed"), SubmissionRefused),
    (WriteAheadTimeout("write-ahead audit exceeded 0.5 s"), AuditNotDurable),
]


@pytest.mark.parametrize(("error", "typed"), _TYPED, ids=[t.__name__ for _, t in _TYPED])
async def test_a_refused_first_persist_is_a_typed_oms_error_with_nothing_chained(
    error: Exception, typed: type[OmsError]
) -> None:
    """B1 reads any `TimeoutError` as an outcome in doubt; `AuditNotDurable` is a refusal, as the
    unit of work rolled back, so it is never one (R5)."""
    with capture_logs() as logs, pytest.raises(typed) as err:
        await SubmissionRepository(cast(Any, _AnyStore(error=error))).create_first(
            FIRST, REDUCE, EVENT_IN
        )
    assert (err.value.__cause__, err.value.__suppress_context__, logs) == (None, True, [])
    assert not isinstance(err.value, TimeoutError)
    assert getattr(err.value, "constraint", getattr(err.value, "reason", "")) in str(error)


async def test_any_other_refusal_of_the_first_persist_passes_unchanged() -> None:
    error = OrderConstraintError("tg_ref_fmt")
    with pytest.raises(OrderConstraintError) as err:
        await SubmissionRepository(cast(Any, _AnyStore(error=error))).create_first(
            FIRST, REDUCE, EVENT_IN
        )
    assert err.value is error


async def test_a_first_persist_logs_ids_only() -> None:
    with capture_logs() as logs:
        await SubmissionRepository(cast(Any, _AnyStore(PERSISTED))).create_first(
            FIRST, REDUCE, EVENT_IN
        )
    assert logs == [
        {
            "event": "oms_order_first_persisted", "log_level": "info", **_IDS,
            "state": "pending_submit", "anchor_id": str(ANCHOR), "trade_group_id": None,
            "recorded_stops": [],
        }
    ]  # fmt: skip


async def test_the_anchor_is_found_by_its_canonical_key_on_place_order() -> None:
    store = _AnyStore(None)
    found = await IdempotencyAnchorRepository(cast(Any, store)).find(
        uuid.UUID(int=4), uuid.UUID(REF.upper()), SHA
    )
    assert found is None
    assert store.calls == [("find", (uuid.UUID(int=4), "placeOrder", REF, SHA))]


async def test_a_stop_request_in_flight_refuses_the_next_one_and_logs_nothing() -> None:
    error = OrderConstraintError("ux_rs_in_flight")
    with capture_logs() as logs, pytest.raises(StopRequestInFlight) as err:
        await RecordedStopRepository(cast(Any, _AnyStore(error=error))).record([STOP])
    assert (err.value.__cause__, logs) == (None, [])


async def test_the_anchor_and_stop_lines_carry_no_key_fingerprint_or_price() -> None:
    with capture_logs() as logs:
        await IdempotencyAnchorRepository(cast(Any, _AnyStore(True))).record_outcome(
            ANCHOR, OUTCOME
        )
        await RecordedStopRepository(cast(Any, _AnyStore((STOP_ROW,)))).record([STOP])
    assert [line["event"] for line in logs] == ["oms_anchor_decided", "oms_stops_recorded"]
    text = repr(logs)
    assert REF not in text and SHA not in text and "62000" not in text
    assert logs[1]["record_id"] == str(STOP.id) and logs[1]["kind"] == "stop_loss"


async def _no_audit(swept: tuple[SweptStop, ...]) -> None:
    return None


async def test_the_sweep_logs_each_voided_row_by_its_ids() -> None:
    swept = (SweptStop(STOP.id, ACCOUNT, ORDER, "take_profit"),)
    store = _AnyStore(swept)
    with capture_logs() as logs:
        got = await RecordedStopRepository(cast(Any, store)).void_orphans(
            None, at=T0, write_ahead=_no_audit
        )
    assert got == swept and store.calls == [("void_orphans", (None,))]
    assert logs == [
        {"event": "oms_stop_unplaced_entry_swept", "log_level": "warning",
         "record_id": str(STOP.id), "account_id": str(ACCOUNT), "order_id": str(ORDER),
         "kind": "take_profit"}
    ]  # fmt: skip


async def test_a_sweep_whose_audit_did_not_land_voided_nothing() -> None:
    error = WriteAheadTimeout("write-ahead audit exceeded 5.0 s")
    with pytest.raises(AuditNotDurable) as err:
        await RecordedStopRepository(cast(Any, _AnyStore(error=error))).void_orphans(
            ACCOUNT, at=T0, write_ahead=_no_audit
        )
    assert err.value.__cause__ is None and not isinstance(err.value, TimeoutError)
