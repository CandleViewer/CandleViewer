"""E29-T04 (#913) S3-H H2b: the complete read and its writes (21 Sec.3.3.11, 24 Sec.8.8 rule 6), on
`FakeTradingPort`, the in-memory order store and a recording store double."""

from __future__ import annotations

import ast
import asyncio
import inspect
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import ServiceUnavailableError
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, Order, Position
from candleviewer.oms import commands, stop_resolution
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.oms.stop_resolution import (
    SPAN_HELD,
    TRAIL_HELD,
    CompleteRead,
    PositionState,
    StopResolver,
    VoidReason,
    VoidWriteAhead,
)
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, NewOrderEvent, OrderRow
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.oms.command_rig import (
    LIVE_ACCOUNT,
    STOP,
    T0,
    T0_US,
    exchange_order,
    new_order,
    position,
    ref,
)
from tests.unit.oms.test_stop_decision import (
    KEY,
    SECOND_US,
    TP,
    fired,
    flat,
    request_rows,
    stop_row,
    tpsl_order,
)

NOW = T0 + timedelta(seconds=30)
UID = "100001"


@dataclass
class Store:
    """A recording `ResolutionStore`: `rows` is what `waiting_for_key` lists, `in_force` what
    `in_force_for_key` does."""

    rows: list[RecordedStopRow] = field(default_factory=list)
    in_force: list[RecordedStopRow] = field(default_factory=list)
    calls: list[tuple[str, tuple[UUID, ...], str, PositionState | None]] = field(
        default_factory=list
    )

    async def waiting_for_key(
        self, account_id: UUID, symbol: str, position_idx: int, *, now: datetime,
        bound_s: float | None,
    ) -> list[RecordedStopRow]:  # fmt: skip
        return list(self.rows)

    async def in_force_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> list[RecordedStopRow]:
        return list(self.in_force)

    async def put_in_force(self, account_id: UUID, rows: Any, *, at: datetime) -> object:
        self.calls.append(("put_in_force", tuple(r.id for r in rows), "in_force", None))
        return tuple(rows)

    async def resolve(
        self, account_id: UUID, rows: Any, outcome: str, *, at: datetime,
        write_ahead: VoidWriteAhead | None = None, position_state: PositionState | None = None,
    ) -> tuple[RecordedStopRow, ...]:  # fmt: skip
        if write_ahead is not None:
            await write_ahead(tuple(rows))
        self.calls.append(("resolve", tuple(r.id for r in rows), outcome, position_state))
        return tuple(rows)

    def moves(self) -> dict[UUID, str]:
        return {i: outcome for _, ids, outcome, _ in self.calls for i in ids}


@dataclass
class Audit:
    hooks: list[tuple[VoidReason, PositionState, tuple[UUID, ...]]] = field(default_factory=list)

    def hook(self, reason: VoidReason, position_state: PositionState) -> VoidWriteAhead:
        async def write(rows: tuple[RecordedStopRow, ...]) -> None:
            self.hooks.append((reason, position_state, tuple(r.id for r in rows)))

        return write


@dataclass
class Rig:
    port: FakeTradingPort
    orders: InMemoryOrderStore
    store: Store
    audit: Audit
    resolver: StopResolver

    async def resolve(self, account: AccountRef | None = None) -> Any:
        return await self.resolver.resolve_key(self.port, account or ref(), KEY, bound_s=10.0)

    async def entry(self, **over: Any) -> OrderRow:
        """A stored entry, `submitting`."""
        submitting = {"state": ORDER_STATE_OF["submitting"], "lifecycle_state": "submitting"}
        event = NewOrderEvent(kind="submit_attempt", source="local", event_ts=T0)
        return await self.orders.create(new_order(**(submitting | over)), event)

    def methods(self) -> list[str]:
        return [call.method for call in self.port.calls]


def build(*, port: FakeTradingPort | None = None, timeout_s: float = 5.0) -> Rig:
    orders = InMemoryOrderStore(clock=lambda: T0)
    store, audit = Store(), Audit()
    read = CompleteRead(orders, read_timeout_s=timeout_s, whole_timeout_s=3 * timeout_s)
    port = port or FakeTradingPort(now_us=lambda: T0_US)
    return Rig(port, orders, store, audit, StopResolver(store, read, audit, now=lambda: NOW))


async def seed_entry(
    rig: Rig, *, state: str, filled: str = "0", answered: bool = True, **over: Any
) -> tuple[RecordedStopRow, RecordedStopRow]:
    """A stored entry, its venue order in `state` with `filled` filled (`over` changes the venue
    order only), and its two attach rows listed."""
    row = await rig.entry()
    venue = exchange_order(new_order(), state=state, filled_qty=Decimal(filled), **over)
    rig.port.seed_order(venue, uid=UID)
    at = T0 if answered else None
    rows = request_rows(source="entry_attach", order_id=row.id, answered_at=at)
    rig.store.rows = list(rows)
    return rows


