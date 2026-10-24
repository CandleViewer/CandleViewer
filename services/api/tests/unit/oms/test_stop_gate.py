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
from candleviewer.oms import stop_gate
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
from tests.unit.oms.test_stop_decision import fired, stop_row, tpsl_order

KEY = PositionKey(cr.ACCOUNT, cr.SYMBOL, 0)
WHERE = f"account {cr.ACCOUNT} {cr.SYMBOL} position_idx 0"
EVENT = NewOrderEvent(kind="submit_attempt", source="local", event_ts=cr.T0)
EXPOSED = (
    f"oms_stop_request_held: C-2.6 exposure, held_for_reconciliation, {WHERE} open with no stop at"
    " all, until E29-T06's pass"
)
FILL_VOID = (
    f"oms_stop_entry_filled_stop_absent: C-2.6 exposure, {WHERE}, {{}}: a stop-loss voided while"
    " its position is open on its side (C-2.6)"
)


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


async def refused(rig: Rig, key: PositionKey = KEY, **asked: Any) -> None:
    with pytest.raises(StopRequestPending) as pending:
        await rig.gate.clear(key, **asked)
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
    attach = asyncio.create_task(rig.gate.clear(KEY, wait_s=5.0, protective=True))
    await until(lambda: rig.venue.reads() == 1)
    assert not attach.done()
    rig.venue.open.set()
    await attach  # returned: the read ended and a fresh read lists nothing


async def test_an_attach_past_its_wait_is_refused_and_the_read_runs_on() -> None:
    rig = build()
    await request(rig)
    rig.venue.open.clear()
    await refused(rig, wait_s=0.01, protective=True)  # the read held past the wait
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
    await refused(rig, keys[-2], wait_s=0.01, protective=True)  # an attach takes it
    await refused(rig, keys[-1], wait_s=0.01, protective=True)  # none left
    await until(lambda: rig.venue.reads() == MAX_RESOLUTIONS)
    assert keys[-1] not in rig.gate._running
    rig.venue.open.set()
    await rig.idle()


async def busy(rig: Rig) -> list[PositionKey]:
    """Every slot taken: seven entries' reads and an attach's, each held at the venue; a ninth key
    waits too."""
    keys = [PositionKey(cr.ACCOUNT, f"COIN{n}USDT", 0) for n in range(MAX_RESOLUTIONS + 1)]
    for key in keys:
        await request(rig, symbol=key.symbol)
    rig.venue.open.clear()
    for key in keys[: MAX_RESOLUTIONS - 1]:
        await refused(rig, key)
    await refused(rig, keys[MAX_RESOLUTIONS - 1], wait_s=0.01, protective=True)  # the kept slot
    await until(lambda: rig.venue.reads() == MAX_RESOLUTIONS)
    return keys


async def turns(n: int = 100) -> None:
    """Turn the loop `n` times: what is waiting stays waiting, and nothing sleeps."""
    for _ in range(n):
        await asyncio.sleep(0)


async def test_an_attach_that_finds_every_slot_taken_waits_for_one_within_its_wait() -> None:
    """SEC-S3H3A-02 (C-2.6): a protective attach is not refused for want of a slot while its wait
    lasts; once a read ends it starts its key's read and clears when that read has."""
    rig = build()
    keys = await busy(rig)
    attach = asyncio.create_task(rig.gate.clear(keys[-1], wait_s=5.0, protective=True))
    await turns()
    assert not attach.done() and keys[-1] not in rig.gate._running  # waiting for a slot
    rig.gate._running[keys[0]].cancel()  # one read ends
    await until(lambda: rig.venue.reads() == MAX_RESOLUTIONS + 1)  # the attach's read starts
    assert keys[-1] in rig.gate._running
    rig.venue.open.set()
    await attach  # its read ended and a fresh read lists nothing
    await rig.idle()


async def test_an_attach_waits_for_a_slot_no_longer_than_its_wait_and_an_entry_not_at_all() -> None:
    """SEC-S3H3A-02: with no slot freed the attach is refused once its wait is spent, nothing
    started for it; an entry under the same load is refused at once, whatever wait it names."""
    rig = build()
    keys = await busy(rig)
    attach = asyncio.create_task(rig.gate.clear(keys[-1], wait_s=0.05, protective=True))
    entry = asyncio.create_task(rig.gate.clear(keys[-1], wait_s=5.0))
    await turns()
    assert entry.done() and not attach.done()
    with pytest.raises(StopRequestPending):
        await entry
    with pytest.raises(StopRequestPending):
        await attach
    assert keys[-1] not in rig.gate._running and rig.venue.reads() == MAX_RESOLUTIONS
    rig.venue.open.set()
    await rig.idle()


