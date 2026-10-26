"""`ClockGuard`: verified offset against exchange server time (E08-S07,
`docs/plan/24-internal-schemas.md` §14.3, `docs/plan/20-architecture.md`
§3.1).

This module lives outside the concrete exchange adapter package, so per
CONSTITUTION.md C-2.2 it stays adapter-agnostic and never references
exchange-specific nomenclature; the exchange adapter rejects a signed
request whose signed
timestamp header falls outside its recv-window (fixed — `24-internal-
schemas.md` §14.3 states plainly that we *fix clocks rather than widening
the window*). `ClockGuard` measures the offset via the adapter's public
server-time endpoint (through the `ServerTimeFetcher` protocol below),
re-measures on a fixed cadence and on signature failure, and exposes
`offset_us()`/`assert_healthy()` so the REST client's
`clock_offset_ms_provider` (E08-T02) and the trading gate (E29) both
consume one governed measurement.

All internal timestamps are microseconds (`TsUs`, `24-internal-schemas.md`
§1.2); the offset is stored in microseconds and converted to milliseconds
only at the adapter's signed-request header boundary (technical notes,
ticket body).

Hot-path exclusion: this module runs a low-frequency supervised background
task (one measurement burst per `resync_interval_s`, default 300 s), never
a per-tick or per-message call — it is not a statechart (catalogue §1.2).
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

import structlog

from candleviewer.exchange.base.errors import ClockDriftError
from candleviewer.ingestion.errors import IngestionError
from candleviewer.ingestion.metrics import (
    clock_measurements_total,
    clock_offset_age_seconds,
    clock_resync_triggered_total,
    exchange_clock_drift_ms,
)
from candleviewer.observability.context import spawn


def _log() -> structlog.stdlib.BoundLogger:
    """Resolved per call: a module-level logger cached under
    `cache_logger_on_first_use=True` keeps a stale processor chain after
    `configure_logging()` runs, so step events would escape `capture_logs()`
    (same pitfall as ingestion/rejection.py)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


_STEP_RETRY_BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
"""Delays before each confirming retry of a host-step correction (doubling, capped
at 30 s). The provisional correction stays applied while retrying; only after the
last attempt fails is it reverted (and the step reference restored)."""


def default_mono_ns() -> int:
    """Reference clock for step detection: `CLOCK_BOOTTIME` where available
    (Linux — keeps counting through suspend, so a WSL/host sleep is NOT seen as a
    wall step), else `time.monotonic_ns` (which may pause across suspend)."""
    if sys.platform == "linux":
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    return time.monotonic_ns()


_MICROS_PER_MS = 1_000
_SAMPLE_COUNT = 5
"""Samples per measurement burst (Test plan: "offset maths incl. outlier
rejection" needs more than one sample to have an outlier to reject)."""
_BURST_ATTEMPTS = 3
"""Max bursts per measurement when the host clock steps mid-burst (#1912)."""


class ServerTimeFetcher(Protocol):
    """Returns `(server_time_us, request_sent_epoch_s, round_trip_s)` for
    one call to the exchange adapter's public server-time endpoint.
    `request_sent_epoch_s` MUST be a wall-clock (epoch) timestamp — e.g.
    `time.time()`/`time_ns()` — never a `time.monotonic()` value, because it
    is compared directly against the server's epoch time to compute the
    offset; monotonic time has an arbitrary origin and would make the
    offset roughly the full epoch value. `round_trip_s` may (and should)
    come from a monotonic clock, since only the *difference* between two
    monotonic reads is meaningful. Implemented by a thin adapter over the
    exchange adapter's REST client — kept as a narrow protocol here so this
    module never imports the concrete adapter directly (module boundaries,
    C-3.1, C-2.2) and stays unit-testable with a fake."""

    async def __call__(self) -> tuple[int, float, float]: ...


