"""E29-Q04's in-process world (#1148): the composed `OmsRuntime` of `test_oms_runtime.World`,
extended, not copied, on a `VirtualTimeLoop` (`audit_waits.virtual`, as s1 to s4 run): every
bound, the reconciliation job's 30 s cadence among them, runs on fake seconds (C-13.7). Over the
world's in-memory order store it adds:

* the venue (`_venue`): the demo `FakeTradingPort` the lane's port is, on the world's wall clock,
  one per world, held before the runtime starts (`Exchange`), so a process that went down before
  it can leave the venue a create (`opened(before=)`);
* an in-memory position store (the world's own refuses every write) and an in-memory
  `ReconcileReads` and hand-over store (`Handovers`, which reads back what it was given), so the
  runtime composes reconciliation in place of its stand-ins; `World(handover_store=None,
  reconcile_reads=None)` composes the shipped stand-ins;
* the account's private stream on `FakeTradingPort.subscribe_private` (`streamed`);
* the storage tier's outage switch (`Outage.down`) and the named fault doors (`door`): `send`
  (the SEND step's commit), `place` (the venue's create), `ack` (the commit of the create's answer)
  and `commit` (the next commit), each faulted through the store's own `fail_next` or the fake's
  own `script`, so a failure is reproduced from its scenario's name alone (#1148's design note);
* the lane's audit writer, whose write-ahead log can fill (`Wal`);
* a watch on the account's passes (`passes`), observed and never changed.

The scenarios drive `place`, `commit` and the outage switch through the real runtime (the
scenarios and `test_harness_guards.py`).

The submit is the pipeline's (`runtime.submission`), as `placeOrder` reaches it. Demo only, no
socket (`test_harness_guards.py`). Nothing asserts on the stream consumer's host time (a row's
lag, its `ts_ingest`): the runtime binds the consumer to the host's clock."""

from __future__ import annotations

import asyncio
import functools
import inspect
import itertools
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Collection,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Final, Literal, NoReturn
from uuid import UUID

from candleviewer.audit.writer import AuditUnavailable
from candleviewer.domain.primitives import TsUs
from candleviewer.exchange.base.models import FeeRate, RiskLimitTier, Wallet
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.oms.fakes import InMemoryOrderStore, InMemorySubmissionStore
from candleviewer.oms.submit import SubmitOutcome
from candleviewer.oms_reconcile_wiring import RECONCILE
from candleviewer.oms_wiring import OmsRuntime, OmsStores
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.oms_handovers import (
    AppendOutcome,
    HandoverKind,
    HandoverRow,
    NewHandover,
)
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.positions import PositionRow
from candleviewer.storage.repositories.recorded_stops import LIVE_STOP_STATUSES, RecordedStopRow
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.chaos.oms._oracle import Book, Truth
from tests.chaos.oms._venue import Venue, VenuePort
from tests.unit.audit.audit_waits import VirtualTimeLoop
from tests.unit.oms import command_rig as cr
from tests.unit.oms import stream_world
from tests.unit.oms import test_oms_runtime as rt
from tests.unit.oms.submit_rig import Groups, context, entry, instrument

ACCOUNT, SYMBOL, REF = cr.ACCOUNT, cr.SYMBOL, cr.ref()
PRICE: Final = Decimal(60000)
#: The series the scenarios read (20 Sec.12.1).
UNKNOWN, CORRECTIONS = "oms_unknown_orders", "oms_reconcile_corrections_total"
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_US: Final = timedelta(microseconds=1)
_END_US: Final = 2**62  # the executions read's end: after every fill the venue stamped
#: The fault doors (module docstring); `send` and `ack` name the B1 state their step writes.
type Door = Literal["send", "place", "ack", "commit"]
_STEPS: Final = {"send": "submitting", "ack": "submitted"}
#: Every write and read of the store a `SqlAlchemy*` adapter would send to Postgres.
_TIERS: Final = ("orders", "executions", "submissions", "anchors", "stops", "groups", "sweep")


def wall() -> datetime:
    """The venue's and the OMS's wall clock: the world's T0 plus the loop's fake seconds."""
    return rt.T0 + timedelta(seconds=asyncio.get_running_loop().time())


def wall_us() -> TsUs:
    return (wall() - _EPOCH) // _US


