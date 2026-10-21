"""`AuditWal` edge cases and writer failure paths not hit by the
behavioural tests: blank lines, compaction no-op, compaction reclaiming
space on a full WAL, and the flusher-death log."""

from __future__ import annotations

import asyncio
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs
from wal_double import record_wal_io

from candleviewer.audit.wal import AuditWal, AuditWalCorrupt, AuditWalFull, encode_frame
from candleviewer.audit.writer import AuditWriter, _log_task_failure


def test_wal_replay_and_commit_cursor(tmp_path: Path) -> None:
    wal = AuditWal(tmp_path / "w.wal")
    wal.append({"a": 1})
    end = wal.append({"a": 2})
    assert [r for _, r in wal.replay()] == [{"a": 1}, {"a": 2}]
    assert wal.read_pending(1) == [(len(encode_frame({"a": 1})), {"a": 1})]
    wal.mark_committed(end)
    assert list(wal.replay()) == []


def test_wal_compact_noop_when_nothing_committed(tmp_path: Path) -> None:
    wal = AuditWal(tmp_path / "w.wal")
    wal.append({"a": 1})
    wal.compact()
    assert [r for _, r in wal.replay()] == [{"a": 1}]


def test_wal_full_raises(tmp_path: Path) -> None:
    wal = AuditWal(tmp_path / "w.wal", max_bytes=10)
    with pytest.raises(AuditWalFull):
        wal.append({"payload": "x" * 20})


async def test_writer_compacts_committed_prefix_when_wal_full(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = AuditWriter(repo, str(tmp_path / "a.wal"), clock=clock, max_wal_bytes=2000)
    w._running = True  # drive the WAL by hand: no flusher task
    await w.emit("auth.login", actor_label="0", reason="r" * 400)
    first_end = w._wal.read_pending(1)[0][0]
    assert 2 * first_end <= 2000 < 3 * first_end, first_end
    w._wal.mark_committed(first_end)  # pretend it reached Postgres
    for i in range(1, 3):
        await w.emit("auth.login", actor_label=str(i), reason="r" * 400)
    assert [r["actor_label"] for _, r in w._wal.replay()] == ["1", "2"]
    assert w.refused_total == 0


async def test_log_task_failure_reports_crash() -> None:
    async def boom() -> None:
        raise ValueError("x")

    task = asyncio.create_task(boom())
    with pytest.raises(ValueError):
        await task
    with capture_logs() as logs:
        _log_task_failure(task)
    assert any(e["event"] == "audit writer task died" for e in logs)


@pytest.mark.parametrize("cut", [1, 3, 12, -1])
def test_wal_torn_tail_truncated_before_next_append(tmp_path: Path, cut: int) -> None:
    """PR #1561 N1: a crash mid-write leaves half a frame; the next append
    must not glue onto it and replay yields both acknowledged records."""
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"a": 1})
    frame = encode_frame({"a": "torn"})
    with open(path, "ab") as fh:
        fh.write(frame[:cut])
    reopened = AuditWal(path)
    assert reopened.torn_tail_truncations == 1
    reopened.append({"a": 2})
    assert [r for _, r in reopened.replay()] == [{"a": 1}, {"a": 2}]


def test_wal_torn_tail_in_process_append_and_replay_skip(tmp_path: Path) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"a": 1})
    with open(path, "ab") as fh:
        fh.write(encode_frame({"a": "torn"})[:-4])
    with capture_logs() as logs:
        assert [r for _, r in wal.replay()] == [{"a": 1}]
    assert any("torn tail" in e["event"] for e in logs)
    wal.append({"a": 2})
    assert wal.torn_tail_truncations == 1
    assert [r for _, r in wal.replay()] == [{"a": 1}, {"a": 2}]


