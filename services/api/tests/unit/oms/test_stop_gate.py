"""E29-T04 (#913) S3-H H3: the stop-request gate that resolves what it refuses (21 Sec.3.3.11, 24
Sec.8.4, 20 Sec.6.2 and Sec.12.1), over H1's in-memory store, H2's resolver and `FakeTradingPort`,
on clocks a test moves. Nothing sleeps: a venue read is held open on an event, and a wait that must
run out is a hundredth of a second."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import ServiceUnavailableError
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, Order, Position
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import StopRequestPending, StoreUnavailable
from candleviewer.oms.fakes import (
    InMemoryOrderStore,
    InMemoryRecordedStopStore,
    InMemoryTradingAccounts,
)
from candleviewer.oms.ports import KeyedRecord, PositionKey
from candleviewer.oms.repository import OrderRepository, RecordedStopRepository
from candleviewer.oms.stop_gate import MAX_RESOLUTIONS, ResolvingStopGate, StopVoidAudit
from candleviewer.oms.stop_resolution import RESTORE_HELD, CompleteRead, StopResolver
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.orders import (
    ORDER_STATE_OF,
    LifecycleState,
    NewOrderEvent,
    OrderRow,
)
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, RecordedStopRow
from tests.unit.oms import command_rig as cr
from tests.unit.oms.order_rig import Pager
from tests.unit.oms.test_stop_decision import fired, tpsl_order

KEY = PositionKey(cr.ACCOUNT, cr.SYMBOL, 0)
WHERE = f"account {cr.ACCOUNT} {cr.SYMBOL} position_idx 0"
EVENT = NewOrderEvent(kind="submit_attempt", source="local", event_ts=cr.T0)


class Venue(FakeTradingPort):
    """The demo venue, its positions read held while `open` is clear."""

    def __init__(self) -> None:
        super().__init__(environment="demo", now_us=lambda: cr.T0_US)
        self.open = asyncio.Event()
        self.open.set()

    async def positions(self, account: AccountRef) -> list[Position]:
        found = list(await super().positions(account))
        await self.open.wait()
        return found

    def reads(self) -> int:
        return sum(call.method == "positions" for call in self.calls)


@dataclass
class Clock:
    """The app's clock, past the 10 s bound of every row the store stamps at `at`, and the gate's
    monotonic one."""

    now: datetime = cr.T0 + timedelta(seconds=11)
    at: datetime = cr.T0
    s: float = 100.0


@dataclass
class Rig:
    gate: ResolvingStopGate
    store: InMemoryOrderStore
    stops: RecordedStopRepository
    venue: Venue
    audits: cr.Audits
    pager: Pager
    metrics: Metrics
    clock: Clock

    def count(self, outcome: str) -> float:
        labels = {"env": "demo", "outcome": outcome}
        return self.metrics.registry.get_sample_value("oms_stop_resolutions_total", labels) or 0.0

    async def idle(self) -> None:
        """Until no resolution runs: each awaited, never slept on."""
        while running := [task for task in self.gate._running.values() if not task.done()]:
            await asyncio.wait(running)
        await until(lambda: not self.gate._running)


def build(
    *,
    started_at: datetime | None = cr.T0 - timedelta(days=1),
    accounts: tuple[AccountRef, ...] = (cr.ref(),),
    **over: Any,
) -> Rig:
    clock = Clock()
    store = InMemoryOrderStore(clock=lambda: clock.at)
    stops = RecordedStopRepository(InMemoryRecordedStopStore(store))
    venue, audits, pager, metrics = Venue(), cr.Audits(), Pager(), Metrics("demo")
    read = CompleteRead(OrderRepository(store))
    resolver = StopResolver(stops, read, StopVoidAudit(audits), now=lambda: clock.now)
    gate = ResolvingStopGate(
        stops, resolver, accounts=InMemoryTradingAccounts(*accounts),
        port_for=lambda _environment: venue, bound_s=10.0, now=lambda: clock.now,
        monotonic=lambda: clock.s, metrics=metrics, pager=pager, started_at=started_at, **over,
    )  # fmt: skip
    return Rig(gate, store, stops, venue, audits, pager, metrics, clock)


async def until(done: Callable[[], bool]) -> None:
    """Turn the loop until `done()`, at most 10 000 times: a bound on the test, not a time."""
    for _ in range(10_000):
        if done():
            return
        await asyncio.sleep(0)
    raise AssertionError("never happened")


async def _audited(_rows: Any) -> None:
    return None


async def request(rig: Rig, *, symbol: str = cr.SYMBOL, **over: Any) -> RecordedStopRow:
    """A stop request's stop-loss row for `symbol`'s position 0, recorded at the store's clock."""
    values: dict[str, Any] = {
        "id": uuid4(), "exchange_account_id": cr.ACCOUNT, "symbol": symbol, "position_idx": 0,
        "position_side": "Buy", "kind": "stop_loss", "source": "trading_stop", "order_id": None,
        "tpsl_mode": "Full", "trigger_price": cr.STOP, "size": None, "audit_record_id": uuid4(),
        "actor_user_id": None,
    }  # fmt: skip
    [row] = await rig.stops.record([NewRecordedStop(**(values | over))], write_ahead=_audited)
    return row