# --- scope and reads ---------------------------------------------------------------------------


async def test_another_accounts_rows_are_never_read_or_written() -> None:
    rig = build()
    rig.store.rows = [stop_row(exchange_account_id=LIVE_ACCOUNT)]
    assert await rig.resolve() == ()
    assert rig.port.calls == [] and rig.store.calls == []


async def test_an_account_other_than_the_keys_is_refused_before_any_read() -> None:
    rig = build()
    rig.store.rows = list(request_rows())
    with pytest.raises(ValueError, match=r"C-12\.4"):
        await rig.resolve(ref(LIVE_ACCOUNT))
    with pytest.raises(ValueError, match=r"C-12\.4"):
        await CompleteRead(rig.orders).read(rig.port, ref(LIVE_ACCOUNT), KEY, (), now=NOW)
    assert rig.port.calls == []


async def test_a_restore_request_reads_nothing_and_writes_nothing() -> None:
    rig = build()
    rig.store.rows = [stop_row(source="restore")]
    (decision,) = await rig.resolve()
    assert decision.outcome == "held_for_reconciliation"
    assert rig.port.calls == [] and rig.store.calls == []


async def test_an_open_full_side_reads_the_position_alone() -> None:
    rig = build()
    sl, tp = rig.store.rows = list(request_rows())
    rig.port.seed_position(position(stop_loss=STOP))
    (decision,) = await rig.resolve()
    assert decision.outcome == "in_force" and rig.methods() == ["positions"]
    assert rig.store.calls == [
        ("resolve", (tp.id,), "answered", None),
        ("put_in_force", (sl.id,), "in_force", None),
    ]


async def test_a_partial_side_reads_its_orders_from_5_s_before_the_request_in_the_poll_lane() -> (
    None
):
    rig = build()
    rig.store.rows = list(request_rows(tpsl_mode="Partial", size=Decimal("0.010")))
    rig.port.seed_position(position())
    rig.port.seed_order(tpsl_order("partial_stop_loss", STOP), uid=UID)
    rig.port.seed_order(tpsl_order("partial_stop_loss", STOP, position_idx=1), uid=UID)
    (decision,) = await rig.resolve()
    assert decision.outcome == "answered"
    asked = [(c.method, c.request) for c in rig.port.calls]
    assert ("order_history", (None, None, T0_US - 5 * SECOND_US, None)) in asked
    assert {call.lane for call in rig.port.calls} == {"poll"}


async def test_a_full_stop_that_fired_on_a_flat_position_is_answered_never_voided() -> None:
    rig = build()
    rig.store.rows = list(request_rows())
    rig.port.seed_position(flat())
    rig.port.seed_order(fired("stop_loss", STOP), uid=UID)
    (decision,) = await rig.resolve()
    assert decision.outcome == "answered" and rig.audit.hooks == []


async def test_a_held_trail_logs_the_consequence_and_writes_nothing() -> None:
    rig = build()
    trail = stop_row(trailing_distance=Decimal("150"), trailing_active_price=Decimal("61000"))
    rig.store.rows = [trail]
    shown = position().model_copy(update={"trailing_stop_distance": Decimal("150")})
    rig.port.seed_position(shown)
    with capture_logs() as logs:
        (decision,) = await rig.resolve()
    assert decision.held == TRAIL_HELD and rig.store.calls == []
    held = [e for e in logs if e["event"] == "oms_stop_request_held"]
    assert [e["reason"] for e in held] == [TRAIL_HELD]


@pytest.mark.parametrize(("environment", "outcome"), [("demo", "held"), ("live", "voided")])
async def test_a_miss_on_an_open_position_past_a_demo_retention_is_held_and_live_decides(
    environment: Literal["demo", "live"], outcome: str
) -> None:
    rig = build(port=FakeTradingPort(environment=environment, now_us=lambda: T0_US))
    rig.store.rows = list(request_rows(created_at=NOW - timedelta(days=7)))
    rig.port.seed_position(position(stop_loss=Decimal("59000")))
    (decision,) = await rig.resolve(ref(environment=environment))
    if outcome == "held":
        assert decision.held == SPAN_HELD and rig.store.calls == []
    else:
        assert decision.outcome == "in_flight_resolved"


async def test_a_demo_miss_past_retention_on_a_position_with_no_stop_at_all_decides() -> None:
    """21 Sec.3.3.11: a key whose position, open on either side, shows no stop at all is never
    held on the history-miss rule, so its key clears for the protective re-attach (C-2.6)."""
    rig = build(port=FakeTradingPort(environment="demo", now_us=lambda: T0_US))
    rig.store.rows = list(request_rows(created_at=NOW - timedelta(days=7)))
    rig.port.seed_position(position(side="sell"))
    (decision,) = await rig.resolve(ref(environment="demo"))
    assert decision.outcome == "in_flight_resolved" and decision.held is None


