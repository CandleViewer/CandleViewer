"""Integration: the step-up's session rotation on real Postgres 16 (SR-013, #2101; ruling C-5, C-8).

The trap this pins: `SqlAlchemySessionRepository.create_session` must write `step_up_elevations`.
The in-memory fake keeps whatever record it is given, so a unit test of `SessionService.rotate`
passes while an insert that leaves the column out gives the successor the default `{}`, and the
grant the rotating step-up just made is lost. Also pinned here, on the real conditional `UPDATE`:
of a rotation and a refresh of one session exactly one claims it (C-8). Needs Docker
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
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.errors import RefreshReuseDetected, SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import RefreshOutcome, SessionRecord
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import carried_grants
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
_FP = hashlib.sha256(b"POST /trading/kill-switch").hexdigest()
#: A no-grace grant as a step-up leaves it, bound to the SHA-256 of the challenged request.
_ONCE = f"once:killswitch:{uuid.UUID(int=1)}:{_FP}"
_PENDING = f"pending:users:{uuid.UUID(int=2)}"


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


def _repo(rel: SqlAlchemyRelationalRepository) -> SqlAlchemySessionRepository:
    return SqlAlchemySessionRepository(rel, lambda **fields: SessionRecord.model_validate(fields))


async def _user(pg_dsn: str) -> str:
    user = await seed(pg_dsn, f"rotate-{uuid.uuid4().hex[:12]}", "correct horse battery")
    assert user is not None
    return user


def _service(repo: SqlAlchemySessionRepository) -> SessionService:
    return SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW)


async def test_create_session_inserts_the_step_up_elevations_the_record_carries(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """Fails on `main`: the insert left the column out, so the row read back held `{}`."""
    repo = _repo(rel)
    grants = {"users": _NOW + timedelta(minutes=5), _ONCE: _NOW + timedelta(seconds=60)}

    minted = await _service(repo).mint(await _user(pg_dsn), step_up_elevations=grants)

    stored = await repo.find_by_id(str(minted.session_id))
    assert stored is not None
    assert stored.step_up_elevations == grants


async def test_rotate_carries_the_live_grants_to_the_successor_row(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    repo = _repo(rel)
    service = _service(repo)
    old = await service.mint(await _user(pg_dsn))
    held = {
        "users": _NOW + timedelta(minutes=5),
        _ONCE: _NOW + timedelta(seconds=60),
        "keys": _NOW - timedelta(seconds=1),
        _PENDING: _NOW + timedelta(minutes=5),
    }
    seeded = await repo.update_step_up_state(str(old.session_id), lambda _row: (held, 1, None))
    assert seeded is not None
    successor = uuid.uuid4()

    outcome = await service.rotate(
        str(old.session_id), successor_id=successor, carry_grants=carried_grants
    )

    assert outcome.minted.session_id == successor
    new = await repo.find_by_id(str(successor))
    assert new is not None and new.revoked_at is None
    assert new.step_up_elevations == {
        "users": _NOW + timedelta(minutes=5),
        _ONCE: _NOW + timedelta(seconds=60),
    }
    assert (new.step_up_failures, new.expires_at) == (1, old.expires_at)
    claimed = await repo.find_by_id(str(old.session_id))
    assert claimed is not None and claimed.revoked_reason == "rotated"
    family = await repo.walk_rotation_family(str(successor))
    assert set(family) == {str(old.session_id), str(successor)}


async def test_rotate_and_refresh_of_one_session_claim_it_exactly_once(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """C-8: the claim is one conditional `UPDATE ... WHERE revoked_at IS NULL`, so of the two only
    one rotates the session; the other is refused, and at most one successor is ever minted."""
    repo = _repo(rel)
    service = _service(repo)
    user = await _user(pg_dsn)
    old = await service.mint(user)
    successor = uuid.uuid4()

    results = await asyncio.gather(
        service.rotate(str(old.session_id), successor_id=successor, carry_grants=carried_grants),
        service.refresh(old.refresh_token),
        return_exceptions=True,
    )

    won = [r for r in results if isinstance(r, RefreshOutcome)]
    lost = [r for r in results if isinstance(r, BaseException)]
    assert len(won) == 1, results
    assert len(lost) == 1 and isinstance(lost[0], (SessionRevoked, RefreshReuseDetected))
    minted = {str(s.id) for s in await repo.find_live_by_user(user)} - {str(old.session_id)}
    assert len(minted) <= 1
