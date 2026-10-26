"""E16-T03 backpressure ladder through the writer: queue -> WAL spill -> recorded drop."""

from __future__ import annotations

from pathlib import Path

from candleviewer.recorder.wal import RUNS_DIR, encode_frame
from tests.unit.recorder._writer_helpers import (
    T0,
    FsyncCounter,
    make_writer,
    trade,
)


def _frame_size() -> int:
    from candleviewer.recorder.writer import trade_records

    return len(encode_frame(trade_records(trade(1))[0]))


async def test_queue_bound_spills_to_wal(tmp_path: Path) -> None:
    w, sink, *_ = await make_writer(tmp_path, max_queue_rows=3)
    for i in range(3):
        await w.on_trade(trade(i))
    assert w.backlog_rows == 3 and w.spill_bytes == 0
    await w.on_trade(trade(3))
    assert w.is_spilling("trades")
    await w.pump("trades")  # one batched WAL append
    assert w.backlog_rows == 0 and w.spill_bytes > 0
    await w.recover()
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t0", "t1", "t2", "t3"]
    assert w.spill_bytes == 0 and not w.is_spilling("trades")


async def test_spilled_events_cost_one_fsync_per_pump_not_per_event(tmp_path: Path) -> None:
    w, sink, _, _, clock = await make_writer(tmp_path)
    fsync: FsyncCounter = w._lanes["trades"].wal._fsync  # type: ignore[assignment]
    sink.down.add("*")
    await w.on_trade(trade(0))
    clock.advance(0.2)
    await w.pump("trades")  # write fails -> spill (1 fsync)
    base = fsync.calls
    for i in range(1, 501):
        await w.on_trade(trade(i))  # admitted without any I/O
    assert fsync.calls == base
    await w.pump("trades")
    assert fsync.calls == base + 1


async def test_questdb_down_spills_then_replays_in_exch_ts_order(tmp_path: Path) -> None:
    """Scenario: QuestDB stopped -> WAL, no drops; on return replay in exch_ts order, truncate."""
    w, sink, store, events, clock = await make_writer(tmp_path)
    sink.down.add("*")
    for i in (5, 1, 3):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    for i in (4, 2):
        await w.on_trade(trade(i))
    await w.pump("trades")
    assert w.spill_bytes > 0 and sink.rows("trades") == []
    clock.advance(1.0)
    await w.pump("trades")  # retry while still down: stays spilled
    assert w.is_spilling("trades")
    sink.down.clear()
    await w.recover()
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t1", "t2", "t3", "t4", "t5"]
    lane_dir = tmp_path / "wal" / "trades"
    assert w.spill_bytes == 0 and not any(lane_dir.glob("*.wal"))
    assert not (lane_dir / RUNS_DIR).exists()
    assert store.gaps == [] and events.events == []


async def test_spill_replay_retried_on_cadence(tmp_path: Path) -> None:
    w, sink, _, _, clock = await make_writer(tmp_path)
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    sink.down.clear()
    clock.advance(0.5)
    await w.pump("trades")
    assert sink.rows("trades") == []
    clock.advance(0.5)
    await w.pump("trades")
    assert len(sink.rows("trades")) == 1


async def test_wal_full_drops_with_gap_row_and_one_critical_event_per_episode(
    tmp_path: Path,
) -> None:
    """Scenario: WAL at cap + QuestDB down -> drop, recording_gaps row, one critical event."""
    w, sink, store, events, clock = await make_writer(tmp_path, wal_max_bytes=_frame_size() * 2)
    sink.down.add("*")
    for i in range(1, 7):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    ((key, [(first, last)]),) = w.pending_gaps().items()
    assert key == ("BTCUSDT", "trades") and (first, last) == (T0 + 3, T0 + 6)
    (event,) = events.events
    assert event.severity == "critical" and event.details["symbol"] == "BTCUSDT"
    await w.flush_gaps()
    (gap,) = store.gaps
    assert gap["cause"] == "backpressure_drop" and gap["stream"] == "trades"
    # The outage continues past the 10 s gap flush: same episode, no second page.
    await w.on_trade(trade(7))
    clock.advance(10.0)
    await w.pump("trades")
    await w.flush_gaps()
    assert len(events.events) == 1 and len(store.gaps) == 2
    await w.flush_counters()
    kw = store.counters[0][1]
    assert kw["messages_received"] == 7 and kw["messages_dropped"] == 5
    # Drained -> episode closes -> a new outage pages again.
    sink.down.clear()
    await w.recover()
    sink.down.add("*")
    for i in range(8, 12):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    assert len(events.events) == 2


