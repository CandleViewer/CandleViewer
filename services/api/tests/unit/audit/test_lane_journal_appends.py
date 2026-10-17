"""ADR-0037 S1b: appends, segments, their fsync points, failures and the registry
(`docs/plan/24-internal-schemas.md` §15.6; rulings R1 and R2 on #3009). All I/O is in `tmp_path`,
through `LaneFiles` or `Disk`, which injects faults. Nothing sleeps. Keys are test vectors."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import stat
import threading
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.audit import lane_journal as lj
from candleviewer.audit.actions import AUDIT_ACTIONS, LANE_ACTIONS

Rec = dict[str, object]
KEY = bytes(range(32))
KEYS, OTHER_KEYS = lj.LaneKeys(KEY), lj.LaneKeys(bytes(range(32, 64)))
LANE, OTHER = uuid.UUID(int=7), uuid.UUID(int=8)
WAIT_S = 5.0  # a hang fails instead of blocking
LOGINS = "login login_failed account_locked mfa_failed recovery_codes_exhausted recovery_code_used"


def rec(n: int = 0, action: str = "auth.logout", outcome: str = "success", pad: int = 0) -> Rec:
    return {"action": action, "outcome": outcome, "n": n, "pad": "x" * pad}


STARTED = rec(action="audit.lane_started")
F1, F2 = (
    len(lj.encode_frame(KEYS, lane=LANE, seq=seq, prev=lj.ZERO_MAC, cls="reserved", rec=record))
    for seq, record in ((1, STARTED), (2, rec(1)))
)
SEG = F1 + F2  # seg-1 holds frames 1 and 2, seg-3 frames 3 and 4, and so on (`rec(n)`, n < 10)


class Disk(lj.LaneFiles):
    """`fail` maps a primitive to the call that raises EIO (a failing write writes half first);
    `park` holds the next fsync."""

    def __init__(self, path: Path, fail: dict[str, int] | None = None) -> None:
        super().__init__(path)
        self.fail, self.calls = dict(fail or {}), Counter[str]()
        self.park, self.parked, self.release = False, threading.Event(), threading.Event()

    def hit(self, name: str) -> None:
        self.calls[name] += 1
        if self.fail.get(name) == self.calls[name]:
            raise OSError(errno.EIO, name)

    def fsync(self, fd: int) -> None:
        if self.park:
            self.park = False
            self.parked.set()
            self.release.wait(WAIT_S)
        self.hit("fsync")
        super().fsync(fd)

    def write(self, fd: int, data: bytes) -> None:
        try:
            self.hit("write")
        except OSError:
            super().write(fd, data[: len(data) // 2])
            raise
        super().write(fd, data)

    def truncate(self, fd: int, length: int) -> None:
        self.hit("truncate")
        super().truncate(fd, length)

    def unlink(self, path: Path) -> None:
        self.hit("unlink")
        super().unlink(path)


async def boot(
    path: Path, files: lj.LaneFiles | None = None, new: uuid.UUID = LANE, **limits: Any
) -> tuple[lj.LaneJournal, lj.LaneScan]:
    lane = lj.LaneJournal(files or lj.LaneFiles(path), KEYS, **limits)
    return lane, await lane.open(lambda: new)


def on_disk(path: Path) -> lj.LaneScan:
    def read(name: str) -> bytes:
        return (path / name).read_bytes()

    marker = read("confirmed") if (path / "confirmed").exists() else None
    return lj.scan(KEYS, marker=marker, names=os.listdir(path), read=read)


def outline(result: lj.LaneScan) -> list[object]:
    return [
        u.frame.seq if isinstance(u, lj.Handover) else (u.reason, u.from_seq, u.to_seq)
        for u in result.units
    ]


def segments(path: Path) -> list[int]:
    return sorted(int(name[4:24]) for name in os.listdir(path) if name.endswith(".lane"))


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


async def parked(disk: Disk) -> None:
    assert await asyncio.to_thread(disk.parked.wait, WAIT_S), "the fsync never ran"


async def stays_pending(task: asyncio.Task[Any]) -> bool:
    for _ in range(50):
        await asyncio.sleep(0)
    return not task.done()


def test_lane_actions_hold_the_adr_rows() -> None:
    """Decision 3. S2a2 registers the two `audit.lane_*` rows in `AUDIT_ACTIONS`."""
    every, success = frozenset({"success", "failure", "denied"}), frozenset({"success"})
    reserved = ("logout", "session_revoked", "refresh_reuse_detected")
    rows = {f"auth.{name}": ("shared", every) for name in LOGINS.split()}
    rows |= {f"auth.{name}": ("reserved", every) for name in reserved}
    rows |= {"auth.session_refreshed": ("shared", frozenset({"denied"}))}
    rows |= dict.fromkeys(("audit.lane_started", "audit.lane_resumed"), ("reserved", success))

    assert dict(LANE_ACTIONS) == rows
    assert set(LANE_ACTIONS) - AUDIT_ACTIONS == {"audit.lane_started", "audit.lane_resumed"}


@pytest.mark.parametrize(
    "record",
    [
        rec(action="auth.session_refreshed"),
        rec(action="auth.session_created"),
        rec(action="audit.lane_resumed", outcome="denied"),
        rec(outcome="partial"),
        {"outcome": "success"},
        {"action": ["auth.logout"], "outcome": "success"},
        {"action": "auth.logout", "outcome": ["success"]},
    ],
    ids="refresh_mint mint_intent unlisted_outcome unknown_outcome none list list_outcome".split(),
)
async def test_lane_refuses_an_unregistered_action_or_outcome(tmp_path: Path, record: Rec) -> None:
    """U42 and AC-LANE-05: admission by action and outcome; nothing is written."""
    lane, _ = await boot(tmp_path)
    await lane.append(STARTED)
    with pytest.raises(lj.LaneNotAdmitted):
        await lane.append(record)
    await lane.close()

    assert outline(on_disk(tmp_path)) == [1]


async def test_lane_creation_writes_the_marker_then_frame_1_privately(tmp_path: Path) -> None:
    path = tmp_path / "lane"
    lane, result = await boot(path)
    assert result.units == () and lane.lane == LANE and lane.fresh
    with pytest.raises(lj.LaneNotAdmitted):
        await lane.append(rec(1))  # frame 1 is audit.lane_started
    assert os.listdir(path) == [] and await lane.append(STARTED) == 1
    assert await lane.append(rec(2, action="auth.session_refreshed", outcome="denied")) == 2
    await lane.close()
    frames = [u.frame for u in on_disk(path).units if isinstance(u, lj.Handover)]

    start = lj.LaneMarker(LANE, (1, 0), 1, lj.ZERO_MAC, True)
    assert lj.decode_marker(KEYS, (path / "confirmed").read_bytes()) == start
    assert [(f.seq, f.cls) for f in frames] == [(1, "reserved"), (2, "shared")]
    assert sorted(os.listdir(path)) == ["confirmed", lj.segment_name(1)] and mode(path) == 0o700
    assert {mode(path / name) for name in os.listdir(path)} == {0o600}


async def test_lane_every_boot_opens_a_segment_within_the_segment_cap(tmp_path: Path) -> None:
    """Row 16 and R2: three boots, three segments of one frame; the fourth boot's append is
    refused `full` and writes nothing: a boot loop stops there."""
    for record in (STARTED, rec(1), rec(2)):
        lane, _ = await boot(tmp_path, max_segments=3)
        await lane.append(record)
        await lane.close()
    lane, _ = await boot(tmp_path, max_segments=3)
    with pytest.raises(lj.LaneRefused) as full:
        await lane.append(rec(3))
    await lane.close()

    assert full.value.reason == "full" and segments(tmp_path) == [1, 2, 3]


async def test_lane_torn_append_is_sealed_and_its_seq_goes_to_a_new_segment(
    tmp_path: Path,
) -> None:
    """Crash table, "during an append": frame 3 was not durable yet."""
    lane, _ = await boot(tmp_path)
    for record in (STARTED, rec(1), rec(2)):
        await lane.append(record)
    await lane.close()
    os.truncate(tmp_path / lj.segment_name(1), F1 + F2 + 40)
    lane, result = await boot(tmp_path)
    assert outline(result) == [1, 2, ("torn_tail", 3, None)] and await lane.append(rec(3)) == 3
    await lane.close()

    assert outline(on_disk(tmp_path)) == [1, 2, ("torn_tail", 3, 2), 3]
    assert segments(tmp_path) == [1, 3]


async def test_lane_a_taken_segment_name_stops_the_lane(tmp_path: Path) -> None:
    """R1: damage that takes the next segment's name (AC-LANE-09's `len` edit on a newest segment
    of one frame) stops the lane, which writes nothing and never skips a `seq` on its own."""
    lane, _ = await boot(tmp_path, segment_max_bytes=1)  # one frame per segment
    for record in (STARTED, rec(1)):
        await lane.append(record)
    await lane.close()
    second = tmp_path / lj.segment_name(2)
    second.write_bytes(b"9" + second.read_bytes())  # its `len` gains a digit
    lane, result = await boot(tmp_path)
    for _ in range(2):
        with pytest.raises(lj.LaneRefused) as stopped:
            await lane.append(rec(2))
    await lane.close()

    assert outline(result) == [1, ("torn_tail", 2, None)] and stopped.value.reason == "stopped"
    assert sorted(os.listdir(tmp_path)) == ["confirmed", *map(lj.segment_name, (1, 2))]


async def scenario(files: lj.LaneFiles) -> None:
    """Creation, an append and a rotation: 8 fsyncs."""
    lane = lj.LaneJournal(files, KEYS, segment_max_bytes=SEG)
    await lane.open(lambda: LANE)
    try:
        for record in (STARTED, rec(1), rec(2)):
            await lane.append(record)
    finally:
        await lane.close()


@pytest.mark.parametrize(
    ("nth", "handed", "lane"),
    [
        (1, [], OTHER),
        (2, [], OTHER),
        (3, [], LANE),
        (4, [], LANE),
        (5, [1], LANE),
        (6, [1, 2], LANE),
        (7, [1, 2], LANE),
        (8, [1, 2, 3], LANE),
    ],
    ids=(
        "lane_dir marker_tmp marker_dir frame1_new frame1_dir append rotation_new rotation_dir"
    ).split(),
)
async def test_lane_fault_at_each_fsync_point_leaves_the_crash_tables_state(
    tmp_path: Path, nth: int, handed: list[int], lane: uuid.UUID
) -> None:
    """A failed fsync stops the lane where it is, and the reboot finds §15.6's crash table: the
    strays removed, a lane mid-creation completed (a missing marker gets a new id, an existing one
    keeps it), a frame whose fsync failed handed over all the same."""
    path = tmp_path / "lane"
    with pytest.raises((lj.LaneRefused, OSError)):
        await scenario(Disk(path, {"fsync": nth}))
    journal, result = await boot(path, new=OTHER)
    after = handed[-1] + 1 if handed else 1
    assert [u.frame.seq for u in result.units if isinstance(u, lj.Handover)] == handed
    assert journal.lane == lane and journal.refusal is None
    assert not [name for name in os.listdir(path) if name.endswith((".new", ".tmp"))]
    assert await journal.append(STARTED if after == 1 else rec(9)) == after
    await journal.close()


@pytest.mark.parametrize(
    ("fail", "reason", "after"),
    [
        ({"write": 2}, "io_error", [1, 2]),  # frame 1's `.new`: removed, nothing published
        ({"write": 3}, "io_error", [1, 2]),  # frame 2: cut back to frame 1's end
        ({"write": 3, "truncate": 1}, "stopped", [1, ("torn_tail", 2, None)]),
        ({"write": 2, "unlink": 1}, "stopped", []),
    ],
)
async def test_lane_failed_write_refuses_io_error_or_stops_the_lane(
    tmp_path: Path, fail: dict[str, int], reason: str, after: list[object]
) -> None:
    """Failures while running: after `io_error` the next append takes the same `seq`."""
    records = [STARTED, rec(1)]
    lane, _ = await boot(tmp_path, Disk(tmp_path, fail))
    with pytest.raises(lj.LaneRefused) as refused:
        for record in records:
            await lane.append(record)
    with contextlib.suppress(lj.LaneRefused):
        for record in records[int(not lane.fresh) :]:
            await lane.append(record)
    await lane.close()

    assert refused.value.reason == reason and outline(on_disk(tmp_path)) == after


async def test_lane_new_segment_that_cannot_be_created_is_refused_io_error(tmp_path: Path) -> None:
    lane, _ = await boot(tmp_path)
    (tmp_path / f"{lj.segment_name(1)}.new").mkdir()  # something squats on the name
    with pytest.raises(lj.LaneRefused) as refused:
        await lane.append(STARTED)
    await lane.close()

    assert refused.value.reason == "io_error" and segments(tmp_path) == []


@pytest.mark.parametrize("cancel", ["caller", "op_task"])
async def test_lane_cancelled_during_an_fsync_keeps_the_lock_until_it_returns(
    tmp_path: Path, cancel: str
) -> None:
    """#2250: a cancelled caller returns at once, and teardown's cancel of the op task is
    deferred; either way the op keeps the lane lock until its fsync returns and finishes its
    bookkeeping. A caller cancelled while still queued for the lock writes nothing."""
    disk = Disk(tmp_path)
    lane, _ = await boot(tmp_path, disk)
    await lane.append(STARTED)
    disk.park = True
    first = asyncio.create_task(lane.append(rec(1)))
    await parked(disk)
    (first if cancel == "caller" else next(iter(lane._ops))).cancel()
    second, third = (asyncio.create_task(lane.append(rec(n))) for n in (2, 3))
    assert await stays_pending(second)
    third.cancel()
    assert (tmp_path / lj.segment_name(1)).stat().st_size == F1 + F2  # frame 3 waits
    disk.release.set()
    assert await asyncio.wait_for(second, WAIT_S) == 3
    for task in (first, third):
        with pytest.raises(asyncio.CancelledError):
            await task
    await lane.close()

    assert outline(on_disk(tmp_path)) == [1, 2, 3]


async def test_lane_close_waits_for_an_abandoned_boot_and_logs_its_failure(tmp_path: Path) -> None:
    """#2250: an abandoned op runs on; `close()` waits for it, and its failure is logged."""
    disk = Disk(tmp_path / "lane", {"fsync": 1})  # the boot's first fsync, held, then failing
    disk.park = True
    lane = lj.LaneJournal(disk, KEYS)
    opening = asyncio.create_task(lane.open())
    await parked(disk)
    opening.cancel()
    closing = asyncio.create_task(lane.close())
    assert await stays_pending(closing)
    with capture_logs() as logs:
        disk.release.set()
        await asyncio.wait_for(closing, WAIT_S)
    with pytest.raises(asyncio.CancelledError):
        await opening

    assert [e["event"] for e in logs] == ["audit lane op failed after its caller left"]


