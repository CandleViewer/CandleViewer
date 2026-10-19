"""E27-T04 test fakes; `FakeClock` moves monotonic and wall time separately (suspend vs step)."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from uuid import UUID

from candleviewer.accounts.health import HealthTransition
from candleviewer.accounts.order_gate import KeyStanding
from candleviewer.domain.primitives import Exchange
from candleviewer.observability.context import get_context
from candleviewer.storage.repositories.accounts import ExchangeAccountRow, SelfCheckTargetRow
from candleviewer.storage.repositories.dms_episodes_sqlalchemy import DmsEpisodeRow

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


def key_of(account: UUID) -> UUID:
    """`key_row`'s default key id for an account."""
    return UUID(int=account.int + 100)


def key_row(
    account: UUID,
    *,
    key: UUID | None = None,
    verified_at: datetime = T0,
    error: str | None = None,
    armed: bool = True,
    enabled: bool = True,
    env: str = "testnet",
) -> SelfCheckTargetRow:
    """One usable stored key as the usable-key read returns it: its stored last pass
    (`verified_at`), last error code, and its account, enabled and armed for trading by default."""
    # A dict literal, not keywords: ruff S106 reads `colour_token=` as a password. The venue is the
    # domain's one `Exchange`, so this helper names no venue (C-2.2).
    fields: dict[str, Any] = {
        "id": account, "exchange": get_args(Exchange)[0], "env": env, "kind": "main",
        "exchange_uid": "1000001", "parent_account_id": None, "label": "fx",
        "colour_token": "accent.neutral", "is_enabled": enabled, "trading_enabled": armed,
        "position_mode": "one_way",
        "margin_mode": "cross", "account_type": "UNIFIED", "quote_ccy": "USDT",
        "equity_cached_usd": None, "equity_cached_at": None, "max_sub_accounts_hint": 5,
        "last_reconciled_at": None, "created_at": T0, "updated_at": T0, "deleted_at": None,
    }  # fmt: skip
    row = ExchangeAccountRow(**fields)
    return SelfCheckTargetRow(key or key_of(account), False, verified_at, row, error)


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


@dataclass
class Episode:
    account_id: UUID
    from_state: str
    reason: str
    at: datetime
    resolved: bool = False


class Journal:
    """The episode journal (`system_events` in production), rows by id. A step (`record`,
    `resolve`, `read`) in `fail` raises; one in `hold` waits for the event first, and holds its
    cancellation until then too (a stuck server, which the driver's cleanup also waits for), then
    raises its `fail`, if any, in the cancellation's place."""

    def __init__(self, *episodes: Episode) -> None:
        self.rows = {n: replace(e) for n, e in enumerate(episodes, start=1)}  # its own copies
        self.fail: dict[str, BaseException] = {}
        self.hold: dict[str, asyncio.Event] = {}
        self.limits: list[int] = []

    def open(self) -> list[UUID]:
        return [e.account_id for e in self.rows.values() if not e.resolved]

    async def _step(self, name: str) -> None:
        if (hold := self.hold.get(name)) is not None:
            try:
                await hold.wait()
            except asyncio.CancelledError:
                await hold.wait()
                raise self.fail.get(name, asyncio.CancelledError()) from None
        if (error := self.fail.get(name)) is not None:
            raise error

    async def record(self, account_id: UUID, *, from_state: str, reason: str, at: datetime) -> int:
        await self._step("record")
        self.rows[len(self.rows) + 1] = Episode(account_id, from_state, reason, at)
        return len(self.rows)

    async def resolve(self, account_id: UUID, row: int) -> None:
        """The row and its account's older rows, as the SQL does."""
        await self._step("resolve")
        for n, episode in self.rows.items():
            episode.resolved |= episode.account_id == account_id and n <= row

    async def open_episodes(self, limit: int) -> tuple[DmsEpisodeRow, ...]:
        """The latest open row per account, newest first, `limit` at most."""
        self.limits.append(limit)
        await self._step("read")
        latest = {e.account_id: (n, e) for n, e in self.rows.items() if not e.resolved}
        newest = sorted(latest.values(), key=lambda pair: pair[0], reverse=True)[:limit]
        return tuple(
            DmsEpisodeRow(n, e.account_id, e.from_state, e.reason, e.at) for n, e in newest
        )
