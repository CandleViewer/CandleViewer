"""The closed-PnL sync (E29-S06 #981 slice 3; 24 Sec.8.13 "The sync"), on the fake clock of
`VirtualTimeLoop`: every wait runs on fake seconds, so no test sleeps in real time. The venue's
records are the transcribed `rest/trading-closed-pnl.json` row as a USDT one (its `symbol`
changed), and the readings the docs-transcribed `ws/private-position.jsonl` row, a size 0; each
variant changes the values it names. The seed is the orchestrator's ruling of 2026-11-04 (15:51Z).
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.domain.order_entry import OrderEntryRefusal, RefusalReason
from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.models import AccountRef, ClosedPnl, Position, RateLane
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import closed_pnl_sync as sync_mod
from candleviewer.oms.closed_pnl_compose import ClosedPnlComposer
from candleviewer.oms.closed_pnl_sync import (
    CLOSED_PNL_LOOKBACK,
    FETCH_SECONDS,
    ClosedPnlSync,
    merged,
    venue_record,
)
from candleviewer.oms.errors import AccountScopeDenied, OrderEntryRefused, StoreUnavailable
from candleviewer.oms.ports import RateReading
from candleviewer.risk.day_boundary import DayBoundary
from candleviewer.storage.repositories.closed_pnl import (
    VENUE_COLUMNS,
    ClosedPnlRecordRow,
    ComposedRecord,
    FillKey,
    OrderAnchor,
    PendingRecord,
    SettleOutcome,
    VenueRecord,
    WalkFill,
    orderless_record_id,
    record_id,
    settle_outcome,
)  # fmt: skip
from candleviewer.storage.repositories.closed_pnl_sqlalchemy import LOCAL, PROVISIONAL
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.positions import NewPositionSnapshot
from tests._corpus import frames, rest
from tests.unit.audit.audit_waits import virtual
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, account
from tests.unit.oms.submit_rig import Instruments, instrument
from tests.unit.risk.test_day_boundary import Policy

T0 = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)  # the fake loop's 0 s
XID, ORDER = "5a373bfe-188d-4913-9c81-d57ab5be8068", UUID(int=0x0D)  # the record's orderId
REACH = datetime(2026, 10, 28, tzinfo=UTC)  # 00:00 UTC of T0's day, CLOSED_PNL_LOOKBACK before


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _us(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


def _at(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


_ROW = {**rest("rest/trading-closed-pnl.json")["result"]["list"][0], "symbol": "ETHUSDT"}
_BASE = tp.to_closed_pnl(tp.parse(tp.ClosedPnlRow, _ROW, "closed-pnl"), account())


def _record(**over: Any) -> ClosedPnl:
    """The transcribed record as a USDT one, closed an hour before T0 unless `over` says."""
    hour = _us(T0 - timedelta(hours=1))
    return _BASE.model_copy(update={"created_at": hour - 5_000, "closed_at": hour} | over)


def _reading(**changed: str) -> Position:
    """The docs-transcribed position push (BTCUSDT, `positionIdx` 2, size 0), values changed."""
    body = json.loads(frames("ws/private-position.jsonl")[0])
    body["data"][0] |= changed
    pushed = pp.classify(json.dumps(body))
    assert isinstance(pushed, pp.Push)
    [event] = pp.read_push(pushed, account(), now_us=_us(T0))
    assert isinstance(event.payload, Position)
    return event.payload


def _fill(closed_size: Decimal | None) -> NewExecution:
    return NewExecution(
        exchange_account_id=ACCOUNT_A, exec_id="e1", symbol="ETHUSDT", side="Buy",
        exec_qty=Decimal("0.5"), exec_price=Decimal(1180), exec_value=Decimal(590),
        exec_type="Trade", is_maker=False, exec_ts=T0, closed_size=closed_size,
    )  # fmt: skip


@dataclass
class Venue:
    """The trading port and its router: each read recorded at the loop's time, with its window."""

    records: list[ClosedPnl] = field(default_factory=list)
    readings: list[Position] = field(default_factory=list)
    failures: list[Exception] = field(default_factory=list)  # the next reads', in order
    seed_failures: list[Exception] = field(default_factory=list)
    available: bool = True
    gate: asyncio.Event | None = None
    pause: float = 0.0  # each positions read's, on the loop's clock
    records_of: Any = None  # the account its records name, when set; else the one asked
    readings_of: Any = None  # the account its position readings name, likewise
    reads: list[tuple[float, int, int]] = field(default_factory=list)
    lanes: list[RateLane] = field(default_factory=list)
    position_reads: int = 0
    in_flight: int = 0
    most: int = 0

    def port_for(self, environment: Environment) -> Venue:
        return self

    def headroom(self, account: AccountRef, lane: RateLane) -> RateReading:
        self.lanes.append(lane)
        return RateReading(available=True) if self.available else RateReading(False, 1)

    async def closed_pnl(self, account: AccountRef, start: int, end: int) -> list[ClosedPnl]:
        self.reads.append((asyncio.get_running_loop().time(), start, end))
        self.in_flight += 1
        self.most = max(self.most, self.in_flight)
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.failures:
                raise self.failures.pop(0)
            named = {"account_id": self.records_of or account.account_id}
            return [r.model_copy(update=named) for r in self.records]
        finally:
            self.in_flight -= 1

    async def positions(self, account: AccountRef) -> list[Position]:
        self.position_reads += 1
        await asyncio.sleep(self.pause)
        if self.seed_failures:
            raise self.seed_failures.pop(0)
        named = {"account_id": self.readings_of or account.account_id}
        return [p.model_copy(update=named) for p in self.readings]


