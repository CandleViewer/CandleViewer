"""Integration, #913 ruling Q12: two `AuditWriter`s, each with its own WAL file, append to one
`audit_log` at the same time and the table still holds ONE hash chain (no fork, no gap, every
`record_id` once); the chain lock (`pg_advisory_xact_lock` in the repository and in
`audit_chain()`) orders their inserts. The second test ends one writer, a child process, with
SIGKILL mid-burst (no `stop()`) at a point the child reported (some records stored, more only in
its WAL), restarts it in this process on the same WAL file, lets it replay while the other keeps
writing (the replay waits for the other's next row once), and checks the chain again. The
chain is checked by the repo's own verifier (`AuditQueryService.verify`) plus the stored links,
never by hashing here.
Real Postgres 16 via testcontainers (needs Docker)."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.models import VerifyResult
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration
_API = Path(__file__).resolve().parents[3]
_GENESIS = "0" * 64
#: Records the child must report accepted (fsync'd in its WAL) before it is ended.
_ACCEPTED_BEFORE_END = 40
#: The child's flusher stores this many records, then holds its next insert until the signal, so
#: the kill point is fixed by the child's reports, not by timing; a held batch's stored part is
#: re-sent by the replay (ON CONFLICT).
_STORED_BEFORE_HOLD = 7
#: B's replay waits for one more row of A before this insert (at most 4 before it are re-sends).
_REPLAY_PAUSE_AT = 5

#: Writer B as a separate process: reads the DSN from stdin, emits until it is ended, prints
#: `accepted <object_id>` once `ingest()` returned (acceptance is durability), 10 ms apart, and
#: `stored <k>` once its k-th insert committed. Inserts wait 50 ms each (pacing only).
_CHILD = """
import asyncio, sys
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

HOLD = int(sys.argv[2])

class Slow:
    def __init__(self, repo):
        self._repo = repo
        self._stored = 0
    async def insert(self, record):
        if self._stored >= HOLD:
            await asyncio.Event().wait()  # held until SIGKILL
        await asyncio.sleep(0.05)
        await self._repo.insert(record)
        self._stored += 1
        print("stored", self._stored, flush=True)

async def main(dsn, wal):
    repo = SqlAlchemyAuditRepository(SqlAlchemyRelationalRepository(dsn))
    writer = AuditWriter(Slow(repo), wal, flush_batch_size=5)
    await writer.start()
    n = 0
    while True:
        record = writer.build("auth.logout", actor_label="writer-b", object_id=f"b-{n}")
        await writer.ingest(record)
        print("accepted", record.object_id, flush=True)
        n += 1
        await asyncio.sleep(0.01)