async def test_gap_and_counters_kept_until_a_session_exists(tmp_path: Path) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path, wal_max_bytes=1)
    store.session = False
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    await w.flush_gaps()
    await w.flush_counters()
    assert w.pending_gaps() and store.gaps == [] and store.counters == []
    await w.on_trade(trade(2))
    await w.pump("trades")  # window widens while waiting
    store.session = True  # E16-T04 opened the session
    await w.flush_gaps()
    await w.flush_counters()
    (gap,) = store.gaps
    assert gap["cause"] == "backpressure_drop"
    assert store.counters[0][1]["messages_dropped"] == 2
    assert not w.pending_gaps()


async def test_unpersisted_gap_on_stop_raises_critical_event(tmp_path: Path) -> None:
    w, sink, store, events, clock = await make_writer(tmp_path, wal_max_bytes=1)
    store.session = False
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    await w.stop()
    kinds = [e.kind for e in events.events]
    assert kinds == ["recorder_wal_full", "recorder_gap_unpersisted"]
    assert "backpressure_drop" in events.events[-1].message


async def test_disk_error_on_spill_is_a_recorded_drop(tmp_path: Path) -> None:
    """Chaos 13 (disk full): OSError on append -> drop + gap, never silent."""
    w, sink, _, events, clock = await make_writer(tmp_path)

    def boom(_: object) -> int:
        raise OSError(28, "No space left on device")

    w._lanes["trades"].wal.append = boom  # type: ignore[method-assign]
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    assert ("BTCUSDT", "trades") in w.pending_gaps() and events.events


async def test_gap_retained_when_store_fails(tmp_path: Path) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path, wal_max_bytes=1)
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    store.fail = True
    await w.flush_gaps()
    assert w.pending_gaps()
    store.fail = False
    await w.flush_gaps()
    assert not w.pending_gaps() and len(store.gaps) == 1


async def test_corrupt_tail_symbol_gets_a_gap_even_after_removal(tmp_path: Path) -> None:
    w, sink, _, events, clock = await make_writer(tmp_path)
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    spill = tmp_path / "wal" / "trades" / "spill.wal"
    data = bytearray(spill.read_bytes())
    data[12] ^= 0xFF  # the only frame is corrupt
    spill.write_bytes(bytes(data))
    w.seed([])  # symbol no longer recorded
    sink.down.clear()
    await w.recover()
    assert ("BTCUSDT", "trades") in w.pending_gaps()
    assert any(e.kind == "recorder_wal_corrupt" for e in events.events)
    assert sink.rows("trades") == []


async def test_interrupted_replay_resumes_from_checkpoint(tmp_path: Path) -> None:
    """Scenario: replay interrupted halfway and restarted -> no duplicates, resumes."""
    w, sink, _, _, clock = await make_writer(tmp_path, flush_rows=2)
    sink.down.add("*")
    for i in range(6):
        await w.on_trade(trade(i))
    await w.on_trade(trade(3))  # an upstream duplicate inside the WAL
    clock.advance(0.2)
    await w.pump("trades")
    await w.pump("trades")
    sink.down.clear()
    sink.fail_after = 1  # first batch commits, second dies
    await w.recover()
    assert w.is_spilling("trades") and len(sink.rows("trades")) == 2
    sink.fail_after = None
    w2, *_ = await make_writer(tmp_path, flush_rows=2, sink=sink)
    await w2.start()
    await w2.stop()
    ids = [r["trade_id"] for r in sink.rows("trades")]
    assert ids == [f"t{i}" for i in range(6)]  # exactly once, in exch_ts order
    assert not w2.is_spilling("trades") and w2.spill_bytes == 0


