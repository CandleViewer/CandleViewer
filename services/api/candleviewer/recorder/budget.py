"""`DiskBudget` — measured growth, projection and the disk-pressure ladder (E16-T07).

SR-096 / threat S2 (Critical), ADR-0015 decision 6, `21-database-schema.md` §6. The fit
rules, the thresholds and the `DiskPressureChanged` contract are owned by
`24-internal-schemas.md` §13.4.1; this module implements them as pure, synchronous code
(C-2.20: no statechart): an exact integer least-squares fit with one intercept per
contiguous run, the projection to the earlier wall, and the hysteresis ladder whose plain
`level` / `accelerate` hot-path readers consume. `DiskBudget` drives them from one
supervised sampling task; a request reads `report()` and never measures (SCR-142).
"""

from __future__ import annotations

import asyncio
import re
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Final, Protocol, cast

import structlog

from candleviewer.bus.models import Topic
from candleviewer.observability import spawn
from candleviewer.recorder.metrics import (
    disk_free_bytes,
    disk_used_ratio,
    recorder_bytes_per_day,
    recorder_disk_budget_breakdown_age_seconds,
    recorder_disk_budget_last_sample_timestamp_seconds,
    recorder_disk_pressure_level,
    recorder_projected_full_timestamp,
)
from candleviewer.recorder.models import (
    DiskPressureChanged,
    DiskPressureLevel,
    StorageUsage,
    SymbolUsage,
    TierName,
    TierUsage,
)
from candleviewer.storage.cold.observability import Severity, SystemEventSink
from candleviewer.storage.errors import StorageError

US_PER_S: Final = 1_000_000
US_PER_DAY: Final = 86_400 * US_PER_S
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_RUNWAY_DAYS: Final = 36_500
_PCT: Final = 100  # every threshold is an integer percentage
_LADDER: Final = (DiskPressureLevel.WARN, DiskPressureLevel.AUTOSTOP, DiskPressureLevel.HALT)
#: Suggested actions named by every ladder event: codes only, never host paths.
SUGGESTED_ACTIONS: Final = "reduce_depth,shorten_retention,unpin"
_RECORDED: Final[tuple[TierName, ...]] = ("questdb", "parquet")
_TIERS: Final[tuple[TierName, ...]] = ("questdb", "parquet", "postgres")
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")  # OpenAPI `Symbol`
#: What the series store may raise when its volume or file is unavailable.
_UNAVAILABLE: Final = (OSError, TimeoutError, StorageError)
_LEVEL_EVENT: Final[dict[DiskPressureLevel, tuple[Severity, str]]] = {
    DiskPressureLevel.WARN: ("WARNING", "recorder.disk_budget_warning"),
    DiskPressureLevel.AUTOSTOP: ("WARNING", "recorder.disk_autostop"),
    DiskPressureLevel.HALT: ("CRITICAL", "recorder.disk_halt"),
}


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


@dataclass(frozen=True, slots=True)
class BudgetConfig:
    """`CV_DISK_*` keys (20-architecture.md §7.2); percentages are integer points."""

    cap_bytes: int
    warn_pct: int = 80
    autostop_pct: int = 90
    halt_pct: int = 95
    autostop_free_pct: int = 15
    halt_free_pct: int = 5
    #: Every trigger re-arms this many points on the safe side of it.
    rearm_pct: int = 5
    #: `accelerate_retention` holds until used < 100 - this and free > this (21 §6).
    accelerate_until_free_pct: int = 25
    warn_runway_days: int = 7
    warn_runway_rearm_days: int = 1
    sample_interval_s: float = 60.0
    series_step_s: int = 600
    fit_window_s: int = 7 * 86_400
    fallback_window_s: int = 86_400
    min_fit_span_s: int = 3_600
    #: Largest symbols attributed per sample (memory and metric-cardinality bound).
    max_symbols: int = 64
    io_timeout_s: float = 10.0
    #: The best-effort per-tier / per-symbol breakdown; never delays the free-space path.
    breakdown_timeout_s: float = 5.0
    hot_days: int = 7
    retention_days: int = 30

    def __post_init__(self) -> None:
        cap_path = self.rearm_pct < self.warn_pct < self.autostop_pct < self.halt_pct <= _PCT
        free_path = 0 < self.halt_free_pct < self.autostop_free_pct < self.accelerate_until_free_pct
        free_path = free_path and self.autostop_free_pct + self.rearm_pct <= _PCT
        if self.cap_bytes <= 0 or not (cap_path and free_path) or self.sample_interval_s <= 0:
            raise ValueError(
                "disk budget: cap > 0, rearm < warn < autostop < halt <= 100,"
                " 0 < halt_free < autostop_free < accelerate_until_free,"
                " autostop_free + rearm <= 100"
            )

    @property
    def hole_us(self) -> int:
        """A gap between committed points longer than this is a sampling hole."""
        return int(self.series_step_s + 3 * self.sample_interval_s) * US_PER_S


