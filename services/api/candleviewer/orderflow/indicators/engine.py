"""The indicator engine: shared server instances, updated once per bar close (E13-T02, #426;
ADR-0034; 24-internal-schemas §7.3, §7.4; 23-ws-protocol §6.1).

`IndicatorEngine` is the fourth `BarSink` on the bars `EmitRouter`: series store, WS bars
publisher, this, then the writer (20-architecture §4.2). Its `emit` never awaits, like the WS
sinks, so a close reaches every instance of its series before the next emission. Every bound
named here is a constant of `limits.py`.

- **Memo (24 §7.3).** One instance per `(symbol, spec_hash)`. The `spec_hash` holds the bar
  series' own (§7.4), so that is one per `(symbol, bar spec_hash, indicator spec_hash)`. Every
  consumer shares it (WS subscriptions now; S08, E35 and E40 later), and each close updates it
  once. `indicator_cache_hits_total` / `_misses_total` count the joins and the starts.
- **Admission.** `resolve_instances` checks a request against the catalogue before anything is
  held: a `compute: server` indicator, its `params_schema` (`validate_params`, never clamped), a
  series a session anchor can read (not renko), no instance twice. `check` applies the window
  bound (SR-E13-04) and the caps (`leases`, SR-E13-03, IR-31); `admit` checks again, takes the
  leases and starts each new instance, and undoes all of it if anything then raises. A `ctl` that
  replaces instances forgets at once each replaced one no other consumer holds: no grace, and no
  churn charged to its user. Kernels are built here only, from validated parameters.
- **Priming.** A new instance folds the closed bars the series store holds (up to 1 000, of the
  series' current generation). Its cost is counted in kernel updates, a time series' fillers
  included (`_updates`): a sparse series' 1 000 bars can take a million. When its warmup plus the
  subscription's history needs older bars and the generation has them (the store's oldest index
  is above 0), a full recompute reads them (`HistoryRead`, time series only) on one of
  `MAX_CONCURRENT_RECOMPUTES` slots, in a task the engine owns; when the store's bars suffice but
  folding them takes more than `MAX_SYNC_PRIME_UPDATES` updates for the new instances together, a
  full recompute folds them alone. A smaller prime runs at once. With every slot taken the
  admission is refused, never queued. The instance is not ready until its bars are folded: its
  snapshots wait, and the listener's `ready` flushes them. A read that fails, passes
  `RECOMPUTE_TIMEOUT_S` or is incomplete (`HistoryIncompleteError`: rows withheld, or bars that
  skip an index or stop short of the store's oldest) primes from the store alone (logged). Only
  read bars older than the store's oldest are folded: the store, ahead of the engine on the emit
  path, holds every close since. The task folds `PRIME_CHUNK_UPDATES` kernel updates at a time
  and yields between (C-2.17; one bar's fillers are never split, and `StoredHistory` yields after
  each page too). The series' closes that land meanwhile are held back, at most `MAX_POINTS`, and
  folded in order before the instance is ready, in chunks too: new bars up to
  `PRIME_CHUNK_UPDATES` kernel updates, or an amended bar alone (its replay restores a
  checkpoint, which is no kernel update). A generation change or a store repair meanwhile, a
  close it cannot place, or more closes than that primes it from the store alone instead, at once
  and within `MAX_SYNC_PRIME_UPDATES`.
- **Budgets.** A prime that must run at once but would pass its budget (a re-prime, or the end of
  a recompute, with no slot free) folds only the newest bars within it: the kernel starts at the
  oldest of those, as after a restart, and a new warmup follows.
- **Sessions.** A session-anchored instance (`vwap`, `cvd`: `Kernel.anchor_us`) restarts at each
  period start. Its read reaches back to the start of the period holding the oldest bar it needs,
  and it never serves a value of a period it did not fold from that period's start: such a value
  is `None` (`read`: `warmup`) until the next period begins. A fold holds a period whole from the
  generation's first bar (index 0), from a read's window start, or from just past the newest bar
  a budget left out; else only from its own first bar (a non-time series, no free slot, a failed
  or incomplete read). After a kernel restart it holds the restart bar's period whole when the gap
  began in an earlier period, and otherwise only from that bar.
- **Time series** are densified as `BarSeries.densify()` does: a filler, flat at the previous close
  with no volume, advances the kernel and publishes no point. A gap of more than `MAX_FILL_SLOTS`
  empty slots restarts the kernel at the bar after it (a new warmup follows) rather than fold that
  many fillers on the emit path. Other kinds are never densified.
- **Amended closes** (time bars, within the builder's 60 s window). A time-series instance keeps
  its last real bars, enough for that window at its interval plus `CHECKPOINT_EVERY`, with a kernel
  snapshot before every `CHECKPOINT_EVERY`th. An amended close restores the newest checkpoint at or
  before the bar, folds forward with the new bar, and publishes each point whose value changed with
  `amended: true` (`indicator_recompute_total{reason="amended"}`). A close of a bar the ring does
  not hold (older, or another bar at a held index), or one whose replay would take more than
  `MAX_AMEND_UPDATES` kernel updates, fillers included (C-2.17: on a sparse series the checkpoint
  can lie several filled gaps back), re-primes the series' instances, which then re-snapshot as
  after a store repair (`history_repair`).
- **Generations and repairs.** A close in another generation than an instance's is a swap: every
  instance of the series re-primes from the store (which reset first), and the listener
  re-snapshots the series (`generation_swap`). A store repair re-primes it too (`history_repair`,
  the store's repair hook). A re-prime counts `reason="backfill"`; one that needs a full recompute
  and finds no free slot primes from the store alone, at once, within `MAX_SYNC_PRIME_UPDATES` for
  the series' instances together (`Budgets`).
- **Reads.** `read` returns `Available(value, generation, index, build_version)` or `Unavailable`:
  `missing` (no ready instance), `parity_flagged` (an injected hook, never by default), `stale`
  (more than `STALE_AFTER_BARS` closes behind its series, or another generation), `warmup` (the
  kernel's, or a session not folded whole), or `nan` (no value after the warmup: a zero divisor).
  S08's `resolve()` builds on it (IR-45).

Bounds (C-2.18): instances by the caps, each with at most `MAX_POINTS` points, its ring and at most
`MAX_POINTS` held-back closes; recompute tasks by the slots; each read by `RECOMPUTE_TIMEOUT_S`.
C-2.17: a synchronous prime folds at most `MAX_SYNC_PRIME_UPDATES` kernel updates, an amended
close replays at most `MAX_AMEND_UPDATES` in each instance, and a recompute holds the loop for one
page, one chunk of `PRIME_CHUNK_UPDATES` and one bar's fillers, or one held-back amended close,
at a time.
The emit path removes the instances whose grace has ended at most every `SWEEP_EVERY_US`, so an
unheld one folds closes for at most that long past its grace. The state is in memory only: a
restart re-primes (24 §7.4). An instance update that raises is counted
(`bar_emit_sink_errors_total{reason="indicators"}`), logged with the symbol, `spec_hash` and bar
index, and re-primes the series; the other instances still get the close. A re-prime that raises
too is counted and logged the same way and leaves that instance empty, to restart at the next
close.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import time
from bisect import bisect_left
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from operator import itemgetter
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.reader import BarKey, BarPage, stored_bar
from candleviewer.bars.series_store import Latest
from candleviewer.bars.time_builder import LATE_WINDOW_US
from candleviewer.observability.context import spawn
from candleviewer.orderflow.errors import (
    HistoryIncompleteError,
    IndicatorParamError,
    InstanceRefusedError,
    InvalidParamsError,
    RecomputeRefusedError,
)
from candleviewer.orderflow.indicators.catalogue import (
    IndicatorCatalogue,
    IndicatorDef,
    JsonValue,
    Param,
    default_catalogue,
    validate_params,
)
from candleviewer.orderflow.indicators.identity import IndicatorSpec
from candleviewer.orderflow.indicators.kernel import DAY_US, Kernel, session_start
from candleviewer.orderflow.indicators.kernels import build_kernel
from candleviewer.orderflow.indicators.leases import InstanceLeases
from candleviewer.orderflow.indicators.limits import (
    CHECKPOINT_EVERY,
    HISTORY_PAGE_ROWS,
    MAX_AMEND_UPDATES,
    MAX_CONCURRENT_RECOMPUTES,
    MAX_FILL_SLOTS,
    MAX_POINTS,
    MAX_SYNC_PRIME_UPDATES,
    MAX_WINDOW_BARS,
    PRIME_CHUNK_UPDATES,
    RECOMPUTE_TIMEOUT_S,
    STALE_AFTER_BARS,
    SWEEP_EVERY_US,
)
from candleviewer.orderflow.indicators.metrics import (
    CAP_REJECTED,
    COMPUTE,
    RECOMPUTES,
    RecomputeReason,
    indicator_cache_hits_total,
    indicator_cache_misses_total,
)
from candleviewer.orderflow.indicators.types import (
    BarInput,
    KernelContext,
    Outputs,
    Unavailable,
    bar_input,
)

Reprime = Literal["generation_swap", "history_repair"]
Key = tuple[str, str]  # (symbol, spec_hash): an instance, or a series by its bar spec_hash
#: `(index, bar)` pairs, oldest first: what a fold takes.
Bars = Sequence[tuple[int, BarInput]]
#: What priming one instance needs: the bars it folds back from the newest (warmup plus
#: history), and where its periods start (`Kernel.anchor_us`), None for one with none.
Need = tuple[int, int | None]

#: `(symbol, spec, generation, start_us, end_us) -> [(index, bar)]`: the closed tape-built bars of
#: that generation opening in `[start_us, end_us)`, oldest first (`StoredHistory`).
HistoryRead = Callable[[str, BarSpec, int, int, int], Awaitable[Sequence[tuple[int, BarInput]]]]
#: `(generation, start_us, end_us)`: the stored-bar read priming some instances takes.
Window = tuple[int, int, int]

_CATALOGUE: Final = default_catalogue()


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _wall_us() -> int:
    return time.time_ns() // 1_000


@dataclass(frozen=True, slots=True)
class Point:
    """An instance's values on one real bar: the bar's key `(generation, index)`, its open time
    (µs, C4) and one value per output, `None` where there is none."""

    generation: int
    index: int
    t_us: int
    values: Outputs
    amended: bool = False


@dataclass(frozen=True, slots=True)
class InstanceInfo:
    """What a subscriber is told of an instance beside its points (23 §14.10)."""

    key: str
    indicator: str
    params: Mapping[str, JsonValue]
    outputs: tuple[str, ...]
    build_version: int


@dataclass(frozen=True, slots=True)
class Batch:
    """Points of one instance: new or amended ones (`IndicatorListener.points`), or the newest
    `history` of them (`IndicatorEngine.snapshot`)."""

    info: InstanceInfo
    points: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class Available:
    """A value that may cross into a consumer (`boundary.to_decimal` for OMS, journal, audit)."""

    value: float
    generation: int
    index: int
    build_version: int


def _json(value: Param) -> JsonValue:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@dataclass(frozen=True, slots=True)
class Requested:
    """One validated instance: its definition and kernel, every parameter (defaults written out,
    each in its canonical type) and its identity."""

    definition: IndicatorDef
    kernel: type[Kernel]
    params: Mapping[str, Param]
    spec: IndicatorSpec

    @property
    def key(self) -> str:
        return self.spec.spec_hash

    def warmup(self) -> int:
        return self.kernel.warmup_bars(self.params)

    def anchor_us(self, spec: BarSpec) -> int | None:
        """Where its periods start on `spec`'s series (`Kernel.anchor_us`); None if never."""
        context = KernelContext(session_anchor_utc_min=spec.session_anchor_utc_min)
        return self.kernel.anchor_us(self.params, context)

    def span(self, spec: BarSpec, history: int) -> int:
        """The most bars its priming may read on `spec`'s series for `history` (SR-E13-04): its
        warmup and the history and, for a session-anchored one on a time series, the slots of a
        day more, back to the start of a period."""
        step = _step_us(spec)
        day = DAY_US // step if step and self.anchor_us(spec) is not None else 0
        return self.warmup() + history + day

    def info(self) -> InstanceInfo:
        params = {p.name: _json(self.params[p.name]) for p in self.definition.params}
        k = self.kernel
        return InstanceInfo(self.key, self.definition.id, params, k.outputs, k.build_version)

    def echo(self) -> dict[str, JsonValue]:
        """Its `sub_ok.effective` entry (23 §6.1): the id, every param, and its `key`."""
        info = self.info()
        return {"indicator": info.indicator, "params": dict(info.params), "key": info.key}


