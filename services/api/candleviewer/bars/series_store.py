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
  bars it held (those newer than the rows, or replacing a bar they hold, each with its build
  mark), the closes seen just before and during the read that re-close a bar now held, and the
  forming bar. It keeps one generation: the one the series names (an emission's or an earlier
  read's), else the newest row's, else none yet. A read never replaces a named one: only an
  emission swaps it, so the WS publisher sees every generation swap the store makes. One
  read at a time per series: a concurrent `ensure` waits for it, and takes it over if its reader
  was cancelled. A failed read (`bars_series_hydrate_failed_total`) leaves the series as it was;
  a degraded one (SR-E12-11: served, never final) or a live swap leaves it not `hydrated`. An
  `ensure` reads a series that is not `hydrated`, or is `gapped`, again, but never sooner than
  `retry_after_s` after the last read; nothing else starts a read. Without a reader, a series
  keeps only what the store has seen live.
- **Read bound (C-2.18, #2787 D2-G1):** a read takes one of `MAX_CONCURRENT_TAIL_READS` slots,
  shared by every store on the event loop, and gives it back however it ends. The wait for a
  slot is part of the read and counts toward `timeout_s`: a read that cannot start in time fails
  like a slow one (`bars_series_hydrate_failed_total`; an `ensure` at least `retry_after_s`
  later reads it again), and
  the wait never adds to the time a read can take. One read per series waits at most, so at
  most `MAX_SERIES` do, and `timeout_s` sheds them. A series waiting for a slot is a read in
  flight: its other `ensure` calls share it, and the closes seen meanwhile are kept for its
  fold. A read that finds every slot taken counts `bars_series_read_waits_total`, whether or
  not it then gets one.
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
  in flight, the oldest shed first. The sink keeps an expired series current until that sweep.
  Memory: about 5 KB a close (measured), so 5 MB a series, 2.5 GB at `MAX_SERIES`, and 41 MB of
  rings.
- **E12-S12 notes:** the generation rule assumes one live emitter per series (a rebuild must emit
  through its own router), and `CAP_NAME` copies `SpecLeases`' literal until `leases` exports it.
- **`version`** comes from one store-wide counter and moves on every change: a cache key that
  stays safe across a release and a new hold.

Gaps: the closes emitted just before the hold that the writer had not landed yet come from the
ring (the last `RECENT_CLOSES`). A live close that skips indexes past the rows marks the series
`gapped` (`bars_series_gap`), and an `ensure` re-reads it, no sooner than `retry_after_s` after
the last read; the bars it holds newer than the stored rows survive the re-read. Not covered: the
forming bar is unknown until the next `open` or `update` (builders expose none); a hole inside the
stored rows (a row the read withheld or skipped, or one the writer never landed) stays a hole and
is not flagged; a jump is seen on a close only; with no stored row below its ring (an empty read)
a series cannot see its junction, so a writer lagging past the ring goes unflagged, and a series
read clean and empty with nothing seen live is read again only after a swap or a gap; a degraded
re-read drops a held bar whose stored row it withheld; a swap inside a first read goes unseen.
"""

from __future__ import annotations

import asyncio
import functools
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
from candleviewer.bars.limits import MAX_CONCURRENT_TAIL_READS, QUERY_TIMEOUT_S
from candleviewer.bars.metrics import (
    bars_series_gaps_total,
    bars_series_hydrate_failed_total,
    bars_series_read_waits_total,
    bars_series_resets_total,
    bars_spec_cap_rejected_total,
)
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import MAX_TAIL, BarTail, degrade_reason

#: The WS `history` cap (`23-ws-protocol.md` §6.1).
MAX_HISTORY: Final = MAX_TAIL
MAX_SERIES: Final = CAP_GLOBAL
#: `SpecLeases`' name for the process-wide cap: one `subscription_limit` wording.
CAP_NAME: Final = "process-wide"
#: Closes kept per series, held or not, for a new hold to start from.
RECENT_CLOSES: Final = 16
#: A series is never read again sooner than this after its last completed read.
RETRY_AFTER_S: Final = 5.0
#: A released series is kept this long: the builder's release grace (US-MKT-005).
RELEASE_GRACE_S: Final = GRACE_US / 1_000_000

#: `(symbol, spec, limit) -> BarTail`: `BarReader.read_tail`.
TailRead = Callable[[str, BarSpec, int], Awaitable[BarTail]]
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
    refs: int = 0
    generation: int | None = None  # set by the first emission, or by a read
    closed: OrderedDict[int, Bar] = field(default_factory=OrderedDict)  # index -> bar
    forming: Bar | None = None
    #: Holds the stored tail a read took: it neither failed nor was degraded, and no swap followed.
    hydrated: bool = False
    #: Waiters keep the latest read's result: True after a success, a failure or a timeout,
    #: False after a degraded read or a cancellation.
    attempted: bool = False
    #: Store-clock time before which no read starts again (set when a read completes).
    retry_at: float = float("-inf")
    #: A live close skipped indexes past the stored rows: the next `ensure` re-reads.
    gapped: bool = False
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


def _apply(s: _Series, u: BarUpdate, *, gaps: bool = True, count: bool = False) -> bool:
    """Fold one emission of `s.generation` into `s` (module docstring); False when it changes
    nothing. With `gaps`, a close that skips indexes past the newest one marks `s` gapped. Only
    the sink passes `count`: a hold's ring replay and a read's fold count no reset or gap."""
    bar, i = u.bar, u.bar.index
    last = next(reversed(s.closed), -1)
    if u.kind != "close":
        if i <= last:
            _clear(s)  # a bar at or below the newest close re-opened: restarted
            if count:
                bars_series_resets_total.labels(reason="restart").inc()
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
    elif gaps and s.closed and i > last + 1:
        s.gapped = True  # emitted before the hold and not stored yet, or lost: re-read
        if count:
            bars_series_gaps_total.inc()
        _log().warning(
            "bars_series_gap", spec_hash=bar.spec_hash, symbol=bar.symbol,
            from_index=last + 1, to_index=i - 1,
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
            s.hydrated = False  # the new generation's rows are read again (ADR-0033)
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

    def series_count(self) -> int:
        """Series kept: held, or released and in their grace (an expired one until the next
        `ensure` sweeps it)."""
        return len(self._series)

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
        s = self._keep((symbol, spec.spec_hash))
        hold = Hold(symbol, spec.spec_hash, functools.partial(self._release, s, None),
                    functools.partial(self._lose, s))  # fmt: skip
        try:
            await self._settle(s, symbol, spec)
        except BaseException:
            hold.release(grace=False)  # never returned: no lease can follow, so no grace
            raise
        return hold

    def _keep(self, key: Key) -> _Series:
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
            s = self._series[key] = _Series(next(self._versions))
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
        read's, or one a live swap followed)."""
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
        due: the first, a cancelled reader's, or one `retry_after_s` after the last read of a
        series not hydrated or gapped. A waiter keeps a completed read's result. A cancelled
        read is not gated, so its waiters never stay live-only (SR-E12-07 bounds the churn)."""
        woke = False
        while s.replay is not None:  # one read at a time per series
            await s.ready.wait()
            await asyncio.sleep(0)  # were `ready` ever stale, this spins one ensure, not the loop
            woke = True
        if woke and s.attempted:
            return
        if (not s.hydrated or s.gapped) and self._clock() >= s.retry_at:
            await self._hydrate(s, symbol, spec)

    async def _hydrate(self, s: _Series, symbol: str, spec: BarSpec) -> None:
        """One read, its fresh `ready` set however it ends. Its replay starts from the ring (the
        closes seen just before it) and takes every close seen during it, in emission order,
        the wait for a read slot included, which counts toward `timeout_s`."""
        if self._tail is None:
            return
        ready = s.ready = asyncio.Event()
        ring = self._recent.get((symbol, spec.spec_hash), ())
        s.replay, s.attempted = deque(ring, maxlen=MAX_HISTORY), False
        before = s.generation
        try:
            async with asyncio.timeout(self._timeout_s):  # the wait for a slot counts toward it
                slots = _READ_SLOTS.get()
                if slots.locked():  # every slot is taken, or reads are queued for one: it waits
                    bars_series_read_waits_total.inc()
                async with slots:  # given back however the read ends
                    tail = await self._tail(symbol, spec, MAX_HISTORY)
        except Exception as exc:  # broad on purpose: any read failure leaves the series as it was
            s.attempted = True
            bars_series_hydrate_failed_total.labels(reason=degrade_reason(exc)).inc()
            _log().warning(
                "bars_series_hydrate_failed", spec_hash=spec.spec_hash, symbol=symbol,
                error_type=type(exc).__name__, error=str(exc)[:120],
            )  # fmt: skip
        else:
            swapped = before is not None and s.generation != before  # live, during the read
            self._fold(s, tail)
            s.attempted = not tail.integrity_degraded
            s.hydrated = s.attempted and not swapped  # the new generation's rows are read next
            if tail.integrity_degraded:  # SR-E12-11: its bars are served, never as final
                _log().warning(
                    "bars_series_hydrate_degraded", spec_hash=spec.spec_hash, symbol=symbol,
                    dropped=tail.dropped,
                )  # fmt: skip
            if tail.skipped:
                _log().info(
                    "bars_series_rows_skipped", spec_hash=spec.spec_hash, symbol=symbol,
                    skipped=tail.skipped,
                )  # fmt: skip
        finally:
            s.replay = None
            ready.set()
        s.retry_at = self._clock() + self._retry_after_s  # a completed read, not a cancelled one

    def _fold(self, s: _Series, tail: BarTail) -> None:
        """Rebuild `s` in one generation: the one it names (an emission's or an earlier read's: a
        read never replaces it), else the newest row's (the highest at the newest `ts`, until
        ADR-0033's pointer decides), else none: the rows, the bars `s` held that are newer by
        key or re-close a row, the replayed re-closes of bars now held, then the forming bar."""
        replay: Sequence[Close] = s.replay or ()
        forming, held, prior = s.forming, list(s.closed.values()), dict(s.stale)
        gen = s.generation  # only an emission swaps a named one: the publisher sees each swap
        if gen is None and tail.bars:
            gen = tail.bars[-1][0]  # none named yet: the newest row's
        _clear(s)
        s.generation, s.gapped = gen, False
        for g, bar in tail.bars:
            if g != gen:
                continue  # another epoch, or an unflipped ADR-0033 rebuild: the named one wins
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