async def test_the_read_keeps_no_state_between_calls_so_a_retry_reads_afresh() -> None:
    rig = build()
    rig.store.rows = list(request_rows())
    rig.port.seed_position(position(stop_loss=STOP))
    rig.port.script("positions", ServiceUnavailableError("the venue is restarting"))
    assert await rig.resolve() is None
    assert (await rig.resolve())[0].outcome == "in_force"
    assert rig.methods() == ["positions", "positions"]


# --- the entry ---------------------------------------------------------------------------------


async def test_an_entry_still_resting_keeps_its_rows_and_writes_nothing() -> None:
    rig = build()
    await seed_entry(rig, state="new")
    (decision,) = await rig.resolve()
    assert decision.outcome == "entry_resting" and rig.store.calls == []


async def test_a_filled_entry_voids_its_absent_stop_audited_with_its_position_state() -> None:
    rig = build()
    sl, tp = await seed_entry(rig, state="filled", filled="0.010", answered=False)
    rig.port.seed_position(position(take_profit=TP))
    (decision,) = await rig.resolve()
    assert decision.pages == (sl.id,)
    assert rig.store.calls == [
        ("put_in_force", (tp.id,), "in_force", None),
        ("resolve", (sl.id,), "entry_filled_stop_absent", "open"),
    ]
    assert rig.audit.hooks == [("entry_filled_stop_absent", "open", (sl.id,))]


async def test_a_squatter_under_the_entrys_id_credits_no_fill() -> None:
    rig = build()
    sl, tp = await seed_entry(rig, state="filled", filled="0.020", qty=Decimal("0.020"))
    rig.port.seed_position(position(qty="0.020"))
    (decision,) = await rig.resolve()
    assert decision.outcome == "in_flight_resolved" and decision.pages == ()
    assert rig.audit.hooks == [("in_flight_resolved", "open", (sl.id, tp.id))]


async def test_an_entry_bound_to_another_order_id_credits_no_fill() -> None:
    rig = build()
    row = await rig.entry(exchange_order_id="x-bound-elsewhere")
    venue = exchange_order(new_order(), state="filled", filled_qty=Decimal("0.010"))
    rig.port.seed_order(venue, uid=UID)
    rig.store.rows = list(request_rows(source="entry_attach", order_id=row.id))
    rig.port.seed_position(position())
    (decision,) = await rig.resolve()
    assert decision.outcome == "in_flight_resolved"


@pytest.mark.parametrize("stored", [True, False])
async def test_an_entry_not_stored_or_not_found_is_gone(stored: bool) -> None:
    rig = build()
    order_id = (await rig.entry()).id if stored else uuid4()
    rig.store.rows = list(request_rows(source="entry_attach", order_id=order_id))
    rig.port.seed_position(position())
    (decision,) = await rig.resolve()
    assert decision.outcome == "in_flight_resolved"


async def test_an_entry_with_malformed_money_credits_no_fill(monkeypatch: Any) -> None:
    rig = build()
    await seed_entry(rig, state="filled", filled="0.010")
    rig.port.seed_position(position())
    real = commands.found_view

    def malformed(order: Order) -> dict[str, Any]:
        return real(order) | {"qty": "not-money"}

    monkeypatch.setattr(stop_resolution, "found_view", malformed)
    (decision,) = await rig.resolve()
    assert decision.outcome == "in_flight_resolved"


# --- replaced ----------------------------------------------------------------------------------


async def test_a_row_already_in_force_later_replaces_the_older_side_without_a_void() -> None:
    rig = build()
    sl, tp = await seed_entry(rig, state="filled", filled="0.010", answered=False)
    later = stop_row(status="in_force", trigger_price=Decimal("59000"), created_at=NOW)
    rig.store.in_force = [later]
    rig.port.seed_position(position(stop_loss=Decimal("59000"), take_profit=TP))
    (decision,) = await rig.resolve()
    assert decision.pages == () and rig.audit.hooks == []
    assert rig.store.calls == [
        ("resolve", (sl.id,), "replaced", None),
        ("put_in_force", (tp.id,), "in_force", None),
    ]


async def test_a_later_request_in_the_same_read_replaces_the_older_one_before_its_put() -> None:
    rig = build()
    old_sl, old_tp = request_rows()
    new_sl, new_tp = request_rows(trigger_price=Decimal("59000"), created_at=NOW)
    rig.store.rows = [old_sl, old_tp, new_sl, new_tp]
    rig.port.seed_position(position(stop_loss=Decimal("59000")))
    await rig.resolve()
    assert rig.store.calls == [
        ("resolve", (old_tp.id,), "answered", None),
        ("resolve", (new_tp.id,), "answered", None),
        ("resolve", (old_sl.id,), "replaced", None),
        ("put_in_force", (new_sl.id,), "in_force", None),
    ]


