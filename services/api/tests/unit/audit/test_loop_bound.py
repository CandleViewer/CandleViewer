"""D6 (#913 slice 3 L2, the order lane's own audit writer and machine-event sink): `AuditWriter`
and `MachineEventWalSink` each serve one event loop, the one they were built on (built outside
one, their first checked call's), and refuse a call from any other loop, or from a thread that
runs none, with a typed error before anything is read or written (C-2.9, fail closed), the first
refusal of each 5 s window paged (CR-S3L2-08). An exclusive writer locks `<wal>.lock` before it
opens its WAL and holds the lock to the end of its stop, its last WAL op included (CR-S3L2-05), so
no second writer ever reads or cuts that file. No timing is asserted: a call from another loop is
one made on a loop of its own in a worker thread, and each wait is a bound on the test."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository
from structlog.testing import capture_logs

from candleviewer.audit.machine_events import MachineEventWalSink, MachineEventWrongLoop
from candleviewer.audit.wal import AuditWalLocked, encode_frame, lock_wal_file
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, AuditWriterWrongLoop
from candleviewer.statechart.plugins.audit import GENESIS_HASH, MachineEventRow, row_digest

T0 = datetime(2026, 10, 25, 4, 0, tzinfo=UTC)
#: A bound on each of the tests' waits, never a time they expect.
BOUND_S = 10.0
#: When each refusal of the window tests is made, on the refusing object's clock, and whether it
#: pages: the window's first, one just inside it, the next window's first, and one at a clock
#: stepped back, which reads as expired (CR-S3L2-08).
WINDOWS = (
    (T0, True),
    (T0 + timedelta(seconds=4.999), False),
    (T0 + timedelta(seconds=5), True),
    (T0 + timedelta(seconds=4), True),
)


def _elsewhere[T](call: Callable[[], Awaitable[T]]) -> Awaitable[T]:
    """`call()` awaited on a loop of its own, in a worker thread: another event loop."""

    async def run() -> T:
        return await call()

    return asyncio.to_thread(asyncio.run, run())


def _wrong_loop_pages(logs: Sequence[Mapping[str, Any]], event: str) -> int:
    return sum(1 for e in logs if e["event"] == event and e.get("cv_page") is True)


def _built(writer: AuditWriter, name: str) -> Any:
    return writer.build("auth.logout", actor_label="system:test", object_id=name)


async def test_a_writer_refuses_every_call_from_another_loop_before_it_touches_anything(
    tmp_path: Path,
) -> None:
    repo, wal = FakeAuditRepository(), tmp_path / "audit.wal"
    writer = AuditWriter(repo, str(wal), sleep=repo.retry_sleep, clock=lambda: T0)
    await writer.start()
    await writer.emit("auth.logout", actor_label="system:test", object_id="here")
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "emit": lambda: writer.emit("auth.logout", actor_label="system:test"),
        "emit_keyed": lambda: writer.emit_keyed("sl.attached", "a-stop", actor_label="system:test"),
        "ingest": lambda: writer.ingest(_built(writer, "ingested")),
        "ingest_counted": lambda: writer.ingest_counted(_built(writer, "counted")),
        "flush": lambda: writer.flush(1),
        "start": writer.start,
        "stop": lambda: writer.stop(1),
    }
    with capture_logs() as logs:
        for name, call in calls.items():
            with pytest.raises(AuditWriterWrongLoop) as refused:
                await _elsewhere(call)
            assert isinstance(refused.value, AuditUnavailable), name  # callers refuse the action
    assert _wrong_loop_pages(logs, "audit_writer_wrong_loop") == 1  # one window: one page
    await writer.flush(5)  # its own loop still serves it: nothing else was appended or refused
    assert [row["object_id"] for row in repo.rows] == ["here"]
    assert (writer.refused_total, sum(writer.refused_by_domain.values())) == (0, 0)
    await writer.stop(1)


async def test_a_writer_built_outside_a_loop_serves_the_loop_of_its_first_checked_call(
    tmp_path: Path,
) -> None:
    repo = FakeAuditRepository()
    writer = await asyncio.to_thread(AuditWriter, repo, str(tmp_path / "audit.wal"))
    await writer.start()  # the first checked call: this loop is the writer's from now on
    with pytest.raises(AuditWriterWrongLoop):
        await _elsewhere(lambda: writer.emit("auth.logout", actor_label="system:test"))
    await writer.emit("auth.logout", actor_label="system:test")
    await writer.flush(5)
    await writer.stop(1)
    assert len(repo.rows) == 1


def _tear(path: Path) -> None:
    """Half a frame past the acknowledged end: an append another writer has in flight."""
    with open(path, "ab") as fh:
        fh.write(encode_frame({"in_flight": True})[:-5])


async def test_an_exclusive_writer_locks_its_wal_before_it_opens_it_and_until_its_stop_ends(
    tmp_path: Path,
) -> None:
    """A second exclusive writer of the file is refused before it reads it, so it never cuts the
    first's frame in flight; the first's stop drops the lock, and a writer it stopped is not
    started again without it."""
    repo, wal = FakeAuditRepository(), tmp_path / "oms_lane.audit.wal"
    first = AuditWriter(repo, str(wal), sleep=repo.retry_sleep, exclusive=True)
    assert wal.with_name(wal.name + ".lock").exists()
    _tear(wal)
    size = wal.stat().st_size
    with pytest.raises(AuditWalLocked):
        AuditWriter(repo, str(wal), exclusive=True)
    assert wal.stat().st_size == size  # not opened: its torn-tail cut never ran
    await first.start()
    await first.emit("auth.logout", actor_label="system:test")
    await first.flush(5)
    await first.stop(1)
    with pytest.raises(RuntimeError, match="exclusive"):
        await first.start()
    second = AuditWriter(repo, str(wal), sleep=repo.retry_sleep, exclusive=True)
    await second.start()
    await second.stop(1)
    assert len(repo.rows) == 1


async def test_an_exclusive_writer_whose_wal_cannot_be_opened_drops_its_lock(
    tmp_path: Path,
) -> None:
    wal = tmp_path / "oms_lane.audit.wal"
    wal.mkdir()  # no file can be read there
    with pytest.raises(IsADirectoryError):
        AuditWriter(FakeAuditRepository(), str(wal), exclusive=True)
    lock_wal_file(wal).close()  # free again: the failed build kept nothing


class Store:
    """`MachineEventStore` in memory, as the Postgres store answers it."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def insert_batch(self, frames: Sequence[Mapping[str, Any]]) -> None:
        self.rows.extend(dict(frame) for frame in frames)

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str:
        return GENESIS_HASH