async def test_a_resolution_with_the_floor_unread_decides_nothing() -> None:
    """SEC-S3H3A-01: never resolved with no bound, which would list every unanswered row and void
    an entry still on its way blind (21 Sec.3.3.11); it counts `read_failed` and cools its key."""
    rig = build(started_at=None)
    row = await request(rig)
    await rig.gate._resolve(KEY)
    assert rig.venue.calls == [] and status(rig, row) == "pending"
    assert rig.count("read_failed") == 1 and KEY in rig.gate._cooling


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
    await rig.gate.clear(KEY, wait_s=5.0, protective=True)
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


async def held_entry(rig: Rig, way: str = "matched") -> RecordedStopRow:
    """An entry killed after its send, so its Partial stop-loss is held through `WAITING_ENTRY`,
    which a stop that fired since (in history) matches: answered already (`matched`), answered by
    the read itself (`unanswered`), or answered with the venue showing the entry filled (`filled`,
    CR-S3H3A-02)."""
    entry = await stored(rig, "killed")
    row = await request(rig, source="entry_attach", order_id=entry.id, tpsl_mode="Partial",
                        size=Decimal("0.010"))  # fmt: skip
    if way != "unanswered":
        await rig.stops.settle(cr.ACCOUNT, [row.id], "answered", at=cr.T0)
    if way == "filled":
        filled = cr.exchange_order(cr.new_order(), state="filled", filled_qty=Decimal("0.010"))
        rig.venue.seed_order(filled, uid=cr.UIDS["demo"])
    rig.venue.seed_order(fired("partial_stop_loss", cr.STOP), uid=cr.UIDS["demo"])
    return row


@pytest.mark.parametrize(
    ("way", "held"),
    [("matched", 2), ("unanswered", 2), ("filled", 1)],
    ids=["answered_matched", "answered_by_the_read", "entry_filled"],
)
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
    way: str, held: int, position: Position, order: Order | None, paged: bool
) -> None:
    """The lead's rulings on item 6: a C-2.6 exposure only E29-T06's pass clears (no stop-loss
    and no trail on the open position, `shows_no_stop`, and no Partial stop-loss order open),
    wherever the hold through its entry comes from (CR-S3H3A-02); the key stays refused across
    both resolutions of the hold, counted `held_for_reconciliation` once a resolution, or once a
    hold where no decision is (a filled entry's answered stop, CR-S3H3A-03)."""
    rig = build()
    row = await held_entry(rig, way)
    rig.venue.seed_position(position)
    if order is not None:
        rig.venue.seed_order(order, uid=cr.UIDS["demo"])
    for _ in range(2):
        await refused(rig)
        await rig.idle()
        rig.clock.s += 5.0
    assert rig.count("held_for_reconciliation") == held and status(rig, row) == "pending"
    assert rig.pager.calls == ([EXPOSED] if paged else [])


async def test_a_held_key_asked_again_inside_its_cooldown_is_refused_unread() -> None:
    """CR-S3H3A-03: a resolution that wrote nothing (a filled entry's answered stop-loss, held)
    cools its key, so an entry asked again inside 5 s is refused without reading the venue."""
    rig = build()
    await held_entry(rig, "filled")
    rig.venue.seed_position(cr.position())
    for reads in (1, 1):
        await refused(rig)
        await rig.idle()
        assert rig.venue.reads() == reads
    rig.clock.s += 5.0
    await refused(rig)
    await rig.idle()
    assert rig.venue.reads() == 2 and rig.count("answered") == 2


@pytest.mark.parametrize("pager_down", [False, True], ids=["paged", "pager_down"])
async def test_a_stop_loss_voided_on_its_open_position_pages_with_its_ids(pager_down: bool) -> None:
    """A filled entry whose stop is absent: void `entry_filled_stop_absent` with `position_state`,
    audited ahead, paged (C-2.6); the key is clear for the protective re-attach. A page the pager
    refuses is lost, logged critical by its failure, never the void (CR-S3H3A-06)."""
    rig = build()
    entry = await stored(rig, "submitting")
    venue = cr.exchange_order(cr.new_order(), state="filled", filled_qty=Decimal("0.010"))
    rig.venue.seed_order(venue, uid=cr.UIDS["demo"])
    row = await request(rig, source="entry_attach", order_id=entry.id)
    rig.venue.seed_position(cr.position())
    rig.pager.refuse = pager_down
    with capture_logs() as logs:
        await refused(rig)
        await rig.idle()
    await rig.gate.clear(KEY)
    [(record, _)] = rig.audits.written
    assert (record.reason, record.detail["position_state"]) == ("entry_filled_stop_absent", "open")
    assert rig.pager.calls == ([] if pager_down else [FILL_VOID.format(row.id)])
    assert rig.count("entry_filled_stop_absent") == 1
    lost = [(e["log_level"], e["failure"]) for e in logs if e["event"] == "oms_pager_failed"]
    assert lost == ([("critical", "RuntimeError")] if pager_down else [])