# --- failures ----------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["positions", "open_orders", "order_history"])
async def test_a_failed_read_decides_nothing(method: str) -> None:
    rig = build()
    await seed_entry(rig, state="filled", filled="0.010")
    rig.port.seed_position(flat())
    rig.port.script(method, ServiceUnavailableError("the venue is restarting"))
    assert await rig.resolve() is None
    assert rig.store.calls == [] and rig.audit.hooks == []


async def test_a_failed_order_read_after_the_lookup_decides_nothing() -> None:
    rig = build()
    rig.store.rows = list(request_rows(tpsl_mode="Partial", size=Decimal("0.010")))
    rig.port.seed_position(position())
    rig.port.script("order_history", ServiceUnavailableError("the venue is restarting"))
    assert await rig.resolve() is None and rig.store.calls == []


class Hanging(FakeTradingPort):
    """A port whose positions read never answers."""

    async def positions(self, account: AccountRef) -> list[Position]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_a_read_that_does_not_answer_in_its_bound_decides_nothing() -> None:
    rig = build(port=Hanging(now_us=lambda: T0_US), timeout_s=0.01)
    rig.store.rows = list(request_rows())
    assert await rig.resolve() is None and rig.store.calls == []


async def test_a_stored_entry_that_does_not_answer_decides_nothing() -> None:
    rig = build(timeout_s=0.01)
    await seed_entry(rig, state="new")

    async def never(account_id: UUID, order_id: UUID) -> OrderRow | None:
        await asyncio.Event().wait()
        return None

    rig.orders.get = never  # type: ignore[method-assign]  # a store read that never answers
    rig.port.seed_position(position())
    assert await rig.resolve() is None and rig.store.calls == []


# --- what the read never does ------------------------------------------------------------------

READS = {"positions", "open_orders", "order_history"}
TRIGGERS = st.sampled_from([STOP, Decimal("59000"), TP])


@settings(max_examples=60, deadline=None)
@given(
    mode=st.sampled_from(["Full", "Partial"]),
    trigger=TRIGGERS,
    shown=st.one_of(st.none(), TRIGGERS),
    side=st.sampled_from(["buy", "sell", None]),
    bound=st.booleans(),
    fired_kind=st.one_of(st.none(), st.sampled_from(["stop_loss", "partial_stop_loss"])),
    entry=st.sampled_from([None, "new", "filled", "cancelled"]),
)
async def test_property_the_read_only_answers_replaces_puts_in_force_or_voids(
    mode: Literal["Full", "Partial"],
    trigger: Decimal,
    shown: Decimal | None,
    side: Literal["buy", "sell"] | None,
    bound: bool,
    fired_kind: str | None,
    entry: str | None,
) -> None:
    rig = build()
    sized = {"tpsl_mode": mode, "size": Decimal("0.010") if mode == "Partial" else None}
    rows = request_rows(trigger_price=trigger, **sized)
    if entry is not None:
        seeded = await seed_entry(rig, state=entry, filled="0.010" if entry == "filled" else "0")
        rows = request_rows(
            trigger_price=trigger, source="entry_attach", order_id=seeded[0].order_id, **sized
        )
    if bound:
        rows = (replace(rows[0], exchange_order_id="x-bound"), rows[1])
    rig.store.rows = list(rows)
    rig.port.seed_position(position(side=side, qty="0.010" if side else "0", stop_loss=shown))
    if fired_kind is not None:
        rig.port.seed_order(fired(fired_kind, trigger, exchange_order_id="x-bound"), uid=UID)
    assert await rig.resolve() is not None
    assert set(rig.methods()) <= READS and {c.lane for c in rig.port.calls} == {"poll"}
    written = rig.store.moves()
    allowed = {"in_force", "answered", "replaced", "in_flight_resolved", "entry_filled_stop_absent"}
    assert set(written.values()) <= allowed  # never an end, a bind or a release
    voids = {
        i for i, m in written.items() if m in ("in_flight_resolved", "entry_filled_stop_absent")
    }
    assert voids == {i for _, _, ids in rig.audit.hooks for i in ids}  # each audited ahead


def test_the_module_never_tells_b1_a_stop_was_seen_or_lost_nor_binds_an_order_id() -> None:
    tree = ast.parse(inspect.getsource(stop_resolution))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    texts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    for name in ("SL_OBSERVED", "SL_LOST", "send", "settle", "bind", "release", "insert"):
        assert name not in names and name not in texts
    assert not {"set_trading_stop", "place_order", "cancel_order", "amend_order"} & names