@dataclass(frozen=True, slots=True)
class Measurement:
    """One meter pass: the recording volume plus per-tier / per-symbol bytes."""

    total_bytes: int
    free_bytes: int
    tiers: Mapping[TierName, int]
    symbols: Mapping[str, int]

    def __post_init__(self) -> None:
        if not 0 <= self.free_bytes <= self.total_bytes or self.total_bytes <= 0:
            raise ValueError("volume measurement must satisfy 0 <= free <= total, total > 0")


@dataclass(frozen=True, slots=True)
class Breakdown:
    """Best-effort per-tier / per-symbol bytes (QuestDB table sizes, Parquet partition walk)."""

    tiers: Mapping[TierName, int]
    symbols: Mapping[str, int]


class StorageMeter(Protocol):
    """`volume()` (`statvfs`, the ladder's free-space input) is read first and alone; the
    `breakdown()` is best effort. Never a shell-out (SR-096)."""

    async def volume(self) -> tuple[int, int]:
        """`(total_bytes, free_bytes)` of the recording volume."""
        ...

    async def breakdown(self) -> Breakdown: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Point:
    """One committed series point: recorded bytes (QuestDB + Parquet) and per-symbol bytes."""

    ts_us: int
    recorded_bytes: int
    symbols: tuple[tuple[str, int], ...]


class SeriesStore(Protocol):
    """Persistence of the rolling series, so a restart keeps the measured history."""

    async def load(self, since_us: int) -> Sequence[Point]: ...

    async def append(self, point: Point) -> None: ...


class PressurePublisher(Protocol):
    async def publish(self, topic: Topic, event: DiskPressureChanged) -> None: ...


#: `(from_us, to_us) -> [(lo_us, hi_us)]`: `recording_gaps` windows overlapping the range.
GapSource = Callable[[int, int], Awaitable[Sequence[tuple[int, int]]]]
#: Symbols with `recorded_symbols.pinned`.
PinnedSource = Callable[[], Awaitable[frozenset[str]]]


