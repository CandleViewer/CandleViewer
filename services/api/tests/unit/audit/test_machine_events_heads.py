"""`MachineEventWalSink.head` and `seed` (E50-T63, chain continuity). The sink holds each machine
key's chain head, the last accepted `row_hash`, in a map bounded at `HEAD_KEYS_MAX` (least
recently used evicted). `seed(key)` returns at once for a held key; otherwise it waits for the WAL
to drain and reads the head through the events store, both within `SEED_DRAIN_S`; a timeout or a
read error raises `MachineEventUnavailable`, so no machine starts a chain that could fork. Fakes
only, on the virtual-time loop."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from audit_waits import virtual
from structlog.testing import capture_logs
from test_machine_events import T0, FakeStore, chain, frames, row, settle, sink_for

from candleviewer.audit import machine_events
from candleviewer.audit.machine_events import SEED_DRAIN_S, MachineEventUnavailable
from candleviewer.audit.wal import AuditWal
from candleviewer.statechart.persistence import MachineKey
from candleviewer.statechart.plugins import CvAuditPlugin
from candleviewer.statechart.plugins.audit import (
    GENESIS_HASH,
    MachineEventRow,
    row_digest,
    verify_chain,
)
from candleviewer.storage.errors import StorageQueryFailed

KEY = MachineKey("persist_min", "00000000-0000-4000-8000-000000000001", "demo")


def _other(n: int) -> MachineKey:
    return MachineKey("persist_min", f"e-{n}", "demo")


@virtual
async def test_head_is_none_until_an_append_and_then_the_last_accepted_row_hash(
    tmp_path: Path,
) -> None:
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    assert sink.head(KEY) is None
    rows = chain(2)
    for r in rows:
        sink.append(r)
    assert sink.head(KEY) == rows[-1].row_hash
    await sink.stop()


@virtual
async def test_a_rejected_append_holds_no_head(tmp_path: Path) -> None:
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    with pytest.raises(ValueError):
        sink.append(row(0, occurred_at="yesterday"))
    assert sink.head(KEY) is None
    await sink.stop()


@virtual
async def test_seed_returns_at_once_for_a_held_key(tmp_path: Path) -> None:
    store = FakeStore()
    store.down = True  # never read: the held head is the newest one
    sink = sink_for(tmp_path, store)
    await sink.start()
    sink.append(row(0))
    await sink.seed(KEY)
    assert sink.head(KEY) == row(0).row_hash
    await sink.stop()


@virtual
async def test_seed_waits_for_the_wal_to_drain_then_holds_the_stores_head(tmp_path: Path) -> None:
    """Leftover frames of a previous run may belong to the key: the head is read after them."""
    rows = chain(3)
    wal = AuditWal(tmp_path / "machine_events.wal")
    for frame in frames(rows):
        wal.append(frame)
    store = FakeStore()
    store.heads[(KEY.machine_kind, KEY.entity_id, KEY.env)] = rows[-1].row_hash
    sink = sink_for(tmp_path, store)
    await sink.start()
    await sink.seed(KEY)
    assert len(store.rows) == 3 and sink.head(KEY) == rows[-1].row_hash
    await sink.stop()


@virtual
async def test_seed_of_a_key_with_no_rows_holds_the_genesis_hash(tmp_path: Path) -> None:
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    await sink.seed(KEY)
    assert sink.head(KEY) == GENESIS_HASH
    await sink.stop()


@virtual
async def test_seed_that_cannot_drain_within_seed_drain_s_raises_unavailable(
    tmp_path: Path,
) -> None:
    store = FakeStore()
    store.down = True
    sink = sink_for(tmp_path, store)
    await sink.start()
    sink.append(row(0, key=("persist_min", "e-other", "demo")))  # pending, never drained
    loop = asyncio.get_running_loop()
    before = loop.time()
    with pytest.raises(MachineEventUnavailable, match="head"):
        await sink.seed(KEY)
    assert loop.time() - before == pytest.approx(SEED_DRAIN_S)
    assert sink.head(KEY) is None
    await sink.stop()


@virtual
async def test_a_hanging_head_read_is_cut_by_the_seed_deadline(tmp_path: Path) -> None:
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    store.hang = True
    with pytest.raises(MachineEventUnavailable, match="TimeoutError"):
        await sink.seed(KEY)
    store.hang = False
    await sink.stop()


@virtual
async def test_a_head_read_error_raises_unavailable(tmp_path: Path) -> None:
    store = FakeStore()
    store.down = True
    sink = sink_for(tmp_path, store)
    await sink.start()
    with pytest.raises(MachineEventUnavailable, match="StorageTierUnavailable"):
        await sink.seed(KEY)
    await sink.stop()


@virtual
async def test_seed_never_overwrites_a_head_an_append_set_meanwhile(tmp_path: Path) -> None:
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    await sink.seed(_other(9))  # the WAL has drained: the next seed goes straight to its read
    store.heads[(KEY.machine_kind, KEY.entity_id, KEY.env)] = "ee" * 32  # stale once it lands
    pending = asyncio.ensure_future(sink.seed(KEY))
    await asyncio.sleep(0)  # the seed is now suspended inside the store's head read
    newer = row(5, prev="ee" * 32)
    sink.append(newer)
    await pending
    assert sink.head(KEY) == newer.row_hash
    await sink.stop()


@virtual
async def test_seed_after_the_flusher_died_is_refused_at_once(tmp_path: Path) -> None:
    store = FakeStore()
    store.poison = StorageQueryFailed("23514")
    sink = sink_for(tmp_path, store)
    await sink.start()
    sink.append(row(0, key=("persist_min", "e-other", "demo")))
    await settle(lambda: sink.failure is not None)
    with pytest.raises(MachineEventUnavailable, match="flusher"):
        await sink.seed(KEY)
    await sink.stop()


@virtual
async def test_seed_before_start_is_refused(tmp_path: Path) -> None:
    sink = sink_for(tmp_path, FakeStore())
    with pytest.raises(MachineEventUnavailable, match="not running"):
        await sink.seed(KEY)


@virtual
async def test_the_head_map_is_bounded_and_evicts_the_least_recently_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(machine_events, "HEAD_KEYS_MAX", 3)
    sink = sink_for(tmp_path, FakeStore())
    await sink.start()
    for n in range(3):
        sink.append(row(n, key=("persist_min", f"e-{n}", "demo")))
    assert sink.head(_other(0)) is not None  # a read is a use: e-1 is now the oldest
    sink.append(row(3, key=("persist_min", "e-3", "demo")))
    assert sink.head(_other(1)) is None
    assert [sink.head(_other(n)) is not None for n in (0, 2, 3)] == [True, True, True]
    assert sink.head_count == 3
    await sink.stop()


def test_rows_are_chained_by_their_digest() -> None:
    r = row(0)
    assert r.row_hash == row_digest(replace(r, row_hash=""))


@virtual
async def test_evict_then_commit_never_forks_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 1, code-1: a live machine idle while the head map evicts its key refuses its
    next row (counted, paged) instead of chaining it to a stale hash; once its key is seeded again
    the chain goes on from the stored head, unforked."""
    monkeypatch.setattr(machine_events, "HEAD_KEYS_MAX", 2)
    store = FakeStore()
    sink = sink_for(tmp_path, store)
    await sink.start()
    await sink.seed(KEY)
    plugin = CvAuditPlugin(
        machine_kind=KEY.machine_kind, entity_id=KEY.entity_id, env=KEY.env, sink=sink,
        write_ahead=False, head=lambda: sink.head(KEY), clock=lambda: T0,
    )  # fmt: skip
    interp = SimpleNamespace(_active_state_nodes=())

    def commit(event: str) -> None:
        plugin.on_event_received(interp, SimpleNamespace(type=event, data={}))
        plugin.on_transition(interp, (), (), SimpleNamespace(event=event))

    commit("PING")
    for n in range(2):  # two other machines push this key out of the map
        sink.append(row(n, key=("persist_min", f"e-{n}", "demo")))
    assert sink.head(KEY) is None
    with capture_logs() as logs:
        commit("PONG")
    assert plugin.sink_failures == 1
    assert [e["cv_page"] for e in logs if e["event"] == "statechart_audit_sink_failed"] == [True]
    await sink.seed(KEY)  # the owner seeds again (a fault-row writer would, too)
    commit("PING")
    await settle(lambda: sink.pending == 0)
    ours = [MachineEventRow(**r) for r in store.rows if r["entity_id"] == KEY.entity_id]
    assert [r.event_type for r in ours] == ["PING", "PING"] and verify_chain(ours)
    await sink.stop()
