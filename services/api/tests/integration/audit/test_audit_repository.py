"""Integration: `0003_audit_log` + `SqlAlchemyAuditRepository` against real
Postgres 16 (testcontainers). Covers the DB-side AC: trigger-computed chain
with 64-zero genesis, Python verifier agreeing byte-for-byte with the
trigger, out-of-band tamper located, cv_app refused UPDATE/DELETE,
round-trip upgrade/downgrade/upgrade, checkpoint idempotency, and ids drawn
under the chain lock on every insert path (`0045_audit_chain_hardening`), an
id the caller names replaced.

Not run locally (no docker); exercised by the `migrations`/integration CI jobs.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.models import VerifyResult
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import (
    SqlAlchemyAuditRepository,
    insert_audit_row_locked,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    sqlstate_of,
)
from tests.integration._refused import assert_no_row_values, server_text

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        yield dsn


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
    )


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


async def _emit_n(dsn: str, n: int, wal: Path) -> None:
    """Engine is built inside the running loop and disposed before it closes
    (never shared across `asyncio.run` calls — asyncpg futures are
    loop-bound; that was the `different loop` CI failure)."""
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(wal))
        await writer.start()
        for i in range(n):
            await writer.emit(
                "orders.submit",
                actor_label="bot",
                actor_ip="10.0.0.7",
                object_id=str(i),
                before_state={"qty": "0.01", "password_hash": "x"} if i % 2 else None,
            )
        await writer.flush(60)
        await writer.stop(5)
    finally:
        await relational.dispose()


async def _verify(dsn: str) -> VerifyResult:
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        return await AuditQueryService(SqlAlchemyAuditRepository(relational)).verify()
    finally:
        await relational.dispose()


def test_trigger_chain_genesis_and_python_verifier_agree(pg_dsn: str, tmp_path: Path) -> None:
    asyncio.run(_emit_n(pg_dsn, 1000, tmp_path / "a.wal"))
    with psycopg.connect(_sync(pg_dsn)) as conn:
        first = conn.execute("SELECT prev_hash FROM audit_log ORDER BY id LIMIT 1").fetchone()
        assert first is not None and first[0] == "0" * 64
        leak = conn.execute(
            "SELECT count(*) FROM audit_log WHERE before_state::text LIKE '%\"x\"%'"
        )
        assert leak.fetchone() == (0,)
    result = asyncio.run(_verify(pg_dsn))
    assert result.verified and result.entries_checked >= 1000


def test_superuser_tamper_is_located(pg_dsn: str, tmp_path: Path) -> None:
    asyncio.run(_emit_n(pg_dsn, 5, tmp_path / "b.wal"))
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        # The third of the five by position: ids are not consecutive (0045).
        third = conn.execute("SELECT id FROM audit_log ORDER BY id DESC OFFSET 2 LIMIT 1")
        victim = third.fetchone()
        assert victim is not None
        conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_append")
        conn.execute("UPDATE audit_log SET reason = 'forged' WHERE id = %s", (victim[0],))
        conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append")
    result = asyncio.run(_verify(pg_dsn))
    assert not result.verified and result.first_bad_id == victim[0]


def test_truncate_refused_even_for_owner(pg_dsn: str) -> None:
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("TRUNCATE audit_log")


def test_app_role_cannot_update_or_delete(pg_dsn: str) -> None:
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        conn.execute("CREATE ROLE cv_app_t LOGIN PASSWORD 'test-only'")
        conn.execute("GRANT SELECT, INSERT ON audit_log TO cv_app_t")
        conn.execute("SET ROLE cv_app_t")
        for stmt in ("UPDATE audit_log SET reason = 'x'", "DELETE FROM audit_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)


def test_migration_downgrade_refused_while_audit_history_exists(
    pg_dsn: str, tmp_path: Path
) -> None:
    asyncio.run(_emit_n(pg_dsn, 1, tmp_path / "c.wal"))
    with pytest.raises(subprocess.CalledProcessError):
        _alembic(pg_dsn, "downgrade", "0002_rbac_seed")


def test_migration_round_trip_on_empty_db() -> None:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        _alembic(dsn, "downgrade", "0002_rbac_seed")
        _alembic(dsn, "upgrade", "head")


_PREV, _REV = "0044_account_no_hard_delete", "0045_audit_chain_hardening"
_STEPS = (("upgrade", _PREV), ("upgrade", _REV), ("downgrade", _PREV), ("upgrade", _REV))
_FUNCTION = "SELECT prosrc FROM pg_proc WHERE proname = 'audit_chain'"


def test_the_chain_hardening_revision_round_trips_on_a_seeded_chain(tmp_path: Path) -> None:
    """C-5.2, C-5.5: rows go in at 0044, at 0045, back at 0044 and at 0045 again. The downgrade
    restores 0003's `audit_chain()` body exactly and the upgrade the one that draws the id under
    the lock; the chain across all four steps verifies (the id is not hashed). The search_path
    each step leaves: `test_audit_chain_hardening_migration.py`."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        texts: list[str] = []
        for step in _STEPS:
            _alembic(dsn, *step)
            asyncio.run(_emit_n(dsn, 2, tmp_path / f"{len(texts)}.wal"))
            with psycopg.connect(_sync(dsn)) as conn:
                [(text,)] = conn.execute(_FUNCTION).fetchall()
            texts.append(text)
        assert texts[0] == texts[2] != texts[1] == texts[3]
        assert "NEW.id := nextval('audit_log_id_seq');" in texts[1]
        result = asyncio.run(_verify(dsn))
        assert result.verified and result.entries_checked == 8


