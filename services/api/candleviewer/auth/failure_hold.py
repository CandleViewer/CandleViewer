"""`FailureHold` — the minimum time a refused authentication step takes (#4648, #4664).

One helper for every step that checks a credential: the password step of sign-in
(`LoginService`), the second factor and the recovery code (`MfaService`), and the step-up
re-authentication and its password re-check (`StepUpService`). Each step reads `start()`
when it begins and, on a refusal, awaits `hold(started)` after every failure write and
before the refusal leaves the service. So:

- a refusal returns no sooner than the minimum time after its step started;
- a refusal that already took longer is not held further, and is counted
  (`auth_login_failure_floor_missed_total`), so a refusal returned without the wait is
  never silent;
- the wait is never longer than the minimum time itself;
- a success is never held (callers only hold refusals);
- a cancellation during the wait propagates (nothing here catches it).

The minimum time is `CV_AUTH_LOGIN_FAILURE_FLOOR_MS`, one value for every step. A value
below `AUTH_LOGIN_FAILURE_FLOOR_MIN_MS` is refused here as well as by `Settings`, so no
caller can turn the minimum time off (C-4.14); a test that must not wait injects a no-op
`sleep` instead.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

from candleviewer.auth.metrics import auth_login_failure_floor_missed_total
from candleviewer.settings import AUTH_LOGIN_FAILURE_FLOOR_MIN_MS, AUTH_LOGIN_FAILURE_FLOOR_MS

MonotonicClock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

#: The default only: production passes `CV_AUTH_LOGIN_FAILURE_FLOOR_MS`, whose default this is.
FAILURE_MINIMUM = timedelta(milliseconds=AUTH_LOGIN_FAILURE_FLOOR_MS)
#: The lowest minimum time any service accepts: the setting's own lower bound.
FAILURE_MINIMUM_LOWEST = timedelta(milliseconds=AUTH_LOGIN_FAILURE_FLOOR_MIN_MS)


class FailureHold:
    """Holds a refused step until the minimum time has passed since it started."""

    def __init__(
        self,
        minimum: timedelta = FAILURE_MINIMUM,
        *,
        monotonic: MonotonicClock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if minimum < FAILURE_MINIMUM_LOWEST:
            raise ValueError(
                f"the minimum time of a refused authentication step must be at least "
                f"{AUTH_LOGIN_FAILURE_FLOOR_MIN_MS} ms (CV_AUTH_LOGIN_FAILURE_FLOOR_MS)"
            )
        self._minimum_s = minimum.total_seconds()
        self._monotonic = monotonic
        self._sleep = sleep

    @property
    def minimum(self) -> timedelta:
        return timedelta(seconds=self._minimum_s)

    def start(self) -> float:
        """The instant a step starts, on the hold's own clock."""
        return self._monotonic()

    async def hold(self, started: float) -> None:
        """Wait until the minimum time has passed since *started*. Bounded by the minimum time
        itself, and no wait at all when the step already took longer: that step is counted."""
        remaining = started + self._minimum_s - self._monotonic()
        wait = min(remaining, self._minimum_s)
        if wait > 0:
            await self._sleep(wait)
        else:
            auth_login_failure_floor_missed_total.inc()
