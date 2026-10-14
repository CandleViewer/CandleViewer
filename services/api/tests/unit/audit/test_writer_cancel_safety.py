"""#2250: `AuditWriter` is cancellation-safe.

Cancelling a caller (an `asyncio.timeout` around `emit()`, or `stop()` cancelling
the flusher) must never release `_wal_lock` while a WAL worker thread is still
running. `AuditWal` has no lock of its own: a second append would truncate the
in-flight frame as a "torn tail" and leave `AuditWal._end` past EOF, which
disables torn-tail repair and can cost an acknowledged record (C-2.9, C-12.8).

Each test parks a real WAL call in its worker thread (a slow `fsync`, or a
compaction stopped before its file swap) on a `threading.Event`; nothing sleeps
on the wall clock.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from structlog.testing import capture_logs

from candleviewer.audit import wal as wal_module
from candleviewer.audit.writer import AuditUnavailable, AuditWriter

#: Upper bound on any wait for a worker thread: a hang fails instead of blocking CI.
_WAIT_S = 5.0


def _writer(repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock) -> AuditWriter:
    return AuditWriter(repo, str(tmp_path / "audit.wal"), clock=clock, sleep=repo.retry_sleep)


async def _thread_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, _WAIT_S), "worker-thread event never fired"


async def _yield_until(cond: Callable[[], bool], rounds: int = 50) -> bool:
    """Yield to the loop (no wall-clock sleep) until `cond()` or `rounds` run out."""
    for _ in range(rounds):
        if cond():
            return True
        await asyncio.sleep(0)
    return cond()


class _ObservedLock(asyncio.Lock):
    """`asyncio.Lock` that counts acquisitions which had to queue."""

    def __init__(self) -> None:
        super().__init__()
        self.queued = 0

    async def acquire(self) -> Literal[True]:
        if self.locked():
            self.queued += 1
        return await super().acquire()


class _SlowDisk:
    """Once armed, parks the next WAL `fsync` until `release`: the frame's bytes are
    written but `AuditWal._end` has not advanced. Flags each `append` as it returns."""

    def __init__(self, append: Callable[[dict[str, Any]], int]) -> None:
        self.stalled = threading.Event()
        self.release = threading.Event()
        self.returned = [threading.Event(), threading.Event()]
        self.fail_after_release = False
        self._armed = False
        self._calls = 0
        self._append = append

    def arm(self) -> None:
        self._armed = True

    def fsync(self, fd: int) -> None:
        if self._armed:
            self._armed = False
            self.stalled.set()
            if not self.release.wait(_WAIT_S) or self.fail_after_release:
                raise OSError("disk gone")
        os.fsync(fd)

    def append(self, record: dict[str, Any]) -> int:
        index = self._calls
        self._calls += 1
        try:
            return self._append(record)
        finally:
            if index < len(self.returned):
                self.returned[index].set()


class _OsProxy:
    """Stands in for `os` inside `candleviewer.audit.wal` only."""

    def __init__(self, disk: _SlowDisk) -> None:
        self._disk = disk

    def fsync(self, fd: int) -> None:
        self._disk.fsync(fd)

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)


@pytest.fixture
def slow_disk(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[AuditWriter], _SlowDisk]]:
    made: list[_SlowDisk] = []

    def install(writer: AuditWriter) -> _SlowDisk:
        disk = _SlowDisk(writer._wal.append)
        monkeypatch.setattr(wal_module, "os", _OsProxy(disk))
        monkeypatch.setattr(writer._wal, "append", disk.append)
        made.append(disk)
        return disk

    yield install
    for disk in made:
        disk.release.set()  # never leave a worker thread parked after a failed assertion


SlowDisk = Callable[[AuditWriter], _SlowDisk]


async def test_writer_emit_cancelled_mid_append_holds_wal_lock_until_append_returns(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, slow_disk: SlowDisk
) -> None:
    w = _writer(repo, tmp_path, clock)
    await w.start()
    disk = slow_disk(w)
    disk.arm()
    emit = asyncio.create_task(w.emit("auth.login", actor_label="a"))
    await _thread_event(disk.stalled)
    emit.cancel()  # e.g. an `asyncio.timeout` around the caller's emit()
    with pytest.raises(asyncio.CancelledError):
        await emit
    assert w._wal_lock.locked(), "cancel released _wal_lock while the WAL append still runs"
    assert not disk.returned[0].is_set()
    disk.release.set()
    async with asyncio.timeout(_WAIT_S), w._wal_lock:
        assert disk.returned[0].is_set(), "_wal_lock was free before the append returned"
    await w.stop(1)


async def test_writer_cancelled_append_survives_next_emit_and_end_matches_file(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, slow_disk: SlowDisk
) -> None:
    """The issue's reproduction: the next emitter queues behind the in-flight append
    and never truncates it as a torn tail; afterwards `_end` is the file size."""
    repo.down = True  # records stay in the WAL (no commit, no compaction) while inspected
    w = _writer(repo, tmp_path, clock)
    lock = _ObservedLock()
    w._wal_lock = lock
    await w.start()
    disk = slow_disk(w)
    disk.arm()
    first = asyncio.create_task(w.emit("auth.login", actor_label="first"))
    await _thread_event(disk.stalled)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    before = lock.queued  # the flusher's batch read may already have made someone queue
    second = asyncio.create_task(w.emit("auth.login", actor_label="second"))
    if not await _yield_until(lambda: lock.queued > before):
        # The writer let the second append run beside the stalled one: let it
        # finish first, exactly as in the issue's reproduction.
        await _thread_event(disk.returned[1])
    disk.release.set()
    await asyncio.wait_for(second, _WAIT_S)
    await _thread_event(disk.returned[0])
    wal = w._wal
    assert [r["actor_label"] for _, r in wal.replay()] == ["first", "second"]
    assert wal.torn_tail_truncations == 0
    assert wal._end == (tmp_path / "audit.wal").stat().st_size
    repo.down = False
    await w.flush(_WAIT_S)
    await w.stop(1)
    assert [r["actor_label"] for r in repo.rows] == ["first", "second"]


async def test_writer_stop_drains_in_flight_append_before_cancelling_flusher(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, slow_disk: SlowDisk
) -> None:
    w = _writer(repo, tmp_path, clock)
    await w.start()
    disk = slow_disk(w)
    disk.arm()
    emit = asyncio.create_task(w.emit("auth.login", actor_label="in-flight"))
    await _thread_event(disk.stalled)
    flusher = w._task
    assert flusher is not None
    stopping = asyncio.create_task(w.stop(_WAIT_S))
    await _yield_until(stopping.done)
    assert not stopping.done() and not flusher.done(), "stop() cancelled the flusher mid-append"
    disk.release.set()
    await asyncio.wait_for(stopping, _WAIT_S)
    await emit  # accepted: returned normally, then flushed within the grace period
    assert [r["actor_label"] for r in repo.rows] == ["in-flight"]
    assert w._wal._end == (tmp_path / "audit.wal").stat().st_size


async def test_writer_flusher_cancelled_mid_compaction_keeps_lock_until_it_returns(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _writer(repo, tmp_path, clock)
    stalled, release = threading.Event(), threading.Event()
    mark_committed = w._wal.mark_committed

    def parked_mark_committed(offset: int) -> None:
        if offset == 0:  # inside compact(): remainder copied to .tmp, file not yet swapped
            stalled.set()
            release.wait(_WAIT_S)
        mark_committed(offset)

    monkeypatch.setattr(w._wal, "mark_committed", parked_mark_committed)
    await w.start()
    try:
        await w.emit("auth.login", actor_label="committed")
        await _thread_event(stalled)
        flusher = w._task
        assert flusher is not None
        flusher.cancel()
        with pytest.raises(asyncio.CancelledError):
            await flusher
        assert w._wal_lock.locked(), "cancelling the flusher released _wal_lock mid-compaction"
        late = asyncio.create_task(w.emit("auth.login", actor_label="late"))
        assert not await _yield_until(late.done), "an append ran beside the compaction"
        release.set()
        await asyncio.wait_for(late, _WAIT_S)
    finally:
        release.set()
    assert [r["actor_label"] for _, r in w._wal.replay()] == ["late"]
    assert w._wal._end == (tmp_path / "audit.wal").stat().st_size
    await w.stop(1)


async def test_writer_emit_cancelled_while_queued_for_lock_appends_nothing(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, slow_disk: SlowDisk
) -> None:
    """A caller cancelled before its op took `_wal_lock` holds nothing and started no
    thread: the op is cancelled with it, so no late append and no task is left behind."""
    w = _writer(repo, tmp_path, clock)
    lock = _ObservedLock()
    w._wal_lock = lock
    await w.start()
    disk = slow_disk(w)
    disk.arm()
    first = asyncio.create_task(w.emit("auth.login", actor_label="first"))
    await _thread_event(disk.stalled)
    before = lock.queued
    queued = asyncio.create_task(w.emit("auth.login", actor_label="queued"))
    assert await _yield_until(lambda: lock.queued > before)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    disk.release.set()
    await asyncio.wait_for(first, _WAIT_S)
    await w.stop(_WAIT_S)
    assert [r["actor_label"] for r in repo.rows] == ["first"]
    assert not w._wal_ops


@pytest.mark.parametrize("cancelled", ["caller", "op task"])
async def test_writer_cancelled_emit_whose_append_fails_still_alarms_and_counts(
    cancelled: str,
    repo: FakeAuditRepository,
    tmp_path: Path,
    clock: FakeClock,
    slow_disk: SlowDisk,
) -> None:
    """The op outlives its cancelled caller, so a WAL failure is still surfaced:
    `AuditUnavailable` bookkeeping and the fail-closed alarm run inside the op. Round 3:
    likewise when the op task itself is cancelled; the WAL error then wins over the
    deferred cancel, so the waiting `emit()` reports `AuditUnavailable`."""
    alarms: list[str] = []

    async def alarm(reason: str) -> None:
        alarms.append(reason)

    w = AuditWriter(
        repo, str(tmp_path / "audit.wal"), clock=clock, sleep=repo.retry_sleep, on_alarm=alarm
    )
    await w.start()
    disk = slow_disk(w)
    disk.arm()
    disk.fail_after_release = True
    emit = asyncio.create_task(w.emit("auth.login", actor_label="doomed"))
    await _thread_event(disk.stalled)
    expected: type[BaseException] = asyncio.CancelledError
    if cancelled == "caller":
        emit.cancel()
    else:
        _wal_op(w, "audit-wal-append").cancel()  # as asyncio.Runner teardown would
        expected = AuditUnavailable
    disk.release.set()
    with pytest.raises(expected):
        await emit
    await w.stop(_WAIT_S)
    assert alarms == ["audit WAL unavailable: OSError"] and w.refused_total == 1
    assert repo.rows == [] and not w._wal_lock.locked()


async def test_writer_flusher_op_failing_after_cancel_is_logged(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _writer(repo, tmp_path, clock)
    stalled, release = threading.Event(), threading.Event()
    mark_committed = w._wal.mark_committed

    def failing_mark_committed(offset: int) -> None:
        if offset == 0:  # inside compact()
            stalled.set()
            release.wait(_WAIT_S)
            raise OSError("disk gone")
        mark_committed(offset)

    monkeypatch.setattr(w._wal, "mark_committed", failing_mark_committed)
    await w.start()
    with capture_logs() as logs:
        try:
            await w.emit("auth.login", actor_label="x")
            await _thread_event(stalled)
            flusher = w._task
            assert flusher is not None
            flusher.cancel()
            with pytest.raises(asyncio.CancelledError):
                await flusher
        finally:
            release.set()
        await w.stop(_WAIT_S)
    failed = [e for e in logs if e["event"] == "audit WAL op failed after its caller was cancelled"]
    assert [(e["op"], e["error"], e["log_level"]) for e in failed] == [
        ("audit-wal-commit", "OSError", "critical")
    ]
    assert not w._wal_lock.locked() and not w._wal_ops


def _wal_op(w: AuditWriter, name: str) -> asyncio.Task[Any]:
    ops = [t for t in w._wal_ops if t.get_name() == name]
    assert len(ops) == 1, f"expected one in-flight {name} op, got {len(ops)}"
    return ops[0]


async def test_writer_op_task_cancelled_mid_append_keeps_lock_and_end_matches_file(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, slow_disk: SlowDisk
) -> None:
    """#2250 review (Medium): event-loop teardown cancels the WAL *op task itself*,
    not only its caller. That must not release `_wal_lock` while the append's
    worker thread still runs, or the next append truncates the in-flight frame."""
    repo.down = True  # keep records in the WAL for inspection
    w = _writer(repo, tmp_path, clock)
    await w.start()
    disk = slow_disk(w)
    disk.arm()
    emit = asyncio.create_task(w.emit("auth.login", actor_label="first"))
    await _thread_event(disk.stalled)
    _wal_op(w, "audit-wal-append").cancel()  # as asyncio.Runner teardown would
    await asyncio.sleep(0)
    assert w._wal_lock.locked(), "cancelling the op task released _wal_lock mid-append"
    second = asyncio.create_task(w.emit("auth.login", actor_label="second"))
    assert not await _yield_until(second.done), "an append ran beside the stalled one"
    disk.release.set()
    await asyncio.wait_for(second, _WAIT_S)
    with pytest.raises(asyncio.CancelledError):
        await emit
    assert w.buffer_depth == 2, "the cancelled op skipped its bookkeeping"
    wal = w._wal
    assert [r["actor_label"] for _, r in wal.replay()] == ["first", "second"]
    assert wal.torn_tail_truncations == 0
    assert wal._end == (tmp_path / "audit.wal").stat().st_size
    repo.down = False
    await w.flush(_WAIT_S)
    assert [r["actor_label"] for r in repo.rows] == ["first", "second"]
    assert w.buffer_depth == 0
    await w.stop(_WAIT_S)


async def test_writer_op_task_cancelled_mid_compaction_keeps_later_ack_durable(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling the commit op task during compaction must not let a later,
    acknowledged emit land in the old file that the compaction then swaps away."""
    w = _writer(repo, tmp_path, clock)
    stalled, release = threading.Event(), threading.Event()
    mark_committed = w._wal.mark_committed

    def parked_mark_committed(offset: int) -> None:
        if offset == 0:  # inside compact(): remainder copied to .tmp, file not yet swapped
            stalled.set()
            release.wait(_WAIT_S)
        mark_committed(offset)

    monkeypatch.setattr(w._wal, "mark_committed", parked_mark_committed)
    await w.start()
    try:
        await w.emit("auth.login", actor_label="committed")
        await _thread_event(stalled)
        _wal_op(w, "audit-wal-commit").cancel()  # as asyncio.Runner teardown would
        await asyncio.sleep(0)
        assert w._wal_lock.locked(), "cancelling the commit op released _wal_lock mid-compaction"
        late = asyncio.create_task(w.emit("auth.login", actor_label="late"))
        assert not await _yield_until(late.done), "an append ran beside the compaction"
        release.set()
        await asyncio.wait_for(late, _WAIT_S)  # acknowledged
    finally:
        release.set()
    assert [r["actor_label"] for _, r in w._wal.replay()] == ["late"], "acknowledged record lost"
    assert w._wal._end == (tmp_path / "audit.wal").stat().st_size
    await w.stop(_WAIT_S)