@dataclass
class Store:
    """The closed-PnL store as slice 2's decides a read's outcome (`settle_outcome`), the order rows
    row 56 joins, the stated closes, the confirmed flats (row 57) and the snapshots appended; and,
    for the composition, each order row's key by its id (`keys`), the stored trade fills by
    symbol, the symbols held in hedge mode and the calls made, rows 58, 61 and 62 and the upsert
    as `closed_pnl_sqlalchemy` writes them."""

    rows: dict[UUID, ClosedPnlRecordRow] = field(default_factory=dict)
    orders: dict[str, tuple[UUID, Any]] = field(default_factory=dict)
    closes: dict[UUID, Decimal | None] = field(default_factory=dict)
    flats: dict[tuple[str, int], tuple[datetime, ...]] = field(default_factory=dict)
    snapshots: list[NewPositionSnapshot] = field(default_factory=list)
    reaches: list[datetime] = field(default_factory=list)
    keys: dict[UUID, tuple[str, Any, int]] = field(default_factory=dict)
    fills: list[tuple[str, WalkFill]] = field(default_factory=list)
    hedge: set[str] = field(default_factory=set)
    calls: Counter[str] = field(default_factory=Counter)

    async def settle(self, record: VenueRecord) -> SettleOutcome:
        held = self.rows.get(record.id)
        outcome = settle_outcome(held, record)
        if outcome in ("inserted", "settled", "replaced"):
            venue = {name: getattr(record, name) for name in VENUE_COLUMNS}
            venue |= {"settled_at": held.settled_at or T0} if held else {}
            self.rows[record.id] = replace(held, **venue) if held else ClosedPnlRecordRow(
                id=record.id, exchange_account_id=record.exchange_account_id,
                exchange_order_id=record.exchange_order_id, symbol=record.symbol,
                side=record.side, position_idx=None, trade_group_id=None, gross_pnl=None,
                fee_pnl=None, funding_pnl=None, opened_at=None, settled_at=T0, final_at=None,
                divergent=False, audited_local_net=None, audited_closed_pnl=None, updated_at=T0,
                **venue,
            )  # fmt: skip
        return outcome

    async def finalize(self, account_id: UUID, record_id: UUID) -> bool:
        row = self.rows.get(record_id)
        if row is None or row.final_at is not None or row.settled_at is None:
            return False
        self.rows[record_id] = replace(row, final_at=T0)
        return True

    async def pending(
        self, account_id: UUID, reach: datetime, limit: int
    ) -> tuple[PendingRecord, ...]:
        self.reaches.append(reach)
        rows = [
            r for r in self.rows.values()
            if r.final_at is None and r.exchange_order_id in self.orders and r.closed_at >= reach
        ]  # fmt: skip
        return tuple(PendingRecord(r, *self.orders[str(r.exchange_order_id)]) for r in rows)

    async def walk_flats(
        self, account_id: UUID, symbol: str, position_idx: int, before: datetime, limit: int
    ) -> tuple[datetime, ...]:
        flats = sorted(set(self.flats.get((symbol, position_idx), ())))
        start = max((at for at in flats if at < before), default=None)
        return () if start is None else tuple(at for at in flats if at >= start)[:limit]

    async def walk_fills(
        self, account_id: UUID, symbol: str, position_idx: int, after: FillKey, limit: int
    ) -> tuple[WalkFill, ...]:
        self.calls["walk_fills"] += 1
        key = (after.at, after.exec_id or "")
        on = [
            f for s, f in self.fills if s == symbol and f.order_position_idx in (None, position_idx)
        ]
        later = [f for f in on if (f.exec_ts, f.exec_id if after.exec_id else "") > key]
        return tuple(sorted(later, key=lambda f: (f.exec_ts, f.exec_id))[:limit])

    async def anchors(
        self, account_id: UUID, orders: Any, exchange_order_ids: Any
    ) -> tuple[OrderAnchor, ...]:
        self.calls["anchors"] += 1
        found = []
        for xid, (oid, state) in self.orders.items():
            if (oid not in orders and xid not in exchange_order_ids) or oid not in self.keys:
                continue
            symbol, side, idx = self.keys[oid]
            own = [f for _, f in self.fills if f.order_id == oid]
            times = sorted(f.exec_ts for f in own)
            closing = [f.exec_ts for f in own if (f.closed_size or 0) > 0]
            flats = self.flats.get((symbol, idx), ())
            start = max((t for t in flats if times and t < times[0]), default=None)
            found.append(OrderAnchor(
                order_id=oid, exchange_order_id=xid, symbol=symbol, side=side, position_idx=idx,
                state=state, first_fill=times[0] if times else None,
                last_fill=times[-1] if times else None, last_close=max(closing, default=None),
                start=start, held=record_id(account_id, xid) in self.rows,
            ))  # fmt: skip
        return tuple(sorted(found, key=lambda a: a.order_id))

    async def hedged(self, account_id: UUID, symbol: str) -> bool:
        return symbol in self.hedge

    async def compose(self, record: ComposedRecord) -> ClosedPnlRecordRow:
        """`compose_statement`'s upsert: the local figures always, the provisional columns while
        the row is unsettled."""
        self.calls["compose"] += 1
        held, local = self.rows.get(record.id), {n: getattr(record, n) for n in LOCAL}
        provisional = {n: getattr(record, n) for n in PROVISIONAL}
        self.rows[record.id] = row = replace(
            held, **local, **({} if held.settled_at else provisional)
        ) if held else ClosedPnlRecordRow(
            id=record.id, exchange_account_id=record.exchange_account_id,
            exchange_order_id=record.exchange_order_id, symbol=record.symbol, side=record.side,
            leverage=None, closed_pnl=None, venue_created_at=None, settled_at=None, final_at=None,
            divergent=False, audited_local_net=None, audited_closed_pnl=None, updated_at=T0,
            **local, **provisional,
        )  # fmt: skip
        return row

    async def closed_size(self, account_id: UUID, order_id: UUID) -> Decimal | None:
        return self.closes.get(order_id)

    async def append(self, snapshot: NewPositionSnapshot) -> NewPositionSnapshot:
        self.snapshots.append(snapshot)
        return snapshot


