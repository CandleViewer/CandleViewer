# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The clock model on scripted readings (#856 Technical notes): exact intervals, and the 500 ms
skew rule at its edge."""

from __future__ import annotations

import pytest

from spike.oms_demo_path.measure import ClockOffset
from spike.sl_attach.timing import AckTiming, Exchanged, ExposureTiming, skew_discard, skew_ms

T0 = 1_793_000_000_000  # an exchange-clock ms


def _exchange(venue_ms: int | None, *, sent: float = 1000.0, received: float = 1080.0) -> Exchanged:
    return Exchanged("/v5/position/trading-stop", "POST", sent, received, venue_ms, 0, 200)


def test_exposure_and_its_parts_on_the_exchange_clock() -> None:
    # host wall = exchange - 250 ms; the fill at T0, ingested 40 ms later, the stop sent 3 ms
    # after that, its 200 after a 95 ms round trip; the venue stamped its reply at T0 + 90
    offset = 250.0
    ingest_wall_ms = T0 + 40 - offset
    timing = ExposureTiming(
        exec_time_ms=T0,
        ingest_us=int(ingest_wall_ms * 1000),
        t_stop_send_wall_ms=ingest_wall_ms + 3,
        t_stop_send_s=10.000,
        t_stop_ok_s=10.095,
        t_stop_ok_wall_ms=ingest_wall_ms + 3 + 95,
        stop_venue_ms=T0 + 90,
        offset_ms=offset,
    )
    assert timing.push_lag_ms == pytest.approx(40.0)
    assert timing.react_ms == pytest.approx(3.0)
    assert timing.stop_rtt_ms == pytest.approx(95.0)
    assert timing.exposure_ms == pytest.approx(138.0)
    assert timing.exposure_venue_ms == 90.0
    assert timing.exposure_ms == pytest.approx(
        timing.push_lag_ms + timing.react_ms + timing.stop_rtt_ms
    )


def test_exposure_without_the_reply_time_has_no_cross_check() -> None:
    timing = ExposureTiming(T0, T0 * 1000, T0, 0.0, 0.1, T0 + 100.0, None, 0.0)
    assert timing.exposure_venue_ms is None and timing.exposure_ms == pytest.approx(100.0)


def test_ack_and_overhead() -> None:
    timing = AckTiming(t_send_s=5.0, t_ack_s=5.042, rtt_ms=37.0)
    assert timing.ack_ms == pytest.approx(42.0) and timing.overhead_ms == pytest.approx(5.0)
    assert AckTiming(5.0, 5.01, None).overhead_ms is None
    assert AckTiming(5.0, 5.01, 30.0).overhead_ms == 0.0  # never negative


@pytest.mark.parametrize(("skew", "discarded"), [(499, False), (500, False), (501, True)])
def test_the_500_ms_edge(skew: int, discarded: bool) -> None:
    # host midpoint 1040, offset 100: the exchange's midpoint is 1140
    measured = skew_ms(_exchange(1140 + skew), 100.0)
    assert measured == pytest.approx(float(skew))
    assert skew_discard(measured, 10.0) is discarded


def test_the_rule_reads_the_raw_skew_not_the_rounded_one() -> None:
    """N1: 500.0004 ms rounds to 500.0 at 3 dp, but it is past the limit."""
    measured = skew_ms(_exchange(1640), 99.9996)
    assert measured is not None and measured > 500.0
    assert skew_discard(measured, 10.0) is True


def test_a_late_venue_clock_is_skew_too() -> None:
    assert skew_ms(_exchange(1140 - 501), 100.0) == pytest.approx(501.0)


def test_an_uncertain_offset_or_an_unstamped_reply_is_discarded() -> None:
    assert skew_discard(0.0, 500.0) is False
    assert skew_discard(0.0, 501.0) is True
    assert skew_ms(_exchange(None), 0.0) is None and skew_discard(None, 0.0) is True
    assert skew_discard(0.0, None) is True


def test_the_offset_keeps_its_best_round_trip() -> None:
    # #843's estimator, reused: the shortest round trip wins; its half is the uncertainty
    offset = ClockOffset()
    offset.sample(1000.0, 1200.0, 1350)  # rtt 200: 1350 - 1100
    offset.sample(2000.0, 2020.0, 2260)  # rtt 20: 2260 - 2010
    offset.sample(3000.0, 3100.0, 3999)  # rtt 100: not better
    assert offset.value == 250 and offset.best_rtt_ms == 20.0
