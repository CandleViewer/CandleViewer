"""Integration: verify's batch statement on Postgres 16 (#2464). A batch stops before a row
once the renderings before that row reach the byte budget, so it holds at most the budget
plus one entry: an entry over the whole budget comes alone when it is first, and ends the
batch it lands in otherwise; the walk goes on past short batches. Entries go in through the
repository's own `insert`.

Not run locally (no docker); exercised by the CI integration job (testcontainers). Its
statements were also run by hand on a scratch Postgres 16.4 before review.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.query import AuditQueryService
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_T0 = datetime(2026, 10, 15, tzinfo=UTC)
_BUDGET = 1000  # bytes: a few small entries, and less than one large one


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
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def relational(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """Built inside the test's own loop and disposed before it closes."""
    client = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield client
    finally:
        await client.dispose()


async def _append(repo: SqlAlchemyAuditRepository, sizes: list[int]) -> int:
    """One entry per size, a `reason` of that many characters; returns the id before them."""
    head = await repo.read_head()
    for i, size in enumerate(sizes):
        await repo.insert(
            {
                "record_id": uuid.uuid4(),
                "actor_label": "it",
                "action": "auth.login",
                "outcome": "success",
                "severity": "info",
                "reason": "r" * size,
                "event_ts": (_T0 + timedelta(seconds=i)).isoformat(),
            }
        )
    return 0 if head is None else head[0]


def _n(row: tuple[Any, ...]) -> int:
    """What the statement counts for a row: the UTF-8 bytes of its renderings."""
    return len("".join(v for v in row[3:] if v is not None).encode())


def _ids(rows: list[tuple[Any, ...]]) -> list[int]:
    return [int(row[0]) for row in rows]


async def test_a_batch_stops_before_the_row_that_starts_past_the_budget(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    whole = SqlAlchemyAuditRepository(relational)  # the default budget: all twelve fit
    cut = SqlAlchemyAuditRepository(relational, verify_batch_max_bytes=_BUDGET)
    base = await _append(whole, [100] * 12)
    every = await whole.fetch_verify_batch(after_id=base, to_id=base + 12, limit=100)
    assert _ids(every) == list(range(base + 1, base + 13))
    batch = await cut.fetch_verify_batch(after_id=base, to_id=base + 12, limit=100)
    assert batch == every[: len(batch)] and 1 < len(batch) < 12
    sizes = [_n(row) for row in every]  # the last row in starts below the budget
    assert sum(sizes[: len(batch) - 1]) < _BUDGET <= sum(sizes[: len(batch)])


async def test_an_entry_over_the_budget_comes_alone_first_and_ends_a_batch_otherwise(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    repo = SqlAlchemyAuditRepository(relational, verify_batch_max_bytes=_BUDGET)
    base = await _append(repo, [10, 10, 5000, 10, 10])  # the third is over the whole budget
    big, last = base + 3, base + 5
    fetch = repo.fetch_verify_batch
    assert _ids(await fetch(after_id=base, to_id=last, limit=10)) == [base + 1, base + 2, big]
    assert _ids(await fetch(after_id=base + 2, to_id=last, limit=10)) == [big]
    assert _ids(await fetch(after_id=big, to_id=last, limit=10)) == [base + 4, last]
    result = await AuditQueryService(repo).verify(from_id=base + 1, to_id=last, batch_size=10)
    assert (result.verified, result.entries_checked) == (True, 5)
