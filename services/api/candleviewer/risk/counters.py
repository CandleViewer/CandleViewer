"""The day's risk counters for one (environment, account, paper) (E39-T01, M17; E39-K01 §5, §6).

Pure state, fed by `RiskFill`, `RiskPosition`, `RiskMark` and `VenueClosedPnl` events and read by
`figures(now)`, the snapshot `evaluate` judges. No I/O and no clock read: every time is passed in.
Single asyncio loop: every method is synchronous with no `await`, so no lock is needed.

- **Idempotent by exec id** (SR-E39-11): a replayed fill is ignored; record ids likewise.
- **A close is booked by its fills' exchange time**, an order's closing fills as one close, at its
  **bound**: price PnL less the closing fee and the prorated opening fee at no less than the taker
  rate x the opening value (K01 §6), provisional until a venue record confirms it or 5 min pass
  (then the stream's figure is settled for the flatten only; the blocking figure keeps the bound).
- **A backfilled close** (no `exec_pnl`) is booked from the projection's entry, no gain credited,
  unconfirmed until a record covers it (K01 §5.5).
- **Reconciliation only tightens** a confirmed close; a record confirms an awaiting close in either
  direction only as the sole candidate with no awaiting sibling on the symbol. An unmatched or
  ambiguous record is booked by its `updated_at`, a loss in full and a gain at 0 (K01 §5.4, §5.5).
- **Unrealised:** `min(0, net)` over the open positions at a mark at most `max_age` old (public,
  then the push's); a missing, stale or future mark answers `None` (K01 §5.2, §5.8).
- **Rollover** on the shared `DayCalendar`: the day's closes, peak and day-start equity reset;
  positions carry (K01 §5.3). A fill dated after the key's end waits (bounded) until a roll or an
  offset change brings it inside the key.
- **A position push includes every fill dated at or before it** (K01 §5.5, §5.8): such a fill books
  its close but never moves the size or entry. Fills out of exchange order bound the entry at its
  worst and net no gain until the next push; a close ahead of its own open is clamped (over-count).
- **Sticky fail closed** (cold start, malformed value, exhausted bound, unboundable close) until the
  slice-3 rebuild or a restart; about 600k ids per account at the caps. `figures` is O(positions).
- **Day-start equity** is the key's first `set_equity`; slice 3 seeds it on a mid-day cold start.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Final

from candleviewer.domain.primitives import Side
from candleviewer.risk.clock import DayCalendar
from candleviewer.risk.inputs import RiskFigures, RiskFill, RiskMark, RiskPosition, VenueClosedPnl

DEFAULT_MAX_AGE: Final = timedelta(seconds=10)
RECORD_TIMEOUT: Final = timedelta(minutes=5)
#: A record matches a close whose last fill is at most this long before the record (A2 + margin).
MATCH_WINDOW: Final = timedelta(seconds=120)
#: Per-day bound on exec and record ids held; past it the counter answers unavailable, not wrong.
MAX_IDS: Final = 200_000
MAX_EARLY: Final = 1024
_ZERO: Final = Decimal(0)


class CloseState(StrEnum):
    PROVISIONAL = "provisional"
    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    TIMED_OUT = "timed_out"


_AWAITING: Final = (CloseState.PROVISIONAL, CloseState.UNCONFIRMED)


class FillOutcome(StrEnum):
    """What a fill did; the service logs prior_day, alerts on overflow and invalid (SR-E39-11)."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    PRIOR_DAY = "prior_day"  # dated before the key: the position moves, today's figure does not
    QUEUED = "queued"  # dated after the key's end: booked when its key starts
    OVERFLOW = "overflow"  # an id or queue bound is reached: the counter fails closed
    INVALID = "invalid"  # a malformed value or an unboundable close: the counter fails closed


