"""E27-T04 test fakes; `FakeClock` moves monotonic and wall time separately (suspend vs step)."""

from __future__ import annotations

import asyncio
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
    while `hold` is set keeps each call waiting until the test sets it (a slow hook)."""

    def __init__(self, *failing: UUID, clock: FakeClock | None = None) -> None:
        self.transitions: list[HealthTransition] = []
        self.contexts: list[dict[str, Any]] = []
        self.task_names: list[str] = []
        self.called_at: list[float] = []
        self.failing = set(failing)
        self.hold: asyncio.Event | None = None
        self.entered = asyncio.Event()
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
        self.entered.set()
        if self.hold is not None:
            await self.hold.wait()
        if transition.account_id in self.failing:
            raise RuntimeError("echoed exchange text: invalid key")


class Standings(dict[UUID, KeyStanding]):
    def standing(self, account_id: UUID) -> KeyStanding | None:
        return self.get(account_id)


class Sizing(dict[UUID, bool]):
    """Wallet freshness per account; an account with no entry has no snapshot (`None`)."""

    def risk_sizing_available(self, account_id: UUID) -> bool | None:
        return self.get(account_id)
