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
    _utc_now,
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
#: Open positions must answer well inside the 300 ms slice budget, so the flags still show.
POSITIONS_BUDGET_S: Final = 0.2


@dataclass(frozen=True, slots=True)
class StorageHeadroom:
    used_bytes: int
    free_bytes: int
    days_until_full: float | None


@dataclass(frozen=True, slots=True)
class TradingState:
    live_enabled: bool
    kill_switch_engaged: bool
    #: `None` while no OMS positions provider is wired (the slice is then `unavailable`).
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
        now: Callable[[], datetime] = _utc_now,
        positions_budget_s: float = POSITIONS_BUDGET_S,
    ) -> None:
        self._fan, self._now, self._positions_budget_s = fan, now, positions_budget_s
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
        live = await self._oms.live_enabled()
        killed = await self._oms.kill_switch_engaged()
        flags_only = TradingState(live, killed, None)  # kill switch and flag always shown
        try:
            async with asyncio.timeout(self._positions_budget_s):
                positions = await self._oms.open_positions()
        except SourceUnavailable as exc:
            return Degraded(flags_only, "unavailable", exc.detail)
        except TimeoutError:
            return Degraded(flags_only, "error", "open_positions: timed out")
        except Exception:  # the message may carry internals: never forwarded
            return Degraded(flags_only, "error", "open_positions: source failed")
        return TradingState(live, killed, positions)