asyncio.run(main(sys.stdin.readline().strip(), sys.argv[1]))
"""


@pytest.fixture
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_API,
            env={**os.environ, "CV_PG_DSN": dsn.replace("+asyncpg", "+psycopg")},
            check=True,
        )
        yield dsn


def _rows(dsn: str) -> list[tuple[int, str, str, str, str]]:
    sql = "SELECT id, record_id::text, object_id, prev_hash, entry_hash FROM audit_log ORDER BY id"
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql")) as conn:
        return conn.execute(sql).fetchall()


def _assert_one_chain(rows: list[tuple[int, str, str, str, str]], result: VerifyResult) -> None:
    """The verifier walked every row and passed; each stored link names the row before it, so no
    two rows share a predecessor (a fork) and none skips one (a gap); every record is there once."""
    assert rows, "audit_log is empty"
    assert (result.verified, result.first_bad_id) == (True, None), result
    assert result.entries_checked == len(rows)
    assert result.last_hash == rows[-1][4]
    assert [r[3] for r in rows] == [_GENESIS, *[r[4] for r in rows[:-1]]]
    assert len({r[3] for r in rows}) == len(rows)
    assert len({r[1] for r in rows}) == len({r[2] for r in rows}) == len(rows)


def _switches(rows: list[tuple[int, str, str, str, str]]) -> int:
    """How often consecutive rows come from different writers (0 = no interleaving at all)."""
    sides = [r[2][0] for r in rows]
    return sum(a != b for a, b in itertools.pairwise(sides))


async def _burst(writer: AuditWriter, side: str, ns: range) -> list[str]:
    ids = [f"{side}-{n}" for n in ns]
    for object_id in ids:
        await writer.emit("auth.logout", actor_label=f"writer-{side}", object_id=object_id)
        await asyncio.sleep(0)
    return ids


async def _verify(repo: SqlAlchemyAuditRepository) -> VerifyResult:
    service = AuditQueryService(repo)
    try:
        return await service.verify(batch_size=7)
    finally:
        service.close()


async def _interleaved(dsn: str, tmp: Path) -> tuple[list[str], VerifyResult]:
    relational = [SqlAlchemyRelationalRepository(dsn) for _ in "ab"]
    try:
        repos = [SqlAlchemyAuditRepository(r) for r in relational]
        writers = [
            AuditWriter(repo, str(tmp / f"{side}.wal"), flush_batch_size=7)
            for repo, side in zip(repos, "ab", strict=True)
        ]
        for writer in writers:
            await writer.start()
        emitted: list[str] = []
        for round_ in range(4):  # both flushers run while both writers append
            ns = range(25 * round_, 25 * (round_ + 1))
            bursts = await asyncio.gather(
                *(_burst(w, s, ns) for w, s in zip(writers, "ab", strict=True))
            )
            emitted += [i for burst in bursts for i in burst]
        for writer in writers:
            await writer.flush(60)
            await writer.stop(5)
        return emitted, await _verify(repos[0])
    finally:
        for r in relational:
            await r.dispose()


def test_two_writers_with_their_own_wal_keep_one_unbroken_chain(
    pg_dsn: str, tmp_path: Path
) -> None:
    emitted, result = asyncio.run(_interleaved(pg_dsn, tmp_path))
    rows = _rows(pg_dsn)

    _assert_one_chain(rows, result)
    assert sorted(r[2] for r in rows) == sorted(emitted)
    assert len(rows) == 200
    assert _switches(rows) >= 20  # the two writers' inserts did interleave


async def _a_until(writer: AuditWriter, done: asyncio.Event, emitted: list[str]) -> None:
    n = 0
    while not done.is_set():
        emitted += await _burst(writer, "a", range(n, n + 5))
        n += 5
        await asyncio.sleep(0.01)


class _Signalling(SqlAlchemyAuditRepository):
    """A's repository: sets `stored` after each committed insert."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        super().__init__(relational)
        self.stored = asyncio.Event()

    async def insert(self, record: dict[str, Any]) -> None:
        await super().insert(record)
        self.stored.set()


class _PausingReplay(SqlAlchemyAuditRepository):
    """B's repository during its replay: after `_REPLAY_PAUSE_AT` inserts it waits until writer A
    stored one more row, so an A row lands between B's replayed rows (the replay races A)."""

    def __init__(self, relational: SqlAlchemyRelationalRepository, a: _Signalling) -> None:
        super().__init__(relational)
        self._a = a
        self._inserts = 0

    async def insert(self, record: dict[str, Any]) -> None:
        self._inserts += 1
        if self._inserts == _REPLAY_PAUSE_AT:
            self._a.stored.clear()
            await self._a.stored.wait()
        await super().insert(record)


class _Crash(NamedTuple):
    emitted_a: list[str]
    accepted_b: list[str]
    stored_seen: int  # B's stored count the parent had read when it sent the signal
    at_end: int  # B's rows in the table after the signal
    head: int  # greatest id when B restarted
    after: int  # B's rows after the replay
    result: VerifyResult