async def test_stale_checkpoint_never_skips_rows_through_the_writer(tmp_path: Path) -> None:
    w, sink, _, _, clock = await make_writer(tmp_path, flush_rows=2, replay_chunk_rows=2)
    sink.down.add("*")
    for i in range(6):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    sink.down.add("*")
    await w.recover()  # builds runs/, write fails
    runs = tmp_path / "wal" / "trades" / RUNS_DIR
    (runs / "CHECKPOINT").write_bytes(b'{"ck": 999999999, "total": 6}')
    sink.down.clear()
    await w.recover()
    assert [r["trade_id"] for r in sink.rows("trades")] == [f"t{i}" for i in range(6)]
    assert not runs.exists() and not w.is_spilling("trades")


async def test_truncated_run_becomes_a_gap_and_the_rest_replays(tmp_path: Path) -> None:
    w, sink, store, events, clock = await make_writer(tmp_path, flush_rows=2, replay_chunk_rows=2)
    sink.down.add("*")
    for i in range(6):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    await w.recover()  # runs/ built; write still fails
    runs = tmp_path / "wal" / "trades" / RUNS_DIR
    victim = runs / "000001.run"
    victim.write_bytes(victim.read_bytes()[:5])
    sink.down.clear()
    await w.recover()
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t0", "t1", "t4", "t5"]
    # Persisted immediately (a live session exists), so the DAMAGED marker could be cleared.
    (gap,) = store.gaps
    assert gap["cause"] == "backpressure_drop" and not w.pending_gaps()
    assert any(e.kind == "recorder_wal_corrupt" for e in events.events)


async def test_crash_after_quarantine_before_gap_persist_raises_one_gap_on_restart(
    tmp_path: Path,
) -> None:
    """Adversarial N1: the damaged run is already in corrupt/ when the process dies; the
    durable DAMAGED marker makes the restart raise exactly one gap for that window."""
    w, sink, store, _, clock = await make_writer(tmp_path, flush_rows=2, replay_chunk_rows=2)
    sink.down.add("*")
    for i in range(6):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    await w.recover()  # runs/ built; write fails
    lane_wal = w._lanes["trades"].wal
    runs = tmp_path / "wal" / "trades" / RUNS_DIR
    victim = runs / "000001.run"
    victim.write_bytes(victim.read_bytes()[:5])
    lane_wal.verify_runs()  # quarantine happens ... then the process "crashes"
    assert not victim.exists() and (runs / "DAMAGED").exists()

    sink.down.clear()
    w2, sink2, store2, events2, _ = await make_writer(
        tmp_path, flush_rows=2, replay_chunk_rows=2, sink=sink
    )
    await w2.start()
    await w2.stop()
    assert [g["start"].timestamp() for g in store2.gaps] == [
        store2.gaps[0]["start"].timestamp()
    ]  # exactly one gap row
    (gap,) = store2.gaps
    assert gap["cause"] == "backpressure_drop"
    assert sum(e.kind == "recorder_wal_corrupt" for e in events2.events) == 1
    assert [r["trade_id"] for r in sink2.rows("trades")] == ["t0", "t1", "t4", "t5"]
    assert not runs.exists()
    assert store.gaps == []


async def test_damaged_marker_kept_until_the_gap_row_is_persisted(tmp_path: Path) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path, flush_rows=2, replay_chunk_rows=2)
    sink.down.add("*")
    for i in range(4):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    await w.recover()
    runs = tmp_path / "wal" / "trades" / RUNS_DIR
    victim = runs / "000001.run"
    victim.write_bytes(victim.read_bytes()[:5])
    store.session = False  # gap cannot be persisted yet
    sink.down.clear()
    await w.recover()
    assert w.pending_gaps()
    # runs/ is gone after a full replay, but the gap stays pending in memory and is still
    # raised as recorder_gap_unpersisted at stop (never silent).
    store.session = True
    await w.flush_gaps()
    assert len(store.gaps) == 1