async def refused(rig: Rig, key: PositionKey = KEY, **wait: float) -> None:
    with pytest.raises(StopRequestPending) as pending:
        await rig.gate.clear(key, **wait)
    assert pending.value.retry_after_s == 5


def status(rig: Rig, row: RecordedStopRow) -> str:
    return rig.store._stops[row.id].status


async def stored(rig: Rig, lifecycle: LifecycleState) -> OrderRow:
    """The entry stored in `lifecycle`, its `orders` state alike."""
    order = cr.new_order(state=ORDER_STATE_OF[lifecycle], lifecycle_state=lifecycle)
    return await OrderRepository(rig.store).create(order, EVENT)


async def test_an_entry_is_refused_at_once_its_read_runs_on_once_and_its_retry_passes() -> None:
    """24 Sec.8.4: 409 at once with `Retry-After: 5`; a second caller joins the one read; the read
    voids the request nothing shows (`in_flight_resolved`, audited ahead), and the retry passes."""
    rig = build()
    row = await request(rig)
    rig.venue.open.clear()
    await refused(rig)
    await until(lambda: rig.venue.reads() == 1)
    await refused(rig)  # joined: no second read
    rig.venue.open.set()
    await rig.idle()
    await rig.gate.clear(KEY)
    assert rig.venue.reads() == 1 and status(rig, row) == "void"
    assert rig.count("in_flight_resolved") == 1
    [(record, _)] = rig.audits.written
    assert isinstance(record, KeyedRecord)
    assert (record.action, record.reason, record.name, record.actor_user_id) == (
        "sl.modified", "in_flight_resolved", f"in_flight_resolved:{row.id}", None,
    )  # fmt: skip
    assert record.detail == {"kind": "stop_loss", "source": "trading_stop"}  # ids only


async def test_an_attach_waits_for_the_read_then_clears() -> None:
    rig = build()
    await request(rig)
    rig.venue.open.clear()
    attach = asyncio.create_task(rig.gate.clear(KEY, wait_s=5.0))
    await until(lambda: rig.venue.reads() == 1)
    assert not attach.done()
    rig.venue.open.set()
    await attach  # returned: the read ended and a fresh read lists nothing


async def test_an_attach_past_its_wait_is_refused_and_the_read_runs_on() -> None:
    rig = build()
    await request(rig)
    rig.venue.open.clear()
    await refused(rig, wait_s=0.01)  # the read held past the wait
    [task] = rig.gate._running.values()
    assert not task.done()
    rig.venue.open.set()
    await rig.idle()
    await rig.gate.clear(KEY)