class Positions(stream_world.Book):
    """`positions` and `position_snapshots` in memory (`stream_world.Book`: a later exchange
    time wins), with the runtime's two reads: the account's open rows, and those with no stop."""

    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]:
        rows = (r for r in self.rows.values() if r.exchange_account_id == account_id)
        return tuple(sorted((r for r in rows if r.size > 0), key=lambda r: r.symbol))

    async def list_unprotected(self, account_id: UUID) -> tuple[PositionRow, ...]:
        return tuple(r for r in await self.list_open(account_id) if r.stop_loss is None)


@dataclass
class PassReads:
    """`ReconcileReads` over the in-memory store, as `SqlAlchemyReconcileStore`'s statements read
    Postgres: the account's unfinished orders and live recorded stops, oldest first, its stored
    `exec_id`s, and its watermark, which only ever moves forward."""

    store: InMemoryOrderStore
    marks: dict[UUID, datetime] = field(default_factory=dict)

    async def unfinished_for(self, account_id: UUID) -> tuple[OrderRow, ...]:
        rows = await self.store.list_unfinished("demo", limit=10_000)
        return tuple(r for r in rows if r.exchange_account_id == account_id)

    async def stored(self, account_id: UUID, exec_ids: Collection[str]) -> frozenset[str]:
        rows = [await self.store.executions.get(account_id, e) for e in set(exec_ids)]
        return frozenset(r.exec_id for r in rows if r is not None)

    async def live_for_account(self, account_id: UUID) -> tuple[RecordedStopRow, ...]:
        mine = (r for r in self.store._stops.values() if r.exchange_account_id == account_id)
        live = (r for r in mine if r.status in LIVE_STOP_STATUSES)
        return tuple(sorted(live, key=lambda r: (r.created_at, r.id)))

    async def last_reconciled(self, account_id: UUID) -> datetime | None:
        return self.marks.get(account_id)

    async def advance(self, account_id: UUID, to: datetime) -> bool:
        self.marks[account_id] = max(self.marks.get(account_id, to), to)
        return True


@dataclass
class Handovers:
    """`oms_handovers` in memory, as `SqlAlchemyHandoverStore` keeps it (21 Sec.3.3.12): one entry
    per account and order id, or per account and `exec_id`, an empty read counted on the entry
    held (the first stamped once), read back in append order, decided once, pruned by id. It keeps
    no bound: the real store's 1,000 entries an account (`HandoverStoreFull` past them) are not
    modelled."""

    clock: Callable[[], datetime] = wall
    rows: dict[int, HandoverRow] = field(default_factory=dict)
    ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    async def append(self, entry: NewHandover) -> AppendOutcome:
        key = (entry.exchange_account_id, entry.kind, entry.exec_id or entry.exchange_order_id)
        held = [r for r in self.rows.values() if _key(r) == key]
        now = self.clock()
        if held and entry.empty_read:
            [row] = held
            first = row.first_empty_read_at or now
            self.rows[row.id] = replace(
                row, empty_reads=row.empty_reads + 1, first_empty_read_at=first
            )
            return "counted"
        if held:
            return "held"
        n = next(self.ids)
        self.rows[n] = HandoverRow(
            id=n, exchange_account_id=entry.exchange_account_id, kind=entry.kind,
            exchange_order_id=entry.exchange_order_id, exec_id=entry.exec_id, source=entry.source,
            record=entry.record, payload=entry.payload, empty_reads=int(entry.empty_read),
            first_empty_read_at=now if entry.empty_read else None, decided_at=None, created_at=now,
        )  # fmt: skip
        return "added"

    async def pending(self, account_id: UUID, kind: HandoverKind) -> tuple[HandoverRow, ...]:
        return tuple(
            r for r in self.rows.values() if (r.exchange_account_id, r.kind) == (account_id, kind)
        )

    async def decide(self, account_id: UUID, exec_id: str) -> bool:
        held = [r for r in self.rows.values() if _key(r) == (account_id, "execution", exec_id)]
        if not held or held[0].decided_at is not None:
            return False
        self.rows[held[0].id] = replace(held[0], decided_at=self.clock())
        return True

    async def prune(self, account_id: UUID, ids: Collection[int]) -> int:
        gone = [
            n for n in set(ids) if n in self.rows and self.rows[n].exchange_account_id == account_id
        ]
        for n in gone:
            del self.rows[n]
        return len(gone)


def _key(row: HandoverRow) -> tuple[UUID, str, str]:
    return row.exchange_account_id, row.kind, row.exec_id or row.exchange_order_id


