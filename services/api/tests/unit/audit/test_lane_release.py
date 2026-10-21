"""ADR-0037 S2c (#3009): the offline release command and what the next boot makes of its note
(`docs/plan/24-internal-schemas.md` §15.6 Release, scan rows 12, 13 and 16). The sink is a real
`AuditWriter` over the in-memory repository, the key a test vector read through S2b-1's loader
from a file in `tmp_path`. Every async test runs on a `VirtualTimeLoop` (`audit_waits`, #3709,
#3816): the drain's polls and backoffs, the writer's budgets and `until()`'s bound are fake
seconds, which pass only when nothing else can happen, so no wait depends on how fast the runner
is."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import runpy
import sys
import uuid
from collections.abc import Callable
from io import FileIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from audit_waits import TaskEnded, VirtualTimeLoop, virtual
from structlog.testing import capture_logs

from candleviewer import audit_lane_wiring
from candleviewer.admin.lane_release import ReleaseExit, main
from candleviewer.audit import lane_journal as lj
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.lane import AuditLane, LaneFacade, lock_lane
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.writer import AuditUnavailable, AuditWriter
from candleviewer.observability import logging as observability_logging
from candleviewer.settings import Settings

#: WAIT_S is fake seconds: past every wait a test here makes, which takes a few fake milliseconds.
KEY, LANE, WAIT_S = bytes(range(32)), uuid.UUID(int=7), 600.0
KEYS, OTHER = lj.LaneKeys(KEY), lj.LaneKeys(bytes(range(32, 64)))  # OTHER: configured nowhere
ROTATED = lj.LaneKeys(bytes(range(32, 64)), previous=KEY)  # a boot under OTHER's key, since lost
#: A fake millisecond: the drain parks between polls and retries instead of spinning.
FAST: dict[str, Any] = {"retry_s": (0.001, 0.001), "poll_s": 0.001, "new_lane": lambda: LANE}
WORDS = ("op" * 32, "INC-" + "7" * 60, "a planted frame no key verifies " + "x" * 248)  # the caps
WORKERS = ("audit-writer", "audit-lane-drain")  # the flusher's and the drain's task names


class Gate(AuditWriter):
    """The sink: refuses (`AuditUnavailable`) every record whose action is in `shut`."""

    shut: frozenset[str] = frozenset()

    async def ingest(self, record: AuditEmission | dict[str, Any]) -> int:
        if (record["action"] if isinstance(record, dict) else record.action) in self.shut:
            raise AuditUnavailable("the sink refuses")
        return await super().ingest(record)


@pytest.fixture
def audit(tmp_path: Path) -> Path:
    (path := tmp_path.resolve() / "audit").mkdir()  # the directory of the WAL, and of `lane/`
    return path


@pytest.fixture
def settings(tmp_path: Path, audit: Path) -> Settings:
    key = tmp_path.resolve() / "lane.key"  # outside the audit directory, as the loader requires
    key.write_text(KEY.hex())
    key.chmod(0o400)
    wal = str(audit / "audit.wal")
    return Settings(storage_backend="real", audit_wal_path=wal, CV_AUDIT_LANE_KEY_FILE=str(key))


async def sink(audit: Path, repo: FakeAuditRepository) -> Gate:
    writer = Gate(repo, str(audit / "audit.wal"), clock=FakeClock(), sleep=repo.retry_sleep)
    await writer.start()
    return writer


async def boot(
    audit: Path,
    writer: AuditWriter,
    keys: lj.LaneKeys = KEYS,
    files: lj.LaneFiles | None = None,
    **caps: Any,
) -> tuple[AuditLane, lj.LaneScan]:
    journal = lj.LaneJournal(files or lj.LaneFiles(audit / "lane"), keys, **caps)
    lane = AuditLane(journal, writer, **FAST)
    return lane, await lane.start()


def workers() -> list[asyncio.Task[Any]]:
    """The running flushers and drains, whose death `until()` watches."""
    return [task for task in asyncio.all_tasks() if task.get_name() in WORKERS]


def failed(task: asyncio.Task[Any]) -> bool:
    return task.done() and not task.cancelled() and task.exception() is not None


async def until(check: Callable[[], bool]) -> None:
    """Wait until `check()` holds, looking again at each point where nothing is ready. A flusher
    or drain that dies meanwhile fails it at once, unless its death is what `check()` waits for.
    A stall fails it after `WAIT_S` fake seconds, naming the flushers and drains that had died by
    then, before the wait too, with the last one's error as the cause (as `test_lane_drain`'s)."""
    loop = asyncio.get_running_loop()
    assert isinstance(loop, VirtualTimeLoop), "an async test here runs on a VirtualTimeLoop"
    try:
        async with asyncio.timeout(WAIT_S):
            while not check():
                watched = workers()
                await loop.idle(*watched)
                died = [task for task in watched if failed(task)]
                if died and not check():
                    cause = died[0].exception()
                    raise TaskEnded(f"{died[0].get_name()} ended before the condition") from cause
    except TimeoutError:
        dead = [task for task in loop.made if task.get_name() in WORKERS and failed(task)]
        stalled = f"stalled: still false after {WAIT_S:g} fake seconds"
        if dead:
            names = ", ".join(task.get_name() for task in dead)
            raise TaskEnded(f"{stalled}; had died: {names}") from dead[-1].exception()
        raise AssertionError(stalled) from None


def logout(writer: AuditWriter) -> AuditEmission:
    return writer.build("auth.logout", actor_label="owner")


def mac(frame: bytes) -> str:
    return frame[-65:-1].decode()


async def held_lane(audit: Path, writer: Gate, layout: str) -> tuple[lj.Pos, lj.Pos, bytes]:
    """Frames 1-3 drained, then 4 and 5 under an unknown key and, unless `to_the_end`, an authentic
    6; or (`own_segment`, the review's reproduction) a lost key's boot, 4 and 5 all of seg-4."""
    lane, _ = await boot(audit, writer)
    await lane.append(logout(writer))
    if not writer.shut:
        await until(lambda: lane.confirmed == lane.journal.end)
    await lane.close()
    path, (_, prev), rec = audit / "lane", lane.journal.head, logout(writer).model_dump(mode="json")
    if layout == "own_segment":
        shut, writer.shut = writer.shut, frozenset(AUDIT_ACTIONS)
        lane, _ = await boot(audit, writer, ROTATED)  # its first append opens seg-4
        await lane.append(logout(writer))
        await lane.close()
        writer.shut, held = shut, (path / lj.segment_name(4)).read_bytes()
        return (4, 0), (4, len(held)), held
    u4 = lj.encode_frame(OTHER, lane=LANE, seq=4, prev=prev, cls="reserved", rec={})
    u5 = lj.encode_frame(OTHER, lane=LANE, seq=5, prev=mac(u4), cls="reserved", rec={})
    a6 = lj.encode_frame(KEYS, lane=LANE, seq=6, prev=mac(u5), cls="reserved", rec=rec)
    seg, at = path / lj.segment_name(1), len((path / lj.segment_name(1)).read_bytes())
    if layout == "next_segment":
        seg.write_bytes(seg.read_bytes() + u4)
        (path / lj.segment_name(5)).write_bytes(u5 + a6)
        return (1, at), (5, len(u5)), u4 + u5
    seg.write_bytes(seg.read_bytes() + u4 + u5 + (b"" if layout == "to_the_end" else a6))
    return (1, at), (1, at + len(u4 + u5)), u4 + u5


def release(settings: Settings, hold: lj.Pos, words: tuple[str, ...] = WORDS) -> int:
    argv = ["--hold", f"{hold[0]}:{hold[1]}"]
    for flag, word in zip(("--operator", "--ticket", "--operator-reason"), words, strict=True):
        argv += [flag, word]
    return main(argv, settings=settings)


def after(row: dict[str, Any]) -> Any:
    return json.loads(row["after_state"])


LAYOUTS = ["next_frame", "next_segment", "to_the_end", "own_segment"]
GAP, LOGOUT = ("audit.lane_anomaly", "seq_gap"), ("auth.logout", None)
GAP_ROW = ("from_seq", "to_seq", "prev_unverified")
#: Rows between `released` and `audit.lane_resumed`; the gap row's range and `prev_unverified`.
FOLLOWS: dict[str, tuple[list[tuple[str, str | None]], list[object] | None]] = {
    "next_frame": ([GAP, LOGOUT], [4, 5, True]), "next_segment": ([GAP, LOGOUT], [4, 5, True]),
    "to_the_end": ([], None), "own_segment": ([GAP], [4, 4, False]),
}  # fmt: skip


async def released(audit: Path, settings: Settings, layout: str) -> SimpleNamespace:
    """The boot that holds, the command, the boot that applies the note; what each left."""
    repo = FakeAuditRepository()
    writer = await sink(audit, repo)
    hold, end, held = await held_lane(audit, writer, layout)
    with capture_logs() as logs:
        lane, result = await boot(audit, writer)
        refusal = lane.journal.refusal
        await lane.close()
        status = release(settings, hold)
        name = f"{lj.segment_name(hold[0])}.{hold[1]}"
        copy = (audit / "lane" / "quarantine" / name).read_bytes()
        body = json.loads((audit / "lane" / "released").read_bytes().split(b"\n")[0])
        lane, _ = await boot(audit, writer)
        await until(lambda: lane.confirmed == lane.journal.end)
        stopped = lane.journal.refusal
        await lane.close()
    await writer.stop(1)
    return SimpleNamespace(**locals())


@pytest.mark.parametrize("layout", LAYOUTS)
@virtual
async def test_release_copies_the_held_bytes_then_writes_the_note(
    audit: Path, settings: Settings, layout: str
) -> None:
    """An unknown-`kid` frame holds the lane; the command copies the held bytes (to the next
    authentic frame, in any segment, or to the end), then writes the note (words at their caps)."""
    r = await released(audit, settings, layout)
    ids = {"v": 1, "lane": str(LANE), "hold": list(r.hold), "end": list(r.end), "from_seq": 4}

    assert r.refusal == "held" and r.result.hold == r.hold and r.status == 0  # RELEASED
    assert r.copy == r.held and r.body == ids | dict(zip(lj.NOTE_WORDS, WORDS, strict=True))


@pytest.mark.parametrize("layout", LAYOUTS)
@virtual
async def test_release_next_boot_records_one_released_row_and_the_held_seq_values(
    audit: Path, settings: Settings, layout: str
) -> None:
    """One `released` row with the words, then the held `seq` values as a `seq_gap` row before the
    next frame: for a whole segment at the end, before the boot's own, so the lane runs on."""
    r = await released(audit, settings, layout)
    rows, (follows, gap) = r.repo.rows[3:], FOLLOWS[layout]
    expected = {
        "from_seq": 4, "to_seq": 3, "bytes": len(r.held), "quarantined": r.name,
        "digest": hashlib.sha256(r.held).hexdigest(), "prev_unverified": False,
        "marker_behind": False, "marker_ahead": False,
    } | dict(zip(lj.NOTE_WORDS, WORDS, strict=True))  # fmt: skip

    assert [(row["action"], row["reason"]) for row in rows] == [
        ("audit.lane_anomaly", "released"), *follows, ("audit.lane_resumed", None),
    ]  # fmt: skip
    assert after(rows[0]) == expected and r.stopped is None
    assert gap is None or [after(rows[1])[k] for k in GAP_ROW] == gap


@virtual
async def test_release_next_boot_counts_the_released_row_under_its_reason(
    audit: Path, settings: Settings
) -> None:
    """S4a1-M2 (D1): `released` is a label value of the lane's anomaly count, so the drain counts
    the row a release leaves, and the `seq_gap` row after it, rather than dropping them."""
    r = await released(audit, settings, "next_frame")

    assert r.lane.anomalies == dict.fromkeys(lj.ANOMALY_REASONS, 0) | {"released": 1, "seq_gap": 1}


async def restart(audit: Path, writer: Gate) -> lj.LaneReason | None:
    """A boot, its drain to the end unless the sink is shut, a stop: the refusal before the stop."""
    lane, _ = await boot(audit, writer)
    if not writer.shut:
        await until(lambda: lane.confirmed == lane.journal.end)
    refusal = lane.journal.refusal
    await lane.close()
    return refusal


@pytest.mark.parametrize(
    ("damage", "reason"), [("torn", "seq_gap"), ("mac", "frame_rejected"), ("emptied", "seq_gap")]
)
@virtual
async def test_boot_records_damage_that_took_the_newest_segments_name_and_moves_past_it(
    audit: Path, damage: str, reason: str
) -> None:
    """#3009 ruling (a), scan row 16 at boot: a boot with the sink down leaves its own frame 3
    waiting, all of seg-3, then torn, tampered or emptied. The next boot records it as one
    critical row for `seq` 3 (damage at the start of a published segment is never a crash's),
    keeps its bytes in `quarantine/` if it has any, and writes its own frame 4 to seg-4, the free
    name, so the lane drains; it used to need seg-3's taken name, stop and write nothing at every
    boot. A second boot adds nothing."""
    repo, path = FakeAuditRepository(), audit / "lane"
    writer = await sink(audit, repo)
    await restart(audit, writer)  # frames 1 and 2, drained
    writer.shut = frozenset(AUDIT_ACTIONS)
    await restart(audit, writer)  # frame 3 waits, alone in seg-3
    writer.shut, seg = frozenset(), path / lj.segment_name(3)
    head, body = seg.read_bytes().split(b"\n", 1)
    if damage == "torn":  # its `len` one more than its body
        seg.write_bytes(damaged := b"%d\n%s" % (int(head) + 1, body))
    elif damage == "mac":  # one letter of its record: the frame parses and its MAC fails
        seg.write_bytes(damaged := head + b"\n" + body.replace(b"resumed", b"resumeD", 1))
    else:  # cut to nothing: the name stays taken, with no byte to keep
        seg.write_bytes(damaged := b"")
    refusals = [await restart(audit, writer) for _ in range(2)]
    await writer.stop(1)
    anomalies = [after(r) | r for r in repo.rows if r["action"] == "audit.lane_anomaly"]
    copies = {copy.name: copy.read_bytes() for copy in path.glob("quarantine/*")}
    resumed = [after(r) for r in repo.rows if r["action"] == "audit.lane_resumed"]

    assert refusals == [None, None]
    assert [(a["reason"], a["severity"], a["from_seq"], a["to_seq"]) for a in anomalies] == [
        (reason, "critical", 3, 3)
    ]
    assert copies == ({anomalies[0]["quarantined"]: damaged} if damaged else {})
    assert (anomalies[0]["quarantined"] is None) == (not damaged)
    assert [(r["head_seq"], r["anchored"]) for r in resumed] == [(1, True), (3, False), (4, True)]


class Unlinks(lj.LaneFiles):
    """Keeps the bytes of each segment it unlinks (compaction's), by name."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.unlinked: dict[str, bytes] = {}

    def unlink(self, path: Path) -> None:
        if path.name.startswith("seg-") and path.name.endswith(".lane"):
            self.unlinked[path.name] = path.read_bytes()
        super().unlink(path)


def segment_bytes(path: Path) -> dict[str, bytes]:
    names = sorted(name for name in os.listdir(path) if name.endswith(".lane"))
    return {name: (path / name).read_bytes() for name in names}


def authentic(segments: dict[str, bytes]) -> set[str]:
    """The `record_id` of every authentic frame in `segments` (name to bytes), each read alone."""
    ids = set[str]()
    for name in segments:
        found = lj.scan(KEYS, marker=None, names=[name], read=segments.__getitem__)
        ids |= {str(u.frame.rec["record_id"]) for u in found.units if isinstance(u, lj.Handover)}
    return ids


JUNK, Q9 = b"junk\n", f"{lj.segment_name(9)}.0"  # planted as seg-9, and its quarantine copy
#: Per layout of the running wedge: the journal's caps; then, once the lane stopped, the
#: segments, the head `seq` and the records the façade sent to the sink; the anomaly rows'
#: (reason, from_seq, to_seq, bytes, quarantined).
WEDGES: dict[str, tuple[dict[str, Any], list[int], int, int, list[tuple[object, ...]]]] = {
    "sealed": ({}, [1, 9], 4, 2, [("segment_corrupt", 5, None, 5, Q9), ("seq_gap", 5, 9, 0, None)]),
    "rotating": ({"segment_max_bytes": 1}, [3, 9], 3, 3, [("segment_corrupt", 4, 9, 5, Q9)]),
}


@pytest.mark.parametrize("layout", WEDGES)
@virtual
async def test_segment_planted_past_the_next_seq_while_running_stops_the_lane_and_loses_nothing(
    audit: Path, layout: str
) -> None:
    """The running wedge (#3009): a segment planted while cv-api runs, named past the next
    `seq`. Once a running scan has sealed it, the drain's position is in it, and a segment the
    lane then published under its own, lower name would sort before that position: no running
    scan reads it, the next boot passes the planted name as a gap, and compaction unlinks the
    acknowledged frames in it. So the running scan that meets such a name stops the lane
    (`sealed`: frame 4 still lands in seg-1, ahead of the drain), and publish() refuses a name
    at or below an existing segment's (`rotating`: a segment per frame, so the first append
    after the plant); the façade falls back. Nothing lies behind the drain, compaction unlinks
    no frame before its hand-over, the restart accounts for the planted name and comes up, and
    every record reaches the sink."""
    caps, segments, head, fell, anomalies = WEDGES[layout]
    repo, path = FakeAuditRepository(), audit / "lane"
    writer, files = await sink(audit, repo), Unlinks(path)
    lane, _ = await boot(audit, writer, files=files, **caps)  # frames 1 and 2
    facade = LaneFacade(writer, lane)

    async def emit(n: int) -> None:
        await facade.emit("auth.logout", actor_label="owner", object_id=str(n))
        await until(lambda: lane.confirmed == lane.journal.end)  # the drain took what it reads

    await emit(3)
    (path / lj.segment_name(9)).write_bytes(JUNK)  # planted while the lane runs; 4 is next
    await emit(4)
    first = lane.journal.refusal
    for n in (5, 6):
        await emit(n)
    refusal, (seq, _) = lane.journal.refusal, lane.journal.head
    fell_back, disk = facade.refused["reserved", "stopped"], segment_bytes(path)
    running = {r["record_id"] for r in repo.rows}
    await lane.close()
    lane, _ = await boot(audit, writer, files=files, **caps)
    await until(lambda: lane.confirmed == lane.journal.end)
    restarted = lane.journal.refusal
    await lane.close()
    await writer.stop(1)
    logouts = [r["object_id"] for r in repo.rows if r["action"] == "auth.logout"]
    rows = [after(r) | r for r in repo.rows if r["action"] == "audit.lane_anomaly"]
    fields = ("reason", "from_seq", "to_seq", "bytes", "quarantined")

    assert logouts == ["3", "4", "5", "6"]  # every record reached the sink, once
    assert authentic(disk) <= running  # nothing lay behind the drain
    assert authentic(files.unlinked) <= {r["record_id"] for r in repo.rows}  # nor was unlinked
    assert (first, refusal, seq, fell_back) == ("stopped", "stopped", head, fell)
    assert [int(name[4:24]) for name in disk] == segments  # none published since the plant
    assert [tuple(row[k] for k in fields) for row in rows] == anomalies
    assert restarted is None


@virtual
async def test_release_logs_the_hold_and_the_outcome_and_never_the_words(
    audit: Path, settings: Settings
) -> None:
    """The hold line ignores no note; the command's line has outcome, positions and bytes."""
    r = await released(audit, settings, "next_frame")
    held_line = next(e for e in r.logs if e["event"] == "audit lane held at boot")
    release_line = next(e for e in r.logs if e["event"] == "audit.lane.release")
    outcome = {"outcome": "released", "end": r.end, "bytes": len(r.held)}

    assert {"hold": r.hold, "note_ignored": False}.items() <= held_line.items()
    assert outcome.items() <= release_line.items()
    assert not [e for e in r.logs if any(word in repr(e) for word in WORDS)]


@pytest.mark.parametrize("case", ["deleted", "removed_by_hand", "marker_fsync_fails"])
@virtual
async def test_release_note_is_deleted_once_the_marker_passes_its_end(
    audit: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Not at boot, nor while the marker is short of the note's `end`, but with the durable marker
    write that reaches it; a failed deletion, like a failed marker write, stops the lane."""
    repo, note = FakeAuditRepository(), audit / "lane" / "released"
    writer = await sink(audit, repo)
    writer.shut = frozenset(AUDIT_ACTIONS)  # boot 1 confirms nothing: boot 3 hands frames 1-3 again
    hold, end, _ = await held_lane(audit, writer, "to_the_end")
    assert release(settings, hold) == ReleaseExit.RELEASED
    writer.shut = frozenset({"audit.lane_anomaly"})
    lane, _ = await boot(audit, writer)
    await until(lambda: lane.confirmed == hold)
    kept = note.exists()
    if case == "removed_by_hand":
        note.unlink()
    elif case == "marker_fsync_fails":
        monkeypatch.setattr(lj.LaneFiles, "sync_dir", lambda *_: os.fsync(1 << 20))  # EBADF
    writer.shut = frozenset({"audit.lane_resumed"})  # the row passes, this boot's frame waits
    await until(lambda: lane.confirmed == end or lane.journal.refusal is not None)
    gone, refusal = not note.exists(), lane.journal.refusal
    await lane.close()
    await writer.stop(1)

    assert kept and gone == (case != "marker_fsync_fails")
    assert refusal == (None if case == "deleted" else "stopped")
    assert [r["reason"] for r in repo.rows if r["action"] == "audit.lane_anomaly"] == ["released"]


@virtual
async def test_release_during_a_rotation_verifies_with_both_keys_and_notes_under_the_new_one(
    audit: Path, settings: Settings
) -> None:
    """Mid-rotation the command verifies with both keys, so it holds only where neither does,
    and signs the note with the current key, the only one a note verifies under."""
    previous, new_key = settings.audit_lane_mac_file, bytes(range(64, 96))
    (new := Path(previous).with_name("new.key")).write_text(new_key.hex())
    new.chmod(0o400)
    keys = {"audit_lane_mac_file": str(new), "audit_lane_previous_mac_file": previous}
    repo = FakeAuditRepository()
    writer = await sink(audit, repo)
    hold, _, _ = await held_lane(audit, writer, "to_the_end")  # under KEY, now the previous key
    status = release(settings.model_copy(update=keys), hold)
    rotated = lj.LaneKeys(new_key, previous=KEY)
    lane = AuditLane(lj.LaneJournal(lj.LaneFiles(audit / "lane"), rotated), writer, **FAST)
    result = await lane.start()
    await until(lambda: lane.confirmed == lane.journal.end)
    await lane.close()
    await writer.stop(1)

    assert status == ReleaseExit.RELEASED and not result.held
    assert [r["reason"] for r in repo.rows if r["action"] == "audit.lane_anomaly"] == ["released"]


@pytest.mark.parametrize("bad", ["bad_mac", "another_hold"])
@virtual
async def test_release_note_with_a_bad_mac_or_another_hold_is_ignored_and_logged(
    audit: Path, bad: str
) -> None:
    """A note failing its MAC under the current key, or naming another hold, is ignored and
    logged and kept; the hold stays (appends refused `held`, no `released` row)."""
    repo = FakeAuditRepository()
    writer = await sink(audit, repo)
    hold, end, _ = await held_lane(audit, writer, "next_frame")
    keys, at = (OTHER, hold) if bad == "bad_mac" else (KEYS, (1, 0))
    planted = lj.encode_note(keys, lane=LANE, hold=at, end=end, from_seq=4, words=WORDS)
    (audit / "lane" / "released").write_bytes(planted)
    with capture_logs() as logs:
        lane, result = await boot(audit, writer)
    with pytest.raises(lj.LaneRefused) as refused:
        await lane.append(logout(writer))
    await lane.close()
    await writer.stop(1)

    assert refused.value.reason == "held" and result.hold == hold
    assert [(e["hold"], e["note_ignored"]) for e in logs if "hold" in e] == [(hold, True)]
    assert (audit / "lane" / "released").read_bytes() == planted
    assert [r["action"] for r in repo.rows[3:]] == []


@pytest.mark.parametrize("holder", ["cv_api", "shared"])
@virtual
async def test_release_refuses_while_cv_api_runs(
    audit: Path, settings: Settings, holder: str
) -> None:
    """U42: while cv-api holds `lane.lock` (its own `lock_lane`), or anything holds it shared, the
    command refuses (exit 5) and writes nothing; once it is free, the same command releases."""
    writer = await sink(audit, FakeAuditRepository())
    hold, _, _ = await held_lane(audit, writer, "next_frame")
    await writer.stop(1)
    before = sorted(os.listdir(audit / "lane"))
    if holder == "cv_api":
        lock = lock_lane(settings.audit_wal_path)
    else:
        lock = FileIO(os.open(audit / "lane" / "lane.lock", os.O_RDONLY | os.O_CREAT, 0o600), "r")
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
    with lock:
        refused = release(settings, hold)
        names = sorted(os.listdir(audit / "lane"))

    assert refused == 5 and names == sorted({*before, "lane.lock"})  # API_RUNNING
    assert release(settings, hold) == ReleaseExit.RELEASED


def swapping(real: Callable[..., int], lane: Path, to: Path) -> Callable[..., int]:
    """`lj._open` that swaps `lane` for a link to `to` just before the helper opens `lane/`."""

    def opening(path: Path | str, flags: int, dir_fd: int | None = None) -> int:
        if path == "lane":
            lane.rename(to)
            lane.symlink_to(to)
        return real(path, flags, dir_fd)

    return opening


#: The exit status each refusal gives, by the numbers runbook auth-rbac §12 documents.
REFUSED = {
    "not_held": 6, "marker_hold": 6, "no_lane": 6, "no_name_left": 6, "hold_mismatch": 7,
    "no_real_backend": 4, "key_refused": 4, "relative_wal": 4, "dotdot_wal": 4,
    "symlinked_lane": 4, "symlinked_lock": 4, "swapped_lane": 4, "copy_fails": 4,
    "lock_error": 4,
}  # fmt: skip
#: The position the operator names, when not the planted frames': elsewhere, or where the scan
#: holds with no segment name left (`seg-` and 20 nines).
NAMED = {"hold_mismatch": (1, 0), "no_name_left": (10**20 - 1, 5)}


@pytest.mark.parametrize("case", list(REFUSED))
@virtual
async def test_release_refuses_and_writes_nothing(
    audit: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    """No note when the lane holds at no frame, at another hold, with no key or a refused one, an
    unanchored path, a symlinked `lane.lock` (nothing created through it) or a failed copy."""
    tmp_path = audit.parent
    writer = await sink(audit, FakeAuditRepository())
    hold, _, held = await held_lane(audit, writer, "to_the_end")
    await writer.stop(1)
    lane, seg = audit / "lane", audit / "lane" / lj.segment_name(1)
    if case == "not_held":  # the planted frames cut off again
        seg.write_bytes(seg.read_bytes()[: hold[1]])
    elif case == "no_name_left":  # no frame where the scan holds, at the end of the data
        seg.write_bytes(seg.read_bytes()[: hold[1]])
        (lane / lj.segment_name(NAMED[case][0])).write_bytes(b"junk\n")
    elif case == "marker_hold":  # row 1: the marker under a key nobody configured
        marker = lj.LaneMarker(LANE, hold, 4, lj.ZERO_MAC, True)
        (lane / "confirmed").write_bytes(lj.encode_marker(OTHER, marker))
    elif case == "no_lane":  # row 3: no marker, and no authentic frame before the hold
        seg.write_bytes(held)
        (lane / "confirmed").unlink()
    elif case == "no_real_backend":
        settings = settings.model_copy(update={"storage_backend": "fake"})
    elif case == "key_refused":
        (key := tmp_path / "open.key").write_text(KEY.hex())
        settings = settings.model_copy(update={"audit_lane_mac_file": str(key.resolve())})
    elif case in ("relative_wal", "dotdot_wal"):  # either would reach the lane, unchecked
        monkeypatch.chdir(tmp_path)
        wal = "audit/audit.wal" if case == "relative_wal" else str(audit / ".." / "audit" / "a.wal")
        settings = settings.model_copy(update={"audit_wal_path": wal})
    elif case == "symlinked_lane":
        lane.rename(audit / "real")
        lane.symlink_to(audit / "real")
    elif case == "symlinked_lock":
        (lane / "lane.lock").symlink_to(audit / "elsewhere")
    elif case == "swapped_lane":  # SEC-REM-03: a link once the audit directory is open
        monkeypatch.setattr(lj, "_open", swapping(lj._open, lane, audit / "real"))
    elif case == "copy_fails":
        (lane / "quarantine").write_bytes(b"")
    elif case == "lock_error":  # an `flock` error that is not another holder: exit 4, not 5
        monkeypatch.setattr(fcntl, "flock", lambda *_: os.fsync(1 << 20))  # EBADF
    before = sorted(os.listdir(lane))
    status = release(settings, NAMED.get(case, hold))
    said = {"hold_mismatch": f"holds at 1:{hold[1]}", "key_refused": "must be mode 0400"}
    said["no_name_left"] = "does not hold at a frame"

    assert status == ReleaseExit(REFUSED[case]) and {*os.listdir(lane)} - {*before} <= {"lane.lock"}
    assert not (audit / "elsewhere").exists()
    assert said.get(case, "") in capsys.readouterr().out


ARGUMENTS = {
    "blank": ("--operator", "  "), "operator_65": ("--operator", "o" * 65),
    "ticket_65": ("--ticket", "t" * 65), "reason_281": ("--operator-reason", "r" * 281),
    "newline": ("--operator", "a\nb"), "escape": ("--ticket", "INC-1\x1b[2K"),
    "bidi": ("--operator-reason", "a \u202eb"), "hold_three_parts": ("--hold", "1:2:3"),
    "hold_wide_digit": ("--hold", "\uff11:0"), "hold_21_digits": ("--hold", "1" * 21 + ":0"),
}  # fmt: skip


@pytest.mark.parametrize("case", list(ARGUMENTS))
def test_release_refuses_arguments_out_of_bounds(
    capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Words trimmed, printable, 1 to their caps (64, 64, 280); `--hold` two runs of 1 to 20 ASCII
    digits around a colon; else exit 2 before any setting or file is read, never echoing it."""
    (flag, value), words = ARGUMENTS[case], {"--hold": "1:0", "--operator": "o", "--ticket": "t"}
    words["--operator-reason"] = "r"
    argv = [x for pair in (words | {flag: value}).items() for x in pair]
    with pytest.raises(SystemExit) as exited:
        main(argv)
    err = capsys.readouterr().err

    assert exited.value.code == 2 and f"argument {flag}: must be" in err
    assert value.strip() not in err or not value.strip()


def test_release_note_files_follow_the_marker_procedure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fsync point 2: a boot removes the `released.tmp` a crash left; the note is renamed into
    place and later unlinked, each step then fsyncing the directory."""
    files, seen = lj.LaneFiles(tmp_path), list[list[str]]()
    (tmp_path / "released.tmp").write_bytes(b"half a note")
    names, _, note = files.boot()
    monkeypatch.setattr(lj.LaneFiles, "sync_dir", lambda *_: seen.append(os.listdir(tmp_path)))
    files.write_note(b"note")
    files.drop_note()

    assert (names, note) == ([], None) and seen == [["released"], []]


def test_release_runs_as_a_module_with_its_logging_configured_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python -m candleviewer.admin.lane_release` installs the redacting log chain, as `main.py`
    does, before the key loader runs; with no key there is no lane (exit 4)."""
    calls = list[str]()
    monkeypatch.setattr(observability_logging, "configure_logging", lambda **_: calls.append("log"))
    monkeypatch.setattr(audit_lane_wiring, "load_lane_keys", lambda *_: calls.append("keys"))
    argv = ["--hold", "1:0", "--operator", "o", "--ticket", "t", "--operator-reason", "r"]
    monkeypatch.setattr(sys, "argv", ["lane_release", *argv])
    monkeypatch.delitem(sys.modules, "candleviewer.admin.lane_release")
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("candleviewer.admin.lane_release", run_name="__main__")

    assert exited.value.code == ReleaseExit.LANE_UNAVAILABLE and calls == ["log", "keys"]