async def test_writer_op_task_cancelled_mid_append_still_wakes_the_flusher(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, slow_disk: SlowDisk
) -> None:
    """#2250 round 3: the deferred cancel must not skip the op's bookkeeping. With no
    later emit, only this op's `_idle.clear()` + `_wake.set()` get the record flushed;
    before, `flush()` returned at once with nothing in the DB until a restart."""
    w = _writer(repo, tmp_path, clock)
    await w.start()
    await w.flush(_WAIT_S)  # the start-up replay found nothing: idle
    disk = slow_disk(w)
    disk.arm()
    emit = asyncio.create_task(w.emit("auth.login", actor_label="only"))
    await _thread_event(disk.stalled)
    _wal_op(w, "audit-wal-append").cancel()  # as asyncio.Runner teardown would
    disk.release.set()
    with pytest.raises(asyncio.CancelledError):
        await emit  # ends with its op, after the op's bookkeeping
    await w.flush(_WAIT_S)
    assert [r["actor_label"] for r in repo.rows] == ["only"] and w.buffer_depth == 0
    await w.stop(_WAIT_S)


async def test_writer_op_task_cancelled_mid_cursor_write_finishes_bookkeeping(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2250 round 3: a commit op cancelled during its cursor write still clears
    `_inflight` and settles `_pending` before it ends. A stale `_inflight` refused the
    emergency compaction, so a full WAL failed every emit with `AuditUnavailable`."""
    w = _writer(repo, tmp_path, clock)
    stalled, release = threading.Event(), threading.Event()
    mark_committed = w._wal.mark_committed

    def parked_mark_committed(offset: int) -> None:
        if offset != 0:  # the batch's cursor write, not compact()'s reset to 0
            stalled.set()
            release.wait(_WAIT_S)
        mark_committed(offset)

    monkeypatch.setattr(w._wal, "mark_committed", parked_mark_committed)
    await w.start()
    try:
        await w.emit("auth.login", actor_label="committed")
        await _thread_event(stalled)
        commit = _wal_op(w, "audit-wal-commit")
        commit.cancel()  # as asyncio.Runner teardown would
        release.set()
        await asyncio.wait({commit}, timeout=_WAIT_S)
    finally:
        release.set()
    assert commit.cancelled()
    assert w._inflight is False and w.buffer_depth == 0
    # The cursor is durable; the optional compaction was skipped for the cancel.
    assert w._wal.committed_offset() == (tmp_path / "audit.wal").stat().st_size
    await w.stop(_WAIT_S)


async def test_writer_op_task_cancelled_mid_read_leaves_no_stale_inflight(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2250 round 3: a batch read whose op task is cancelled ends that flusher run, so
    nothing commits the batch: `_inflight` must not stay set behind it (it would refuse
    the emergency compaction). The record is still flushed after a restart."""
    w = _writer(repo, tmp_path, clock)
    stalled, release = threading.Event(), threading.Event()
    read_pending = w._wal.read_pending

    def parked_read_pending(max_records: int) -> list[tuple[int, dict[str, Any]]]:
        batch = read_pending(max_records)
        if batch:  # the read that found the record, not the empty start-up one
            stalled.set()
            release.wait(_WAIT_S)
        return batch

    monkeypatch.setattr(w._wal, "read_pending", parked_read_pending)
    await w.start()
    try:
        await w.emit("auth.login", actor_label="x")
        await _thread_event(stalled)
        read = _wal_op(w, "audit-wal-read")
        read.cancel()  # as asyncio.Runner teardown would
        release.set()
        await asyncio.wait({read}, timeout=_WAIT_S)
    finally:
        release.set()
    assert read.cancelled() and w._inflight is False
    await w.stop(_WAIT_S)
    await w.start()  # the next run reads the same batch again
    await w.flush(_WAIT_S)
    await w.stop(_WAIT_S)
    assert [r["actor_label"] for r in repo.rows] == ["x"]


async def _audit_own_shutdown(w: AuditWriter, disk: _SlowDisk, parked: asyncio.Event) -> None:
    """Parks until cancelled, then audits its own shutdown (as a session handler would),
    while `asyncio.run`'s teardown is still cancelling every other task."""
    try:
        parked.set()
        await asyncio.Event().wait()
    finally:
        lock_dropped = await _yield_until(lambda: not w._wal_lock.locked())
        cleanup = asyncio.create_task(w.emit("auth.logout", actor_label="cleanup"))
        if lock_dropped:  # the regression: this append now runs beside the parked one
            await _thread_event(disk.returned[1])
        disk.release.set()
        await cleanup


def test_writer_asyncio_run_teardown_mid_append_truncates_nothing(
    tmp_path: Path, slow_disk: SlowDisk
) -> None:
    """#2250 round 3: `asyncio.run` teardown cancels every Task at once. Were the WAL
    thread awaited through a Task (`spawn(run_in_thread(...))`, `asyncio.to_thread`),
    teardown would cancel that Task as well, drop `_wal_lock` while the append's thread
    is parked, and a shutdown audit would truncate the in-flight frame. The thread
    future must stay the plain executor Future (`thread_future`)."""
    path = tmp_path / "audit.wal"
    writers: list[AuditWriter] = []
    tasks: list[asyncio.Task[None]] = []

    async def main() -> None:
        repo = FakeAuditRepository()
        w = AuditWriter(repo, str(path), clock=FakeClock(), sleep=repo.retry_sleep)
        writers.append(w)
        await w.start()
        disk = slow_disk(w)
        disk.arm()
        tasks.append(asyncio.create_task(w.emit("auth.login", actor_label="first")))
        await _thread_event(disk.stalled)
        parked = asyncio.Event()
        tasks.append(asyncio.create_task(_audit_own_shutdown(w, disk, parked)))
        await parked.wait()
        # Returning leaves the parked append, the flusher and the handler to teardown.

    with capture_logs() as logs:
        asyncio.run(main())
    assert any(e["event"].startswith("audit WAL op cancelled while its worker") for e in logs)
    wal, size = writers[0]._wal, path.stat().st_size
    assert wal.torn_tail_truncations == 0, "teardown let an append truncate the in-flight frame"
    assert wal._end == size
    reopened = wal_module.AuditWal(path)
    assert reopened.torn_tail_truncations == 0 and reopened._end == size
    assert [r["actor_label"] for _, r in reopened.replay()] == ["first", "cleanup"]
