"""Unit (E42-T01): `AdminOverviewService` assembles the six `GET /admin/overview` slices from
its ports. Every slice is populated when every source answers; a slow recorder degrades only
its own slice; unwired ports are `unavailable`; trading (kill switch, flags) is read live."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from candleviewer.admin.overview.fanout import SliceFanOut, SourceUnavailable
from candleviewer.admin.overview.ports import (
    AccountCounts,
    RecorderStatus,
    StorageSnapshot,
    UserCounts,
)
from candleviewer.admin.overview.service import (
    AdminOverviewService,
    StorageHeadroom,
    TradingState,
)

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
GB = 10**9


class Counts:
    def __init__(self) -> None:
        self.user_reads = 0
        self.expiring_before: datetime | None = None

    async def user_counts(self) -> UserCounts:
        self.user_reads += 1
        return UserCounts(total=4, active=3, without_mfa=1)

    async def account_counts(self, expiring_before: datetime) -> AccountCounts:
        self.expiring_before = expiring_before
        return AccountCounts(total=4, enabled=3, keys_expiring_30d=1, keys_invalid=0)

    async def open_incidents(self) -> int:
        return 2


class Recorder:
    def __init__(self, *, hang: bool = False, sampled: bool = True) -> None:
        self.hang, self.sampled = hang, sampled

    async def recorder_status(self) -> RecorderStatus:
        if self.hang:  # the AC's "does not respond within its 300 ms budget"
            await asyncio.Event().wait()
        return RecorderStatus(symbols_recording=3, symbols_degraded=0, lag_seconds_p99=0.042)

    async def storage_snapshot(self) -> StorageSnapshot | None:
        return StorageSnapshot(41 * GB, 400 * GB, None, 187.5, ()) if self.sampled else None


class Oms:
    def __init__(self, *, positions: bool = True) -> None:
        self.positions, self.kill_switch_reads = positions, 0

    async def open_positions(self) -> int:
        if not self.positions:
            raise SourceUnavailable("open_positions: no provider wired")
        return 2

    async def kill_switch_engaged(self) -> bool:
        self.kill_switch_reads += 1
        return False

    async def live_enabled(self) -> bool:
        return True


def _service(
    *, recorder: Recorder | None = None, oms: Oms | None = None, counts: Counts | None = None
) -> AdminOverviewService:
    fan = SliceFanOut(budget_s=0.01, monotonic=lambda: 0.0, now=lambda: NOW)
    return AdminOverviewService(
        fan,
        counts=counts or Counts(),
        recorder=recorder or Recorder(),
        oms=oms or Oms(),
        now=lambda: NOW,
    )


async def test_every_slice_is_populated_when_every_source_answers() -> None:
    snap = await _service().overview()
    assert snap.generated_at == NOW
    assert snap.users.value == UserCounts(4, 3, 1)
    assert snap.accounts.value == AccountCounts(4, 3, 1, 0)
    assert snap.recorder.value == RecorderStatus(3, 0, 0.042)
    assert snap.storage.value == StorageHeadroom(41 * GB, 400 * GB, 187.5)
    assert snap.trading.value == TradingState(True, False, 2)
    assert snap.incidents.value == 2
    slices = (snap.users, snap.accounts, snap.recorder, snap.storage, snap.trading, snap.incidents)
    assert {s.status for s in slices} == {"ok"}


async def test_a_recorder_that_misses_its_budget_degrades_only_its_slice() -> None:
    snap = await _service(recorder=Recorder(hang=True)).overview()
    assert (snap.recorder.status, snap.recorder.detail) == ("error", "timed out after 10 ms")
    others = (snap.users, snap.accounts, snap.storage, snap.trading, snap.incidents)
    assert {s.status for s in others} == {"ok"}


async def test_unwired_ports_make_their_slices_unavailable() -> None:
    fan = SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    snap = await AdminOverviewService(fan, now=lambda: NOW).overview()
    details = {
        name: (getattr(snap, name).status, getattr(snap, name).detail)
        for name in ("users", "accounts", "recorder", "storage", "trading", "incidents")
    }
    assert details == {n: ("unavailable", f"{n}: no provider wired") for n in details}


async def test_keys_nearing_expiry_are_counted_over_the_next_30_days() -> None:
    counts = Counts()
    await _service(counts=counts).overview()
    assert counts.expiring_before == NOW + timedelta(days=30)


async def test_storage_before_the_first_disk_sample_is_unavailable() -> None:
    snap = await _service(recorder=Recorder(sampled=False)).overview()
    assert (snap.storage.status, snap.storage.detail) == (
        "unavailable",
        "storage: no disk sample yet",
    )


async def test_trading_without_a_positions_provider_keeps_kill_switch_and_flag() -> None:
    snap = await _service(oms=Oms(positions=False)).overview()
    assert snap.trading.status == "unavailable"
    assert snap.trading.detail == "open_positions: no provider wired"
    assert snap.trading.value == TradingState(True, False, None)


async def test_trading_is_read_live_while_the_other_slices_are_cached() -> None:
    counts, oms = Counts(), Oms()
    service = _service(counts=counts, oms=oms)
    await service.overview()
    await service.overview()
    assert (counts.user_reads, oms.kill_switch_reads) == (1, 2)