class RecordOutcome(StrEnum):
    """What a venue record did; the service audits tightened, bound_settled and unmatched_booked."""

    DUPLICATE = "duplicate"
    OUT_OF_DAY = "out_of_day"
    UNCHANGED = "unchanged"
    CONFIRMED = "confirmed"
    HELD = "held"  # a sibling awaits a record: kept until one sole match or the timeout
    TIGHTENED = "tightened"
    BOUND_SETTLED = "bound_settled"
    UNMATCHED_BOOKED = "unmatched_booked"
    OVERFLOW = "overflow"  # the per-day id bound is reached: the counter fails closed
    INVALID = "invalid"  # a non-positive or non-finite value: the counter fails closed


@dataclass(slots=True)
class _Close:
    symbol: str
    side: Side
    state: CloseState
    booked_at: datetime
    last_exec: datetime
    qty: Decimal = _ZERO
    exit_value: Decimal = _ZERO
    bound: Decimal = _ZERO
    exact: Decimal = _ZERO
    from_record: bool = False
    held: Decimal | None = None  # a HELD record's pnl: the timeout settles on it (K01 §5.4)
    slot: tuple[datetime, int, str] | None = None  # its place in the last-exec order


@dataclass(slots=True)
class _Position:
    size: Decimal = _ZERO
    entry: Decimal = _ZERO
    at: datetime | None = None
    push_at: datetime | None = None  # the last applied push: fills dated at or before it are in it
    disordered: bool = False  # a fill arrived older than one applied: entry bounded until a push
    hi: Decimal = _ZERO  # the highest and lowest entry candidate since the last push
    lo: Decimal = _ZERO
    open_fee: Decimal = _ZERO  # the still-open part's opening fees and value, for proration
    open_value: Decimal = _ZERO
    max_rate: Decimal = _ZERO


def _dir(side: Side) -> int:
    return 1 if side == "buy" else -1


def _positive(*values: Decimal | None) -> bool:
    return all(v is None or (v.is_finite() and v > _ZERO) for v in values)


def _finite(*values: Decimal | None) -> bool:
    return all(v is None or v.is_finite() for v in values)


def _entry(pos: _Position, side: Side) -> Decimal:
    """The average entry; once fills arrived out of exchange order, its worst case (pessimistic):
    an average of the push's entry and the opening prices since lies between their extremes."""
    if not pos.disordered:
        return pos.entry
    if side == "buy":
        return max(pos.hi, pos.entry)
    return min(pos.lo, pos.entry) if pos.lo else pos.entry


