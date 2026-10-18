"""ADR-0037 S2a1 (#3009): `ingest()` returns a commit token, the record's ordinal in the WAL's
append order, and `committed_through()` the highest token whose record the flusher has put in
Postgres. Tokens are monotonic and committed in WAL order across compactions and flusher
restarts, `committed_through()` never passes a token whose record is not stored (a refusing
insert holds it back), and a repeated record gets the next token and is stored once. A backlog
from an earlier process, and a record a restarted flusher reads again, take no token; a
compaction that fails moves no base. `ingest()` refuses an invalid record, model or JSON."""

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
from pydantic import ValidationError

from candleviewer.audit import wal as wal_module
from candleviewer.audit.actions import UnknownAuditAction
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
        self.attempted = asyncio.Event()  # set by the first insert attempt
        self.attempts: list[tuple[int, str, frozenset[str]]] = []

    def snapshot(self) -> tuple[int, frozenset[str]]:
        through = -1 if self.writer is None else self.writer.committed_through()
        return through, frozenset(r["record_id"] for r in self.rows)

    async def insert(self, record: dict[str, Any]) -> None:
        through, stored = self.snapshot()
        self.attempts.append((through, record["record_id"], stored))
        self.attempted.set()
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


def _emission(label: str, clock: FakeClock, action: str = "auth.logout") -> AuditEmission:
    """What `build()` makes, without a writer: the WAL cap below needs the frame sizes first."""
    return AuditEmission(
        record_id=uuid.uuid4(),
        action=action,
        actor_label=label,
        event_ts=clock(),
    )


async def _writer_over_a_full_wal(
    repo: _ObservedRepository, path: Path, labels: str
) -> tuple[AuditWriter, list[AuditEmission]]:
    """A started writer over a WAL that holds three records stored in Postgres already but not
    compacted away (a crash before its compaction), capped one byte short of holding a record per
    label, so the last one overflows it. Nothing is pending: no batch is in flight."""
    clock = FakeClock()
    old = AuditWal(path / "audit.wal")
    for i in range(3):
        prefix = old.append(json.loads(_emission(f"old{i}", clock).model_dump_json()))
    old.mark_committed(prefix)
    new = [_emission(label, clock) for label in labels]
    frames = sum(len(encode_frame(json.loads(e.model_dump_json()))) for e in new)
    w = _writer(repo, path, max_wal_bytes=prefix + frames - 1)
    await w.start()
    await w.flush(5)
    return w, new


def _fail_first_compaction(w: AuditWriter, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first `compact()` raises `OSError` before it touches the file; later ones run."""
    real = w._wal.compact
    calls: list[None] = []

    def compact() -> None:
        calls.append(None)
        if len(calls) == 1:
            raise OSError("disk full")
        real()

    monkeypatch.setattr(w._wal, "compact", compact)


async def test_writer_tokens_survive_the_compaction_a_full_wal_runs(tmp_path: Path) -> None:
    """A WAL left with a committed prefix (a crash before its compaction) is compacted by the
    append that would overflow it, while an earlier token still waits for the flusher."""
    repo = _ObservedRepository()
    w, new = await _writer_over_a_full_wal(repo, tmp_path, "ab")
    # Concurrent, so the second append overflows before the flusher reads the first.
    assert list(await asyncio.gather(w.ingest(new[0]), w.ingest(new[1]))) == [1, 2]
    await w.flush(5)
    await w.stop(1)
    ids = [str(e.record_id) for e in new]
    assert w.committed_through() == 2 and [r["record_id"] for r in repo.rows] == ids
    _never_ahead(repo, ids)


async def test_writer_refuses_an_append_to_a_full_wal_while_a_batch_is_in_flight(
    tmp_path: Path,
) -> None:
    """A compaction under a batch the flusher is inserting would move the coordinate its offsets
    are in, so a full WAL refuses the append instead, whatever committed prefix it holds."""
    repo = _ObservedRepository()
    w, new = await _writer_over_a_full_wal(repo, tmp_path, "ab")
    repo.down = True
    assert await w.ingest(new[0]) == 1
    await asyncio.wait_for(repo.attempted.wait(), 5)  # the flusher parks in its insert's retry
    with pytest.raises(AuditUnavailable):
        await w.ingest(new[1])
    assert w._wal.committed_offset() > 0  # the prefix is still there: nothing was compacted
    repo.down = False
    await w.flush(5)
    assert await w.ingest(new[1]) == 2  # the refusal took no token; the commit made room
    await w.flush(5)
    await w.stop(1)
    ids = [str(e.record_id) for e in new]
    assert w.committed_through() == 2 and [r["record_id"] for r in repo.rows] == ids
    _never_ahead(repo, ids)


async def test_writer_a_backlog_from_an_earlier_process_takes_no_token(tmp_path: Path) -> None:
    """Frames an earlier process left in the WAL are stored by `start()`'s replay. They are no
    one's token, so replaying them commits nothing."""
    clock = FakeClock()
    old = AuditWal(tmp_path / "audit.wal")
    backlog = [_emission(f"old{i}", clock) for i in range(2)]
    for e in backlog:
        old.append(json.loads(e.model_dump_json()))  # appended, never committed
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path)
    await w.start()
    await w.flush(5)
    assert [r["record_id"] for r in repo.rows] == [str(e.record_id) for e in backlog]
    assert w.committed_through() == 0
    repo.down = True
    first = w.build("auth.login", actor_label="new")
    assert await w.ingest(first) == 1
    assert w.committed_through() == 0  # Postgres is down: the new record is not stored
    repo.down = False
    await w.flush(5)
    await w.stop(1)
    assert w.committed_through() == 1
    _never_ahead(repo, [str(first.record_id)])


