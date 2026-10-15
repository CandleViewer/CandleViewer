"""Fake `MonotonicTime` for the replay clock tests (C-13.7: no sleeps, no wall clock).

`FakeTime(auto=True)` jumps to each deadline as soon as the clock waits on it, like a perfect
sleeper. `oversleep_s` adds a deterministic lateness, spread from 0 to that bound, to each wait
to exercise drift correction. With `auto=False` a wait stays parked until the test calls
`advance()` or the clock sets its wake event. It spins on cooperative yields, and a wait that is
never released fails the test instead of hanging it.
"""

from __future__ import annotations

import asyncio
from typing import Final

_SPIN_LIMIT: Final = 100_000


class FakeTime:
    def __init__(
        self, *, start: float = 1_000.0, auto: bool = True, oversleep_s: float = 0.0
    ) -> None:
        self.t = start
        self.auto = auto
        self.oversleep_s = oversleep_s
        self.waits = 0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

    async def wait_until(self, deadline: float, wake: asyncio.Event) -> None:
        self.waits += 1
        await asyncio.sleep(0)
        if self.auto:
            if not wake.is_set() and self.t < deadline:
                self.t = deadline + self.oversleep_s * (self.waits * 7_919 % 101) / 100
            return
        for _ in range(_SPIN_LIMIT):
            if wake.is_set() or self.t >= deadline:
                return
            await asyncio.sleep(0)
        raise AssertionError("FakeTime: a wait was never released")