async def test_a_void_that_committed_pages_once_though_a_later_write_of_its_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3H3A-04: a killed entry the venue shows filled, its answered stop-loss absent from the
    open position, is voided and paged as the void commits, counted once, though the read's next
    void (a trading-stop request nothing shows) fails: that one stays, and the read is
    `read_failed`."""
    rig = build()
    entry = await stored(rig, "killed")
    filled = cr.exchange_order(cr.new_order(), state="filled", filled_qty=Decimal("0.010"))
    rig.venue.seed_order(filled, uid=cr.UIDS["demo"])
    voided = await request(rig, source="entry_attach", order_id=entry.id)
    await rig.stops.settle(cr.ACCOUNT, [voided.id], "answered", at=cr.T0)
    kept = await request(rig)
    rig.venue.seed_position(cr.position())
    resolve = rig.stops.resolve

    async def fails(account_id: Any, rows: Any, outcome: Any, **over: Any) -> Any:
        if outcome == "in_flight_resolved":
            raise StorageTierUnavailable("down")
        return await resolve(account_id, rows, outcome, **over)

    monkeypatch.setattr(rig.stops, "resolve", fails)
    await refused(rig)
    await rig.idle()
    assert (status(rig, voided), status(rig, kept)) == ("void", "pending")
    assert rig.pager.calls == [FILL_VOID.format(voided.id)]
    assert (rig.count("entry_filled_stop_absent"), rig.count("read_failed")) == (1, 1)


@pytest.mark.parametrize(
    ("seconds", "stamped"),
    [(2.0, 0.0), (0.5, 0.0), (0.5, 0.75)],
    ids=["app_clock_after", "app_clock_behind", "stamped_after_the_app_clock"],
)
async def test_a_row_from_before_the_start_waits_whatever_its_age(
    seconds: float, stamped: float
) -> None:
    """Q7: a row stamped before the start waits, one stamped after it only past its bound, the app
    clock behind the database's or not; behind it, a row stamped between the app clock's `now` and
    the start waits too: the listing's `now` is never before the start (CR-S3H3A-05)."""
    rig = build(started_at=cr.T0 + timedelta(seconds=1))
    rig.clock.at = cr.T0 + timedelta(seconds=stamped)
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
    await refused(rig, wait_s=5.0, protective=True)  # closed: refused at once, no read started
    assert rig.venue.reads() == 1


async def test_a_resolution_past_its_bound_decided_nothing_and_cools_its_key() -> None:
    """CR-S3H3A-06: the whole resolution's bound (30 s; a hundredth here) ends a read that never
    answers: `read_failed`, logged by its type, and an entry asked again meets the cooldown."""
    rig = build(resolution_timeout_s=0.01)
    row = await request(rig)
    rig.venue.open.clear()
    with capture_logs() as logs:
        await refused(rig)
        await rig.idle()
    assert rig.count("read_failed") == 1 and status(rig, row) == "pending"
    failed = [e["failure"] for e in logs if e["event"] == "oms_stop_resolution_failed"]
    assert failed == ["TimeoutError"]
    await refused(rig)
    assert rig.venue.reads() == 1 and not rig.gate._running


async def test_the_holds_and_cooldowns_kept_are_bounded_and_ended_cooldowns_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3H3A-06 (C-2.18): past `MAX_HOLDS` keys the oldest hold and cooldown are forgotten, so
    that key is read again inside its 5 s and its hold announced again; a cooldown that ended is
    pruned as the next begins."""
    monkeypatch.setattr(stop_gate, "MAX_HOLDS", 2)
    rig = build()
    keys = [PositionKey(cr.ACCOUNT, f"COIN{n}USDT", 0) for n in range(3)]
    for key in keys:
        await request(rig, symbol=key.symbol, source="restore")
    with capture_logs() as logs:
        for key in (*keys, keys[0]):
            await refused(rig, key)
            await rig.idle()
    held = [e["symbol"] for e in logs if e["event"] == "oms_stop_request_held"]
    assert held == ["COIN0USDT", "COIN1USDT", "COIN2USDT", "COIN0USDT"]
    assert rig.count("held_for_reconciliation") == 4
    rig.clock.s += 5.0
    await refused(rig, keys[1])
    await rig.idle()
    assert list(rig.gate._cooling) == [keys[1]]


async def test_a_take_profit_void_is_audited_as_tp_modified() -> None:
    """CR-S3H3A-06: a take-profit side's void record is `tp.modified`, named by reason and row."""
    audits, row = cr.Audits(), stop_row(kind="take_profit", trigger_price=Decimal(64000))
    await StopVoidAudit(audits).hook("in_flight_resolved")((row,), None)
    [(record, _)] = audits.written
    assert isinstance(record, KeyedRecord)
    assert (record.action, record.name) == ("tp.modified", f"in_flight_resolved:{row.id}")


