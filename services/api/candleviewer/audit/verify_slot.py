"""Single-flight for audit chain verification (contract #2392/#2446): at most one run at a
time, the scheduled (start-up and nightly) job included.

An on-demand run tries (`try_acquire`) and is refused with `409` while the slot is held or a
scheduled run is waiting for it. A scheduled run waits (`acquire`), first come first served,
so it is never skipped. The start-up and nightly verify job (`verify_job.py`, #2111) takes
`AuditService.query.verify_slot` with `acquire()` and gives it back with `release()` in a
`finally`; it is inert until the real runner is wired (#2966), so until then only on-demand runs
take the slot. The slot is handed straight to the next waiter, so an on-demand run never slips
in between.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque


class VerifySlot:
    def __init__(self) -> None:
        self._held = False
        self._waiters: deque[asyncio.Future[None]] = deque()

    @property
    def held(self) -> bool:
        return self._held

    def try_acquire(self) -> bool:
        """Take the slot if it is free and nobody waits for it (an on-demand run)."""
        if self._held or self._waiters:
            return False
        self._held = True
        return True

    async def acquire(self) -> None:
        """Wait for the slot (a scheduled run): never skipped, first come first served."""
        if self.try_acquire():
            return
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():  # handed over as the cancel came
                self.release()
            else:
                with contextlib.suppress(ValueError):  # `release` may have dropped it
                    self._waiters.remove(waiter)
            raise

    def release(self) -> None:
        """Give the slot back, or hand it to the first waiter still waiting."""
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)  # the waiter now holds the slot
                return
        self._held = False