async def test_writer_a_replayed_backlogs_commit_leaves_the_depth_at_this_processs_records(
    tmp_path: Path,
) -> None:
    """`buffer_depth` counts only this process's records: committing a batch of an earlier
    run's frames leaves this process's three uncommitted records in it (#3009 S2a2c paces on it)."""
    clock, old = FakeClock(), AuditWal(tmp_path / "audit.wal")
    backlog = [str(_emission(f"old{i}", clock).record_id) for i in range(10)]
    for i, record_id in enumerate(backlog):
        old.append(
            json.loads(_emission(f"old{i}", clock).model_dump_json()) | {"record_id": record_id}
        )
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, flush_batch_size=10)  # the backlog is one batch
    new = [w.build("auth.logout", actor_label=str(i)) for i in range(3)]
    repo.refuse = {backlog[0]}  # Postgres stalls on the backlog
    await w.start()
    await asyncio.wait_for(repo.attempted.wait(), 5)
    for record in new:
        await w.ingest(record)
    repo.refuse = {str(r.record_id) for r in new}  # the backlog goes in; the new records wait
    await asyncio.wait_for(_attempted(repo, str(new[0].record_id)), 5)
    depth = w.buffer_depth
    repo.refuse.clear()
    await w.flush(5)
    await w.stop(1)

    assert (depth, w.buffer_depth, w.committed_through()) == (3, 0, 3)


async def _attempted(repo: _ObservedRepository, record_id: str) -> None:
    while all(attempt[1] != record_id for attempt in repo.attempts):  # noqa: ASYNC110 - no event
        await asyncio.sleep(0)


async def test_writer_a_restart_that_rereads_confirmed_records_counts_them_once(
    tmp_path: Path,
) -> None:
    """The flusher dies on the second record of a batch, after it confirmed the first. The
    restart reads both again and inserts the first again (a no-op): that one counts once."""
    died = asyncio.Event()

    async def alarm(_reason: str) -> None:
        died.set()

    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, max_insert_attempts=1, on_alarm=alarm)
    await w.start()
    built = [w.build("auth.logout", actor_label=str(i)) for i in range(3)]
    ids = [str(b.record_id) for b in built]
    repo.refuse = {ids[1]}  # Postgres keeps refusing the second record
    # Concurrent, so the flusher reads the three frames as one batch.
    assert list(await asyncio.gather(*(w.ingest(b) for b in built))) == [1, 2, 3]
    await asyncio.wait_for(died.wait(), 5)  # record 1 stored and confirmed, record 2 refused
    assert w.committed_through() == 1
    repo.refuse.clear()
    await w.start()
    await w.flush(5)
    assert (w.committed_through(), w.buffer_depth) == (3, 0)  # record 1 is not counted twice
    last = w.build("auth.logout", actor_label="next")
    assert await w.ingest(last) == 4
    await w.flush(5)
    await w.stop(1)
    assert w.committed_through() == 4
    _never_ahead(repo, [*ids, str(last.record_id)])


async def test_writer_a_failing_commit_compaction_does_not_move_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`compact()` fails after the commit cursor moved: the file keeps its prefix, so positions
    keep their base and the restarted flusher's records get their own tokens."""
    died = asyncio.Event()

    async def alarm(_reason: str) -> None:
        died.set()

    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, flush_batch_size=1, on_alarm=alarm)
    await w.start()
    repo.down = True
    built = [w.build("auth.logout", actor_label=str(i)) for i in range(3)]
    assert [await w.ingest(b) for b in built] == [1, 2, 3]
    _fail_first_compaction(w, monkeypatch)
    repo.down = False
    await asyncio.wait_for(died.wait(), 5)  # the first commit could not compact: the flusher died
    assert w.committed_through() == 1
    await w.start()
    await w.flush(5)
    await w.stop(1)
    assert w.committed_through() == 3
    _never_ahead(repo, [str(b.record_id) for b in built])