def resolve_instances(
    raw: Sequence[Mapping[str, Any]],
    bar_spec: BarSpec,
    catalogue: IndicatorCatalogue | None = None,
) -> tuple[Requested, ...]:
    """The validated instances of a request (23 §6.1), each entry `{indicator, params}` as §13's
    `indicatorInstance` shapes it. Raises `InstanceRefusedError` for the first defect, in order:
    no such indicator, a `client_worker` one, its parameters (`validate_params`), a session anchor
    on renko bars, the same instance twice. `compute` is the definition's, never the caller's."""
    cat = _CATALOGUE if catalogue is None else catalogue
    out: list[Requested] = []
    seen: set[str] = set()
    for position, item in enumerate(raw):
        name = item.get("indicator")
        definition = cat.get(name) if isinstance(name, str) else None
        if definition is None:
            raise InstanceRefusedError(position, "no indicator has that id.")
        kernel = definition.kernel
        if kernel is None:
            message = f"{definition.id} is computed in the chart, not served here."
            raise InstanceRefusedError(position, message)
        try:
            params = validate_params(definition, item.get("params", {}))
            spec = IndicatorSpec.of(definition.id, params, bar_spec_hash=bar_spec.spec_hash)
        except InvalidParamsError as exc:
            raise InstanceRefusedError(position, str(exc)) from None
        except IndicatorParamError:
            raise InstanceRefusedError(position, "a parameter cannot be read.") from None
        if bar_spec.kind == "renko" and any(p.name == "anchor" for p in definition.params):
            message = f"{definition.id} restarts each session, which renko bars cannot anchor."
            raise InstanceRefusedError(position, message)
        if spec.spec_hash in seen:
            raise InstanceRefusedError(position, "the same instance is requested twice.")
        seen.add(spec.spec_hash)
        out.append(Requested(definition, kernel, MappingProxyType(params), spec))
    return tuple(out)


