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
  ambiguous record is booked by its `updated_at` as a loss in full; one with no loss books
  nothing, so it neither closes at break-even nor resets the loss run (K01 §5.4, §5.5).
- **Unrealised:** `min(0, net)` over the open positions at a mark at most `max_age` old (public,
  then the push's); a missing, stale or future mark answers `None` (K01 §5.2, §5.8).
- **Rollover** on the shared `DayCalendar`: the day's closes, peak and day-start equity reset;
  positions carry (K01 §5.3). A fill dated after the key's end waits (bounded) until a roll or an
  offset change brings it inside the key, or is dropped as a prior-day fill when a roll skips its
  key (a §8.13 short day or a multi-day jump); the caller saw QUEUED and gets no second outcome.
- **A position push includes every fill dated at or before it** (K01 §5.5, §5.8): such a fill books
  its close but never moves the size or entry; one at the push's own instant counts as in it (the
  venue pushes per change). The first push is the baseline: fills already applied that are dated
  after it are replayed on it (a pre-start size is never lost). Fills out of exchange order bound
  the entry at its worst and net no gain until the next push; a close ahead of its own open is
  clamped (over-count). **Adapter contract (slice 3):** a push is stamped with the venue's own
  update time of the position or, for a REST snapshot, its fetch time, never earlier: a first push
  dated before an exec it already includes would replay that exec on it (double size, phantom gain).
- **Indexed:** a record looks up only the closes of its (symbol, side, qty) in its match window,
  and the expiry and the sibling test read only the closes awaiting a record.
- **Sticky fail closed** (cold start, malformed value or tz-naive time, exhausted bound,
  unboundable close, a first push older than more fills than were logged) until the
  slice-3 rebuild or a restart; about 600k ids per account at the caps. `figures` is O(positions).
- **Day-start equity** is the key's first `set_equity`; slice 3 seeds it on a mid-day cold start.
- **A stream gap** (`mark_gap`) makes the account unavailable again until the backfill completes and
  slice 3 calls `mark_ready` (K01 §5.5); unlike the sticky states it is reversible.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from itertools import count
from typing import Final, cast

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
    QUEUED = "queued"  # after the key's end: booked when its key starts, or dropped as a
    # prior-day fill when a roll skips its key (a §8.13 short day or multi-day jump); no 2nd outcome
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
    #: Fills applied before the first push, replayed on it when it is older (None after it).
    log: list[tuple[datetime, int, bool, Decimal, Decimal]] | None = field(default_factory=list)
    lost: bool = False  # the log overflowed: an older first push cannot be replayed


def _signed(value: Decimal, side: Side) -> Decimal:
    """A long's PnL as is, a short's negated."""
    return value if side == "buy" else -value


def _positive(*values: Decimal | None) -> bool:
    return all(v is None or (v.is_finite() and v > _ZERO) for v in values)


def _finite(*values: Decimal | None) -> bool:
    return all(v is None or v.is_finite() for v in values)


def _aware(*times: datetime) -> bool:
    return all(t.utcoffset() is not None for t in times)


def _open(pos: _Position, qty: Decimal, price: Decimal) -> None:
    value = price * qty
    size = pos.size + qty
    pos.entry = (pos.entry * pos.size + value) / size
    pos.size, pos.open_value = size, pos.open_value + value
    pos.hi = max(pos.hi, price)
    pos.lo = min(pos.lo, price) if pos.lo else price


def _entry(pos: _Position, side: Side) -> Decimal:
    """The average entry; once fills arrived out of exchange order, its worst case (pessimistic):
    an average of the push's entry and the opening prices since lies between their extremes."""
    if not pos.disordered:
        return pos.entry
    if side == "buy":
        return max(pos.hi, pos.entry)
    return min(pos.lo, pos.entry) if pos.lo else pos.entry