async def test_an_attach_whose_read_ends_with_its_key_still_listed_is_refused() -> None:
    """CR-S3H3A-06: an attach waits for the read of its key, which a `restore` row keeps held:
    listed still once the read ended, the attach is refused (B1's `sl_missing`), nothing read."""
    rig = build()
    await request(rig, source="restore")
    await refused(rig, wait_s=5.0, protective=True)
    assert rig.venue.calls == [] and rig.count("held_for_reconciliation") == 1


async def test_a_gate_tasks_unexpected_error_is_logged_by_its_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3H3A-08: an error out of a resolution's own end, not left for asyncio's "never
    retrieved"."""
    rig = build()
    await request(rig, source="restore")

    def fails(_key: PositionKey) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(rig.gate, "_cool", fails)
    with capture_logs() as logs:
        await refused(rig)
        await rig.idle()
    failed = [
        (e["log_level"], e["failure"]) for e in logs if e["event"] == "oms_stop_gate_task_failed"
    ]
    assert failed == [("error", "RuntimeError")]


async def test_the_floors_start_is_read_once_from_the_databases_clock() -> None:
    """Q7: once, so a sweep retried after this runtime wrote a row never moves it past that row."""
    rig = build(started_at=None)
    rig.clock.at = cr.T0 + timedelta(seconds=1)
    assert await rig.gate.start_floor() == cr.T0 + timedelta(seconds=1)
    rig.clock.at = cr.T0
    assert await rig.gate.start_floor() == cr.T0 + timedelta(seconds=1)


@pytest.mark.parametrize("refused_account", [False, True])
async def test_the_startup_pass_resolves_each_waiting_key_never_a_refused_accounts(
    refused_account: bool,
) -> None:
    """20 Sec.6.2 step 2: each waiting key of the account read once; an account the binding
    refuses (paged there) leaves its keys refused, never read."""
    rig = build(accounts=() if refused_account else (cr.ref(),))
    rows = [await request(rig, symbol=symbol) for symbol in ("BTCUSDT", "ETHUSDT")]
    with capture_logs() as logs:
        rig.gate.start_pass(cr.ACCOUNT)
        await until(lambda: not rig.gate._passes)
        await rig.idle()
    assert rig.venue.reads() == (0 if refused_account else 2)
    assert [status(rig, row) for row in rows] == ["pending" if refused_account else "void"] * 2
    skipped = [entry["failure"] for entry in logs if entry["event"] == "oms_stop_pass_skipped"]
    assert skipped == (["AccountScopeDenied"] if refused_account else [])


async def test_a_pass_over_more_keys_than_slots_leaves_the_kept_slot_and_follows_as_they_free() -> (
    None
):
    """CR-S3H3B-02 and -03 (C-2.18): one pass per account, the sweep's retry adding none; it starts
    seven reads, waits for a slot rather than take the one kept for an attach (which an attach
    still takes), and starts each next key as a read ends."""
    rig = build()
    keys = [PositionKey(cr.ACCOUNT, f"COIN{n}USDT", 0) for n in range(MAX_RESOLUTIONS + 1)]
    rows = [await request(rig, symbol=key.symbol) for key in keys]
    rig.venue.open.clear()
    for _ in range(2):  # the sweep retried while its pass runs
        rig.gate.start_pass(cr.ACCOUNT)
    await until(lambda: rig.venue.reads() == MAX_RESOLUTIONS - 1)
    for _ in range(64):  # turns enough for an eighth read, which never starts
        await asyncio.sleep(0)
    passes = [t for t in asyncio.all_tasks() if t.get_name() == "oms-stop-pass"]
    assert rig.venue.reads() == MAX_RESOLUTIONS - 1 and len(passes) == 1
    unread = next(key for key in keys if key not in rig.gate._running)
    attach = asyncio.create_task(rig.gate.clear(unread, wait_s=5.0, protective=True))
    await until(lambda: rig.venue.reads() == MAX_RESOLUTIONS)
    rig.venue.open.set()
    await attach
    await until(lambda: not rig.gate._passes)
    await rig.idle()
    assert rig.venue.reads() == len(keys)
    assert [status(rig, row) for row in rows] == ["void"] * len(keys)
