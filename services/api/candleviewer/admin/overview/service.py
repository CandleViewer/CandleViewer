"""`AdminOverviewService` (E42-T01): the `GET /admin/overview` read model.

Six slices, read concurrently through the shared `SliceFanOut` (one budget, cache and failure
mapping each): users, accounts and incidents from the relational counts; recorder and storage
from the recorder port; trading from the OMS port, read live on every call because kill-switch
and flag state are never cached. A port that is not wired makes its slice `unavailable`. The
trading flags are awaited in turn; open positions get a shorter budget so the flags survive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from candleviewer.admin.overview.fanout import (
    Degraded,
    SliceFanOut,
    SliceResult,
    SourceUnavailable,
    combine,
    read_part,
    utc_now,
)
from candleviewer.admin.overview.ports import (
    AccountCounts,
    CountsPort,
    OmsPort,
    RecorderPort,
    RecorderStatus,
    UserCounts,
)
from candleviewer.admin.overview.slices import AdminSlice

#: `AdminOverview.accounts.keys_expiring_30d`.
KEY_EXPIRY_WINDOW: Final = timedelta(days=30)
#: Trading sub-reads run one after another, each under its own sub-budget; together they
#: must leave `MIN_MARGIN_S` of the slice budget, so a slow OMS never loses the kill switch.
FLAG_BUDGET_S: Final = 0.05
POSITIONS_BUDGET_S: Final = 0.14
MIN_MARGIN_S: Final = 0.05


@dataclass(frozen=True, slots=True)
class StorageHeadroom:
    used_bytes: int
    free_bytes: int
    days_until_full: float | None


@dataclass(frozen=True, slots=True)
class TradingState:
    """A field is `None` when its part could not be read (the slice is then degraded)."""

    live_enabled: bool | None
    kill_switch_engaged: bool | None
    open_positions: int | None


@dataclass(frozen=True, slots=True)
class OverviewSnapshot:
    generated_at: datetime
    users: SliceResult[UserCounts]
    accounts: SliceResult[AccountCounts]
    recorder: SliceResult[RecorderStatus]
    storage: SliceResult[StorageHeadroom]
    trading: SliceResult[TradingState]
    incidents: SliceResult[int]


def _unwired(source: str) -> SourceUnavailable:
    return SourceUnavailable(f"{source}: no provider wired")


class AdminOverviewService:
    def __init__(
        self,
        fan: SliceFanOut,
        *,
        counts: CountsPort | None = None,
        recorder: RecorderPort | None = None,
        oms: OmsPort | None = None,
        now: Callable[[], datetime] = utc_now,
        flag_budget_s: float = FLAG_BUDGET_S,
        positions_budget_s: float = POSITIONS_BUDGET_S,
    ) -> None:
        spent = 2 * flag_budget_s + positions_budget_s
        if min(flag_budget_s, positions_budget_s) <= 0 or spent > fan.budget_s - MIN_MARGIN_S:
            raise ValueError("trading sub-budgets must leave 50 ms of the slice budget")
        self._fan, self._now = fan, now
        self._flag_budget_s, self._positions_budget_s = flag_budget_s, positions_budget_s
        self._counts, self._recorder, self._oms = counts, recorder, oms

    async def overview(self) -> OverviewSnapshot:
        read = self._fan.read
        users, accounts, recorder, storage, trading, incidents = await asyncio.gather(
            read(AdminSlice.USERS, self._users),
            read(AdminSlice.ACCOUNTS, self._accounts),
            read(AdminSlice.RECORDER, self._recorder_status),
            read(AdminSlice.STORAGE, self._storage),
            read(AdminSlice.TRADING, self._trading, cached=False),
            read(AdminSlice.INCIDENTS, self._incidents),
        )
        return OverviewSnapshot(self._now(), users, accounts, recorder, storage, trading, incidents)

    async def _users(self) -> UserCounts:
        if self._counts is None:
            raise _unwired("users")
        return await self._counts.user_counts()

    async def _accounts(self) -> AccountCounts:
        if self._counts is None:
            raise _unwired("accounts")
        return await self._counts.account_counts(self._now() + KEY_EXPIRY_WINDOW)

    async def _incidents(self) -> int:
        if self._counts is None:
            raise _unwired("incidents")
        return await self._counts.open_incidents()

    async def _recorder_status(self) -> RecorderStatus:
        if self._recorder is None:
            raise _unwired("recorder")
        return await self._recorder.recorder_status()

    async def _storage(self) -> StorageHeadroom:
        if self._recorder is None:
            raise _unwired("storage")
        snap = await self._recorder.storage_snapshot()
        if snap is None:
            raise SourceUnavailable("storage: no disk sample yet")
        return StorageHeadroom(snap.used_bytes, snap.free_bytes, snap.days_until_full)

    async def _trading(self) -> TradingState | Degraded[TradingState]:
        if self._oms is None:
            raise _unwired("trading")
        oms, flag_s = self._oms, self._flag_budget_s
        # The kill switch first: whatever fails after it, the tile keeps showing its state.
        killed, kill_problem = await read_part("kill_switch", oms.kill_switch_engaged, flag_s)
        live, live_problem = await read_part("live_flag", oms.live_enabled, flag_s)
        positions, positions_problem = await read_part(
            "open_positions", oms.open_positions, self._positions_budget_s
        )
        state = TradingState(live, killed, positions)
        return combine(state, [kill_problem, live_problem, positions_problem])
