"""Integration: one no-grace step-up grant on real Postgres 16 (#2304): identical re-sends racing
to use it, and the other writes of the step-up columns racing them.

`SqlAlchemySessionRepository.consume_step_up_key` removes a one-shot grant with one conditional
`UPDATE ... RETURNING`. Under READ COMMITTED a concurrent writer waits on the row lock, then
re-evaluates the jsonb predicate on the committed row, finds the key gone and updates nothing; a
read-modify-write would hand the grant to every caller. `update_step_up_state`, the only other
writer of the columns, reads the row `FOR NO KEY UPDATE` and rewrites it in the same transaction,
so it never writes back a grant used after it read (security review, round 3). Needs Docker
(testcontainers); the CI `integration` job runs it.
"""

from __future__ import annotations

import asyncio
import hashlib
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

from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_repository import StepUpState
from candleviewer.auth.step_up import (
    CHALLENGE_WINDOW,
    GRACE_WINDOW,
    SINGLE_USE_WINDOW,
    StepUpChallenge,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
#: The SHA-256 of the refused request the grant is bound to (any 64-hex value binds).
_FINGERPRINT = hashlib.sha256(b"POST /trading/kill-switch").hexdigest()
#: The held request using its grant, left uncommitted so that a writer queues behind it.
_USE_UNCOMMITTED = sa.text(
    "UPDATE sessions SET step_up_elevations = step_up_elevations - CAST(:key AS text) "
    "WHERE id = CAST(:id AS uuid)"
)
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")


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


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield relational
    finally:
        await relational.dispose()


def _grant_key() -> str:
    """`once:killswitch:<challenge_id>:<sha256>`, composed as `StepUpService` stores it."""
    grant = StepUpChallenge(uuid.uuid4(), "killswitch", _NOW + SINGLE_USE_WINDOW, _FINGERPRINT)
    return grant.key("once:")


async def _live_session(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository, elevations: dict[str, datetime]
) -> tuple[SqlAlchemySessionRepository, str]:
    """A live session row of a fresh user whose `step_up_elevations` holds `elevations`."""
    user_id = await seed(pg_dsn, f"grant-{uuid.uuid4().hex[:12]}", "correct horse battery")
    assert user_id is not None
    repo = SqlAlchemySessionRepository(rel, lambda **fields: SessionRecord.model_validate(fields))
    record = SessionRecord(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        refresh_token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
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
    )
    await repo.create_session(record)
    saved = await repo.update_step_up_state(str(record.id), lambda _row: (elevations, 0, None))
    assert saved is not None
    return repo, str(record.id)


def _keep(state: StepUpState) -> StepUpState:
    """A write of the step-up columns that keeps every entry the row holds when it is read."""
    return state


async def _until_blocked(probe: AsyncConnection) -> None:
    """Bounded condition wait: a backend queued on a lock (pg_locks is never cached)."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= 1:
            return
        await asyncio.sleep(0.025)
    raise AssertionError("the writer never queued behind the uncommitted use of the grant")


@pytest.mark.parametrize("callers", [2, 8], ids=["two-re-sends", "burst-of-8"])
async def test_concurrent_consumers_of_one_grant_get_exactly_one_row(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository, callers: int
) -> None:
    key, window = _grant_key(), {"users": _NOW + GRACE_WINDOW}
    repo, sid = await _live_session(pg_dsn, rel, {key: _NOW + SINGLE_USE_WINDOW, **window})

    results = await asyncio.gather(
        *(repo.consume_step_up_key(sid, key=key, now=_NOW) for _ in range(callers))
    )

    used = [row for row in results if row is not None]
    assert len(used) == 1
    assert used[0].step_up_elevations == window  # only the grant is removed
    final = await repo.find_by_id(sid)
    assert final is not None and key not in final.step_up_elevations
    assert await repo.consume_step_up_key(sid, key=key, now=_NOW) is None  # a later re-send


async def test_an_expired_grant_is_not_consumed(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    key = _grant_key()
    repo, sid = await _live_session(pg_dsn, rel, {key: _NOW + SINGLE_USE_WINDOW})

    assert await repo.consume_step_up_key(sid, key=key, now=_NOW + SINGLE_USE_WINDOW) is None

    final = await repo.find_by_id(sid)
    assert final is not None and key in final.step_up_elevations  # no row was written


async def test_a_grant_on_a_revoked_session_is_not_consumed(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    key = _grant_key()
    repo, sid = await _live_session(pg_dsn, rel, {key: _NOW + SINGLE_USE_WINDOW})
    assert await repo.revoke(sid, reason="logout", now=_NOW) is not None

    assert await repo.consume_step_up_key(sid, key=key, now=_NOW) is None


async def test_a_write_queued_behind_the_use_of_a_grant_never_restores_it(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """Security review round 3: the held request is using its grant (uncommitted) when another
    request of the session writes a challenge. The write reads the row only once the use
    commits, so it keeps the grant used; rewriting the copy it would have read before would put
    the grant back, and the identical request could execute a second time inside the 60 s."""
    key, window = _grant_key(), {"users": _NOW + GRACE_WINDOW}
    repo, sid = await _live_session(pg_dsn, rel, {key: _NOW + SINGLE_USE_WINDOW, **window})
    challenge = StepUpChallenge(uuid.uuid4(), "keys", _NOW + CHALLENGE_WINDOW)
    seen: list[dict[str, datetime]] = []

    def issue(state: StepUpState) -> StepUpState:
        elevations, failures, readonly_until = state
        seen.append(dict(elevations))
        return {**elevations, challenge.key(): challenge.expires_at}, failures, readonly_until

    engine = create_async_engine(pg_dsn)
    try:
        async with engine.connect() as probe:
            async with engine.begin() as held:
                await held.execute(_USE_UNCOMMITTED, {"id": sid, "key": key})
                writer = asyncio.create_task(repo.update_step_up_state(sid, issue))
                await _until_blocked(probe)
            written = await writer
    finally:
        await engine.dispose()

    assert seen == [window]  # read after the use committed, never before it
    assert written is not None
    assert written.step_up_elevations == {**window, challenge.key(): challenge.expires_at}
    assert await repo.consume_step_up_key(sid, key=key, now=_NOW) is None


async def test_writes_racing_the_use_of_a_grant_never_restore_it(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    key = _grant_key()
    repo, sid = await _live_session(pg_dsn, rel, {key: _NOW + SINGLE_USE_WINDOW})

    used, *written = await asyncio.gather(
        repo.consume_step_up_key(sid, key=key, now=_NOW),
        *(repo.update_step_up_state(sid, _keep) for _ in range(8)),
    )

    assert used is not None and all(row is not None for row in written)
    final = await repo.find_by_id(sid)
    assert final is not None and key not in final.step_up_elevations


async def test_a_revoked_session_is_not_rewritten(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    key = _grant_key()
    repo, sid = await _live_session(pg_dsn, rel, {key: _NOW + SINGLE_USE_WINDOW})
    assert await repo.revoke(sid, reason="logout", now=_NOW) is not None
    seen: list[StepUpState] = []

    def change(state: StepUpState) -> StepUpState:
        seen.append(state)
        return {}, 0, None

    assert await repo.update_step_up_state(sid, change) is None
    final = await repo.find_by_id(sid)
    assert seen == [] and final is not None and key in final.step_up_elevations