@dataclass
class Accounts:
    named: Any = None  # the account every resolve answers, when set; else the one asked
    failures: list[Exception] = field(default_factory=list)  # the next resolves', in order

    async def trading_account(self, account_id: Any) -> AccountRef:
        if self.failures:
            raise self.failures.pop(0)
        return account(self.named or account_id)


@dataclass
class Rig:
    venue: Venue
    store: Store
    metrics: Metrics
    sync: ClosedPnlSync
    told: list[str]  # each end `on_ended` was told of

    def times(self) -> list[float]:
        return [round(at, 6) for at, _, _ in self.venue.reads]

    def counted(self) -> dict[str, float]:
        seen = self.metrics.snapshot([FETCH_SECONDS])
        return {k: seen.get(f"{FETCH_SECONDS}_count{{result={k}}}", 0) for k in ("ok", "failed")}

    def crossed(self) -> float:
        """The crossings between accounts, counted apart from `failed` (`other_account`)."""
        return self.metrics.snapshot([FETCH_SECONDS]).get(
            f"{FETCH_SECONDS}_count{{result=other_account}}", 0
        )


def rig(
    at: datetime = T0,
    resolve: Any = None,
    unresolved: Any = (),
    *,
    policy: Policy | None = None,
    composed: bool = False,
    **venue: Any,
) -> Rig:
    """The sync over fakes, its day from the one resolver over `policy` (offset 0 unless set);
    with `composed`, its composition over the same store, ETHUSDT settling 480 min apart."""
    v, store, metrics, loop = Venue(**venue), Store(), Metrics("demo"), asyncio.get_running_loop()
    told, listed = list[str](), Instruments(listed={"ETHUSDT": instrument(symbol="ETHUSDT")})
    sync = ClosedPnlSync(
        accounts=Accounts(resolve, list(unresolved)), router=v, records=store, closes=store,
        snapshots=store,
        metrics=metrics, now=lambda: at + timedelta(seconds=loop.time()),
        on_ended=lambda: told.append("ended"), day_start=DayBoundary(policy or Policy()).day_start,
        composer=ClosedPnlComposer(store=store, instruments=listed) if composed else None,
    )  # fmt: skip
    return Rig(v, store, metrics, sync, told)


# --- triggers, the poll and its end (24 Sec.8.13 "The sync") -------------------------------------


@virtual
async def test_startup_reads_each_account_once_from_the_lookback_before_the_days_start() -> None:
    r = rig(records=[_record()])
    assert r.sync.start([ACCOUNT_B, ACCOUNT_A]) and not r.sync.start([ACCOUNT_A])
    await asyncio.sleep(3600)  # the order has no row: nothing is polled
    assert [(s, e) for _, s, e in r.venue.reads] == [(_us(REACH), _us(T0))] * 2
    assert set(r.venue.lanes) == {"poll"} and r.counted() == {"ok": 2, "failed": 0}
    assert {row.exchange_account_id for row in r.store.rows.values()} == {ACCOUNT_A, ACCOUNT_B}
    await r.sync.stop()


@virtual
async def test_a_closing_fill_is_read_a_second_later_with_that_seconds_fills_then_polled() -> None:
    """Debounced 1 s; the fills keep the poll until a read starting SETTLE_POLL_S after them."""
    r = rig()
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    for _ in range(3):
        r.sync.stored(_fill(Decimal("0.5")))
        await asyncio.sleep(0.25)
    await asyncio.sleep(4.25)
    assert r.times() == [0, 11]
    await asyncio.sleep(600)
    assert r.times() == [0, 11, 71]  # the first read starting 60 s after the last fill (10.5 s)
    await r.sync.stop()


@virtual
async def test_a_fill_stating_no_close_is_read_once_its_poll_is_due_and_a_funding_row_never(
) -> None:  # fmt: skip
    r = rig()
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    r.sync.stored(replace(_fill(None), exec_type="Funding"))
    r.sync.stored(_fill(None))  # a REST-recovered fill: it states no `closedSize`
    await asyncio.sleep(600)
    assert r.times() == [0, 70]
    await r.sync.stop()


@virtual
async def test_requests_made_during_a_read_fold_into_one_next_read() -> None:
    r = rig(gate=asyncio.Event())
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)  # the startup read waits on the venue
    r.sync.reconnected(ACCOUNT_A)
    r.sync.reconnected(ACCOUNT_A)
    r.sync.stored(_fill(Decimal("0.5")))
    assert r.venue.gate is not None
    r.venue.gate.set()
    await asyncio.sleep(2)
    assert r.times() == [0, 1] and r.venue.most == 1
    await r.sync.stop()


