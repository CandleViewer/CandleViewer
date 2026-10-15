"""Unit (E42-T01): `AdminOverviewService` assembles the six `GET /admin/overview` slices from
its ports. Every slice is populated when every source answers; a slow recorder degrades only
its own slice; unwired ports are `unavailable`; trading (kill switch, flags) is read live."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.overview.fanout import DEFAULT_BUDGET_S, SliceFanOut, SourceUnavailable
from candleviewer.admin.overview.ports import (
    AccountCounts,
    RecorderStatus,
    StorageSnapshot,
    UserCounts,
)
from candleviewer.admin.overview.service import (
    FLAG_BUDGET_S,
    MIN_MARGIN_S,
    POSITIONS_BUDGET_S,
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
    def __init__(
        self, *, positions: str = "ok", kill: str = "ok", live: str = "ok", killed: bool = False
    ) -> None:
        self.positions, self.kill, self.live, self.killed = positions, kill, live, killed
        self.kill_switch_reads = 0

    async def open_positions(self) -> int:
        if self.positions == "unwired":
            raise SourceUnavailable("open_positions: no provider wired")
        if self.positions == "hang":
            await asyncio.Event().wait()
        if self.positions == "raise":
            raise OSError("postgresql://internal")
        return 2

    async def kill_switch_engaged(self) -> bool:
        self.kill_switch_reads += 1
        if self.kill == "raise":
            raise OSError("kill-switch store down")
        return self.killed

    async def live_enabled(self) -> bool:
        if self.live == "hang":
            await asyncio.Event().wait()
        if self.live == "raise":
            raise OSError("flag store down")
        return True


def _service(
    flag_s: float = FLAG_BUDGET_S, positions_s: float = POSITIONS_BUDGET_S, **ports: Any
) -> AdminOverviewService:
    """The default 300 ms slice budget; hang tests shrink only a sub-budget (no flakes)."""
    fan = SliceFanOut(monotonic=lambda: 0.0, now=lambda: NOW)
    merged: dict[str, Any] = {"counts": Counts(), "recorder": Recorder(), "oms": Oms()} | ports
    return AdminOverviewService(
        fan, now=lambda: NOW, flag_budget_s=flag_s, positions_budget_s=positions_s, **merged
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
    snap = await _service(recorder=Recorder(hang=True)).overview()  # waits the real 300 ms
    assert (snap.recorder.status, snap.recorder.detail) == ("error", "timed out after 300 ms")
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
    snap = await _service(oms=Oms(positions="unwired")).overview()
    assert snap.trading.status == "unavailable"
    assert snap.trading.detail == "open_positions: no provider wired"
    assert snap.trading.value == TradingState(True, False, None)


@pytest.mark.parametrize(
    ("mode", "detail"),
    [("hang", "open_positions: timed out"), ("raise", "open_positions: source failed")],
    ids=["timeout", "failure"],
)
async def test_trading_keeps_kill_switch_and_flag_when_positions_fail(
    mode: str, detail: str
) -> None:
    snap = await _service(oms=Oms(positions=mode), positions_s=0.01).overview()
    assert (snap.trading.status, snap.trading.detail) == ("error", detail)
    assert snap.trading.value == TradingState(True, False, None)


async def test_trading_is_read_live_while_the_other_slices_are_cached() -> None:
    counts, oms = Counts(), Oms()
    service = _service(counts=counts, oms=oms)
    await service.overview()
    await service.overview()
    assert (counts.user_reads, oms.kill_switch_reads) == (1, 2)


async def test_a_failing_flag_read_leaves_no_task_behind() -> None:
    before = asyncio.all_tasks()
    snap = await _service(oms=Oms(kill="raise", live="hang")).overview()
    assert (snap.trading.status, snap.trading.detail) == ("error", "kill_switch: source failed")
    assert asyncio.all_tasks() == before  # the old nested gather leaked one task per call


def test_the_trading_sub_budgets_leave_a_margin_of_the_slice_budget() -> None:
    assert 2 * FLAG_BUDGET_S + POSITIONS_BUDGET_S <= DEFAULT_BUDGET_S - MIN_MARGIN_S
    for flag_s, positions_s in ((0.05, 0.2), (0.0, 0.14), (0.06, 0.14)):
        with pytest.raises(ValueError):
            AdminOverviewService(
                SliceFanOut(), flag_budget_s=flag_s, positions_budget_s=positions_s
            )


@pytest.mark.parametrize("live", ["hang", "raise"], ids=["live-flag-hangs", "live-flag-raises"])
async def test_the_kill_switch_survives_a_failed_live_flag_read(live: str) -> None:
    snap = await _service(oms=Oms(live=live, killed=True), flag_s=0.01).overview()
    assert snap.trading.status == "error" and snap.trading.detail is not None
    assert snap.trading.detail.startswith("live_flag: ")
    assert snap.trading.value == TradingState(None, True, 2)  # kill switch engaged, still shown


async def test_a_partial_trading_failure_logs_part_and_class_never_the_message() -> None:
    with capture_logs() as logs:
        await _service(oms=Oms(positions="raise"), positions_s=0.01).overview()
    assert [e["reason"] for e in logs] == ["open_positions:OSError"]
    assert "postgresql" not in repr(logs)
