"""Integration: `SqlAlchemyAuditRepository.query_page` per-shape statements on Postgres 16.

Covers the repository-level AC: the caller's scope applied in the SQL (an `actor_user_id`
naming another user is narrowed, never widened), and each filter shape against real types
(uuid, inet, enums, text[], timestamptz, full text) with `to` exclusive. Rows go in
through the repository's own `insert` (the single audit writer path).

Not run locally (no docker); exercised by the CI integration job (testcontainers).
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_T0 = datetime(2026, 9, 1, tzinfo=UTC)
_MANAGER, _OTHER = uuid.UUID(int=0xA1), uuid.UUID(int=0xB2)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        migrate_dsn = url.replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(  # fixed argv, literal alembic subcommand, no shell
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": migrate_dsn},
            check=True,
        )
        with psycopg.connect(url.replace("postgresql+psycopg2", "postgresql")) as conn:
            for uid, name in ((_MANAGER, "it_manager"), (_OTHER, "it_other")):
                conn.execute(
                    "INSERT INTO users (id, email, username, password_hash, status) "
                    "VALUES (%s, %s, %s, '$argon2id$synthetic', 'active')",
                    (uid, f"{name}@example.invalid", name),
                )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyAuditRepository]:
    """Built inside the test's own loop and disposed before it closes (asyncpg futures are
    loop-bound)."""
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield SqlAlchemyAuditRepository(relational)
    finally:
        await relational.dispose()


def _row(kind: str, i: int, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "record_id": uuid.uuid4(),
        "actor_user_id": _MANAGER if i % 2 else _OTHER,
        "actor_label": "it",
        "actor_ip": f"192.0.2.{1 + i % 3}",
        "action": "orders.submit" if i % 2 else "auth.login",
        "object_kind": kind,
        "object_id": f"obj-{i}",
        "object_label": f"label {i}",
        "outcome": "denied" if i % 3 == 0 else "success",
        "severity": "error" if i % 4 == 0 else "info",
        "after_state": {"symbol": "BTCUSDT" if i % 2 else "ETHUSDT", "n": i},
        "event_ts": (_T0 + timedelta(minutes=i)).isoformat(),
    }
    return {**row, **over}


async def _page(repo: SqlAlchemyAuditRepository, kind: str, **kw: Any) -> list[dict[str, Any]]:
    unset = dict.fromkeys(set(inspect.signature(repo.query_page).parameters))
    args = {**unset, "subject_type": kind, "limit": 500, "timeout_ms": 4000, **kw}
    return await repo.query_page(**args)


async def _seed(repo: SqlAlchemyAuditRepository, kind: str, n: int) -> list[dict[str, Any]]:
    rows = [_row(kind, i) for i in range(n)]
    for row in rows:
        await repo.insert(row)
    return rows


async def test_restricted_scope_returns_only_the_callers_rows(
    repo: SqlAlchemyAuditRepository,
) -> None:
    await _seed(repo, "it_scope", 6)
    narrowed = await _page(
        repo, "it_scope", restrict_to_actor=str(_MANAGER), actor_user_id=str(_OTHER)
    )
    assert len(narrowed) == 3 and {r["actor_user_id"] for r in narrowed} == {_MANAGER}
    owner = await _page(repo, "it_scope", actor_user_id=str(_OTHER))
    assert len(owner) == 3 and {r["actor_user_id"] for r in owner} == {_OTHER}


async def test_each_filter_shape_matches_its_predicate(repo: SqlAlchemyAuditRepository) -> None:
    rows = await _seed(repo, "it_shapes", 12)

    def ids(pred: Any) -> list[str]:
        return sorted(r["object_id"] for r in rows if pred(r))

    async def got(**kw: Any) -> list[str]:
        return sorted(r["object_id"] for r in await _page(repo, "it_shapes", **kw))

    assert await got(subject_id="obj-5") == ["obj-5"]
    assert await got(ip="192.0.2.2") == ids(lambda r: r["actor_ip"] == "192.0.2.2")
    assert await got(outcome="denied") == ids(lambda r: r["outcome"] == "denied")
    assert await got(severity="error") == ids(lambda r: r["severity"] == "error")
    assert await got(actions=["auth.login"]) == ids(lambda r: r["action"] == "auth.login")
    start, end = _T0 + timedelta(minutes=3), _T0 + timedelta(minutes=7)
    assert await got(from_ts=start, to_ts=end) == ["obj-3", "obj-4", "obj-5", "obj-6"]
    assert await got(q="btcusdt") == ids(lambda r: r["after_state"]["symbol"] == "BTCUSDT")
    assert await got(q="BTCUSDT label") == await got(q="btcusdt")  # every term, any case
    assert await got(q="btcusdt ethusdt") == []
    assert await got(q='"label 7"') == ["obj-7"]  # the subject label is searched too
