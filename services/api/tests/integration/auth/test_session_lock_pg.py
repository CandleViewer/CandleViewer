"""Integration: `POST /auth/lock`'s stored lock on real Postgres 16 (#4743, E09-S03-F1).

The lock is one unit of work (`SqlAlchemySessionRepository.lock_session`): the row read `FOR NO KEY
UPDATE`, the `auth.session_locked` record written ahead under that lock, then `locked_at` set. Here
on the real table: the row as the lock leaves it, ten concurrent locks of one session writing one
record, a failing or slow record rolling the lock back, a revoked or expired row never locked,
extend's write refusing a locked row, the unlock clearing it and stamping `unlocked_at`, a refresh
claim racing the lock carrying it to the successor, and the lock surviving a new engine. Needs
Docker (testcontainers); the CI `integration` job runs it.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.errors import SessionIdleLocked, SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionService
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
_IDLE_S = 900
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")
#: Opaque strings the fakes hash: test-only literals, never a credential.
_OPAQUE = "lock-pg-opaque-4743"


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW + timedelta(seconds=60)  # inside the idle timeout: unlocked by the clock

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
            timeout=120,
        )
        yield dsn


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield relational
    finally:
        await relational.dispose()


def _repo(rel: SqlAlchemyRelationalRepository) -> SqlAlchemySessionRepository:
    return SqlAlchemySessionRepository(rel, lambda **fields: SessionRecord.model_validate(fields))


async def _live(pg_dsn: str, repo: SqlAlchemySessionRepository) -> SessionRecord:
    """A live session row of a fresh user, last seen at `_NOW`."""
    user = await seed(pg_dsn, f"lock-{uuid.uuid4().hex[:12]}", "correct horse battery")
    assert user is not None
    record = SessionRecord(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user),
        refresh_token_hash=hashlib.sha256(f"{_OPAQUE}-{uuid.uuid4()}".encode()).hexdigest(),
        access_token_jti=uuid.uuid4(),
        issued_at=_NOW,
        last_seen_at=_NOW,
        expires_at=_NOW + timedelta(hours=12),
        revoked_at=None,
        revoked_reason=None,
        ip=None,
        user_agent=None,
        device_label=None,
        is_electron=False,
        mfa_satisfied_at=_NOW,
        idle_timeout_s=_IDLE_S,
    )
    assert await repo.create_session(record) is not None
    return record


class _Ahead:
    """The lock's write-ahead record: the rows it was called with."""

    def __init__(self) -> None:
        self.rows: list[SessionRecord] = []

    async def __call__(self, row: SessionRecord) -> None:
        self.rows.append(row)


