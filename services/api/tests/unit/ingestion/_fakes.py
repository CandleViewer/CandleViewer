"""Shared ingestion test doubles (no network, no real time, C-13.7)."""

from __future__ import annotations

import asyncio


class ParkingSleep:
    """Fake `sleep`: records each delay and parks the caller until `release()`, so a test
    steps a retry schedule one wait at a time (no real time passes)."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.parked: list[asyncio.Future[None]] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        wake: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.parked.append(wake)
        await wake

    def release(self) -> None:
        self.parked.pop(0).set_result(None)


async def settle(spins: int = 20) -> None:
    """Let ready tasks run until they park again (event-loop turns, no time passes)."""
    for _ in range(spins):
        await asyncio.sleep(0)
