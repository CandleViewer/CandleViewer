"""Integration (#2911): the session layer reads `users.status` on real Postgres 16.

A refresh parked between its claim and its mint across a disable mints no live session; a mint
queues behind a disable's lock on the user row and is then refused; a disabled user's live session
that no disable revoked is refused at refresh, before the claim. A `locked` or `invited` user
still mints and rotates, and the read by refresh hash populates the status. The disable is the
E42-T04 store's order: lock the user row (`LOCK_USER`), set `disabled`, revoke the live sessions,
commit. Not run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.errors import UserDisabled
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import SessionService
from candleviewer.storage.repositories.owner_floor_sqlalchemy import LOCK_USER
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime.now(UTC).replace(microsecond=0)
#: Bounds every wait on another task: a regression fails instead of hanging CI.
_WAIT_S = 30.0
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES "
    "(CAST(:id AS uuid), :email, :name, '$argon2id$fixture', 'active')"
)
_SET_DISABLED = sa.text("UPDATE users SET status = 'disabled' WHERE id = CAST(:id AS uuid)")
_SET_STATUS = sa.text(
    "UPDATE users SET status = CAST(:status AS user_status) WHERE id = CAST(:id AS uuid)"
)
_REVOKE_LIVE = sa.text(
    "UPDATE sessions SET revoked_at = now(), revoked_reason = 'user_disabled' "
    "WHERE user_id = CAST(:id AS uuid) AND revoked_at IS NULL"
)
_LIVE = sa.text(
    "SELECT count(*) FROM sessions WHERE user_id = CAST(:id AS uuid) AND revoked_at IS NULL"
)
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")
_HOLD_SESSIONS = sa.text("LOCK TABLE sessions IN SHARE MODE")  # blocks inserts, not reads
_LOCK_USER_NOWAIT = sa.text(
    "SELECT status FROM users WHERE id = CAST(:id AS uuid) FOR NO KEY UPDATE NOWAIT"
)


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
        )
        yield dsn


class _ParkedMint(SqlAlchemySessionRepository):
    """Parks the mint's insert once armed: the refresh has claimed and has not minted yet."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        super().__init__(relational, lambda **f: SessionRecord.model_validate(f))
        self.armed = False
        self.parked = asyncio.Event()
        self.release = asyncio.Event()

    async def create_session(self, session: Any) -> Any:
        if self.armed:
            self.parked.set()
            await self.release.wait()
        return await super().create_session(session)


@asynccontextmanager
async def _env(pg_dsn: str) -> AsyncIterator[tuple[AsyncEngine, _ParkedMint, SessionService]]:
    # Every UPDATE of `users` runs the owner-floor trigger: keep one active owner that stays.
    await seed(pg_dsn, "floor-keeper", "correct horse battery")
    engine, rel = create_async_engine(pg_dsn), SqlAlchemyRelationalRepository(pg_dsn, "it2911")
    repo = _ParkedMint(rel)
    try:
        yield engine, repo, SessionService(repo, Hasher(), clock=lambda: _NOW)
    finally:
        await rel.dispose()
        await engine.dispose()


async def _user(engine: AsyncEngine) -> str:
    uid = uuid.uuid4()
    async with engine.begin() as conn:
        name = f"u{uid.hex[:20]}"
        await conn.execute(
            _USER, {"id": str(uid), "email": f"{name}@example.invalid", "name": name}
        )
    return str(uid)


async def _disable(conn: AsyncConnection, uid: str) -> None:
    """The E42-T04 disable transaction's statements, in its lock order (user row first)."""
    assert (await conn.execute(LOCK_USER, {"id": uid})).first() is not None
    await conn.execute(_SET_DISABLED, {"id": uid})
    await conn.execute(_REVOKE_LIVE, {"id": uid})


async def _live(engine: AsyncEngine, uid: str) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(_LIVE, {"id": uid})).scalar_one())


