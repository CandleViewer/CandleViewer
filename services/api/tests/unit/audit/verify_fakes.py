"""A scripted `VerifyRunner` for the scheduled verify job's tests (#2111). No database, no
network, no sleeps."""

from __future__ import annotations

import asyncio
from collections import deque

from candleviewer.audit.verify_runner import VerifyOutcome, VerifyRunRequest


class FakeVerifyRunner:
    """Each `run()` records its request, then returns the next scripted outcome or raises the
    next scripted exception. A run past the end of the script is a test bug (`IndexError`).

    With `hold`, a run sets `entered` and then waits for `hold`, so a test can cancel it
    mid-run or check the verify slot while it runs."""

    def __init__(
        self, *script: VerifyOutcome | BaseException, hold: asyncio.Event | None = None
    ) -> None:
        self._script = deque(script)
        self._hold = hold
        self.entered = asyncio.Event()
        self.requests: list[VerifyRunRequest] = []

    async def run(self, request: VerifyRunRequest) -> VerifyOutcome:
        self.requests.append(request)
        self.entered.set()
        if self._hold is not None:
            await self._hold.wait()
        step = self._script.popleft()
        if isinstance(step, BaseException):
            raise step
        return step
