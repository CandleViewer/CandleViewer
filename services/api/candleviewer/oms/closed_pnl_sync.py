"""The venue's closed-PnL records, read and kept (E29-S06 #981 slice 3; 24 Sec.8.13 "The sync").

`ClosedPnlSync` reads each account's records through `TradingPort.closed_pnl` in the `poll` lane,
the governor's background class, never the stop and cancel reserve (C-12.7): it reads the lane's
headroom first and reads nothing without it, as reconciliation's fetch does. A read covers the
reach, `CLOSED_PNL_LOOKBACK` before the day's start up to now, since the venue filters its window
by a time its documents do not name. Several records under one `orderId` are kept as one
(`merged`, logged at WARNING), and each is settled through the closed-PnL store, which replaces the
venue's columns until the record is final and then refuses them: a read after final is logged at
WARNING, never applied, and counted nowhere.

**The composition** (slice 5b, `closed_pnl_compose`, on the orchestrator's rulings of 2026-11-04,
23:45Z). With a `composer`, a pass composes the orders the stored fills named before it reads the
venue, so a close shows as soon as its fill is stored, a failed read or none (Q2), and after the
records settle it composes the delta set (Q3): the records the read inserted, settled or replaced
(every one it read, at the account's first composition), those the poll reads (row 56) and the
named orders. That step takes the named orders first, then the venue ids an earlier step left,
then the records the read changed, then the poll's page less those, so a full page starves no
fresh settle; what it leaves past its bounds, but the page's, is carried to the next pass, at most
`CARRY_LIMIT` an account, and asks for one. Its final rule is the composition's (Q4): settled,
the order's row terminal, and the `c` the walk gives the record's closes, each sure of its count,
summing to its `qty`. Without one, a record is final once its order's row is terminal and its
`qty` is the size the order's stored trade fills state they closed (row 60), a fill that states
none keeping it open. A composition that fails is logged at WARNING by kind and keeps the poll,
the named orders and what it was to carry; the read goes on.

**The comparison** (slice 5c, `closed_pnl_compare`, the rulings Q2, Q3 and Q6): with a `comparer`,
the items the delta set's step composed are compared after it, and the records not settled whose
`closed_at` left the reach since the last pass (row 56 read from where the last pass's reach was,
or `MISSING_SPAN` before the reach at the account's first pass, which a restart repeats) are
recorded as a venue figure missing. What the comparison owes (a record held back or unwritten, a
flag unwritten) is compared again at the next pass: its order composed again, ahead of the records
the read changed, or its missing record written again; it keeps the poll.

**The seed** (the orchestrator's ruling of 2026-11-04 15:51Z, option (a)): at an account's first
read the sync reads the venue's positions, in the same lane, and stores each reading the venue
states at size 0, for a key (account, symbol, `position_idx`) that holds no confirmed flat yet, as
a confirmed flat dated by the reading's `updatedTime` (`exchange_updated_ts`, 21 Sec.3.3.7), so
the key's next position has a walk (24 Sec.8.13 step 3). Only what the venue states: never a
non-zero reading, a missing one or a flat inferred from local fills (Choice 1), and none dated
past the store's skew of the clock read after the positions. A seed that fails, as one reading
another account does (C-2.11), is tried again at the next read; the records are kept all the same.

**Triggers.** Startup (`start`) and a private-stream reconnect (`reconnected`) ask for a read at
once; a stored trade fill (`stored`) asks for one within `SETTLE_POLL_S`, and a closing one (a
stated `closed_size` above 0) within `DEBOUNCE_S`, so the fills of one close in that second are
read once; with a composer, each names its order, at most `NAMED_LIMIT` an account (C-2.18), past
which one is dropped, logged, and composed once its record is read. A read is made again
`SETTLE_POLL_S` after the last one started while that read failed, while the account holds a
record within the reach that is not final and whose order has a row (21 Sec.13.1 row 56), or
while a stored fill waits for a read that starts `SETTLE_POLL_S` after it and succeeds. A record
with no `orderId`, or whose order has no row, keeps no poll. A read the account binding refuses
outright (`_refused`: the account missing, deleted, another environment's or holding no active
key) ends both the failed read's poll and the fills' wait, so the account is not resolved every
`SETTLE_POLL_S` until a restart: its next stored fill or reconnect asks again.

**Placement.** One owned task (`start`, `stop`; `fault` once it ends unasked, which `on_ended` is
told once) on the loop that makes every call, reading the due accounts one at a time: one read is
in flight per account, and a request made meanwhile is folded into the account's next read. The
requests are a queue of at most `MAX_ACCOUNTS` accounts, one coalesced entry each: a request that
would add an account past it is dropped and logged at ERROR, as no process trades that many
(C-2.18). Every external await is bounded and a cancel is never swallowed. Each read is timed in
`oms_closed_pnl_fetch_seconds` by `result` (`FETCH_RESULTS`), and a crossing between accounts, a
read's or a seed's, apart. Logs carry ids and kinds only, never a figure (C-12.6).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, Environment, TsUs
from candleviewer.exchange.base.models import AccountRef, ClosedPnl, Position, RateLane
from candleviewer.observability import spawn
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.storage.repositories.closed_pnl import (
    ClosedPnlRecordRow,
    PendingRecord,
    SettleOutcome,
    VenueRecord,
)
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.oms_reads import CLOSING_EXEC_TYPES, TERMINAL_STATES
from candleviewer.storage.repositories.positions import MAX_FUTURE_SKEW, NewPositionSnapshot

from .closed_pnl_compare import ClosedPnlComparer, Owed
from .closed_pnl_compose import ClosedPnlComposer, Composed, ComposePass
from .errors import AccountScopeDenied, OrderEntryRefused
from .ports import RateReading, TradingAccounts

#: 24 Sec.8.13, both PROPOSED there: the poll's period, and how far before the day's start a read
#: reaches (the venue's widest window).
SETTLE_POLL_S: Final = 60.0
CLOSED_PNL_LOOKBACK: Final = timedelta(days=7)
DEBOUNCE_S: Final = 1.0
#: The lane every read rides: never `critical`, the stop and cancel reserve (C-12.7).
LANE: Final[RateLane] = "poll"
PORT_TIMEOUT_S: Final = 5.0  # an account's resolve, a store call (C-2.18)
READ_TIMEOUT_S: Final = 30.0  # one read, all its pages, as reconciliation's fetch
PENDING_LIMIT: Final = 200  # the records one poll reads (row 56); the rest wait for the next
MAX_ACCOUNTS: Final = 256
NAMED_LIMIT: Final = 256  # the orders an account's stored fills name for the composition
CARRY_LIMIT: Final = 1024  # the venue ids a composition left that an account carries to the next
#: PROPOSED: how far before the reach an account's first pass looks for a venue figure missing.
MISSING_SPAN: Final = timedelta(days=1)
#: The outcomes that put a record read in the delta set (Q3).
_CHANGED: Final = frozenset[SettleOutcome](("inserted", "settled", "replaced"))
FETCH_SECONDS: Final = "oms_closed_pnl_fetch_seconds"
#: Its `result`s: a read's `ok` or `failed`, and apart from them a crossing between accounts, the
#: resolve, a record or a seed's position reading naming another (`_OtherAccount`, C-2.11), which
#: the ticket `OmsClosedPnlAccountCrossing` reads (20 Sec.12.5).
FETCH_RESULTS: Final = ("ok", "failed", "other_account")
#: The order-entry gate's reason for an account with no usable key, as `commands` reads it.
_NO_ACTIVE_KEY: Final = "no_active_key"
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_ANY_FLAT: Final = datetime.max.replace(tzinfo=UTC)  # row 57's bound that finds a key's last flat
#: The merge's sums are exact here; its one division rounds to the columns' 18 places.
_WIDE: Final = Context(prec=80)
_E18: Final = Decimal(10) ** -18


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class VenueReads(Protocol):  # `TradingPort`'s two reads the sync makes
    async def closed_pnl(
        self, account: AccountRef, start: TsUs, end: TsUs
    ) -> Sequence[ClosedPnl]: ...
    async def positions(self, account: AccountRef) -> Sequence[Position]: ...


class ReadRouter(Protocol):
    """`routing.TradingRouter`: an environment's port, and a lane's headroom, taking no token."""

    def port_for(self, environment: Environment) -> VenueReads: ...
    def headroom(self, account: AccountRef, lane: RateLane) -> RateReading: ...


class ClosedPnlRecords(Protocol):  # `closed_pnl.ClosedPnlStore`'s writes, rows 56 and 57
    async def settle(self, record: VenueRecord) -> SettleOutcome: ...
    async def finalize(self, account_id: UUID, record_id: UUID) -> bool: ...
    async def pending(
        self, account_id: UUID, reach: datetime, limit: int
    ) -> tuple[PendingRecord, ...]: ...
    async def walk_flats(
        self, account_id: UUID, symbol: str, position_idx: int, before: datetime, limit: int
    ) -> tuple[datetime, ...]: ...


class StoredCloses(Protocol):  # `executions_sqlalchemy.SqlAlchemyExecutionStore.closed_size`
    async def closed_size(self, account_id: UUID, order_id: UUID) -> Decimal | None: ...


class SnapshotWrites(Protocol):  # `positions.PositionSnapshotStore`
    async def append(self, snapshot: NewPositionSnapshot) -> object: ...


class _NoHeadroom(Exception):
    """The `poll` lane would not get its token within its wait: nothing is sent (C-12.7)."""


class _OtherAccount(Exception):
    """The resolve, a record or a position reading names another account (C-2.11)."""


def _refused(error: Exception) -> bool:
    """The account binding's refusal outright (`TradingAccountsBinding`): the account missing,
    soft-deleted or another environment's (`AccountScopeDenied`), or holding no active key."""
    if isinstance(error, OrderEntryRefused):
        return error.reason == _NO_ACTIVE_KEY
    return isinstance(error, AccountScopeDenied)


