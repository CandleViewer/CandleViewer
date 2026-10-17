"""ADR-0037 S1c: the lane's byte quotas, and its lock's waiter caps with `reserved` first
(`docs/plan/24-internal-schemas.md` §15.6 Limits; readings 2 and 6 of the ruling on #3009).
All I/O is in `tmp_path`; nothing sleeps. Keys are test vectors."""

from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

import pytest

from candleviewer.audit import lane_journal as lj

KEYS, LANE, WAIT_S = lj.LaneKeys(bytes(range(32))), uuid.UUID(int=7), 5.0


def rec(n: int, action: str = "auth.logout", outcome: str = "success") -> dict[str, object]:
    return {"action": action, "outcome": outcome, "n": n}


STARTED, LOGIN = rec(0, "audit.lane_started"), rec(1, "auth.login_failed", "failure")


def size(seq: int, record: dict[str, object], cls: Literal["reserved", "shared"]) -> int:
    return len(lj.encode_frame(KEYS, lane=LANE, seq=seq, prev=lj.ZERO_MAC, cls=cls, rec=record))


F1, F2, FS = size(1, STARTED, "reserved"), size(2, rec(1), "reserved"), size(2, LOGIN, "shared")


class Parked(lj.LaneFiles):
    """Holds the next fsync until `release`, so its op keeps the lane lock meanwhile."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.park, self.parked, self.release = False, threading.Event(), threading.Event()

    def fsync(self, fd: int) -> None:
        if self.park:
            self.park = False
            self.parked.set()
            self.release.wait(WAIT_S)
        super().fsync(fd)


async def boot(
    path: Path, files: lj.LaneFiles | None = None, **limits: Any
) -> tuple[lj.LaneJournal, lj.LaneScan]:
    lane = lj.LaneJournal(files or lj.LaneFiles(path), KEYS, **limits)
    return lane, await lane.open(lambda: LANE)


async def settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0)


async def test_lane_quotas_refuse_full_and_shared_keeps_to_its_share(tmp_path: Path) -> None:
    """Past `LANE_MAX_BYTES`, or `SHARED_MAX_BYTES` for a `shared` append, the append is refused
    `full` and nothing is written, while a `reserved` append still fits where `shared` may not."""
    lane, _ = await boot(tmp_path, lane_max_bytes=F1 + FS + 2 * F2, shared_max_bytes=FS)
    assert [await lane.append(record) for record in (STARTED, LOGIN)] == [1, 2]
    with pytest.raises(lj.LaneRefused) as shared:
        await lane.append(LOGIN)
    assert [await lane.append(rec(n)) for n in (3, 4)] == [3, 4]  # exactly LANE_MAX_BYTES
    with pytest.raises(lj.LaneRefused) as full:
        await lane.append(rec(5))
    await lane.close()

    assert shared.value.reason == full.value.reason == "full"
    assert (tmp_path / lj.segment_name(1)).stat().st_size == F1 + FS + 2 * F2


async def test_lane_quota_counts_every_byte_after_the_marker(tmp_path: Path) -> None:
    """Reading 2: a boot counts the bytes after the marker, a run's among them, and a
    confirmation frees the bytes it passes."""
    lane, _ = await boot(tmp_path)
    for record in (STARTED, rec(1)):
        await lane.append(record)
    await lane.close()
    segment = tmp_path / lj.segment_name(1)
    segment.write_bytes(segment.read_bytes() + b"junk")  # a run of four bytes after frame 2
    lane, result = await boot(tmp_path, lane_max_bytes=F1 + 2 * F2 + 3)
    one = result.units[0]
    with pytest.raises(lj.LaneRefused) as full:
        await lane.append(rec(2))
    assert one.state.next_seq is not None
    await lane.confirm(lj.LaneMarker(LANE, one.end, one.state.next_seq, one.state.prev, True))
    assert full.value.reason == "full" and await lane.append(rec(2)) == 3
    await lane.close()


async def test_lane_waiters_are_capped_per_class_and_reserved_go_first(tmp_path: Path) -> None:
    """Lane lock waiters: past its class's cap an append is refused `busy` at once, never queued;
    when the lock frees, a queued `reserved` append goes before an older `shared` one. The
    drain's operations queue with `reserved`, outside the caps (reading 6)."""
    disk = Parked(tmp_path)
    lane, _ = await boot(tmp_path, disk, waiters={"reserved": 1, "shared": 1})
    await lane.append(STARTED)
    disk.park = True
    holder = asyncio.create_task(lane.append(rec(1)))
    assert await asyncio.to_thread(disk.parked.wait, WAIT_S)
    queued = [asyncio.create_task(lane.append(record)) for record in (LOGIN, rec(3))]
    await settle()
    refused = []
    for record in (LOGIN, rec(4)):
        with pytest.raises(lj.LaneRefused) as busy:
            await lane.append(record)
        refused.append(busy.value.reason)
    confirming = asyncio.create_task(lane.confirm(lj.LaneMarker(LANE, (1, 0), 1, "0" * 64, True)))
    await settle()
    assert not confirming.done()
    disk.release.set()
    seqs = await asyncio.wait_for(asyncio.gather(holder, *queued, confirming), WAIT_S)
    await lane.close()

    assert refused == ["busy", "busy"] and seqs == [2, 4, 3, None]


async def test_lane_lock_survives_cancelled_waiters() -> None:
    """A waiter cancelled while queued frees its slot, also when `release()` meets it first, and
    one granted the lock just as it was cancelled passes the lock on."""
    lock = lj._LaneLock({"reserved": 1, "shared": 1})
    await lock.acquire("shared", True)
    first = asyncio.create_task(lock.acquire("reserved", True))
    await settle()
    first.cancel()
    await settle()  # it leaves the queue itself
    second = asyncio.create_task(lock.acquire("reserved", True))  # in the slot `first` freed
    await settle()
    second.cancel()
    lock.release()  # meets `second`, cancelled but not yet run, and frees the lock
    third, fourth = (asyncio.create_task(lock.acquire(c, True)) for c in ("reserved", "shared"))
    await settle()
    lock.release()  # grants `fourth`, which is cancelled before it runs: it passes the lock on
    fourth.cancel()
    await settle()
    for task in (first, second, fourth):
        with pytest.raises(asyncio.CancelledError):
            await task
    await third

    assert not lock._held and not any(lock._queues.values())