@dataclass
class Wal(rt.Writer):
    """The lane's audit writer over its write-ahead log (`audit.writer.AuditWriter`), the runtime's
    alarm (`alarm`) its fail-closed one: once `full` (Postgres down long enough to fill the log),
    every append is refused `AuditUnavailable` and the alarm fired, in the writer's own words, as
    `test_writer_wal_full_with_postgres_down_refuses_never_drops` pins the writer; with `refuses`
    off, a full log drops what it is given instead (fail open, s13's negative control)."""

    full: bool = False
    refuses: bool = True
    alarm: Callable[[str], Awaitable[None]] | None = None

    async def emit(self, action: str, **fields: Any) -> None:
        if not self.full:
            await super().emit(action, **fields)
        elif self.refuses:
            await self._refused()

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None:
        if not self.full:
            await super().emit_keyed(action, name, **fields)
        elif self.refuses:
            await self._refused()

    async def _refused(self) -> NoReturn:
        cause = "audit WAL unavailable: AuditWalFull"
        if self.alarm is not None:
            await self.alarm(cause)
        raise AuditUnavailable(cause)


@dataclass(frozen=True, slots=True)
class Pass:
    """One pass a watch saw open (`World.passes`): its trigger, and when, on the loop's clock."""

    trigger: str
    at: float


@dataclass
class Passes:
    """The account's passes from the watch on: each one opened, how many have closed, and the most
    ever open at once."""

    runs: list[Pass] = field(default_factory=list)
    ended: int = 0
    peak: int = 0

    def of(self, trigger: str) -> list[Pass]:
        return [run for run in self.runs if run.trigger == trigger]


@dataclass
class Outage:
    """The storage tier (C-13.6 #10): while `down`, every store call is refused
    `StorageTierUnavailable` before it reaches a table, as a refused connection is; an armed door
    faults the one step that writes its B1 state, through the store's own `fail_next`."""

    store: InMemoryOrderStore
    down: bool = False
    doors: dict[str, tuple[BaseException, bool]] = field(default_factory=dict)

    def wrap(self, target: object) -> Any:
        return _Switched(target, self)

    def entered(self, name: str, args: Sequence[Any]) -> None:
        if self.down:
            raise StorageTierUnavailable("the storage tier is down")
        step = args[0] if name == "transition" and args else None
        armed = None if step is None else self.doors.pop(step.lifecycle_state, None)
        if armed is not None:
            self.store.fail_next(armed[0], committed=armed[1])


class _Switched:
    """A store as the runtime meets it through `Outage`: each coroutine method switched."""

    def __init__(self, target: object, outage: Outage) -> None:
        self._target, self._outage = target, outage

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._target, name)
        if not inspect.iscoroutinefunction(value):
            return value

        async def switched(*args: Any, **kwargs: Any) -> Any:
            self._outage.entered(name, args)
            return await value(*args, **kwargs)

        return switched


@dataclass
class Exchange(rt.Venue):
    """The adapter's service whose lane port is the chaos venue's (`VenuePort`): one per world, held
    from the start, with the adapter's rate governor when one is given (`_venue`)."""

    governor: TokenBucketGovernor | None = None
    held: VenuePort = field(init=False)

    def __post_init__(self) -> None:
        self.held = VenuePort(now_us=wall_us, governor=self.governor)

    def port(self, env: str) -> VenuePort:
        assert env == "demo", "the chaos suite runs on demo only (C-13.5)"
        return self.held


