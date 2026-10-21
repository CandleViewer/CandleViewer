"""Order entry's halt on clock drift (E29-T04 #913; 24-internal-schemas.md Sec.8.6, `10002`).

24 Sec.8.6 maps `10002`, a request timestamp outside `recv_window`, to `CLOCK_DRIFT`: block all
order entry system-wide, raise a distinct alert, and force a clock resync before resuming. The REST
client re-measures and retries a `10002` once (E08-T02), so one that still reaches an order means
the clock its requests are signed with is off. `ClockHalt.trip()` records that, and from then on
`refusal()` refuses every order request until a measurement taken after the trip passes
`assert_healthy()`: the measurement must be younger than the trip (`offset_age_s()` below the
time since it), as one taken before the trip predates the evidence and never clears it, whatever
it says. Untripped, `refusal()` refuses whenever `assert_healthy()` does (E08-S07, "Hard drift
blocks trading"). Each refusal is a fresh `ClockDriftBlocked`, 503 `clock_drift` with
`Retry-After`, answered before anything is recorded or sent.

The clock (`ports.ClockHealth`, `ingestion.clock.ClockGuard` in slice 3's wiring) records the
verdict; the halt enforces it, synchronously, with no await between its reads. One halt serves the
process, as the block is system-wide. The order path that meets a `10002` trips it and asks for the
resync (slice 2b's command port); the pipeline asks `refusal()` first.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import structlog

from candleviewer.exchange.base.errors import ClockDriftError

from .errors import ClockDriftBlocked
from .ports import ClockHealth

__all__ = ["CLOCK_HALT_RETRY_AFTER_S", "ClockHalt"]

#: The `Retry-After`, in seconds, of an order refused while the clock is not cleared.
CLOCK_HALT_RETRY_AFTER_S: Final = 5


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ClockHalt:
    """The clock gate ahead of every order request (module docstring). `monotonic` reads seconds
    at the rate of the clock behind `offset_age_s()`; only the two durations are compared, so the
    two clocks need not share an origin."""

    def __init__(
        self,
        clock: ClockHealth,
        *,
        monotonic: Callable[[], float],
        retry_after_s: int = CLOCK_HALT_RETRY_AFTER_S,
    ) -> None:
        if isinstance(retry_after_s, bool) or not isinstance(retry_after_s, int):
            raise TypeError("retry_after_s is a whole number of seconds")
        if retry_after_s < 1:
            raise ValueError("retry_after_s is a delay of at least one second")
        self._clock = clock
        self._monotonic = monotonic
        self._retry_after_s = retry_after_s
        self._tripped_at: float | None = None

    def trip(self) -> None:
        """Halt order entry: a `10002` reached an order. A trip while halted restarts the wait,
        so only a measurement taken after the latest trip clears it."""
        again = self._tripped_at is not None
        self._tripped_at = self._monotonic()
        _log().warning("oms_clock_halt_tripped", already_halted=again)

    def refusal(self) -> ClockDriftBlocked | None:
        """None while order entry may go on, else the refusal to answer with. A halt clears here,
        once the clock's last measurement is healthy and younger than the trip."""
        try:
            self._clock.assert_healthy()
        except ClockDriftError:
            return self._refused()
        tripped_at = self._tripped_at
        if tripped_at is None:
            return None
        since_trip = self._monotonic() - tripped_at
        age = self._clock.offset_age_s()
        if not age < since_trip:  # stale, never measured (inf) or unreadable (NaN): fail closed
            return self._refused()
        self._tripped_at = None
        _log().info("oms_clock_halt_cleared", halted_s=round(since_trip, 3))
        return None

    def _refused(self) -> ClockDriftBlocked:
        return ClockDriftBlocked(retry_after_s=self._retry_after_s)
