"""Unit: E16-T07 `DiskBudget` maths — the growth fit (gaps, holes, drops), the projection and
the disk-pressure ladder with hysteresis on the cap and the free-space paths (24-internal-
schemas §13.4.1). Pure functions: no I/O, no clock, no sleeps."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.recorder.budget import (
    US_PER_DAY,
    US_PER_S,
    BudgetConfig,
    PressureLadder,
    fit_daily_growth,
    project_full_at,
)
from candleviewer.recorder.models import DiskPressureLevel as L

STEP = 600 * US_PER_S
HOLE = BudgetConfig(cap_bytes=1).hole_us
RATE = 86_400 * 1_000  # 1 000 B/s -> exact integer points every 600 s
HOUR = 3_600 * US_PER_S


def _line(n: int, *, start: int = 0, base: int = 0) -> list[tuple[int, int]]:
    return [(start + i * STEP, base + 1_000 * i * 600) for i in range(n)]


def test_fit_exact_line_returns_the_rate() -> None:
    assert fit_daily_growth(_line(50), hole_us=HOLE) == RATE


def test_fit_ignores_points_inside_a_recorded_gap() -> None:
    before = _line(13)  # 0 .. 2 h
    flat = [(t, before[-1][1]) for t, _ in _line(18, start=2 * HOUR)[1:]]  # outage: no growth
    after = _line(13, start=5 * HOUR, base=before[-1][1])
    points = before + flat + after
    assert fit_daily_growth(points, hole_us=HOLE, gaps=[(2 * HOUR + 1, 5 * HOUR)]) == RATE
    assert (fit_daily_growth(points, hole_us=HOLE) or 0) < RATE * 0.9  # the outage would depress


def test_fit_restarts_at_a_sampling_hole() -> None:
    first = _line(10)
    second = _line(10, start=first[-1][0] + 3 * HOUR, base=first[-1][1])  # down 3 h, no growth
    assert fit_daily_growth(first + second, hole_us=HOLE) == RATE


def test_fit_restarts_at_a_gap_lying_between_two_points() -> None:
    first = _line(10)
    second = _line(10, start=first[-1][0] + STEP, base=10**9)  # level shift across the gap
    end = first[-1][0]
    gaps = [(end + 3, end + 9), (end + 1, end + 5)]  # unsorted, overlapping (two symbols)
    assert fit_daily_growth(first + second, hole_us=HOLE, gaps=gaps) == RATE
    assert fit_daily_growth(first + second, hole_us=HOLE) != RATE


def test_fit_drop_counts_for_the_net_total_and_restarts_a_symbol_run() -> None:
    first = _line(20)
    second = _line(20, start=first[-1][0] + STEP, base=first[-1][1] // 2)  # retention halves
    assert fit_daily_growth(first + second, hole_us=HOLE, restart_on_drop=True) == RATE
    assert (fit_daily_growth(first + second, hole_us=HOLE) or 0) < RATE


@pytest.mark.parametrize("points", [[], [(0, 5)], [(0, 5), (0, 9)]])
def test_fit_without_time_spread_is_unknown(points: list[tuple[int, int]]) -> None:
    assert fit_daily_growth(points, hole_us=HOLE) is None


@given(st.lists(st.integers(min_value=0, max_value=10**10), min_size=2, max_size=60))
def test_fit_of_a_monotone_series_is_never_negative(increments: list[int]) -> None:
    ys = [sum(increments[: i + 1]) for i in range(len(increments))]
    points = [(i * STEP, y) for i, y in enumerate(ys)]
    for restart in (False, True):
        assert (fit_daily_growth(points, hole_us=HOLE, restart_on_drop=restart) or 0) >= 0


def test_projection_takes_the_earlier_wall_and_reached_wall_is_now() -> None:
    full_at, runway = project_full_at(used=400, cap=1_000, free=300, daily_growth=100, now_us=0)
    assert (full_at, runway) == (3 * US_PER_DAY, Fraction(3))  # volume (300) before cap (600)
    reached = project_full_at(used=1_200, cap=1_000, free=50, daily_growth=10, now_us=7)
    assert reached == (7, Fraction(0))
    assert project_full_at(used=1, cap=10, free=9, daily_growth=0, now_us=7) == (None, None)
    far = project_full_at(used=0, cap=10**15, free=10**15, daily_growth=1, now_us=7)
    assert far == (None, None)  # > 100 years: out of sight


@given(
    st.integers(min_value=0, max_value=10**13),
    st.integers(min_value=1, max_value=10**13),
    st.integers(min_value=0, max_value=10**13),
    st.integers(min_value=-(10**12), max_value=10**12),
)
def test_runway_is_never_negative(used: int, cap: int, free: int, growth: int) -> None:
    full_at, runway = project_full_at(used=used, cap=cap, free=free, daily_growth=growth, now_us=5)
    assert runway is None or runway >= 0
    assert full_at is None or full_at >= 5


CFG = BudgetConfig(cap_bytes=1_000)


def _walk(readings: list[tuple[int, int]], runway: Fraction | None = None) -> list[tuple[L, bool]]:
    """Readings are (used bytes of a 1 000 B cap, free bytes of a 100 B volume)."""
    ladder, out = PressureLadder(CFG), []
    for used, free in readings:
        ladder.evaluate(used=used, cap=1_000, free=free, total=100, runway_days=runway)
        out.append((ladder.level, ladder.accelerate))
    return out


def test_cap_path_thresholds() -> None:
    levels = [lvl for lvl, _ in _walk([(790, 50), (800, 50), (900, 50), (950, 50)])]
    assert levels == [L.NORMAL, L.WARN, L.AUTOSTOP, L.HALT]


def test_free_space_path_thresholds() -> None:
    assert [lvl for lvl, _ in _walk([(100, 16), (100, 14), (100, 4)])] == [
        L.NORMAL,
        L.AUTOSTOP,
        L.HALT,
    ]


def test_hysteresis_steps_down_only_past_each_rearm_point() -> None:
    walk = _walk([(960, 50), (910, 50), (899, 50), (850, 50), (849, 50), (750, 50), (749, 50)])
    assert [lvl for lvl, _ in walk] == [
        L.HALT,
        L.HALT,
        L.AUTOSTOP,
        L.AUTOSTOP,
        L.WARN,
        L.WARN,
        L.NORMAL,
    ]


def test_oscillating_89_91_engages_autostop_once_until_below_85() -> None:
    levels = [lvl for lvl, _ in _walk([(890, 50), (910, 50)] * 10 + [(860, 50), (849, 50)])]
    assert levels[0] == L.WARN and set(levels[1:21]) == {L.AUTOSTOP}
    assert levels[-1] == L.WARN


def test_free_path_rearms_at_20_and_10_percent() -> None:
    walk = _walk([(100, 4), (100, 9), (100, 10), (100, 19), (100, 20)])
    assert [lvl for lvl, _ in walk] == [L.HALT, L.HALT, L.AUTOSTOP, L.AUTOSTOP, L.NORMAL]


def test_accelerated_retention_holds_until_used_below_75_and_free_above_25() -> None:
    walk = _walk([(500, 14), (500, 21), (500, 25), (760, 30), (740, 26)])
    assert [acc for _, acc in walk] == [True, True, True, True, False]


def test_projection_within_seven_days_warns_and_rearms_past_eight() -> None:
    ladder = PressureLadder(CFG)
    for runway, want in ((Fraction(6), L.WARN), (Fraction(15, 2), L.WARN), (Fraction(9), L.NORMAL)):
        ladder.evaluate(used=500, cap=1_000, free=50, total=100, runway_days=runway)
        assert ladder.level is want


def test_config_rejects_unordered_thresholds() -> None:
    with pytest.raises(ValueError, match="warn < autostop < halt"):
        BudgetConfig(cap_bytes=1, warn_pct=90, autostop_pct=90)