def _merged(gaps: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(gaps):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _terms(n: int, st: int, sy: int, stt: int, sty: int) -> tuple[Fraction, Fraction]:
    """One run's least-squares numerator and denominator, from exact integer sums."""
    return Fraction(n * sty - st * sy, n), Fraction(n * stt - st * st, n)


def fit_daily_growth(
    points: Sequence[tuple[int, int]],
    *,
    hole_us: int,
    gaps: Sequence[tuple[int, int]] = (),
    restart_on_drop: bool = False,
) -> int | None:
    """Least-squares bytes/day with one intercept per contiguous run, in exact integer sums.

    One pass over time-ordered points, O(points + gaps). Points inside a gap `[lo, hi)` are
    dropped; a run restarts across a gap, at a sampling hole (> `hole_us`) and, with
    `restart_on_drop`, at every size drop (retention), which makes the slope a write rate.
    `None` when no run has any time spread."""
    windows, g = _merged(gaps), 0
    num = den = Fraction(0)
    n = st = sy = stt = sty = t0 = 0
    prev: tuple[int, int] | None = None
    for t, y in points:
        crossed = g
        while g < len(windows) and windows[g][1] <= t:
            g += 1
        if g < len(windows) and windows[g][0] <= t:
            prev = None
            continue
        restart = prev is None or g != crossed or t - prev[0] > hole_us
        if restart or (restart_on_drop and prev is not None and y < prev[1]):
            if n:
                a, b = _terms(n, st, sy, stt, sty)
                num, den = num + a, den + b
            n = st = sy = stt = sty = 0
            t0 = t
        s = (t - t0) // US_PER_S
        n, st, sy, stt, sty = n + 1, st + s, sy + y, stt + s * s, sty + s * y
        prev = (t, y)
    if n:
        a, b = _terms(n, st, sy, stt, sty)
        num, den = num + a, den + b
    return None if den == 0 else round(num / den * 86_400)


def project_full_at(
    *, used: int, cap: int, free: int, daily_growth: int | None, now_us: int
) -> tuple[int | None, Fraction | None]:
    """`(full_at_us, runway_days)` to the earlier wall (the cap or the volume). `(None, None)`
    when growth is unknown, not positive or the wall is out of sight (> 100 years); a wall
    already reached is `now`, runway 0."""
    if daily_growth is None or daily_growth <= 0:
        return None, None
    remaining = max(0, min(cap - used, free))
    if remaining // daily_growth > _MAX_RUNWAY_DAYS:
        return None, None
    return now_us + remaining * US_PER_DAY // daily_growth, Fraction(remaining, daily_growth)


class PressureLadder:
    """The ladder with hysteresis (24-internal-schemas §13.4.1), exact integer comparisons.

    Each level is a latch: it engages at its trigger and releases only past its re-arm point,
    so a reading oscillating around a trigger changes the level once."""

    def __init__(self, cfg: BudgetConfig) -> None:
        self._cfg = cfg
        self._on = dict.fromkeys(_LADDER, False)
        self.accelerate = False

    @property
    def level(self) -> DiskPressureLevel:
        return max((lvl for lvl, on in self._on.items() if on), default=DiskPressureLevel.NORMAL)

    def evaluate(
        self, *, used: int, cap: int, free: int, total: int, runway_days: Fraction | None
    ) -> None:
        c, r = self._cfg, self._cfg.rearm_pct

        def at(pct: int) -> bool:
            return used * _PCT >= cap * pct

        def below(pct: int) -> bool:
            return free * _PCT < total * pct

        soon = runway_days is not None and runway_days <= c.warn_runway_days
        far = runway_days is None or runway_days > c.warn_runway_days + c.warn_runway_rearm_days
        self._latch(DiskPressureLevel.WARN, at(c.warn_pct) or soon, not at(c.warn_pct - r) and far)
        for lvl, pct, free_pct in (
            (DiskPressureLevel.AUTOSTOP, c.autostop_pct, c.autostop_free_pct),
            (DiskPressureLevel.HALT, c.halt_pct, c.halt_free_pct),
        ):
            self._latch(
                lvl, at(pct) or below(free_pct), not at(pct - r) and not below(free_pct + r)
            )
        a = c.accelerate_until_free_pct
        if self._on[DiskPressureLevel.AUTOSTOP]:
            self.accelerate = True
        elif not at(_PCT - a) and free * _PCT > total * a:
            self.accelerate = False

    def _latch(self, level: DiskPressureLevel, engage: bool, release: bool) -> None:
        if engage:
            self._on[level] = True
        elif release:
            self._on[level] = False


def _utc(ts_us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=ts_us)


def _days(runway: Fraction | None) -> str:
    if runway is None:
        return ""
    return str((Decimal(runway.numerator) / runway.denominator).quantize(Decimal("0.1")))


def _fit_all(
    points: Sequence[Point], gaps: Sequence[tuple[int, int]], cfg: BudgetConfig, now_us: int
) -> tuple[int | None, dict[str, int]]:
    """Total (net) and per-symbol (write-rate) growth over the 7 d window, else the last 24 h."""
    long_ago = now_us - cfg.fit_window_s * US_PER_S
    full = bool(points) and points[0].ts_us <= long_ago
    window = cfg.fit_window_s if full else cfg.fallback_window_s
    sel = [p for p in points if p.ts_us >= now_us - window * US_PER_S]
    if len(sel) < 2 or sel[-1].ts_us - sel[0].ts_us < cfg.min_fit_span_s * US_PER_S:
        return None, {}
    hole = cfg.hole_us
    total = fit_daily_growth([(p.ts_us, p.recorded_bytes) for p in sel], hole_us=hole, gaps=gaps)
    per: dict[str, list[tuple[int, int]]] = {}
    for p in sel:
        for symbol, size in p.symbols:
            per.setdefault(symbol, []).append((p.ts_us, size))
    rates = {
        s: g
        for s, pts in per.items()
        if (g := fit_daily_growth(pts, hole_us=hole, gaps=gaps, restart_on_drop=True)) is not None
    }
    return total, rates


class DiskBudget:
    """Samples, fits, projects and runs the ladder on one supervised task (`start`/`stop`)."""

    def __init__(
        self,
        *,
        meter: StorageMeter,
        events: SystemEventSink,
        bus: PressurePublisher,
        env: str,
        config: BudgetConfig,
        now_us: Callable[[], int],
        gaps: GapSource | None = None,
        pinned: PinnedSource | None = None,
        store: SeriesStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        recording_refused: bool = False,
    ) -> None:
        self._meter, self._events, self._bus = meter, events, bus
        #: SR-096: a recording volume shared with the backend keeps the write gate closed.
        self.recording_refused = recording_refused
        self._cfg, self._now_us, self._sleep = config, now_us, sleep
        self._gaps, self._pinned, self._store = gaps, pinned, store
        self._topic = Topic(env=env, domain="recorder", detail="disk_pressure")
        self._ladder = PressureLadder(config)
        #: Last state the bus was told about; a failed announcement is retried next pass.
        self._announced = (DiskPressureLevel.NORMAL, False)
        bound = (config.fit_window_s + config.series_step_s) // config.series_step_s + 2
        self._series: deque[Point] = deque(maxlen=bound)
        self._growth: tuple[int | None, dict[str, int]] = (None, {})
        self._stale = True
        self._report: StorageUsage | None = None
        self._last_pins: frozenset[str] = frozenset()
        self._breakdown = Breakdown({}, {})
        #: Last fresh breakdown (construction until the first): its age is exported.
        self._fresh_at = now_us()
        self._rate_labels: set[str] = set()
        self._task: asyncio.Task[None] | None = None

    @property
    def level(self) -> DiskPressureLevel:
        """Plain enum for synchronous / hot-path readers (C-2.20); updated every sample."""
        return self._ladder.level

    @property
    def accelerate_retention(self) -> bool:
        return self._ladder.accelerate

    @property
    def halted(self) -> bool:
        """The `StreamWriter` gate (#491): level 3 or a refused volume. A plain bool per row."""
        return self.recording_refused or self._ladder.level is DiskPressureLevel.HALT

    @property
    def refuses_auto_record(self) -> bool:
        """`RecordingPolicy`: no new chart-open recording from level 2 (ADR-0015 d6, AC3)."""
        return self.recording_refused or self._ladder.level >= DiskPressureLevel.AUTOSTOP

    def report(self) -> StorageUsage | None:
        """`StorageUsage` from the last sample (never measured per request); `None` before it."""
        return self._report

    async def sample_once(self) -> None:
        cfg, now = self._cfg, self._now_us()
        async with asyncio.timeout(cfg.io_timeout_s):  # free space first: the ladder's input
            total, free = await self._meter.volume()
        try:
            async with asyncio.timeout(cfg.breakdown_timeout_s):
                self._breakdown = await self._meter.breakdown()
            fresh, self._fresh_at = True, now
        except Exception as exc:  # best effort: the last sizes and the free-space path go on
            fresh = False  # stale sizes never reach the series or the fit
            logger().warning("disk_budget_breakdown_unavailable", error=type(exc).__name__)
        m = Measurement(total, free, self._breakdown.tiers, self._breakdown.symbols)
        pinned = await self._pins()
        used = sum(m.tiers.get(t, 0) for t in _RECORDED)
        named = ((s, b) for s, b in m.symbols.items() if _SYMBOL_RE.match(s))
        top = tuple(sorted(named, key=lambda sb: (-sb[1], sb[0]))[: cfg.max_symbols])
        point = Point(now, used, top)
        if fresh and self._commit(point):
            await self._persist(point)
        if fresh and self._stale:
            self._growth = await self._refit(now)
        growth, fitted = self._growth
        rates = {s: fitted[s] for s, _ in top if s in fitted}  # labels <= max_symbols
        full_at, runway = project_full_at(
            used=used, cap=cfg.cap_bytes, free=m.free_bytes, daily_growth=growth, now_us=now
        )
        self._report = self._build_report(m, now, full_at, growth, rates, top, pinned)
        self._ladder.evaluate(
            used=used, cap=cfg.cap_bytes, free=m.free_bytes, total=m.total_bytes, runway_days=runway
        )
        self._publish_metrics(used, m.free_bytes, full_at, rates)
        state = (self._ladder.level, self._ladder.accelerate)
        if state != self._announced:
            await self._announce(m, used, full_at, runway, top, pinned, now)
            self._announced = state
        recorder_disk_budget_last_sample_timestamp_seconds.set(now // US_PER_S)
        recorder_disk_budget_breakdown_age_seconds.set((now - self._fresh_at) // US_PER_S)

    def _build_report(
        self,
        m: Measurement,
        now: int,
        full_at: int | None,
        growth: int | None,
        rates: Mapping[str, int],
        top: tuple[tuple[str, int], ...],
        pinned: frozenset[str],
    ) -> StorageUsage:
        days: dict[TierName, int] = {
            "questdb": self._cfg.hot_days,
            "parquet": self._cfg.retention_days,
        }
        return StorageUsage(
            disk_total_bytes=m.total_bytes,
            disk_used_bytes=m.total_bytes - m.free_bytes,
            disk_free_bytes=m.free_bytes,
            projected_full_at=None if full_at is None else _utc(full_at),
            daily_growth_bytes=growth or 0,
            tiers=tuple(
                TierUsage(tier=t, used_bytes=m.tiers[t], retention_days=days.get(t))
                for t in _TIERS
                if t in m.tiers
            ),
            symbols=tuple(
                SymbolUsage(
                    symbol=s, used_bytes=b, daily_growth_bytes=rates.get(s, 0), pinned=s in pinned
                )
                for s, b in top
            ),
            generated_at=_utc(now),
        )

    def _publish_metrics(
        self, used: int, free: int, full_at: int | None, rates: Mapping[str, int]
    ) -> None:
        disk_used_ratio.set(used / self._cfg.cap_bytes)
        disk_free_bytes.set(free)
        # A refused volume closes the gate: the level must say so, or nothing pages.
        level = DiskPressureLevel.HALT if self.recording_refused else self._ladder.level
        recorder_disk_pressure_level.set(int(level))
        recorder_projected_full_timestamp.set(0 if full_at is None else full_at // US_PER_S)
        for gone in self._rate_labels - rates.keys():
            recorder_bytes_per_day.remove(gone)
        for symbol, rate in rates.items():
            recorder_bytes_per_day.labels(symbol=symbol).set(rate)
        self._rate_labels = set(rates)

    async def _announce(
        self,
        m: Measurement,
        used: int,
        full_at: int | None,
        runway: Fraction | None,
        top: tuple[tuple[str, int], ...],
        pinned: frozenset[str],
        now: int,
    ) -> None:
        """System event first (alert before action, SR-096), then the bus for the consumers."""
        cfg, level, previous = self._cfg, self._ladder.level, self._announced[0]
        logger().info(
            "disk_pressure_changed",
            level=level.name,
            previous=previous.name,
            accelerate_retention=self._ladder.accelerate,
        )
        async with asyncio.timeout(cfg.io_timeout_s):
            if level > previous:
                severity, code = _LEVEL_EVENT[level]
                detail: dict[str, str | int] = {
                    "used_pct": used * _PCT // cfg.cap_bytes,
                    "free_pct": m.free_bytes * _PCT // m.total_bytes,
                    "projected_full_at": "" if full_at is None else _utc(full_at).isoformat(),
                    "runway_days": _days(runway),
                    "actions": SUGGESTED_ACTIONS,
                }
                if level is DiskPressureLevel.WARN:
                    over = used * _PCT >= cfg.cap_bytes * cfg.warn_pct
                    detail["trigger"] = "threshold" if over else "projection"
                if top:
                    detail["dominant_symbol"], detail["dominant_symbol_bytes"] = top[0]
                    detail["dominant_symbol_pinned"] = str(top[0][0] in pinned).lower()
                await self._events.emit(severity, code, detail)
            await self._bus.publish(
                self._topic,
                DiskPressureChanged(
                    level=level,
                    previous=previous,
                    accelerate_retention=self._ladder.accelerate,
                    used_bytes=used,
                    cap_bytes=cfg.cap_bytes,
                    free_bytes=m.free_bytes,
                    total_bytes=m.total_bytes,
                    ts_event=now,
                ),
            )

    async def _pins(self) -> frozenset[str]:
        """Pinned symbols; the last known set while the source is unavailable."""
        if self._pinned is not None:
            try:
                async with asyncio.timeout(self._cfg.io_timeout_s):
                    self._last_pins = await self._pinned()
            except Exception as exc:  # any source failure (driver errors are not mapped)
                logger().warning("disk_budget_pins_unavailable", error=type(exc).__name__)
        return self._last_pins

    # --- the rolling series ---------------------------------------------------------------

    def _commit(self, point: Point) -> bool:
        """Keep one point per `series_step_s` and only the fit window (bounded, C-2.18)."""
        step = self._cfg.series_step_s * US_PER_S
        if self._series and point.ts_us - self._series[-1].ts_us < step:
            return False
        self._series.append(point)
        horizon = point.ts_us - self._cfg.fit_window_s * US_PER_S - step
        while self._series[0].ts_us < horizon:
            self._series.popleft()
        self._stale = True
        return True

    async def _persist(self, point: Point) -> None:
        if self._store is None:
            return
        try:
            async with asyncio.timeout(self._cfg.io_timeout_s):
                await self._store.append(point)
        except _UNAVAILABLE as exc:  # the in-memory series still serves the fit
            logger().warning("disk_budget_persist_failed", error=type(exc).__name__)

    async def _refit(self, now: int) -> tuple[int | None, dict[str, int]]:
        points = tuple(self._series)
        gaps: tuple[tuple[int, int], ...] = ()
        if self._gaps is not None and points:
            try:
                async with asyncio.timeout(self._cfg.io_timeout_s):
                    gaps = tuple(await self._gaps(points[0].ts_us, now))
            except Exception as exc:  # any source failure: fit without gaps, never block
                logger().warning("disk_budget_gaps_unavailable", error=type(exc).__name__)
        fitted = await asyncio.to_thread(_fit_all, points, gaps, self._cfg, now)
        self._stale = False
        return fitted

    async def load_series(self) -> None:
        """Seed the series from the store; the task calls it once before the first sample."""
        if self._store is None:
            return
        since = self._now_us() - (self._cfg.fit_window_s + self._cfg.series_step_s) * US_PER_S
        try:
            async with asyncio.timeout(self._cfg.io_timeout_s):
                points = await self._store.load(since)
        except (*_UNAVAILABLE, ValueError) as exc:
            logger().warning("disk_budget_series_load_failed", error=type(exc).__name__)
            return
        now = self._now_us()
        for point in sorted(points, key=lambda p: p.ts_us):
            if point.ts_us <= now and point.recorded_bytes >= 0:  # never a future point
                self._commit(point)

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self) -> None:
        """Start the supervised sampling task (idempotent)."""
        if self._task is None:
            self._task = spawn(self._run(), name="recorder-disk-budget")
            self._task.add_done_callback(_on_task_done)

    async def stop(self) -> None:
        """Cancel the task, then close the meter (its executor and QuestDB connection)."""
        task, self._task = self._task, None
        try:
            if task is not None:
                task.cancel()
                await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():  # our own caller: propagate
                raise
        finally:
            await self._meter.close()

    async def _run(self) -> None:
        loaded = False
        while True:
            try:
                if not loaded:
                    await self.load_series()
                    loaded = True
                await self.sample_once()
            except Exception as exc:  # a failed pass keeps the last level; next pass retries
                logger().error("disk_budget_sample_failed", error=type(exc).__name__)
            await self._sleep(self._cfg.sample_interval_s)


def _on_task_done(task: asyncio.Task[None]) -> None:
    error = None if task.cancelled() else task.exception()
    if error is not None:  # never silent (C-2.18)
        logger().critical("disk_budget_task_died", error=type(error).__name__)