async def test_at_most_eight_reads_run_and_the_last_slot_is_kept_for_an_attach() -> None:
    """C-2.18: an entry past the seventh is refused unread; an attach takes the eighth; past it
    an attach is refused unread too."""
    rig = build()
    keys = [PositionKey(cr.ACCOUNT, f"COIN{n}USDT", 0) for n in range(MAX_RESOLUTIONS + 1)]
    for key in keys:
        await request(rig, symbol=key.symbol)
    rig.venue.open.clear()
    for key in keys[: MAX_RESOLUTIONS - 1]:
        await refused(rig, key)
    await until(lambda: rig.venue.reads() == MAX_RESOLUTIONS - 1)
    await refused(rig, keys[-2])  # an entry: the last slot is an attach's
    assert len(rig.gate._running) == MAX_RESOLUTIONS - 1
    await refused(rig, keys[-2], wait_s=0.01)  # an attach takes it
    await refused(rig, keys[-1], wait_s=0.01)  # none left
    assert rig.venue.reads() == MAX_RESOLUTIONS and keys[-1] not in rig.gate._running
    rig.venue.open.set()
    await rig.idle()


async def test_a_failed_read_keeps_the_key_refused_and_cools_it_for_entries_never_attaches() -> (
    None
):
    """A read that decided nothing counts `read_failed`; for 5 s an entry is refused unread; an
    attach reads at once, and its read clears the key."""
    rig = build()
    row = await request(rig)
    rig.venue.script("positions", ServiceUnavailableError("the venue is restarting"))
    await refused(rig)
    await rig.idle()
    assert rig.count("read_failed") == 1 and status(rig, row) == "pending"
    await refused(rig)
    assert rig.venue.reads() == 1 and not rig.gate._running  # cooling: the venue not asked
    await rig.gate.clear(KEY, wait_s=5.0)
    assert rig.venue.reads() == 2 and status(rig, row) == "void"


async def test_a_restore_row_is_held_unread_paged_and_logged_once_per_hold() -> None:
    rig = build()
    row = await request(rig, source="restore")
    with capture_logs() as logs:
        for _ in range(2):
            await refused(rig)
            await rig.idle()
            rig.clock.s += 5.0  # past the cooldown: the next entry starts a read again
    assert rig.venue.calls == [] and status(rig, row) == "pending"
    assert rig.count("held_for_reconciliation") == 2
    assert rig.pager.calls == [
        f"oms_stop_restore_held: held_for_reconciliation, {WHERE}, E29-T06's"
    ]
    held = [entry["reasons"] for entry in logs if entry["event"] == "oms_stop_request_held"]
    assert held == [[RESTORE_HELD]]


async def held_entry(rig: Rig) -> RecordedStopRow:
    """An entry killed after its send, its Partial stop-loss answered, so held through
    `WAITING_ENTRY`; the read matches a stop that fired since (in history)."""
    entry = await stored(rig, "killed")
    row = await request(rig, source="entry_attach", order_id=entry.id, tpsl_mode="Partial",
                        size=Decimal("0.010"))  # fmt: skip
    await rig.stops.settle(cr.ACCOUNT, [row.id], "answered", at=cr.T0)
    rig.venue.seed_order(fired("partial_stop_loss", cr.STOP), uid=cr.UIDS["demo"])
    return row


@pytest.mark.parametrize(
    ("position", "order", "paged"),
    [
        (cr.position(), None, True),
        (cr.position(take_profit=Decimal(64000)), None, True),
        (cr.position(stop_loss=Decimal(55000)), None, False),
        (cr.position(), tpsl_order("partial_stop_loss", Decimal(55000)), False),
        (cr.position(side=None, qty="0"), None, False),
    ],
    ids=[
        "open_no_stop",
        "open_take_profit_only",
        "open_stop_loss",
        "partial_stop_loss_open",
        "flat",
    ],
)
async def test_a_hold_through_its_entry_pages_once_per_hold_when_open_with_no_stop_at_all(
    position: Position, order: Order | None, paged: bool
) -> None:
    """The lead's rulings on item 6: a C-2.6 exposure only E29-T06's pass clears (no stop-loss
    and no trail on the open position, `shows_no_stop`, and no Partial stop-loss order open); the
    key stays refused across both resolutions of the hold."""
    rig = build()
    row = await held_entry(rig)
    rig.venue.seed_position(position)
    if order is not None:
        rig.venue.seed_order(order, uid=cr.UIDS["demo"])
    for _ in range(2):
        await refused(rig)
        await rig.idle()
        rig.clock.s += 5.0
    assert rig.count("held_for_reconciliation") == 2 and status(rig, row) == "pending"
    page = (
        f"oms_stop_request_held: C-2.6 exposure, held_for_reconciliation, {WHERE} open with no"
        " stop at all, until E29-T06's pass"
    )
    assert rig.pager.calls == ([page] if paged else [])


