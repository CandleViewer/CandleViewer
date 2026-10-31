"""Ingest-boundary rejection accounting (#1889 / #1890 / #1892, §14.2 rule 9).

One place turns any per-frame failure into: a bounded `reason`, one
`ingest_rejected_total{stream, reason}` increment and at most one structured
log line per (stream, reason) per `LOG_INTERVAL_S` (no payload is ever logged).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final, Literal

import structlog

from candleviewer.exchange.base.frame_guard import (
    MAX_FUTURE_SKEW_MS,
    REJECT_REASONS,
    FrameRejectedError,
    check_event_window,
)
from candleviewer.ingestion.metrics import ingest_rejected_total

_LOGGER_NAME: Final[str] = __name__

Stream = Literal["trade", "ticker", "book", "pump", "liquidation"]
LOG_INTERVAL_S: Final[float] = 10.0


def reason_of(exc: BaseException) -> str:
    """Bounded label value for `exc` (never free text)."""
    if isinstance(exc, FrameRejectedError) and exc.reason in REJECT_REASONS:
        return exc.reason
    if isinstance(exc, RecursionError):
        return "depth_limit"
    if isinstance(exc, ValueError):
        return "malformed"
    return "internal_error"


class RejectionLog:
    """Per-stream counter + rate-limited log; O(1) per rejection."""

    __slots__ = ("_clock", "_last", "_stream", "suppressed")

    def __init__(self, stream: Stream, clock: Callable[[], float] = time.monotonic) -> None:
        self._stream, self._clock = stream, clock
        self._last: dict[str, float] = {}
        self.suppressed = 0

    def record(self, exc: BaseException) -> str:
        reason = reason_of(exc)
        ingest_rejected_total.labels(stream=self._stream, reason=reason).inc()
        now = self._clock()
        last = self._last.get(reason)
        if last is not None and now - last < LOG_INTERVAL_S:
            self.suppressed += 1
            return reason
        self._last[reason] = now
        # Resolved per call (rate-limited path): a module-level logger cached under
        # `cache_logger_on_first_use=True` keeps a stale processor chain after
        # `configure_logging()` runs (same pitfall as observability/metrics.py).
        structlog.get_logger(_LOGGER_NAME).warning(
            f"{self._stream} frame rejected",
            stream=self._stream,
            reason=reason,
            error=type(exc).__name__,
            suppressed=self.suppressed,
        )
        self.suppressed = 0
        return reason


#: Prints stamped up to this long before `launchTime` are tolerated (pre-market auction).
LAUNCH_GRACE_US: Final[int] = 24 * 3600 * 1_000_000


def corrected_now_us(
    offset_us: Callable[[], int],
    host_now_us: Callable[[], int] = lambda: time.time_ns() // 1000,
) -> Callable[[], int]:
    """Exchange-corrected "now" in µs (#1912): host wall clock + `ClockGuard.offset_us()`.

    The guard's offset is `server - local` (venue ahead of host -> positive) and
    already includes any detected host clock step. Applied exactly once, here;
    `host_now_us` must be the raw host clock."""
    return lambda: host_now_us() + offset_us()


class EventWindow:
    """`[launchTime - grace, now + max_future_skew]` over an injected wall clock
    (#1892). Raises `FrameRejectedError`; a missing launch time skips that side."""

    __slots__ = ("_launch", "_now", "_skew")

    def __init__(
        self,
        now_us: Callable[[], int],
        launch_time_us: Callable[[str], int | None],
        max_future_skew_us: int = MAX_FUTURE_SKEW_MS * 1000,
    ) -> None:
        self._now, self._launch, self._skew = now_us, launch_time_us, max_future_skew_us

    def __call__(self, symbol: str, ts_us: int) -> None:
        check_event_window(
            ts_us,
            now_us=self._now(),
            launch_us=self._launch(symbol),
            future_skew_us=self._skew,
            launch_grace_us=LAUNCH_GRACE_US,
            symbol=symbol,
        )
