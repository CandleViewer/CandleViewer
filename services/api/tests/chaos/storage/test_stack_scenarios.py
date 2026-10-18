"""Chaos scenarios 1, 2 and 3b against the real compose stack (E07-Q04, C-13.6).

Run by the CI `integration` job's chaos step (`-m "chaos and integration"`),
which brings up postgres + questdb and a fixed-size loopback image. Each test
is arrange -> inject -> assert(data, signals, health) -> recover ->
assert(recovery), restarting any stopped service in `finally`.

Every scenario starts from a healthy stack (`_stack_healthy`) and restarts what it
stops with `st.stopped`, which waits until the service answers and re-issues
`compose start` if it did nothing (GH-3087).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from candleviewer.audit.redact import redact
from candleviewer.health_wiring import PgSystemEventWriter, register_real_probes
from candleviewer.observability.health_probes import ComponentState, HealthRegistry
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.retention.policy import RetentionPolicy, load_defaults
from candleviewer.storage.retention.ports import Partition
from candleviewer.storage.retention.reaper import Reaper
from tests.chaos.storage import _stack as st
from tests.chaos.storage._harness import Rig, chaos_table
from tests.unit.storage.cold._helpers import FakeHotSource, day_range
from tests.unit.storage.retention.test_reaper import NOW, Env, part

pytestmark = [pytest.mark.chaos, pytest.mark.integration]


@pytest.fixture
async def pg() -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(st.pg_dsn(), "chaos")
    try:
        yield repo
    finally:
        await repo.dispose()


@pytest.fixture(autouse=True)
async def _stack_healthy() -> None:
    """No scenario starts while Postgres or QuestDB is down.

    A predecessor that died without restarting what it stopped is healed here (with a warning)
    or fails loudly, instead of cascading into the next scenario as a refused connection."""
    await st.ensure_up("postgres", st.pg_up)
    await st.ensure_up("questdb", st.qdb_up)


def _registry(pg: SqlAlchemyRelationalRepository, disk_path: Path) -> HealthRegistry:
    reg = HealthRegistry(events=PgSystemEventWriter(pg, redact_details=redact))
    register_real_probes(
        reg,
        pg_repo=pg,
        questdb_host=st.HOST,
        questdb_port=st.QDB_PG_PORT,
        parquet_root=str(disk_path),
        disk_path=str(disk_path),
    )
    return reg


async def _state(reg: HealthRegistry, name: str) -> ComponentState:
    snap = await reg.refresh()
    return next(c.state for c in snap.components if c.name == name)


async def _events_since(
    pg: SqlAlchemyRelationalRepository, since: datetime, probe: str
) -> list[str]:
    async with pg.unit_of_work() as uow:
        rows = await uow.session.execute(
            text(
                "SELECT kind || ':' || (details->>'from') || '->' || (details->>'to') "
                "FROM system_events WHERE event_ts >= :since AND details->>'probe' = :p "
                "ORDER BY id"
            ),
            {"since": since, "p": probe},
        )
        return [str(r[0]) for r in rows]


async def _qdb_count(symbol: str) -> int:
    conn = await st.qdb_connect()
    try:
        return int(await conn.fetchval("SELECT count() FROM trades WHERE symbol = $1", symbol))
    finally:
        await conn.close()


def _trades(symbol: str, start: int, n: int) -> list[dict[str, object]]:
    base = 1_760_000_000_000_000
    return [
        {"ts": base + i, "symbol": symbol, "side": "buy", "price": 65000.5, "size": 0.01,
         "notional": 650.005, "trade_id": f"t{i}"}
        for i in range(start, start + n)
    ]  # fmt: skip


async def test_s1_questdb_down_mid_ingest_backpressure_and_exactly_once(
    pg: SqlAlchemyRelationalRepository, tmp_path: Path
) -> None:
    conn = await st.qdb_connect()
    try:
        await run_migrations(_Exec(conn), st.QDB_DDL)
    finally:
        await conn.close()
    sym, bound = f"CH{uuid.uuid4().hex[:8].upper()}", 1_000
    writer = IlpWriter(st.TcpIlpTransport(), ALL_SCHEMAS, max_queue_rows=bound, flush_rows=200)
    reg = _registry(pg, tmp_path)
    await writer.start()
    await writer.write_rows("trades", _trades(sym, 0, 500), "ts")
    await writer.flush("trades")
    await st.until(lambda: _count_is(sym, 500), "arrange: baseline rows visible")
    await st.until(lambda: _is(reg, "questdb", ComponentState.HEALTHY), "arrange: questdb ok")
    since = datetime.now(UTC)
    accepted = 0
    max_depth = 0

    async def produce() -> None:
        nonlocal accepted
        for start in range(500, 2_500, 100):
            with contextlib.suppress(StorageTierUnavailable):  # rows stay buffered
                await writer.write_rows("trades", _trades(sym, start, 100), "ts")
            accepted += 100

    producer: asyncio.Task[None] | None = None
    try:
        async with st.stopped("questdb", st.qdb_up):
            await st.until(lambda: _is(reg, "questdb", ComponentState.DOWN), "health: questdb down")
            assert await _state(reg, "postgres") is ComponentState.HEALTHY, "degraded, not fatal"
            producer = asyncio.create_task(produce())

            async def stalled() -> bool:
                nonlocal max_depth
                max_depth = max(max_depth, writer.queue_depth("trades"))
                return writer.write_errors_total >= 1 and not producer.done()

            await st.until(stalled, "signal: write error recorded and producer backpressured")
            assert writer.queue_depth("trades") <= bound, "INVARIANT: buffer bounded (C-2.18)"
            assert accepted < 2_000, "backpressure: producer cannot run ahead of QuestDB"
        await st.until(st.qdb_up, "recovery: questdb accepting connections", 120)
        await asyncio.wait_for(producer, timeout=120)
        assert max_depth <= bound
        await writer.stop()
        try:
            await st.until(lambda: _count_is(sym, 2_500), "recovery: exactly 2500 rows", 120)
        except AssertionError as exc:
            seen = await _qdb_count(sym)
            raise AssertionError(
                f"{exc}; observed {seen} rows, writer.rows_written_total="
                f"{writer.rows_written_total}, accepted={accepted}"
            ) from exc
        await st.until(lambda: _is(reg, "questdb", ComponentState.HEALTHY), "health: recovered")
        events = await _events_since(pg, since, "questdb")
        assert "health_degraded:healthy->down" in events, events
        assert "health_recovered:down->healthy" in events, events
    finally:
        if producer is not None and not producer.done():
            producer.cancel()
        with contextlib.suppress(Exception):
            await writer.stop()


class _Exec:
    def __init__(self, conn: object) -> None:
        self._c = conn

    async def execute(self, sql: str, *args: object) -> None:
        await self._c.execute(sql, *args)  # type: ignore[attr-defined]  # asyncpg.Connection

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        return [dict(r) for r in await self._c.fetch(sql, *args)]  # type: ignore[attr-defined]


async def _is(reg: HealthRegistry, name: str, want: ComponentState) -> bool:
    return await _state(reg, name) is want


async def _count_is(sym: str, n: int) -> bool:
    with contextlib.suppress(Exception):
        return await _qdb_count(sym) == n
    return False


async def _insert_event(pg: SqlAlchemyRelationalRepository, marker: str) -> None:
    async with pg.unit_of_work() as uow:
        await uow.session.execute(
            text(
                "INSERT INTO system_events (component, kind, severity, message) "
                "VALUES ('db', 'chaos_probe', 'info', :m)"
            ),
            {"m": marker},
        )
        await uow.commit()


async def _marker_rows(pg: SqlAlchemyRelationalRepository, marker: str) -> int:
    async with pg.unit_of_work() as uow:
        res = await uow.session.execute(
            text("SELECT count(*) FROM system_events WHERE message = :m"), {"m": marker}
        )
        return int(res.scalar_one())


async def test_s2_postgres_down_fails_readiness_no_partial_write_and_records_events(
    pg: SqlAlchemyRelationalRepository, tmp_path: Path
) -> None:
    reg = _registry(pg, tmp_path)
    await st.until(lambda: _is(reg, "postgres", ComponentState.HEALTHY), "arrange: postgres ok")
    since = datetime.now(UTC)
    lost = f"chaos-s2-inflight-{uuid.uuid4().hex}"
    after = f"chaos-s2-after-{uuid.uuid4().hex}"
    async with st.stopped("postgres", st.pg_up):
        await st.until(lambda: _is(reg, "postgres", ComponentState.DOWN), "readiness: pg down")
        snap = reg.snapshot()
        assert snap is not None and snap.overall is ComponentState.DOWN, "fails loudly"
        with pytest.raises(Exception):  # noqa: B017 - any driver error; never success
            await asyncio.wait_for(_insert_event(pg, lost), timeout=30)
    await st.until(lambda: _is(reg, "postgres", ComponentState.HEALTHY), "recovery", 120)
    await _insert_event(pg, after)  # UoW transactions resume
    assert await _marker_rows(pg, after) == 1
    assert await _marker_rows(pg, lost) == 0, "INVARIANT: no partial write survived"
    events = await _events_since(pg, since, "postgres")
    # The down-edge cannot be persisted while Postgres itself is down; the
    # recovery row carries both transitions (from=down, to=healthy).
    assert "health_recovered:down->healthy" in events, events


class _DiskEnv(Env):
    def __init__(self, mount: Path) -> None:
        super().__init__([])
        self.mount = mount
        self.auto = {"AUTO1", "PINNED1"}
        self.pinned = {"PINNED1"}

    def free_pct(self) -> float:
        u = shutil.disk_usage(self.mount)
        return 100.0 * u.free / u.total


def _assert_loopback_image(mount: Path) -> None:
    """Harness guard (#275): only ever fill the dedicated loopback image."""
    assert mount.is_mount(), f"{mount} is not a mount point; refusing to fill it"
    total = shutil.disk_usage(mount).total
    assert total <= st.LOOP_MAX_BYTES, f"{mount} is {total} bytes; not the chaos loopback image"


async def test_s3b_disk_full_on_loopback_cold_root_trading_path_unaffected(
    pg: SqlAlchemyRelationalRepository,
) -> None:
    mount = st.LOOP_DIR
    _assert_loopback_image(mount)
    ballast = mount / f"ballast-{uuid.uuid4().hex}.bin"
    cold = mount / f"cold-{uuid.uuid4().hex}"
    marker = f"chaos-s3b-{uuid.uuid4().hex}"
    reg = _registry(pg, mount)
    env = _DiskEnv(mount)
    try:
        await asyncio.to_thread(_fill, ballast)
        assert env.free_pct() < 5.0, "arrange: loopback image <5% free"
        paused = await Reaper(
            RetentionPolicy([], load_defaults()), env, env, env, env, env, env,
            volume="chaos-cold",
        ).guard()  # fmt: skip
        assert paused and env.events[0][0] == "CRITICAL", "signal: critical event first"
        assert env.paused == ["AUTO1"], "non-pinned auto symbols paused; pinned untouched"
        disk_state = await _state(reg, "disk")
        assert disk_state in (ComponentState.WARNING, ComponentState.DOWN), "health: disk flagged"
        rig = Rig(cold, FakeHotSource(chaos_table(5_000)))
        with pytest.raises(OSError):  # loud failure, never a silent partial file
            await rig.exporter().export_partition("BTCUSDT", StreamKind.TRADES, day_range())
        assert rig.entries() == [], "INVARIANT: no manifest entry for a failed export"
        await _insert_event(pg, marker)  # SR-096: trading path (Postgres) still writes
        assert await _marker_rows(pg, marker) == 1
    finally:
        ballast.unlink(missing_ok=True)
        await asyncio.to_thread(shutil.rmtree, cold, True)
    assert env.free_pct() > 50.0, "recovery: self-cleaning"


def _fill(path: Path) -> None:
    """Fill to ENOSPC: 1 MiB chunks, then 4 KiB chunks for the last partial MiB."""
    with path.open("wb", buffering=0) as f:
        for size in (1 << 20, 1 << 12):
            chunk = bytes(size)
            try:
                while True:
                    f.write(chunk)
            except OSError:
                pass  # ENOSPC at this granularity
        with contextlib.suppress(OSError):
            os.fsync(f.fileno())


async def test_s8_two_reapers_on_real_postgres_advisory_lock_one_drop_one_audit() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from candleviewer.storage.retention.locks import PgAdvisoryRunLock

    eng_a, eng_b = create_async_engine(st.pg_dsn()), create_async_engine(st.pg_dsn())
    env = Env([part("A", 40)])
    gate = asyncio.Event()
    orig = env.drop

    async def slow_drop(p: Partition) -> None:
        await gate.wait()  # hold the lock until the rival has tried and lost
        await orig(p)

    env.drop = slow_drop  # type: ignore[method-assign]

    def mk(engine: object) -> Reaper:
        return Reaper(
            RetentionPolicy([], load_defaults()), env, env, env, env, env, env,
            clock=lambda: NOW, volume=f"chaos-{id(env)}", lock=PgAdvisoryRunLock(engine),  # type: ignore[arg-type]
        )  # fmt: skip

    try:
        first = asyncio.create_task(mk(eng_a).run())
        await st.until(lambda: _drop_pending(env), "first reaper inside the lock")
        second = await asyncio.wait_for(mk(eng_b).run(), timeout=30)
        assert second.items == [], "rival instance locked out by pg_try_advisory_lock"
        gate.set()
        await asyncio.wait_for(first, timeout=30)
        assert len([e for e in env.log if e.startswith("drop:")]) == 1
        assert len([a for a in env.audits if a[0] == "retention.purge"]) == 1
        third = await asyncio.wait_for(mk(eng_b).run(), timeout=30)  # lock released
        assert third.to_drop == [] and len(env.audits) >= 1
    finally:
        gate.set()
        await eng_a.dispose()
        await eng_b.dispose()


async def _drop_pending(env: Env) -> bool:
    return any(a[0] == "retention.dry_run" for a in env.audits)