async def test_a_stop_loss_voided_on_its_open_position_pages_with_its_ids() -> None:
    """A filled entry whose stop is absent: void `entry_filled_stop_absent` with `position_state`,
    audited ahead, paged (C-2.6); the key is clear for the protective re-attach."""
    rig = build()
    entry = await stored(rig, "submitting")
    venue = cr.exchange_order(cr.new_order(), state="filled", filled_qty=Decimal("0.010"))
    rig.venue.seed_order(venue, uid=cr.UIDS["demo"])
    row = await request(rig, source="entry_attach", order_id=entry.id)
    rig.venue.seed_position(cr.position())
    await refused(rig)
    await rig.idle()
    await rig.gate.clear(KEY)
    [(record, _)] = rig.audits.written
    assert (record.reason, record.detail["position_state"]) == ("entry_filled_stop_absent", "open")
    assert rig.pager.calls == [
        f"oms_stop_entry_filled_stop_absent: C-2.6 exposure, {WHERE}, {row.id}"
    ]
    assert rig.count("entry_filled_stop_absent") == 1


@pytest.mark.parametrize("seconds", [2.0, 0.5], ids=["app_clock_after", "app_clock_behind"])
async def test_a_row_from_before_the_start_waits_whatever_its_age(seconds: float) -> None:
    """Q7: a row stamped before the start waits, one stamped after it only past its bound, the app
    clock behind the database's or not."""
    rig = build(started_at=cr.T0 + timedelta(seconds=1))
    before = await request(rig)
    rig.clock.at, rig.clock.now = cr.T0 + timedelta(seconds=1.5), cr.T0 + timedelta(seconds=seconds)
    await request(rig, symbol="ETHUSDT")
    rig.venue.open.clear()
    await refused(rig)  # younger than its bound, waiting all the same
    await rig.gate.clear(PositionKey(cr.ACCOUNT, "ETHUSDT", 0))  # in flight inside its bound
    rig.venue.open.set()
    await rig.idle()
    assert status(rig, before) == "void"


@pytest.mark.parametrize("failure", ["floor_unread", "refused", "late"])
async def test_a_key_whose_rows_cannot_be_read_is_store_unavailable(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: no stop request leaves unchecked (503 `store_unavailable`), nothing read."""
    rig = build(started_at=None if failure == "floor_unread" else cr.T0, read_timeout_s=0.01)

    async def refuses(*_args: Any, **_kwargs: Any) -> None:
        raise StorageTierUnavailable("down")

    async def hangs(*_args: Any, **_kwargs: Any) -> None:
        await asyncio.Event().wait()

    if failure != "floor_unread":
        broken = refuses if failure == "refused" else hangs
        monkeypatch.setattr(rig.stops, "waiting_for_key", broken)
    with pytest.raises(StoreUnavailable):
        await rig.gate.clear(KEY)
    assert rig.venue.calls == [] and not rig.gate._running


async def test_aclose_cancels_the_running_reads_and_none_starts_after() -> None:
    rig = build()
    await request(rig)
    rig.venue.open.clear()
    await refused(rig)
    await until(lambda: rig.venue.reads() == 1)
    [task] = rig.gate._running.values()
    await rig.gate.aclose()
    assert task.cancelled() and rig.count("read_failed") == 0
    await refused(rig, wait_s=5.0)  # closed: refused at once, no read started
    assert rig.venue.reads() == 1