def _at_tick(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(ROUND_HALF_EVEN) * tick


class AccountCounters:
    """One account's counters on one day key; `figures` is None while the state is unavailable."""

    def __init__(
        self,
        calendar: DayCalendar,
        *,
        taker_rate: Decimal,
        max_age: timedelta = DEFAULT_MAX_AGE,
    ) -> None:
        self._calendar = calendar
        self._key = calendar.key
        self._taker_rate = taker_rate
        self._max_age = max_age
        self._ready = False  # cold start: unavailable until the rebuild completes (slice 3)
        self._broken = False  # sticky: see the module docstring
        self._seen: set[str] = set()
        self._seen_before: set[str] = set()
        self._records: set[str] = set()
        self._closes: dict[str, _Close] = {}
        self._order: list[tuple[datetime, int, str]] = []  # closes by last exec time
        self._seq = 0
        self._run: int | None = 0  # the loss run; None: recount on the next read
        self._realised = _ZERO
        self._early: list[tuple[RiskFill, Decimal, Decimal, CloseState]] = []
        self._positions: dict[tuple[str, Side], _Position] = {}
        self._marks: dict[tuple[str, str], RiskMark] = {}
        self._equity: Decimal | None = None
        self._day_equity: Decimal | None = None
        self._peak = _ZERO

    def mark_ready(self) -> None:
        self._ready = True

    def set_equity(self, equity: Decimal, now: datetime) -> None:
        self._roll(now)
        self._equity = equity
        if self._day_equity is None:
            self._day_equity = equity

    def apply_mark(self, mark: RiskMark) -> None:
        if not _positive(mark.price):
            self._broken = True
            return
        held = self._marks.get((mark.symbol, mark.source))
        if held is None or mark.at >= held.at:
            self._marks[(mark.symbol, mark.source)] = mark

    def apply_position(self, push: RiskPosition) -> None:
        valid = _finite(push.size, push.entry_price) and push.size >= _ZERO
        if not (valid and (push.size == _ZERO or push.entry_price > _ZERO)):
            self._broken = True
            return
        pos = self._positions.setdefault((push.symbol, push.side), _Position())
        if pos.at is not None and push.at < pos.at:
            return  # older than a fill already applied
        pos.size, pos.at, pos.push_at, pos.disordered = push.size, push.at, push.at, False
        pos.hi = pos.lo = _ZERO
        if push.size > _ZERO:  # a flat push keeps the last entry for its late closing fills
            pos.entry = pos.hi = pos.lo = push.entry_price
            pos.open_value = max(pos.open_value, push.entry_price * push.size)

    def apply_fill(self, fill: RiskFill, now: datetime) -> FillOutcome:
        """Apply one fill once by exec id; a fill dated at or before the last push books only."""
        self._roll(now)
        if fill.exec_id in self._seen or fill.exec_id in self._seen_before:
            return FillOutcome.DUPLICATE
        valid = _positive(fill.qty, fill.price, fill.entry_price)
        if not (valid and _finite(fill.fee, fill.fee_rate, fill.exec_pnl)):
            self._broken = True
            return FillOutcome.INVALID
        if len(self._seen) >= MAX_IDS:
            self._broken = True
            return FillOutcome.OVERFLOW
        self._seen.add(fill.exec_id)
        pos = self._positions.setdefault((fill.symbol, fill.position_side), _Position())
        stale = pos.push_at is not None and fill.exec_time <= pos.push_at
        if pos.at is not None and fill.exec_time < pos.at and not stale:
            pos.disordered = True
        pos.at = fill.exec_time if pos.at is None else max(pos.at, fill.exec_time)
        if fill.opening:
            pos.open_fee += fill.fee
            pos.max_rate = max(pos.max_rate, fill.fee_rate)
            if not stale:
                value = fill.price * fill.qty
                size = pos.size + fill.qty
                pos.entry = (pos.entry * pos.size + value) / size
                pos.size, pos.open_value = size, pos.open_value + value
                pos.hi = max(pos.hi, fill.price)
                pos.lo = min(pos.lo, fill.price) if pos.lo else fill.price
            return FillOutcome.APPLIED
        sign = _dir(fill.position_side)
        entry = fill.entry_price or _entry(pos, fill.position_side) or None
        exec_entry = (
            _ZERO if fill.exec_pnl is None else fill.price - fill.exec_pnl * sign / fill.qty
        )
        held = pos.size + fill.qty if stale else pos.size  # the size before this close
        share = min(Decimal(1), fill.qty / held) if held > _ZERO else Decimal(1)
        open_fee = pos.open_fee * share
        open_value = max(pos.open_value * share, fill.qty * max(entry or _ZERO, exec_entry))
        pos.open_fee -= open_fee
        if not stale:  # clamped: a close ahead of its own open leaves exposure over, not under
            pos.size = max(_ZERO, pos.size - fill.qty)
        pos.open_value = max(pos.open_value - pos.open_value * share, pos.entry * pos.size)
        rate = max(self._taker_rate, pos.max_rate, fill.fee_rate)
        bound_fee = max(open_fee, rate * open_value)
        if fill.exec_pnl is not None:
            exact = fill.exec_pnl - fill.fee - open_fee
            bound, state = fill.exec_pnl - fill.fee - bound_fee, CloseState.PROVISIONAL
        elif entry is None:
            self._broken = True  # a backfilled close with no entry cannot be bounded
            return FillOutcome.INVALID
        else:
            pnl = (fill.price - entry) * fill.qty * sign
            exact = pnl - fill.fee - open_fee
            bound, state = min(_ZERO, pnl - fill.fee - bound_fee), CloseState.UNCONFIRMED
        if fill.exec_time >= self._key.end:
            if len(self._early) >= MAX_EARLY:
                self._broken = True
                return FillOutcome.OVERFLOW
            self._early.append((fill, bound, exact, state))
            return FillOutcome.QUEUED
        if fill.exec_time < self._key.start:
            return FillOutcome.PRIOR_DAY
        self._book(fill, bound, exact, state, now)
        return FillOutcome.APPLIED

    def _place(self, ref: str, close: _Close, last_exec: datetime) -> None:
        """Move `close` to `last_exec` in the order; the run is kept only for one appended last."""
        appended = close.slot is None and (not self._order or self._order[-1][0] <= last_exec)
        if close.slot is not None:
            del self._order[bisect_left(self._order, close.slot)]
        self._seq += 1
        close.last_exec, close.slot = last_exec, (last_exec, self._seq, ref)
        insort(self._order, close.slot)
        if appended and self._run is not None:
            self._run = self._run + 1 if close.bound < _ZERO else 0
        else:
            self._run = None

    def _rebound(self, close: _Close, bound: Decimal) -> None:
        self._realised += bound - close.bound
        close.bound = bound
        self._run = None

    def _book(
        self, fill: RiskFill, bound: Decimal, exact: Decimal, state: CloseState, now: datetime
    ) -> None:
        close = self._closes.get(fill.order_ref)
        if close is None:
            close = self._closes[fill.order_ref] = _Close(
                fill.symbol, fill.position_side, state, now, fill.exec_time
            )
        close.qty += fill.qty
        close.exit_value += fill.price * fill.qty
        close.bound += bound
        self._realised += bound
        close.exact += exact
        close.booked_at = now
        if close.state is not CloseState.UNCONFIRMED:
            close.state = state
        self._place(fill.order_ref, close, max(close.last_exec, fill.exec_time))

    def apply_venue_record(self, record: VenueClosedPnl, now: datetime) -> RecordOutcome:
        self._roll(now)
        if record.record_id in self._records:
            return RecordOutcome.DUPLICATE
        valid = _positive(record.qty, record.avg_exit_price, record.tick)
        if not (valid and _finite(record.pnl)):
            self._broken = True
            return RecordOutcome.INVALID
        if len(self._records) >= MAX_IDS:
            self._broken = True
            return RecordOutcome.OVERFLOW
        self._records.add(record.record_id)
        exit_at = _at_tick(record.avg_exit_price, record.tick)
        lo = record.updated_at - MATCH_WINDOW
        candidates = [
            close
            for close in self._closes.values()
            if not close.from_record
            and (close.symbol, close.side, close.qty)
            == (record.symbol, record.position_side, record.qty)
            and _at_tick(close.exit_value / close.qty, record.tick) == exit_at
            and lo <= close.last_exec <= record.updated_at
        ]
        if len(candidates) != 1:
            if record.updated_at not in self._key:
                return RecordOutcome.OUT_OF_DAY
            ref = f"record:{record.record_id}"
            booked = _Close(record.symbol, record.position_side, CloseState.CONFIRMED, now, now)
            booked.qty, booked.exit_value = record.qty, record.avg_exit_price * record.qty
            booked.bound = booked.exact = min(_ZERO, record.pnl)  # no gain until confirmed
            self._closes[ref], booked.from_record = booked, True
            self._realised += booked.bound
            self._place(ref, booked, record.updated_at)
            return RecordOutcome.UNMATCHED_BOOKED
        close = candidates[0]
        if close.state in _AWAITING:
            siblings = any(
                other is not close and other.symbol == close.symbol and other.state in _AWAITING
                for other in self._closes.values()
            )
            if record.pnl >= close.bound and siblings:
                close.held = record.pnl  # the id stays unread: a re-poll may still confirm it
                self._records.discard(record.record_id)
                return RecordOutcome.HELD
            outcome = RecordOutcome.CONFIRMED
            if record.pnl < close.bound:
                outcome = RecordOutcome.TIGHTENED
            elif record.pnl > close.bound:
                outcome = RecordOutcome.BOUND_SETTLED
        elif record.pnl < close.bound:
            outcome = RecordOutcome.TIGHTENED
        else:
            return RecordOutcome.UNCHANGED
        self._rebound(close, record.pnl)
        close.exact = record.pnl
        close.state = CloseState.CONFIRMED
        return outcome

    def expire_records(self, now: datetime) -> tuple[str, ...]:
        """Closes with no record after `RECORD_TIMEOUT`: a held record's pnl, else their own figure,
        counts for the flatten."""
        self._roll(now)
        expired = [
            ref
            for ref, close in self._closes.items()
            if close.state in _AWAITING and now - close.booked_at >= RECORD_TIMEOUT
        ]
        for ref in expired:
            close = self._closes[ref]
            close.state = CloseState.TIMED_OUT
            if close.held is not None:
                close.exact = close.held
        return tuple(expired)

    @property
    def realised_today(self) -> Decimal:
        """The blocking realised figure: every close at its bound or its record."""
        return self._realised

    @property
    def settled_today(self) -> Decimal:
        """The flatten decision's realised figure: confirmed records and timed-out closes only."""
        return sum(
            (
                close.exact if close.state is CloseState.TIMED_OUT else close.bound
                for close in self._closes.values()
                if close.state not in _AWAITING
            ),
            _ZERO,
        )

    @property
    def unconfirmed(self) -> bool:
        return any(close.state in _AWAITING for close in self._closes.values())

    def _mark(self, symbol: str, now: datetime) -> Decimal | None:
        for source in ("public", "position"):
            mark = self._marks.get((symbol, source))
            if mark is not None and timedelta(0) <= now - mark.at <= self._max_age:
                return mark.price
        return None

    def figures(self, now: datetime) -> RiskFigures | None:
        """The snapshot at `now`, or None: risk state unavailable (fail closed)."""
        self._roll(now)
        if not self._ready or self._broken:
            return None
        net, held = _ZERO, 0
        notional: dict[str, Decimal] = {}
        for (symbol, side), pos in self._positions.items():
            if pos.size <= _ZERO:
                continue
            mark = self._mark(symbol, now)
            if mark is None:
                return None
            rate = max(self._taker_rate, pos.max_rate)
            fees = max(pos.open_fee, rate * pos.open_value)
            pnl = (mark - _entry(pos, side)) * pos.size * _dir(side) - fees
            net += min(_ZERO, pnl) if pos.disordered else pnl  # no gain on an unsure position
            notional[symbol] = notional.get(symbol, _ZERO) + pos.size * mark
            held += 1
        daily = self._realised + min(_ZERO, net)
        self._peak = max(self._peak, daily)
        return RiskFigures(
            as_of=now,
            equity=self._equity,
            day_start_equity=self._day_equity,
            daily_figure=daily,
            day_peak_figure=self._peak,
            open_positions=held,
            open_orders=0,
            orders_last_minute=0,
            consecutive_losses=self._consecutive_losses(),
            symbol_notional=notional,
        )

    def _consecutive_losses(self) -> int:
        """Losing closes since the last non-losing one by last exec time; break-even resets."""
        if self._run is None:
            run = 0
            for *_, ref in reversed(self._order):
                if self._closes[ref].bound >= _ZERO:
                    break
                run += 1
            self._run = run
        return self._run

    def _roll(self, now: datetime) -> None:
        self._calendar.advance(now)
        key = self._calendar.key
        if key == self._key:
            return
        if key.start != self._key.start:
            self._closes.clear()
            self._order.clear()
            self._records.clear()
            self._seen_before, self._seen = self._seen, set()
            self._run, self._realised, self._peak = 0, _ZERO, _ZERO
            self._day_equity = self._equity
        self._key = key  # a new day, or an offset change stretched the end: re-examine the queue
        early, self._early = self._early, []
        for fill, bound, exact, state in early:
            if fill.exec_time >= key.end:
                self._early.append((fill, bound, exact, state))
            else:
                self._book(fill, bound, exact, state, now)