def merged(records: Iterable[ClosedPnl]) -> list[ClosedPnl]:
    """A read's records, several under one `orderId` taken as one record (24 Sec.8.13): their
    sizes, `closed_pnl`, `open_fee` and `close_fee` summed (a fee one of them omits is absent),
    their prices weighted by size, `closed_at` the latest, `created_at` the earliest and `leverage`
    the latest record's. Exact sums and one rounding make it order-independent, and a record alone
    under its order is kept as read, so merging again changes nothing. A record with no `orderId`
    is its own (the empty-orderId rule)."""
    groups: dict[str, list[ClosedPnl]] = {}
    out: list[ClosedPnl] = []
    for record in records:
        if record.exchange_order_id is None:
            out.append(record)
        else:
            groups.setdefault(record.exchange_order_id, []).append(record)
    for order_id, group in groups.items():
        if len(group) > 1:
            account_id, count = str(group[0].account_id), len(group)
            _log().warning("closed_pnl_records_merged", account_id=account_id,
                           exchange_order_id=order_id, records=count)  # fmt: skip
        out.append(group[0] if len(group) == 1 else _one(group))
    return out


def _sum(values: Iterable[Decimal]) -> Decimal:
    total = Decimal(0)
    for value in values:
        total = _WIDE.add(total, value)
    return total