def _row(i: int) -> MachineEventRow:
    base = MachineEventRow(
        machine_kind="order", entity_id=f"order-{i}", env="demo", event_type="EXEC",
        payload={"i": i}, from_states=["submitted"], to_states=["partially_filled"],
        actions_run=["record"], fault=None, occurred_at=T0.isoformat(), phase="commit",
        prev_hash=GENESIS_HASH,
    )  # fmt: skip
    return dataclasses.replace(base, row_hash=row_digest(base))


async def _seed(sink: MachineEventWalSink, key: MachineEventRow) -> None:
    await sink.seed(key)


async def _append(sink: MachineEventWalSink, row: MachineEventRow) -> None:
    sink.append(row)


async def _head(sink: MachineEventWalSink, key: MachineEventRow) -> str | None:
    return sink.head(key)


async def test_a_sink_refuses_every_call_from_another_loop_or_from_none_and_writes_nothing(
    tmp_path: Path,
) -> None:
    store = Store()
    sink = MachineEventWalSink(store, tmp_path / "machine_events.wal", clock=lambda: T0)
    await sink.start()
    sink.append(_row(0))
    calls: list[Callable[[], Awaitable[object]]] = [
        lambda: _append(sink, _row(1)),
        lambda: _head(sink, _row(0)),
        lambda: _seed(sink, _row(2)),
        sink.start,
        sink.stop,
    ]
    with capture_logs() as logs:
        for call in calls:
            with pytest.raises(MachineEventWrongLoop):
                await _elsewhere(call)
        with pytest.raises(MachineEventWrongLoop):  # a thread that runs no loop at all
            await asyncio.to_thread(sink.append, _row(3))
    assert _wrong_loop_pages(logs, "machine_events.wrong_loop") == 1  # one window: one page
    assert sink.head(_row(0)) == _row(0).row_hash and sink.head(_row(2)) is None
    sink.append(_row(4))  # its own loop still serves it, and it is still running
    await sink.stop()
    assert [row["entity_id"] for row in store.rows] == ["order-0", "order-4"]