@dataclass
class World(rt.World):
    """The runtime's world (`test_oms_runtime.World`) with the chaos parts (module docstring)."""

    venue: rt.Venue = field(default_factory=Exchange)
    store: InMemoryOrderStore = field(default_factory=lambda: InMemoryOrderStore(wall))
    handover_store: Any = field(default_factory=Handovers)
    reconcile_reads: Any = None
    streamed: bool = False
    positions: Positions = field(default_factory=Positions)
    #: Whether the oracle checked this world (the suite's autouse fixture asks, `conftest.py`).
    checked: bool = False
    #: The client keys of its submits, in order: a count, not `uuid4`, so a run repeats them
    #: (C-13.7). The pipeline draws its own group, order and anchor ids: link ids still differ.
    refs: Iterator[int] = field(default_factory=lambda: itertools.count(1), init=False, repr=False)
    oms: OmsRuntime = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.outage = Outage(self.store)
        if self.reconcile_reads is None and self.handover_store is not None:
            self.reconcile_reads = PassReads(self.store)
        BUILT.append(self)

    def stores(self) -> OmsStores:
        wrap, store = self.outage.wrap, self.store
        tiers = (store, store.executions, store.submissions, store.anchors, store.stops,
                 Groups(store), store)  # fmt: skip
        switched = dict(zip(_TIERS, map(wrap, tiers), strict=True))
        handovers, reads = self.handover_store, self.reconcile_reads
        return replace(
            super().stores(), **switched, positions=lambda _clock: wrap(self.positions),
            handovers=None if handovers is None else wrap(handovers),
            reconcile=None if reads is None else wrap(reads),
        )  # fmt: skip

    @property
    def port(self) -> VenuePort:
        assert isinstance(self.venue, Exchange)
        return self.venue.held

    @functools.cached_property
    def exchange(self) -> Venue:
        """The venue engine over the lane's port (`_venue.Venue`), one per world."""
        return Venue(self.port, REF, wall_us)

    def door(self, name: Door, fault: BaseException, *, committed: bool = False) -> None:
        """Arm a door (module docstring); `place` is the venue's (`Venue.lose_ack`, `time_out`)."""
        if name == "commit":
            self.store.fail_next(fault, committed=committed)
        elif name == "place":
            self.port.script("place_order", fault)
        else:
            self.outage.doors[_STEPS[name]] = (fault, committed)

    # --- Driving it -------------------------------------------------------------------------

    async def submit(self, *, key: int | None = None, **over: Any) -> SubmitOutcome:
        """`placeOrder`'s pipeline: a limit buy entry, its stop and take-profit attached, under a
        key of its own (`submit_rig.entry`), the world's next, or `key` (a retry's)."""
        ref = UUID(int=next(self.refs) if key is None else key)
        outcome: SubmitOutcome = await self.oms.submission.submit(
            entry(**over), context(client_ref=ref)
        )
        return outcome

    async def settle(self) -> None:
        """Until the lane's work in hand is done and the account's reconciliation job rests (B19's
        rest states): the next point where nothing is ready, so no fake second passes while the
        job is already at rest."""
        loop = asyncio.get_running_loop()
        assert isinstance(loop, VirtualTimeLoop)
        for _ in range(1_000):  # a bound on the test, never a time
            await asyncio.sleep(0)
            await loop.idle()
            if (job := self.job()) is None or job in b19.REST_STATES:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the reconciliation job never came to rest")

    async def elapse(self, seconds: float) -> None:
        assert isinstance(asyncio.get_running_loop(), VirtualTimeLoop)  # fake seconds, never real
        await asyncio.sleep(seconds)
        await self.settle()

    async def until(self, done: Callable[[], Awaitable[bool]], within_s: float) -> float:
        """The fake seconds until `done()`, read once a second, at most `within_s`."""
        loop, began = asyncio.get_running_loop(), asyncio.get_running_loop().time()
        while not await done():
            if loop.time() - began >= within_s:
                raise AssertionError(f"not within {within_s} s")
            await self.elapse(1)
        return loop.time() - began

    # --- Reading it -------------------------------------------------------------------------

    def job(self) -> str | None:
        reconcile = self.oms._composed().reconcile
        return None if reconcile is None else reconcile.jobs.state(ACCOUNT)

    async def row(self, order_id: UUID) -> OrderRow:
        row = await self.store.get(ACCOUNT, order_id)
        assert row is not None
        return row

    def sample(self, name: str, **labels: str) -> float:
        """A series' value as a scrape reads it, summed over any label not named."""
        found = (
            s.value for m in self.metrics.registry.collect() for s in m.samples
            if s.name == name and labels.items() <= s.labels.items()
        )  # fmt: skip
        return sum(found, 0.0)

    def raised(self, severity: str) -> list[str]:
        """What the pager took at `severity` (a `page`, an `alert`), in order."""
        took = zip(self.pager.severities, self.pager.calls, strict=True)
        return [summary for at, summary in took if at == severity]

    def reports(self) -> list[dict[str, Any]]:
        """Each pass's `oms.reconcile` record as the lane's writer took it (its `after_state`)."""
        records = self.writer.records
        return [fields["after_state"] for action, fields in records if action == RECONCILE]

    def passes(self) -> Passes:
        """A watch on the account's passes from now on: around B19's two services that open and
        close each one (`ReconcilePhases.fetch` and `report`), each delegated as it is; none over
        the stand-ins, which compose no pass."""
        seen, reconcile = Passes(), self.oms._composed().reconcile
        if reconcile is None:
            return seen
        assert self.job() in b19.REST_STATES  # none open now: one would go uncounted
        phases = reconcile.phases
        fetch, report = phases.fetch, phases.report

        async def fetched(account_id: str, *, pass_id: str, trigger: str) -> Mapping[str, Any]:
            seen.runs.append(Pass(trigger, asyncio.get_running_loop().time()))
            seen.peak = max(seen.peak, len(seen.runs) - seen.ended)
            try:
                return await fetch(account_id, pass_id=pass_id, trigger=trigger)
            except BaseException:  # a failed fetch closes its run: a retry opens one of its own
                seen.ended += 1
                raise

        async def reported(account_id: str, **kwargs: Any) -> Mapping[str, Any]:
            try:
                return await report(account_id, **kwargs)
            finally:
                seen.ended += 1

        vars(phases).update(fetch=fetched, report=reported)
        return seen

    def paged(self, alert: str) -> bool:
        """Whether the pager took a `page` for the order alert `alert`, worded as the notice route
        words it (`OrderNoticesRouter`): among any others it took, so a scenario names its own."""
        raised = zip(self.pager.severities, self.pager.calls, strict=True)
        return ("page", f"order alert {alert}") in raised

    async def book(self) -> Book:
        """The account's `orders`, `executions` and open `positions` rows, as the tables hold
        them (the in-memory store keeps no account-wide read of its own)."""
        orders = sorted(
            (r for r in self.store._orders.values() if r.exchange_account_id == ACCOUNT),
            key=lambda r: (r.created_ts, r.id),
        )
        fills = (r for (account, _), r in self.store._fills.items() if account == ACCOUNT)
        return Book(tuple(orders), tuple(fills), await self.positions.list_open(ACCOUNT))

    async def truth(self) -> Truth:
        """What the venue holds for the account, through its own reads, and its create log."""
        port = self.port
        orders = (*await port.open_orders(REF), *await port.order_history(REF))
        fills, positions = await port.executions(REF, 0, _END_US), await port.positions(REF)
        return Truth(orders, tuple(fills), tuple(positions), self.exchange.creates())