async def _end_b(child: asyncio.subprocess.Process) -> tuple[list[str], int]:
    """Read B's reports and SIGKILL it once it accepted `_ACCEPTED_BEFORE_END` records and
    stored some but fewer (deterministic: its flusher holds after `_STORED_BEFORE_HOLD`)."""
    assert child.stdout is not None
    accepted: list[str] = []
    stored = 0
    while not (len(accepted) >= _ACCEPTED_BEFORE_END and 0 < stored < len(accepted)):
        line = await child.stdout.readline()
        assert line, "writer B ended before it reached the kill point"
        kind, value = line.decode().split()
        if kind == "accepted":
            accepted.append(value)
        else:
            stored = int(value)
    child.send_signal(signal.SIGKILL)  # mid-burst, no stop(): its WAL keeps the backlog
    await child.wait()
    return accepted, stored


async def _crash_and_replay(dsn: str, tmp: Path) -> _Crash:
    """B (a child process) is ended at its reported kill point, then restarted here on its WAL
    and replays while A keeps writing."""
    relational = [SqlAlchemyRelationalRepository(dsn) for _ in "ab"]
    writer_a: AuditWriter | None = None
    writer_b: AuditWriter | None = None
    child: asyncio.subprocess.Process | None = None
    done = asyncio.Event()
    a_task: asyncio.Task[None] | None = None
    try:
        repo_a = _Signalling(relational[0])
        writer_a = AuditWriter(repo_a, str(tmp / "a.wal"), flush_batch_size=7)
        await writer_a.start()
        wal_b = str(tmp / "b.wal")
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _CHILD, wal_b, str(_STORED_BEFORE_HOLD),
            cwd=_API, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        )  # fmt: skip
        assert child.stdin is not None
        child.stdin.write(dsn.encode() + b"\n")
        await child.stdin.drain()
        child.stdin.close()
        emitted_a: list[str] = []
        a_task = asyncio.create_task(_a_until(writer_a, done, emitted_a))
        async with asyncio.timeout(120):
            accepted_b, stored_seen = await _end_b(child)
            rows = _rows(dsn)
            at_end = sum(1 for r in rows if r[2].startswith("b-"))
            head = rows[-1][0]
            replay = _PausingReplay(relational[1], repo_a)
            writer_b = AuditWriter(replay, wal_b, flush_batch_size=7)
            await writer_b.start()  # replays B's WAL while A still appends
            await writer_b.flush(60)
            done.set()
            await a_task
            for writer in (writer_a, writer_b):
                await writer.flush(60)
                await writer.stop(5)
        after = sum(1 for r in _rows(dsn) if r[2].startswith("b-"))
        result = await _verify(repo_a)
        return _Crash(emitted_a, accepted_b, stored_seen, at_end, head, after, result)
    finally:
        done.set()
        if child is not None and child.returncode is None:
            child.kill()
            await child.wait()
        if a_task is not None and not a_task.done():
            a_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await a_task
        for leftover in (writer_a, writer_b):
            if leftover is not None:
                await leftover.stop(5)  # no-op after the clean stop above
        for r in relational:
            await r.dispose()


def test_a_writer_ended_mid_burst_replays_its_wal_into_the_same_chain(
    pg_dsn: str, tmp_path: Path
) -> None:
    crash = asyncio.run(_crash_and_replay(pg_dsn, tmp_path))
    rows = _rows(pg_dsn)
    stored = [r[2] for r in rows]
    print(  # the kill point, for the run log
        f"KILL accepted={len(crash.accepted_b)} stored_seen={crash.stored_seen} "
        f"at_end={crash.at_end} after={crash.after} rows={len(rows)}"
    )

    # B was ended with some records stored and more only in its WAL
    assert 0 < crash.stored_seen <= crash.at_end <= _STORED_BEFORE_HOLD < len(crash.accepted_b)
    assert crash.after >= len(crash.accepted_b)  # the replay stored every one of them
    _assert_one_chain(rows, crash.result)
    assert set(crash.accepted_b) <= set(stored)
    assert sorted(i for i in stored if i.startswith("a-")) == sorted(crash.emitted_a)
    # The replay raced A: A stored rows after B's restart and before B's last replayed row.
    post = [r for r in rows if r[0] > crash.head]
    last_b = max(r[0] for r in post if r[2].startswith("b-"))
    assert any(r[2].startswith("a-") and r[0] < last_b for r in post)
    assert _switches(post) >= 1
