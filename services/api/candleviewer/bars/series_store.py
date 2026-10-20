"""Recent bars of the series WS subscribers hold, for the `bars` snapshot (E12-T06, #2195, #399).

`23-ws-protocol.md` §6.1: a snapshot is up to `history` bars, the newest closed bars in index order
and the forming bar last; §8.2: a bar's key is `(generation, index)`. Pure `bars` (no `ws` import):
a WS snapshot source reads `latest` and `version`.

- **Sink** (a `BarSink` on the `EmitRouter`). Every close also goes to a per-series ring of the
  last `RECENT_CLOSES`, kept or not. For a kept series, `open`/`update` set the forming bar and a
  `close` appends and clears it. A close of a held bar (same key and open time: amended or
  repeated) replaces it in place; an amended close of a bar not held is ignored. A different bar
  at or below the newest index (a builder cold start restarts `index`) resets the series, and so
  does an emission in any other generation, lower or higher: there is one live builder per series,
  so its generation is never stale (§8.2 generation swap). Generations are opaque epochs: none is
  assumed, and a series has none until an emission or a read names one. Naming the first is not a
  swap; a change of generation is, and leaves the series not `hydrated`, so the new generation's
  rows are read (ADR-0033). The sink counts resets by cause (`bars_series_resets_total`) and gaps
  (below, `bars_series_gaps_total`); a hold's ring replay and a read's fold count neither. A
  re-close of a bar the ring holds takes that bar's slot there.
- **Hydration:** the first `ensure` starts a series from its ring, replayed by the sink rules,
  then reads the newest closed tape-built bars, bounded by `timeout_s`, and folds over them the
  bars it held (those newer than the rows, or replacing a bar they hold, and, when the read
  withheld rows, any below the newest row; each with its build mark), the closes seen just
  before and during the read that re-close a bar now held, and the
  forming bar. It keeps one generation: the one the series names (an emission's or an earlier
  read's), else the newest row's, else none yet. A read never replaces a named one: only an
  emission swaps it, so the WS publisher sees every generation swap the store makes. One
  read at a time per series: a concurrent `ensure` waits for it, and takes it over if its reader
  was cancelled, unless its own deadline had cut it, which makes it a failed read the waiters
  keep. A failed read (`bars_series_hydrate_failed_total`) leaves the series as it was;
  a degraded one (SR-E12-11: served, never final), one that skipped a row (`BarTail.skipped`:
  never merged, so the row's held bar is dropped; #3614) or a live swap leaves it not `hydrated`
  (a clean read withholds and skips none). An `ensure` reads a series that is not `hydrated`, or
  is `gapped`, again, but never sooner than its re-read interval after the last read:
  `retry_after_s`, more for a gap or misses (below); the heal driver's `refresh` (below) is the
  only other trigger, by the same rules. Without a reader, a series keeps only what the store has
  seen live.
- **Read bound (C-2.18, #2787 D2-G1):** a read takes one of `MAX_CONCURRENT_TAIL_READS` slots,
  shared by every store on the event loop, and gives it back however it ends. The wait for a
  slot is part of the read and counts toward `timeout_s`: a read that cannot start in time fails
  like a slow one (`bars_series_hydrate_failed_total`; an `ensure` at least its re-read interval
  later reads it again: `retry_after_s`, more for a gap or misses, below), and
  the wait never adds to the time a read can take. One read per series waits at most, so at
  most `MAX_SERIES` do, and `timeout_s` sheds them. A series waiting for a slot is a read in
  flight: its other `ensure` calls share it, and the closes seen meanwhile are kept for its
  fold. A read that finds every slot taken counts `bars_series_read_waits_total`, whether or
  not it then gets one.
- **Heal driver and repairs (#2787 D2-H1):** `due(now)` lists, earliest first, at most `limit`
  held series that are not complete (not `hydrated`, or `gapped`) and not reading, whose re-read
  interval has passed by `now` (the store's clock); `refresh` reads one as `ensure` would,
  without holding it. A completed read repairs a series (23 §7.4 `history_repair`) when it adds
  or replaces a bar the series serves and loses none it held. A held bar below the oldest bar the
  series keeps is lost too, unless no read could hold it there: it opened before the read's
  start (`BarTail.since_us`), the series is full, so the 1 000-bar cap leaves it deeper than any
  `history`, or the read hit its row limit (`BarTail.fetched` reached `MAX_HISTORY`: a skipped
  row left the series short of full, but the limit, not `since_us`, ended the window). Whoever
  started that read, the store then calls the repair hook (`on_repair`, set once: `create_app`
  sets it, with `bars_enabled`, to the WS publisher's `history_repair`) with
  `min_history`, the depth of the newest bar it added or replaced, newest first and the forming
  bar 1, as `latest` counts `history`. A depth it cannot count (the walk raised, or gave less
  than 1) goes out as 1, counted (`bars_series_repair_failed_total{reason="depth"}`) and logged
  at error: extra snaps, never a skipped repair. A hook that raises is counted (`reason="hook"`)
  and logged, and the read stands. The call is the last step of the read that changes state,
  after its fold and bookkeeping: the clock is read before the fold and the logs come after the
  call, so nothing between them awaits or can raise. That keeps the call cancellation-safe (no
  cancellation can land between the fold and the call) and `min_history` exact (until the call,
  older bars only move away from the newest, barring a reset, so a late call could only reach
  more subscribers). A first read reaches nobody: its holders take their first `snap` after it.
  `bars_series_incomplete_in_use` counts the held series that are not complete, at scrape time.
- **Holds and bounds (C-2.18):** `ensure` returns a `Hold`, released once. A hold collected
  unreleased is released as of its collection: its finalizer only queues it, and the next
  `ensure` applies the queue before its sweep. An unheld series is kept `release_grace_s` (the
  builder's grace, US-MKT-005) from its latest release, explicit or queued, so a quick
  resubscribe finds it as the sink kept it and, while it is `hydrated` and not `gapped`, reads
  nothing (BR-38); the next `ensure` sweeps the expired. A hold that never reached its lease
  (refused, or its `ensure` failed or was cancelled) is released with no grace of its own
  (`release(grace=False)`): it frees its slot at once, or when an earlier release's grace ends.
  At most `MAX_HISTORY` closed bars per series and `MAX_SERIES`
  series kept, held or in grace (the process-wide spec cap); rings for at most `MAX_SERIES`
  series, the least recently closed dropped first; at most `MAX_HISTORY` closes kept for a read
  in flight, the oldest shed first; at most `MAX_GAP_RANGES` gap ranges logged per series (4 096
  at `MAX_SERIES`). The sink keeps an expired series current until that sweep. Memory: about 5 KB
  a close (measured), so 5 MB a series, 2.5 GB at `MAX_SERIES`, and 41 MB of rings; the logged
  ranges are under 2 KB a series.
- **E12-S12 notes:** the generation rule assumes one live emitter per series (a rebuild must emit
  through its own router), and `CAP_NAME` copies `SpecLeases`' literal until `leases` exports it.
- **`version`** comes from one store-wide counter and moves on every change: a cache key that
  stays safe across a release and a new hold.

Gaps: the closes emitted just before the hold that the writer had not landed yet come from the
ring (the last `RECENT_CLOSES`). A live close that skips indexes past the rows marks the series
`gapped` (`bars_series_gap`), and so does a first close above index 0 of a series read clean and
empty, if its bar opened inside that read's window (#2787 D2-H1a; the bars below one that opened
before it, as a restored builder's can after a long downtime, lie outside every read), but none
does after a read the table-row bound started later than its window (`BarTail.bounded`, D2-M4):
bars below its start may exist, so a writer lagging at that junction goes unflagged (the write
path's counters show it, `bar_emit_sink_errors_total` and `bars_write_failed_total`). The read
being folded is the judge (#3660): with no row of the series' generation, a clean one checks the
first bar it finds held, whatever came before it (a close from the ring, one during the read, or
one after a failed or degraded read or a live swap), and one not clean checks none. A restart
that empties a series read clean with rows meets the same check, with that read's window, so its
first close above 0 counts a gap: one count, one warning and one read, harmless (#3660 (b)).
Not after a bounded read (D2-M4): bars below its start may exist. An
`ensure` re-reads it, no sooner than its re-read interval after the last read. The bars it holds
newer than the stored rows survive the re-read, and so do, when the read withholds rows
(SR-E12-11), the ones it holds below the newest row (D2-H1b). A gap that stays (D2-H2): a read
that finds the series gapped and leaves it so doubles its re-read interval, from `retry_after_s`
up to `MAX_GAP_BACKOFF` times it (160 s at 5 s), and counts `bars_series_gap_rereads_total`,
unless a live reset or swap landed during it (the gap it began on is gone: `_Series.resets`).
`bars_series_gap` is logged once per `(from_index, to_index)`: a series keeps the ranges logged,
at most `MAX_GAP_RANGES` (the oldest forgotten first). A read that heals the series, or a live
reset or swap, forgets them and brings the interval back to `retry_after_s`; a gap seen live (a
close past the newest bar: a hole no read has looked at yet) brings the interval back too, but a
re-read in flight that leaves the series gapped then doubles it once. A miss (#2787 P4b) is a
completed read that is not clean: it fails, or withholds or skips rows (#3614: one that keeps
skipping a malformed row backs off to 160 s); a read whose deadline passes before its reader has
unwound is a failed read, whoever cancelled it first (its waiters keep that result); one that
unwinds before its deadline sets none. Misses in a row ask for their own interval:
`retry_after_s` after the first, doubled by each later one up to `MAX_GAP_BACKOFF` times it; the
next read waits out the longer of the two, `retry_after_s * max(backoff, missed)`. A clean read
ends the streak, and so does a gap seen live after misses that completed (so a read may
fill the new hole), but not after failed ones, nor does a live reset or swap. Only a streak's
first miss logs `bars_series_hydrate_failed` or `_degraded`: the failure counter counts each
failure, and the reader logs and counts each row it withholds. A read that skips a row logs
`bars_series_rows_skipped` every time, and the reader `bars_tail_rows_malformed` for a malformed
one: one a re-read interval at most, so one in 160 s once the streak has grown. A read that is not
clean and finds no row of the generation judges no hole before its first held bar, so it can end
the series not gapped, which forgets the logged ranges as a heal does: the next clean read logs
that hole again. A gap a fold flags is logged, never counted: `bars_series_gaps_total` counts gaps
seen live, since every re-read meets the same held closes and a count there would also restart the
gap interval and end a miss streak, as a gap seen live does.

Not covered: the forming bar is unknown until the next `open` or `update` (builders expose none);
a read that loses a held bar repairs nothing, even if it adds bars (§7.4); a hole inside the
stored rows with no bar held for it is not flagged (`gapped` stays false): one the writer never
landed leaves the series complete, and a row skipped or withheld leaves it not `hydrated`, so it is
read again; a jump is seen on a close only; a series with more holes than `MAX_GAP_RANGES` logs
each again on every re-read, which finds them oldest first; a series freed after its grace starts
afresh when held again (nothing logged, `retry_after_s`).
"""

