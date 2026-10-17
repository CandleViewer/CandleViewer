"""ADR-0037 S2a1 (#3009): `ingest()` returns a commit token, the record's ordinal in the WAL's
append order, and `committed_through()` the highest token whose record the flusher has put in
Postgres. Tokens are monotonic and committed in WAL order across compactions and flusher
restarts, `committed_through()` never passes a token whose record is not stored (a refusing
insert holds it back), and a repeated record gets the next token and is stored once."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.audit import wal as wal_module
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.wal import AuditWal, encode_frame
from candleviewer.audit.writer import AuditUnavailable, AuditWriter


class _ObservedRepository(FakeAuditRepository):
    """At every insert attempt, records `committed_through()`, the record id being inserted
    and the ids already stored; refuses the ids in `refuse` (a record Postgres keeps failing)."""

    def __init__(self) -> None:
        super().__init__()
        self.writer: AuditWriter | None = None
        self.refuse: set[str] = set()
        self.attempts: list[tuple[int, str, frozenset[str]]] = []

    def snapshot(self) -> tuple[int, frozenset[str]]:
        through = -1 if self.writer is None else self.writer.committed_through()
        return through, frozenset(r["record_id"] for r in self.rows)

    async def insert(self, record: dict[str, Any]) -> None:
        through, stored = self.snapshot()
        self.attempts.append((through, record["record_id"], stored))
        if record["record_id"] in self.refuse:
            raise ConnectionError("insert refused")
        await super().insert(record)


def _writer(repo: _ObservedRepository, path: Path, **kw: Any) -> AuditWriter:
    w = AuditWriter(repo, str(path / "audit.wal"), clock=FakeClock(), sleep=repo.retry_sleep, **kw)
    repo.writer = w
    return w


def _never_ahead(repo: _ObservedRepository, ids: list[str]) -> None:
    """At every insert attempt and now, each token at or below `committed_through()` names a
    stored record (`ids[t - 1]` is token t's), and `committed_through()` never went down."""
    seen = [(through, stored) for through, _id, stored in repo.attempts] + [repo.snapshot()]
    for through, stored in seen:
        assert set(ids[:through]) <= stored
    throughs = [through for through, _ in seen]
    assert throughs == sorted(throughs)


async def test_writer_tokens_are_committed_in_wal_order_across_compactions_and_a_restart(
    tmp_path: Path,
) -> None:
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, flush_batch_size=1)  # a commit and a compaction per record
    await w.start()
    repo.down = True
    built = [w.build("auth.login", actor_label=str(i)) for i in range(4)]
    assert [await w.ingest(b) for b in built] == [1, 2, 3, 4]
    assert w.committed_through() == 0
    repo.down = False
    await w.flush(5)
    ids = [str(b.record_id) for b in built]
    # Before each insert exactly the tokens before it are committed: WAL order.
    assert [(through, rid) for through, rid, _ in repo.attempts] == [
        (0, ids[0]),  # Postgres down
        (0, ids[0]),
        (1, ids[1]),
        (2, ids[2]),
        (3, ids[3]),
    ]
    assert w.committed_through() == 4 and (tmp_path / "audit.wal").stat().st_size == 0
    await w.stop(1)
    await w.start()  # a flusher restart in the same process
    more = [w.build("auth.logout", actor_label=str(i)) for i in range(2)]
    assert [await w.ingest(b) for b in more] == [5, 6]
    await w.flush(5)
    await w.stop(1)
    ids += [str(b.record_id) for b in more]
    assert w.committed_through() == 6 and [r["record_id"] for r in repo.rows] == ids
    _never_ahead(repo, ids)


async def test_writer_a_refused_insert_holds_committed_through_back_across_a_flusher_death(
    tmp_path: Path,
) -> None:
    died = asyncio.Event()

    async def alarm(_reason: str) -> None:
        died.set()

    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, max_insert_attempts=2, on_alarm=alarm)
    await w.start()
    repo.down = True  # Postgres refuses every insert
    built = [w.build("auth.session_revoked", actor_label=str(i)) for i in range(3)]
    assert [await w.ingest(b) for b in built] == [1, 2, 3]
    assert w.committed_through() == 0
    ids = [str(b.record_id) for b in built]
    repo.refuse = {ids[1]}  # Postgres is back, but token 2's insert keeps failing
    repo.down = False
    await asyncio.wait_for(died.wait(), 5)  # the flusher gave up on it: fail closed
    assert w.committed_through() == 1 and [r["record_id"] for r in repo.rows] == ids[:1]
    with pytest.raises(AuditUnavailable):
        await w.ingest(w.build("auth.logout", actor_label="refused"))
    repo.refuse.clear()
    await w.start()  # the restart once the cause is fixed
    await w.flush(5)
    assert w.committed_through() == 3
    last = w.build("auth.logout", actor_label="next")
    assert await w.ingest(last) == 4
    await w.flush(5)
    await w.stop(1)
    ids.append(str(last.record_id))
    assert w.committed_through() == 4 and [r["record_id"] for r in repo.rows] == ids
    _never_ahead(repo, ids)