@virtual
async def test_a_failed_read_keeps_the_poll_until_one_succeeds() -> None:
    r = rig(failures=[ConnectionError(), TimeoutError()])
    with capture_logs() as logs:
        r.sync.start([ACCOUNT_A])
        await asyncio.sleep(600)
    assert r.times() == [0, 60, 120] and r.counted() == {"ok": 1, "failed": 2}
    failed = [e["kind"] for e in logs if e["event"] == "closed_pnl_read_failed"]
    assert failed == ["ConnectionError", "TimeoutError"]
    await r.sync.stop()


@virtual
async def test_the_reach_is_the_lookback_before_the_resolvers_day_start() -> None:
    """At +180 the day starts at 21:00Z of the previous UTC date (24 Sec.8.13), so the read
    reaches `CLOSED_PNL_LOOKBACK` before that, the cap's own reach."""
    r = rig(policy=Policy(180))
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)
    start = datetime(2026, 11, 3, 21, tzinfo=UTC) - CLOSED_PNL_LOOKBACK
    assert [(s, e) for _, s, e in r.venue.reads] == [(_us(start), _us(T0))]
    await r.sync.stop()


@virtual
async def test_a_resolver_that_fails_fails_the_read_and_keeps_the_poll() -> None:
    """With its day unresolved the sync reads nothing, never from UTC midnight, and reads again
    `SETTLE_POLL_S` later, as after any failed read."""
    policy = Policy(failure=OSError("postgres unreachable"))
    r = rig(policy=policy)
    with capture_logs() as logs:
        r.sync.start([ACCOUNT_A])
        await asyncio.sleep(30)
        assert r.venue.reads == []
        policy.failure = None
        await asyncio.sleep(60)
    assert r.times() == [60] and r.counted() == {"ok": 1, "failed": 0}
    failed = [e["kind"] for e in logs if e["event"] == "closed_pnl_read_failed"]
    assert failed == ["DayBoundaryUnavailable"]
    await r.sync.stop()


def _refusal(reason: RefusalReason) -> OrderEntryRefused:
    return OrderEntryRefused(OrderEntryRefusal(reason, "Order entry is not available."))


@pytest.mark.parametrize(
    "refusal", [AccountScopeDenied(), _refusal("no_active_key")], ids=["deleted", "keyless"]
)
@virtual
async def test_an_account_the_binding_refuses_is_not_polled_until_its_next_trigger(
    refusal: Exception,
) -> None:
    """A refusal outright (deleted, missing or another environment's, or keyless) ends the
    account's poll, the wait its stored fill keeps too, rather than resolving it every
    `SETTLE_POLL_S` until a restart; its next trigger asks again."""
    r = rig(unresolved=[refusal] * 2)
    r.sync.start([])
    r.sync.stored(_fill(Decimal("0.5")))  # it comes in by a fill, whose wait would poll it
    await asyncio.sleep(600)
    assert r.counted() == {"ok": 0, "failed": 1}
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(600)
    assert r.counted() == {"ok": 0, "failed": 2} and r.venue.reads == []
    await r.sync.stop()


@pytest.mark.parametrize(
    "failure", [TimeoutError(), StoreUnavailable(), _refusal("maintenance")],
    ids=["timeout", "store", "another_refusal"],
)  # fmt: skip
@virtual
async def test_a_resolve_that_fails_otherwise_keeps_the_poll(failure: Exception) -> None:
    r = rig(unresolved=[failure] * 2)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(600)
    assert r.counted() == {"ok": 1, "failed": 2} and r.times() == [120]
    await r.sync.stop()


@virtual
async def test_every_read_rides_the_poll_lane_and_none_is_sent_without_its_headroom() -> None:
    """C-12.7: the reads draw on the governor's background class, never the stop and cancel
    reserve; a lane with no headroom sends nothing, and the read is tried again on the poll."""
    r = rig(available=False)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(61)
    assert r.venue.reads == [] and r.venue.lanes == ["poll", "poll"]
    assert r.counted() == {"ok": 0, "failed": 2}
    await r.sync.stop()


@virtual
async def test_the_poll_runs_while_a_record_whose_order_has_a_row_is_not_final() -> None:
    """Final once its order's row is terminal and its qty is what the order's stored fills state
    they closed: not while the order is open, nor while a fill states no size."""
    r = rig(records=[_record()])
    r.store.orders[XID], r.store.closes[ORDER] = (ORDER, "partially_filled"), Decimal(3)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(30)
    r.store.orders[XID], r.store.closes[ORDER] = (ORDER, "filled"), None
    await asyncio.sleep(60)
    r.store.closes[ORDER] = Decimal(3)
    await asyncio.sleep(600)
    assert r.times() == [0, 60, 120]
    assert r.store.rows[record_id(ACCOUNT_A, XID)].final_at is not None
    await r.sync.stop()


@virtual
async def test_a_record_with_no_order_id_or_no_order_row_is_kept_and_keeps_no_poll() -> None:
    orderless = _record(exchange_order_id=None, side="buy")
    r = rig(records=[orderless, _record()])
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(600)
    blank = orderless_record_id(ACCOUNT_A, "ETHUSDT", "short", _at(orderless.created_at))
    assert r.times() == [0] and set(r.store.rows) == {blank, record_id(ACCOUNT_A, XID)}
    await r.sync.stop()