from __future__ import annotations

import asyncio
import functools
import heapq
import itertools
import time
import weakref
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, NamedTuple

import structlog

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.errors import SpecCapExceeded
from candleviewer.bars.leases import CAP_GLOBAL, GRACE_US, Key
from candleviewer.bars.limits import MAX_CONCURRENT_TAIL_READS, MAX_TAIL, QUERY_TIMEOUT_S
from candleviewer.bars.metrics import (
    bars_series_gap_rereads_total,
    bars_series_gaps_total,
    bars_series_hydrate_failed_total,
    bars_series_incomplete_in_use,
    bars_series_read_waits_total,
    bars_series_repair_failed_total,
    bars_series_resets_total,
    bars_spec_cap_rejected_total,
)
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail, degrade_reason

#: The WS `history` cap (`23-ws-protocol.md` §6.1).
MAX_HISTORY: Final = MAX_TAIL
MAX_SERIES: Final = CAP_GLOBAL
#: `SpecLeases`' name for the process-wide cap: one `subscription_limit` wording.
CAP_NAME: Final = "process-wide"
#: Closes kept per series, held or not, for a new hold to start from.
RECENT_CLOSES: Final = 16
#: A series is never read again sooner than this after its last completed read.
RETRY_AFTER_S: Final = 5.0
#: A gap or misses that stay double a series' re-read interval up to this many `retry_after_s`.
MAX_GAP_BACKOFF: Final = 32
#: Gap ranges a series logs once each (`bars_series_gap`), the oldest forgotten first.
MAX_GAP_RANGES: Final = 8
#: A released series is kept this long: the builder's release grace (US-MKT-005).
RELEASE_GRACE_S: Final = GRACE_US / 1_000_000

