"""The recorded stop's in-force and end hooks on an applied position push (E29-T05 #848, S5c;
24-internal-schemas.md Sec.8.8 rule 6, 21-database-schema.md Sec.3.3.11), the lost-stop episode
and its readiness gauge (the orchestrator's 12:45Z condition), and the one definition of what a
read shows of a recorded stop (`stop_shown`). The stops are `InMemoryRecordedStopStore` behind
`RecordedStopRepository`; every bound runs on the fake clock of `VirtualTimeLoop`."""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections.abc import Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Position
from candleviewer.oms import positions as projection
from candleviewer.oms import stop_resolution, stop_shown
from candleviewer.oms.fakes import InMemoryOrderStore, InMemoryRecordedStopStore
from candleviewer.oms.ports import NoPositionProtection, PositionKey
from candleviewer.oms.positions import RECORD_BOUND_S, OrderRows, PositionProjection, RecordedStops
from candleviewer.oms.repository import OrderRepository, RecordedStopRepository
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.positions import MAX_FUTURE_SKEW
from candleviewer.storage.repositories.recorded_stops import (
    InForce,
    RecordedStopRow,
    StaleRecordedStop,
)
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms.position_rig import ACCOUNT, NOW_US, OTHER, Rig, position, routed, stamp

T0 = datetime(2025, 10, 9, 8, tzinfo=UTC)  # the records' writes, before the rig's pushes
KEY = PositionKey(ACCOUNT, "BTCUSDT", 0)
OID = UUID(int=0x0E)
STOP, TP = Decimal("60000"), Decimal("63000")
FLAT: dict[str, Any] = {"qty": Decimal("0"), "side": None}


def row(n: int, **over: Any) -> RecordedStopRow:
    """A Full-mode `trading_stop` stop-loss of the long, pending and answered, unbound."""
    values: dict[str, Any] = {
        "id": UUID(int=n), "exchange_account_id": ACCOUNT, "symbol": "BTCUSDT",
        "position_idx": 0, "position_side": "Buy", "kind": "stop_loss", "source": "trading_stop",
        "order_id": None, "tpsl_mode": "Full", "trigger_price": STOP, "size": None,
        "trailing_distance": None, "trailing_active_price": None, "exchange_order_id": None,
        "status": "pending", "audit_record_id": UUID(int=0x99), "actor_user_id": None,
        "created_at": T0 + timedelta(seconds=n), "answered_at": T0, "in_force_at": None,
        "closed_at": None, "released_at": None, "position_marker": None,
    }  # fmt: skip
    return RecordedStopRow(**(values | over))


def bound(n: int, **over: Any) -> RecordedStopRow:
    """In force, bound to its stop's order."""
    return row(
        n, **({"status": "in_force", "in_force_at": T0, "exchange_order_id": f"x{n}"} | over)
    )


def order_row(**over: Any) -> OrderRow:
    values: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    return OrderRow(**(values | {"id": OID, "exchange_account_id": ACCOUNT} | over))