@virtual
async def test_the_poll_ends_for_a_record_once_it_is_older_than_the_reach() -> None:
    """The reach is CLOSED_PNL_LOOKBACK before the day's start, so it moves at 00:00 UTC."""
    late = datetime(2026, 11, 4, 23, 58, 30, tzinfo=UTC)
    r = rig(late, records=[_record(closed_at=_us(REACH + timedelta(seconds=30)))])
    r.store.orders[XID] = (ORDER, "partially_filled")
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(600)
    assert r.times() == [0, 60, 120]
    assert r.store.reaches == [REACH, REACH, REACH + timedelta(days=1)]
    await r.sync.stop()


@virtual
async def test_a_read_after_final_is_logged_at_warning_and_never_applied() -> None:
    r = rig(records=[_record()])
    r.store.orders[XID], r.store.closes[ORDER] = (ORDER, "filled"), Decimal(3)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)
    kept = r.store.rows[record_id(ACCOUNT_A, XID)]
    assert kept.final_at is not None
    r.venue.records = [_record(closed_pnl=Decimal("-50"))]
    with capture_logs() as logs:
        r.sync.reconnected(ACCOUNT_A)
        await asyncio.sleep(1)
    assert r.store.rows[kept.id] == kept
    [line] = [e for e in logs if e["event"] == "closed_pnl_read_after_final"]
    assert (line["log_level"], line["exchange_order_id"]) == ("warning", XID)
    await r.sync.stop()


@virtual
async def test_records_under_one_order_are_stored_as_one_and_logged_at_warning() -> None:
    first = _record(qty=Decimal(1), closed_pnl=Decimal("-15"))
    later = _record(qty=Decimal(2), closed_pnl=Decimal("-32.4"), closed_at=first.closed_at + 9)
    r = rig(records=[first, later])
    with capture_logs() as logs:
        r.sync.start([ACCOUNT_A])
        await asyncio.sleep(1)
    [row] = r.store.rows.values()
    assert (row.qty, row.closed_pnl, row.closed_at) == (
        Decimal(3),
        Decimal("-47.4"),
        _at(later.closed_at),
    )
    [line] = [e for e in logs if e["event"] == "closed_pnl_records_merged"]
    assert (line["log_level"], line["records"], line["exchange_order_id"]) == ("warning", 2, XID)
    await r.sync.stop()


@virtual
async def test_stop_ends_the_task_and_a_later_request_reads_nothing() -> None:
    r = rig()
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)
    await r.sync.stop()
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(100)
    assert r.times() == [0] and r.sync.fault is None and not r.sync.start([ACCOUNT_A])