#: `(symbol, spec, limit) -> BarTail`: `BarReader.read_tail`.
TailRead = Callable[[str, BarSpec, int], Awaitable[BarTail]]
#: `(symbol, spec, min_history)` after a read repaired a series (module docstring): the WS
#: publisher's `history_repair`, whose result the store ignores. Synchronous: it never awaits.
RepairHook = Callable[[str, BarSpec, int], object]
#: A close as emitted, with its generation.
Close = tuple[BarUpdate, int]


class _ReadSlots:
    """The process-wide bound on concurrent tail reads: `size` slots, shared by every store.

    A `Semaphore` binds to the loop where it first has to wait, so it is made on the running
    loop, when first needed, and made again if that loop changes (a test's, a restarted app's):
    none is made at import or used on another loop. The backend runs one loop, so the bound holds;
    two loops reading at once would keep replacing each other's semaphore, and it would hold on
    neither."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._held: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None

    def get(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        held = self._held
        if held is None or held[0] is not loop:
            held = self._held = (loop, asyncio.Semaphore(self._size))
        return held[1]


_READ_SLOTS: Final = _ReadSlots(MAX_CONCURRENT_TAIL_READS)


class Latest(NamedTuple):
    """`latest`: the series' change counter and generation (None before an emission or a read
    names one), its closed bars in index order, the forming bar, and the lowest `build_version`
    among those bars when below the running code (None: all current; §6.1 `meta.build_version`)."""

    version: int
    generation: int | None
    closed: list[Bar]
    forming: Bar | None
    oldest_build: int | None


class Hold:
    """One `ensure`'s claim on a series. `release` drops it once: a second call is a no-op, so a
    double release never drops another caller's hold. A hold collected unreleased runs `lost`
    once instead (`weakref.finalize`, which `release` detaches). `lost` is required: a collection
    may run on any thread, so the store's only queues the release for its loop."""

    __slots__ = ("__weakref__", "_drop", "_finalizer", "spec_hash", "symbol")

    def __init__(
        self,
        symbol: str,
        spec_hash: str,
        drop: Callable[[bool], None],
        lost: Callable[[], None],
    ) -> None:
        self.symbol, self.spec_hash = symbol, spec_hash
        self._drop: Callable[[bool], None] | None = drop
        self._finalizer = weakref.finalize(self, lost)

    def release(self, *, grace: bool = True) -> None:
        """`grace=False`: the hold never reached its lease, so it starts no grace of its own."""
        self._finalizer.detach()
        drop, self._drop = self._drop, None
        if drop is not None:
            drop(grace)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(slots=True)