async def _until_blocked(probe: AsyncConnection, n: int) -> None:
    """Bounded condition wait: `n` backends queued on a lock (pg_locks is never cached)."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= n:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{n} callers never blocked on the disable's lock")


async def test_refresh_parked_across_a_disable_mints_no_live_session(pg_dsn: str) -> None:
    async with _env(pg_dsn) as (engine, repo, service):
        uid = await _user(engine)
        minted = await service.mint(uid)
        repo.armed = True
        refresh = asyncio.create_task(service.refresh(minted.refresh_token))
        await asyncio.wait_for(repo.parked.wait(), _WAIT_S)  # claimed, successor not minted
        async with engine.begin() as conn:
            await _disable(conn, uid)
        assert await service.revoke_all(uid, reason="user_disabled") == ()  # the S4b sweep
        repo.release.set()

        with pytest.raises(UserDisabled):
            await asyncio.wait_for(refresh, _WAIT_S)
        assert await _live(engine, uid) == 0


async def test_disable_and_mint_serialise(pg_dsn: str) -> None:
    """The mint's `FOR SHARE` read of the user row queues behind the disable's `FOR NO KEY
    UPDATE`; once the disable commits, the mint reads `disabled` and inserts nothing."""
    async with _env(pg_dsn) as (engine, _repo, service):
        uid = await _user(engine)
        async with engine.connect() as probe:
            async with engine.begin() as conn:
                await _disable(conn, uid)
                mint = asyncio.create_task(service.mint(uid))
                await _until_blocked(probe, 1)
            with pytest.raises(UserDisabled):
                await asyncio.wait_for(mint, _WAIT_S)
        assert await _live(engine, uid) == 0


async def test_a_disabled_users_live_session_is_refused_at_refresh(pg_dsn: str) -> None:
    """The status changed with no session revoked (a session no disable saw): an active user
    rotates; once disabled, refresh refuses before the claim and the session is left as it was."""
    async with _env(pg_dsn) as (engine, _repo, service):
        uid = await _user(engine)
        rotated = (await service.refresh((await service.mint(uid)).refresh_token)).minted
        async with engine.begin() as conn:
            await conn.execute(_SET_DISABLED, {"id": uid})

        with pytest.raises(UserDisabled):
            await service.refresh(rotated.refresh_token)
        assert await _live(engine, uid) == 1  # refused before the claim: nothing changed


async def test_the_mint_holds_the_user_row_until_its_insert_commits(pg_dsn: str) -> None:
    """The status read and the insert are one transaction: while the insert waits, the
    disable's lock on the user row cannot be granted (`NOWAIT` is refused, 55P03)."""
    async with _env(pg_dsn) as (engine, _repo, service):
        uid = await _user(engine)
        async with engine.connect() as probe, engine.connect() as disable:
            async with engine.begin() as holder:
                await holder.execute(_HOLD_SESSIONS)
                mint = asyncio.create_task(service.mint(uid))
                await _until_blocked(probe, 1)
                with pytest.raises(sa.exc.DBAPIError) as refused:
                    await disable.execute(_LOCK_USER_NOWAIT, {"id": uid})
                assert getattr(refused.value.orig, "sqlstate", None) == "55P03"
                await disable.rollback()
            await asyncio.wait_for(mint, _WAIT_S)
        assert await _live(engine, uid) == 1


@pytest.mark.parametrize("status", ["locked", "invited"])
async def test_a_locked_or_invited_user_still_mints_and_rotates(pg_dsn: str, status: str) -> None:
    """#2911 refuses `disabled` (or a gone user) only, as login does: the status read under the
    user-row lock lets `locked` and `invited` through, and their sessions rotate."""
    async with _env(pg_dsn) as (engine, _repo, service):
        uid = await _user(engine)
        async with engine.begin() as conn:
            await conn.execute(_SET_STATUS, {"id": uid, "status": status})

        await service.refresh((await service.mint(uid)).refresh_token)

        assert await _live(engine, uid) == 1


async def test_the_read_by_refresh_hash_populates_the_status_for_an_active_user(
    pg_dsn: str,
) -> None:
    """Repository contract: `refresh` refuses a session whose `user_status` reads `None` (fail
    closed), so `find_by_refresh_hash` must populate it on Postgres."""
    async with _env(pg_dsn) as (engine, _repo, service):
        uid = await _user(engine)
        minted = await service.mint(uid)

        by_hash = await service.peek_refresh(minted.refresh_token)  # find_by_refresh_hash

        assert by_hash is not None and by_hash.user_status is UserStatus.ACTIVE
        assert await _live(engine, uid) == 1
