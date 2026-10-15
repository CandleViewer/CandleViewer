"""Pacing math of the replay clock (E26-T03): absolute deadlines, continuous speed changes,
backpressure re-anchoring and the achieved-rate window. No time source is involved: the tests
drive wall time by hand."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.replay.pacing import US_PER_S, Pacer, RateWindow

HOUR_US = 3_600 * US_PER_S


def test_pacer_due_is_measured_from_the_anchor_at_the_speed() -> None:
    pacer = Pacer(4.0, wall=100.0, ts_us=0)
    assert pacer.due(0) == 100.0
    assert pacer.due(8 * US_PER_S) == pytest.approx(102.0)


def test_pacer_replay_time_before_the_anchor_is_due_at_the_anchor() -> None:
    pacer = Pacer(1.0, wall=50.0, ts_us=10 * US_PER_S)
    assert pacer.due(3 * US_PER_S) == 50.0
    assert pacer.position(49.0) == 10 * US_PER_S


def test_pacer_rejects_a_speed_that_is_not_paced() -> None:
    with pytest.raises(ValueError, match="positive"):
        Pacer(0.0, wall=0.0, ts_us=0)
    with pytest.raises(ValueError, match="positive"):
        Pacer(1.0, wall=0.0, ts_us=0).set_speed(-1.0, wall=0.0, position_us=0)


def test_pacer_speed_change_continues_from_the_current_position_without_a_jump() -> None:
    pacer = Pacer(1.0, wall=0.0, ts_us=0)
    here = pacer.position(30.0)
    pacer.set_speed(10.0, wall=30.0, position_us=here)
    assert pacer.position(30.0) == here == 30 * US_PER_S
    assert pacer.due(here + 10 * US_PER_S) == pytest.approx(31.0)


def test_pacer_lateness_within_max_lag_keeps_the_absolute_schedule() -> None:
    pacer = Pacer(1.0, wall=0.0, ts_us=0)
    assert pacer.late(US_PER_S, wall=1.2, max_lag_s=0.25) == pytest.approx(0.2)
    assert (pacer.anchor_wall, pacer.anchor_ts, pacer.lost_s) == (0.0, 0, 0.0)
    assert pacer.due(2 * US_PER_S) == pytest.approx(2.0)


def test_pacer_lateness_beyond_max_lag_slows_the_clock_and_books_lost_time() -> None:
    pacer = Pacer(2.0, wall=0.0, ts_us=0)
    lag = pacer.late(2 * US_PER_S, wall=4.0, max_lag_s=0.25)
    assert lag == pytest.approx(3.0)
    assert pacer.lost_s == pytest.approx(3.0)
    assert pacer.due(4 * US_PER_S) == pytest.approx(5.0)  # no burst: 2 s of replay is 1 s


def test_pacer_late_event_inside_a_skipped_stretch_never_moves_the_anchor_back() -> None:
    pacer = Pacer(1.0, wall=0.0, ts_us=0)
    pacer.skip_to(60 * US_PER_S, wall=5.0)
    pacer.late(30 * US_PER_S, wall=9.0, max_lag_s=0.25)
    assert (pacer.anchor_wall, pacer.anchor_ts) == (9.0, 60 * US_PER_S)


def test_pacer_skip_to_compresses_replay_time_up_to_the_gap_end() -> None:
    pacer = Pacer(1.0, wall=0.0, ts_us=0)
    pacer.skip_to(600 * US_PER_S, wall=10.0)
    assert pacer.due(300 * US_PER_S) == 10.0
    assert pacer.due(601 * US_PER_S) == pytest.approx(11.0)


def test_pacer_skip_to_a_point_the_schedule_passed_keeps_the_position() -> None:
    pacer = Pacer(1.0, wall=0.0, ts_us=0)
    pacer.skip_to(5 * US_PER_S, wall=20.0)
    assert pacer.position(20.0) == 20 * US_PER_S


def test_rate_window_reports_the_paced_ratio_from_lost_wall_time() -> None:
    window = RateWindow(1.0)
    window.restart(wall=0.0, lost_s=0.0, position_us=0)
    assert not window.update(wall=0.5, lost_s=0.0, position_us=0, requested=10.0)
    assert (window.ratio, window.speed) == (None, None)
    assert window.update(wall=2.0, lost_s=1.0, position_us=0, requested=10.0)
    assert window.ratio == pytest.approx(0.5)
    assert window.speed == pytest.approx(5.0)


def test_rate_window_clamps_the_ratio_to_zero_when_everything_was_lost() -> None:
    window = RateWindow(1.0)
    window.restart(wall=0.0, lost_s=0.0, position_us=0)
    assert window.update(wall=1.0, lost_s=3.0, position_us=0, requested=1.0)
    assert window.ratio == 0.0


def test_rate_window_reports_replay_seconds_per_wall_second_when_unbounded() -> None:
    window = RateWindow(1.0)
    window.restart(wall=0.0, lost_s=0.0, position_us=0)
    assert window.update(wall=2.0, lost_s=0.0, position_us=500 * US_PER_S, requested=-1.0)
    assert window.ratio is None
    assert window.speed == pytest.approx(250.0)


@given(
    speed=st.sampled_from((0.1, 0.5, 1.0, 4.0, 25.0, 100.0)),
    gaps_us=st.lists(st.integers(0, 5 * US_PER_S), min_size=1, max_size=200),
    oversleeps=st.lists(st.floats(0.0, 0.01), min_size=200, max_size=200),
)
def test_pacer_oversleep_never_accumulates_into_drift(
    speed: float, gaps_us: list[int], oversleeps: list[float]
) -> None:
    """Every wait overshoots by up to 10 ms, yet each event is emitted within 10 ms of its ideal
    time, however many events came before it. An event already due is emitted without a wait."""
    pacer = Pacer(speed, wall=0.0, ts_us=0)
    wall, ts = 0.0, 0
    for step_us, over in zip(gaps_us, oversleeps, strict=False):
        ts += step_us
        if pacer.due(ts) > wall:
            wall = pacer.due(ts) + over
        pacer.late(ts, wall=wall, max_lag_s=0.25)
        ideal = ts / (speed * US_PER_S)
        assert 0.0 <= wall - ideal <= 0.01 + 1e-9
    assert pacer.lost_s == 0.0


def test_pacer_one_hour_at_1x_with_jitter_ends_within_half_a_percent() -> None:
    """The ticket's pacing criterion on the schedule alone: 3 600 one-second events, each wait
    oversleeping up to 5 ms, finish within 0.5 % of an hour with no drift from start to end."""
    pacer = Pacer(1.0, wall=0.0, ts_us=0)
    wall, errors = 0.0, []
    for i in range(1, 3_601):
        ts = i * US_PER_S
        wall = pacer.due(ts) + (i % 7) * 0.0007
        pacer.late(ts, wall=wall, max_lag_s=0.25)
        errors.append(wall - ts / US_PER_S)
    assert abs(wall - 3_600.0) <= 0.005 * 3_600.0
    assert max(errors) < 0.005
    assert abs(errors[-1] - errors[0]) < 0.005


@given(
    ts=st.lists(st.integers(0, HOUR_US), min_size=2, max_size=50),
    speed=st.floats(0.1, 100.0),
)
def test_pacer_due_is_monotonic_and_round_trips_through_position(
    ts: list[int], speed: float
) -> None:
    pacer = Pacer(speed, wall=7.0, ts_us=0)
    ordered = sorted(ts)
    dues = [pacer.due(t) for t in ordered]
    assert dues == sorted(dues)
    for t, d in zip(ordered, dues, strict=True):
        assert abs(pacer.position(d) - t) <= 2
