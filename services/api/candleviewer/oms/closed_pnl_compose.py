"""The closed-PnL composition (E29-S06 #981 slice 5b; 24 Sec.8.13 steps 1 to 6, "Provisional,
settled and final").

`ClosedPnlComposer.begin(account)` opens one sync pass's composition, which composes orders from
their stored fills: before the venue read, the orders the stored fills named, so a close shows as
soon as its fill is stored (the orchestrator's ruling Q2 of 2026-11-04, 23:45Z); after the
records settle, the pass's delta set (Q3), whose final rule it completes (Q4).

- **Reads.** One read of the orders (21 Sec.13.1 row 61): the account's order rows named, each
  with its stored trade fills' first, last and last closing (`closedSize` above 0) times, its
  key's last confirmed flat before the first (its walk's start), and whether its record is
  stored. Per walk, the key's flats (row 57) and fills (row 58, each with the group its order
  row's leg names, a leg of the account alone); per symbol, whether it is held in hedge mode
  (row 62). Every read names the account (C-12.4).
- **One walk per key per pass.** The orders of a key that share a start share a walk, up to their
  last fill: a confirmed flat drops all a walk holds, so the key's walk taken in pieces between
  its confirmed flats gives each close what one walk across them would; the pieces overlap only
  where an order's own fills straddle a flat, with the same closes.
  A walk is kept for the pass, so the settled step reuses the first step's unless it needs a
  fill past that walk's end, and a walk capped by a later sibling's fills is taken again for each
  earlier order, to that order's last fill.
- **Figures.** From the closes the walk gives an order's fills, exact, each quantized once,
  `ROUND_HALF_UP` to 8 dp: `gross_pnl` the closed PnL they hold, `fee_pnl` minus their closing
  fees and the opening fees they take, `funding_pnl` 0 when no settlement of the symbol falls in
  `[opened_at, the last close]`, ends included, and `local_net` the three's sum. Each is absent,
  never estimated: all with no walk start or past its cap, or where a close holds no closed PnL
  or disagrees; `fee_pnl` and `funding_pnl` while a close is unreadable; `funding_pnl` while a
  settlement falls in the window (until #843) or the interval is unknown; `local_net` unless all
  three are present. A later pass that cannot walk a held record (no start, as after the 90-day
  prune, or past the cap) does not write it, so it keeps the figures an earlier walk composed.
- **The item.** Written for an order whose stored fill closes (a stated `closedSize` above 0, or a
  `c` the walk gives) or whose record is stored: `qty` the closes' `c`, `avg_exit_price` their
  size-weighted price and `avg_entry_price` the entry value they take over their `c`, both to the
  column's 18 places, `closed_at` the last close, the walk's `opened_at`, and `trade_group_id`
  the one group the position's opening fills' orders name. A settled row keeps the venue's.
- **Final (Q4, option 3).** `is_final`: per record, from its own closes, never the walk's `clean`.
  A wrong `final_at` is permanent (21 `trg_cpr_guard`); in doubt the record stays open, polled.
- **Bounds (C-2.18).** A walk takes at most `WALK_BUDGET` and runs on a worker thread
  (`asyncio.to_thread`): 500 fills take a few milliseconds, more than the loop may spend. A step
  takes at most `COMPOSE_LIMIT` orders, those named by id first, and a pass spends about
  `WALL_BUDGET_S` of the loop's clock, checked before each order, so the last order's bounded
  calls may run past it; every store call is bounded. The venue ids a step leaves, past its limit
  or the budget, are `unreached`, for its caller to carry. An order past a walk's cap gets no
  figures, and one past the budget none this pass, each logged at WARNING with the account and
  its record.
- **Logs.** Ids and counts only, never a figure (C-12.6). No cap reads these figures: the day's
  loss keeps its own read of the venue's settled records (`day_figures`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)
from typing import Any, Final, Literal, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.domain.funding import FundingIntervalUnknown, resolve_funding_interval_minutes
from candleviewer.storage.repositories.closed_pnl import (
    ClosedPnlRecordRow,
    ComposedRecord,
    FillKey,
    OrderAnchor,
    WalkFill,
    record_id,
)
from candleviewer.storage.repositories.oms_reads import TERMINAL_STATES
from candleviewer.storage.repositories.orders import OrderState

from .closed_pnl_walk import Walk, WalkBudget, WalkClose, walk
from .errors import OmsNotReady
from .ports import Instruments

#: C-2.18: a walk's fills and flats (one more is read, so a capped walk knows), the orders one
#: step composes, the loop time past which a pass starts no order, and each call's bound.
WALK_BUDGET: Final = WalkBudget(fills=500, flats=32)
COMPOSE_LIMIT: Final = 256
WALL_BUDGET_S: Final = 5.0
CALL_TIMEOUT_S: Final = 5.0
#: Sums, products and negations of the walk's outputs, never rounded: they span about 200
#: digits, and `Inexact` is trapped, as the walk's is, so one past 400 digits raises instead.
_EXACT: Final = Context(prec=400, traps=[InvalidOperation, DivisionByZero, Overflow, Inexact])
_ROUND: Final = Context(prec=400)  # a figure's one quantize, the only rounding past a division
_WIDE: Final = Context(prec=80)  # a price's one division, as the walk's
_8DP, _18DP, _DAY = Decimal("1e-8"), Decimal("1e-18"), timedelta(days=1)
_ZERO: Final = Decimal(0).quantize(_8DP)
_Key = tuple[str, int, datetime]  # a walk's: symbol, `position_idx`, start


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ComposeStore(Protocol):
    """`closed_pnl.ClosedPnlStore`'s calls the composition makes, each in its account (C-12.4)."""

    async def anchors(
        self, account_id: UUID, orders: Collection[UUID], exchange_order_ids: Collection[str]
    ) -> tuple[OrderAnchor, ...]: ...
    async def walk_flats(
        self, account_id: UUID, symbol: str, position_idx: int, before: datetime, limit: int
    ) -> tuple[datetime, ...]: ...
    async def walk_fills(
        self, account_id: UUID, symbol: str, position_idx: int, after: FillKey, limit: int
    ) -> tuple[WalkFill, ...]: ...
    async def hedged(self, account_id: UUID, symbol: str) -> bool: ...
    async def compose(self, record: ComposedRecord) -> ClosedPnlRecordRow: ...
    async def finalize(self, account_id: UUID, record_id: UUID) -> bool: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Composed:
    """An order's composition as written: the row the write left, `local_net`, the walk's
    average entry and the size its closes close (each None when not composed), and `final` when
    this step made the record final. The comparison, E29-S06's next slice, reads it."""

    row: ClosedPnlRecordRow
    local_net: Decimal | None
    avg_entry: Decimal | None
    closed: Decimal | None
    final: bool