def _one(group: list[ClosedPnl]) -> ClosedPnl:
    latest = max(group, key=lambda r: (r.closed_at, r.leverage))
    qty = _sum(r.qty for r in group)

    def weighted(price: Callable[[ClosedPnl], Decimal]) -> Decimal:
        if qty == 0:  # no size to weigh by: the store refuses the record (`cpr_qty`)
            return price(latest)
        total = _sum(_WIDE.multiply(r.qty, price(r)) for r in group)
        return _WIDE.divide(total, qty).quantize(_E18, ROUND_HALF_EVEN, _WIDE)

    def fee(of: Callable[[ClosedPnl], Decimal | None]) -> Decimal | None:
        fees = [of(r) for r in group]
        return None if None in fees else _sum(f for f in fees if f is not None)

    return latest.model_copy(
        update={
            "qty": qty,
            "avg_entry_price": weighted(lambda r: r.avg_entry_price),
            "avg_exit_price": weighted(lambda r: r.avg_exit_price),
            "closed_pnl": _sum(r.closed_pnl for r in group),
            "open_fee": fee(lambda r: r.open_fee),
            "close_fee": fee(lambda r: r.close_fee),
            "created_at": min(r.created_at for r in group),
        }
    )


def venue_record(record: ClosedPnl) -> VenueRecord:
    """The store's record of a read's record: the item's side is the closing order's opposite, a
    `sell` closing a `long`; `ValueError` for one the table refuses, naming the rule."""
    return VenueRecord(
        exchange_account_id=record.account_id, exchange_order_id=record.exchange_order_id,
        symbol=record.symbol, side="long" if record.side == "sell" else "short", qty=record.qty,
        avg_entry_price=record.avg_entry_price, avg_exit_price=record.avg_exit_price,
        leverage=record.leverage, closed_pnl=record.closed_pnl, closed_at=_at(record.closed_at),
        venue_created_at=_at(record.created_at),
    )  # fmt: skip


