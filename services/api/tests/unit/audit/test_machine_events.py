"""`MachineEventWalSink` (E50-T63, M19): the durable, synchronous `machine_events` sink over the
audit WAL, with one bounded flusher. Fakes only: a `tmp_path` WAL, a fake events store, a fake
clock, and the virtual-time loop of `audit_waits` (every sleep, backoff and deadline runs on
fake seconds; nothing reads the wall clock)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import stat
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from audit_waits import virtual
from structlog.testing import capture_logs
from wal_double import record_wal_io

from candleviewer.audit import machine_events
from candleviewer.audit.machine_events import (
    MAX_FRAME_BYTES,
    RETRY_INITIAL_S,
    RETRY_MAX_S,
    MachineEventRejected,
    MachineEventUnavailable,
    MachineEventWalSink,
    SinkMetrics,
)
from candleviewer.audit.wal import AuditWal, AuditWalCorrupt, encode_frame
from candleviewer.statechart.plugins.audit import GENESIS_HASH, MachineEventRow, row_digest
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable

T0 = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)
KEY = ("persist_min", "00000000-0000-4000-8000-000000000001", "demo")


class FakeStore:
    """`MachineEventStore`: idempotent on `row_hash`, as the Postgres store is."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.batches: list[int] = []
        self.down = False
        self.hang = False
        self.poison: Exception | None = None
        self.heads: dict[tuple[str, str, str], str] = {}

    async def insert_batch(self, frames: Sequence[Mapping[str, Any]]) -> None:
        await asyncio.sleep(0)  # a real insert suspends
        if self.hang:
            await asyncio.Event().wait()
        if self.poison is not None:
            raise self.poison
        if self.down:
            raise StorageTierUnavailable("statechart events.insert_batch failed (sqlstate 08006)")
        self.batches.append(len(frames))
        held = {r["row_hash"] for r in self.rows}
        self.rows.extend(dict(f) for f in frames if f["row_hash"] not in held)

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str:
        await asyncio.sleep(0)
        if self.hang:
            await asyncio.Event().wait()
        if self.down:
            raise StorageTierUnavailable("statechart events.head failed (sqlstate 08006)")
        key = (machine_kind, entity_id, env)
        if key in self.heads:  # a test's own value
            return self.heads[key]
        stored = [r for r in self.rows if (r["machine_kind"], r["entity_id"], r["env"]) == key]
        return str(stored[-1]["row_hash"]) if stored else GENESIS_HASH  # as the table's head


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class Seen:
    """Records the sink's metric calls."""

    def __init__(self) -> None:
        self.flushed: list[str] = []
        self.pending: list[int] = []

    def metrics(self) -> SinkMetrics:
        return SinkMetrics(flushed=self.flushed.append, pending=self.pending.append)


def row(i: int, *, prev: str = GENESIS_HASH, key: tuple[str, str, str] = KEY, **kw: Any) -> Any:
    base = MachineEventRow(
        machine_kind=key[0], entity_id=key[1], env=key[2], event_type="PING",
        payload={"i": i}, from_states=["persist_min.idle"], to_states=["persist_min.idle"],
        actions_run=["record"], fault=None, occurred_at=(T0 + timedelta(seconds=i)).isoformat(),
        phase="commit", prev_hash=prev,
    )  # fmt: skip
    base = dataclasses.replace(base, **kw)
    return dataclasses.replace(base, row_hash=row_digest(base))


def chain(n: int, start: int = 0, prev: str = GENESIS_HASH) -> list[Any]:
    out = []
    for i in range(start, start + n):
        out.append(row(i, prev=prev))
        prev = out[-1].row_hash
    return out


def _tear(path: Path) -> None:
    """A crash mid-write: half a frame after the acknowledged end."""
    with open(path, "ab") as fh:
        fh.write(encode_frame({"torn": True})[:-5])