#: Every world built in the running test; the suite's autouse fixture empties it per test. The
#: suite's one module-level list, and safe: a process runs one test at a time (an xdist worker is a
#: process of its own), the fixture empties it before and after each, and only `unchecked` reads it
#: (the fixture, and its guard test), so no world outlives its test here.
BUILT: list[World] = []


def unchecked() -> list[World]:
    """The worlds of the running test the oracle has not checked (`conftest.py`)."""
    return [world for world in BUILT if not world.checked]


@asynccontextmanager
async def opened(
    before: Callable[[World], Awaitable[None]] | None = None, **over: Any
) -> AsyncIterator[World]:
    """A demo world whose runtime is ready, the account's startup pass at rest: the account
    seeded with its key, its instrument, quote, wallet and fee rate; `before`, a process that ran
    before this one over the same store and venue; the runtime started as
    `test_oms_runtime.started` starts it, and stopped at the end."""
    world = World(**over)
    InMemorySubmissionStore(world.store).seed_account(REF)
    world.accounts.append(TradingAccountRow(ACCOUNT, "demo", REF.uid, False, rt.KEY))
    if world.streamed:
        world.tracked.accounts = frozenset({ACCOUNT})
    tiers = (RiskLimitTier(
        tier_id=1, risk_limit_value=Decimal(2_000_000), maintenance_margin_rate=Decimal("0.005"),
        initial_margin_rate=Decimal("0.01"), max_leverage=Decimal(100),
    ),)  # fmt: skip
    listed = {SYMBOL: instrument()}
    world.ingestion.instruments = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(get=listed.get, risk_limit_tiers=lambda _s: tiers)
    )
    quote = SimpleNamespace(bid1_price=PRICE, ask1_price=PRICE, last_price=PRICE)
    world.ingestion.tickers = SimpleNamespace(
        latest=lambda _s: quote, is_stale=lambda _s: False,
        acquire=lambda _c, _s: None, release=lambda _c, _s: None,
    )  # fmt: skip
    for flag in world.flags:
        flag.read()
    if before is not None:
        await before(world)
    world.oms = world.runtime(now=wall)
    async with rt.started(world.oms):
        await world.oms.wait_ready()
        world.port.set_wallet(Wallet(
            account_id=ACCOUNT, equity=Decimal(100_000), wallet_balance=Decimal(100_000),
            available_to_withdraw=None, available_margin=Decimal(100_000),
            used_margin=Decimal(0), unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0),
            account_im_rate=Decimal(0), account_mm_rate=Decimal(0), updated_at=0,
        ))  # fmt: skip
        taker = Decimal("0.00055")
        fee = FeeRate(symbol=SYMBOL, maker=Decimal("0.0002"), taker=taker, fetched_at=0)
        world.port.set_fee_rate(ACCOUNT, fee)
        await world.settle()
        yield world