def _ticks(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(ROUND_HALF_EVEN)


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
        self._seq = count()  # arrival order: the tie-break at one exchange instant
        self._run: int | None = 0  # the loss run; None: recount on the next read
        self._realised = _ZERO  # Σ bound, kept running: a recount may differ by a 28-digit ulp
        self._by_key: dict[tuple[str, Side, Decimal], list[tuple[datetime, int, str]]] = {}
        self._awaiting: dict[str, None] = {}  # the closes awaiting a record, and per symbol
        self._awaiting_on: dict[str, int] = {}
        self._early: list[tuple[RiskFill, Decimal, Decimal, CloseState]] = []
        self._positions: dict[tuple[str, Side], _Position] = {}
        self._marks: dict[tuple[str, str], RiskMark] = {}
        self._equity: Decimal | None = None
        self._day_equity: Decimal | None = None
        self._peak = _ZERO

    def mark_ready(self) -> None:
        self._ready = True

    def mark_gap(self) -> None:
        """A detected stream gap: unavailable until the backfill completes (K01 §5.5)."""
        self._ready = False

    def set_equity(self, equity: Decimal, now: datetime) -> None:
        self._roll(now)
        self._equity = equity
        if self._day_equity is None:
            self._day_equity = equity

    def apply_mark(self, mark: RiskMark) -> None:
        if not (_positive(mark.price) and _aware(mark.at)):
            self._broken = True
            return
        held = self._marks.get((mark.symbol, mark.source))
        if held is None or mark.at >= held.at:
            self._marks[(mark.symbol, mark.source)] = mark

    def apply_position(self, push: RiskPosition) -> None:
        valid = _finite(push.size, push.entry_price) and push.size >= _ZERO and _aware(push.at)
        if not (valid and (push.size == _ZERO or push.entry_price > _ZERO)):
            self._broken = True
            return
        pos = self._positions.setdefault((push.symbol, push.side), _Position())
        later: list[tuple[datetime, int, bool, Decimal, Decimal]] = []
        last = pos.at
        if last is not None and push.at < last:
            if pos.log is None:
                return  # older than a fill already applied
            if pos.lost:
                self._broken = True  # m9: the fills after this first push cannot be replayed
                return
            later = sorted(entry for entry in pos.log if entry[0] > push.at)
        pos.size, pos.at, pos.push_at, pos.disordered = push.size, push.at, push.at, False
        pos.hi = pos.lo = _ZERO
        pos.log = None
        if push.size > _ZERO:  # a flat push keeps the last entry for its late closing fills
            pos.entry = pos.hi = pos.lo = push.entry_price
        for _, _, opening, qty, price in later:  # the baseline: replay what came after it
            if opening:
                _open(pos, qty, price)
            else:
                pos.size = max(_ZERO, pos.size - qty)
        if later:
            pos.at = last
        pos.open_value = max(pos.open_value, pos.entry * pos.size)

    def apply_fill(self, fill: RiskFill, now: datetime) -> FillOutcome:
        """Apply one fill once by exec id; a fill dated at or before the last push books only."""
        self._roll(now)
        if fill.exec_id in self._seen or fill.exec_id in self._seen_before:
            return FillOutcome.DUPLICATE
        valid = _positive(fill.qty, fill.price, fill.entry_price) and _aware(fill.exec_time)
        if not (valid and _finite(fill.fee, fill.fee_rate, fill.exec_pnl)):
            self._broken = True
            return FillOutcome.INVALID
        if len(self._seen) >= MAX_IDS:
            self._broken = True
            return FillOutcome.OVERFLOW
        self._seen.add(fill.exec_id)
        pos = self._positions.setdefault((fill.symbol, fill.position_side), _Position())
        stale = pos.push_at is not None and fill.exec_time <= pos.push_at  # l10: same ms is in it
        if pos.log is not None and not pos.lost:
            if len(pos.log) >= MAX_EARLY:
                pos.lost, pos.log = True, []
            else:
                logged = (fill.exec_time, next(self._seq), fill.opening, fill.qty, fill.price)
                pos.log.append(logged)
        if pos.at is not None and fill.exec_time < pos.at and not stale:
            pos.disordered = True
        pos.at = fill.exec_time if pos.at is None else max(pos.at, fill.exec_time)
        if fill.opening:
            pos.open_fee += fill.fee
            pos.max_rate = max(pos.max_rate, fill.fee_rate)
            if not stale:
                _open(pos, fill.qty, fill.price)
            return FillOutcome.APPLIED
        entry = fill.entry_price or _entry(pos, fill.position_side) or None
        exec_entry = (
            _ZERO
            if fill.exec_pnl is None
            else fill.price - _signed(fill.exec_pnl, fill.position_side) / fill.qty
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
            pnl = _signed((fill.price - entry) * fill.qty, fill.position_side)
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

    def _place(self, ref: str, close: _Close, last_exec: datetime) -> tuple[datetime, int, str]:
        """Move `close` to `last_exec` in the order; the run is kept only for one appended last."""
        appended = close.slot is None and (not self._order or self._order[-1][0] <= last_exec)
        if close.slot is not None:
            del self._order[bisect_left(self._order, close.slot)]
        slot = (last_exec, next(self._seq), ref)
        close.last_exec, close.slot = last_exec, slot
        insort(self._order, slot)
        if appended and self._run is not None:
            self._run = self._run + 1 if close.bound < _ZERO else 0
        else:
            self._run = None
        return slot

    def _track(self, ref: str, close: _Close, was: bool) -> None:
        """Keep the awaiting index after `close` moved from awaiting (`was`) or not."""
        if (close.state in _AWAITING) == was:
            return
        count = self._awaiting_on.get(close.symbol, 0)
        if was:
            del self._awaiting[ref]
            self._awaiting_on[close.symbol] = count - 1
        else:
            self._awaiting[ref] = None
            self._awaiting_on[close.symbol] = count + 1

    def _rebound(self, close: _Close, bound: Decimal) -> None:
        self._realised += bound - close.bound
        close.bound = bound
        self._run = None

    def _book(
        self, fill: RiskFill, bound: Decimal, exact: Decimal, state: CloseState, now: datetime
    ) -> None:
        ref = fill.order_ref
        close = self._closes.get(ref)
        was = close is not None and close.state in _AWAITING
        if close is None:
            close = self._closes[ref] = _Close(
                fill.symbol, fill.position_side, state, now, fill.exec_time
            )
        else:  # booked before, so placed: it leaves its key's bucket before its qty moves
            bucket = self._by_key[(close.symbol, close.side, close.qty)]
            del bucket[bisect_left(bucket, cast("tuple[datetime, int, str]", close.slot))]
        close.qty += fill.qty
        close.exit_value += fill.price * fill.qty
        close.bound += bound
        self._realised += bound
        close.exact += exact
        close.booked_at = now
        if close.state is not CloseState.UNCONFIRMED:
            close.state = state
        self._track(ref, close, was)
        slot = self._place(ref, close, max(close.last_exec, fill.exec_time))
        insort(self._by_key.setdefault((close.symbol, close.side, close.qty), []), slot)

    def apply_venue_record(self, record: VenueClosedPnl, now: datetime) -> RecordOutcome:
        self._roll(now)
        if record.record_id in self._records:
            return RecordOutcome.DUPLICATE
        valid = _positive(record.qty, record.avg_exit_price, record.tick)
        if not (valid and _finite(record.pnl) and _aware(record.updated_at)):
            self._broken = True
            return RecordOutcome.INVALID
        if len(self._records) >= MAX_IDS:
            self._broken = True
            return RecordOutcome.OVERFLOW
        self._records.add(record.record_id)
        exit_at = _ticks(record.avg_exit_price, record.tick)
        lo = record.updated_at - MATCH_WINDOW
        bucket = self._by_key.get((record.symbol, record.position_side, record.qty), [])
        candidates: list[tuple[str, _Close]] = []
        n = bisect_left(bucket, lo, key=lambda slot: slot[0])
        while n < len(bucket) and bucket[n][0] <= record.updated_at:
            close = self._closes[bucket[n][2]]
            if _ticks(close.exit_value / close.qty, record.tick) == exit_at:
                candidates.append((bucket[n][2], close))
            n += 1
        if len(candidates) != 1:
            if record.updated_at not in self._key:
                return RecordOutcome.OUT_OF_DAY
            if record.pnl >= _ZERO:  # attributes to no close and carries nothing: not a close
                return RecordOutcome.UNMATCHED_BOOKED  # read, for the audit; books nothing (m11)
            ref = f"record:{record.record_id}"  # an OMS order reference has no colon (C-2.10)
            booked = _Close(record.symbol, record.position_side, CloseState.CONFIRMED, now, now)
            booked.bound = booked.exact = record.pnl  # a loss in full, never matched
            self._closes[ref] = booked
            self._realised += booked.bound
            self._place(ref, booked, record.updated_at)
            return RecordOutcome.UNMATCHED_BOOKED
        ref, close = candidates[0]
        was = close.state in _AWAITING
        if was:
            siblings = self._awaiting_on[close.symbol] > 1  # another close awaits on the symbol
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
        self._track(ref, close, was)
        return outcome

    def expire_records(self, now: datetime) -> tuple[str, ...]:
        """Closes with no record after `RECORD_TIMEOUT`: a held record's pnl, else their own figure,
        counts for the flatten."""
        self._roll(now)
        expired = [
            ref for ref in self._awaiting if now - self._closes[ref].booked_at >= RECORD_TIMEOUT
        ]
        for ref in expired:
            close = self._closes[ref]
            close.state = CloseState.TIMED_OUT
            self._track(ref, close, True)
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
        return bool(self._awaiting)

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
            pnl = _signed((mark - _entry(pos, side)) * pos.size, side) - fees
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
        if key == self._key:  # a key changes only at its end (`clock.py`): a new day
            return
        self._closes.clear()
        self._order.clear()
        self._by_key.clear()
        self._awaiting.clear()
        self._awaiting_on.clear()
        self._records.clear()
        self._seen_before, self._seen = self._seen, set()
        self._run, self._realised, self._peak = 0, _ZERO, _ZERO
        self._day_equity = self._equity
        self._key = key  # re-examine the queue
        early, self._early = self._early, []
        for fill, bound, exact, state in early:
            if fill.exec_time >= key.end:
                self._early.append((fill, bound, exact, state))
            elif fill.exec_time < key.start:  # before the key: prior day, as in `apply_fill`
                continue
            else:
                self._book(fill, bound, exact, state, now)
