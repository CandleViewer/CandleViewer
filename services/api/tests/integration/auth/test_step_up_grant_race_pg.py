"""Integration: one-shot step-up grants on real Postgres 16 (#2304, #2798): identical re-sends
racing to use a grant, and every other write of the step-up columns racing the use.

`SqlAlchemySessionRepository.consume_step_up_key` removes a grant with one conditional
`UPDATE ... RETURNING`. Under READ COMMITTED a concurrent writer waits on the row lock, then
re-evaluates the jsonb predicate on the committed row, finds the key gone and updates nothing; a
read-modify-write would hand the grant to every caller. Every other write of the columns is
`update_step_up_state` (the step-up service's challenges, grants, strikes and lifted downgrades:
the row is read `FOR NO KEY UPDATE` and rewritten in the same transaction) or the idle unlock's
single `UPDATE`, so none of them writes back a grant used after the request read the row
(security review round 3). Needs Docker (testcontainers); the CI `integration` job runs it.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import SessionReadOnly, StepUpCodeInvalid
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, SessionRecord
from candleviewer.auth.session_repository import StepUpState
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from scripts.seed_fixture_user import seed
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.test_step_up import _HASHER, PASSWORD, _pw_hash

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
#: A no-grace grant as a step-up leaves it, bound to the SHA-256 of the challenged request.
_BOUND = hashlib.sha256(b"POST /trading/kill-switch").hexdigest()
_GRANT = f"once:killswitch:{uuid.UUID(int=1)}:{_BOUND}"
_GRANT_UNTIL = _NOW + timedelta(seconds=60)
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


@dataclass(frozen=True)
class _Session:
    """A live session row on Postgres, and the real step-up service writing it."""

    repo: SqlAlchemySessionRepository
    sid: str
    user: str
    svc: StepUpService
    totp: bytes

    def code(self) -> str:
        return generate_code(self.totp, time_step_for(_NOW.timestamp()))


async def _service(repo: SqlAlchemySessionRepository, user: str) -> tuple[StepUpService, bytes]:
    """`StepUpService` on the Postgres rows; the factors (password, TOTP) from the unit fakes."""
    methods, encryptor = FakeMfaRepository(), TotpEncryptor(os.urandom(32))
    mfa = MfaService(methods, encryptor, recovery_code_key=b"k" * 32, clock=lambda: _NOW)
    enrolled = await mfa.enroll(
        user, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
    )
    sealed = methods.methods[str(enrolled.method_id)].secret_enc
    assert sealed is not None
    totp = encryptor.decrypt(sealed)
    first = generate_code(totp, time_step_for(_NOW.timestamp()) - 1)
    await mfa.confirm_enrollment(user, method_id=str(enrolled.method_id), code=first)
    users = FakeUserRepository()
    users.add(make_user(password_hash=await _pw_hash()).model_copy(update={"id": uuid.UUID(user)}))
    return StepUpService(methods, repo, encryptor, users, _HASHER, clock=lambda: _NOW), totp


async def _live_session(
    pg_dsn: str,
    rel: SqlAlchemyRelationalRepository,
    elevations: dict[str, datetime],
    *,
    failures: int = 0,
    readonly_until: datetime | None = None,
) -> _Session:
    """A live session row of a fresh user whose step-up columns hold the given values."""
    user = await seed(pg_dsn, f"grant-{uuid.uuid4().hex[:12]}", "correct horse battery")
    assert user is not None
    repo = SqlAlchemySessionRepository(rel, lambda **fields: SessionRecord.model_validate(fields))
    record = SessionRecord(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user),
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
    stored = await repo.update_step_up_state(
        str(record.id), lambda _row: (elevations, failures, readonly_until)
    )
    assert stored is not None
    svc, totp = await _service(repo, user)
    return _Session(repo, str(record.id), user, svc, totp)


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
    window = {"users": _NOW + timedelta(minutes=5)}
    s = await _live_session(pg_dsn, rel, {_GRANT: _GRANT_UNTIL, **window})

    results = await asyncio.gather(
        *(s.repo.consume_step_up_key(s.sid, key=_GRANT, now=_NOW) for _ in range(callers))
    )

    used = [row for row in results if row is not None]
    assert len(used) == 1
    assert used[0].step_up_elevations == window  # only the grant is removed
    assert await s.repo.consume_step_up_key(s.sid, key=_GRANT, now=_NOW) is None  # a re-send


async def test_an_expired_grant_is_not_consumed(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    s = await _live_session(pg_dsn, rel, {_GRANT: _GRANT_UNTIL})

    assert await s.repo.consume_step_up_key(s.sid, key=_GRANT, now=_GRANT_UNTIL) is None

    final = await s.repo.find_by_id(s.sid)
    assert final is not None and _GRANT in final.step_up_elevations  # no row was written


async def test_a_grant_on_a_revoked_session_is_not_consumed(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    s = await _live_session(pg_dsn, rel, {_GRANT: _GRANT_UNTIL})
    assert await s.repo.revoke(s.sid, reason="logout", now=_NOW) is not None

    assert await s.repo.consume_step_up_key(s.sid, key=_GRANT, now=_NOW) is None


async def _challenge(s: _Session) -> None:
    await s.svc.record_pending(s.sid, "keys")  # a refused request of another class


async def _grant(s: _Session) -> None:
    await s.svc.step_up(s.user, s.sid, "keys", s.code(), PASSWORD)


async def _strike(s: _Session) -> None:
    with pytest.raises(StepUpCodeInvalid):
        await s.svc.step_up(s.user, s.sid, "keys", "000000", "wrong password")


async def _third_strike(s: _Session) -> None:
    with pytest.raises(SessionReadOnly):
        await s.svc.step_up(s.user, s.sid, "keys", "000000", "wrong password")


async def _lift(s: _Session) -> None:
    await s.svc.assert_writable(s.sid)  # the downgrade ran out: the write lifts it


async def _unlock(s: _Session) -> None:
    assert await s.repo.lift_idle_lock(s.sid, now=_NOW) is not None


@pytest.mark.parametrize(
    ("writer", "failures", "readonly_for"),
    [
        (_challenge, 0, None),
        (_grant, 0, None),
        (_strike, 0, None),
        (_third_strike, 2, None),
        (_lift, 3, -timedelta(seconds=1)),
        (_unlock, 0, None),
    ],
    ids=["challenge", "grant", "strike", "third-strike", "lift-downgrade", "idle-unlock"],
)
async def test_a_write_queued_behind_the_use_of_a_grant_never_restores_it(
    pg_dsn: str,
    rel: SqlAlchemyRelationalRepository,
    writer: Callable[[_Session], Coroutine[Any, Any, None]],
    failures: int,
    readonly_for: timedelta | None,
) -> None:
    """Security review round 3: the held request is using its grant (uncommitted) when another
    request of the session writes the step-up columns. The write reads the row only once the use
    commits, so the grant stays used; rewriting a copy read before the use would put it back, and
    the identical request could execute a second time inside the 60 s."""
    readonly_until = None if readonly_for is None else _NOW + readonly_for
    s = await _live_session(
        pg_dsn, rel, {_GRANT: _GRANT_UNTIL}, failures=failures, readonly_until=readonly_until
    )
    engine = create_async_engine(pg_dsn)
    try:
        async with engine.connect() as probe:
            async with engine.begin() as held:
                await held.execute(_USE_UNCOMMITTED, {"id": s.sid, "key": _GRANT})
                written = asyncio.create_task(writer(s))
                await _until_blocked(probe)
            await written
    finally:
        await engine.dispose()

    final = await s.repo.find_by_id(s.sid)
    assert final is not None and _GRANT not in final.step_up_elevations
    assert await s.repo.consume_step_up_key(s.sid, key=_GRANT, now=_NOW) is None


async def test_writes_racing_the_use_of_a_grant_never_restore_it(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    s = await _live_session(pg_dsn, rel, {_GRANT: _GRANT_UNTIL})

    used, *written = await asyncio.gather(
        s.repo.consume_step_up_key(s.sid, key=_GRANT, now=_NOW),
        *(s.repo.update_step_up_state(s.sid, _keep) for _ in range(8)),
    )

    assert used is not None and all(row is not None for row in written)
    final = await s.repo.find_by_id(s.sid)
    assert final is not None and _GRANT not in final.step_up_elevations


async def test_a_revoked_session_is_not_rewritten(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    s = await _live_session(pg_dsn, rel, {_GRANT: _GRANT_UNTIL})
    assert await s.repo.revoke(s.sid, reason="logout", now=_NOW) is not None
    seen: list[StepUpState] = []

    def change(state: StepUpState) -> StepUpState:
        seen.append(state)
        return {}, 0, None

    assert await s.repo.update_step_up_state(s.sid, change) is None
    final = await s.repo.find_by_id(s.sid)
    assert seen == [] and final is not None and _GRANT in final.step_up_elevations
