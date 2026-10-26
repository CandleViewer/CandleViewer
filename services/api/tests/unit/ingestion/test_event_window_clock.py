"""#1912: the #1892 EventWindow runs on the exchange-corrected clock (E08-S07)."""

from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.frame_guard import MAX_FUTURE_SKEW_MS, FrameRejectedError
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.ingestion.metrics import clock_resync_triggered_total
from candleviewer.ingestion.rejection import EventWindow, corrected_now_us
from candleviewer.ingestion.service import IngestionService
from candleviewer.observability.logging import configure_logging

_S = 1_000_000
_VENUE_US = 1_800_000_000 * _S


class _Host:
    def __init__(self, now_us: int) -> None:
        self.now_us = now_us

    def __call__(self) -> int:
        return self.now_us


class _Clocks:
    """Fake wall + monotonic clocks; `step` moves only the wall clock (host step)."""

    def __init__(self) -> None:
        self.mono_ns = 5_000 * 1_000_000_000
        self.wall_base_ns = _VENUE_US * 1000 - self.mono_ns  # host == venue at t0

    def wall(self) -> int:
        return self.mono_ns + self.wall_base_ns

    def mono(self) -> int:
        return self.mono_ns

    def host_us(self) -> int:
        return self.wall() // 1000

    def step(self, seconds: float) -> None:
        self.wall_base_ns += int(seconds * 1_000_000_000)

    def advance(self, seconds: float) -> None:
        self.mono_ns += int(seconds * 1_000_000_000)


async def _no_sleep(_s: float) -> None:
    await asyncio.sleep(0)