_T0 = datetime(2026, 10, 18, tzinfo=UTC)
Insert = Callable[[SqlAlchemyRelationalRepository, dict[str, Any]], Awaitable[None]]
_WAITING = "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('audit_log'))"
_HOLDER_ROW = (
    "INSERT INTO audit_log (record_id, actor_label, action) VALUES (%s, 'h', 'auth.login')"
)


def _record(label: str) -> dict[str, Any]:
    return {
        "record_id": str(uuid.uuid4()), "actor_label": label, "action": "auth.login",
        "outcome": "success", "severity": "info", "event_ts": _T0.isoformat(),
    }  # fmt: skip


async def _locked(relational: SqlAlchemyRelationalRepository, record: dict[str, Any]) -> None:
    async with relational.unit_of_work() as uow:
        assert await insert_audit_row_locked(uow.session, record)
        await uow.commit()


async def _unlocked(relational: SqlAlchemyRelationalRepository, record: dict[str, Any]) -> None:
    """An INSERT locked only by its trigger: the column default draws an id before the lock, which
    `audit_chain()` replaces with one drawn under it (0045)."""
    insert = "INSERT INTO audit_log (record_id, actor_label, action) VALUES (:r, 'w', 'auth.login')"
    async with relational.unit_of_work() as uow:
        await uow.session.execute(sa.text(insert), {"r": uuid.UUID(record["record_id"])})
        await uow.commit()


async def _until_waiting(conn: psycopg.AsyncConnection[Any]) -> None:
    """Until an INSERT waits for the chain lock; bounded, so a missed wait fails fast."""
    async with asyncio.timeout(30):
        while not await (await conn.execute(_WAITING)).fetchall():
            pass


async def _race(dsn: str, insert: Insert) -> tuple[int, int, VerifyResult]:
    """`insert` waits while another connection holds the chain lock; the holder then commits a
    row of its own. Returns the waiter's id, the holder's id and verify over the two."""
    relational = SqlAlchemyRelationalRepository(dsn)
    query = AuditQueryService(SqlAlchemyAuditRepository(relational))
    waiter, holder = _record("waiter"), _record("holder")
    try:
        async with await psycopg.AsyncConnection.connect(_sync(dsn)) as conn:
            await conn.execute(_LOCK_SQL)
            task = asyncio.ensure_future(insert(relational, waiter))
            await _until_waiting(conn)
            await conn.execute(_HOLDER_ROW, (holder["record_id"],))
            await conn.commit()  # releases the chain lock
            await task
            ids = "SELECT id FROM audit_log WHERE record_id = %s"
            [(w,)] = await (await conn.execute(ids, (waiter["record_id"],))).fetchall()
            [(h,)] = await (await conn.execute(ids, (holder["record_id"],))).fetchall()
        return w, h, await query.verify(from_id=min(w, h), to_id=max(w, h))
    finally:
        query.close()
        await relational.dispose()


async def test_an_insert_without_the_explicit_lock_keeps_the_chain(pg_dsn: str) -> None:
    """The waiter's default drew an id before the holder's row; before 0045 the waiter kept it and
    hashed the later row as its predecessor, a break verify named. Its id is now drawn under the
    lock, after the holder's."""
    waiter, holder, result = await _race(pg_dsn, _unlocked)
    assert holder < waiter and result.verified and result.entries_checked == 2


async def test_the_lock_first_helper_keeps_the_chain_under_the_same_schedule(pg_dsn: str) -> None:
    waiter, holder, result = await _race(pg_dsn, _locked)
    assert holder < waiter and result.verified and result.entries_checked == 2


_ROUNDS = 500  # two inserts a round: AC-ADM-16's 1,000
_RAW_ROW = "INSERT INTO audit_log (record_id, actor_label, action) VALUES (%s, 'raw', 'auth.login')"
_ORDER = "SELECT id, record_id::text FROM audit_log WHERE record_id = ANY(%s::uuid[]) ORDER BY id"
_CACHE = "SELECT cache_size FROM pg_sequences WHERE sequencename = 'audit_log_id_seq'"


