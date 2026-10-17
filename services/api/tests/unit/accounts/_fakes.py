"""E27-T04 test fakes; `FakeClock` moves monotonic and wall time separately (suspend vs step)."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from candleviewer.accounts.health import HealthTransition
from candleviewer.accounts.order_gate import KeyStanding
from candleviewer.observability.context import get_context

T0 = datetime(2026, 10, 15, 12, tzinfo=UTC)
DAY = timedelta(days=1)


class FakeClock:
    def __init__(self) -> None:
        self.mono = 1_000.0
        self.wall = T0

    def monotonic(self) -> float:
        return self.mono

    def now(self) -> datetime:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


ACC = UUID("a1000000-0000-4000-8000-000000000001")
ACC_B = UUID("a1000000-0000-4000-8000-000000000002")


class Dms:
    """Dead-man's-switch hook: records every call with the correlation context and task name it
    ran under (and its monotonic time, given a clock), raises for the `failing` accounts, and
    while `hold` is set keeps each call waiting until the test sets the event that was `hold`
    when the call started (a slow hook); with `stubborn` it swallows every cancellation
    meanwhile (a hook that breaks the contract). `entered` is set once a call starts and
    `exited` once one has returned or raised; `active` counts the calls inside the hook now,
    `peak` the most there ever were, and `idle` is set while none is."""

    def __init__(self, *failing: UUID, clock: FakeClock | None = None) -> None:
        self.transitions: list[HealthTransition] = []
        self.contexts: list[dict[str, Any]] = []
        self.task_names: list[str] = []
        self.called_at: list[float] = []
        self.failing = set(failing)
        self.hold: asyncio.Event | None = None
        self.stubborn = False
        self.active = self.peak = 0
        self.idle = asyncio.Event()
        self.idle.set()
        self.entered = asyncio.Event()
        self.exited = asyncio.Event()
        self._clock = clock

    @property
    def calls(self) -> list[tuple[UUID, str]]:
        return [(t.account_id, t.reason) for t in self.transitions]

    async def account_down(self, transition: HealthTransition) -> None:
        self.transitions.append(transition)
        self.contexts.append(get_context())
        task = asyncio.current_task()
        assert task is not None
        self.task_names.append(task.get_name())
        if self._clock is not None:
            self.called_at.append(self._clock.monotonic())
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.idle.clear()
        self.entered.set()
        hold = self.hold
        try:
            while hold is not None and not hold.is_set():
                try:
                    await hold.wait()
                except asyncio.CancelledError:
                    if not self.stubborn:
                        raise
            if transition.account_id in self.failing:
                raise RuntimeError("echoed exchange text: invalid key")
        finally:
            self.active -= 1
            if not self.active:
                self.idle.set()
            self.exited.set()


class Jitter(random.Random):
    """The retry-jitter RNG: each draw lands `fraction` of the way through the range it is asked
    for (1.0, the default, is no jitter), and every range is recorded."""

    def __init__(self, fraction: float = 1.0) -> None:
        super().__init__(0)
        self.fraction = fraction
        self.ranges: list[tuple[float, float]] = []

    def uniform(self, a: float, b: float) -> float:
        self.ranges.append((a, b))
        return a + (b - a) * self.fraction


class Standings(dict[UUID, KeyStanding]):
    """The key verifier's last result per account; an account with no entry is unknown."""

    def standing(self, account_id: UUID) -> KeyStanding | None:
        return self.get(account_id)


class Sizing(dict[UUID, bool]):
    """Whether risk-based sizing may use each account's balance; an account with no entry has no
    snapshot (`None`)."""

    def risk_sizing_available(self, account_id: UUID) -> bool | None:
        return self.get(account_id)
