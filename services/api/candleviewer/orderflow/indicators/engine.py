"""The indicator engine: shared server instances, updated once per bar close (E13-T02, #426;
ADR-0034; 24-internal-schemas §7.3, §7.4; 23-ws-protocol §6.1).

`IndicatorEngine` is the fourth `BarSink` on the bars `EmitRouter`: series store, WS bars
publisher, this, then the writer (20-architecture §4.2). Its `emit` never awaits, like the WS
sinks, so a close reaches every instance of its series before the next emission.

- **Memo (24 §7.3).** One instance per `(symbol, spec_hash)`. The `spec_hash` holds the bar
  series' own (§7.4), so that is one per `(symbol, bar spec_hash, indicator spec_hash)`. Every
  consumer shares it (WS subscriptions now; S08, E35 and E40 later), and each close updates it
  once. `indicator_cache_hits_total` / `_misses_total` count the joins and the starts.
- **Admission.** `resolve_instances` checks a request against the catalogue before anything is
  held: a `compute: server` indicator, its `params_schema` (`validate_params`, never clamped), a
  series a session anchor can read (not renko), no instance twice. `check` applies the window
  bound (SR-E13-04) and the caps (`leases`, SR-E13-03); `admit` checks again, takes the leases and
  starts each new instance. Kernels are built here only, from validated parameters.
- **Priming.** A new instance folds the closed bars the series store holds (up to 1 000, of the
  series' current generation). When its warmup plus the subscription's history needs older bars
  and the generation has them (the store's oldest index is above 0), a full recompute reads them
  (`HistoryRead`, time series only) on one of `MAX_CONCURRENT_RECOMPUTES` slots, in a task the
  engine owns. With every slot taken the admission is refused, never queued. The instance is not
  ready until the read ends: its snapshots wait, and the listener's `ready` flushes them. A read
  that fails or passes `RECOMPUTE_TIMEOUT_S` primes from the store alone (logged). Only read bars
  older than the store's oldest are folded: the store, ahead of the engine on the emit path, holds
  every close since.
- **Time series** are densified as `BarSeries.densify()` does: a filler, flat at the previous close
  with no volume, advances the kernel and publishes no point. A gap of more than `MAX_FILL_SLOTS`
  empty slots restarts the kernel at the bar after it (a new warmup follows) rather than fold that
  many fillers on the emit path. Other kinds are never densified.
- **Amended closes** (time bars, within the builder's 60 s window). A time-series instance keeps
  its last real bars, enough for that window at its interval plus `CHECKPOINT_EVERY`, with a kernel
  snapshot before every `CHECKPOINT_EVERY`th. An amended close restores the newest checkpoint at or
  before the bar, folds forward with the new bar, and publishes each point whose value changed with
  `amended: true` (`indicator_recompute_total{reason="amended"}`). A close of a bar the ring does
  not hold (older, or another bar at a held index) re-primes the series' instances, which then
  re-snapshot as after a store repair (`history_repair`).
- **Generations and repairs.** A close in another generation than an instance's is a swap: every
  instance of the series re-primes from the store (which reset first), and the listener
  re-snapshots the series (`generation_swap`). A store repair re-primes it too (`history_repair`,
  the store's repair hook). A re-prime counts `reason="backfill"`; one that needs a read and finds
  no free slot primes from the store alone.
- **Reads.** `read` returns `Available(value, generation, index, build_version)` or `Unavailable`:
  `missing` (no ready instance), `parity_flagged` (an injected hook, never by default), `stale`
  (more than `STALE_AFTER_BARS` closes behind its series, or another generation), `warmup`, or
  `nan` (no value after the warmup: a zero divisor). S08's `resolve()` builds on it (IR-45).

Bounds (C-2.18): instances by the caps, each with at most `MAX_POINTS` points and its ring;
recompute tasks by the slots; each read by `RECOMPUTE_TIMEOUT_S`. The state is in memory only:
a restart re-primes (24 §7.4). An instance update that raises is counted
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
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.limits import MAX_TAIL
from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.reader import MAX_LIMIT, BarKey, BarPage, stored_bar
from candleviewer.bars.series_store import Latest
from candleviewer.bars.time_builder import LATE_WINDOW_US
from candleviewer.observability.context import spawn
from candleviewer.orderflow.errors import (
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
from candleviewer.orderflow.indicators.kernel import Kernel
from candleviewer.orderflow.indicators.kernels import build_kernel
from candleviewer.orderflow.indicators.leases import InstanceLeases
from candleviewer.orderflow.indicators.limits import (
    MAX_CONCURRENT_RECOMPUTES,
    MAX_WINDOW_BARS,
    RECOMPUTE_TIMEOUT_S,
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

#: The most points an instance keeps: the WS `history` cap (23 §6.1), so any snapshot is whole.
MAX_POINTS: Final = MAX_TAIL
#: A time-series instance keeps a kernel snapshot before every this-many real bars.
CHECKPOINT_EVERY: Final = 8
#: More empty slots than this in one time-series gap restart the kernel instead of being filled.
MAX_FILL_SLOTS: Final = 1_000
#: A read of an instance more than this many closes behind its series is `stale`.
STALE_AFTER_BARS: Final = 2

Reprime = Literal["generation_swap", "history_repair"]
Key = tuple[str, str]  # (symbol, spec_hash): an instance, or a series by its bar spec_hash

#: `(symbol, spec, generation, start_us, end_us) -> [(index, bar)]`: the closed tape-built bars of
#: that generation opening in `[start_us, end_us)`, oldest first (`stored_history`).
HistoryRead = Callable[[str, BarSpec, int, int, int], Awaitable[Sequence[tuple[int, BarInput]]]]

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
    """The slice of `bars.reader.BarReader` `stored_history` reads through."""

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


def stored_history(reader: RangeReader, *, max_rows: int = MAX_WINDOW_BARS) -> HistoryRead:
    """`HistoryRead` over `BarReader.read_bars` (parameterised SQL only): pages of at most
    `MAX_LIMIT` rows and `max_rows` in all, keeping the closed tape-built bars of the generation."""

    async def read(
        symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> Sequence[tuple[int, BarInput]]:
        out: list[tuple[int, BarInput]] = []
        after: int | None = None
        taken = 0
        while taken < max_rows:
            limit = min(MAX_LIMIT, max_rows - taken)
            page = await reader.read_bars(symbol, spec, start_us, end_us, limit, after_us=after)
            taken += len(page.rows)
            for row in page.rows:
                s = stored_bar(row)
                if not (s.tape_built and s.confirmed and s.generation == generation):
                    continue
                if s.index is None or s.delta is None:
                    continue
                values = (s.open, s.high, s.low, s.close, s.volume, s.delta)
                o, h, lo, c, v, d = (float(x) for x in values)
                out.append((s.index, BarInput(s.ts_us, o, h, lo, c, v, d, False)))
            if page.next_cursor is None:
                break
            after = page.next_cursor
        return out

    return read


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
    ready: bool = False
    generation: int | None = None
    points: deque[Point] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    last: BarInput | None = None
    last_index: int | None = None
    folded: int = 0  # densified bars folded since the kernel started (warmup)
    seq: int = 0  # ring entries ever appended (the checkpoint cadence)


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
        `MAX_WINDOW_BARS` (`RecomputeRefusedError` `window`), a cap (`InstanceCapError`), and a
        new instance that needs a read with no slot free (`RecomputeRefusedError` `recompute`;
        decided from the store, so only once the series is held). `consumer`: one that replaces its
        own instances (`leases.check`). Changes nothing."""
        self._sweep()
        for r in requested:
            if r.warmup() + history > MAX_WINDOW_BARS:
                CAP_REJECTED["window"].inc()
                message = f"{r.definition.id} needs more than {MAX_WINDOW_BARS} bars."
                raise RecomputeRefusedError("window", message)
        self._leases.check(symbol, [r.key for r in requested], user, consumer)
        if self._read_for(symbol, spec, requested, history) is not None and not self._reader():
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
        (module docstring). With `replacing`, the consumer's leases on those keys are released
        once the new ones are held (a WS `ctl`), and `reason` counts each instance it starts.
        Nothing is held when it raises. The series must be held in the store."""
        mine = consumer if replacing else None
        self.check(symbol, spec, requested, user, history=history, consumer=mine)
        window = self._read_for(symbol, spec, requested, history)
        new = [r for r in requested if (symbol, r.key) not in self._instances]
        for r in requested:
            started = self._leases.acquire((symbol, r.key), consumer, user)
            (indicator_cache_misses_total if started else indicator_cache_hits_total).inc()
            inst = self._instances.get((symbol, r.key))
            if inst is not None:
                inst.history = max(inst.history, history)
        fresh = [self._start(symbol, spec, r, history) for r in new]
        keys = {r.key for r in requested}
        self.release(symbol, [k for k in replacing if k not in keys], consumer)
        if reason is not None and fresh:
            RECOMPUTES[reason].inc(len(fresh))
        read = self._reader()
        if window is None or read is None:  # `check` refused a read with no reader
            for inst in fresh:
                self._prime(inst)
        else:
            self._spawn(read, symbol, spec, fresh, window)
        self._bump((symbol, spec.spec_hash))

    def _read_for(
        self, symbol: str, spec: BarSpec, requested: Sequence[Requested], history: int
    ) -> tuple[int, int, int] | None:
        """The read that starting the new instances of `requested` takes (`_window`), if any."""
        new = [(r.warmup(), history) for r in requested if (symbol, r.key) not in self._instances]
        return self._window(symbol, spec, new)

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
        for key in self._leases.expired(self._now_us() if now is None else now):
            inst = self._instances.pop(key, None)
            if inst is None:
                continue
            series = (inst.symbol, inst.bar_spec.spec_hash)
            on_series = self._series.get(series, {})
            on_series.pop(inst.req.key, None)
            if not on_series:  # a later instance starts from a fresh, higher version
                self._series.pop(series, None)
                self._newest.pop(series, None)
                self._versions.pop(series, None)

    def _start(self, symbol: str, spec: BarSpec, r: Requested, history: int) -> _Instance:
        context = KernelContext(session_anchor_utc_min=spec.session_anchor_utc_min)
        step = _step_us(spec)
        inst = _Instance(
            r, r.info(), symbol, spec, context, self._kernel(r, context), step,
            deque(maxlen=_ring_size(step)), history,
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

    def _window(
        self, symbol: str, spec: BarSpec, needs: Sequence[tuple[int, int]]
    ) -> tuple[int, int, int] | None:
        """`(generation, start_us, end_us)` of the read that priming `needs` (warmup, history)
        takes, or None when the store's bars suffice (module docstring)."""
        step = _step_us(spec)
        if not needs or self._history is None or not step:
            return None
        latest = self._latest(symbol, spec)
        if latest is None or latest.generation is None or not latest.closed:
            return None
        oldest, newest = latest.closed[0], latest.closed[-1]
        need = max(warmup + history for warmup, history in needs)
        held = (newest.open_time - oldest.open_time) // step + 1
        if oldest.index == 0 or need <= held:
            return None
        return latest.generation, newest.open_time - (need - 1) * step, newest.open_time + 1

    def _reader(self) -> HistoryRead | None:
        """The stored-bar read when a slot is free to run it now, else None."""
        if self._history is None or self._stopping or self._busy >= self._slots:
            return None
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # no loop to run the read on
            return None
        return self._history

    def _spawn(
        self,
        read: HistoryRead,
        symbol: str,
        spec: BarSpec,
        insts: list[_Instance],
        window: tuple[int, int, int],
    ) -> None:
        """Take a slot and run the read and the priming in a task the engine owns."""
        self._busy += 1
        task = spawn(self._backfill(read, symbol, spec, insts, window), name="indicator-backfill")
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        """A recompute task ended, however (a cancelled one may never have started): its slot
        is free again, and an error that escaped it is logged."""
        self._tasks.discard(task)
        self._busy -= 1
        if not task.cancelled() and (exc := task.exception()) is not None:
            _log().error("indicator_backfill_crashed", error_type=type(exc).__name__)

    async def _backfill(
        self,
        read: HistoryRead,
        symbol: str,
        spec: BarSpec,
        insts: list[_Instance],
        window: tuple[int, int, int],
    ) -> None:
        generation, start, end = window
        rows: Sequence[tuple[int, BarInput]] = ()
        try:
            async with asyncio.timeout(RECOMPUTE_TIMEOUT_S):
                rows = await read(symbol, spec, generation, start, end)
        except Exception as exc:  # primed from the store alone, logged; a cancellation raises
            _log().warning(
                "indicator_backfill_failed",
                symbol=symbol,
                spec_hash=spec.spec_hash,
                error_type=type(exc).__name__,
            )
        for inst in insts:
            if self._instances.get((symbol, inst.req.key)) is inst:  # not expired meanwhile
                self._prime(inst, generation, rows)
        self._bump((symbol, spec.spec_hash))
        if self._listener is not None:
            self._listener.ready(symbol, spec)

    def _prime(
        self,
        inst: _Instance,
        generation: int | None = None,
        older: Sequence[tuple[int, BarInput]] = (),
    ) -> None:
        """Fold the store's closed bars, after `older` ones of `generation` that predate them,
        into a fresh kernel. Synchronous: no close can land in between."""
        started = time.perf_counter()
        latest = self._latest(inst.symbol, inst.bar_spec)
        gen = None if latest is None else latest.generation
        closed = [] if latest is None or gen is None else latest.closed
        first = closed[0].index if closed else None
        bars = [] if gen is None or gen != generation else [
            (i, b) for i, b in older if first is None or i < first
        ]  # fmt: skip
        bars.sort(key=lambda pair: pair[0])
        bars.extend((b.index, bar_input(b)) for b in closed)
        inst.kernel = self._kernel(inst.req, inst.context)
        inst.points.clear()
        inst.ring.clear()
        inst.last = inst.last_index = None
        inst.folded = inst.seq = 0
        inst.generation = gen
        keep = len(bars) - (inst.ring.maxlen or 0)  # only the ring's bars keep a checkpoint
        index: int | None = None
        try:
            for position, (index, x) in enumerate(bars):
                values = self._advance(inst, index, x, checkpoint=position >= keep)
                inst.points.append(Point(gen or 0, index, x.t, values))
        except Exception as exc:  # contained: the instance restarts empty after these bars
            self._failed(inst, index, exc, "indicator_prime_failed")
            inst.kernel = self._kernel(inst.req, inst.context)
            inst.points.clear()
            inst.ring.clear()
            inst.last, inst.last_index = None, bars[-1][0]
            inst.folded = inst.seq = 0
        inst.ready = True
        COMPUTE[inst.req.kernel.indicator].observe(time.perf_counter() - started)

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
        """Re-prime every ready instance of the series (`backfill`) and re-snapshot it."""
        series = (symbol, spec.spec_hash)
        insts = [i for i in self._series.get(series, {}).values() if i.ready]
        if not insts:
            return
        RECOMPUTES["backfill"].inc(len(insts))
        window = self._window(symbol, spec, [(i.req.warmup(), i.history) for i in insts])
        read = self._reader()
        if window is not None and read is not None:
            for inst in insts:
                inst.ready = False  # its snapshots wait for the read (`ready`)
            self._spawn(read, symbol, spec, insts, window)
        else:
            for inst in insts:
                self._prime(inst)
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
        reads, and closes only (only closed bars are served, 23 §6.1)."""
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
        insts = [i for i in self._series[series].values() if i.ready]
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
            values = self._advance(inst, bar.index, x)
        except Exception as exc:  # contained to this instance: the others still get the close
            self._failed(inst, bar.index, exc, "indicator_update_failed")
            return None
        point = Point(inst.generation or 0, bar.index, bar.open_time, values)
        inst.points.append(point)
        inst.last_index = bar.index
        return [point]

    def _advance(
        self, inst: _Instance, index: int, x: BarInput, *, checkpoint: bool = True
    ) -> Outputs:
        """Fold a real bar, after its fillers, keeping the ring of a time series."""
        fills = _fill(inst.last, x.t, inst.step)
        entry: _Entry | None = None
        if inst.ring.maxlen:
            entry = _Entry(index, x)
            if checkpoint and inst.seq % CHECKPOINT_EVERY == 0:
                entry.checkpoint, entry.prev = inst.kernel.snapshot(), inst.last
                entry.folded = inst.folded
            inst.seq += 1
        if fills is None:  # a gap past `MAX_FILL_SLOTS`: the kernel restarts at this bar
            inst.kernel, inst.folded = self._kernel(inst.req, inst.context), 0
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
        return values

    def _amend(self, inst: _Instance, index: int, x: BarInput) -> list[Point] | None:
        """Replay from the newest checkpoint at or before the bar (module docstring): the points
        that changed, with `amended: true`; [] when the bar did not change; None to re-prime."""
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
                e.values = values
                changed.append(Point(inst.generation or 0, e.index, bar.t, values, amended=True))
        inst.kernel, inst.last, inst.folded = kernel, last, folded
        _replace(inst.points, changed)
        RECOMPUTES["amended"].inc()
        return changed

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
            return Unavailable("warmup" if inst.folded < inst.req.warmup() else "nan")
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

    def instances(self, symbol: str, bar_spec_hash: str) -> int:
        """Instances running on a series (in their grace too)."""
        return len(self._series.get((symbol, bar_spec_hash), {}))

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
