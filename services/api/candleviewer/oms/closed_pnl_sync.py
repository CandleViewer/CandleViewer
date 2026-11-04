"""The venue's closed-PnL records, read and kept (E29-S06 #981 slice 3; 24 Sec.8.13 "The sync").

`ClosedPnlSync` reads each account's records through `TradingPort.closed_pnl` in the `poll` lane,
the governor's background class, never the stop and cancel reserve (C-12.7): it reads the lane's
headroom first and reads nothing without it, as reconciliation's fetch does. A read covers the
reach, `CLOSED_PNL_LOOKBACK` before the day's start up to now, since the venue filters its window
by a time its documents do not name. Several records under one `orderId` are kept as one
(`merged`, logged at WARNING), and each is settled through the closed-PnL store, which replaces the
venue's columns until the record is final and then refuses them: a read after final is logged at
WARNING, never applied, and counted nowhere. A record is final once its closing order's row is
terminal and its `qty` is the size the order's stored trade fills state they closed; a fill that
states none (a REST-recovered one) keeps it open, and polled within the reach, until the
composition's walk gives such a fill its `c`. The composition and the comparison are E29-S06's
later slices: this one stores and keeps the records.

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
read once. A read is made again `SETTLE_POLL_S` after the last one started while that read failed,
while the account holds a record within the reach that is not final and whose order has a row
(21 Sec.13.1 row 56), or while a stored fill waits for a read that starts `SETTLE_POLL_S` after it
and succeeds. A record with no `orderId`, or whose order has no row, keeps no poll.

**Placement.** One owned task (`start`, `stop`; `fault` once it ends unasked) on the loop that
makes every call, reading the due accounts one at a time: one read is in flight per account, and a
request made meanwhile is folded into the account's next read. The requests are a queue of at most
`MAX_ACCOUNTS` accounts, one coalesced entry each: a request that would add an account past it is
dropped and logged at ERROR, as no process trades that many (C-2.18). Every external await is
bounded and a cancel is never swallowed. Each read is timed in `oms_closed_pnl_fetch_seconds`.
Logs carry ids and kinds only, never a figure (C-12.6).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
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
from candleviewer.storage.repositories.closed_pnl import PendingRecord, SettleOutcome, VenueRecord
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.oms_reads import CLOSING_EXEC_TYPES, TERMINAL_STATES
from candleviewer.storage.repositories.positions import MAX_FUTURE_SKEW, NewPositionSnapshot

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
FETCH_SECONDS: Final = "oms_closed_pnl_fetch_seconds"
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


def utc_day_start(at: datetime) -> datetime:
    """00:00 UTC of `at`'s day: offset 0, the instant the order path reads until E29-S06's resolver
    slice wires `risk_policy.day_boundary_utc_offset_minutes` (24 Sec.8.13, Sec.9.3.6)."""
    return at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


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


class ClosedPnlSync:
    """`now` is the wall clock a read's window takes; `day_start` the day's start for an instant,
    00:00 UTC until E29-S06's resolver slice passes its own."""

    def __init__(
        self, *, accounts: TradingAccounts, router: ReadRouter, records: ClosedPnlRecords,
        closes: StoredCloses, snapshots: SnapshotWrites, metrics: Metrics,
        now: Callable[[], datetime], day_start: Callable[[datetime], datetime] = utc_day_start,
    ) -> None:  # fmt: skip
        self._accounts, self._router, self._records = accounts, router, records
        self._closes, self._snapshots = closes, snapshots
        self._now, self._day_start = now, day_start
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
        self._task.add_done_callback(_ended)
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

    def stored(self, execution: NewExecution) -> None:
        """A fill the store took: one of a trade type keeps the poll until a read that starts
        `SETTLE_POLL_S` after it succeeds, and asks for a read within `DEBOUNCE_S` if it closes."""
        if execution.exec_type not in CLOSING_EXEC_TYPES:
            return
        size = execution.closed_size
        after = DEBOUNCE_S if size is not None and size > 0 else SETTLE_POLL_S
        state = self._ask(AccountId(execution.exchange_account_id), after)
        if state is not None and self._loop is not None:
            until = self._loop.time() + SETTLE_POLL_S
            state.fills_until = (
                until if state.fills_until is None else max(state.fills_until, until)
            )

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
        except Exception as exc:  # a failed read keeps the poll until one succeeds
            _log().warning("closed_pnl_read_failed", account_id=str(account_id),
                           kind=type(exc).__name__)  # fmt: skip
            state.keep, ok = True, False
        else:
            ok = True
            if state.fills_until is not None and started >= state.fills_until:
                state.fills_until = None
        if state.keep or state.fills_until is not None:
            at = started + SETTLE_POLL_S
            state.due = at if state.due is None else min(state.due, at)
        return ok

    async def _pass(self, account_id: AccountId, state: _Account) -> bool:
        """The read, the records' writes and row 56's poll, then the seed, last so a slow one
        delays none of them: whether a record is left to poll."""
        now = self._now()
        reach = self._day_start(now) - CLOSED_PNL_LOOKBACK
        account, records = await self._fetch(account_id, reach, now)
        for record in merged(records):
            await self._settle(record)
        pending = self._records.pending(account_id, reach, PENDING_LIMIT)
        left = False
        for item in await _bounded(pending, PORT_TIMEOUT_S):
            left = not await self._finalized(account_id, item) or left
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
        except Exception:
            self._seconds.labels("failed").observe(clock() - began)
            raise
        self._seconds.labels("ok").observe(clock() - began)
        return account, records

    async def _seed(self, account: AccountRef) -> None:
        """The ruled seed (module docstring): each key the venue states at size 0 and that holds
        no confirmed flat gets that reading stored as one, dated by its `updatedTime`."""
        if not self._router.headroom(account, LANE).available:
            raise _NoHeadroom
        port = self._router.port_for(account.environment)
        readings = await _bounded(port.positions(account), READ_TIMEOUT_S)
        horizon, account_id = self._now() + MAX_FUTURE_SKEW, account.account_id  # after the read
        if any(p.account_id != account_id for p in readings):
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

    async def _settle(self, record: ClosedPnl) -> None:
        ids = {"account_id": str(record.account_id), "exchange_order_id": record.exchange_order_id}
        try:
            stored = venue_record(record)
        except (TypeError, ValueError) as exc:  # one the table refuses: the others are kept
            _log().error("closed_pnl_record_refused", kind=type(exc).__name__, **ids)
            return
        outcome = await _bounded(self._records.settle(stored), PORT_TIMEOUT_S)
        if outcome == "frozen":  # 24 Sec.8.13: never applied, counted nowhere
            _log().warning("closed_pnl_read_after_final", **ids)
        elif outcome == "replaced":
            _log().info("closed_pnl_record_replaced", **ids)

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


def _ended(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        _log().error("closed_pnl_sync_ended", kind=type(exc).__name__)
