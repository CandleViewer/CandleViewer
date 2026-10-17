"""Integration: `SqlAlchemyFlagRepository` on real Postgres 16 (E42-T03): `ensure` is insert-only
and idempotent, `load` returns every row with every override kept, and an unreachable database is
an outage. Runs in the CI integration lane."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.flags import FLAGS
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.flags_sqlalchemy import FlagSeed, SqlAlchemyFlagRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_KEY = "rules.graph_editor"  # boolean, default true
_SEEDS = [FlagSeed(f.key, f.kind, f.description, f.default, f.is_killswitch) for f in FLAGS]
_PCT = FlagSeed("algo.pct", "percentage", "P", 25, False)
_VAR = FlagSeed("ui.mode", "variant", "V", "a", False, ("a", "b"))


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, env=env, check=True
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


def _sync(pg_dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


@pytest.fixture(autouse=True)
def no_flags(pg_dsn: str) -> None:
    with _sync(pg_dsn) as c:
        c.execute("DELETE FROM feature_flags")  # cascades to the overrides


def _user(pg_dsn: str) -> UUID:
    uid = uuid.uuid4()
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid}@example.test", f"u{uid.hex[:12]}"),
        )
    return uid


def _add_override(pg_dsn: str, key: str, value: object, uid: UUID | None, role: str = "") -> None:
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO feature_flag_overrides (id, feature_flag_id, user_id, role_id, value) "
            "SELECT gen_random_uuid(), f.id, %s, (SELECT id FROM roles WHERE name = %s), %s "
            "FROM feature_flags f WHERE f.key = %s",
            (uid, role or None, Jsonb(value), key),
        )


@pytest.fixture
async def relational(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield repo
    finally:
        await repo.dispose()


def _repository(
    relational: SqlAlchemyRelationalRepository, budget_ms: int = 2000
) -> SqlAlchemyFlagRepository:
    return SqlAlchemyFlagRepository(relational, read_budget_ms=budget_ms)


def _row(pg_dsn: str, key: str) -> tuple[Any, ...]:
    with _sync(pg_dsn) as c:
        return (
            c.execute(
                "SELECT kind::text, default_value, rollout_pct, variants, is_killswitch, "
                "description, updated_at FROM feature_flags WHERE key = %s",
                (key,),
            ).fetchone()
            or ()
        )


async def test_ensure_inserts_every_flag_once_at_its_default(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo = _repository(relational)
    await repo.ensure([*_SEEDS, _PCT, _VAR])
    first = {s.key: _row(pg_dsn, s.key) for s in [*_SEEDS, _PCT, _VAR]}
    assert first["killswitch.order_entry"][:5] == ("boolean", False, None, None, True)
    assert first["algo.pct"][:4] == ("percentage", False, 25, None)
    assert first["ui.mode"][:4] == ("variant", "a", None, ["a", "b"])
    assert {k: r[5] for k, r in first.items()} == {
        s.key: s.description for s in [*_SEEDS, _PCT, _VAR]
    }
    await repo.ensure([FlagSeed(_KEY, "boolean", "x", False, False)])
    assert {key: _row(pg_dsn, key) for key in first} == first  # nothing re-written
    assert len(await repo.load()) == len(FLAGS) + 2


async def test_load_keeps_every_override_and_an_unreadable_value(
    pg_dsn: str, relational: SqlAlchemyRelationalRepository
) -> None:
    repo, alice, bob, carol = _repository(relational), _user(pg_dsn), _user(pg_dsn), _user(pg_dsn)
    await repo.ensure(_SEEDS)
    _add_override(pg_dsn, _KEY, False, alice)
    _add_override(pg_dsn, _KEY, {"odd": 1}, bob)  # unreadable: kept, the service counts it
    _add_override(pg_dsn, _KEY, None, carol)  # a JSON null: kept
    _add_override(pg_dsn, _KEY, None, None, "manager")
    with _sync(pg_dsn) as c:
        c.execute("UPDATE feature_flags SET default_value = '\"garbage\"' WHERE key = %s", (_KEY,))
    row = (await repo.load())[_KEY]
    assert (row.value, row.updated_by) == ("garbage", None)
    assert row.user_overrides == {alice: False, bob: {"odd": 1}, carol: None}
    assert row.role_overrides == {"manager": None}


async def test_an_unreachable_database_is_an_outage_for_ensure_and_load() -> None:
    dead = SqlAlchemyRelationalRepository("postgresql+asyncpg://cv:cv@127.0.0.1:1/none")
    try:
        repo = _repository(dead)
        with pytest.raises(StorageTierUnavailable):
            await repo.ensure(_SEEDS)
        with pytest.raises(StorageTierUnavailable):
            await repo.load()
    finally:
        await dead.dispose()