@dataclass
class Stops:
    """`RecordedStopRepository` over the in-memory store, recording each call's account, and
    scripting a lost compare-and-set (`stale` writes), a hung read or a leaked foreign row."""

    db: InMemoryOrderStore = field(default_factory=lambda: InMemoryOrderStore(clock=lambda: T0))
    stale: dict[str, int] = field(default_factory=dict)
    hang: bool = False
    fail: bool = False
    leak: tuple[RecordedStopRow, ...] = ()
    reads: int = 0
    accounts: list[UUID] = field(default_factory=list)
    ended: list[tuple[UUID, ...]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.repo = RecordedStopRepository(InMemoryRecordedStopStore(self.db))

    def seed(self, *rows: RecordedStopRow) -> None:
        for r in rows:
            self.db._stops[r.id] = r

    def status(self, n: int) -> tuple[str, str | None]:
        stored = self.db._stops[UUID(int=n)]
        return stored.status, stored.end

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        self.reads += 1
        self.accounts.append(account_id)
        if self.hang:
            await asyncio.Event().wait()
        if self.fail:
            raise RuntimeError("61000.5")
        return (*await self.repo.live_for_key(account_id, symbol, position_idx), *self.leak)

    async def put_in_force(
        self, account_id: UUID, rows: Sequence[RecordedStopRow], *,
        in_force: Sequence[RecordedStopRow], at: datetime,
    ) -> InForce:  # fmt: skip
        self.accounts.append(account_id)
        self._lose("put_in_force")
        return await self.repo.put_in_force(account_id, rows, in_force=in_force, at=at)

    async def end(
        self, account_id: UUID, rows: Sequence[RecordedStopRow], *, at: datetime
    ) -> tuple[RecordedStopRow, ...]:
        self.accounts.append(account_id)
        self.ended.append(tuple(r.id for r in rows))
        self._lose("end")
        return await self.repo.end(account_id, rows, at=at)

    def _lose(self, name: str) -> None:
        if self.stale.get(name, 0) > 0:
            self.stale[name] -= 1
            raise StaleRecordedStop


@dataclass
class Orders:
    """The order rows (`order_rows.get`): a row, None, or an exception per id."""

    rows: dict[UUID, OrderRow | Exception] = field(default_factory=dict)

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        await asyncio.sleep(0)
        found = self.rows.get(order_id)
        if isinstance(found, Exception):
            raise found
        return found


def build(rig: Rig, stops: Stops, orders: Orders | None = None, **kw: Any) -> PositionProjection:
    return rig.projection(
        **({"stops": stops, "order_rows": orders or Orders(), "now": lambda: T0} | kw)
    )


async def push(made: PositionProjection, p: Position) -> None:
    await made.take(AccountId(p.account_id), p, routed(p))


def _binds_as_the_projections_ports(
    stops: RecordedStopRepository, orders: OrderRepository
) -> tuple[RecordedStops, OrderRows]:
    return stops, orders  # mypy --strict checks the M14 facades against the two ports (S8)


# C4: in force.
@virtual
async def test_take_shown_pending_full_stop_goes_in_force_and_replaces_the_older_one() -> None:
    """R1: the latest shown row of its kind goes in force; the row in force before is replaced."""
    stops, rig = Stops(), Rig()
    stops.seed(bound(1, trigger_price=Decimal("59000")), row(2), row(3))
    await push(build(rig, stops), position(stop_loss=STOP))
    assert [stops.status(n)[0] for n in (1, 2, 3)] == ["replaced", "replaced", "in_force"]


@virtual
async def test_take_trail_whose_distance_shows_is_never_put_in_force() -> None:
    """R2: a trail is shown only by its distance and activation price, which no read shows."""
    stops = Stops()
    trail = {"trailing_distance": Decimal("50"), "trailing_active_price": Decimal("61500")}
    stops.seed(row(1, **trail))
    shows = position(stop_loss=STOP, trailing_stop_distance=Decimal("50"))
    await push(build(Rig(), stops), shows)
    assert stops.status(1) == ("pending", None)


@virtual
async def test_take_shown_pending_entry_attach_row_goes_in_force() -> None:
    """Q2: an entry's attach, the primary C-2.6 record, goes in force on the push showing it."""
    stops = Stops()
    stops.seed(row(1, source="entry_attach", order_id=OID))
    await push(build(Rig(), stops), position(stop_loss=STOP))
    assert stops.status(1)[0] == "in_force"


@virtual
async def test_take_shown_pending_restore_row_is_never_put_in_force_here() -> None:
    """Q2: a `restore` row is E29-T06's complete read's to put in force, never a push's."""
    stops = Stops()
    stops.seed(row(1, source="restore"))
    await push(build(Rig(), stops), position(stop_loss=STOP))
    assert stops.status(1) == ("pending", None)


@virtual
async def test_take_partial_row_is_never_put_in_force_here() -> None:
    """R3: a Partial side is shown by its materialised order row (S6), never by the position."""
    stops = Stops()
    stops.seed(row(1, tpsl_mode="Partial", size=Decimal("0.1")))
    await push(build(Rig(), stops), position(stop_loss=STOP))
    assert stops.status(1) == ("pending", None)


@virtual
async def test_take_shown_take_profit_goes_in_force_beside_its_stop_loss() -> None:
    stops = Stops()
    stops.seed(row(1), row(2, kind="take_profit", trigger_price=TP))
    await push(build(Rig(), stops), position(stop_loss=STOP, take_profit=TP))
    assert [stops.status(n)[0] for n in (1, 2)] == ["in_force", "in_force"]


# C5: the end.
@virtual
async def test_take_flat_push_ends_a_bound_in_force_row_in_force() -> None:
    """R4."""
    stops = Stops()
    stops.seed(bound(1))
    await push(build(Rig(), stops), position(**FLAT))
    assert stops.status(1) == ("ended", "in_force")


@virtual
async def test_take_flat_push_keeps_an_unbound_row_until_after_bind_ends_it() -> None:
    """R5: a fired Full-mode stop's flat push first: the record stays live and matchable for its
    order's push; once S6 binds it, `after_bind` ends it with the kept position."""
    stops = Stops()
    stops.seed(row(1, status="in_force", in_force_at=T0))
    made = build(Rig(), stops)
    await push(made, position(**FLAT))
    assert stops.status(1) == ("in_force", None)
    stops.seed(replace(stops.db._stops[UUID(int=1)], exchange_order_id="x1"))
    await made.after_bind(KEY)
    assert stops.status(1) == ("ended", "in_force")


@virtual
async def test_after_bind_with_no_applied_position_of_the_key_does_nothing() -> None:
    stops, rig = Stops(), Rig()
    stops.seed(bound(1))
    await build(rig, stops).after_bind(KEY)
    assert stops.reads == 0 and rig.counts == ["after_bind_unknown"]


@virtual
async def test_take_flat_push_keeps_a_released_row() -> None:
    stops = Stops()
    stops.seed(bound(1, exchange_order_id=None, released_at=T0))
    await push(build(Rig(), stops), position(**FLAT))
    assert stops.status(1) == ("in_force", None)


@virtual
async def test_take_flat_push_ends_an_answered_bound_trading_stop_answered_unread() -> None:
    """R6: a stop the exchange accepted, which may have fired before any read showed it."""
    stops = Stops()
    stops.seed(row(1, exchange_order_id="x1"), row(2, source="restore", exchange_order_id="x2"))
    await push(build(Rig(), stops), position(**FLAT))
    assert [stops.status(n) for n in (1, 2)] == [("ended", "answered_unread")] * 2


@virtual
async def test_take_flat_push_never_ends_an_unanswered_row() -> None:
    """R7: the bound row in force beside it still ends."""
    stops, rig = Stops(), Rig()
    stops.seed(row(1, answered_at=None, exchange_order_id="x1"), bound(2, kind="take_profit"))
    await push(build(rig, stops), position(**FLAT))
    assert [stops.status(n)[0] for n in (1, 2)] == ["pending", "ended"]
    assert "record_failed" not in rig.counts


@pytest.mark.parametrize(
    ("entry", "ends"),
    [
        (order_row(state="accepted", cum_exec_qty=Decimal("0")), False),  # resting
        (order_row(state="partially_filled", cum_exec_qty=Decimal("0.2")), False),  # resting
        (order_row(state="cancelled", cum_exec_qty=Decimal("0")), False),  # waiting
        (order_row(state="held", cum_exec_qty=Decimal("0")), False),  # waiting
        (None, False),  # no row: decides nothing
        (order_row(state="filled", cum_exec_qty=Decimal("0.4")), True),
        (order_row(state="cancelled", cum_exec_qty=Decimal("0.3")), True),  # filled, then ended
    ],
)
@virtual
async def test_take_flat_push_ends_an_entry_attach_row_only_once_its_entry_filled_and_rests_no_more(
    entry: OrderRow | None, ends: bool
) -> None:
    """R8 (d)."""
    stops = Stops()
    stops.seed(row(1, source="entry_attach", order_id=OID, exchange_order_id="x1"))
    orders = Orders({OID: entry} if entry is not None else {})
    await push(build(Rig(), stops, orders), position(**FLAT))
    assert stops.status(1)[0] == ("ended" if ends else "pending")


@pytest.mark.parametrize("error", [RuntimeError("x"), TimeoutError()])
@virtual
async def test_take_entry_attach_row_whose_order_read_fails_is_kept(error: Exception) -> None:
    """R8: fail closed; the bound row in force beside it still ends."""
    stops, rig = Stops(), Rig()
    entry = row(1, source="entry_attach", order_id=OID, exchange_order_id="x1")
    stops.seed(entry, bound(2, kind="take_profit"))
    await push(build(rig, stops, Orders({OID: error})), position(**FLAT))
    assert [stops.status(n)[0] for n in (1, 2)] == ["pending", "ended"]
    assert rig.counts.count("order_read_failed") == 1


@virtual
async def test_take_entry_attach_row_in_force_ends_with_no_order_read() -> None:
    stops = Stops()
    stops.seed(bound(1, source="entry_attach", order_id=OID))
    await push(build(Rig(), stops), position(**FLAT))
    assert stops.status(1) == ("ended", "in_force")


@virtual
async def test_take_one_way_reversal_ends_the_old_sides_rows_and_puts_the_new_sides_in_force() -> (
    None
):
    """R9: the short's own row, written with its entry's attach, goes in force once shown."""
    stops = Stops()
    stops.seed(bound(1), row(2, position_side="Sell", trigger_price=Decimal("62000")))
    await push(build(Rig(), stops), position(side="sell", stop_loss=Decimal("62000")))
    assert [stops.status(n) for n in (1, 2)] == [("ended", "in_force"), ("in_force", None)]
    assert stops.reads == 1  # the put compares the rows in force the end left: one pass


@pytest.mark.parametrize("stop_loss", [None, STOP, Decimal("55000")])
@virtual
async def test_take_push_open_on_the_rows_side_never_ends_it(stop_loss: Decimal | None) -> None:
    """R10, C-2.6: a position open on the row's side keeps every record of it, stop or no stop."""
    stops = Stops()
    stops.seed(bound(1), row(2, kind="take_profit", trigger_price=TP, exchange_order_id="x2"))
    await push(build(Rig(), stops), position(stop_loss=stop_loss))
    assert [stops.status(n)[0] for n in (1, 2)] == ["in_force", "pending"]
    assert stops.ended == []


@virtual
async def test_take_stale_push_writes_no_record() -> None:
    """R11: a row the store did not apply is not the position's complete read."""
    stops = Stops()
    stops.seed(bound(1))
    await push(build(Rig(upserts=["stale"]), stops), position(**FLAT))
    assert stops.reads == 0 and stops.status(1) == ("in_force", None)


@virtual
async def test_after_bind_on_a_flat_push_older_than_the_record_keeps_it() -> None:
    """SEC-S5C-01 (e), C-2.6: the open push an hour after the last applied flat one failed to
    store, so `after_bind` holds the flat push; the bound Partial stop placed for the new
    position, in force since then, is kept."""
    stops, rig = Stops(), Rig()
    made = build(rig, stops)
    await push(made, position(**FLAT, updated_at=NOW_US))
    rig.raises["upsert"] = RuntimeError("store down")
    await push(made, position(updated_at=NOW_US + 3_600_000_000))
    later = stamp(NOW_US) + timedelta(hours=1)
    stops.seed(
        bound(1, tpsl_mode="Partial", size=Decimal("0.1"), created_at=T0, answered_at=later,
              in_force_at=later)
    )  # fmt: skip
    await made.after_bind(KEY)
    assert stops.status(1) == ("in_force", None)
    assert rig.counts.count("record_newer_than_read") == 1


@pytest.mark.parametrize(
    ("newer_by", "status"),
    [(MAX_FUTURE_SKEW + timedelta(seconds=2), ("in_force", None)),
     (MAX_FUTURE_SKEW - timedelta(seconds=2), ("ended", "in_force"))],
)  # fmt: skip
@virtual
async def test_take_flat_push_ends_a_record_only_within_the_stores_skew_of_its_write(
    newer_by: timedelta, status: tuple[str, str | None]
) -> None:
    """SEC-S5C-01 (e) on the push path: a record in force more than `MAX_FUTURE_SKEW` after the
    push's exchange time postdates it, so the push cannot show it flat."""
    stops = Stops()
    flat = position(**FLAT)
    stops.seed(bound(1, in_force_at=stamp(flat.updated_at) + newer_by))
    await push(build(Rig(), stops), flat)
    assert stops.status(1) == status


@virtual
async def test_take_naive_wall_clock_counts_record_failed_and_pages_nothing() -> None:
    """SEC-S5C-02: the `now` port is aware UTC; a naive one makes the store refuse the write."""
    stops, rig = Stops(), Rig()
    stops.seed(bound(1))
    naive = T0.replace(tzinfo=None)  # the miswired port under test
    await push(build(rig, stops, now=lambda: naive), position(**FLAT))
    assert rig.counts.count("record_failed") == 1 and rig.pages == []
    assert stops.status(1) == ("in_force", None)


@virtual
async def test_take_lost_compare_and_set_reads_the_key_again_and_decides_afresh() -> None:
    """R12: the refused write is never acted on: a fresh read, a fresh decision."""
    stops, rig = Stops(stale={"put_in_force": 1}), Rig()
    stops.seed(row(1))
    await push(build(rig, stops), position(stop_loss=STOP))
    assert stops.reads == 2 and stops.status(1) == ("in_force", None)
    assert "record_stale" not in rig.counts


@pytest.mark.parametrize("write", ["put_in_force", "end"])
@virtual
async def test_take_always_stale_record_write_stops_after_three_attempts(write: str) -> None:
    """R12, C-2.18: the re-read loop is bounded; the next applied row or E29-T06 decides."""
    stops, rig = Stops(stale={write: 100}), Rig()
    stops.seed(row(1), bound(2, kind="take_profit"))
    shows = position(stop_loss=STOP) if write == "put_in_force" else position(**FLAT)
    await push(build(rig, stops), shows)
    assert stops.reads == projection.MAX_RECORD_ATTEMPTS == 3
    assert rig.counts.count("record_stale") == 1


@virtual
async def test_take_hung_record_read_is_cut_at_its_bound_and_the_snapshot_still_runs() -> None:
    """R13: the hook and the snapshot share one deadline; the hook only its part of it."""
    stops, rig = Stops(hang=True), Rig()
    spent = await rig.take(stops=stops, order_rows=Orders(), now=lambda: T0)
    assert spent == pytest.approx(RECORD_BOUND_S)
    assert len(rig.snaps) == 1 and rig.counts.count("record_failed") == 1


@virtual
async def test_take_record_store_failure_is_counted_and_the_snapshot_still_runs() -> None:
    stops, rig = Stops(fail=True), Rig()
    await push(build(rig, stops), position(**FLAT))
    assert rig.counts.count("record_failed") == 1 and stops.reads == 1 and len(rig.snaps) == 1


async def _leaky_flat_push() -> Stops:
    """R14: a store that leaks another account's row and another key's into the read."""
    foreign = bound(9, exchange_account_id=OTHER)
    stops = Stops(leak=(foreign, bound(8, symbol="ETHUSDT")))
    stops.seed(bound(1), foreign)
    await push(build(Rig(), stops), position(**FLAT))
    return stops


@virtual
async def test_take_names_only_its_own_accounts_rows() -> None:
    """R14: a leaked row of another account or another key is never named."""
    stops = await _leaky_flat_push()
    assert stops.ended == [(UUID(int=1),)] and stops.status(9) == ("in_force", None)


@virtual
async def test_take_scopes_every_record_call_to_the_streams_account() -> None:
    stops = await _leaky_flat_push()
    assert set(stops.accounts) == {ACCOUNT}


# The episode and the readiness gauge (the orchestrator's 12:45Z condition).
@virtual
async def test_take_lost_stop_episode_ends_when_a_reading_is_handed_on() -> None:
    rig = Rig(took=[True])
    made = build(rig, Stops(), readings=NoPositionProtection())
    await push(made, position())
    rig.ids = (UUID(int=1),)  # a live order takes the next reading
    await push(made, position())
    rig.ids = ()
    await push(made, position())
    assert len(rig.pages) == 2


async def _unhanded_lost_takes() -> Rig:
    rig = Rig()
    made = build(rig, Stops(), readings=NoPositionProtection())
    for _ in range(1 + 2 * projection.REPAGE_AFTER):
        await push(made, position())
    return rig


@virtual
async def test_take_lost_stop_handed_nothing_on_pages_again_after_repage_after_takes() -> None:
    assert len((await _unhanded_lost_takes()).pages) == 3


@virtual
async def test_take_lost_stop_repage_is_counted_apart_from_the_first_page() -> None:
    assert (await _unhanded_lost_takes()).counts.count("lost_repaged") == 2


@virtual
async def test_oldest_unhanded_age_reads_the_oldest_owed_key_on_the_fake_clock() -> None:
    rig = Rig()
    made = build(rig, Stops(), readings=NoPositionProtection())
    assert made.oldest_unhanded_age_s() == 0.0
    await push(made, position())  # BTCUSDT owed from here
    rig.cost["upsert"] = 4.0
    await push(made, position(symbol="ETHUSDT"))
    assert made.oldest_unhanded_age_s() == pytest.approx(4.0)
    rig.ids, rig.cost["upsert"] = (UUID(int=1),), 1.0
    await push(made, position())  # BTCUSDT's reading handed on: ETHUSDT is the oldest
    assert made.oldest_unhanded_age_s() == pytest.approx(1.0)
    await push(made, position(symbol="ETHUSDT"))
    assert made.oldest_unhanded_age_s() == 0.0


@virtual
async def test_oldest_unhanded_age_keeps_a_held_row_evicted_from_the_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S5B-05: an evicted future-dated row's reading stays owed in readiness."""
    monkeypatch.setattr(projection, "MAX_REFUSED", 1)
    rig = Rig(upserts=["dated", "dated", "dated"])
    made = build(rig, Stops())
    await push(made, position())
    rig.cost["upsert"] = 2.0
    await push(made, position(symbol="ETHUSDT"))  # BTCUSDT's row is evicted
    assert rig.counts.count("refused_evicted") == 1
    assert made.oldest_unhanded_age_s() == pytest.approx(4.0)


@pytest.mark.parametrize("newer", ["dated", "applied"])
@virtual
async def test_hold_keeps_the_newer_row_when_a_reapply_races_a_take(
    newer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-S5B-06: a re-apply of an older held row that finishes after a newer row of the key
    was held or applied never puts the older one back."""
    old, new = position(), position(updated_at=NOW_US + 999_999)
    rig = Rig(upserts=["dated", newer, "dated", "applied"])
    made = build(rig, Stops())
    await push(made, old)
    entered, gate, base = asyncio.Event(), asyncio.Event(), rig.upsert

    async def gated(state: Any) -> Any:  # the older row's re-apply waits for the newer row
        if state.exchange_updated_ts == stamp(old.updated_at):
            entered.set()
            await gate.wait()
        return await base(state)

    monkeypatch.setattr(rig, "upsert", gated)
    racing = asyncio.create_task(made.reapply(ACCOUNT))
    await entered.wait()
    await push(made, new)
    gate.set()
    await racing
    monkeypatch.undo()
    rig.handed.clear()
    await made.reapply(ACCOUNT)
    times = [value.updated_time for _, value in rig.handed]
    assert times == ([new.updated_at // 1_000] if newer == "dated" else [])


# The one definition (C-2.6): moved verbatim from `stop_resolution`.
_MOVED_FROM = "2899fdc0"  # the last commit to change `stop_resolution.py`; same as origin/main
_MOVED = '''\
type PositionState = Literal["open", "flat"]


def position_state(row: RecordedStopRow, position: Position | None) -> PositionState:
    """`open` when the position holds a size on the row's side, else `flat`: none on its side,
    the other side's included (a one-way reversal)."""
    if position is None or position.qty <= 0 or position.side != row.position_side.lower():
        return "flat"
    return "open"


def full_shows(row: RecordedStopRow, position: Position | None) -> bool:
    """A Full side the position shows: open on the row's side, its stop-loss or take-profit at
    the trigger. Never a trail: it is shown only by its distance and activation price."""
    if row.tpsl_mode != "Full" or position is None or position_state(row, position) != "open":
        return False
    if row.kind == "take_profit":
        return position.take_profit == row.trigger_price
    return row.trailing_distance is None and position.stop_loss == row.trigger_price


def trail_unreadable(row: RecordedStopRow, position: Position | None) -> bool:
    """A trail whose distance the open position shows: no read shows its activation price yet
    (`[O-4]`), so it can be neither shown nor taken for absent, and is held."""
    return (
        row.tpsl_mode == "Full"
        and row.trailing_distance is not None
        and position is not None
        and position_state(row, position) == "open"
        and position.trailing_stop_distance == row.trailing_distance
    )
'''
_NAMES = ("position_state", "full_shows", "trail_unreadable")


def test_stop_shown_helpers_are_one_definition_in_both_modules() -> None:
    for name in (*_NAMES, "PositionState"):
        assert getattr(stop_resolution, name) is getattr(stop_shown, name)


def test_stop_shown_helpers_are_byte_identical_ast_to_their_definitions_before_the_move() -> None:
    def defs(source: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef):
                out[node.name] = ast.dump(node)
            elif isinstance(node, ast.TypeAlias):
                out[node.name.id] = ast.dump(node)
        return out

    before, after = defs(_MOVED), defs(inspect.getsource(stop_shown))
    for name in (*_NAMES, "PositionState"):
        assert after[name] == before[name], name
