"""Integration: identical re-sends racing for one no-grace step-up grant, against real
Postgres 16 (#2304).

`SqlAlchemySessionRepository.consume_step_up_key` removes a one-shot grant with one conditional
`UPDATE ... RETURNING`. Under READ COMMITTED a concurrent writer waits on the row lock, then
re-evaluates the jsonb predicate on the committed row, finds the key gone and updates nothing; a
read-modify-write would hand the grant to every caller. Not run locally (no docker); CI only.
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
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.models import SessionRecord
from candleviewer.auth.step_up import GRACE_WINDOW, SINGLE_USE_WINDOW, StepUpChallenge
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
    saved = await repo.save_step_up_state(
        str(record.id), elevations=elevations, failures=0, readonly_until=None
    )
    assert saved is not None
    return repo, str(record.id)


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
