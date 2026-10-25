"""Integration, #913 slice 3 L2 (ruling Q12): the serving loop's audit writer and the order lane's
own append to one `audit_log` at the same time, each on its own event loop with its own pool and
its own WAL file, and the table holds ONE hash chain: no fork, no gap, every record once. The
lane's writer is built as the runtime builds it (`admin.wiring.build_lane_audit_writer` over an
audit repository on a pool of the lane's, exclusive, at `oms_wiring.lane_audit_wal`), on an
`OrderLane`'s loop, where it runs and stops. Each round holds the chain lock from a third session
(`pg_advisory_lock(hashtext('audit_log'))`, the key `insert_audit_row_locked` and `audit_chain()`
take per transaction) while both writers append a burst, waits until each writer's flusher is
queued on that lock inside its insert, then lets go, so the two flushers' inserts contend for it.
The chain is checked by the repo's own verifier (`AuditQueryService.verify`) and the stored links,
as #4350's two-writer case is. Real Postgres 16 via testcontainers (needs Docker); CI's
`integration` job runs it."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import psycopg
import pytest

from candleviewer.admin.wiring import build_lane_audit_writer
from candleviewer.audit.models import VerifyResult
from candleviewer.audit.wal import AuditWalLocked
from candleviewer.audit.writer import AuditWriter, AuditWriterWrongLoop
from candleviewer.oms_lane import OrderLane
from candleviewer.oms_wiring import lane_audit_wal
from candleviewer.settings import Settings
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.audit.test_two_writers_one_chain import (
    _assert_one_chain,
    _burst,
    _rows,
    _switches,
    _verify,
    pg_dsn,
)

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]

_ROUNDS = 6
_PER_ROUND = 15
#: The chain lock, taken and given back by a third session, on the key the writers take.
_HOLD = "SELECT pg_advisory_lock(hashtext('audit_log'))"
_LET_GO = "SELECT pg_advisory_unlock(hashtext('audit_log'))"
_WAITING = "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
#: A bound on each wait of the test (both flushers queued, a flush), never a time it expects.
_BOUND_S = 60.0


def _queued(watch: psycopg.Connection, waiters: int) -> bool:
    """Whether `waiters` transactions come to wait for an advisory lock within `_BOUND_S`: each
    writer's insert, queued on the chain lock the third session holds. `pg_locks` notifies
    nothing, so it is read again every 10 ms, off the loops."""
    deadline = time.monotonic() + _BOUND_S
    while time.monotonic() < deadline:
        row = watch.execute(_WAITING).fetchone()
        if row is not None and int(row[0]) >= waiters:
            return True
        time.sleep(0.01)
    return False


async def _quiet(cause: str) -> None:
    """The runtime's alarm (ruling 4): none fires here, as no append is refused."""
    raise AssertionError(cause)


async def _lane_writer(dsn: str, tmp: Path) -> tuple[AuditWriter, SqlAlchemyRelationalRepository]:
    """The lane's writer as the runtime builds it, on the loop this runs on (the lane's)."""
    relational = SqlAlchemyRelationalRepository(dsn, "oms")
    wal = lane_audit_wal(Settings(audit_wal_path=str(tmp / "audit.wal")))
    try:
        repository = SqlAlchemyAuditRepository(relational)
        writer = build_lane_audit_writer(repository, wal, on_alarm=_quiet)
        await writer.start()
    except BaseException:
        await relational.dispose()
        raise
    return writer, relational


async def _ended(writer: AuditWriter, relational: SqlAlchemyRelationalRepository) -> None:
    try:
        await writer.flush(_BOUND_S)
        await writer.stop(5)
    finally:
        await relational.dispose()


async def _two_loops(dsn: str, tmp: Path) -> tuple[list[str], VerifyResult]:
    """`_ROUNDS` contended rounds of both writers: the ids they emitted, and the verifier's walk
    of the table once both have stopped."""
    served = SqlAlchemyRelationalRepository(dsn)
    serving = AuditWriter(SqlAlchemyAuditRepository(served), str(tmp / "audit.wal"))
    lane = OrderLane()
    await lane.start()
    watch = psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)
    emitted = list[str]()
    try:
        lane_writer, lane_pool = await lane.call(_lane_writer(dsn, tmp))
        try:
            await serving.start()
            with pytest.raises(AuditWriterWrongLoop):  # D6: the lane's writer is the lane's alone
                await lane_writer.emit("auth.logout", actor_label="writer-serving")
            for round_ in range(_ROUNDS):
                ns = range(_PER_ROUND * round_, _PER_ROUND * (round_ + 1))
                await asyncio.to_thread(watch.execute, _HOLD)
                try:
                    bursts = await asyncio.gather(
                        _burst(serving, "s", ns), lane.call(_burst(lane_writer, "l", ns))
                    )
                    emitted += [i for burst in bursts for i in burst]
                    # both flushers wait on the lock, each inside an insert
                    assert await asyncio.to_thread(_queued, watch, 2)
                finally:
                    await asyncio.to_thread(watch.execute, _LET_GO)
                await serving.flush(_BOUND_S)
                await lane.call(lane_writer.flush(_BOUND_S))
        finally:
            await lane.call(_ended(lane_writer, lane_pool))
        await serving.flush(_BOUND_S)
        return emitted, await _verify(SqlAlchemyAuditRepository(served))
    finally:
        watch.close()
        await lane.stop()
        await serving.stop(5)
        await served.dispose()


def test_the_lane_and_serving_writers_on_two_loops_keep_one_unbroken_chain(
    pg_dsn: str, tmp_path: Path
) -> None:
    emitted, result = asyncio.run(_two_loops(pg_dsn, tmp_path))
    rows = _rows(pg_dsn)

    _assert_one_chain(rows, result)
    assert sorted(r[2] for r in rows) == sorted(emitted)
    assert len(rows) == 2 * _ROUNDS * _PER_ROUND
    assert _switches(rows) >= _ROUNDS  # the two writers' contended inserts did interleave
    assert (tmp_path / "oms_lane.audit.wal.lock").exists()  # the lane's own WAL, locked (D6)


def test_a_second_lane_writer_on_the_same_wal_is_refused_while_the_first_holds_it(
    pg_dsn: str, tmp_path: Path
) -> None:
    """D6: two processes' lane writers on one host and settings never share the file: the second
    is refused before it opens it, and builds once the first has stopped."""

    async def twice() -> None:
        first, pool = await _lane_writer(pg_dsn, tmp_path)
        try:
            with pytest.raises(AuditWalLocked):
                await _lane_writer(pg_dsn, tmp_path)
        finally:
            await _ended(first, pool)
        again, pool = await _lane_writer(pg_dsn, tmp_path)
        await _ended(again, pool)

    asyncio.run(twice())