@pytest.mark.parametrize("end", ["raises", "returns", "cancelled"])
@virtual
async def test_a_task_that_ends_unasked_is_logged_and_told_once(
    end: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any end other than by `stop()`, an error or a return its loop never makes, or a cancel no
    stop made (as the order lane's death makes one), is a fault, logged at ERROR by its kind and
    told to `on_ended` once (the runtime's page); a second start and the later stop add none."""

    async def ended(self: ClosedPnlSync) -> None:
        if end == "raises":
            raise RuntimeError("the sync's task")
        if end == "cancelled":
            await asyncio.Event().wait()

    monkeypatch.setattr(ClosedPnlSync, "_run", ended)
    r = rig()
    with capture_logs() as logs:
        assert r.sync.start([ACCOUNT_A])
        await asyncio.sleep(1)
        if end == "cancelled":
            task = r.sync._task
            assert task is not None and (r.sync.fault, r.told) == (None, [])
            task.cancel()  # not through its stop
            await asyncio.sleep(1)
        assert r.sync.fault is not None and r.told == ["ended"]
        assert not r.sync.start([ACCOUNT_A])
        await r.sync.stop()
    kind = {"raises": "RuntimeError", "returns": "returned", "cancelled": "CancelledError"}[end]
    kinds = [(e["kind"], e["log_level"]) for e in logs if e["event"] == "closed_pnl_sync_ended"]
    assert (kinds, r.told) == ([(kind, "error")], ["ended"])


@pytest.mark.parametrize("on_cancel", ["ends", "raises"])
@virtual
async def test_a_stop_it_was_asked_for_is_told_to_no_one(
    on_cancel: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A requested `stop()` never pages: its cancel ends the task, and a task that raises as it
    ends is logged, never told."""

    async def run(self: ClosedPnlSync) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if on_cancel == "raises":
                raise RuntimeError("its cancel") from None
            raise

    monkeypatch.setattr(ClosedPnlSync, "_run", run)
    r = rig()
    with capture_logs() as logs:
        r.sync.start([ACCOUNT_A])
        await asyncio.sleep(1)
        await r.sync.stop()
        await asyncio.sleep(0)  # the task's callbacks have run
    ended = [e["kind"] for e in logs if e["event"] == "closed_pnl_sync_ended"]
    assert (r.told, ended) == ([], ["RuntimeError"] if on_cancel == "raises" else [])
    assert r.sync.fault is None


@virtual
async def test_a_resolve_naming_another_account_fails_the_read_before_any_venue_call() -> None:
    r = rig(resolve=ACCOUNT_B, records=[_record()], readings=[_reading()])
    assert not await r.sync.read(ACCOUNT_A)
    assert (r.venue.lanes, r.venue.reads, r.venue.position_reads) == ([], [], 0)
    assert r.store.rows == {} and r.store.snapshots == []
    assert (r.counted(), r.crossed()) == ({"ok": 0, "failed": 0}, 1)  # a crossing, apart


@virtual
async def test_a_record_naming_another_account_fails_the_read_and_keeps_nothing() -> None:
    r = rig(records=[_record()], readings=[_reading()], records_of=ACCOUNT_B)
    assert not await r.sync.read(ACCOUNT_A)
    assert r.store.rows == {} and r.store.snapshots == [] and r.venue.position_reads == 0
    assert (r.counted(), r.crossed()) == ({"ok": 0, "failed": 0}, 1)


@virtual
async def test_another_accounts_record_after_the_accounts_own_fails_the_whole_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rig(readings=[_reading()])
    theirs = _record(exchange_order_id="b-order").model_copy(update={"account_id": ACCOUNT_B})

    async def closed_pnl(account: AccountRef, start: int, end: int) -> list[ClosedPnl]:
        return [_record(), theirs]  # the asked account's own record first

    monkeypatch.setattr(r.venue, "closed_pnl", closed_pnl)
    assert not await r.sync.read(ACCOUNT_A)
    assert r.store.rows == {} and r.venue.position_reads == 0
    assert (r.counted(), r.crossed()) == ({"ok": 0, "failed": 0}, 1)


# --- the seed (the orchestrator's ruling, 2026-11-04 15:51Z) --------------------------------------


@virtual
async def test_the_seed_stores_a_flat_only_from_a_venue_size_0_reading() -> None:
    """A size 0 the venue states is stored, dated by its `updatedTime`; a non-zero first reading
    (the transcribed row with `size` changed), a missing one (SOLUSDT) and one dated past the skew
    store none."""
    ahead = _reading(symbol="XRPUSDT").model_copy(update={"updated_at": _us(T0) + 6_000_000})
    readings = [_reading(symbol="ETHUSDT", size="0.4"), _reading(), ahead]  # each skip goes on
    r = rig(readings=readings)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)
    [seed] = r.store.snapshots
    assert (seed.symbol, seed.position_idx, seed.size, seed.reason) == (
        "BTCUSDT", 2, Decimal(0), "rest_reconcile",
    )  # fmt: skip
    assert seed.exchange_updated_ts == _at(1_697_682_317_038_000)  # the reading's updatedTime
    await r.sync.stop()


@virtual
async def test_a_key_holding_a_confirmed_flat_gets_no_second_seed_and_an_account_one_read() -> None:
    """A non-zero ETH, BTC holding its flat, then a fresh size 0 SOL: SOL alone is seeded."""
    readings = [_reading(symbol="ETHUSDT", size="0.4"), _reading(), _reading(symbol="SOLUSDT")]
    r = rig(readings=readings)
    r.store.flats[("BTCUSDT", 2)] = (T0 - timedelta(days=1),)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(1)
    assert [s.symbol for s in r.store.snapshots] == ["SOLUSDT"] and r.venue.position_reads == 1
    await r.sync.stop()


@virtual
async def test_a_seed_that_fails_is_tried_again_and_the_records_are_kept_meanwhile() -> None:
    r = rig(records=[_record()], readings=[_reading()], seed_failures=[ConnectionError()])
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)
    assert r.store.rows and r.store.snapshots == [] and r.counted()["ok"] == 1
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(1)
    assert [s.symbol for s in r.store.snapshots] == ["BTCUSDT"] and r.venue.position_reads == 2
    await r.sync.stop()


@virtual
async def test_a_flat_the_venue_states_during_a_slow_positions_read_is_seeded() -> None:
    """The skew runs from the clock read after the positions read: 12 s into a 10 s one is within
    its 5 s, past the clock itself."""
    r = rig(readings=[_reading().model_copy(update={"updated_at": _us(T0) + 12_000_000})], pause=10)
    assert await r.sync.read(ACCOUNT_A)
    assert [s.exchange_updated_ts for s in r.store.snapshots] == [T0 + timedelta(seconds=12)]


@virtual
async def test_a_slow_seed_delays_none_of_the_records_writes() -> None:
    r = rig(records=[_record()], readings=[_reading()], pause=10)
    r.store.orders[XID], r.store.closes[ORDER] = (ORDER, "filled"), Decimal(3)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)  # the seed's positions read takes 10 s
    assert r.store.rows[record_id(ACCOUNT_A, XID)].final_at is not None and not r.store.snapshots
    await asyncio.sleep(10)
    assert [s.symbol for s in r.store.snapshots] == ["BTCUSDT"]
    await r.sync.stop()


@virtual
async def test_a_seed_reading_of_another_account_fails_the_seed_and_the_records_settle() -> None:
    """As a record fails the read, and the seed is tried again at the next read."""
    r = rig(records=[_record()], readings=[_reading()], readings_of=ACCOUNT_B)
    with capture_logs() as logs:
        assert await r.sync.read(ACCOUNT_A) and await r.sync.read(ACCOUNT_A)
    assert r.store.snapshots == [] and r.venue.position_reads == 2
    assert set(r.store.rows) == {record_id(ACCOUNT_A, XID)}
    failed = [e["kind"] for e in logs if e["event"] == "closed_pnl_flat_seed_failed"]
    assert failed == ["_OtherAccount"] * 2  # and counted as crossings, never a WARNING alone
    assert (r.counted(), r.crossed()) == ({"ok": 2, "failed": 0}, 2)


@virtual
async def test_another_accounts_reading_after_the_accounts_own_fails_the_whole_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r, walks = rig(records=[_record()]), list[str]()
    theirs = _reading(symbol="ETHUSDT").model_copy(update={"account_id": ACCOUNT_B})
    walk = r.store.walk_flats

    async def positions(account: AccountRef) -> list[Position]:
        return [_reading(), theirs]  # the asked account's own reading first

    async def walk_flats(account_id: UUID, symbol: str, *rest: Any) -> tuple[datetime, ...]:
        walks.append(symbol)
        return await walk(account_id, symbol, *rest)

    monkeypatch.setattr(r.venue, "positions", positions)
    monkeypatch.setattr(r.store, "walk_flats", walk_flats)
    with capture_logs() as logs:
        assert await r.sync.read(ACCOUNT_A)
    assert (r.store.snapshots, walks) == ([], [])
    assert set(r.store.rows) == {record_id(ACCOUNT_A, XID)}
    failed = [e["kind"] for e in logs if e["event"] == "closed_pnl_flat_seed_failed"]
    assert failed == ["_OtherAccount"]
    assert (r.counted(), r.crossed()) == ({"ok": 1, "failed": 0}, 1)


# --- the merge (24 Sec.8.13: several records under one orderId) ---------------------------------


def test_the_merge_sums_weighs_by_size_and_takes_the_latest_and_the_earliest() -> None:
    a = _record(
        qty=Decimal(1), avg_entry_price=Decimal(100), avg_exit_price=Decimal(110),
        closed_pnl=Decimal("9.5"), open_fee=Decimal("0.06"), close_fee=Decimal("0.066"),
        leverage=Decimal(5),
    )  # fmt: skip
    b = _record(
        qty=Decimal(2), avg_entry_price=Decimal(103), avg_exit_price=Decimal(104),
        closed_pnl=Decimal("1.4"), open_fee=Decimal("0.12"), close_fee=None, leverage=Decimal(3),
        created_at=a.created_at + 7, closed_at=a.closed_at + 9,
    )  # fmt: skip
    [one] = merged([a, b])
    assert (one.qty, one.avg_entry_price, one.avg_exit_price) == (
        Decimal(3),
        Decimal(102),
        Decimal(106),
    )
    assert (one.closed_pnl, one.open_fee, one.close_fee) == (Decimal("10.9"), Decimal("0.18"), None)
    assert (one.leverage, one.created_at, one.closed_at) == (Decimal(3), a.created_at, b.closed_at)
    orderless = _record(exchange_order_id=None)
    assert merged([orderless, orderless]) == [orderless, orderless]  # each its own record


_SIZE = st.decimals(min_value=Decimal("0.001"), max_value=Decimal(10**6), places=8)
_MONEY = st.decimals(min_value=-(10**9), max_value=10**9, places=8)


@st.composite
def _records(draw: st.DrawFn) -> list[ClosedPnl]:
    def one() -> ClosedPnl:
        return _record(
            exchange_order_id=draw(st.sampled_from([None, "o-1", "o-2"])), qty=draw(_SIZE),
            avg_entry_price=draw(_SIZE), avg_exit_price=draw(_SIZE), closed_pnl=draw(_MONEY),
            open_fee=draw(st.none() | _MONEY), close_fee=draw(st.none() | _MONEY),
            leverage=draw(st.sampled_from([Decimal(1), Decimal(5), Decimal("12.5")])),
            created_at=draw(st.integers(0, 10**6)), closed_at=draw(st.integers(10**6, 2 * 10**6)),
        )  # fmt: skip

    return [one() for _ in range(draw(st.integers(1, 8)))]


@settings(max_examples=200, deadline=None, derandomize=True)
@given(records=_records(), data=st.data())
def test_property_the_merge_is_order_independent_and_idempotent(
    records: list[ClosedPnl], data: st.DataObject
) -> None:
    once = Counter(merged(records))
    assert Counter(merged(data.draw(st.permutations(records)))) == once
    assert Counter(merged(list(once.elements()))) == once
    assert sum(r.qty for r in once.elements()) == sum(r.qty for r in records)


@pytest.mark.parametrize("closed_size", [None, Decimal(0)])
def test_a_fill_the_store_took_before_the_start_asks_for_nothing(
    closed_size: Decimal | None,
) -> None:
    """Startup's reads cover what came before: a trigger before `start` is a no-op."""
    store = Store()
    sync = ClosedPnlSync(
        accounts=Accounts(), router=Venue(), records=store, closes=store, snapshots=store,
        metrics=Metrics("demo"), now=lambda: T0, on_ended=lambda: None,
        day_start=DayBoundary(Policy()).day_start,
    )  # fmt: skip
    sync.stored(_fill(closed_size))
    sync.reconnected(ACCOUNT_A)
    assert sync.fault is None


# --- the composition (slice 5b; the orchestrator's rulings of 2026-11-04, 23:45Z) ----------------

OPENER, GROUP = UUID(int=0x0E), UUID(int=0x0F)


def _composable(r: Rig, *, closed: str | None = "3", pnl: str | None = "-45") -> NewExecution:
    """A long of 3 opened on GROUP's leg after a confirmed flat at 07:00 and closed by the record's
    order at 09:00, no settlement between (480 min apart): the fill `stored` names it by."""
    s = r.store
    s.flats[("ETHUSDT", 0)] = (T0 - timedelta(hours=3),)
    s.orders |= {"x-open": (OPENER, "filled"), XID: (ORDER, "filled")}
    s.keys |= {OPENER: ("ETHUSDT", "Buy", 0), ORDER: ("ETHUSDT", "Sell", 0)}
    for n, (oid, price, fee, size, closed_pnl) in enumerate((
        (OPENER, "1195", "2.151", "0", "0"), (ORDER, "1180", "2.124", closed, pnl),
    )):  # fmt: skip
        s.fills.append(("ETHUSDT", WalkFill(
            exec_id=f"w{n}", exec_ts=T0 - timedelta(minutes=90 - 30 * n), order_id=oid,
            side="Buy" if oid == OPENER else "Sell", exec_type="Trade", exec_qty=Decimal(3),
            exec_price=Decimal(price),
            exec_fee=Decimal(fee), closed_pnl=None if closed_pnl is None else Decimal(closed_pnl),
            closed_size=None if size is None else Decimal(size), order_position_idx=0,
            order_exchange_id=XID if oid == ORDER else "x-open",
            order_group_id=GROUP if oid == OPENER else None,
        )))  # fmt: skip
    return replace(_fill(None if closed is None else Decimal(closed)), order_id=ORDER)


@virtual
async def test_a_named_close_is_composed_before_the_read_so_a_failed_read_hides_nothing() -> None:
    """Q2: a pass composes the orders its stored fills named before it reads the venue; the read
    failing keeps the poll and those orders for the next pass."""
    r = rig(composed=True)
    named = _composable(r)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    r.venue.failures.append(TimeoutError())
    r.sync.stored(named)
    await asyncio.sleep(2)
    item = r.store.rows[record_id(ACCOUNT_A, XID)]
    assert (item.settled_at, item.qty, item.trade_group_id) == (None, Decimal(3), GROUP)
    assert (item.gross_pnl, item.fee_pnl, item.funding_pnl) == (
        Decimal(-45), Decimal("-4.275"), Decimal(0),
    )  # fmt: skip
    assert r.counted() == {"ok": 1, "failed": 1} and r.sync._state[ACCOUNT_A].named == {ORDER}
    await r.sync.stop()


@virtual
async def test_the_read_settles_a_provisional_close_in_place_and_the_walk_finalizes_it() -> None:
    """A REST-recovered close (no closedSize, no closed PnL) is provisional with no local figure,
    from the pass its fill asks for, until its record is read, which settles it in place; the
    walk's `c` then completes the final rule (Q4), which the stated sizes never would (row 60)."""
    r = rig(composed=True)
    named = _composable(r, closed=None, pnl=None)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    r.sync.stored(named)
    await asyncio.sleep(61)  # a fill stating no closedSize asks for a read SETTLE_POLL_S later
    rid = record_id(ACCOUNT_A, XID)
    first = r.store.rows[rid]
    assert (first.settled_at, first.qty, first.gross_pnl, first.trade_group_id) == (
        None, Decimal(3), None, GROUP,
    )  # fmt: skip
    r.venue.records = [_record()]
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(1)
    settled = r.store.rows[rid]
    assert (settled.closed_pnl, settled.trade_group_id) == (_record().closed_pnl, GROUP)
    assert settled.settled_at is not None and settled.final_at is not None
    await r.sync.stop()


@virtual
async def test_a_failed_composition_is_logged_by_kind_and_keeps_its_orders_and_the_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = rig(composed=True)
    named, real = _composable(r), r.store.anchors
    failures = [StoreUnavailable(), StoreUnavailable()]

    async def anchors(*args: Any) -> tuple[OrderAnchor, ...]:
        if failures:
            raise failures.pop()
        return await real(*args)

    monkeypatch.setattr(r.store, "anchors", anchors)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    with capture_logs() as logs:
        r.sync.stored(named)
        await asyncio.sleep(2)
    assert [e for e in logs if e["event"] == "closed_pnl_compose_failed"] == [
        {"event": "closed_pnl_compose_failed", "log_level": "warning",
         "account_id": str(ACCOUNT_A), "kind": "StoreUnavailable"},
    ] * 2  # fmt: skip
    assert r.counted()["ok"] == 2 and not r.store.rows  # the read went on
    await asyncio.sleep(60)
    assert record_id(ACCOUNT_A, XID) in r.store.rows  # the next pass composed it
    await r.sync.stop()


@virtual
async def test_the_first_composition_takes_every_record_read_and_later_ones_what_changed() -> None:
    """Q3: an account's first composition takes each record its read covers, as after a restart;
    later ones take the records the read changed, the poll's and the named orders'."""
    r = rig(composed=True, records=[_record()])
    _composable(r)
    await r.store.settle(venue_record(_record()))
    rid = record_id(ACCOUNT_A, XID)
    r.store.rows[rid] = replace(r.store.rows[rid], final_at=T0)  # final before a restart
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(1)
    assert r.store.calls["anchors"] == 1 and r.store.rows[rid].gross_pnl == -45
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(1)
    assert r.store.calls["anchors"] == 1  # unchanged, final and named by no fill
    await r.sync.stop()


@virtual
async def test_an_accounts_named_orders_are_bounded_and_none_without_a_composer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_mod, "NAMED_LIMIT", 1)
    r, bare = rig(composed=True), rig()
    r.sync.start([])
    bare.sync.start([])
    with capture_logs() as logs:
        for oid in (ORDER, OPENER, ORDER):
            r.sync.stored(replace(_fill(Decimal(1)), order_id=oid))
            bare.sync.stored(replace(_fill(Decimal(1)), order_id=oid))
    assert (r.sync._state[ACCOUNT_A].named, bare.sync._state[ACCOUNT_A].named) == ({ORDER}, set())
    assert logs == [{"event": "closed_pnl_named_order_dropped", "log_level": "warning",
                     "account_id": str(ACCOUNT_A)}]  # fmt: skip
    await r.sync.stop()
    await bare.sync.stop()