def frames(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [dataclasses.asdict(r) for r in rows]


def sink_for(
    tmp_path: Path, store: FakeStore, *, max_bytes: int = 64 * 1024 * 1024, **kw: Any
) -> MachineEventWalSink:
    return MachineEventWalSink(store, tmp_path / "machine_events.wal", max_bytes=max_bytes, **kw)


async def settle(cond: Callable[[], bool], steps: int = 10_000) -> None:
    """Step the virtual loop (fake time moves only when nothing is ready) until `cond` holds."""
    loop = asyncio.get_running_loop()
    for _ in range(steps):
        if cond():
            return
        await loop.idle()  # type: ignore[attr-defined]  # VirtualTimeLoop.idle
    raise AssertionError("condition not reached")


# --- append: durable before it returns, bounded, fail closed ------------------------------------


@virtual
async def test_append_writes_and_fsyncs_one_frame_before_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.17 by structure: one frame written, one `fsync`, nothing read, on the caller's thread."""
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    r = row(0)
    recorded = record_wal_io(monkeypatch)
    sink.append(r)
    frame = encode_frame(dataclasses.asdict(r))
    assert recorded.write_sizes("machine_events.wal") == [len(frame)]
    assert recorded.fsyncs == 1 and recorded.reads == []
    assert (tmp_path / "machine_events.wal").read_bytes().endswith(frame)
    await sink.stop()


@virtual
async def test_an_oversize_row_is_rejected_and_writes_nothing(tmp_path: Path) -> None:
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    wal = tmp_path / "machine_events.wal"
    with pytest.raises(MachineEventRejected, match="MAX_FRAME_BYTES"):
        sink.append(row(0, payload={"pad": "x" * MAX_FRAME_BYTES}))
    assert wal.stat().st_size == 0
    await sink.stop()


@pytest.mark.parametrize(
    "occurred_at",
    ["2026-10-21T05:00:00+02:00", "2026-10-21T03:00:00", "2026-10-21T03:00:00Z", "yesterday", ""],
    ids=["offset", "naive", "z-suffix", "garbage", "empty"],
)
@virtual
async def test_a_row_whose_occurred_at_is_not_the_utc_form_is_rejected(
    tmp_path: Path, occurred_at: str
) -> None:
    """The row digest covers the string and Postgres returns UTC: only `+00:00` round-trips."""
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    with pytest.raises(MachineEventRejected, match="occurred_at"):
        sink.append(row(0, occurred_at=occurred_at))
    assert (tmp_path / "machine_events.wal").stat().st_size == 0
    await sink.stop()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()], ids=["nan", "inf", "obj"])
@virtual
async def test_a_row_that_json_cannot_hold_is_rejected(tmp_path: Path, value: object) -> None:
    """Postgres `json` refuses NaN and the infinities: refused here, never a poison row later."""
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    with pytest.raises(MachineEventRejected):
        sink.append(row(0, payload={"x": value}))
    assert (tmp_path / "machine_events.wal").stat().st_size == 0
    await sink.stop()


@pytest.mark.parametrize(
    ("field", "value"),
    [("entity_id", ""), ("env", "dev"), ("phase", "later"), ("phase", "fault"),
     ("fault", {"kind": "x"}), ("prev_hash", "A" * 64), ("row_hash", "f" * 63)],
    ids=["entity", "env", "phase", "fault-phase-without-fault", "fault-on-commit", "prev-hex",
         "row-hex"],
)  # fmt: skip
@virtual
async def test_a_row_the_table_would_refuse_is_rejected_at_append(
    tmp_path: Path, field: str, value: object
) -> None:
    """The cheap mirrors of `machine_events`' CHECKs and `sha256_hex`: a row Postgres would refuse
    is refused here, before it can become a poison row in the WAL."""
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    bad = dataclasses.replace(row(0), **{field: value})
    if field != "row_hash":
        bad = dataclasses.replace(bad, row_hash=row_digest(bad))
    with pytest.raises(MachineEventRejected, match=field):
        sink.append(bad)
    assert (tmp_path / "machine_events.wal").stat().st_size == 0
    await sink.stop()


@virtual
async def test_a_second_sink_on_the_same_wal_is_refused_until_the_first_stops(
    tmp_path: Path,
) -> None:
    """One writer per WAL file: an exclusive lock on `<wal>.lock`, held from start to stop."""
    first, second = sink_for(tmp_path, FakeStore()), sink_for(tmp_path, FakeStore())
    await first.start()
    with pytest.raises(MachineEventUnavailable, match="another process"):
        await second.start()
    await first.stop()
    await second.start()
    second.append(row(0))
    await second.stop()


@virtual
async def test_append_before_start_or_after_stop_is_refused(tmp_path: Path) -> None:
    sink = sink_for(tmp_path, FakeStore())
    with pytest.raises(MachineEventUnavailable, match="not running"):
        sink.append(row(0))
    await sink.start()
    sink.append(row(0))
    await sink.stop()
    with pytest.raises(MachineEventUnavailable, match="not running"):
        sink.append(row(1))