def _guard(
    clocks: _Clocks, fetches: list[int] | None = None, fail: list[bool] | None = None
) -> ClockGuard:
    async def _fetch() -> tuple[int, float, float]:
        if fail:
            raise ConnectionError("network down after resume")
        if fetches is not None:
            fetches.append(1)
        # venue time is the true time: unaffected by host steps
        return (_VENUE_US + clocks.mono_ns // 1000 - 5_000 * _S, clocks.wall() / 1e9, 0.0)

    return ClockGuard(
        _fetch,
        sample_count=1,
        wall_ns=clocks.wall,
        mono_ns=clocks.mono,
        step_check_interval_ms=0,
        sleep=_no_sleep,
    )


def _window(clocks: _Clocks, guard: ClockGuard) -> EventWindow:
    return EventWindow(corrected_now_us(guard.offset_us, clocks.host_us), lambda _s: None)


def _venue_now(clocks: _Clocks) -> int:
    return _VENUE_US + clocks.mono_ns // 1000 - 5_000 * _S


def _steps() -> float:
    # No public read on the metric facade; the private child value is the only accessor.
    return float(clock_resync_triggered_total.labels(reason="host_step")._value.get())


def test_corrected_now_positive_offset_when_venue_ahead_of_host() -> None:
    host = _Host(_VENUE_US - 10 * _S)  # host 10 s behind venue
    assert corrected_now_us(lambda: 10 * _S, host)() == _VENUE_US  # server - local > 0


def test_backward_host_step_without_remeasure_accepts_venue_prints() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    window = _window(clocks, guard)
    window("BTCUSDT", _venue_now(clocks))
    clocks.step(-10)  # WSL resume; no re-measure has happened
    window("BTCUSDT", _venue_now(clocks))  # no ts_future
    assert guard.offset_us() == 10 * _S


def test_backward_host_step_uncorrected_window_rejects() -> None:
    clocks = _Clocks()
    clocks.step(-10)
    window = EventWindow(clocks.host_us, lambda _s: None)
    with pytest.raises(FrameRejectedError) as ei:
        window("BTCUSDT", _venue_now(clocks))
    assert ei.value.reason == "ts_future"


def test_forward_host_step_symmetric() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    window = _window(clocks, guard)
    clocks.step(10)
    window("BTCUSDT", _venue_now(clocks))
    assert guard.offset_us() == -10 * _S


def test_implausible_venue_ts_still_rejected_after_step() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    window = _window(clocks, guard)
    clocks.step(-10)
    with pytest.raises(FrameRejectedError) as ei:
        window("BTCUSDT", _venue_now(clocks) + MAX_FUTURE_SKEW_MS * 1000 + 1)
    assert ei.value.reason == "ts_future"


def test_step_below_threshold_does_not_trigger() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    before = _steps()
    clocks.advance(30)  # elapsed time is not a step
    clocks.step(-0.5)
    assert guard.offset_us() == 0
    assert _steps() == before


async def test_step_triggers_exactly_one_single_flight_measure() -> None:
    clocks = _Clocks()
    fetches: list[int] = []
    guard = _guard(clocks, fetches)
    before = _steps()
    clocks.step(-10)
    guard.offset_us()
    guard.offset_us()  # re-entry while the measure is in flight
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(fetches) == 1
    assert _steps() == before + 1
    assert guard.offset_us() == 10 * _S  # measurement confirms the step correction
    assert len(fetches) == 1  # reference re-based: no re-trigger


async def test_offset_tracks_guard_without_double_apply() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    now = corrected_now_us(guard.offset_us, clocks.host_us)
    assert now() == clocks.host_us()  # unmeasured offset is 0
    clocks.wall_base_ns -= 7 * 1_000_000_000  # host 7 s behind; measured, not poked
    await guard.measure_once()
    assert guard.offset_us() == 7 * _S
    assert now() == clocks.host_us() + 7 * _S == _venue_now(clocks)


async def _drain() -> None:
    for _ in range(40):
        await asyncio.sleep(0)


async def test_unconfirmed_step_reverts_and_rearms_detector() -> None:
    clocks = _Clocks()
    guard = _guard(clocks, fail=[True])
    clocks.wall_base_ns += 10 * 1_000_000_000  # suspend: mono paused, wall advanced
    with capture_logs() as logs:
        assert guard.offset_us() == -10 * _S  # provisional correction
        await _drain()
    assert "clock_step_unconfirmed" in [e["event"] for e in logs]
    # Reverted with the pre-step reference restored: the next check re-detects the
    # still-present skew instead of silently trusting the old offset forever.
    assert guard.check_host_step() == 10 * _S


async def test_genuine_step_survives_outage_longer_than_first_retries() -> None:
    clocks = _Clocks()
    fail = [True]
    sleeps = 0

    async def _flaky_sleep(_s: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 5:
            fail[0] = False  # network is back after ~15 s of backoff
        await asyncio.sleep(0)

    async def _fetch() -> tuple[int, float, float]:
        if fail[0]:
            raise ConnectionError("down")
        return (_venue_now(clocks), clocks.wall() / 1e9, 0.0)

    guard = ClockGuard(
        _fetch,
        sample_count=1,
        wall_ns=clocks.wall,
        mono_ns=clocks.mono,
        step_check_interval_ms=0,
        sleep=_flaky_sleep,
    )
    window = _window(clocks, guard)
    clocks.step(-10)
    window("BTCUSDT", _venue_now(clocks))  # accepted while provisional
    await _drain()
    assert sleeps == 5
    window("BTCUSDT", _venue_now(clocks))  # accepted after confirmation
    assert guard.offset_us() == 10 * _S


async def test_stop_cancels_the_step_confirm_task() -> None:
    clocks = _Clocks()
    block = asyncio.Event()

    async def _hang_sleep(_s: float) -> None:
        await block.wait()

    guard = ClockGuard(
        _fail_fetch,
        sample_count=1,
        wall_ns=clocks.wall,
        mono_ns=clocks.mono,
        step_check_interval_ms=0,
        sleep=_hang_sleep,
    )
    before = asyncio.all_tasks()
    clocks.step(-10)
    guard.offset_us()
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks() - before) == 1  # the confirm task
    await guard.stop()
    await asyncio.sleep(0)
    assert asyncio.all_tasks() - before == set()


async def _fail_fetch() -> tuple[int, float, float]:
    raise ConnectionError("down")


async def test_suspend_false_step_confirmed_by_measurement_keeps_true_offset() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    clocks.wall_base_ns += 10 * 1_000_000_000  # false step: venue time did not move
    guard.offset_us()
    await _drain()
    # Venue time is unaffected by the host step, so the measurement re-derives the
    # true offset (server - local) from scratch; the provisional value is dropped.
    assert guard.offset_us() == -10 * _S  # wall is 10 s ahead of venue after the step


async def test_step_during_measure_burst_is_not_lost() -> None:
    clocks = _Clocks()
    calls = 0

    async def _fetch() -> tuple[int, float, float]:
        nonlocal calls
        calls += 1
        if calls == 1:
            clocks.step(-10)  # lands while the first burst samples
        return (_venue_now(clocks), clocks.wall() / 1e9, 0.0)

    guard = ClockGuard(
        _fetch, sample_count=1, wall_ns=clocks.wall, mono_ns=clocks.mono, sleep=_no_sleep
    )
    offset = await guard.measure_once()
    assert calls == 2  # first burst discarded, redone after the step
    assert offset == 10 * _S
    assert guard.check_host_step() == 0  # reference rebased onto the post-step skew


def test_host_step_without_event_loop_corrects_and_schedules_nothing() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    clocks.step(-10)
    assert guard.check_host_step() == -10 * _S  # sync caller, no running loop
    assert guard.offset_us() == 10 * _S


async def test_offset_ms_or_none_includes_host_step() -> None:
    clocks = _Clocks()
    guard = _guard(clocks)
    assert guard.offset_ms_or_none() is None  # never measured
    await guard.measure_once()
    clocks.step(-10)
    assert guard.offset_ms_or_none() == 10_000


async def test_the_offset_snapshot_reads_the_verified_offset_and_never_checks_a_host_step() -> None:
    """#913 L1d (CR-S3L1B-09, ruling Q4): the order lane's reader, called on its own loop. `None`
    until the guard has measured, never a fabricated 0, and the service's alike until a guard is
    attached; then the offset as the serving loop's reads left it: a host step none of them has
    seen is not folded in, nothing is counted and no resync is spawned on the calling loop."""
    clocks, fetches, service = _Clocks(), list[int](), IngestionService()
    guard = _guard(clocks, fetches)
    assert service.clock_offset_snapshot_ms() is None and guard.offset_ms_snapshot() is None
    service.attach_clock(guard)
    assert service.clock_offset_snapshot_ms() is None  # attached, never measured
    await guard.measure_once()
    clocks.step(-10)
    steps, fetched = _steps(), len(fetches)
    assert service.clock_offset_snapshot_ms() == guard.offset_ms_snapshot() == 0
    for _ in range(5):
        await asyncio.sleep(0)
    assert (_steps(), len(fetches)) == (steps, fetched)  # no host-step check ran
    assert guard.offset_ms_or_none() == 10_000  # a serving read folds the step in
    assert service.clock_offset_snapshot_ms() == 10_000


async def test_the_offset_snapshot_floors_a_sub_millisecond_offset_as_the_serving_read() -> None:
    """#913 L1d: a venue 0.5 ms behind the host is an offset of -1 ms in the snapshot, floored as
    `offset_ms_or_none` floors it, never truncated to 0."""
    clocks = _Clocks()

    async def behind() -> tuple[int, float, float]:
        return (clocks.wall() // 1000 - 500, clocks.wall() / 1e9, 0.0)

    guard = ClockGuard(
        behind,
        sample_count=1,
        wall_ns=clocks.wall,
        mono_ns=clocks.mono,
        step_check_interval_ms=0,
        sleep=_no_sleep,
    )
    await guard.measure_once()
    assert guard.offset_ms_snapshot() == guard.offset_ms_or_none() == -1


async def test_periodic_failure_log_survives_logging_reconfiguration() -> None:
    """Regression (#1961, mirrors #1921): clock.py resolves its logger per call, so
    `capture_logs()` still sees periodic-measure events after logging is reconfigured."""

    async def periodic_events() -> list[str]:
        clocks = _Clocks()

        async def _down() -> tuple[int, float, float]:
            raise ConnectionError("time endpoint down")

        sleeps = 0

        async def _sleep(_s: float) -> None:
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                raise asyncio.CancelledError  # second wait ends the loop
            await asyncio.sleep(0)

        guard = ClockGuard(
            _down,
            sample_count=1,
            wall_ns=clocks.wall,
            mono_ns=clocks.mono,
            step_check_interval_ms=0,
            sleep=_sleep,
        )
        with capture_logs() as logs:
            await guard._run_periodic()
        return [e["event"] for e in logs]

    configure_logging(env="demo")
    await periodic_events()  # first use binds (and, with a module-level logger, caches)
    configure_logging(env="demo")
    assert "clock_periodic_measurement_failed" in await periodic_events()