class _Series:
    version: int
    #: The spec its first `ensure` named: with the key's symbol, what a `refresh` reads.
    spec: BarSpec
    refs: int = 0
    generation: int | None = None  # set by the first emission, or by a read
    closed: OrderedDict[int, Bar] = field(default_factory=OrderedDict)  # index -> bar
    forming: Bar | None = None
    #: Holds the stored tail a read took: it neither failed nor was degraded, skipped no row
    #: (#3614), and no swap followed. Set by the fold, before the held bars (#3660).
    hydrated: bool = False
    #: The start (µs, `BarTail.since_us`) of the last read folded, set with `hydrated`
    #: as the fold starts, so a clean read's while `hydrated`: holding no bar, the series takes a
    #: close of a bar that opened before it as no gap (D2-H1a), the held ones that fold applies
    #: included (#3660).
    since_us: int = 0
    #: That read was `BarTail.bounded` (D2-M4), set with `since_us`: bars of the series may lie
    #: below `since_us`, so holding no bar, the series takes no close as a gap (`_junction`).
    bounded: bool = False
    #: A live swap since the read in flight began (set by `_live`, cleared as a read starts).
    swapped: bool = False
    #: Waiters keep the latest read's result: True after a success (a skipping read too, #3614), a
    #: failure or a timeout, False after a degraded read or a cancellation, unless its own deadline
    #: had cut it, which makes it a failed read the waiters keep.
    attempted: bool = False
    #: Store-clock time the last read completed, or its deadline passed before its reader had
    #: unwound, whoever cancelled it first (one that unwinds before its deadline sets none): the
    #: next starts `retry_after_s * max(backoff, missed)` after it, no sooner.
    read_at: float = float("-inf")
    #: A live close skipped indexes past the stored rows: the next `ensure` re-reads.
    gapped: bool = False
    #: A gap's re-read interval in `retry_after_s`: doubled, up to `MAX_GAP_BACKOFF`, by a read that
    #: finds the series gapped and leaves it so; 1 again on a gap seen live, and by `_forget_gaps`.
    backoff: int = 1
    #: Bumped by `_forget_gaps` (a heal, a live reset or swap): a read that sees it move did not
    #: re-read the gap it began on, so it neither doubles the interval nor counts (D2-H2).
    resets: int = 0
    #: Misses in a row (module docstring), as the re-read interval in `retry_after_s` they ask for:
    #: 1 after the first, doubled by each later one up to `MAX_GAP_BACKOFF`; 0 after a clean read.
    missed: int = 0
    #: The streak's last miss failed (else it withheld or skipped rows): a gap seen live keeps it.
    failing: bool = False
    #: The gap ranges `(from_index, to_index)` logged since it last healed, reset or swapped, each
    #: once (D2-H2); the oldest is forgotten past `MAX_GAP_RANGES`.
    logged: deque[tuple[int, int]] = field(default_factory=lambda: deque(maxlen=MAX_GAP_RANGES))
    #: Store-clock time a released series is freed at (None while held).
    expires_at: float | None = None
    #: Store-clock time of its latest release, explicit or queued: its grace counts from it.
    released_at: float = float("-inf")
    #: index -> `build_version` of the held bars built below the running code: a read sets its
    #: rows', a re-read carries each held bar's own, and a live re-close, the bar leaving the
    #: window or a reset drops one. Its indexes are always among `closed`'s.
    stale: dict[int, int] = field(default_factory=dict)
    #: Closes seen while a read is in flight (the oldest shed past `MAX_HISTORY`), folded over
    #: its rows.
    replay: deque[Close] | None = None
    #: Set when the read in flight ends, however it ends; a fresh one per read.
    ready: asyncio.Event = field(default_factory=asyncio.Event)


def _clear(s: _Series) -> None:
    s.closed.clear()
    s.stale.clear()
    s.forming = None


def _holds(s: _Series, bar: Bar) -> bool:
    held = s.closed.get(bar.index)
    return held is not None and held.open_time == bar.open_time


def _forget_gaps(s: _Series) -> None:
    """Healed, or reset or swapped live: a gap seen from now on logs and is read afresh (D2-H2),
    and a read in flight does not back off (`resets`)."""
    s.logged.clear()
    s.backoff = 1
    s.resets += 1


def _incomplete(s: _Series) -> bool:
    """Not `hydrated`, or `gapped`: read again once its re-read interval has passed."""
    return not s.hydrated or s.gapped


def _miss(s: _Series, *, failed: bool) -> bool:
    """A completed read failed, withheld or skipped rows: the streak's interval grows
    (`_Series.missed`). True for the streak's first read, the one that logs."""
    first, s.failing = not s.missed, failed
    s.missed = 1 if first else min(2 * s.missed, MAX_GAP_BACKOFF)
    return first


def _repair_depth(
    s: _Series, before: dict[int, Bar], since_us: int, limited: bool = False
) -> int | None:
    """§7.4 `min_history` of a fold that turned `before` (index -> bar) into `s`: the depth of the
    newest bar it added or replaced among those `s` serves, newest first and the forming bar 1, as
    `latest` counts `history`. None when it added or replaced none, or lost a bar `s` held (no
    repair, §7.4). A held bar below `s`'s oldest is not lost when no read could hold it there: it
    opened before the read's start (`since_us`), or `s` is full, so the 1 000-bar cap leaves it
    deeper than any `history`, or the read hit its row limit (`limited`: its rows end before its
    window does, as a full series' do). Exact for the window, the cap and the row limit."""
    forming = int(s.forming is not None)
    served = itertools.islice(reversed(s.closed.values()), MAX_HISTORY - forming)
    for depth, bar in enumerate(served, 1 + forming):
        was = before.get(bar.index)
        if was is not bar and was != bar:  # added or replaced: a bar kept keeps its object
            oldest, full = next(iter(s.closed)), limited or len(s.closed) >= MAX_HISTORY
            lost = any(  # gone, and not below `oldest` out of the read's reach
                i not in s.closed and (i > oldest or (b.open_time >= since_us and not full))
                for i, b in before.items()
            )
            return None if lost else depth
    return None


def _counted_depth(
    s: _Series, before: dict[int, Bar], since_us: int, limited: bool
) -> tuple[int | None, Exception | int | None]:
    """`_repair_depth`, guarded, never raising: a depth it cannot count (it raised, or came out
    below 1) is 1, never a skipped repair (P11's caller contract: extra snaps, never a miss), and
    counted (`reason="depth"`). The second item is the fault, which `_hydrate` logs after the
    hook: the exception, or the depth below 1."""
    try:
        depth = _repair_depth(s, before, since_us, limited)
    except Exception as exc:  # broad on purpose: a repair whose depth fails still goes out
        bars_series_repair_failed_total.labels(reason="depth").inc()
        return 1, exc
    if depth is not None and depth < 1:
        bars_series_repair_failed_total.labels(reason="depth").inc()
        return 1, depth
    return depth, None