class ClockMeasurementUnavailableError(IngestionError):
    """The public server-time endpoint failed on every sample in a burst.
    The last known offset continues to be applied (scenario "Exchange time
    endpoint unavailable") — this error is raised only to the caller that
    requested a fresh measurement, never used to fall back to an
    uncorrected clock.

    The message embeds `str(exc)` from the last failed sample. The
    server-time endpoint is public and unsigned, so no request headers
    (API key, signature) are ever attached to it, and the adapter's REST
    client only surfaces `TransportError`/`UnknownStateError` text (status
    code, path, body snippet) here — never raw request headers (see review
    note, `50-security.md`). Do not widen this fetcher to a signed endpoint
    without re-auditing this message for leaking credentials."""


class ClockGuard:
    """Owns the measured offset to the exchange's server time.

    `offset_us()` is the value injected into signed requests (E08-T02's
    `clock_offset_ms_provider`, converted to ms at that boundary — this
    class always deals in microseconds internally). `assert_healthy()`
    raises `ClockDriftError` above `hard_threshold_ms` so E29 can refuse to
    place orders; it never blocks trading itself (out of scope, ticket
    body) — it only records the verdict.
    """

    def __init__(
        self,
        fetch_server_time: ServerTimeFetcher,
        *,
        warn_threshold_ms: int = 500,
        hard_threshold_ms: int = 2_000,
        resync_interval_s: float = 300.0,
        max_offset_age_s: float = 900.0,
        sample_count: int = _SAMPLE_COUNT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = random.random,
        wall_ns: Callable[[], int] = time.time_ns,
        mono_ns: Callable[[], int] = default_mono_ns,
        step_threshold_s: float = 1.0,
        step_check_interval_ms: int = 100,
    ) -> None:
        if hard_threshold_ms <= warn_threshold_ms:
            raise ValueError("hard_threshold_ms must exceed warn_threshold_ms")
        self._fetch_server_time = fetch_server_time
        self._warn_threshold_ms = warn_threshold_ms
        self._hard_threshold_ms = hard_threshold_ms
        self._resync_interval_s = resync_interval_s
        self._max_offset_age_s = max_offset_age_s
        self._sample_count = max(1, sample_count)
        self._clock = clock
        self._sleep = sleep
        self._random = random_fn

        self._offset_us: int = 0
        # #1912 host-step detector: (wall - mono) only moves when the host wall
        # clock is stepped (WSL sleep/resume, NTP jump), never with elapsed time.
        self._wall_ns, self._mono_ns = wall_ns, mono_ns
        self._step_threshold_us = int(step_threshold_s * 1_000_000)
        self._step_check_interval_ns = step_check_interval_ms * 1_000_000
        self._skew_ref_us = self._wall_minus_mono_us()
        self._next_step_check_ns = 0
        self._resync_task: asyncio.Task[int] | None = None
        #: Last *verified* offset while a step correction is unconfirmed (else None).
        self._pre_step_offset_us: int | None = None
        self._pre_step_skew_ref_us: int = self._skew_ref_us
        self._step_reverted = False  # next detection is a re-detection (outage), not new
        self._last_measured_monotonic: float | None = None
        self._consecutive_failures = 0
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    # -- public read surface -------------------------------------------------

    def offset_us(self) -> int:
        """The last verified offset (server - local), in microseconds. Never
        raises — before the first successful measurement this is `0`
        (uncorrected), which is why `assert_healthy()` and the age metric
        exist to guard trading on that state, not this accessor. A host clock
        step is folded in immediately (#1912), before any re-measurement."""
        self._maybe_check_host_step()
        return self._offset_us

    def _wall_minus_mono_us(self) -> int:
        return (self._wall_ns() - self._mono_ns()) // 1_000

    def _maybe_check_host_step(self) -> None:
        """Throttled (>= `step_check_interval_ms` apart; never per frame work)."""
        now_ns = self._mono_ns()
        if now_ns < self._next_step_check_ns:
            return
        self._next_step_check_ns = now_ns + self._step_check_interval_ns
        self.check_host_step()

    def check_host_step(self) -> int:
        """Detect a host wall-clock step; returns the step in µs (0 if none).

        offset = server - local, so a pure host step of `s` shifts the offset by
        `-s` exactly. Corrects at once, counts it, and schedules one
        single-flight `measure_once()` (public unsigned endpoint) to confirm."""
        delta_us = self._wall_minus_mono_us()
        step_us = delta_us - self._skew_ref_us
        if abs(step_us) <= self._step_threshold_us:
            return 0
        if self._pre_step_offset_us is None:
            # provisional until confirmed; remember both so a revert re-arms detection
            self._pre_step_offset_us = self._offset_us
            self._pre_step_skew_ref_us = self._skew_ref_us
        self._skew_ref_us = delta_us
        self._offset_us -= step_us
        reason = "host_step_redetect" if self._step_reverted else "host_step"
        clock_resync_triggered_total.labels(reason=reason).inc()
        _log().warning("clock_host_step_detected", step_ms=step_us / _MICROS_PER_MS)
        if self._resync_task is None or self._resync_task.done():
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return step_us  # no loop: periodic task will re-measure
            self._resync_task = spawn(self._resync_after_step(), name="clock-guard-step-resync")
        return step_us

    async def _resync_after_step(self) -> int:
        """Confirm the provisional step correction with a real measurement.

        Retries with doubling backoff up to 30 s (single-flight: one such task). If
        every attempt fails the correction is REVERTED to the last verified offset:
        a suspend/resume or NTP slew can masquerade as a step, and an unverified
        correction must not outlive the evidence (same rule as `measure_once`:
        keep the last *verified* value)."""
        for delay in (*_STEP_RETRY_BACKOFF_S, None):
            try:
                return await self.measure_once()  # success clears the provisional state
            except ClockMeasurementUnavailableError as exc:
                _log().warning("clock_step_measurement_failed", error=str(exc))
            if delay is None:
                break
            await self._sleep(delay)
        if self._pre_step_offset_us is not None:
            self._offset_us = self._pre_step_offset_us
            self._skew_ref_us = self._pre_step_skew_ref_us  # detector re-fires next check
            self._pre_step_offset_us = None
            self._step_reverted = True
        _log().warning("clock_step_unconfirmed", offset_us=self._offset_us)
        return self._offset_us

    def offset_ms_or_none(self) -> int | None:
        """E04-T06 latency provider: `exchange - local` in ms, or `None` before
        the first successful measurement (exchange stage then unavailable,
        never a skew-dominated number)."""
        if self._last_measured_monotonic is None:
            return None
        return self.offset_us() // _MICROS_PER_MS  # includes any detected host step

    def offset_ms_snapshot(self) -> int | None:
        """#913 L1d (CR-S3L1B-09): `offset_ms_or_none` for a reader on another event loop, the
        order lane's trading port: the last verified offset in ms, any host step the serving loop's
        reads have folded in, else `None` before the first successful measurement, never a
        fabricated 0. It runs no host-step check, so it changes nothing, counts nothing and spawns
        no resync on the calling loop: two attribute reads of values replaced whole."""
        if self._last_measured_monotonic is None:
            return None
        return self._offset_us // _MICROS_PER_MS

    def offset_age_s(self) -> float:
        """Seconds since the last successful measurement, or `inf` if none
        has ever completed (scenario "Exchange time endpoint unavailable":
        the age must be exported and alarmed, never hidden)."""
        if self._last_measured_monotonic is None:
            return float("inf")
        return max(0.0, self._clock() - self._last_measured_monotonic)

    def assert_healthy(self) -> None:
        """Raise `ClockDriftError` if the offset exceeds the hard threshold
        or no measurement has ever succeeded. E29 calls this before order
        placement (Story scenario "Hard drift blocks trading"); this class
        never calls it itself — recording, not enforcing (statechart rule
        C-2.21 applies by analogy: this guard records a fact, the caller
        enforces it)."""
        if self._last_measured_monotonic is None:
            raise ClockDriftError("clock offset has never been measured")
        offset_ms = self._offset_us / _MICROS_PER_MS
        if abs(offset_ms) > self._hard_threshold_ms:
            raise ClockDriftError(
                f"clock offset {offset_ms:.1f} ms exceeds hard threshold "
                f"{self._hard_threshold_ms} ms"
            )

    def health_severity(self) -> str:
        """`ok` / `warn` / `critical` for the health surface (SCR-147),
        matching the drift-alarm thresholds without raising."""
        if self._last_measured_monotonic is None:
            return "critical"
        offset_ms = abs(self._offset_us / _MICROS_PER_MS)
        if offset_ms > self._hard_threshold_ms:
            return "critical"
        if offset_ms > self._warn_threshold_ms:
            return "warn"
        return "ok"

    def describe(self) -> str:
        """Human-readable drift message (accessibility note, ticket body):
        "Clock is 1.2 s ahead of the exchange" — never a bare severity dot."""
        if self._last_measured_monotonic is None:
            return "Clock offset has not been measured yet."
        offset_ms = self._offset_us / _MICROS_PER_MS
        direction = "ahead of" if offset_ms > 0 else "behind"
        return f"Clock is {abs(offset_ms) / 1000:.2f} s {direction} the exchange."

    # -- measurement ----------------------------------------------------

    async def measure_once(self) -> int:
        """Take one round-trip-corrected offset burst and update state.

        Samples `self._sample_count` round trips, drops the single sample
        with the largest round-trip time when there are enough samples for
        that to leave a usable set (Test plan: "robust to a slow sample"),
        and returns the median offset (microseconds) of what remains. On
        total failure the last known offset is left untouched, its age
        keeps advancing, and `ClockMeasurementUnavailableError` is raised
        (scenario "Exchange time endpoint unavailable": never silently
        fall back to an uncorrected local clock — falling back here means
        *keeping* the last verified offset, not zeroing it).
        """
        for _attempt in range(_BURST_ATTEMPTS):
            skew_before = self._wall_minus_mono_us()
            offset = await self._measure_burst()
            skew_after = self._wall_minus_mono_us()
            if abs(skew_after - skew_before) <= self._step_threshold_us:
                self._offset_us = offset
                self._skew_ref_us = skew_after
                self._pre_step_offset_us = None
                self._step_reverted = False
                self._record_measured(offset)
                return offset
            _log().warning("clock_step_during_measurement", attempt=_attempt)
        clock_measurements_total.labels(result="failed").inc()
        self._consecutive_failures += 1
        raise ClockMeasurementUnavailableError("host clock stepped during every measurement burst")

    async def _measure_burst(self) -> int:
        samples: list[tuple[int, float]] = []  # (offset_us, rtt_s)
        errors: list[Exception] = []
        for _ in range(self._sample_count):
            try:
                server_time_us, sent_epoch_s, rtt_s = await self._fetch_server_time()
            except Exception as exc:
                errors.append(exc)
                continue
            # offset = server_time - (t_send + rtt/2) — round-trip-corrected
            # estimate (ticket body technical notes), all in microseconds.
            # `sent_epoch_s` MUST be wall-clock (epoch), never monotonic —
            # see `ServerTimeFetcher` docstring.
            local_mid_us = int((sent_epoch_s + rtt_s / 2) * 1_000_000)
            samples.append((server_time_us - local_mid_us, rtt_s))

        if not samples:
            clock_measurements_total.labels(result="failed").inc()
            self._consecutive_failures += 1
            last_error = errors[-1] if errors else "unknown"
            raise ClockMeasurementUnavailableError(
                f"all {self._sample_count} clock-time samples failed: {last_error}"
            )

        clean = self._discard_outlier(samples)
        offsets = sorted(offset for offset, _ in clean)
        return offsets[len(offsets) // 2]

    def _record_measured(self, median_offset_us: int) -> None:
        self._last_measured_monotonic = self._clock()
        self._consecutive_failures = 0
        clock_measurements_total.labels(result="ok").inc()
        exchange_clock_drift_ms.set(median_offset_us / _MICROS_PER_MS)
        clock_offset_age_seconds.set(0.0)
        self._log_if_drifted(median_offset_us)

    @staticmethod
    def _discard_outlier(samples: list[tuple[int, float]]) -> list[tuple[int, float]]:
        """Drop the single largest-RTT sample when there are enough left to
        still form a useful set — a lone slow request must not poison the
        offset (scenario "Measurement is robust to a slow sample")."""
        if len(samples) <= 2:
            return samples
        worst_index = max(range(len(samples)), key=lambda i: samples[i][1])
        return [s for i, s in enumerate(samples) if i != worst_index]

    def _log_if_drifted(self, offset_us: int) -> None:
        offset_ms = offset_us / _MICROS_PER_MS
        if abs(offset_ms) > self._hard_threshold_ms:
            _log().error("clock_drift_critical", offset_ms=offset_ms, severity="critical")
        elif abs(offset_ms) > self._warn_threshold_ms:
            _log().warning("clock_drift_warn", offset_ms=offset_ms, severity="warn")
        else:
            _log().debug("clock_drift_ok", offset_ms=offset_ms, severity="ok")

    # -- signature-failure fallback --------------------------------------

    async def resync_after_signature_failure(self, *, reason: str = "signature_failure") -> int:
        """Immediate re-measure trigger for the REST client's `10002` path
        (Story scenario "Signature failure fallback"). This method owns the
        measurement trigger only — the *single retry* of the failed request
        is the REST client's own `clock_retry_used` guard (E08-T02); a
        second consecutive `10002` must surface `ClockDriftError` rather
        than looping, which this method supports by simply propagating
        `ClockMeasurementUnavailableError`/results without retrying itself.
        """
        clock_resync_triggered_total.labels(reason=reason).inc()
        return await self.measure_once()

    # -- lifecycle (M6 `ingestion` conventions, 20-architecture.md §3) ---

    async def start(self) -> None:
        """Measure once synchronously (so `offset_us()` is meaningful before
        the first request goes out) then start the periodic resync task.
        Task failures never propagate — "failures never cancel the task"
        (technical notes) — they are logged and retried after a jittered
        interval."""
        try:
            await self.measure_once()
        except ClockMeasurementUnavailableError:
            _log().warning("clock_initial_measurement_failed")
        self._stopping = False
        self._task = spawn(self._run_periodic(), name="clock-guard-resync")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._resync_task is not None:
            self._resync_task.cancel()
            try:
                await self._resync_task
            except asyncio.CancelledError:
                pass
            self._resync_task = None

    async def _run_periodic(self) -> None:
        while not self._stopping:
            jitter = self._resync_interval_s * 0.1 * self._random()
            try:
                await self._sleep(self._resync_interval_s + jitter)
            except asyncio.CancelledError:
                return
            if self._stopping:
                return
            try:
                await self.measure_once()
            except ClockMeasurementUnavailableError as exc:
                _log().warning("clock_periodic_measurement_failed", error=str(exc))
            except asyncio.CancelledError:
                return
            except Exception:
                _log().exception("clock_periodic_measurement_unexpected_error")
            clock_offset_age_seconds.set(self.offset_age_s())


class _NormalisedServerTime(Protocol):
    """Normalised server time as exposed by the adapter's validated response model."""

    @property
    def time_us(self) -> int: ...


class _PublicRestClient(Protocol):
    """Structural shape this module needs from an exchange adapter's REST client: a
    `server_time()` that returns a validated, normalised value. Declared here (not imported
    from a concrete adapter) so this module never depends on the exchange adapter
    (C-2.2, C-3.1); payload parsing lives in the adapter (C-2.3)."""

    async def server_time(self) -> _NormalisedServerTime: ...


def rest_client_fetcher(
    client: _PublicRestClient,
    *,
    wall_clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
) -> ServerTimeFetcher:
    """Adapt an exchange adapter's `server_time()` REST
    call to `ServerTimeFetcher`. Kept as a factory function (not a method
    on the client) so the REST client itself never depends on this module —
    the dependency direction is `ClockGuard` -> REST client, matching the
    ticket's "offset is injected into the REST client rather than read from
    a global" (technical notes)."""

    async def _fetch() -> tuple[int, float, float]:
        sent_epoch_s = wall_clock()
        sent_monotonic_s = monotonic()
        server_time = await client.server_time()
        rtt_s = monotonic() - sent_monotonic_s
        server_time_us = server_time.time_us
        return server_time_us, sent_epoch_s, rtt_s

    return _fetch
