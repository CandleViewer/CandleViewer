"""Integration (#4540): the failure update for the login placeholder's nil UUID changes no row in
real Postgres 16, so an unknown identifier's failed sign-in creates no row and locks no one, even
if a row with that id were ever planted."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa

from candleviewer.auth.login_service import ABSENT_USER_ID, LOCKOUT_THRESHOLD
from candleviewer.auth.models import UserRecord
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from tests.integration import _refused
from tests.integration._refused import seed_user

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head, on loopback
_NOW = datetime.now(UTC).replace(microsecond=0)
_LOCK = timedelta(minutes=15)
_SNAPSHOT = "SELECT id::text, failed_login_count, locked_until FROM users ORDER BY id"


def _rec(model: Any) -> Callable[..., Any]:
    return lambda **f: model.model_validate(f)


async def _failures_for_the_placeholder(pg_dsn: str) -> tuple[list[Any], list[Any], list[Any]]:
    """The users rows before and after LOCKOUT_THRESHOLD + 1 placeholder failures, and the
    failures' results."""
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    try:
        async with rel.unit_of_work() as uow:
            before = list((await uow.session.execute(sa.text(_SNAPSHOT))).all())
            await uow.commit()
        results = [
            await users.record_login_failure(
                str(ABSENT_USER_ID),
                lockout_threshold=LOCKOUT_THRESHOLD,
                lock_duration=_LOCK,
                now=_NOW,
            )
            for _ in range(LOCKOUT_THRESHOLD + 1)
        ]
        async with rel.unit_of_work() as uow:
            after = list((await uow.session.execute(sa.text(_SNAPSHOT))).all())
            await uow.commit()
        return before, after, results
    finally:
        await rel.dispose()


async def test_record_login_failure_for_the_placeholder_id_changes_no_row(pg_dsn: str) -> None:
    seed_user(pg_dsn)

    before, after, results = await _failures_for_the_placeholder(pg_dsn)

    assert results == [None] * (LOCKOUT_THRESHOLD + 1)
    assert after == before  # no row created, none counted or locked


async def test_record_login_failure_never_counts_against_a_planted_placeholder_row(
    pg_dsn: str,
) -> None:
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, %s)",
            [str(ABSENT_USER_ID), "absent@x.invalid", "absent-row", "$argon2id$x"],
        )

    before, after, results = await _failures_for_the_placeholder(pg_dsn)

    assert results == [None] * (LOCKOUT_THRESHOLD + 1)
    assert after == before
