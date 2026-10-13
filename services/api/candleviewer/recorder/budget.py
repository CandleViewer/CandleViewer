"""`DiskBudget` core — growth fit, projection and the disk-pressure ladder (E16-T07).

SR-096 / threat S2 (Critical), ADR-0015 decision 6, `21-database-schema.md` §6. The fit
rules, the thresholds and the `DiskPressureChanged` contract are owned by
`24-internal-schemas.md` §13.4.1; this module implements them as pure, synchronous code
(C-2.20: no statechart): an exact integer least-squares fit with one intercept per
contiguous run, the projection to the earlier wall, and the hysteresis ladder whose plain
`level` / `accelerate` hot-path readers consume. The sampling service that drives them
lands in the next slice of E16-T07.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

from candleviewer.recorder.models import DiskPressureLevel

US_PER_S: Final = 1_000_000
US_PER_DAY: Final = 86_400 * US_PER_S
_MAX_RUNWAY_DAYS: Final = 36_500
_LADDER: Final = (DiskPressureLevel.WARN, DiskPressureLevel.AUTOSTOP, DiskPressureLevel.HALT)


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
    hot_days: int = 7
    retention_days: int = 30

    def __post_init__(self) -> None:
        cap_path = 0 < self.warn_pct < self.autostop_pct < self.halt_pct <= 100
        free_path = 0 < self.halt_free_pct < self.autostop_free_pct < self.accelerate_until_free_pct
        if self.cap_bytes <= 0 or not (cap_path and free_path) or self.sample_interval_s <= 0:
            raise ValueError(
                "disk budget: cap > 0, 0 < warn < autostop < halt <= 100 and"
                " 0 < halt_free < autostop_free < accelerate_until_free"
            )

    @property
    def hole_us(self) -> int:
        """A gap between committed points longer than this is a sampling hole."""
        return int(self.series_step_s + 3 * self.sample_interval_s) * US_PER_S


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
            return used * 100 >= cap * pct

        def below(pct: int) -> bool:
            return free * 100 < total * pct

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
        elif not at(100 - a) and free * 100 > total * a:
            self.accelerate = False

    def _latch(self, level: DiskPressureLevel, engage: bool, release: bool) -> None:
        if engage:
            self._on[level] = True
        elif release:
            self._on[level] = False