async def test_two_connection_inserts_link_in_id_order(pg_dsn: str) -> None:
    """AC-ADM-16, SR-E42-10: two connections append 1,000 rows, one through the app's lock-first
    path, one by a raw INSERT that meets the lock only in the trigger; they take turns holding the
    chain lock while the other's INSERT waits behind it. A waiting raw INSERT's default has drawn
    an id before the holder's row exists, the schedule that linked out of id order before 0045.
    Ids now follow lock order, and the chain verifies in id order."""
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    query = AuditQueryService(SqlAlchemyAuditRepository(relational))
    order: list[str] = []  # record ids, in the order their rows took the chain lock
    try:
        async with (
            await psycopg.AsyncConnection.connect(_sync(pg_dsn)) as raw,
            await psycopg.AsyncConnection.connect(_sync(pg_dsn), autocommit=True) as watch,
        ):
            # A cached sequence would hand each session its own block of ids (0045).
            assert await (await watch.execute(_CACHE)).fetchall() == [(1,)]
            for i in range(_ROUNDS):
                app, raw_id = _record("app"), str(uuid.uuid4())
                if i % 2 == 0:  # the app path holds the lock; the raw INSERT waits behind it
                    async with relational.unit_of_work() as uow:
                        await uow.session.execute(sa.text(_LOCK_SQL))
                        waiting = asyncio.ensure_future(raw.execute(_RAW_ROW, (raw_id,)))
                        await _until_waiting(watch)
                        assert await insert_audit_row_locked(uow.session, app)
                        await uow.commit()
                    await waiting
                    await raw.commit()
                    order += [app["record_id"], raw_id]
                else:  # the raw INSERT holds the lock; the app path waits behind it
                    await raw.execute(_RAW_ROW, (raw_id,))
                    queued = asyncio.ensure_future(_locked(relational, app))
                    await _until_waiting(watch)
                    await raw.commit()
                    await queued
                    order += [raw_id, app["record_id"]]
            rows = await (await watch.execute(_ORDER, (order,))).fetchall()
        assert [record for _, record in rows] == order  # every holder's id below its waiter's
        result = await query.verify(from_id=rows[0][0])
        assert result.verified and result.entries_checked == 2 * _ROUNDS
    finally:
        query.close()
        await relational.dispose()


_NAMED = 2**62  # no sequence here reaches it: the INSERT names it, the trigger replaces it
_NAMED_ROW = (
    "INSERT INTO audit_log (id, record_id, actor_label, action) "
    "VALUES (%s, %s, 'named', 'auth.login') RETURNING id"
)


async def test_the_trigger_replaces_an_id_the_caller_supplies(pg_dsn: str) -> None:
    """SR-E42-10: an INSERT that names its own id (another tool, a migration, a manual insert)
    cannot place its row anywhere but after the head: `audit_chain()` replaces the id with one
    drawn under the lock. The row the app appends next links to it in id order, and verify passes;
    before 0045 the named row kept 2**62 and the next row, drawing a lower id, linked to it out of
    id order."""
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyAuditRepository(relational)
    query = AuditQueryService(repo)
    try:
        head = await repo.read_head()
        head_id = 0 if head is None else head[0]
        async with await psycopg.AsyncConnection.connect(_sync(pg_dsn), autocommit=True) as conn:
            named = await conn.execute(_NAMED_ROW, (_NAMED, str(uuid.uuid4())))
            [(returned,)] = await named.fetchall()
        await _locked(relational, _record("after"))
        assert head_id < returned < _NAMED
        result = await query.verify(from_id=head_id + 1)
        assert result.verified and result.entries_checked == 2
    finally:
        query.close()
        await relational.dispose()


async def test_wal_path_and_in_transaction_inserts_interleave_into_one_verified_chain(
    pg_dsn: str,
) -> None:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyAuditRepository(relational)
    query = AuditQueryService(repo)
    try:
        head = await repo.read_head()
        records = [_record(f"r{i}") for i in range(40)]
        await asyncio.gather(
            *(repo.insert(r) for r in records[::2]),  # the WAL flusher's path
            *(_locked(relational, r) for r in records[1::2]),
        )
        result = await query.verify(from_id=1 if head is None else head[0] + 1)
        assert result.verified and result.entries_checked == 40
    finally:
        query.close()
        await relational.dispose()


# What a record `au_action_fmt` refuses carries (P1/P2 values, planted by name: #2748, C-12.6).
_ACTION, _ACTOR, _IP, _NOTE = "Bad Action", "secret-actor-label", "198.51.100.23", "SECRET-NOTE"


async def test_a_refused_audit_insert_leaves_without_the_records_values(pg_dsn: str) -> None:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    refused = _record(_ACTOR) | {"action": _ACTION, "actor_ip": _IP, "before_state": {"n": _NOTE}}
    try:
        with server_text(relational) as seen, pytest.raises(sa.exc.IntegrityError) as err:
            await SqlAlchemyAuditRepository(relational).insert(refused)
        assert (sqlstate_of(err.value), constraint_of(err.value)) == ("23514", "au_action_fmt")
        assert_no_row_values(err.value, seen, _ACTION, _ACTOR, _IP, _NOTE)
    finally:
        await relational.dispose()