def _at(us: TsUs) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


def _us(at: datetime) -> TsUs:
    return (at - _EPOCH) // timedelta(microseconds=1)


async def _bounded[T](call: Awaitable[T], seconds: float) -> T:
    async with asyncio.timeout(seconds):
        return await call


@dataclass
class _Account:
    due: float | None = None  # when its next read runs, on the loop's clock; None: none asked
    fills_until: float | None = None  # a read starting then or later, succeeding, ends the fills'
    keep: bool = False  # its last read failed, or left a record to poll
    seeded: bool = False  # its keys' flats were seeded (the ruling's first sight)
    named: set[UUID] = field(default_factory=set)  # the orders its stored fills named, to compose
    composed: bool = False  # its first composition after the settle ran
    carried: list[str] = field(default_factory=list)  # venue ids a composition left, oldest first
    owed: Owed = field(default_factory=dict)  # what its comparison owes the next pass
    missing_from: datetime | None = None  # where its next look for a venue figure missing starts


class ClosedPnlSync:
    """`now` is the wall clock a read's window takes; `day_start` the start of the day holding an
    instant, from the one resolver the cap takes too (`risk.day_boundary`, 24 Sec.8.13), whose
    failure fails the read, so the poll keeps running; `on_ended` what is told, once, on the
    task's loop, that the task ended other than by `stop()` (the runtime's page): it must not
    raise; `composer` the composition (module docstring), None for the stored rule alone;
    `comparer` the comparison of what it composes (module docstring), None for none."""

    def __init__(
        self, *, accounts: TradingAccounts, router: ReadRouter, records: ClosedPnlRecords,
        closes: StoredCloses, snapshots: SnapshotWrites, metrics: Metrics,
        now: Callable[[], datetime], on_ended: Callable[[], None],
        day_start: Callable[[datetime], Awaitable[datetime]],
        composer: ClosedPnlComposer | None = None, comparer: ClosedPnlComparer | None = None,
    ) -> None:  # fmt: skip
        self._accounts, self._router, self._records = accounts, router, records
        self._closes, self._snapshots, self._composer = closes, snapshots, composer
        self._comparer = comparer
        self._now, self._day_start, self._on_ended = now, day_start, on_ended
        spec = next(spec for spec in CATALOGUE if spec.name == FETCH_SECONDS)
        self._seconds = metrics.histogram(
            spec.name, spec.help, spec.labels, buckets=spec.buckets or (),
            max_series=spec.max_series,
        )  # fmt: skip
        self._state: dict[AccountId, _Account] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopped = False

    def start(self, accounts: Iterable[AccountId]) -> bool:
        """Startup: a read of each account at once, and the task; True when this call started it.
        Once, and never after `stop()`."""
        if self._task is not None or self._stopped:
            return False
        self._loop = asyncio.get_running_loop()
        for account_id in accounts:
            self._ask(account_id, 0.0)
        self._task = spawn(self._run(), name="oms-closed-pnl-sync")
        self._task.add_done_callback(self._ended)
        return True

    async def stop(self, timeout_s: float = PORT_TIMEOUT_S) -> None:
        """Cancel the task and wait for it, bounded; a cancel of the caller propagates."""
        self._stopped = True
        if self._task is None:
            return
        self._task.cancel()
        done, _ = await asyncio.wait({self._task}, timeout=timeout_s)
        if not done:
            _log().error("closed_pnl_sync_stop_timeout")

    @property
    def fault(self) -> str | None:
        task = self._task
        ended = task is not None and task.done() and not self._stopped
        return "the closed-PnL sync task ended" if ended else None

    def _ended(self, task: asyncio.Task[None]) -> None:
        """Any end `stop()` did not ask for, by an error, a return or a cancel (as the order lane's
        death cancels what is left on it), is a fault: logged at ERROR by its kind and told to
        `on_ended` once, as a task ends once. An end a stop asked for is told to no one, and is
        logged unless it is that stop's cancel. The error is retrieved either way."""
        error = asyncio.CancelledError() if task.cancelled() else task.exception()
        if self._stopped and task.cancelled():
            return
        kind = "returned" if error is None else type(error).__name__
        _log().error("closed_pnl_sync_ended", kind=kind)
        if not self._stopped:
            self._on_ended()

    def stored(self, execution: NewExecution) -> None:
        """A fill the store took: one of a trade type keeps the poll until a read that starts
        `SETTLE_POLL_S` after it succeeds, asks for a read within `DEBOUNCE_S` if it closes, and
        names its order for the composition."""
        if execution.exec_type not in CLOSING_EXEC_TYPES:
            return
        size, account_id = execution.closed_size, AccountId(execution.exchange_account_id)
        after = DEBOUNCE_S if size is not None and size > 0 else SETTLE_POLL_S
        state = self._ask(account_id, after)
        if state is not None and self._loop is not None:
            until = self._loop.time() + SETTLE_POLL_S
            state.fills_until = (
                until if state.fills_until is None else max(state.fills_until, until)
            )
        order = execution.order_id
        if state is None or self._composer is None or order is None or order in state.named:
            return
        if len(state.named) < NAMED_LIMIT:
            state.named.add(order)
        else:  # composed once its record is read (C-2.18)
            _log().warning("closed_pnl_named_order_dropped", account_id=str(account_id))

    def reconnected(self, account_id: AccountId) -> None:
        """The account's private stream came back: its records are read at once."""
        self._ask(account_id, 0.0)

    def _ask(self, account_id: AccountId, after: float) -> _Account | None:
        if self._loop is None or self._stopped:
            return None  # before the start, whose reads cover it; or after the stop
        state = self._state.get(account_id)
        if state is None:
            if len(self._state) >= MAX_ACCOUNTS:
                _log().error("closed_pnl_sync_request_dropped", account_id=str(account_id))
                return None
            state = self._state[account_id] = _Account()
        at = self._loop.time() + after
        state.due = at if state.due is None else min(state.due, at)
        self._wake.set()
        return state

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            self._wake.clear()
            now = loop.time()
            due = sorted(
                (s.due, a) for a, s in self._state.items() if s.due is not None and s.due <= now
            )
            for _, account_id in due:
                await self.read(account_id)
            if due:
                continue  # time has passed: look again before waiting
            dues = [s.due for s in self._state.values() if s.due is not None]
            timeout = None if not dues else max(0.0, min(dues) - loop.time())
            with contextlib.suppress(TimeoutError):  # the next read is due; a cancel propagates
                await asyncio.wait_for(self._wake.wait(), timeout)

    async def read(self, account_id: AccountId) -> bool:
        """The task's read of one account, True when it succeeded; public for the tests alone."""
        started = asyncio.get_running_loop().time()
        state = self._state.setdefault(account_id, _Account())
        state.due = None  # a request made from here on is the next read's
        try:
            state.keep = await self._pass(account_id, state)
        except Exception as exc:  # a failed read keeps the poll until one succeeds, a refusal not
            _log().warning("closed_pnl_read_failed", account_id=str(account_id),
                           kind=type(exc).__name__)  # fmt: skip
            state.keep, ok = not _refused(exc), False
            if not state.keep:  # nor the fills' wait: its next stored fill or `resyncing` asks
                state.fills_until = None
        else:
            ok = True
            if state.fills_until is not None and started >= state.fills_until:
                state.fills_until = None
        if state.keep or state.fills_until is not None:
            at = started + SETTLE_POLL_S
            state.due = at if state.due is None else min(state.due, at)
        return ok

    async def _pass(self, account_id: AccountId, state: _Account) -> bool:
        """The named orders' composition, the read, the records' writes, row 56's poll and the
        delta set's composition, then the seed, last so a slow one delays none of them: whether
        a record is left to poll. The named orders are kept for the next pass unless the delta
        set's composition ran."""
        now = self._now()
        named, state.named, done = state.named, set(), self._composer is None
        composing = None if self._composer is None else self._composer.begin(account_id)
        try:
            if composing is not None and named:  # before the day's and the venue's reads (Q2)
                await self._composed(account_id, composing.compose(named))
            reach = await _bounded(self._day_start(now), PORT_TIMEOUT_S) - CLOSED_PNL_LOOKBACK
            account, records = await self._fetch(account_id, reach, now)
            read = [(record, await self._settle(record)) for record in merged(records)]
            pending = await _bounded(
                self._records.pending(account_id, reach, PENDING_LIMIT), PORT_TIMEOUT_S
            )
            if composing is None:
                left = False
                for item in pending:
                    left = not await self._finalized(account_id, item) or left
            else:
                changed = [
                    r.exchange_order_id for r, outcome in read
                    if r.exchange_order_id is not None
                    and (outcome in _CHANGED or not state.composed)
                ]  # fmt: skip
                done, left = await self._settled(account_id, state, composing, named, changed,
                                                 pending, reach)  # fmt: skip
                state.composed = state.composed or done
        finally:
            if not done:  # composed at the next pass, before its read
                state.named |= named
        if not state.seeded:
            try:
                await self._seed(account)
                state.seeded = True
            except Exception as exc:  # tried again at the next read; the records are kept
                _log().warning("closed_pnl_flat_seed_failed", account_id=str(account_id),
                               kind=type(exc).__name__)  # fmt: skip
        return left

    async def _fetch(
        self, account_id: AccountId, reach: datetime, now: datetime
    ) -> tuple[AccountRef, Sequence[ClosedPnl]]:
        clock = asyncio.get_running_loop().time
        began = clock()
        try:
            account = await _bounded(self._accounts.trading_account(account_id), PORT_TIMEOUT_S)
            if account.account_id != account_id:
                raise _OtherAccount
            if not self._router.headroom(account, LANE).available:
                raise _NoHeadroom
            port = self._router.port_for(account.environment)
            read = port.closed_pnl(account, _us(reach), _us(now))
            records = await _bounded(read, READ_TIMEOUT_S)
            if any(r.account_id != account_id for r in records):
                raise _OtherAccount
        except Exception as exc:  # a crossing between accounts is counted apart (`FETCH_RESULTS`)
            crossed = isinstance(exc, _OtherAccount)
            self._seconds.labels("other_account" if crossed else "failed").observe(clock() - began)
            raise
        self._seconds.labels("ok").observe(clock() - began)
        return account, records

    async def _seed(self, account: AccountRef) -> None:
        """The ruled seed (module docstring): each key the venue states at size 0 and that holds
        no confirmed flat gets that reading stored as one, dated by its `updatedTime`. A reading
        of another account is timed as a crossing (`other_account`), as a read's is."""
        if not self._router.headroom(account, LANE).available:
            raise _NoHeadroom
        port, clock = self._router.port_for(account.environment), asyncio.get_running_loop().time
        began = clock()
        readings = await _bounded(port.positions(account), READ_TIMEOUT_S)
        horizon, account_id = self._now() + MAX_FUTURE_SKEW, account.account_id  # after the read
        if any(p.account_id != account_id for p in readings):
            self._seconds.labels("other_account").observe(clock() - began)
            raise _OtherAccount  # the seed fails, as a record fails the read, and is tried again
        for p in readings:
            at = _at(p.updated_at)
            if p.qty != 0 or at > horizon:
                continue  # only a size 0 the venue states, dated in reach
            flats = self._records.walk_flats(account_id, p.symbol, p.position_idx, _ANY_FLAT, 1)
            if await _bounded(flats, PORT_TIMEOUT_S):
                continue  # a key holding a confirmed flat gets no second one
            seed = NewPositionSnapshot(
                exchange_account_id=account_id, symbol=p.symbol, size=p.qty,
                reason="rest_reconcile", position_idx=p.position_idx, mark_price=p.mark_price,
                unrealised_pnl=p.unrealised_pnl, cum_realised_pnl=p.cum_realised_pnl,
                liq_price=p.liq_price, exchange_updated_ts=at,
            )  # fmt: skip
            await _bounded(self._snapshots.append(seed), PORT_TIMEOUT_S)
            _log().info("closed_pnl_flat_seeded", account_id=str(account_id), symbol=p.symbol,
                        position_idx=p.position_idx)  # fmt: skip

    async def _settle(self, record: ClosedPnl) -> SettleOutcome | None:
        ids = {"account_id": str(record.account_id), "exchange_order_id": record.exchange_order_id}
        try:
            stored = venue_record(record)
        except (TypeError, ValueError) as exc:  # one the table refuses: the others are kept
            _log().error("closed_pnl_record_refused", kind=type(exc).__name__, **ids)
            return None
        outcome = await _bounded(self._records.settle(stored), PORT_TIMEOUT_S)
        if outcome == "frozen":  # 24 Sec.8.13: never applied, counted nowhere
            _log().warning("closed_pnl_read_after_final", **ids)
        elif outcome == "replaced":
            _log().info("closed_pnl_record_replaced", **ids)
        return outcome

    async def _composed[T](self, account_id: AccountId, step: Awaitable[T]) -> T | None:
        """A composition step, None when it failed, logged by kind: the read goes on."""
        try:
            return await step
        except Exception as exc:  # a cancel propagates
            _log().warning("closed_pnl_compose_failed", account_id=str(account_id),
                           kind=type(exc).__name__)  # fmt: skip
            return None

    async def _settled(
        self, account_id: AccountId, state: _Account, composing: ComposePass, named: set[UUID],
        changed: list[str], pending: Sequence[PendingRecord], reach: datetime,
    ) -> tuple[bool, bool]:  # fmt: skip
        """The delta set's composition, its final rule and its comparison (Q3, Q4): whether it
        ran, and whether a record is left to poll, one of the poll's not final, a venue id
        carried or a comparison owed. The named orders come first, then the venue ids carried
        from earlier passes and those whose comparison is owed, then the records the read
        changed, then the poll's page less those, so a full page starves no fresh settle; what
        the step leaves past its bounds is carried to the next pass."""
        owed = (venue for venue, row in state.owed.items() if row is None)
        venue = list(dict.fromkeys((*state.carried, *owed, *changed)))
        first = set(venue)
        ids = (i.row.exchange_order_id for i in pending)  # row 56's each have one (its join)
        page = [x for x in ids if x is not None and x not in first]
        composed = await self._composed(
            account_id, composing.compose(named, (*venue, *page), finalize=True)
        )
        left = venue if composed is None else composing.unreached
        self._carry(account_id, state, left, set(page))
        compared = await self._compared(account_id, state, composed or (), reach)
        if composed is None:
            return False, True
        final = {c.row.id for c in composed if c.final}
        polled = any(item.row.id not in final for item in pending)
        return True, bool(state.carried) or not compared or polled

    async def _compared(
        self, account_id: AccountId, state: _Account, composed: Sequence[Composed],
        reach: datetime,
    ) -> bool:  # fmt: skip
        """The comparison of what the step composed and of the venue figures missing: whether
        nothing is owed. Never raises but a cancel: a failed look for the missing is logged by
        kind and made again at the next pass, from where it started."""
        if self._comparer is None:
            return True
        missing = [row for row in state.owed.values() if row is not None]
        looked = True
        try:
            missing += await self._missing(account_id, state, reach)
        except Exception as exc:  # a cancel propagates
            _log().warning("closed_pnl_missing_read_failed", account_id=str(account_id),
                           kind=type(exc).__name__)  # fmt: skip
            looked = False
        state.owed = await self._comparer.compare(account_id, composed, missing)
        return looked and not state.owed

    async def _missing(
        self, account_id: AccountId, state: _Account, reach: datetime
    ) -> list[ClosedPnlRecordRow]:
        """The records not settled whose `closed_at` left the reach since the last look (row 56
        from there), oldest first; a full page moves the look to its last `closed_at` only."""
        since = reach - MISSING_SPAN if state.missing_from is None else state.missing_from
        if since >= reach:
            return []
        read = self._records.pending(account_id, since, PENDING_LIMIT)
        rows = [item.row for item in await _bounded(read, PORT_TIMEOUT_S)]
        gone = [row for row in rows if row.closed_at < reach]
        state.missing_from = reach
        # A full page whose rows all share one `closed_at` equal to `since` cannot split that
        # instant, so the look moves to the reach and rows past the page at that instant are never
        # read, so never recorded (row 56's tie at the cut; it takes 200 records closed at once).
        if len(rows) == PENDING_LIMIT == len(gone) and gone[-1].closed_at > since:
            state.missing_from = gone[-1].closed_at  # the rest of that time at the next look
            gone = [row for row in gone if row.closed_at < state.missing_from]
        return [row for row in gone if row.settled_at is None]

    def _carry(
        self, account_id: AccountId, state: _Account, left: Iterable[str], page: set[str]
    ) -> None:
        """Carry the venue ids a composition left, but its page's, which the poll reads again,
        at most `CARRY_LIMIT` (C-2.18): past it the latest are dropped, logged at WARNING."""
        kept = list(dict.fromkeys(v for v in left if v not in page))
        if len(kept) > CARRY_LIMIT:
            _log().warning("closed_pnl_compose_carry_dropped", account_id=str(account_id),
                           left=len(kept) - CARRY_LIMIT)  # fmt: skip
        state.carried = kept[:CARRY_LIMIT]

    async def _finalized(self, account_id: AccountId, item: PendingRecord) -> bool:
        """Whether the record is final now: settled, its order's row terminal, and its `qty` the
        size its order's stored trade fills state they closed (24 Sec.8.13)."""
        row = item.row
        if row.settled_at is None or item.order_state not in TERMINAL_STATES:
            return False
        closed = self._closes.closed_size(account_id, item.order_id)
        if await _bounded(closed, PORT_TIMEOUT_S) != row.qty:
            return False
        return await _bounded(self._records.finalize(account_id, row.id), PORT_TIMEOUT_S)