async def test_writer_a_repeated_record_gets_the_next_token_and_is_stored_once(
    tmp_path: Path,
) -> None:
    """The repeat is appended again and its insert is a no-op (`ON CONFLICT (record_id) DO
    NOTHING`); that no-op commits its token, since a row with its `record_id` is stored."""
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path)
    await w.start()
    first, other = (w.build("auth.logout", actor_label=label) for label in ("a", "b"))
    repeat = json.loads(first.model_dump_json())  # as the lane's drain hands it over
    assert [await w.ingest(r) for r in (first, repeat, other)] == [1, 2, 3]
    await w.flush(5)
    await w.stop(1)
    ids = [str(first.record_id), str(first.record_id), str(other.record_id)]
    assert w.committed_through() == 3 and [r["record_id"] for r in repo.rows] == ids[::2]
    assert [rid for _through, rid, _ in repo.attempts] == ids
    assert (await AuditQueryService(repo).verify()).verified
    _never_ahead(repo, ids)


async def test_writer_a_refused_append_takes_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path)
    await w.start()
    assert await w.ingest(w.build("auth.login", actor_label="a")) == 1

    def boom(_record: dict[str, Any]) -> int:
        raise OSError("disk gone")

    append = w._wal.append
    monkeypatch.setattr(w._wal, "append", boom)
    with pytest.raises(AuditUnavailable):
        await w.ingest(w.build("auth.login", actor_label="refused"))
    monkeypatch.setattr(w._wal, "append", append)
    assert await w.ingest(w.build("auth.login", actor_label="b")) == 2
    await w.flush(5)
    await w.stop(1)
    assert w.committed_through() == 2
    assert [r["actor_label"] for r in repo.rows] == ["a", "b"]


def _emission(label: str, clock: FakeClock) -> AuditEmission:
    """What `build()` makes, without a writer: the WAL cap below needs the frame sizes first."""
    return AuditEmission(
        record_id=uuid.uuid4(),
        action="auth.logout",
        actor_label=label,
        event_ts=clock(),
    )


async def test_writer_tokens_survive_the_compaction_a_full_wal_runs(tmp_path: Path) -> None:
    """A WAL left with a committed prefix (a crash before its compaction) is compacted by the
    append that would overflow it, while an earlier token still waits for the flusher."""
    clock = FakeClock()
    path = tmp_path / "audit.wal"
    old = AuditWal(path)
    for i in range(3):
        prefix = old.append(json.loads(_emission(f"old{i}", clock).model_dump_json()))
    old.mark_committed(prefix)  # stored in Postgres already, but not yet compacted
    new = [_emission(label, clock) for label in ("a", "b")]
    first, second = (len(encode_frame(json.loads(e.model_dump_json()))) for e in new)
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, max_wal_bytes=prefix + first + second - 1)
    await w.start()
    await w.flush(5)  # nothing pending: no batch is in flight
    # Concurrent, so the second append overflows before the flusher reads the first.
    assert list(await asyncio.gather(w.ingest(new[0]), w.ingest(new[1]))) == [1, 2]
    await w.flush(5)
    await w.stop(1)
    ids = [str(e.record_id) for e in new]
    assert w.committed_through() == 2 and [r["record_id"] for r in repo.rows] == ids
    _never_ahead(repo, ids)


class _NoFsync:
    """`os` for `candleviewer.audit.wal` without `fsync`: the property is about token order;
    the WAL's durability has its own tests."""

    @staticmethod
    def fsync(_fd: int) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)


#: Ingests weighted up; a WAL of three frames, so an outage also refuses appends.
_STEPS = st.lists(
    st.sampled_from(["ingest"] * 3 + ["repeat", "down", "up", "settle", "restart"]),
    min_size=4,
    max_size=40,
)


async def _interleave(steps: list[str], batch: int, path: Path) -> None:
    repo = _ObservedRepository()
    w = _writer(repo, path, flush_batch_size=batch, max_wal_bytes=1200)
    await w.start()
    built: list[AuditEmission] = []
    ids: list[str] = []  # ids[t - 1] is token t's record
    for step in steps:
        if step in ("ingest", "repeat"):
            if step == "repeat" and built:
                record = built[len(built) // 2]
            else:
                record = w.build("auth.logout", actor_label=str(len(built)))
            try:
                token = await w.ingest(record)
            except AuditUnavailable:  # the WAL is full and a batch is in flight: no token
                continue
            assert token == len(ids) + 1
            built.append(record)
            ids.append(str(record.record_id))
        elif step in ("down", "up"):
            repo.down = step == "down"
        elif step == "settle" and not repo.down:
            await w.flush(5)
        elif step == "settle":
            for _ in range(5):
                await asyncio.sleep(0)
        else:
            await w.stop(0.01 if repo.down else 1)
            await w.start()
        _never_ahead(repo, ids)
    repo.down = False
    await w.flush(5)
    await w.stop(1)
    assert w.committed_through() == len(ids)
    assert [r["record_id"] for r in repo.rows] == list(dict.fromkeys(ids))
    _never_ahead(repo, ids)


@settings(max_examples=40, deadline=None)
@given(steps=_STEPS, batch=st.integers(min_value=1, max_value=3))
def test_writer_random_interleavings_keep_committed_through_monotonic_and_stored(
    steps: list[str], batch: int
) -> None:
    """Random ingests, repeats, outages, flushes (each commit compacts) and flusher restarts:
    `committed_through()` never goes down and never passes a record that is not stored."""
    with mock.patch.object(wal_module, "os", _NoFsync()), tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_interleave(steps, batch, Path(tmp)))
