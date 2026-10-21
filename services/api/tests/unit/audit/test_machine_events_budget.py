"""Scenario 7 (E50-T63): a large WAL is drained in bounded windows. The C-2.17 stall bound is
proven by structure, as `test_page_structure_budget.py` proves the audit page's: a recording file
double counts the bytes each WAL call reads and writes, the rows per batch and the `fsync`s; no
assertion reads a clock (the virtual-time loop runs the coalesce sleeps)."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest
from audit_waits import virtual
from test_machine_events import T0, FakeStore, settle
from wal_double import record_wal_io

from candleviewer.audit.machine_events import (
    COMPACT_COPY_MAX_BYTES,
    FLUSH_BATCH_ROWS,
    FLUSH_WINDOW_BYTES,
    MachineEventWalSink,
)
from candleviewer.audit.wal import encode_frame
from candleviewer.statechart.plugins.audit import GENESIS_HASH


def _pad(rng: random.Random) -> int:
    return rng.randint(6000, 9000) if rng.random() < 0.1 else rng.randint(100, 400)


def _records(total: int, seed: int) -> list[dict[str, Any]]:
    """Frames of mixed sizes until `total` bytes, mostly small, one in ten near 8 KiB: some
    windows end on the byte bound, others on the row bound."""
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible test data
    out: list[dict[str, Any]] = []
    size, prev = 0, GENESIS_HASH
    while size < total:
        i = len(out)
        row_hash = f"{i:064x}"
        record = {
            "machine_kind": "persist_min", "entity_id": "e-1", "env": "demo",
            "event_type": "PING", "payload": {"pad": "p" * _pad(rng)},
            "from_states": ["persist_min.idle"], "to_states": ["persist_min.idle"],
            "actions_run": ["record"], "fault": None, "occurred_at": T0.isoformat(),
            "phase": "commit", "prev_hash": prev, "row_hash": row_hash,
        }  # fmt: skip
        out.append(record)
        size += len(encode_frame(record))
        prev = row_hash
    return out


@virtual
async def test_a_20_mib_wal_drains_in_bounded_windows_in_order_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "machine_events.wal"
    records = _records(20 * 1024 * 1024, seed=7)
    path.write_bytes(b"".join(encode_frame(r) for r in records))  # uncommitted, acknowledged
    store = FakeStore()
    recorded = record_wal_io(monkeypatch)
    sink = MachineEventWalSink(store, path)
    await sink.start()
    await settle(lambda: len(store.rows) == len(records))
    await sink.stop()
    reads = recorded.read_sizes(path.name)
    assert reads and max(reads) <= FLUSH_WINDOW_BYTES  # one window per batch, never the file
    assert max(store.batches) <= FLUSH_BATCH_ROWS
    assert FLUSH_BATCH_ROWS in store.batches  # the row bound bit
    assert min(store.batches[:-1]) < FLUSH_BATCH_ROWS  # and so did the byte bound
    assert store.rows == records  # every row, in order, once
    assert recorded.fsyncs <= 3 * len(store.batches)  # the cursor, and a compaction's two
    assert recorded.write_sizes("machine_events.tmp") == [0]  # O(1): nothing was pending


@virtual
async def test_a_compaction_with_rows_pending_copies_at_most_its_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over half the cap committed and a remainder within `COMPACT_COPY_MAX_BYTES`: one bounded
    copy reclaims the prefix while rows are still pending; then the drain ends in O(1)."""
    path = tmp_path / "machine_events.wal"
    records = _records(3 * 1024 * 1024, seed=11)
    path.write_bytes(b"".join(encode_frame(r) for r in records))
    store = FakeStore()
    recorded = record_wal_io(monkeypatch)
    sink = MachineEventWalSink(store, path, max_bytes=4 * 1024 * 1024)
    await sink.start()
    await settle(lambda: len(store.rows) == len(records))
    await sink.stop()
    copies = recorded.write_sizes("machine_events.tmp")
    assert copies[-1] == 0 and 0 < max(copies) <= COMPACT_COPY_MAX_BYTES
    assert store.rows == records