@virtual
async def test_a_full_wal_raises_unavailable_and_pages_once_per_window(tmp_path: Path) -> None:
    store, clock = FakeStore(), Clock()
    store.down = True
    rows = chain(5)
    one = len(encode_frame(dataclasses.asdict(rows[0])))
    sink = sink_for(tmp_path, store, max_bytes=2 * one + one // 2, clock=clock)
    await sink.start()
    sink.append(rows[0])
    sink.append(rows[1])
    with capture_logs() as logs:
        for r in rows[2:]:
            with pytest.raises(MachineEventUnavailable, match="AuditWalFull"):
                sink.append(r)
    pages = [e for e in logs if e.get("cv_page")]
    assert len(pages) == 1 and pages[0]["log_level"] == "critical"
    assert sink.append_failure_active
    await sink.stop()


@virtual
async def test_an_unwritable_wal_raises_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()

    def broken(self: AuditWal, record: dict[str, Any]) -> int:
        raise OSError("disk gone")

    monkeypatch.setattr(AuditWal, "append", broken)
    with pytest.raises(MachineEventUnavailable, match="OSError"):
        sink.append(row(0))
    assert sink.append_failure_active
    await sink.stop()


@virtual
async def test_the_append_failure_latch_expires_after_5_s_and_the_next_append_re_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 4: #2510's latch. It never refuses an append and never waits for one."""
    clock = Clock()
    sink = sink_for(tmp_path, FakeStore(), clock=clock)
    await sink.start()
    real_append = AuditWal.append
    failing = {"on": True}

    def flaky(self: AuditWal, record: dict[str, Any]) -> int:
        if failing["on"]:
            raise OSError("disk gone")
        return real_append(self, record)

    monkeypatch.setattr(AuditWal, "append", flaky)
    with pytest.raises(MachineEventUnavailable):
        sink.append(row(0))
    assert sink.append_failure_active
    clock.now += timedelta(seconds=4.999)
    assert sink.append_failure_active
    clock.now += timedelta(seconds=0.001)
    assert not sink.append_failure_active  # 5 s, no append since
    with pytest.raises(MachineEventUnavailable):  # failure re-arms the window
        sink.append(row(1))
    clock.now += timedelta(seconds=1)
    assert sink.append_failure_active
    failing["on"] = False
    sink.append(row(2))  # success clears the failure time
    assert not sink.append_failure_active and sink.append_failed_at is None
    failing["on"] = True
    with pytest.raises(MachineEventUnavailable):
        sink.append(row(3))
    clock.now -= timedelta(seconds=1)  # a clock stepped back reads as expired
    assert not sink.append_failure_active
    await sink.stop()


# --- the flusher ---------------------------------------------------------------------------------


@virtual
async def test_the_flusher_inserts_rows_in_append_order_once_and_compacts(tmp_path: Path) -> None:
    store, seen = FakeStore(), Seen()
    sink = sink_for(tmp_path, store, metrics=seen.metrics())
    await sink.start()
    rows = chain(3)
    for r in rows:
        sink.append(r)
    await settle(lambda: len(store.rows) == 3 and sink.pending == 0)
    assert store.rows == frames(rows) and store.batches == [3]  # one burst, one batch
    assert seen.flushed == ["ok"] and seen.pending[-1] == 0
    assert (tmp_path / "machine_events.wal").stat().st_size == 0  # nothing pending: O(1)
    await sink.stop()


@virtual
async def test_an_outage_with_room_in_the_wal_loses_nothing(tmp_path: Path) -> None:
    """Scenario 2: `append` returns once fsync'd; the flusher retries with capped doubling backoff
    and, once Postgres is back, inserts every row in append order, once."""
    store, seen = FakeStore(), Seen()
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        await asyncio.sleep(delay)

    store.down = True
    sink = sink_for(tmp_path, store, sleep=sleep, metrics=seen.metrics())
    await sink.start()
    rows = chain(4)
    for r in rows:
        sink.append(r)  # returns: the frame is durable
    await settle(lambda: seen.flushed.count("error") >= 8)
    backoff = [d for d in delays if d >= RETRY_INITIAL_S]
    assert backoff[:7] == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, RETRY_MAX_S]
    assert store.rows == [] and seen.pending[-1] == 4
    store.down = False
    await settle(lambda: len(store.rows) == 4)
    assert store.rows == frames(rows)
    await sink.stop()