async def test_writer_a_failing_emergency_compaction_does_not_move_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compaction a full WAL runs fails: that append is refused, the two earlier tokens stay
    right, and the next append succeeds once the flusher has compacted."""
    repo = _ObservedRepository()
    w, new = await _writer_over_a_full_wal(repo, tmp_path, "abc")
    _fail_first_compaction(w, monkeypatch)
    results = await asyncio.gather(*(w.ingest(e) for e in new), return_exceptions=True)
    assert results[:2] == [1, 2] and isinstance(results[2], AuditUnavailable)
    await w.flush(5)
    assert await w.ingest(new[2]) == 3
    await w.flush(5)
    await w.stop(1)
    assert w.committed_through() == 3
    _never_ahead(repo, [str(e.record_id) for e in new])


async def _ingest_refuses(tmp_path: Path, error: type[Exception], *forms: Any) -> None:
    """Every form is refused with `error`: nothing reaches the WAL and no token is taken."""
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path)
    await w.start()
    for form in forms:
        with pytest.raises(error):
            await w.ingest(form)
    assert (tmp_path / "audit.wal").read_bytes() == b""
    assert await w.ingest(w.build("auth.login", actor_label="ok")) == 1
    await w.flush(5)
    await w.stop(1)
    assert [r["actor_label"] for r in repo.rows] == ["ok"]


async def test_writer_ingest_refuses_an_unregistered_action_in_either_form(tmp_path: Path) -> None:
    """A model built without `build()` is checked as its JSON form is (the lane's drain turns that
    refusal into a `record_invalid` row)."""
    bad = _emission("x", FakeClock(), "auth.unregistered_action")
    await _ingest_refuses(tmp_path, UnknownAuditAction, bad, json.loads(bad.model_dump_json()))


async def test_writer_ingest_refuses_a_model_that_skipped_its_validation(tmp_path: Path) -> None:
    """`model_construct()` skips validation and `model_validate()` returns such an instance as it
    is: `ingest()` checks its fields again, or a record id that is no UUID would reach the WAL."""
    unchecked = AuditEmission.model_construct(
        record_id="not-a-uuid", action="auth.login", actor_label="x", event_ts=FakeClock()()
    )
    await _ingest_refuses(tmp_path, ValidationError, unchecked)


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


async def test_writer_a_restart_counts_a_dead_batchs_confirmed_records_in_its_depth(
    tmp_path: Path,
) -> None:
    """The flusher dies on the third record of a four-record batch, after it confirmed two: the
    restart reads all four again from the unmoved cursor, so `buffer_depth` counts four, then
    none once the batch commits."""
    died = asyncio.Event()

    async def alarm(_reason: str) -> None:
        died.set()

    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, flush_batch_size=4, max_insert_attempts=1, on_alarm=alarm)
    await w.start()
    built = [w.build("auth.logout", actor_label=str(i)) for i in range(4)]
    repo.refuse = {str(built[2].record_id)}
    await asyncio.gather(*(w.ingest(b) for b in built))  # one batch
    await asyncio.wait_for(died.wait(), 5)
    repo.refuse.clear()
    await w.start()
    depth = w.buffer_depth
    await w.flush(5)
    await w.stop(1)

    assert (depth, w.buffer_depth, w.committed_through()) == (4, 0, 4)


async def test_writer_a_commit_takes_only_its_own_records_out_of_the_depth(tmp_path: Path) -> None:
    """Each cursor commit takes out of `buffer_depth` only the records confirmed since the last
    one: after a first batch commits, a second batch's commit leaves the third record counted."""
    repo = _ObservedRepository()
    w = _writer(repo, tmp_path, flush_batch_size=1)
    await w.start()
    built = [w.build("auth.logout", actor_label=str(i)) for i in range(3)]
    await w.ingest(built[0])
    await w.flush(5)  # the first batch commits
    repo.refuse = {str(built[1].record_id), str(built[2].record_id)}
    for record in built[1:]:
        await w.ingest(record)
    repo.refuse = {str(built[2].record_id)}  # the second goes in and commits; the third waits
    await asyncio.wait_for(_attempted(repo, str(built[2].record_id)), 5)
    depth = w.buffer_depth
    repo.refuse.clear()
    await w.flush(5)
    await w.stop(1)

    assert (depth, w.buffer_depth) == (1, 0)