@pytest.mark.parametrize(
    "mangle",
    [
        lambda f: f.replace(b'"a":2', b'"a":9'),  # checksum mismatch
        lambda f: b"x" + f[1:],  # bad header
        lambda f: f[:-1] + b"X",  # bad trailer
        lambda f: b"5\n[1,2]\n" + b"%08x\n" % zlib.crc32(b"[1,2]"),  # not a dict
        lambda f: b"3\n{x}\n" + b"%08x\n" % zlib.crc32(b"{x}"),  # bad json
    ],
)
def test_wal_corrupt_middle_frame_raises(tmp_path: Path, mangle: Callable[[bytes], bytes]) -> None:
    path = tmp_path / "w.wal"
    good = [encode_frame({"a": i}) for i in (1, 2, 3)]
    bad = mangle(good[1])
    path.write_bytes(good[0] + bad + good[2])
    with pytest.raises(AuditWalCorrupt) as exc:
        AuditWal(path)
    assert exc.value.offset == len(good[0])


def test_wal_corrupt_middle_detected_on_replay(tmp_path: Path) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"a": 1})
    wal.append({"a": 2})
    data = bytearray(path.read_bytes())
    data[3] ^= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(AuditWalCorrupt):
        list(wal.replay())


async def test_writer_flusher_death_fails_closed_then_recovers(
    tmp_path: Path, clock: FakeClock
) -> None:
    """PR #1561 N2: a repository that keeps raising kills the flusher ->
    alarm, emit() raises AuditUnavailable; next start() replays the WAL."""
    from candleviewer.audit.writer import AuditUnavailable

    class PoisonRepo(FakeAuditRepository):
        broken = True

        async def insert(self, record: dict[str, Any]) -> None:
            if self.broken:
                raise RuntimeError("poison")
            await super().insert(record)

    repo = PoisonRepo()
    alarms: list[str] = []

    async def alarm(msg: str) -> None:
        alarms.append(msg)

    async def no_sleep(_d: float) -> None:
        await asyncio.sleep(0)

    w = AuditWriter(
        repo,
        str(tmp_path / "a.wal"),
        clock=clock,
        sleep=no_sleep,
        on_alarm=alarm,
        max_insert_attempts=3,
    )
    await w.start()
    await w.emit("auth.login", actor_label="kept")
    assert w._task is not None
    with pytest.raises(RuntimeError):
        await w._task
    assert len(alarms) == 1 and "flusher died" in alarms[0]
    assert isinstance(w.failure, RuntimeError) and w.write_errors_total == 3
    with pytest.raises(AuditUnavailable):
        await w.emit("auth.login", actor_label="refused")
    assert w.refused_total == 1
    assert w.append_failure is None  # #2510: flusher death stays on `failure`, unlatched
    await w.stop(0.01)
    repo.broken = False  # repository healed
    await w.start()
    await w.flush(5)
    await w.stop(1)
    assert [r["actor_label"] for r in repo.rows] == ["kept"]
    assert w.failure is None


# --- E50-T63: `read_window`, one bounded read per call ------------------------------------------


def _filled(path: Path, records: list[dict[str, Any]]) -> AuditWal:
    """A WAL whose frames were all acknowledged (written at once: no fsync per frame)."""
    path.write_bytes(b"".join(encode_frame(r) for r in records))
    return AuditWal(path)


def _padded(n: int, width: int = 60) -> list[dict[str, Any]]:
    return [{"i": i, "pad": "x" * width} for i in range(n)]