@virtual
async def test_rows_accepted_before_the_wal_filled_reach_the_store_once_after_recovery(
    tmp_path: Path,
) -> None:
    """Scenario 3: the append that cannot be made durable fails closed; earlier rows survive."""
    store = FakeStore()
    store.down = True
    rows = chain(6)
    one = len(encode_frame(dataclasses.asdict(rows[0])))
    sink = sink_for(tmp_path, store, max_bytes=3 * one + one // 2)
    await sink.start()
    accepted = []
    for r in rows:
        try:
            sink.append(r)
            accepted.append(r)
        except MachineEventUnavailable:
            pass
    assert len(accepted) == 3
    store.down = False
    await settle(lambda: len(store.rows) == 3)
    assert store.rows == frames(accepted)
    await sink.stop()


@virtual
async def test_start_replays_leftover_frames_idempotently(tmp_path: Path) -> None:
    """A crash between the insert and the cursor: the next start re-inserts, `row_hash` dedups."""
    rows = chain(4)
    wal = AuditWal(tmp_path / "machine_events.wal")
    for f in frames(rows):
        wal.append(f)
    store = FakeStore()
    store.rows = frames(rows[:2])  # already in Postgres, cursor never moved
    sink = sink_for(tmp_path, store)
    await sink.start()
    await settle(lambda: len(store.rows) == 4)
    assert store.rows == frames(rows)
    await sink.stop()


@virtual
async def test_a_torn_tail_is_never_flushed_and_is_cut_by_the_next_append(tmp_path: Path) -> None:
    rows = chain(3)
    path = tmp_path / "machine_events.wal"
    wal = AuditWal(path)
    for f in frames(rows[:2]):
        wal.append(f)
    _tear(path)
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    await settle(lambda: len(store.rows) == 2)
    sink.append(rows[2])
    await settle(lambda: len(store.rows) == 3)
    assert store.rows == frames(rows)
    await sink.stop()


@pytest.mark.parametrize(
    "poison",
    [StorageQueryFailed("23514"), StorageQueryFailed("22P02"), ValueError("not ISO-8601 UTC")],
    ids=["class-23", "class-22", "adapter-refusal"],
)
@virtual
async def test_a_poison_batch_kills_the_flusher_and_appends_fail_closed(
    tmp_path: Path, poison: Exception
) -> None:
    store = FakeStore()
    store.poison = poison
    sink = sink_for(tmp_path, store)
    await sink.start()
    sink.append(row(0))
    with capture_logs() as logs:
        await settle(lambda: sink.failure is not None)
    assert sink.failure is poison
    deaths = [e for e in logs if e["event"] == "machine_events.flusher_died"]
    assert deaths and deaths[0]["cv_page"] is True and deaths[0]["log_level"] == "critical"
    assert deaths[0]["error"] == type(poison).__name__
    with pytest.raises(MachineEventUnavailable, match="flusher"):
        sink.append(row(1))
    await sink.stop()
    store.poison = None  # fixed: the next start replays everything accepted
    again = sink_for(tmp_path, store)
    await again.start()
    await settle(lambda: len(store.rows) == 1)
    await again.stop()


@pytest.mark.parametrize(
    "error",
    [StorageQueryFailed("42501"), StorageQueryFailed("XX000"), StorageQueryFailed(None)],
    ids=["class-42", "class-XX", "no-sqlstate"],
)
@virtual
async def test_a_statement_error_outside_classes_22_and_23_is_retried(
    tmp_path: Path, error: Exception
) -> None:
    """Only a data exception or an integrity violation is poison; any other error backs off."""
    store, seen = FakeStore(), Seen()
    store.poison = error
    sink = sink_for(tmp_path, store, metrics=seen.metrics())
    await sink.start()
    sink.append(row(0))
    await settle(lambda: seen.flushed.count("error") >= 3)
    assert sink.failure is None
    store.poison = None
    await settle(lambda: len(store.rows) == 1)
    await sink.stop()


@virtual
async def test_a_corrupt_frame_kills_the_flusher(tmp_path: Path) -> None:
    path = tmp_path / "machine_events.wal"
    wal = AuditWal(path)
    for f in frames(chain(3)):
        wal.append(f)
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    data = bytearray(path.read_bytes())
    data[5] ^= 0x01  # inside the first frame's body
    path.write_bytes(bytes(data))
    await settle(lambda: sink.failure is not None)
    assert type(sink.failure).__name__ == "AuditWalCorrupt" and store.rows == []
    await sink.stop()


@virtual
async def test_a_hanging_insert_is_cut_by_its_deadline_and_retried(tmp_path: Path) -> None:
    """The carry's hang case: the insert deadline cuts it; the rows wait in the WAL."""
    store, seen = FakeStore(), Seen()
    store.hang = True
    sink = sink_for(tmp_path, store, metrics=seen.metrics())
    await sink.start()
    sink.append(row(0))
    await settle(lambda: seen.flushed.count("error") >= 2)
    store.hang = False
    await settle(lambda: len(store.rows) == 1)
    assert seen.flushed[-1] == "ok"
    await sink.stop()


@virtual
async def test_stop_drains_within_its_grace_and_leaves_the_rest_durable(tmp_path: Path) -> None:
    store = FakeStore()
    store.down = True
    sink = sink_for(tmp_path, store)
    await sink.start()
    rows = chain(2)
    for r in rows:
        sink.append(r)
    loop = asyncio.get_running_loop()
    before = loop.time()
    with capture_logs() as logs:
        await sink.stop()  # Postgres never comes back: bounded by STOP_GRACE_S of fake time
    assert loop.time() - before <= 2 * machine_events.STOP_GRACE_S
    assert any(e["event"] == "machine_events.stop_not_drained" for e in logs)
    store.down = False
    again = sink_for(tmp_path, store)
    await again.start()
    await settle(lambda: len(store.rows) == 2)
    assert store.rows == frames(rows)
    await again.stop()


@virtual
async def test_stop_after_a_drain_leaves_an_empty_wal(tmp_path: Path) -> None:
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    for r in chain(3):
        sink.append(r)
    await sink.stop()
    assert len(store.rows) == 3
    assert json.loads((tmp_path / "machine_events.wal.committed").read_text() or "0") == 0
    assert (tmp_path / "machine_events.wal").stat().st_size == 0


# --- the builder the composition root reaches the sink through (C-3.3) -------------------------


@virtual
async def test_the_admin_wiring_builder_takes_the_wal_path_and_cap_from_the_settings(
    tmp_path: Path,
) -> None:
    from candleviewer.admin.wiring import build_machine_event_sink
    from candleviewer.settings import Settings

    settings = Settings(
        audit_wal_path=str(tmp_path / "audit" / "audit.wal"),
        machine_event_wal_max_bytes=1024 * 1024,
    )
    store, seen = FakeStore(), Seen()
    sink = build_machine_event_sink(settings, store, metrics=seen.metrics())
    assert sink.wal_path == tmp_path / "audit" / "machine_events.wal"
    assert sink.max_bytes == 1024 * 1024
    await sink.start()
    sink.append(row(0))
    await settle(lambda: len(store.rows) == 1)
    await sink.stop()
    assert seen.flushed == ["ok"]


# --- start edge cases ----------------------------------------------------------------------------


@virtual
async def test_a_corrupt_wal_at_start_fails_closed_and_releases_its_lock(tmp_path: Path) -> None:
    """A frame corrupt before the acknowledged end stops the boot (`AuditWalCorrupt`, never
    skipped); the lock is dropped, so the fixed WAL can be opened again."""
    path = tmp_path / "machine_events.wal"
    good = [encode_frame(f) for f in frames(chain(3))]
    bad = bytearray(good[1])
    bad[4] ^= 0x01
    path.write_bytes(good[0] + bytes(bad) + good[2])
    sink = sink_for(tmp_path, FakeStore())
    with pytest.raises(AuditWalCorrupt):
        await sink.start()
    path.write_bytes(b"".join(good))
    store = FakeStore()
    fixed = sink_for(tmp_path, store)
    await fixed.start()
    await settle(lambda: len(store.rows) == 3)
    await fixed.stop()


@virtual
async def test_a_restart_after_a_flusher_death_reuses_the_open_wal(tmp_path: Path) -> None:
    store = FakeStore()
    store.poison = StorageQueryFailed("23514")
    sink = sink_for(tmp_path, store)
    await sink.start()
    sink.append(row(0))
    await settle(lambda: sink.failure is not None)
    store.poison = None
    await sink.start()  # the operator's restart: the lock and the open WAL are kept
    await settle(lambda: len(store.rows) == 1)
    await sink.start()  # running: a no-op
    assert sink.failure is None
    await sink.stop()


@pytest.mark.parametrize("bad", ["not a row", {"row": 1}], ids=["str", "dict"])
@virtual
async def test_something_that_is_no_row_is_rejected(tmp_path: Path, bad: Any) -> None:
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    with pytest.raises(MachineEventRejected, match="MachineEventRow"):
        sink.append(bad)
    with pytest.raises(MachineEventRejected, match="occurred_at"):
        sink.append(row(0, occurred_at=1_700_000_000))
    await sink.stop()


# --- review round 1 (E50-T63): the stall page, the refused count, owner-only files, frame bound ---


@virtual
async def test_a_flush_failing_for_60_s_pages_once_per_window(tmp_path: Path) -> None:
    """code-2: an insert that keeps failing without a commit pages after `FLUSH_STALL_PAGE_S`, at
    most once per window (the WAL has room, so `append` would not page until it fills)."""
    store, seen, clock = FakeStore(), Seen(), Clock()

    async def sleep(delay: float) -> None:  # the injected clock moves with every backoff
        clock.now += timedelta(seconds=delay)
        await asyncio.sleep(delay)

    store.down = True
    sink = sink_for(tmp_path, store, clock=clock, sleep=sleep, metrics=seen.metrics())
    await sink.start()
    sink.append(row(0))

    def pages(logs: list[Any]) -> int:
        return sum(1 for e in logs if e["event"] == "machine_events.flush_stalled")

    with capture_logs() as logs:
        await settle(lambda: seen.flushed.count("error") >= 7)  # failing for 31.5 s
        assert pages(logs) == 0
        await settle(lambda: seen.flushed.count("error") >= 8)  # 61.5 s
        assert pages(logs) == 1
        await settle(lambda: seen.flushed.count("error") >= 9)  # 91.5 s: the same window
        assert pages(logs) == 1
        await settle(lambda: seen.flushed.count("error") >= 10)  # 121.5 s: the next one
        assert pages(logs) == 2
    [first, *_] = [e for e in logs if e["event"] == "machine_events.flush_stalled"]
    assert first["cv_page"] is True and first["log_level"] == "critical"
    assert first["error"] == "StorageTierUnavailable"
    store.down = False
    await settle(lambda: len(store.rows) == 1)
    await sink.stop()


@virtual
async def test_a_rejected_row_is_counted_refused(tmp_path: Path) -> None:
    """code-3: a rejection is a lost audit row: the sink counts it (`event_flush`, `refused`)."""
    seen = Seen()
    sink = sink_for(tmp_path, FakeStore(), metrics=seen.metrics())
    await sink.start()
    with pytest.raises(MachineEventRejected):
        sink.append(row(0, occurred_at="2026-10-21T05:00:00+02:00"))
    with pytest.raises(MachineEventRejected):
        sink.append(row(1, payload={"x": float("nan")}))
    assert seen.flushed == ["refused", "refused"]
    await sink.stop()


@virtual
async def test_the_wal_and_its_cursor_stay_owner_only(tmp_path: Path) -> None:
    """code-6: the WAL holds the table's P1 payloads: 0600, also after a commit and a compaction
    replaced the files."""
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    wal = tmp_path / "machine_events.wal"
    cursor = tmp_path / "machine_events.wal.committed"
    assert [stat.S_IMODE(p.stat().st_mode) for p in (wal, cursor)] == [0o600, 0o600]
    sink.append(row(0))
    await settle(lambda: len(store.rows) == 1 and sink.pending == 0)
    assert [stat.S_IMODE(p.stat().st_mode) for p in (wal, cursor)] == [0o600, 0o600]
    await sink.stop()


@virtual
async def test_a_frame_declared_larger_than_any_row_stops_the_flusher_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """code-7: the sink never writes a frame over `MAX_FRAME_BYTES`, so a larger one (here
    valid, past the window) is corruption: refused before it is read, never read whole."""
    path = tmp_path / "machine_events.wal"
    big = {"pad": "b" * (300 * 1024)}
    path.write_bytes(encode_frame(big))
    store = FakeStore()
    recorded = record_wal_io(monkeypatch)
    sink = sink_for(tmp_path, store)
    await sink.start()
    await settle(lambda: sink.failure is not None)
    assert type(sink.failure).__name__ == "AuditWalCorrupt" and store.rows == []
    assert max(recorded.read_sizes(path.name)) <= machine_events.FLUSH_WINDOW_BYTES
    await sink.stop()
