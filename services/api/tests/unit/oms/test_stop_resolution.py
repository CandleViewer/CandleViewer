"""E29-T04 (#913) S3-H H2b: the complete read and its writes (21 Sec.3.3.11, 24 Sec.8.8 rule 6), on
`FakeTradingPort`, the in-memory order store and a recording store double."""

from __future__ import annotations

import ast
import asyncio
import inspect
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import ServiceUnavailableError
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, Order, Position
from candleviewer.oms import commands, stop_resolution
from candleviewer.oms.errors import AuditNotDurable
from candleviewer.oms.fakes import InMemoryOrderStore, InMemoryRecordedStopStore
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.oms.stop_resolution import (
    ENTRY_HELD,
    RESTORE_HELD,
    SPAN_HELD,
    TRAIL_HELD,
    UNSEEN_PAGE,
    CompleteRead,
    PositionState,
    StopResolver,
    VoidReason,
    VoidWriteAhead,
)
from candleviewer.storage.repositories import recorded_stops
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, NewOrderEvent, OrderRow
from candleviewer.storage.repositories.orders_sqlalchemy import OMS_STATEMENT_TIMEOUT_MS
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow, StaleRecordedStop
from tests.unit.oms import submission_contract as sc
from tests.unit.oms.command_rig import (
    ACCOUNT,
    LIVE_ACCOUNT,
    STOP,
    SYMBOL,
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
SPAN = timedelta(hours=1)
NOW_US = T0_US + 30 * SECOND_US
DAY_US = 86_400 * SECOND_US
ADAPTER_WINDOWS = 106  # `exchange.bybit.trading._MAX_WINDOWS`
UID = "100001"


@dataclass
class Store:
    """A recording `ResolutionStore`: `rows` is what `waiting_for_key` lists, `in_force` what
    `in_force_for_key` does; `views` is each put's read of the rows in force, by id (SEC-S2D-03)."""

    rows: list[RecordedStopRow] = field(default_factory=list)
    in_force: list[RecordedStopRow] = field(default_factory=list)
    calls: list[tuple[str, tuple[UUID, ...], str, PositionState | None]] = field(
        default_factory=list
    )
    views: list[tuple[UUID, ...]] = field(default_factory=list)

    async def waiting_for_key(
        self, account_id: UUID, symbol: str, position_idx: int, *, now: datetime,
        bound_s: float | None,
    ) -> list[RecordedStopRow]:  # fmt: skip
        return list(self.rows)

    async def in_force_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> list[RecordedStopRow]:
        return list(self.in_force)

    async def put_in_force(
        self, account_id: UUID, rows: Any, *, in_force: Any, at: datetime
    ) -> object:
        self.calls.append(("put_in_force", tuple(r.id for r in rows), "in_force", None))
        self.views.append(tuple(r.id for r in in_force))
        return tuple(rows)

    async def resolve(
        self, account_id: UUID, rows: Any, outcome: str, *, at: datetime,
        write_ahead: VoidWriteAhead | None = None, position_state: PositionState | None = None,
    ) -> tuple[RecordedStopRow, ...]:  # fmt: skip
        if write_ahead is not None:
            await write_ahead(tuple(rows), position_state)
        self.calls.append(("resolve", tuple(r.id for r in rows), outcome, position_state))
        return tuple(rows)

    def moves(self) -> dict[UUID, str]:
        return {i: outcome for _, ids, outcome, _ in self.calls for i in ids}


@dataclass
class Audit:
    """A recording `VoidAudit`: each hook records the state the store gives it (H1)."""

    hooks: list[tuple[VoidReason, PositionState | None, tuple[UUID, ...]]] = field(
        default_factory=list
    )

    def hook(self, reason: VoidReason) -> VoidWriteAhead:
        async def write(rows: tuple[RecordedStopRow, ...], state: PositionState | None) -> None:
            self.hooks.append((reason, state, tuple(r.id for r in rows)))

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


def build(
    *, port: FakeTradingPort | None = None, timeout_s: float = 5.0, now: datetime = NOW
) -> Rig:
    orders = InMemoryOrderStore(clock=lambda: T0)
    store, audit = Store(), Audit()
    read = CompleteRead(orders, read_timeout_s=timeout_s, whole_timeout_s=3 * timeout_s)
    port = port or FakeTradingPort(now_us=lambda: T0_US)
    resolver = StopResolver(store, read, audit, now=lambda: now, store_timeout_s=timeout_s)
    return Rig(port, orders, store, audit, resolver)


class Capped(FakeTradingPort):
    """A port whose history read lists what the adapter's would (24 Sec.14.1): the 7 days from
    `start`, or to `end`, or to its clock with neither; every 7-day window between both."""

    async def order_history(
        self, account: AccountRef, *, order_link_id: Any = None,
        exchange_order_id: str | None = None, start: int | None = None, end: int | None = None,
    ) -> list[Order]:  # fmt: skip
        if start is None:
            end = self._now_us() if end is None else end
            start = end - 7 * DAY_US
        elif end is None:
            end = start + 7 * DAY_US
        elif end - start > ADAPTER_WINDOWS * 7 * DAY_US:  # `trading._windows` refuses it too
            raise ValueError("the window is longer than the exchange keeps")
        return list(
            await super().order_history(account, order_link_id=order_link_id,
                                        exchange_order_id=exchange_order_id, start=start, end=end)
        )  # fmt: skip


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


async def test_a_restore_only_resolution_writes_on_the_stored_rows_in_force_never_on_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S2D-03: with no venue read, a restore request's resolution still reads the key's rows
    in force from the store for its writes, never an empty view on a key that holds one; it is
    held (E29-T06's), so it puts nothing in force."""
    rig = build()
    rig.store.rows = [stop_row(source="restore")]
    shown = stop_row(status="in_force", trigger_price=Decimal("59000"), created_at=T0 - SPAN)
    rig.store.in_force = [shown]
    given: list[tuple[UUID, ...]] = []
    write = rig.resolver._write

    async def spy(key: Any, decisions: Any, in_force: Any, *rest: Any) -> None:
        given.append(tuple(r.id for r in in_force))
        await write(key, decisions, in_force, *rest)

    monkeypatch.setattr(rig.resolver, "_write", spy)
    (decision,) = await rig.resolve()
    assert decision.held == RESTORE_HELD and given == [(shown.id,)]
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
    assert ("order_history", (None, None, T0_US - 5 * SECOND_US, NOW_US)) in asked
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
    resolved = [e["held"] for e in logs if e["event"] == "oms_stop_request_resolved"]
    assert resolved == [TRAIL_HELD]  # the gate logs the hold once per key (H3)
    assert not [e for e in logs if e["event"] == "oms_stop_request_held"]


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
    assert rig.audit.hooks == [("in_flight_resolved", None, (sl.id, tp.id))]  # the void's own


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
    assert rig.store.calls == [  # in force first: a lost put replaces nothing (Fable Minor)
        ("put_in_force", (tp.id,), "in_force", None),
        ("resolve", (sl.id,), "replaced", None),
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
        ("put_in_force", (new_sl.id,), "in_force", None),
        ("resolve", (old_sl.id,), "replaced", None),  # unanswered: the put never replaces it
    ]


async def test_each_put_compares_the_reads_rows_in_force_as_the_puts_before_it_left_them() -> None:
    """SEC-S2D-03: a read that puts rows in force for two requests gives the second put the read's
    view of the rows in force as the first put left it (its kind's row replaced by the first
    put's), so the read's own writes never make it stale."""
    rig = build()
    prior = stop_row(kind="take_profit", trigger_price=Decimal("63000"), status="in_force",
                     created_at=T0 - SPAN)  # fmt: skip
    old_sl, old_tp = request_rows()
    new_sl, new_tp = request_rows(trigger_price=Decimal("59000"), created_at=NOW)
    rig.store.rows, rig.store.in_force = [old_sl, old_tp, new_sl, new_tp], [prior]
    rig.port.seed_position(position(stop_loss=Decimal("59000"), take_profit=TP))
    await rig.resolve()
    assert rig.store.calls == [
        ("resolve", (new_tp.id,), "answered", None),
        ("put_in_force", (old_tp.id,), "in_force", None),
        ("put_in_force", (new_sl.id,), "in_force", None),
        ("resolve", (old_sl.id,), "replaced", None),
    ]
    assert rig.store.views == [(prior.id,), (old_tp.id,)]


async def test_an_answered_row_the_put_replaces_gets_no_replace_of_its_own() -> None:
    """Fable Minor: the put's transaction replaces an older answered row of its kind, so the
    read's own `replaced` is for an unanswered row or a successor already stored in force."""
    rig = build()
    row = await rig.entry()
    old_sl, old_tp = request_rows(source="entry_attach", order_id=row.id, answered_at=T0)
    new_sl, new_tp = request_rows(trigger_price=Decimal("59000"), created_at=NOW)
    rig.store.rows = [old_sl, old_tp, new_sl, new_tp]
    rig.port.seed_position(position(stop_loss=Decimal("59000")))
    old, _ = await rig.resolve()
    assert rig.store.calls == [
        ("resolve", (new_tp.id,), "answered", None),
        ("put_in_force", (new_sl.id,), "in_force", None),
    ]
    assert old.held == ENTRY_HELD  # its answered take-profit stays listed
    rig = build()
    rig.store.rows = [old_sl, old_tp]
    rig.store.in_force = [replace(new_sl, status="in_force")]
    rig.port.seed_position(position(stop_loss=Decimal("59000")))
    await rig.resolve()
    assert rig.store.calls == [("resolve", (old_sl.id,), "replaced", None)]


# --- the H lens folds: the history window, the entry lookup, the entry hold, the store bound ----


async def test_the_history_read_ends_now_so_a_newer_request_past_a_week_of_the_oldest_is_read(
) -> None:  # fmt: skip
    """Opus Major (H2b): with no end the adapter reads the 7 days from `start` only, so a newer
    request's fired stop went unread and its rows were voided `in_flight_resolved`."""
    port = Capped(environment="live", now_us=lambda: NOW_US + 8 * DAY_US)
    rig = build(port=port, now=NOW + timedelta(days=8))
    old = request_rows()
    late = NOW + timedelta(days=8, seconds=-60)
    new = request_rows(trigger_price=Decimal("59000"), created_at=late)
    rig.store.rows = [*old, *new]
    rig.port.seed_position(flat())
    fired_at = NOW_US + 8 * DAY_US - 30 * SECOND_US
    rig.port.seed_order(fired("stop_loss", Decimal("59000"), created_at=fired_at), uid=UID)
    held, answered = await rig.resolve(ref(environment="live"))
    assert held.held == SPAN_HELD and answered.outcome == "answered"
    asked = [c.request for c in rig.port.calls if c.method == "order_history"]
    assert asked == [(None, None, T0_US - 5 * SECOND_US, NOW_US + 8 * DAY_US)]


async def test_an_entry_is_looked_up_by_its_bound_id_from_5_s_before_it_was_stored() -> None:
    """Opus Major (H2b): the default window missed a filled entry older than a week, and the read
    voided its rows `in_flight_resolved`, unpaged; the bound id from `created_ts` finds it."""
    port = Capped(environment="live", now_us=lambda: NOW_US + 8 * DAY_US)
    rig = build(port=port, now=NOW + timedelta(days=8))
    venue = exchange_order(new_order(), state="filled", filled_qty=Decimal("0.010"))
    row = await rig.entry(exchange_order_id=venue.exchange_order_id)
    rig.port.seed_order(venue, uid=UID)
    sl, tp = rig.store.rows = list(request_rows(source="entry_attach", order_id=row.id))
    rig.port.seed_position(position(stop_loss=STOP))
    (decision,) = await rig.resolve(ref(environment="live"))
    assert decision.outcome == "entry_filled_stop_absent"
    assert rig.store.moves() == {sl.id: "in_force", tp.id: "entry_filled_stop_absent"}
    asked = [cast(tuple[Any, ...], c.request)[:3] for c in rig.port.calls
             if c.method == "order_history"]  # fmt: skip
    assert asked == [(None, venue.exchange_order_id, T0_US - 5 * SECOND_US)]  # end: 7 d on


@pytest.mark.parametrize(("pos", "outcome"), [(flat(), "held"), (position(), "voided")])
async def test_an_entry_not_found_past_the_span_is_unseen(pos: Position, outcome: str) -> None:
    """Its miss proves nothing: held where a miss is (flat past the span); voided on a position
    with no stop at all, paged (the 06:38Z ruling) with the void audited with its state; logged
    once as unseen, by its `order_link_id` alone (Fable Minor)."""
    rig = build(now=NOW + timedelta(days=2))
    row = await rig.entry()
    sl, tp = rig.store.rows = list(request_rows(source="entry_attach", order_id=row.id))
    rig.port.seed_position(pos)
    with capture_logs() as logs:
        (decision,) = await rig.resolve()
    unseen = [e for e in logs if e["event"] == "oms_stop_read_entry_unseen"]
    assert unseen == [
        {"event": "oms_stop_read_entry_unseen", "log_level": "warning",
         "order_link_id": row.order_link_id}
    ]  # fmt: skip
    if outcome == "held":
        assert decision.held == SPAN_HELD and rig.store.calls == []
    else:
        assert decision.outcome == "in_flight_resolved" and decision.pages == (sl.id,)
        assert decision.page == UNSEEN_PAGE
        assert rig.store.calls == [("resolve", (sl.id, tp.id), "in_flight_resolved", "open")]
        assert rig.audit.hooks == [("in_flight_resolved", "open", (sl.id, tp.id))]


@pytest.mark.parametrize("environment", ["live", "demo"])
async def test_an_unseen_entry_on_a_position_open_with_a_foreign_stop_decides_as_gone(
    environment: Literal["live", "demo"],
) -> None:
    """Fold 2, Opus Major: 2 d on, past the live span and inside a demo retention, a position
    open on the row's side with a stop that is not the row's decides; no page, no state."""
    port = FakeTradingPort(environment=environment, now_us=lambda: NOW_US + 2 * DAY_US)
    rig = build(port=port, now=NOW + timedelta(days=2))
    row = await rig.entry()
    sl, tp = rig.store.rows = list(request_rows(source="entry_attach", order_id=row.id))
    rig.port.seed_position(position(stop_loss=Decimal("59000")))
    (decision,) = await rig.resolve(ref(environment=environment))
    assert decision.outcome == "in_flight_resolved" and decision.pages == ()
    assert rig.store.calls == [("resolve", (sl.id, tp.id), "in_flight_resolved", None)]


@pytest.mark.parametrize(("pos", "outcome"), [(flat(), "held"), (position(), "voided")])
async def test_a_request_years_old_reads_a_bounded_history_and_still_decides(
    pos: Position, outcome: str
) -> None:
    """Fold 2, Fable Major: the history read starts no earlier than MAX_HISTORY_WINDOWS weeks
    back, so the adapter's walk stays inside its cap and the read's bound: a flat key 3 years on
    is held (`SPAN_HELD`), never a read that fails each time; open with no stop, it decides."""
    later = NOW + timedelta(days=3 * 365)
    now_us = NOW_US + 3 * 365 * DAY_US
    rig = build(port=Capped(environment="live", now_us=lambda: now_us), now=later)
    rig.store.rows = list(request_rows(tpsl_mode="Partial", size=Decimal("0.010")))  # read
    rig.port.seed_position(pos)
    (decision,) = await rig.resolve(ref(environment="live"))
    weeks = stop_resolution.MAX_HISTORY_WINDOWS
    assert 4 <= weeks <= 5
    asked = [c.request for c in rig.port.calls if c.method == "order_history"]
    assert asked == [(None, None, now_us - weeks * 7 * DAY_US, now_us)]
    if outcome == "held":
        assert decision.held == SPAN_HELD
    else:
        assert decision.outcome == "in_flight_resolved"


def test_the_store_bound_outlasts_the_stop_audit_bound_so_its_error_is_the_audits() -> None:
    """Opus Minor: the store-call bound is the stop audit's bound plus a margin, so a late audit
    surfaces as the audit's own error, never as this bound's `TimeoutError`: `AuditNotDurable`
    through `RecordedStopRepository`, the only layer that maps the store's `WriteAheadTimeout`."""
    margin = stop_resolution.STORE_TIMEOUT_S - recorded_stops.STOP_AUDIT_TIMEOUT_S
    statements_s = 2 * OMS_STATEMENT_TIMEOUT_MS / 1000  # the lock and the update before the hook
    assert margin > statements_s and margin >= 5.0
    assert "PageReason" in stop_resolution.__all__
    default = inspect.signature(StopResolver).parameters["store_timeout_s"].default
    assert default == stop_resolution.STORE_TIMEOUT_S
    tree = ast.parse(inspect.getsource(stop_resolution))  # production never reads the fakes
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {m for m in imported if m and m.split(".")[-1] == "fakes"}


async def test_a_late_void_audit_reaches_the_caller_as_audit_not_durable() -> None:
    db = InMemoryOrderStore(clock=lambda: T0)
    stops = RecordedStopRepository(InMemoryRecordedStopStore(db, audit_timeout_s=0.01))

    class Hangs(Audit):
        def hook(self, reason: VoidReason) -> VoidWriteAhead:
            async def write(rows: Any, state: PositionState | None) -> None:
                await asyncio.Event().wait()

            return write

    resolver = StopResolver(stops, CompleteRead(db), Hangs(), now=lambda: NOW)
    port = FakeTradingPort(now_us=lambda: NOW_US)
    await stops.record([sc.trading_stop(ACCOUNT, trigger_price=STOP)], write_ahead=sc.audited)
    port.seed_position(position())
    with pytest.raises(AuditNotDurable):
        await resolver.resolve_key(port, ref(), KEY, bound_s=10.0)


async def test_an_entry_partly_filled_and_still_resting_is_the_fill_case() -> None:
    """The orchestrator's ruling (21 Sec.3.3.11): decided as a fill for its filled part."""
    rig = build()
    sl, _ = await seed_entry(rig, state="partially_filled", filled="0.005", answered=False)
    rig.port.seed_position(position(qty="0.005"))
    (decision,) = await rig.resolve()
    assert decision.outcome == "entry_filled_stop_absent" and decision.pages == (sl.id,)


async def test_rows_answered_by_this_read_carry_the_hold_while_the_stored_entry_waits() -> None:
    """Fable Major (b): the stored order `WAITING_ENTRY` holds (ended, nothing filled) keeps a
    row the read answers listed: `ENTRY_HELD`, its outcome kept."""
    rig = build()
    row = await rig.entry(state=ORDER_STATE_OF["cancelled"], lifecycle_state="cancelled")
    venue = exchange_order(new_order(), state="cancelled")
    rig.port.seed_order(venue, uid=UID)
    rig.store.rows = list(request_rows(source="entry_attach", order_id=row.id))
    rig.port.seed_position(position(stop_loss=STOP))
    (decision,) = await rig.resolve()
    assert decision.outcome == "in_force" and decision.held == ENTRY_HELD


async def test_an_open_partial_stop_order_counts_as_a_stop_once_the_orders_were_read() -> None:
    """The orchestrator's ruling: Partial-mode protection is an open `partial_stop_loss` order;
    the demo miss past retention on that position is held, not voided."""
    rig = build(port=FakeTradingPort(environment="demo", now_us=lambda: T0_US))
    partial = {"tpsl_mode": "Partial", "size": Decimal("0.010")}
    rig.store.rows = list(request_rows(created_at=NOW - timedelta(days=7), **partial))
    rig.port.seed_position(position())
    rig.port.seed_order(tpsl_order("partial_stop_loss", Decimal("57000")), uid=UID)
    (decision,) = await rig.resolve(ref(environment="demo"))
    assert decision.held == SPAN_HELD and rig.store.calls == []


class Stalled(Store):
    async def waiting_for_key(self, *args: Any, **kwargs: Any) -> list[RecordedStopRow]:
        await asyncio.Event().wait()
        return []


async def test_a_store_call_that_does_not_answer_in_its_bound_raises() -> None:
    """21 Sec.3.3.5: every store call is bounded, as each venue read is."""
    rig = build(timeout_s=0.01)
    rig.resolver = StopResolver(Stalled(), CompleteRead(rig.orders), rig.audit, now=lambda: NOW,
                                store_timeout_s=0.01)  # fmt: skip
    with pytest.raises(TimeoutError):
        await rig.resolve()


async def resolved(resolver: StopResolver, port: FakeTradingPort) -> Any:
    decisions = await resolver.resolve_key(port, ref(), KEY, bound_s=10.0)
    assert decisions is not None
    return decisions


async def test_the_resolver_runs_over_the_recorded_stops_facade_and_its_in_memory_store() -> None:
    """H1's real store through `RecordedStopRepository`: the put replaces the row in force, a
    void's hook is given its state by the store, and nothing is left listed."""
    db = InMemoryOrderStore(clock=lambda: T0)
    stops = RecordedStopRepository(InMemoryRecordedStopStore(db))
    audit = Audit()
    resolver = StopResolver(stops, CompleteRead(db), audit, now=lambda: NOW)
    port = FakeTradingPort(now_us=lambda: NOW_US)

    def pair(**over: Any) -> list[Any]:
        return [sc.trading_stop(ACCOUNT, trigger_price=STOP, **over),
                sc.trading_stop(ACCOUNT, kind="take_profit", trigger_price=TP, **over)]  # fmt: skip

    first = await stops.record(pair(), write_ahead=sc.audited)
    await stops.put_in_force(ACCOUNT, first, in_force=(), at=T0)
    second = await stops.record(pair(position_marker="m2"), write_ahead=sc.audited)
    port.seed_position(position(stop_loss=STOP, take_profit=TP))
    (decision,) = await resolved(resolver, port)
    assert decision.outcome == "in_force"
    held = await stops.in_force_for_key(ACCOUNT, SYMBOL, 0)
    assert {r.id for r in held} == {r.id for r in second}
    assert await stops.waiting_for_key(ACCOUNT, SYMBOL, 0, now=NOW, bound_s=10.0) == ()
    third = await stops.record(pair(position_marker="m3"), write_ahead=sc.audited)
    port.seed_position(position())
    (decision,) = await resolved(resolver, port)
    assert decision.outcome == "in_flight_resolved"
    assert audit.hooks == [("in_flight_resolved", None, tuple(r.id for r in third))]
    assert await stops.waiting_for_key(ACCOUNT, SYMBOL, 0, now=NOW, bound_s=10.0) == ()


@pytest.mark.parametrize("after", ["flat", "shown"])
async def test_an_end_between_the_read_and_its_put_loses_the_put_and_the_next_ask_reads_again(
    after: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-S2D-03 (option b): an end (E29-T05's, simulated) lands on the key's row in force after
    the read listed it and before the put. The put compares the rows in force with the read's view
    and loses (`StaleRecordedStop`) with nothing written, so no row is left in force on a key the
    end showed flat. The next resolution reads the key again and decides on what it shows then:
    flat, the request is voided; its stop still shown, it is put in force on the new view."""
    db = InMemoryOrderStore(clock=lambda: T0)
    stops = RecordedStopRepository(InMemoryRecordedStopStore(db))
    resolver = StopResolver(stops, CompleteRead(db), Audit(), now=lambda: NOW)
    port = FakeTradingPort(now_us=lambda: NOW_US)
    [old] = await stops.record([sc.trading_stop(ACCOUNT, trigger_price=Decimal("59000"))],
                               write_ahead=sc.audited)  # fmt: skip
    await stops.put_in_force(ACCOUNT, [old], in_force=(), at=T0)
    [new] = await stops.record([sc.trading_stop(ACCOUNT, trigger_price=STOP, position_marker="m2")],
                               write_ahead=sc.audited)  # fmt: skip
    port.seed_position(position(stop_loss=STOP))
    read = stops.in_force_for_key

    async def ended_after_the_read(account_id: UUID, symbol: str, position_idx: int) -> Any:
        rows = await read(account_id, symbol, position_idx)
        db._stops[old.id] = replace(db._stops[old.id], status="ended", closed_at=T0)
        return rows

    monkeypatch.setattr(stops, "in_force_for_key", ended_after_the_read)
    with pytest.raises(StaleRecordedStop):
        await resolver.resolve_key(port, ref(), KEY, bound_s=10.0)
    monkeypatch.undo()
    assert await stops.in_force_for_key(ACCOUNT, SYMBOL, 0) == ()
    assert db._stops[new.id] == new  # nothing written: pending, unanswered
    if after == "flat":
        port.seed_position(flat())
    (decision,) = await resolved(resolver, port)
    held = [r.id for r in await stops.in_force_for_key(ACCOUNT, SYMBOL, 0)]
    voided = ("in_flight_resolved", [], "void")
    expected = voided if after == "flat" else ("in_force", [new.id], "in_force")
    assert (decision.outcome, held, db._stops[new.id].status) == expected


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