@pytest.mark.parametrize("layout", ["marker_kid", "frame_kid", "no_lane"])
async def test_lane_a_held_boot_opens_no_segment_and_refuses_appends(
    tmp_path: Path, layout: str
) -> None:
    """Hold: rows 1 and 12, and row 3 when no authentic frame sets the lane (reading 3)."""
    start = lj.LaneMarker(LANE, (1, 0), 1, lj.ZERO_MAC, True)
    held = lj.encode_frame(OTHER_KEYS, lane=LANE, seq=1, prev=lj.ZERO_MAC, cls="shared", rec={})
    files = {
        "marker_kid": {"confirmed": lj.encode_marker(OTHER_KEYS, start)},
        "frame_kid": {"confirmed": lj.encode_marker(KEYS, start), lj.segment_name(1): held},
        "no_lane": {lj.segment_name(1): b"junk\n"},
    }[layout]
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    lane, _ = await boot(tmp_path)
    with pytest.raises(lj.LaneRefused) as refused:
        await lane.append(STARTED)
    await lane.close()

    assert refused.value.reason == "held" == lane.refusal
    assert sorted(os.listdir(tmp_path)) == sorted(files)


async def test_lane_boot_refuses_a_file_longer_than_the_lane_writes(tmp_path: Path) -> None:
    longest = lj.SEGMENT_MAX_BYTES + lj.MAX_FRAME_BYTES  # no file the lane writes is longer
    (tmp_path / lj.segment_name(1)).write_bytes(b"x" * (longest + 1))
    with pytest.raises(lj.LaneError):
        await boot(tmp_path)


async def test_lane_appends_log_and_raise_no_record_or_key(tmp_path: Path) -> None:
    """U41: one `audit.lane.appended` line per accepted frame, with `seq`, class, action and a
    `mac` prefix only; a refusal carries no record and no key."""
    private = "do-not-print-this-record"
    with capture_logs() as logs:
        lane, _ = await boot(tmp_path)
        await lane.append(STARTED)
        with pytest.raises(lj.LaneRefused) as large:
            await lane.append(rec(1, pad=lj.MAX_FRAME_BYTES) | {"s": private})
        with pytest.raises(lj.LaneNotAdmitted) as alien:
            await lane.append({"action": private, "outcome": "success"})
        await lane.close()
    shown = " ".join(f"{e} {e!r}" for e in (large.value, alien.value)) + repr(lane) + repr(logs)
    appended = [e for e in logs if e["event"] == "audit.lane.appended"]

    assert [(e["seq"], e["cls"], e["action"], len(e["mac"]), len(e)) for e in appended] == [
        (1, "reserved", "audit.lane_started", 16, 6)
    ]
    assert private not in shown and KEY.hex() not in shown
