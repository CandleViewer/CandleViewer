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
  so its generation is never stale (§8.2 generation swap).
- **Live bars only:** a series holds what the store has seen live, nothing from storage. The first
  `ensure` starts it from its ring, replayed by the sink rules; the sink keeps it current.
- **Holds and bounds (C-2.18):** `ensure` returns a `Hold`, released once. The last release keeps
  the series `release_grace_s` (the builder's grace, US-MKT-005), so a quick resubscribe finds it
  as the sink kept it; the next `ensure` sweeps the expired. At most `MAX_HISTORY` closed bars per
  series and `MAX_SERIES` series kept, held or in grace (the process-wide spec cap); rings for at
  most `MAX_SERIES` series, the least recently closed dropped first.
- **`version`** comes from one store-wide counter and moves on every change: a cache key that
  stays safe across a release and a new hold.

Gaps: nothing older than the ring; the forming bar is unknown until the next `open` or `update`
(builders expose none).
"""

from __future__ import annotations

import functools
import itertools
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, NamedTuple

from candleviewer.bars.emit import LIVE_GENERATION, BarEmission
from candleviewer.bars.errors import SpecCapExceeded
from candleviewer.bars.leases import CAP_GLOBAL, GRACE_US, Key
from candleviewer.bars.metrics import bars_spec_cap_rejected_total
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import MAX_TAIL

#: The WS `history` cap (`23-ws-protocol.md` §6.1).
MAX_HISTORY: Final = MAX_TAIL
MAX_SERIES: Final = CAP_GLOBAL
#: `SpecLeases`' name for the process-wide cap: one `subscription_limit` wording.
CAP_NAME: Final = "process-wide"
#: Closes kept per series, held or not, for a new hold to start from.
RECENT_CLOSES: Final = 16
#: A released series is kept this long: the builder's release grace (US-MKT-005).
RELEASE_GRACE_S: Final = GRACE_US / 1_000_000

#: A close as emitted, with its generation.
Close = tuple[BarUpdate, int]


class Latest(NamedTuple):
    """`latest`: the series' change counter and generation, its closed bars in index order and
    the forming bar."""

    version: int
    generation: int
    closed: list[Bar]
    forming: Bar | None


class Hold:
    """One `ensure`'s claim on a series. `release` drops it once: a second call is a no-op, so a
    double release never drops another caller's hold."""

    __slots__ = ("_drop", "spec_hash", "symbol")

    def __init__(self, symbol: str, spec_hash: str, drop: Callable[[], None]) -> None:
        self.symbol, self.spec_hash = symbol, spec_hash
        self._drop: Callable[[], None] | None = drop

    def release(self) -> None:
        drop, self._drop = self._drop, None
        if drop is not None:
            drop()


@dataclass(slots=True)
class _Series:
    version: int
    refs: int = 0
    generation: int = LIVE_GENERATION
    closed: OrderedDict[int, Bar] = field(default_factory=OrderedDict)  # index -> bar
    forming: Bar | None = None
    #: Store-clock time a released series is freed at (None while held).
    expires_at: float | None = None


def _reset(s: _Series, generation: int) -> None:
    s.closed.clear()
    s.forming, s.generation = None, generation


def _holds(s: _Series, bar: Bar) -> bool:
    held = s.closed.get(bar.index)
    return held is not None and held.open_time == bar.open_time


def _apply(s: _Series, u: BarUpdate) -> bool:
    """Fold one emission of `s.generation` into `s` (module docstring); False when it changes
    nothing."""
    bar, i = u.bar, u.bar.index
    last = next(reversed(s.closed), -1)
    if u.kind != "close":
        if i <= last:
            _reset(s, s.generation)  # a bar at or below the newest close re-opened: restarted
        s.forming = bar
        return True
    if _holds(s, bar):
        s.closed[i] = bar  # the same bar closed again (amended or repeated): in place
        return True
    if i <= last:
        if u.amended:
            return False  # an amended close of a bar this window does not hold
        _reset(s, s.generation)  # another bar at or below the newest index: the builder restarted
    s.closed[i] = bar
    if len(s.closed) > MAX_HISTORY:
        s.closed.popitem(last=False)
    if s.forming is not None and s.forming.index <= i:
        s.forming = None
    return True


def _live(s: _Series, u: BarUpdate, generation: int) -> bool:
    """A sink emission. One live builder per series: any other generation, lower or higher, is
    the series' new one (§8.2 generation swap)."""
    if generation != s.generation:
        _reset(s, generation)
    return _apply(s, u)


class SeriesStore:
    """The `BarSink` and recent-bars store described in the module docstring."""

    name = "series_store"

    def __init__(
        self,
        *,
        release_grace_s: float = RELEASE_GRACE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._grace_s, self._clock = release_grace_s, clock
        self._series: dict[Key, _Series] = {}
        self._recent: OrderedDict[Key, deque[Close]] = OrderedDict()
        self._versions = itertools.count(1)

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
            if s is not None and _live(s, u, gen):
                s.version = next(self._versions)

    def _remember(self, key: Key, close: Close) -> None:
        ring = self._recent.get(key)
        if ring is None:
            if len(self._recent) >= MAX_SERIES:
                self._recent.popitem(last=False)  # the series that closed a bar longest ago
            ring = self._recent[key] = deque(maxlen=RECENT_CLOSES)
        else:
            self._recent.move_to_end(key)
        ring.append(close)

    async def ensure(self, symbol: str, spec: BarSpec) -> Hold:
        """Keep the series (module docstring); release the `Hold` when done with it. Raises
        `SpecCapExceeded` (counted, nothing held) when `MAX_SERIES` series are kept."""
        s = self._keep((symbol, spec.spec_hash))
        return Hold(symbol, spec.spec_hash, functools.partial(self._release, s))

    def _keep(self, key: Key) -> _Series:
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

    def _release(self, s: _Series) -> None:
        s.refs -= 1
        if not s.refs:
            s.expires_at = self._clock() + self._grace_s

    def version(self, symbol: str, spec_hash: str) -> int:
        """The series' change counter; 0 while the store does not keep it."""
        s = self._series.get((symbol, spec_hash))
        return 0 if s is None else s.version

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
        return Latest(s.version, s.generation, closed, forming)