def test_read_window_returns_whole_frames_within_the_byte_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frame the window cuts is left for the next call; nothing past the bound is read."""
    records = _padded(10)
    wal = _filled(tmp_path / "w.wal", records)
    frame = len(encode_frame(records[0]))
    bound = 3 * frame + frame // 2
    recorded = record_wal_io(monkeypatch)
    window = wal.read_window(100, bound)
    assert window == wal.read_pending(3) and [r for _, r in window] == records[:3]
    assert recorded.read_sizes("w.wal") == [bound]
    wal.mark_committed(window[-1][0])
    assert [r for _, r in wal.read_window(100, bound)] == records[3:6]


def test_read_window_returns_a_first_frame_larger_than_the_window_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = {"pad": "y" * 5000}
    wal = _filled(tmp_path / "w.wal", [big, {"a": 1}])
    recorded = record_wal_io(monkeypatch)
    assert [r for _, r in wal.read_window(10, 100)] == [big]
    frame = len(encode_frame(big))
    assert max(recorded.read_sizes("w.wal")) == frame  # the window, its header, then the frame


def test_read_window_returns_at_most_max_records(tmp_path: Path) -> None:
    records = _padded(8, width=1)
    wal = _filled(tmp_path / "w.wal", records)
    assert [r for _, r in wal.read_window(2, 1 << 20)] == records[:2]


def test_read_window_reads_nothing_when_nothing_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wal = AuditWal(tmp_path / "w.wal")
    end = wal.append({"a": 1})
    wal.mark_committed(end)
    recorded = record_wal_io(monkeypatch)
    assert wal.read_window(10, 1 << 16) == []
    assert recorded.reads == []


def test_read_window_never_reads_past_the_acknowledged_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A torn tail (an append that never returned) is never read or returned."""
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    end = wal.append({"a": 1})
    with open(path, "ab") as fh:
        fh.write(encode_frame({"a": "torn"})[:-3])
    recorded = record_wal_io(monkeypatch)
    assert wal.read_window(10, 1 << 16) == [(end, {"a": 1})]
    assert sum(recorded.read_sizes("w.wal")) == end


@pytest.mark.parametrize("victim", [0, 1, 2])
def test_read_window_raises_on_a_corrupt_frame_inside_the_acknowledged_end(
    tmp_path: Path, victim: int
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    ends = [0] + [wal.append({"a": i}) for i in range(3)]
    data = bytearray(path.read_bytes())
    data[ends[victim] + 3] ^= 0x01  # inside that frame's JSON body: its CRC no longer matches
    path.write_bytes(bytes(data))
    with pytest.raises(AuditWalCorrupt) as exc:
        while window := wal.read_window(1, 1 << 16):
            wal.mark_committed(window[-1][0])
    assert exc.value.offset == ends[victim]


def test_read_window_raises_when_the_file_is_shorter_than_its_acknowledged_end(
    tmp_path: Path,
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    first = wal.append({"a": 1})
    wal.append({"a": 2})
    with open(path, "r+b") as fh:
        fh.truncate(first + 4)  # acknowledged bytes lost under the WAL
    assert wal.read_window(1, 1 << 16) == [(first, {"a": 1})]
    wal.mark_committed(first)
    with pytest.raises(AuditWalCorrupt) as exc:
        wal.read_window(1, 1 << 16)
    assert exc.value.offset == first


@settings(max_examples=60, deadline=None)
@given(
    sizes=st.lists(st.integers(0, 300), min_size=0, max_size=25),
    max_bytes=st.integers(1, 2048),
    max_records=st.integers(1, 30),
)
def test_read_window_is_a_bounded_prefix_of_read_pending(
    tmp_path_factory: pytest.TempPathFactory, sizes: list[int], max_bytes: int, max_records: int
) -> None:
    """Agreement with `read_pending`: the window is its first frames, at least one when anything
    is pending, at most `max_records`, and within `max_bytes` unless it is one larger frame."""
    records = [{"i": i, "pad": "z" * n} for i, n in enumerate(sizes)]
    wal = _filled(tmp_path_factory.mktemp("w") / "w.wal", records)
    window = wal.read_window(max_records, max_bytes)
    assert window == wal.read_pending(len(window))
    assert bool(window) == bool(records) and len(window) <= max_records
    span = window[-1][0] if window else 0
    assert span <= max_bytes or len(window) == 1
    if window and len(window) < min(max_records, len(records)):  # the next frame did not fit
        assert window[-1][0] + len(encode_frame(records[len(window)])) > max_bytes