async def _until_blocked(probe: AsyncConnection, backends: int) -> None:
    """Bounded condition wait: *backends* queued on a lock (pg_locks is never cached)."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= backends:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{backends} backends never queued behind the lock's row lock")


async def test_lock_session_sets_locked_at_and_leaves_last_seen_at_on_postgres(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    repo, clock = _repo(rel), _Clock()
    record = await _live(pg_dsn, repo)
    ahead = _Ahead()

    locked, locked_now = await SessionService(repo, Hasher(), clock=clock).lock(
        str(record.id), write_ahead=ahead, audit_timeout_s=2.0
    )

    assert locked_now and [row.locked_at for row in ahead.rows] == [None]
    stored = await repo.find_by_id(str(record.id))
    assert stored is not None and stored.locked_at == locked.locked_at == clock.now
    assert (stored.last_seen_at, stored.unlocked_at, stored.user_status) == (_NOW, None, "active")
    assert locked.user_status == "active" and stored.is_idle_locked(now=clock.now)


async def test_concurrent_locks_of_one_session_write_one_record_and_lock_once(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """Ten units on ten connections: the first holds the row through its record while nine queue
    behind it, then each of them reads the row locked and writes nothing."""
    repo, clock = _repo(rel), _Clock()
    record = await _live(pg_dsn, repo)
    engine = create_async_engine(pg_dsn)
    ahead = _Ahead()
    try:
        async with engine.connect() as probe:

            async def first_waits(row: SessionRecord) -> None:
                await ahead(row)
                if len(ahead.rows) == 1:
                    await _until_blocked(probe, 9)

            svc = SessionService(repo, Hasher(), clock=clock)
            outcomes = await asyncio.gather(
                *(
                    svc.lock(str(record.id), write_ahead=first_waits, audit_timeout_s=30.0)
                    for _ in range(10)
                )
            )
    finally:
        await engine.dispose()
    assert sorted(now for _, now in outcomes) == [False] * 9 + [True]
    assert len(ahead.rows) == 1 and {row.locked_at for row, _ in outcomes} == {clock.now}


@pytest.mark.parametrize("failure", ["refused", "slow"])
async def test_a_failing_or_slow_write_ahead_rolls_the_lock_back(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository, failure: str
) -> None:
    repo = _repo(rel)
    record = await _live(pg_dsn, repo)

    async def broken(_row: SessionRecord) -> None:
        if failure == "refused":
            raise RuntimeError("audit writer refused")
        await asyncio.Event().wait()  # past the 0.2 s bound

    svc = SessionService(repo, Hasher(), clock=_Clock())
    with pytest.raises(RuntimeError if failure == "refused" else WriteAheadTimeout):
        await svc.lock(str(record.id), write_ahead=broken, audit_timeout_s=0.2)
    stored = await repo.find_by_id(str(record.id))
    assert stored is not None and stored.locked_at is None
    async with asyncio.timeout(5):  # the rolled-back unit left no row lock held
        locked, locked_now = await svc.lock(
            str(record.id), write_ahead=_Ahead(), audit_timeout_s=2.0
        )
    assert locked_now and locked.locked_at is not None


@pytest.mark.parametrize("state", ["revoked", "expired"])
async def test_lock_session_never_writes_a_revoked_or_expired_row(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository, state: str
) -> None:
    repo, clock = _repo(rel), _Clock()
    record = await _live(pg_dsn, repo)
    if state == "revoked":
        assert await repo.revoke(str(record.id), reason="logout", now=_NOW) is not None
    else:
        clock.now = record.expires_at
    ahead = _Ahead()
    with pytest.raises(SessionRevoked):
        await SessionService(repo, Hasher(), clock=clock).lock(
            str(record.id), write_ahead=ahead, audit_timeout_s=2.0
        )
    stored = await repo.find_by_id(str(record.id))
    assert ahead.rows == [] and stored is not None and stored.locked_at is None


async def test_touch_last_seen_never_restamps_a_row_locked_by_request(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    repo, clock = _repo(rel), _Clock()
    record = await _live(pg_dsn, repo)
    await SessionService(repo, Hasher(), clock=clock).lock(
        str(record.id), write_ahead=_Ahead(), audit_timeout_s=2.0
    )
    assert await repo.touch_last_seen(str(record.id), now=clock.now) is None
    stored = await repo.find_by_id(str(record.id))
    assert stored is not None and stored.last_seen_at == _NOW


async def test_lift_idle_lock_clears_locked_at_in_the_write_that_restamps_last_seen_at(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    repo, clock = _repo(rel), _Clock()
    record = await _live(pg_dsn, repo)
    sid = str(record.id)
    await repo.update_step_up_state(
        sid, lambda _s: ({"keys": _NOW + timedelta(minutes=5)}, 1, None)
    )
    await SessionService(repo, Hasher(), clock=clock).lock(
        sid, write_ahead=_Ahead(), audit_timeout_s=2.0
    )
    unlocked_at = clock.now + timedelta(seconds=30)

    lifted = await repo.lift_idle_lock(sid, now=unlocked_at)

    assert lifted is not None
    assert (lifted.locked_at, lifted.unlocked_at, lifted.last_seen_at) == (
        None,
        unlocked_at,
        unlocked_at,
    )
    assert (lifted.step_up_elevations, lifted.step_up_failures) == ({}, 1)
    assert not lifted.is_idle_locked(now=unlocked_at)


async def test_a_lock_racing_a_refresh_claim_is_carried_to_the_successor(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """The refresh read the row unlocked; its claim queues behind the lock's row lock, then
    returns the locked row, and the successor is minted locked: a rotation never lifts a lock."""
    repo, clock = _repo(rel), _Clock()
    user = await seed(pg_dsn, f"lock-{uuid.uuid4().hex[:12]}", "correct horse battery")
    assert user is not None
    tokens = itertools.count()
    svc = SessionService(
        repo, Hasher(), clock=clock, refresh_token_factory=lambda: f"{_OPAQUE}-{next(tokens)}"
    )
    minted = await svc.mint(user, idle_timeout_s=_IDLE_S)
    engine = create_async_engine(pg_dsn)
    held, release = asyncio.Event(), asyncio.Event()

    async def holds(row: SessionRecord) -> None:
        held.set()
        await release.wait()

    try:
        async with engine.connect() as probe:
            lock = asyncio.create_task(
                svc.lock(str(minted.session_id), write_ahead=holds, audit_timeout_s=30.0)
            )
            await held.wait()
            refresh = asyncio.create_task(svc.refresh(minted.refresh_token))
            await _until_blocked(probe, 1)  # the claim waits on the row
            release.set()
            locked, locked_now = await lock
            successor = (await refresh).minted
    finally:
        await engine.dispose()
    assert locked_now
    row = await repo.find_by_id(str(successor.session_id))
    assert row is not None and row.locked_at == locked.locked_at
    assert row.last_seen_at == minted.issued_at and row.is_idle_locked(now=clock.now)  # carried
    with pytest.raises(SessionIdleLocked):
        await svc.require_active(str(successor.session_id))


async def test_a_lock_survives_a_new_engine_and_service(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    repo, clock = _repo(rel), _Clock()
    record = await _live(pg_dsn, repo)
    await SessionService(repo, Hasher(), clock=clock).lock(
        str(record.id), write_ahead=_Ahead(), audit_timeout_s=2.0
    )
    restarted = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        svc = SessionService(_repo(restarted), Hasher(), clock=clock)
        with pytest.raises(SessionIdleLocked):
            await svc.require_active(str(record.id))
    finally:
        await restarted.dispose()
