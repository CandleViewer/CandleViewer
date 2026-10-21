"""Integration: verify's batch statement on Postgres 16 (#2464). A batch stops before a row
once the renderings before that row reach the byte budget, so it holds at most the budget
plus one entry: an entry over the whole budget comes alone when it is first, and ends the
batch it lands in otherwise; the walk goes on past short batches. An entry over the per-entry
cap is never fetched: the read that starts with it names it, and a run stops there. Entries
go in through the repository's own `insert`.

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
from candleviewer.storage.errors import AuditEntryTooLarge
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


async def _append(repo: SqlAlchemyAuditRepository, sizes: list[int]) -> tuple[int, list[int]]:
    """One entry per size, a `reason` of that many characters; returns the id before them and
    their ids, read back: an insert draws two ids since `0045_audit_chain_hardening`."""
    head = await repo.read_head()
    ids: list[int] = []
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
        written = await repo.read_head()
        assert written is not None
        ids.append(written[0])
    return 0 if head is None else head[0], ids


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
    base, ids = await _append(whole, [100] * 12)
    every = await whole.fetch_verify_batch(after_id=base, to_id=ids[-1], limit=100)
    assert _ids(every) == ids
    batch = await cut.fetch_verify_batch(after_id=base, to_id=ids[-1], limit=100)
    assert batch == every[: len(batch)] and 1 < len(batch) < 12
    sizes = [_n(row) for row in every]  # the last row in starts below the budget
    assert sum(sizes[: len(batch) - 1]) < _BUDGET <= sum(sizes[: len(batch)])


async def test_an_entry_over_the_budget_comes_alone_first_and_ends_a_batch_otherwise(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    repo = SqlAlchemyAuditRepository(relational, verify_batch_max_bytes=_BUDGET)
    base, ids = await _append(repo, [10, 10, 5000, 10, 10])  # the third is over the whole budget
    big, last = ids[2], ids[4]
    fetch = repo.fetch_verify_batch
    assert _ids(await fetch(after_id=base, to_id=last, limit=10)) == ids[:3]
    assert _ids(await fetch(after_id=ids[1], to_id=last, limit=10)) == [big]
    assert _ids(await fetch(after_id=big, to_id=last, limit=10)) == ids[3:]
    result = await AuditQueryService(repo).verify(from_id=ids[0], to_id=last, batch_size=10)
    assert (result.verified, result.entries_checked) == (True, 5)


async def test_an_entry_over_the_cap_is_never_fetched_and_stops_the_run(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    repo = SqlAlchemyAuditRepository(relational, verify_max_entry_bytes=2000)
    base, ids = await _append(repo, [10, 10, 5000, 10])  # the third is over the cap
    big, last = ids[2], ids[3]
    batch = await repo.fetch_verify_batch(after_id=base, to_id=last, limit=10)
    assert _ids(batch) == ids[:2]  # ends before it
    with pytest.raises(AuditEntryTooLarge) as err:
        await repo.fetch_verify_batch(after_id=ids[1], to_id=last, limit=10)
    assert err.value.entry_id == big
    with pytest.raises(AuditEntryTooLarge):
        await AuditQueryService(repo).verify(from_id=ids[0], to_id=last, batch_size=10)