async def test_a_writer_pages_the_first_wrong_loop_refusal_of_each_window_on_its_clock(
    tmp_path: Path,
) -> None:
    """CR-S3L2-08: a wiring defect refuses every call it makes, so the writer pages the first
    refusal of each `APPEND_FAILURE_COOLDOWN` window on its own clock, never each call; a clock
    stepped back reads as expired. Every call is refused all the same."""
    repo, now = FakeAuditRepository(), [T0]
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), clock=lambda: now[0])
    await writer.start()
    paged = list[bool]()
    for at, _ in WINDOWS:
        now[0] = at
        with capture_logs() as logs, pytest.raises(AuditWriterWrongLoop):
            await _elsewhere(lambda: writer.emit("auth.logout", actor_label="system:test"))
        paged.append(_wrong_loop_pages(logs, "audit_writer_wrong_loop") == 1)
    assert paged == [pages for _, pages in WINDOWS]
    await writer.stop(1)


async def test_a_sink_pages_the_first_wrong_loop_refusal_of_each_window_on_its_clock(
    tmp_path: Path,
) -> None:
    """CR-S3L2-08: the sink's refusals page as the writer's do, on its clock and window
    (`APPEND_FAILURE_COOLDOWN_S`), from another loop or from a thread that runs none."""
    now = [T0]
    sink = MachineEventWalSink(Store(), tmp_path / "machine_events.wal", clock=lambda: now[0])
    await sink.start()
    paged = list[bool]()
    for index, (at, _) in enumerate(WINDOWS):
        now[0] = at
        with capture_logs() as logs, pytest.raises(MachineEventWrongLoop):
            if index % 2:
                await asyncio.to_thread(sink.append, _row(index))  # a thread that runs no loop
            else:
                await _elsewhere(functools.partial(_append, sink, _row(index)))
        paged.append(_wrong_loop_pages(logs, "machine_events.wrong_loop") == 1)
    assert paged == [pages for _, pages in WINDOWS]
    await sink.stop()


async def test_an_exclusive_writer_keeps_its_lock_until_a_wal_op_its_stop_cut_off_has_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-S3L2-05: the stop cancels a flusher that is inside its cursor commit, whose WAL thread
    runs on (#2250). The writer still holds `<wal>.lock` while its stop waits for that thread, so a
    second writer of the file is refused until the stop has ended, never while the commit can
    still write; then one builds."""
    repo, wal = FakeAuditRepository(), tmp_path / "oms_lane.audit.wal"
    parked, passed, last = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def backoff(delay: float) -> None:
        parked.set()  # the flusher holds no WAL op while it waits to retry its insert
        await repo.retry_sleep(delay)

    first = AuditWriter(repo, str(wal), sleep=backoff, exclusive=True)
    await first.start()
    entered, go = threading.Event(), threading.Event()
    mark, drain = first._wal.mark_committed, first._drain_wal_ops

    def held(offset: int) -> None:
        entered.set()
        go.wait(BOUND_S)
        mark(offset)

    async def watched(grace_s: float = 5.0) -> None:
        final = first._task is None  # the stop's last drain: the flusher is cancelled by then
        if final:
            last.set()
        await drain(grace_s)
        if not final:
            passed.set()

    monkeypatch.setattr(first._wal, "mark_committed", held)  # the commit's WAL thread
    monkeypatch.setattr(first, "_drain_wal_ops", watched)
    repo.down = True
    await first.emit("auth.logout", actor_label="system:test")
    await asyncio.wait_for(parked.wait(), BOUND_S)
    stopping = asyncio.ensure_future(first.stop(0.2))
    await asyncio.wait_for(passed.wait(), BOUND_S)  # its first drain found no WAL op
    repo.down = False  # the insert lands and the commit's thread holds the WAL
    assert await asyncio.to_thread(entered.wait, BOUND_S)
    await asyncio.wait_for(last.wait(), BOUND_S)  # the flush ran out; the last drain waits
    with pytest.raises(AuditWalLocked):
        AuditWriter(repo, str(wal), exclusive=True)
    assert not stopping.done()
    go.set()
    await asyncio.wait_for(stopping, BOUND_S)
    second = AuditWriter(repo, str(wal), sleep=repo.retry_sleep, exclusive=True)
    await second.start()
    await second.flush(BOUND_S)
    await second.stop(1)
    assert len(repo.rows) == 1