@dataclass(frozen=True, slots=True)
class _Kept:
    walk: Walk
    last: datetime  # the last fill time it was read up to


def _sum(values: Iterable[Decimal]) -> Decimal:
    total = Decimal(0)
    for value in values:
        total = _EXACT.add(total, value)
    return total


def _q(value: Decimal, places: Decimal) -> Decimal:
    return value.quantize(places, ROUND_HALF_UP, _ROUND)


def is_final(
    row: ClosedPnlRecordRow, state: OrderState, walked: Walk | None, closes: Sequence[WalkClose]
) -> bool:
    """Q4 option 3: settled and not yet final, its order's row terminal, a walk with a start that
    is not capped, the record's closes each `sizes_sure` and their `c` summing to its `qty`."""
    return (
        row.settled_at is not None and row.final_at is None and state in TERMINAL_STATES
        and walked is not None and walked.start is not None and not walked.capped
        and bool(closes)
        and all(close.sizes_sure for close in closes)
        and _sum(close.closed for close in closes) == row.qty
    )  # fmt: skip


def settles(opened: datetime, closed: datetime, minutes: int) -> bool:
    """Whether a funding settlement of the symbol, `minutes` apart from 00:00 UTC each day, falls
    in `[opened, closed]`, both ends included (24 Sec.8.13 step 5)."""
    day = opened.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(minutes=minutes)
    return min(day - (day - opened) // step * step, day + _DAY) <= closed


async def _bounded[T](call: Awaitable[T]) -> T:
    async with asyncio.timeout(CALL_TIMEOUT_S):
        return await call


class ClosedPnlComposer:
    """The composition over the closed-PnL store and the instrument cache (module docstring)."""

    def __init__(
        self, *, store: ComposeStore, instruments: Instruments,
        budget: WalkBudget = WALK_BUDGET, wall_s: float = WALL_BUDGET_S,
    ) -> None:  # fmt: skip
        self.store, self.instruments, self.budget, self.wall_s = store, instruments, budget, wall_s

    def begin(self, account_id: UUID) -> ComposePass:
        """One sync pass's composition of the account: its walks are kept until it ends."""
        return ComposePass(self, account_id)


@dataclass(frozen=True, slots=True)
class _Figures:
    """One order's figures from its closes (module docstring), None where absent."""

    qty: Decimal | None = None
    avg_exit: Decimal | None = None
    avg_entry: Decimal | None = None
    gross: Decimal | None = None
    fee: Decimal | None = None
    funding: Decimal | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    group: UUID | None = None

    @property
    def local_net(self) -> Decimal | None:
        parts = (self.gross, self.fee, self.funding)
        return None if None in parts else _sum(cast(tuple[Decimal, ...], parts))


class ComposePass:
    """One pass's composition of one account (module docstring)."""

    def __init__(self, composer: ClosedPnlComposer, account_id: UUID) -> None:
        self._c, self._account = composer, account_id
        self._walks: dict[_Key, _Kept] = {}
        self._hedged: dict[str, bool] = {}
        self._intervals: dict[str, int | None] = {}
        self._spent = 0.0  # the loop time its steps took
        self._unreached: list[str] = []

    @property
    def unreached(self) -> tuple[str, ...]:
        """The venue ids its last step left, for its caller to carry to a later pass: those it was
        given past `COMPOSE_LIMIT`, after the orders it was given by id, then those of the orders
        the wall budget left."""
        return tuple(self._unreached)

    async def compose(
        self, orders: Collection[UUID], exchange_order_ids: Collection[str] = (), *,
        finalize: bool = False,
    ) -> tuple[Composed, ...]:  # fmt: skip
        """Compose the orders named by id or by venue id, newest last fill first; with
        `finalize`, complete the final rule of each record composed."""
        clock = asyncio.get_running_loop().time
        began = clock()
        try:
            return await self._step(orders, exchange_order_ids, finalize, lambda: clock() - began)
        finally:
            self._spent += clock() - began

    async def _step(
        self, orders: Collection[UUID], names: Collection[str], finalize: bool,
        took: Callable[[], float],
    ) -> tuple[Composed, ...]:  # fmt: skip
        ids, venue = list(dict.fromkeys(orders)), list(dict.fromkeys(names))
        room = max(0, COMPOSE_LIMIT - len(ids))  # the named by id first, then the venue ids
        self._unreached = venue[room:]
        if len(ids) + len(venue) > COMPOSE_LIMIT:
            left = len(ids) + len(venue) - COMPOSE_LIMIT
            ids, venue = ids[:COMPOSE_LIMIT], venue[:room]
            _log().warning("closed_pnl_compose_limited", account_id=str(self._account), left=left)
        if not ids and not venue:
            return ()
        found = await _bounded(self._c.store.anchors(self._account, ids, venue))
        keys: dict[tuple[str, int, datetime | None], list[OrderAnchor]] = {}
        for a in found:  # an order with no venue id or no stored trade fill has nothing to compose
            if a.exchange_order_id is not None and a.last_fill is not None:
                keys.setdefault((a.symbol, a.position_idx, a.start), []).append(a)
        out: list[Composed] = []
        for (symbol, idx, start), group in sorted(keys.items(), key=_newest, reverse=True):
            walked: Walk | None = None
            top = max(cast(datetime, a.last_fill) for a in group)
            for a in group:
                if self._spent + took() >= self._c.wall_s:  # its figures wait for a later pass
                    self._warn("closed_pnl_compose_budget_spent", a)
                    self._unreached.append(cast(str, a.exchange_order_id))
                    continue
                if walked is None and start is not None:
                    walked = await self._walk((symbol, idx, start), group)
                own = walked  # one a later sibling's fills capped is taken again to its own end
                if own is not None and start is not None and own.capped and a.last_fill != top:
                    own = await self._walk((symbol, idx, start), (a,))
                if (composed := await self._one(a, own, finalize)) is not None:
                    out.append(composed)
        return tuple(out)

    async def _walk(self, key: _Key, group: Sequence[OrderAnchor]) -> Walk:
        """The walk of the group's key from its start up to the group's last fill, kept for the
        pass: a kept walk serves a group it reaches, unless it is capped short of that group's
        last fill, as a cap counts the fills up to it."""
        symbol, idx, start = key
        last = max(cast(datetime, a.last_fill) for a in group)
        kept = self._walks.get(key)
        if kept is not None and (kept.last == last or (kept.last > last and not kept.walk.capped)):
            return kept.walk
        store, budget, account = self._c.store, self._c.budget, self._account
        anchor = min(cast(datetime, a.first_fill) for a in group)
        if symbol not in self._hedged:
            self._hedged[symbol] = await _bounded(store.hedged(account, symbol))
        flats = await _bounded(store.walk_flats(account, symbol, idx, anchor, budget.flats + 1))
        read = await _bounded(
            store.walk_fills(account, symbol, idx, FillKey(start), budget.fills + 1)
        )
        fills = tuple(f for f in read if f.exec_ts <= last)  # a full read stopping short caps
        groups = {f.order_id: f.order_group_id for f in fills if f.order_id and f.order_group_id}
        call = asyncio.to_thread(
            walk, fills, tuple(at for at in flats if at <= last), anchor=anchor,
            position_idx=idx, hedged=self._hedged[symbol], budget=budget, order_groups=groups,
        )  # fmt: skip
        self._walks[key] = _Kept(await _bounded(call), last)
        return self._walks[key].walk

    async def _one(self, a: OrderAnchor, w: Walk | None, finalize: bool) -> Composed | None:
        """The order's item (module docstring), and its final rule with `finalize`."""
        closes = () if w is None else tuple(c for c in w.closes if c.fill.order_id == a.order_id)
        if not closes and a.last_close is None and not a.held:
            return None  # no stored fill of it closes: it waits for its record
        if w is not None and w.capped:
            self._warn("closed_pnl_walk_capped", a)
        if a.held and (w is None or w.capped):  # no start, as when pruned, or past its cap: a
            return None  # held record is not written, keeping what an earlier walk composed
        f = await self._figures(a.symbol, closes)
        # A held, unsettled record with no close this pass takes its last fill's time, which may
        # move a provisional item's day until the read settles it; a settled row keeps the venue's.
        record = ComposedRecord(
            exchange_account_id=self._account, exchange_order_id=cast(str, a.exchange_order_id),
            symbol=a.symbol, side="long" if a.side == "Sell" else "short",
            closed_at=f.closed_at or a.last_close or cast(datetime, a.last_fill),
            position_idx=cast(Literal[0, 1, 2], a.position_idx), trade_group_id=f.group,
            qty=f.qty, avg_entry_price=f.avg_entry, avg_exit_price=f.avg_exit, gross_pnl=f.gross,
            fee_pnl=f.fee, funding_pnl=f.funding, opened_at=f.opened_at,
        )  # fmt: skip
        row = await _bounded(self._c.store.compose(record))
        final = finalize and is_final(row, a.state, w, closes)
        if final:
            final = await _bounded(self._c.store.finalize(self._account, row.id))
        return Composed(
            row=row, local_net=f.local_net, avg_entry=f.avg_entry, closed=f.qty, final=final
        )

    async def _figures(self, symbol: str, closes: Sequence[WalkClose]) -> _Figures:
        if not closes:
            return _Figures()
        size = _sum(c.closed for c in closes)
        exits = _sum(_EXACT.multiply(c.closed, c.fill.exec_price) for c in closes)
        values, fees = [c.entry_value for c in closes], [c.opening_fees for c in closes]
        pnl, opened = [c.fill.closed_pnl for c in closes], [c.opened_at for c in closes]
        groups = frozenset[UUID]().union(*(c.groups for c in closes))
        f = _Figures(
            qty=size, avg_exit=_q(_WIDE.divide(exits, size), _18DP),
            closed_at=max(c.fill.exec_ts for c in closes),
            group=next(iter(groups)) if len(groups) == 1 else None,
        )  # fmt: skip
        if None not in values:
            known = cast(list[Decimal], values)
            f = replace(f, avg_entry=_q(_WIDE.divide(_sum(known), size), _18DP))
        if None in pnl or any(c.disagreeing for c in closes):
            return f  # step 1 and the disagreement span: no local figures
        f = replace(f, gross=_q(_sum(cast(list[Decimal], pnl)), _8DP))
        if None in fees or None in opened:
            return f  # unreadable: the walk's figures are absent
        paid = _sum((*(c.closing_fee for c in closes), *cast(list[Decimal], fees)))
        start = min(cast(list[datetime], opened))
        funding = await self._funding(symbol, start, cast(datetime, f.closed_at))
        fee = _q(_EXACT.minus(paid), _8DP)  # negated exactly: `-paid` would round at 28 digits
        return replace(f, fee=fee, funding=funding, opened_at=start)

    async def _funding(self, symbol: str, opened: datetime, closed: datetime) -> Decimal | None:
        """0 with no settlement in the window; absent with one (until #843) or with the symbol's
        interval unknown: no instrument, the cache not ready, or out of range."""
        if symbol not in self._intervals:
            try:
                instrument = await _bounded(self._c.instruments.instrument(symbol))
                self._intervals[symbol] = resolve_funding_interval_minutes(instrument)
            except (OmsNotReady, FundingIntervalUnknown):
                self._intervals[symbol] = None
        minutes = self._intervals[symbol]
        return None if minutes is None or settles(opened, closed, minutes) else _ZERO

    def _warn(self, event: str, a: OrderAnchor) -> None:
        """A record with no figures this pass, one stored or known to close: never a figure."""
        if a.last_close is not None or a.held:
            rid = record_id(self._account, cast(str, a.exchange_order_id))
            _log().warning(event, account_id=str(self._account), record_id=str(rid))


def _newest(item: tuple[object, list[OrderAnchor]]) -> datetime:
    return max(cast(datetime, a.last_fill) for a in item[1])