def _call_repair(hook: RepairHook, symbol: str, spec: BarSpec, depth: int) -> None:
    """Call the repair hook. One that raises never fails the read: counted (`reason="hook"`) and
    logged. A `CancelledError` is no `Exception`, so it is raised, never swallowed."""
    try:
        hook(symbol, spec, depth)
    except Exception as exc:  # broad on purpose: the read stands, whatever the hook did
        bars_series_repair_failed_total.labels(reason="hook").inc()
        _log().warning(
            "bars_series_repair_failed", spec_hash=spec.spec_hash, symbol=symbol,
            min_history=depth, error_type=type(exc).__name__, error=str(exc)[:120],
        )  # fmt: skip


def _junction(s: _Series, bar: Bar) -> bool:
    """D2-H1a on a series holding no bar: a close above index 0 is a gap after a clean read it
    opened inside, unless the table-row bound started that read (D2-M4): bars below its start
    may exist."""
    return s.hydrated and not s.bounded and bar.open_time >= s.since_us


def _apply(s: _Series, u: BarUpdate, *, gaps: bool = True, count: bool = False) -> bool:
    """Fold one emission of `s.generation` into `s` (module docstring); False when it changes
    nothing. With `gaps`, a close that skips indexes past the newest one (past none, so from
    index 0, on a series that held none after a clean read, if its bar opened inside that read's
    window, unless the row bound started that read: `_junction`) marks `s` gapped. Only the sink
    passes `count`: a hold's ring replay and a read's fold count no reset or gap."""
    bar, i = u.bar, u.bar.index
    last = next(reversed(s.closed), -1)
    if u.kind != "close":
        if i <= last:
            _clear(s)  # a bar at or below the newest close re-opened: restarted
            if count:
                bars_series_resets_total.labels(reason="restart").inc()
                _forget_gaps(s)  # the gaps logged were the old run's
        s.forming = bar
        return True
    if _holds(s, bar):
        s.closed[i] = bar  # the same bar closed again (amended or repeated): in place
        s.stale.pop(i, None)  # re-closed by the running code
        return True
    if i <= last or u.amended:  # an amended close is never a bar's first sight (#2666 r2)
        if u.amended:
            return False  # an amended close of a bar this window does not hold
        _clear(s)  # another bar at or below the newest index: the builder restarted
        if count:
            bars_series_resets_total.labels(reason="restart").inc()
            _forget_gaps(s)
    elif gaps and (s.closed or _junction(s, bar)) and i > last + 1:
        # None held after a clean read whose window this bar opened in (the last read folded: this
        # fold's, if one runs): it found no row (D2-H1a, #3660), or a restart emptied the series.
        s.gapped = True  # emitted before the hold and not stored yet, or lost: re-read
        if count:
            bars_series_gaps_total.inc()
            s.backoff = 1  # a new hole, seen live: read at `retry_after_s` again (D2-H2)
            if not s.failing:  # and a degraded read may fill it: their streak ends (#2787 P4b)
                s.missed = 0
        gap = (last + 1, i - 1)
        if gap not in s.logged:  # once per range: a re-read finds it again (D2-H2)
            s.logged.append(gap)
            _log().warning(
                "bars_series_gap", spec_hash=bar.spec_hash, symbol=bar.symbol,
                from_index=gap[0], to_index=gap[1],
            )  # fmt: skip
    s.closed[i] = bar
    if len(s.closed) > MAX_HISTORY:
        s.stale.pop(s.closed.popitem(last=False)[0], None)  # a mark leaves with its bar
    if s.forming is not None and s.forming.index <= i:
        s.forming = None
    return True


def _live(s: _Series, u: BarUpdate, generation: int, *, count: bool = False) -> bool:
    """An emission (`count`: the sink's, not a hold's ring replay). One live builder per series:
    any other generation, lower or higher, is the series' new one (§8.2 generation swap), and the
    first emission names it."""
    if generation != s.generation:
        if s.generation is not None:  # naming the first one is not a swap (23 §8.2)
            s.hydrated, s.swapped = False, True  # its rows are read again (ADR-0033)
            _forget_gaps(s)  # the gaps logged were the old generation's
            if count:
                bars_series_resets_total.labels(reason="generation_swap").inc()
        _clear(s)
        s.generation = generation
        _apply(s, u, count=count)
        return True  # the reset changed the series, even if the emission itself is ignored
    return _apply(s, u, count=count)


def _update(kind: str, bar: Bar) -> BarUpdate:
    return BarUpdate.model_construct(kind=kind, bar=bar, amended=False)


def _reclose(ring: deque[Close], close: Close) -> bool:
    """Put a re-close (amended or repeated) in its bar's slot, as a plain close so a new hold
    takes it as that bar's close; False when the ring lacks the bar (same generation, index and
    open time). Scans only a close at or below the ring's newest index."""
    bar, gen = close[0].bar, close[1]
    if bar.index > ring[-1][0].bar.index:
        return False
    for i in range(len(ring) - 1, -1, -1):
        held, g = ring[i]
        if g == gen and held.bar.index == bar.index and held.bar.open_time == bar.open_time:
            ring[i] = (_update("close", bar), gen)
            return True
    return False