class RangeReader(Protocol):
    """The slice of `bars.reader.BarReader` `StoredHistory` reads through."""

    async def read_bars(
        self,
        symbol: str,
        spec: BarSpec,
        from_us: int,
        to_us: int,
        limit: int,
        *,
        after_us: int | None = None,
        at_key: BarKey | None = None,
    ) -> BarPage: ...


class StoredHistory:
    """`HistoryRead` over `BarReader.read_bars` (parameterised SQL only): the closed tape-built bars
    of a generation, oldest first, in pages of at most `HISTORY_PAGE_ROWS` rows and `max_rows` in
    all, yielding to the loop after each page (C-2.17: a page's integrity checks and conversions
    run without a yield). Another generation's rows and kline rows are left out; a page that
    withheld rows (`integrity_degraded`, SR-E12-11) or a bar of the generation it cannot fold (not
    closed, or no index or delta) raises `HistoryIncompleteError`: an incomplete read is a failed
    one, never folded as empty slots. `reader` is the one it reads through: `create_app` passes the
    series store's own, on the `bars_hydrate` connection (20-architecture §4.2, D-G2)."""

    def __init__(self, reader: RangeReader, *, max_rows: int = MAX_WINDOW_BARS) -> None:
        self.reader, self._max_rows = reader, max_rows

    async def __call__(
        self, symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> list[tuple[int, BarInput]]:
        out: list[tuple[int, BarInput]] = []
        after: int | None = None
        taken = 0
        while taken < self._max_rows:
            limit = min(HISTORY_PAGE_ROWS, self._max_rows - taken)
            page = await self.reader.read_bars(
                symbol, spec, start_us, end_us, limit, after_us=after
            )
            if page.integrity_degraded:
                raise HistoryIncompleteError("A page of stored bars withheld rows.")
            taken += len(page.rows)
            for row in page.rows:
                s = stored_bar(row)
                if not s.tape_built or s.generation != generation:
                    continue  # a kline row, or another generation's: no bar of this one
                if s.index is None or s.delta is None or not s.confirmed:
                    raise HistoryIncompleteError("A stored bar of the generation cannot be read.")
                values = (s.open, s.high, s.low, s.close, s.volume, s.delta)
                o, h, lo, c, v, d = (float(x) for x in values)
                out.append((s.index, BarInput(s.ts_us, o, h, lo, c, v, d, False)))
            if page.next_cursor is None:
                break
            after = page.next_cursor
            await asyncio.sleep(0)  # C-2.17: the loop runs between pages
        return out


class IndicatorListener(Protocol):
    """Where the engine reports what changed (the WS publisher). Every call is synchronous."""

    def points(self, symbol: str, spec: BarSpec, batches: Mapping[str, Batch]) -> None:
        """New or amended points of the series' instances, by instance key."""

    def resnapshot(self, symbol: str, spec: BarSpec, reason: Reprime) -> None:
        """Every instance of the series re-primed: its subscribers need a new snapshot."""

    def ready(self, symbol: str, spec: BarSpec) -> None:
        """An instance of the series finished priming: snapshots waiting for it can go out."""


class SeriesView(Protocol):
    """The slice of `bars.series_store.SeriesStore` the engine reads."""

    def latest(self, symbol: str, spec_hash: str, history: int) -> Latest | None: ...


@dataclass(slots=True)
class _Entry:
    """A real bar of a time series' ring. `checkpoint` is the kernel state before this bar and its
    fillers, with the real bar before it (`prev`) and the bars folded by then (`folded`)."""

    index: int
    input: BarInput
    values: Outputs = ()
    checkpoint: bytes | None = None
    prev: BarInput | None = None
    folded: int = 0


@dataclass(slots=True)
class _Instance:
    req: Requested
    info: InstanceInfo
    symbol: str
    bar_spec: BarSpec
    context: KernelContext
    kernel: Kernel
    step: int  # a time series' interval in µs; 0 for any other kind (never densified or amended)
    ring: deque[_Entry]
    history: int  # the most history an admission asked of it
    anchor_us: int | None  # where a session-anchored kernel's periods start (`Kernel.anchor_us`)
    ready: bool = False
    generation: int | None = None
    points: deque[Point] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    last: BarInput | None = None
    last_index: int | None = None
    folded: int = 0  # densified bars folded since the kernel started (warmup)
    seq: int = 0  # ring entries ever appended (the checkpoint cadence)
    since_us: int | None = None  # the read window a fresh kernel's fold starts at, if any
    complete_us: int | None = None  # a period starting before it is served as None (`_withheld`)
    held: list[tuple[int, BarUpdate]] | None = None  # closes held back while a read's fold runs
    dirty: bool = False  # the series reset or was repaired under that fold


def _step_us(spec: BarSpec) -> int:
    return spec.interval_ms * 1_000 if spec.kind == "time" and spec.interval_ms else 0


def _ring_size(step: int) -> int:
    """Real bars an amended close can reach (the builder's window at this interval), plus the
    checkpoint spacing, so a checkpoint precedes each of them; 0 when nothing is amended."""
    return 0 if not step else LATE_WINDOW_US // step + 2 + CHECKPOINT_EVERY


def _fill(last: BarInput | None, t: int, step: int) -> list[BarInput] | None:
    """The fillers between `last` and a bar opening at `t` (`BarSeries.densify()`), or None past
    `MAX_FILL_SLOTS` of them."""
    if not step or last is None:
        return []
    out: list[BarInput] = []
    c, ft = last.close, last.t + step
    while ft < t:
        if len(out) == MAX_FILL_SLOTS:
            return None
        out.append(BarInput(ft, c, c, c, c, 0.0, 0.0, True))
        ft += step
    return out


def _fillers(a: int, b: int, step: int) -> int:
    """How many fillers `_fill` folds between bars opening at `a` and `b`: none past
    `MAX_FILL_SLOTS`, where the kernel restarts instead."""
    n = (b - a - 1) // step if step else 0
    return n if 0 < n <= MAX_FILL_SLOTS else 0


def _updates(times: Sequence[int], step: int) -> int:
    """The kernel updates a fold of bars opening at `times` (oldest first) takes: one per bar,
    and a time series' fillers."""
    return len(times) + sum(_fillers(a, b, step) for a, b in itertools.pairwise(times))


def _within(times: Sequence[int], step: int, budget: int) -> int:
    """The position of the oldest of the bars opening at `times` (oldest first) a fold can start
    at and take at most `budget` kernel updates (fillers included) to the newest, which it always
    reaches."""
    spent = 1
    for at in range(len(times) - 1, 0, -1):
        spent += 1 + _fillers(times[at - 1], times[at], step)
        if spent > budget:
            return at
    return 0


def _consecutive(bars: Bars) -> bool:
    """True when `bars`' indexes run up one by one: a generation's real bars, none missing."""
    if not bars:
        return True
    first = bars[0][0]
    return list(map(itemgetter(0), bars)) == list(range(first, first + len(bars)))


@dataclass(frozen=True, slots=True)
class _Task:
    """A full recompute's work: the stored-bar read it takes first, or None to fold the series
    store's bars alone."""

    window: Window | None


def _oldest_open(newest_us: int, step: int, need: Need) -> int:
    """The open time of the oldest bar a time-series `need` folds: its bars back from the newest
    and, for a session-anchored one, back to the start of the period holding that bar."""
    bars, anchor_us = need
    first = newest_us - (bars - 1) * step
    return first if anchor_us is None else session_start(first, anchor_us)


class IndicatorEngine:
    """The `BarSink` and instance memo described in the module docstring."""

    name = "indicators"

    def __init__(
        self,
        store: SeriesView,
        *,
        history: HistoryRead | None = None,
        leases: InstanceLeases | None = None,
        slots: int = MAX_CONCURRENT_RECOMPUTES,
        now_us: Callable[[], int] = _wall_us,
        parity_flagged: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._store, self._history = store, history
        self._leases = InstanceLeases() if leases is None else leases
        self._slots, self._busy = slots, 0
        self._now_us, self._parity = now_us, parity_flagged
        self._instances: dict[Key, _Instance] = {}
        self._series: dict[Key, dict[str, _Instance]] = {}  # (symbol, bar spec_hash) -> by key
        self._newest: dict[Key, tuple[int, int]] = {}  # the newest close seen: (generation, index)
        self._versions: dict[Key, int] = {}
        self._counter = itertools.count(1)
        self._listener: IndicatorListener | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = False
        self._swept_us = 0  # when `_sweep` last ran (`now_us`)

    def listen(self, listener: IndicatorListener) -> None:
        """Set the listener (the WS publisher), once: a second call raises `RuntimeError`."""
        if self._listener is not None:
            raise RuntimeError("the indicator engine's listener is set already")
        self._listener = listener

    # -- admission -----------------------------------------------------------------------------

    def check(
        self,
        symbol: str,
        spec: BarSpec,
        requested: Sequence[Requested],
        user: str | None,
        *,
        history: int,
        consumer: str | None = None,
    ) -> None:
        """Raise what `admit` would refuse now, counted, in this order: a window over
        `MAX_WINDOW_BARS` (`Requested.span`; `RecomputeRefusedError` `window`), a cap
        (`InstanceCapError`), and new instances whose priming needs a full recompute with no slot
        free (`RecomputeRefusedError` `recompute`; decided from the store, so only once the
        series is held: `_plan`). `consumer`: one that replaces its own instances
        (`leases.check`). Changes nothing but the removal of instances whose grace has ended."""
        self._sweep()
        for r in requested:
            if r.span(spec, history) > MAX_WINDOW_BARS:
                CAP_REJECTED["window"].inc()
                message = f"{r.definition.id} needs more than {MAX_WINDOW_BARS} bars."
                raise RecomputeRefusedError("window", message)
        self._leases.check(symbol, [r.key for r in requested], user, consumer)
        needs = self._needs(symbol, spec, requested, history)
        if self._plan(symbol, spec, needs) is not None and not self._slot():
            CAP_REJECTED["recompute"].inc()
            raise RecomputeRefusedError("recompute", "Every indicator recompute slot is taken.")

    def admit(
        self,
        symbol: str,
        spec: BarSpec,
        requested: Sequence[Requested],
        consumer: str,
        user: str | None,
        *,
        history: int,
        replacing: Sequence[str] = (),
        reason: RecomputeReason | None = None,
    ) -> None:
        """`check`, then hold every instance of `requested` for `consumer` and start the new ones
        (module docstring). With `replacing`, the consumer's instances of those keys that the new
        set leaves out are let go once the new ones are held (a WS `ctl`, `_let_go`), and `reason`
        counts each instance it starts. Nothing is held when it raises: a refusal takes nothing,
        and a raise after it undoes what this call took (`_unwind`). The series must be held in
        the store."""
        mine = consumer if replacing else None
        self.check(symbol, spec, requested, user, history=history, consumer=mine)
        task = self._plan(symbol, spec, self._needs(symbol, spec, requested, history))
        taken: list[Key] = []  # leases this call gave the consumer
        created: set[Key] = set()  # of those, instances no one held or kept before
        fresh: list[_Instance] = []
        try:
            for r in requested:
                key = (symbol, r.key)
                held = self._leases.held_by(key, consumer)
                new = self._leases.acquire(key, consumer, user)
                if not held:
                    taken.append(key)
                if new:
                    created.add(key)
                (indicator_cache_misses_total if new else indicator_cache_hits_total).inc()
                inst = self._instances.get(key)
                if inst is None:
                    fresh.append(self._start(symbol, spec, r, history))
                else:
                    inst.history = max(inst.history, history)
            if task is not None and fresh:  # `check` found a slot for it
                self._spawn(symbol, spec, fresh, task)
            elif fresh:  # the store's bars, within `MAX_SYNC_PRIME_UPDATES` (`_plan`)
                gen, bars = self._store_bars(symbol, spec)
                for inst in fresh:
                    self._prime(inst, gen, bars)
        except BaseException:
            self._unwind(consumer, taken, created, fresh)
            raise
        keys = {r.key for r in requested}
        self._let_go(symbol, [k for k in replacing if k not in keys], consumer)
        if reason is not None and fresh:
            RECOMPUTES[reason].inc(len(fresh))
        self._bump((symbol, spec.spec_hash))

    def _unwind(
        self, consumer: str, taken: Sequence[Key], created: set[Key], fresh: Sequence[_Instance]
    ) -> None:
        """Undo an admission that raised after its checks (SR-E13-03 bookkeeping fails closed):
        forget the instances it started and the leases it created, with no grace, and release
        the leases it took on running instances."""
        now = self._now_us()
        for key in taken:
            if key in created:
                self._leases.drop(key)
            else:
                self._leases.release(key, consumer, now)
        for inst in fresh:
            self._forget(inst)

    def _needs(
        self, symbol: str, spec: BarSpec, requested: Sequence[Requested], history: int
    ) -> list[Need]:
        """What priming the instances of `requested` that do not run yet needs."""
        return [
            (r.warmup() + history, r.anchor_us(spec))
            for r in requested
            if (symbol, r.key) not in self._instances
        ]

    def _let_go(self, symbol: str, keys: Sequence[str], consumer: str) -> None:
        """The instances a `ctl` replaced: one that `consumer` alone held is forgotten at once,
        with no grace and nothing charged to its user (IR-31: replaced, not released); the
        others lose `consumer`'s lease (`release`)."""
        shared: list[str] = []
        for key in keys:
            if not self._leases.sole((symbol, key), consumer):
                shared.append(key)
                continue
            self._leases.drop((symbol, key))
            inst = self._instances.get((symbol, key))
            if inst is not None:
                self._forget(inst)
        self.release(symbol, shared, consumer)

    def release(self, symbol: str, keys: Sequence[str], consumer: str) -> None:
        """Drop `consumer`'s leases on `keys`; an instance with none left keeps its grace. Never
        raises, so a WS subscription's other releases still run: a lease it does not hold (a
        bookkeeping defect) is logged and skipped."""
        now = self._now_us()
        for key in keys:
            if self._leases.held_by((symbol, key), consumer):
                self._leases.release((symbol, key), consumer, now)
            else:
                _log().warning("indicator_lease_not_held", symbol=symbol, spec_hash=key)
        self._sweep(now)

    async def stop(self) -> None:
        """Refuse new recomputes, then cancel and await the running ones."""
        self._stopping = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _sweep(self, now: int | None = None) -> None:
        """Remove every instance whose grace has ended (`InstanceLeases.expired`)."""
        self._swept_us = now = self._now_us() if now is None else now
        for key in self._leases.expired(now):
            inst = self._instances.get(key)
            if inst is not None:
                self._forget(inst)

    def _forget(self, inst: _Instance) -> None:
        """Remove an instance; a series left with none forgets its newest close and version."""
        key, series = (inst.symbol, inst.req.key), (inst.symbol, inst.bar_spec.spec_hash)
        if self._instances.get(key) is inst:
            del self._instances[key]
        on_series = self._series.get(series, {})
        if on_series.get(inst.req.key) is inst:
            del on_series[inst.req.key]
        if not on_series:  # a later instance starts from a fresh, higher version
            self._series.pop(series, None)
            self._newest.pop(series, None)
            self._versions.pop(series, None)

    def _start(self, symbol: str, spec: BarSpec, r: Requested, history: int) -> _Instance:
        context = KernelContext(session_anchor_utc_min=spec.session_anchor_utc_min)
        step = _step_us(spec)
        inst = _Instance(
            r, r.info(), symbol, spec, context, self._kernel(r, context), step,
            deque(maxlen=_ring_size(step)), history, r.kernel.anchor_us(r.params, context),
        )  # fmt: skip
        self._instances[(symbol, r.key)] = inst
        self._series.setdefault((symbol, spec.spec_hash), {})[r.key] = inst
        return inst

    @staticmethod
    def _kernel(r: Requested, context: KernelContext) -> Kernel:
        return build_kernel(r.definition.id, r.params, source=r.kernel.sources[0], context=context)

    # -- priming and full recomputes ------------------------------------------------------------

    def _latest(self, symbol: str, spec: BarSpec) -> Latest | None:
        return self._store.latest(symbol, spec.spec_hash, MAX_POINTS + 1)  # 1 000 closed at most

    def _store_bars(
        self, symbol: str, spec: BarSpec
    ) -> tuple[int | None, list[tuple[int, BarInput]]]:
        """The series' generation and the closed bars the store holds of it, oldest first, each
        converted once for all the instances that fold them."""
        latest = self._latest(symbol, spec)
        if latest is None or latest.generation is None:
            return None, []
        return latest.generation, [(b.index, bar_input(b)) for b in latest.closed]

    def _window(self, symbol: str, spec: BarSpec, needs: Sequence[Need]) -> Window | None:
        """`(generation, start_us, end_us)` of the read that priming `needs` takes (module
        docstring: back to the oldest bar any of them folds, `_oldest_open`), or None when the
        store's bars suffice, or no read can serve them (no reader, not a time series)."""
        step = _step_us(spec)
        if not needs or self._history is None or not step:
            return None
        latest = self._latest(symbol, spec)
        if latest is None or latest.generation is None or not latest.closed:
            return None
        oldest, newest = latest.closed[0], latest.closed[-1]
        start = min(_oldest_open(newest.open_time, step, need) for need in needs)
        if oldest.index == 0 or start >= oldest.open_time:
            return None
        return latest.generation, start, newest.open_time + 1

    def _plan(self, symbol: str, spec: BarSpec, needs: Sequence[Need]) -> _Task | None:
        """How priming instances with `needs` runs: None when the store's bars suffice for them
        and folding those takes at most `MAX_SYNC_PRIME_UPDATES` kernel updates for them all
        (`_updates`: a sparse time series' fillers count), so the caller folds them at once; else
        a full recompute, which first reads the stored bars `_window` names, if any."""
        if not needs:
            return None
        window = self._window(symbol, spec, needs)
        if window is not None:
            return _Task(window)
        latest = self._latest(symbol, spec)
        if latest is None or latest.generation is None:
            return None
        times = [b.open_time for b in latest.closed]
        if len(needs) * _updates(times, _step_us(spec)) <= MAX_SYNC_PRIME_UPDATES:
            return None
        return _Task(None)

    def _slot(self) -> bool:
        """True when a full recompute can start now: a slot is free, the engine is not stopping,
        and a loop runs to run it on."""
        if self._stopping or self._busy >= self._slots:
            return False
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # no loop to run the task on
            return False
        return True

    def _spawn(self, symbol: str, spec: BarSpec, insts: list[_Instance], task: _Task) -> None:
        """Take a slot and run the full recompute in a task the engine owns (`_backfill`)."""
        running = spawn(self._backfill(symbol, spec, insts, task.window), name="indicator-backfill")
        self._busy += 1
        self._tasks.add(running)
        running.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        """A recompute task ended, however (a cancelled one may never have started): its slot
        is free again, and an error that escaped it is logged."""
        self._tasks.discard(task)
        self._busy -= 1
        if not task.cancelled() and (exc := task.exception()) is not None:
            _log().error("indicator_backfill_crashed", error_type=type(exc).__name__)

    async def _backfill(
        self, symbol: str, spec: BarSpec, insts: list[_Instance], window: Window | None
    ) -> None:
        """A full recompute: the read of `window`, if any, whose bars must run up one index at a
        time (one that fails, times out or is incomplete is logged, and the store's bars alone
        prime), then each instance still running primed from it (`_fold_read`), then `ready`."""
        rows: Bars = ()
        generation: int | None = None
        since: int | None = None
        if window is not None and self._history is not None:
            generation, start, end = window
            try:
                async with asyncio.timeout(RECOMPUTE_TIMEOUT_S):
                    got = await self._history(symbol, spec, generation, start, end)
                if not _consecutive(got):
                    raise HistoryIncompleteError("The stored bars skip an index.")
                rows, since = got, start
            except Exception as exc:  # primed from the store alone, logged; a cancellation raises
                _log().warning(
                    "indicator_backfill_failed",
                    symbol=symbol,
                    spec_hash=spec.spec_hash,
                    error_type=type(exc).__name__,
                )
        for inst in insts:
            if self._instances.get((symbol, inst.req.key)) is inst:  # not expired meanwhile
                await self._fold_read(inst, generation, rows, since)
        self._bump((symbol, spec.spec_hash))
        if self._listener is not None:
            self._listener.ready(symbol, spec)

    async def _fold_read(
        self, inst: _Instance, generation: int | None, older: Bars, since_us: int | None
    ) -> None:
        """Prime `inst` from the store's bars, after a read's `older` bars of `generation`
        (`since_us`: the read's window start; None with no read, or a failed one) while the store
        holds that generation and `older` runs up to its oldest bar (else that read is incomplete:
        logged, and the store's bars alone), `PRIME_CHUNK_UPDATES` kernel updates at a time with a
        yield between, while the instance is not ready; then the closes held back meanwhile, as
        `emit` would have folded them, in chunks too (`_replay`), the ones that land between
        those included (module docstring). A reset or repair meanwhile, too many closes held back,
        or one it cannot place: the store's bars at once, within `MAX_SYNC_PRIME_UPDATES`
        (`_prime`)."""
        gen, stored = self._store_bars(inst.symbol, inst.bar_spec)
        bars: Bars = stored
        if gen != generation:  # no read, or one of another generation: the store's bars alone
            since_us = None
        elif older:
            first = stored[0][0] if stored else older[-1][0] + 1
            cut = bisect_left(older, first, key=itemgetter(0))  # `older` runs up (`_backfill`)
            if cut and older[cut - 1][0] != first - 1:  # it ends short of the store's oldest
                _log().warning(
                    "indicator_backfill_failed",
                    symbol=inst.symbol,
                    spec_hash=inst.req.key,
                    index=first,
                    error_type=HistoryIncompleteError.__name__,
                )
                since_us = None
            else:
                bars = [*older[:cut], *stored]
        key, spent = (inst.symbol, inst.req.key), 0.0
        held: list[tuple[int, BarUpdate]] = []  # `_closes` appends the closes that land
        inst.held, inst.dirty = held, False
        placed = True
        try:
            self._restart(inst, gen, since_us)
            keep = len(bars) - (inst.ring.maxlen or 0)  # only the ring's bars keep a checkpoint
            at: int | None = 0
            while at is not None and at < len(bars):
                started = time.perf_counter()
                at = self._fold(inst, bars, keep, bars[-1][0], start=at, budget=PRIME_CHUNK_UPDATES)
                spent += time.perf_counter() - started
                await asyncio.sleep(0)  # C-2.17: the loop runs between chunks
                if self._instances.get(key) is not inst:  # expired meanwhile
                    return
            while held and not inst.dirty:
                started = time.perf_counter()
                done = self._replay(inst, gen, held)
                spent += time.perf_counter() - started
                if done is None:
                    placed = False
                    break
                del held[:done]
                if held:  # C-2.17: the loop runs between chunks here too
                    await asyncio.sleep(0)
                    if self._instances.get(key) is not inst:
                        return
        finally:
            inst.held = None
        if inst.dirty or not placed:
            gen, stored = self._store_bars(inst.symbol, inst.bar_spec)
            self._prime(inst, gen, stored, budget=MAX_SYNC_PRIME_UPDATES)
            return
        inst.ready = True
        COMPUTE[inst.req.kernel.indicator].observe(spent)

    def _replay(
        self, inst: _Instance, gen: int | None, held: Sequence[tuple[int, BarUpdate]]
    ) -> int | None:
        """Fold the oldest of the closes held back while a read's fold ran, as `emit` would have,
        one chunk's worth (C-2.17): new bars until they take `PRIME_CHUNK_UPDATES` kernel updates
        (one bar's fillers are never split), or an amended bar alone, whose replay also restores a
        checkpoint (`_amend`). How many it folded; None at one of another generation than `gen`,
        or one the instance cannot place (`_update`)."""
        spent = 0
        for done, (generation, u) in enumerate(held):
            last, bar = inst.last, u.bar
            amends = inst.last_index is not None and bar.index <= inst.last_index
            if done and (amends or spent >= PRIME_CHUNK_UPDATES):
                return done
            if generation != gen or self._update(inst, u) is None:
                return None
            if amends:
                return done + 1
            spent += 1 + (0 if last is None else _fillers(last.t, bar.open_time, inst.step))
        return len(held)

    def _prime(
        self, inst: _Instance, gen: int | None, bars: Bars, *, budget: int | None = None
    ) -> None:
        """Fold `bars` (oldest first, of generation `gen`) into a fresh kernel, synchronously: no
        close can land in between. With `budget`, only the newest of them a fold of at most that
        many kernel updates reaches (`_within`): the kernel starts at the oldest of those, and a
        period that began before it is withheld (`_first`)."""
        started = time.perf_counter()
        cut = _within([x.t for _, x in bars], inst.step, budget) if budget and bars else 0
        self._restart(inst, gen, bars[cut - 1][1].t + 1 if cut else None)
        if cut < len(bars):
            keep = len(bars) - cut - (inst.ring.maxlen or 0)
            self._fold(inst, bars[cut:], keep, bars[-1][0])
        inst.ready = True
        COMPUTE[inst.req.kernel.indicator].observe(time.perf_counter() - started)

    def _restart(self, inst: _Instance, gen: int | None, since_us: int | None) -> None:
        """A fresh kernel with nothing folded, in generation `gen`; `since_us`: where the bars its
        fold covers start, when a read's window or a budget set it (`_first`)."""
        inst.kernel = self._kernel(inst.req, inst.context)
        inst.points.clear()
        inst.ring.clear()
        inst.last = inst.last_index = None
        inst.folded = inst.seq = 0
        inst.generation, inst.since_us, inst.complete_us = gen, since_us, None

    def _fold(
        self,
        inst: _Instance,
        bars: Bars,
        keep: int,
        newest: int,
        *,
        start: int = 0,
        budget: int | None = None,
    ) -> int | None:
        """Fold `bars` from position `start` into the instance, one point each, until the kernel
        updates it took (fillers included) reach `budget`, or to the end: the position to go on
        from. A bar at a position from `keep` on keeps a checkpoint (only the ring's bars need
        one). None when a kernel raised: counted and logged (`_failed`), and the instance restarts
        empty after bar `newest`."""
        gen, index, at, spent = inst.generation or 0, None, start, 0
        try:
            while at < len(bars) and (budget is None or spent < budget):
                index, x = bars[at]
                values, updates = self._advance(inst, index, x, checkpoint=at >= keep)
                inst.points.append(Point(gen, index, x.t, self._shown(inst, x.t, values)))
                spent += updates
                at += 1
        except Exception as exc:  # contained: the instance restarts empty after these bars
            self._failed(inst, index, exc, "indicator_prime_failed")
            inst.kernel = self._kernel(inst.req, inst.context)
            inst.points.clear()
            inst.ring.clear()
            inst.last, inst.last_index, inst.since_us = None, newest, None
            inst.folded = inst.seq = 0
            return None
        return at

    def _failed(self, inst: _Instance, index: int | None, exc: Exception, event: str) -> None:
        """Count (`bar_emit_sink_errors_total{reason="indicators"}`) and log a kernel failure."""
        bar_emit_sink_errors_total.labels(reason=self.name).inc()
        _log().error(
            event,
            symbol=inst.symbol,
            spec_hash=inst.req.key,
            index=index,
            error_type=type(exc).__name__,
        )

    def _reprime_series(self, symbol: str, spec: BarSpec, reason: Reprime) -> None:
        """Re-prime every ready instance of the series (`backfill`) and re-snapshot it; one whose
        read's fold is under way ends with the store's bars (`_fold_read`). A re-prime that needs
        a full recompute (`_plan`) runs one when a slot is free; else it folds the store's bars
        at once, within `MAX_SYNC_PRIME_UPDATES` split evenly across the instances (C-2.17)."""
        series = (symbol, spec.spec_hash)
        on_series = self._series.get(series, {})
        for inst in on_series.values():
            if inst.held is not None:
                inst.dirty = True
        insts = [i for i in on_series.values() if i.ready]
        if not insts:
            return
        RECOMPUTES["backfill"].inc(len(insts))
        task = self._plan(symbol, spec, [(i.req.warmup() + i.history, i.anchor_us) for i in insts])
        if task is not None and self._slot():
            for inst in insts:
                inst.ready = False  # its snapshots wait for the recompute (`ready`)
            self._spawn(symbol, spec, insts, task)
        else:
            gen, bars = self._store_bars(symbol, spec)
            budget = None if task is None else MAX_SYNC_PRIME_UPDATES // len(insts)
            for inst in insts:
                self._prime(inst, gen, bars, budget=budget)
        self._bump(series)
        if self._listener is not None:
            self._listener.resnapshot(symbol, spec, reason)

    def history_repair(self, symbol: str, spec: BarSpec, min_history: int) -> None:
        """The series store's repair hook (#2787 D2-H1, 23 §7.4): a re-read added or replaced bars
        of the series, so each instance re-primes and its subscribers re-snapshot. Synchronous."""
        if (symbol, spec.spec_hash) in self._series:
            self._reprime_series(symbol, spec, "history_repair")

    # -- the emit path ---------------------------------------------------------------------------

    async def emit(self, emission: BarEmission) -> None:
        """`BarSink` (module docstring); never awaits: O(1) per update of a series no instance
        reads, and closes only (only closed bars are served, 23 §6.1). First, at most every
        `SWEEP_EVERY_US`, it removes the instances whose grace has ended (`_sweep`)."""
        now = self._now_us()
        if now - self._swept_us >= SWEEP_EVERY_US:
            self._sweep(now)
        h = emission.spec.spec_hash
        closes: dict[str, list[BarUpdate]] = {}
        for u in emission.updates:
            if u.kind == "close" and (u.bar.symbol, h) in self._series:
                closes.setdefault(u.bar.symbol, []).append(u)
        for symbol, updates in closes.items():
            self._closes(symbol, emission.spec, emission.generation, updates)

    def _closes(
        self, symbol: str, spec: BarSpec, generation: int, updates: list[BarUpdate]
    ) -> None:
        series = (symbol, spec.spec_hash)
        seen, top = self._newest.get(series), max(u.bar.index for u in updates)
        if seen is None or seen[0] != generation or top > seen[1]:
            self._newest[series] = (generation, top)
        on_series = self._series[series]
        for inst in on_series.values():
            if inst.held is not None and not inst.dirty:  # a read's fold: `_fold_read` folds them
                if len(inst.held) + len(updates) > MAX_POINTS:
                    inst.dirty = True
                else:
                    inst.held.extend((generation, u) for u in updates)
        insts = [i for i in on_series.values() if i.ready]
        if any(i.generation is not None and i.generation != generation for i in insts):
            self._reprime_series(symbol, spec, "generation_swap")  # the store reset first
            return
        batches: dict[str, Batch] = {}
        reset = False
        for inst in insts:
            inst.generation = generation
            started = time.perf_counter()
            points: list[Point] = []
            for u in updates:
                got = self._update(inst, u)
                if got is None:
                    reset = True
                    break
                points.extend(got)
            COMPUTE[inst.req.kernel.indicator].observe(time.perf_counter() - started)
            if points:
                batches[inst.req.key] = Batch(inst.info, tuple(points))
        if reset:  # a bar the instance cannot place: the whole series re-primes, then snapshots
            self._reprime_series(symbol, spec, "history_repair")
            return
        self._bump(series)
        if batches and self._listener is not None:
            self._listener.points(symbol, spec, batches)

    def _update(self, inst: _Instance, u: BarUpdate) -> list[Point] | None:
        """One close into one instance: its new or amended points, or None when it must re-prime
        (a bar it cannot place, or an update that raised: counted and logged)."""
        bar = u.bar
        try:
            x = bar_input(bar)
            if inst.last_index is not None and bar.index <= inst.last_index:
                return self._amend(inst, bar.index, x)
            values, _ = self._advance(inst, bar.index, x)
        except Exception as exc:  # contained to this instance: the others still get the close
            self._failed(inst, bar.index, exc, "indicator_update_failed")
            return None
        shown = self._shown(inst, x.t, values)
        point = Point(inst.generation or 0, bar.index, bar.open_time, shown)
        inst.points.append(point)
        inst.last_index = bar.index
        return [point]

    def _advance(
        self, inst: _Instance, index: int, x: BarInput, *, checkpoint: bool = True
    ) -> tuple[Outputs, int]:
        """Fold a real bar, after its fillers, keeping the ring of a time series: its values, and
        the kernel updates that took (the bar and its fillers)."""
        fills = _fill(inst.last, x.t, inst.step)
        entry: _Entry | None = None
        if inst.ring.maxlen:
            entry = _Entry(index, x)
            if checkpoint and inst.seq % CHECKPOINT_EVERY == 0:
                entry.checkpoint, entry.prev = inst.kernel.snapshot(), inst.last
                entry.folded = inst.folded
            inst.seq += 1
        if fills is None or inst.last is None:  # the kernel's first bar
            self._first(inst, index, x.t, restarted=fills is None)
        if fills is None:  # a gap past `MAX_FILL_SLOTS`: the kernel restarts at this bar
            inst.kernel, inst.folded = self._kernel(inst.req, inst.context), 0
            fills = []
        else:
            for f in fills:
                inst.kernel.update(f)
            inst.folded += len(fills)
        values = inst.kernel.update(x)
        inst.folded += 1
        inst.last, inst.last_index = x, index
        if entry is not None:
            entry.values = values
            inst.ring.append(entry)
        return values, 1 + len(fills)

    @staticmethod
    def _first(inst: _Instance, index: int, t: int, *, restarted: bool) -> None:
        """A kernel's first bar, at open time `t`: a session-anchored instance holds periods
        whole (`complete_us`): every one when this is the generation's first bar; else those from
        where its fold's bars start, when a read's window or a budget set that (just past the
        newest bar it left out); else those from `t`. After a restart (a gap past
        `MAX_FILL_SLOTS`) it holds them from `t`, or from the start of `t`'s period when the gap
        began in an earlier one: no bar of that period precedes this one (module docstring)."""
        if inst.anchor_us is None or (index == 0 and not restarted):
            return
        if restarted:
            start = session_start(t, inst.anchor_us)
            known = start if inst.last is not None and start > inst.last.t else t
        else:
            known = t if inst.since_us is None else inst.since_us
        inst.complete_us = known if inst.complete_us is None else max(inst.complete_us, known)

    def _amend(self, inst: _Instance, index: int, x: BarInput) -> list[Point] | None:
        """Replay from the newest checkpoint at or before the bar (module docstring): the points
        that changed, with `amended: true`; [] when the bar did not change; None to re-prime (a
        bar the ring cannot place, or a replay past `MAX_AMEND_UPDATES` kernel updates, C-2.17)."""
        ring = inst.ring
        pos = next((q for q in range(len(ring) - 1, -1, -1) if ring[q].index == index), None)
        if pos is None or ring[pos].input.t != x.t:
            return None
        start = next((q for q in range(pos, -1, -1) if ring[q].checkpoint is not None), None)
        if start is None:
            return None
        if ring[pos].input == x:
            return []
        base = ring[start]
        times = [ring[q].input.t for q in range(start, len(ring))]  # x opens when its entry does
        lead = 0 if base.prev is None else _fillers(base.prev.t, times[0], inst.step)
        if lead + _updates(times, inst.step) > MAX_AMEND_UPDATES:
            return None
        kernel = self._kernel(inst.req, inst.context)
        kernel.restore(base.checkpoint or b"")
        last, folded = base.prev, base.folded
        changed: list[Point] = []
        for q in range(start, len(ring)):
            e = ring[q]
            bar = x if q == pos else e.input
            if q > pos and e.checkpoint is not None:
                e.checkpoint, e.prev, e.folded = kernel.snapshot(), last, folded
            fills = _fill(last, bar.t, inst.step)
            if fills is None:
                kernel, folded = self._kernel(inst.req, inst.context), 0
            else:
                for f in fills:
                    kernel.update(f)
                folded += len(fills)
            values = kernel.update(bar)
            folded += 1
            e.input, last = bar, bar
            if q >= pos and values != e.values:
                before, e.values = e.values, values
                shown = self._shown(inst, bar.t, values)
                if shown != self._shown(inst, bar.t, before):
                    gen = inst.generation or 0
                    changed.append(Point(gen, e.index, bar.t, shown, amended=True))
        inst.kernel, inst.last, inst.folded = kernel, last, folded
        _replace(inst.points, changed)
        RECOMPUTES["amended"].inc()
        return changed

    @staticmethod
    def _withheld(inst: _Instance, t: int) -> bool:
        """True on a bar of an anchor period the instance did not fold from its start."""
        return (
            inst.anchor_us is not None
            and inst.complete_us is not None
            and session_start(t, inst.anchor_us) < inst.complete_us
        )

    @classmethod
    def _shown(cls, inst: _Instance, t: int, values: Outputs) -> Outputs:
        """`values` as served: all `None` on a bar `_withheld` keeps back."""
        return (None,) * len(values) if cls._withheld(inst, t) else values

    # -- reads -----------------------------------------------------------------------------------

    def read(
        self, symbol: str, spec_hash: str, output: str | None = None
    ) -> Available | Unavailable:
        """The newest value of an instance's output (its first by default), or why there is none
        (module docstring)."""
        inst = self._instances.get((symbol, spec_hash))
        if inst is None or not inst.ready or not inst.points:
            return Unavailable("missing")
        if self._parity is not None and self._parity(symbol, spec_hash):
            return Unavailable("parity_flagged")
        point = inst.points[-1]
        newest = self._newest.get((symbol, inst.bar_spec.spec_hash))
        if newest is not None and (
            newest[0] != point.generation or newest[1] - point.index > STALE_AFTER_BARS
        ):
            return Unavailable("stale")
        outputs = inst.req.kernel.outputs
        if output is not None and output not in outputs:
            return Unavailable("missing")
        value = point.values[0 if output is None else outputs.index(output)]
        if value is None:
            warming = inst.folded < inst.req.warmup() or self._withheld(inst, point.t_us)
            return Unavailable("warmup" if warming else "nan")
        if not math.isfinite(value):
            return Unavailable("nan")
        return Available(value, point.generation, point.index, inst.req.kernel.build_version)

    def snapshot(self, symbol: str, spec_hash: str, history: int) -> Batch | None:
        """An instance's newest `history` points, oldest first; None while it is not ready."""
        inst = self._instances.get((symbol, spec_hash))
        if inst is None or not inst.ready:
            return None
        newest = list(itertools.islice(reversed(inst.points), max(history, 0)))
        newest.reverse()
        return Batch(inst.info, tuple(newest))

    def version(self, symbol: str, bar_spec_hash: str) -> int:
        """The series' change counter: it moves whenever any of its instances changes."""
        return self._versions.get((symbol, bar_spec_hash), 0)

    def _bump(self, series: Key) -> None:
        self._versions[series] = next(self._counter)


def _replace(points: deque[Point], changed: Sequence[Point]) -> None:
    """Put amended points in place of the ones with their index (the newest end of `points`)."""
    if not changed:
        return
    by_index = {p.index: p for p in changed}
    oldest = min(by_index)
    for i in range(len(points) - 1, -1, -1):
        held = points[i].index
        if held < oldest:
            break
        if held in by_index:
            points[i] = by_index[held]