class SeriesStore:
    """The `BarSink` and recent-bars store described in the module docstring."""

    name = "series_store"

    def __init__(
        self,
        tail: TailRead | None = None,
        *,
        timeout_s: float = QUERY_TIMEOUT_S,
        retry_after_s: float = RETRY_AFTER_S,
        release_grace_s: float = RELEASE_GRACE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tail = tail
        self._timeout_s, self._retry_after_s = timeout_s, retry_after_s
        self._grace_s, self._clock = release_grace_s, clock
        self._series: dict[Key, _Series] = {}
        self._recent: OrderedDict[Key, deque[Close]] = OrderedDict()
        self._versions = itertools.count(1)
        #: Holds collected unreleased, with the time: one entry per hold at most (`_lose`).
        self._lost: deque[tuple[_Series, float]] = deque()
        self._on_repair: RepairHook | None = None
        ref = weakref.ref(self)  # the gauge keeps no store alive

        def incomplete() -> float:  # on the scrape's thread; a store collected reads 0
            store = ref()
            return 0.0 if store is None else float(store.incomplete_count())

        bars_series_incomplete_in_use.set_function(incomplete)  # the store built last (one app)

    def on_repair(self, hook: RepairHook) -> None:
        """Set the repair hook (module docstring), once: the WS publisher's `history_repair`,
        which `create_app` sets with `bars_enabled` (#2787 D2-H1). A second call raises
        `RuntimeError`."""
        if self._on_repair is not None:
            raise RuntimeError("the series store's repair hook is set already")
        self._on_repair = hook

    def now(self) -> float:
        """The store's clock: the `now` the heal driver gives `due`."""
        return self._clock()

    @property
    def timeout_s(self) -> float:
        """A read's deadline, its wait for a slot included. A cut read can outlive it by its
        reader's cleanup (`HEAL_REFRESH_MARGIN_S`); it is a failed read even if cancelled again."""
        return self._timeout_s

    def series_count(self) -> int:
        """Series kept: held, or released and in their grace (an expired one until the next
        `ensure` sweeps it)."""
        return len(self._series)

    def incomplete_count(self) -> int:
        """Held series that are not complete: not `hydrated`, or `gapped`. The gauge
        `bars_series_incomplete_in_use` reads it at scrape time, off the loop, so it counts over a
        copy of the series taken in one step (`tuple`, one C call under the GIL): the loop never
        resizes the map under it. O(series); nothing on the emit path."""
        return sum(1 for s in tuple(self._series.values()) if s.refs and _incomplete(s))

    def due(self, now: float, *, limit: int = MAX_CONCURRENT_TAIL_READS) -> list[Key]:
        """The heal driver's list (module docstring): at most `limit` held series that are not
        complete and not reading, whose re-read interval has passed by `now` (the store's clock),
        the earliest due first. Pure and synchronous: no I/O, no await, nothing changed. Empty
        without a reader. O(series).

        For the driver (#2787 P4b): run fewer `refresh` calls at once than there are read slots
        (`MAX_CONCURRENT_TAIL_READS`), so a subscriber's first read still finds one, and never
        time out a `refresh` sooner than the store's `timeout_s`: a read that unwinds before its
        deadline sets no next read time, so the series would be due again at once."""
        if self._tail is None:
            return []
        due = [(self._next_read(s), k) for k, s in self._series.items() if self._due(s, now)]
        return [k for _, k in heapq.nsmallest(limit, due)]

    async def refresh(self, symbol: str, spec_hash: str) -> bool:
        """The heal driver's read: reads the series now if `due` would list it, by `ensure`'s
        rules (a slot, `timeout_s`, the re-read interval, one read per series), without holding
        it. True when the read repaired the series (and called the repair hook, if set). False
        when it read nothing (not held, reading, complete or not due), or the read changed
        nothing, lost a bar, or failed: a failure takes the store's failure path (counted and
        logged), never raised. A cancellation is raised. A series that becomes complete is read
        once; one that stays incomplete is due again each re-read interval (`due` has the
        driver's two rules)."""
        s = self._series.get((symbol, spec_hash))
        if s is None or not self._due(s, self._clock()):
            return False
        return await self._hydrate(s, symbol, s.spec)

    def _next_read(self, s: _Series) -> float:
        """Store-clock time the next read of `s` is due: its re-read interval after the last, the
        longer of a gap's and a miss streak's."""
        return s.read_at + self._retry_after_s * max(s.backoff, s.missed)

    def _due(self, s: _Series, now: float) -> bool:
        """For the heal driver: `s` is held, not reading, not complete, and a read of it is due."""
        return bool(s.refs) and s.replay is None and _incomplete(s) and now >= self._next_read(s)

    async def emit(self, emission: BarEmission) -> None:
        """`BarSink`: O(1) per update of a series the store does not keep; never awaits."""
        h, gen = emission.spec.spec_hash, emission.generation
        for u in emission.updates:
            key = (u.bar.symbol, h)
            s = self._series.get(key)
            if u.kind == "close":
                self._remember(key, (u, gen))
                if s is not None and s.replay is not None:
                    s.replay.append((u, gen))
            if s is not None and _live(s, u, gen, count=True):
                s.version = next(self._versions)

    def _remember(self, key: Key, close: Close) -> None:
        ring = self._recent.get(key)
        if ring is None:
            if len(self._recent) >= MAX_SERIES:
                self._recent.popitem(last=False)  # the series that closed a bar longest ago
            ring = self._recent[key] = deque(maxlen=RECENT_CLOSES)
        else:
            self._recent.move_to_end(key)
            if _reclose(ring, close):
                return
        ring.append(close)

    async def ensure(self, symbol: str, spec: BarSpec) -> Hold:
        """Keep the series and bring it up to date (module docstring); release the `Hold` when
        done with it. Raises `SpecCapExceeded` (counted, nothing held) when `MAX_SERIES` series
        are kept; a failed or cancelled `ensure` holds nothing either and starts no grace."""
        s = self._keep((symbol, spec.spec_hash), spec)
        hold = Hold(symbol, spec.spec_hash, functools.partial(self._release, s, None),
                    functools.partial(self._lose, s))  # fmt: skip
        try:
            await self._settle(s, symbol, spec)
        except BaseException:
            hold.release(grace=False)  # never returned: no lease can follow, so no grace
            raise
        return hold

    def _keep(self, key: Key, spec: BarSpec) -> _Series:
        while self._lost:  # holds collected unreleased: released as of their collection
            self._release(*self._lost.popleft())
        now = self._clock()
        expired = [
            k for k, s in self._series.items() if s.expires_at is not None and s.expires_at <= now
        ]
        for k in expired:  # an expired series no longer counts toward the cap
            del self._series[k]
        s = self._series.get(key)
        if s is None:
            if len(self._series) >= MAX_SERIES:
                bars_spec_cap_rejected_total.labels(reason=CAP_NAME).inc()
                raise SpecCapExceeded(CAP_NAME, MAX_SERIES, len(self._series))
            s = self._series[key] = _Series(next(self._versions), spec)
            for u, gen in self._recent.get(key, ()):
                _live(s, u, gen)  # the closes seen before this hold, by the sink rules
        s.refs += 1
        s.expires_at = None
        return s

    def _release(self, s: _Series, at: float | None = None, grace: bool = True) -> None:
        """Drop one hold, released at `at` (None: now). Unheld, `s` is kept `release_grace_s`
        from its latest release; `grace=False` (a lease never reached) is no release of its own."""
        if grace:
            s.released_at = max(s.released_at, self._clock() if at is None else at)
        s.refs -= 1
        if not s.refs:
            s.expires_at = s.released_at + self._grace_s

    def _lose(self, s: _Series) -> None:
        """A `Hold`'s finalizer: O(1), never awaits. A collection can run on any thread, so it
        only queues the release (a thread-safe `deque.append`); `_keep` applies it on the loop."""
        self._lost.append((s, self._clock()))

    def version(self, symbol: str, spec_hash: str) -> int:
        """The series' change counter; 0 while the store does not keep it."""
        s = self._series.get((symbol, spec_hash))
        return 0 if s is None else s.version

    def hydrated(self, symbol: str, spec_hash: str) -> bool:
        """True once a read took the series' stored tail (False: live bars only, or a degraded
        read's, or one that skipped a row, or one a live swap followed)."""
        s = self._series.get((symbol, spec_hash))
        return s is not None and s.hydrated

    def gapped(self, symbol: str, spec_hash: str) -> bool:
        """True when a live close skipped indexes past the stored rows (the next `ensure`
        re-reads the series)."""
        s = self._series.get((symbol, spec_hash))
        return s is not None and s.gapped

    def latest(self, symbol: str, spec_hash: str, history: int) -> Latest | None:
        """At most `history` bars in all, the forming bar included: O(history). None while the
        store does not keep the series."""
        s = self._series.get((symbol, spec_hash))
        if s is None:
            return None
        forming = s.forming if history > 0 else None
        n = max(0, history - (forming is not None))
        closed = list(itertools.islice(reversed(s.closed.values()), n))
        closed.reverse()
        oldest = min((s.stale[b.index] for b in closed if b.index in s.stale), default=None)
        return Latest(s.version, s.generation, closed, forming, oldest)

    async def _settle(self, s: _Series, symbol: str, spec: BarSpec) -> None:
        """Wait for the read in flight (its own `timeout_s` bounds it), then read when one is
        due: the first, a cancelled reader's, or one a re-read interval (`retry_after_s`, more for
        a gap or misses) after the last read of a series not hydrated or gapped. A waiter keeps a
        completed read's result. A cancelled read is not gated, so its waiters never stay
        live-only (SR-E12-07 bounds the churn), unless its own deadline had cut it, which makes
        it a failed read the waiters keep: a read whose deadline passes before its reader has
        unwound is a failed read, whoever cancelled it first."""
        woke = False
        while s.replay is not None:  # one read at a time per series
            await s.ready.wait()
            await asyncio.sleep(0)  # were `ready` ever stale, this spins one ensure, not the loop
            woke = True
        if woke and s.attempted:
            return
        if _incomplete(s) and self._clock() >= self._next_read(s):
            await self._hydrate(s, symbol, spec)

    async def _hydrate(self, s: _Series, symbol: str, spec: BarSpec) -> bool:
        """One read, its fresh `ready` set however it ends. Its replay starts from the ring (the
        closes seen just before it) and takes every close seen during it, in emission order,
        the wait for a read slot included, which counts toward `timeout_s`. A read that finds
        the series gapped and leaves it so doubles its re-read interval, unless a live reset or
        swap landed during it (D2-H2). True when it repaired the series: it then calls the repair
        hook, the last step of the read that changes state (module docstring)."""
        if self._tail is None:
            return False
        ready = s.ready = asyncio.Event()
        ring = self._recent.get((symbol, spec.spec_hash), ())
        s.replay, s.attempted, s.swapped = deque(ring, maxlen=MAX_HISTORY), False, False
        gapped = s.gapped  # as it starts: a hole that shows during it is no re-read's
        resets_at_start = s.resets  # nor is a gap after a live reset or swap during it (D2-H2)
        depth: int | None = None  # the repair's `min_history`
        fault: Exception | int | None = None  # a depth not counted, logged after the hook
        dropped = skipped = 0  # rows withheld (a streak's first miss) and skipped: logged last
        deadline = asyncio.timeout(self._timeout_s)  # the wait for a slot counts toward it
        try:
            async with deadline:
                slots = _READ_SLOTS.get()
                if slots.locked():  # every slot is taken, or reads are queued for one: it waits
                    bars_series_read_waits_total.inc()
                async with slots:  # given back however the read ends
                    tail = await self._tail(symbol, spec, MAX_HISTORY)
        except asyncio.CancelledError:
            if deadline.expired():  # it passed before the reader unwound, whoever cancelled first
                self._failed(s, symbol, spec, TimeoutError())  # a failed read all the same
            raise
        except Exception as exc:  # broad on purpose: any read failure leaves the series as it was
            self._failed(s, symbol, spec, exc)
        else:
            s.read_at = self._clock()  # pre-fold: nothing after the fold can raise until the hook
            before = dict(s.closed)  # what `s` served: a repair is judged against it
            self._fold(s, tail)  # it sets `hydrated`, `since_us` and `bounded` (#3660, D2-M4)
            depth, fault = _counted_depth(s, before, tail.since_us, tail.fetched >= MAX_HISTORY)
            s.attempted = not tail.integrity_degraded
            if not s.gapped:  # healed, or never gapped
                _forget_gaps(s)
            elif gapped and s.resets == resets_at_start:  # a re-read, still gapped: back off
                s.backoff = min(2 * s.backoff, MAX_GAP_BACKOFF)
                bars_series_gap_rereads_total.inc()
            skipped = tail.skipped
            if not (tail.integrity_degraded or skipped):
                s.missed = 0  # a clean read ends a miss streak
            elif _miss(s, failed=False):  # the reader logs and counts each row it withholds
                dropped = tail.dropped
        finally:
            s.replay = None
            ready.set()
        if depth is not None and self._on_repair is not None:  # no await since the fold
            _call_repair(self._on_repair, symbol, spec, depth)
        if isinstance(fault, Exception):
            _log().error(
                "bars_series_repair_depth_failed", spec_hash=spec.spec_hash, symbol=symbol,
                error_type=type(fault).__name__, error=str(fault)[:120],
            )  # fmt: skip
        elif fault is not None:
            _log().error(
                "bars_series_repair_depth_failed", spec_hash=spec.spec_hash, symbol=symbol,
                depth=fault,
            )  # fmt: skip
        if dropped:  # SR-E12-11: its bars are served, never as final
            _log().warning(
                "bars_series_hydrate_degraded", spec_hash=spec.spec_hash, symbol=symbol,
                dropped=dropped,
            )  # fmt: skip
        if skipped:
            _log().info(
                "bars_series_rows_skipped", spec_hash=spec.spec_hash, symbol=symbol,
                skipped=skipped,
            )  # fmt: skip
        return depth is not None

    def _failed(self, s: _Series, symbol: str, spec: BarSpec, exc: Exception) -> None:
        """A completed read failed, or its own deadline cut it: the series stays as it was, and
        its next read waits out the miss streak's interval."""
        s.read_at, s.attempted = self._clock(), True  # a completed read, or one its deadline cut
        bars_series_hydrate_failed_total.labels(reason=degrade_reason(exc)).inc()
        if _miss(s, failed=True):  # a streak's first failure logs; the counter counts each
            _log().warning(
                "bars_series_hydrate_failed", spec_hash=spec.spec_hash, symbol=symbol,
                error_type=type(exc).__name__, error=str(exc)[:120],
            )  # fmt: skip

    def _fold(self, s: _Series, tail: BarTail) -> None:
        """Rebuild `s` in one generation: the one it names (an emission's or an earlier read's: a
        read never replaces it), else the newest row's (the highest at the newest `ts`, until
        ADR-0033's pointer decides), else none: the rows (with the bars `s` held below the newest
        row merged in by key when the read withheld rows), the bars `s` held that are newer by
        key or re-close a row, the replayed re-closes of bars now held, then the forming bar. This
        read sets `hydrated`, `since_us` and `bounded` first, so it judges the held bars' gap
        checks: with no row of the generation, H1a's (#3660), whatever the reads before it left."""
        replay: Sequence[Close] = s.replay or ()
        forming, held, prior = s.forming, list(s.closed.values()), dict(s.stale)
        gen = s.generation  # only an emission swaps a named one: the publisher sees each swap
        if gen is None and tail.bars:
            gen = tail.bars[-1][0]  # none named yet: the newest row's
        _clear(s)
        s.generation, s.gapped = gen, False
        # Clean (no row withheld, SR-E12-11, nor skipped, #3614) and no live swap during it (D2-H1c)
        s.hydrated = not (tail.integrity_degraded or tail.skipped or s.swapped)
        s.since_us, s.bounded = tail.since_us, tail.bounded  # the read's start (D2-M4)
        # The named generation's rows: not another epoch's, nor an unflipped ADR-0033 rebuild's.
        rows = [(g, bar) for g, bar in tail.bars if g == gen]
        if rows and tail.integrity_degraded:  # a withheld row never drops its held bar (D2-H1b)
            g, newest = rows[-1]
            top = (newest.open_time, newest.index)
            rows += [(g, b) for b in held if (b.open_time, b.index) < top]
            rows.sort(key=lambda r: (r[1].open_time, r[1].index))  # stable: a row, then its twin
        for g, bar in rows:
            _apply(s, _update("close", bar), gaps=False)
            built = tail.builds.get((g, bar.index, bar.open_time))
            if built is not None:
                s.stale[bar.index] = built
        last = next(reversed(s.closed.values()), None)
        end = None if last is None else (last.open_time, last.index)
        for b in held:  # each keeps its own build mark; storage may still lack them
            # By key: non-time bars share open times. An older bar the rows lack (a missed
            # write, a pre-restart run) is not a restart.
            if end is None or (b.open_time, b.index) > end or _holds(s, b):
                _apply(s, _update("close", b))
                if b.index in prior:
                    s.stale[b.index] = prior[b.index]
        for u, g in replay:  # re-closes of the bars now held (newer closes were held already)
            if g == gen and _holds(s, u.bar):
                _apply(s, u)
        if forming is not None:
            _apply(s, _update("update", forming))
        s.version = next(self._versions)
