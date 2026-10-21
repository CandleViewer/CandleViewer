"""Integration: verify's checkpoint cross-check against real `audit_log` and
`audit_checkpoints` on Postgres 16 (#2392: every checkpoint with `head_id <= to_id` must name
an entry whose `entry_hash` is its `head_hash`; a range that ends at the head breaks on a
checkpoint above it). Entries go in through the repository's own `insert`.

Not run locally (no docker); exercised by the CI integration job (testcontainers).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.models import ChainBreakKind
from candleviewer.audit.query import AuditQueryService
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_T0 = datetime(2026, 10, 15, tzinfo=UTC)


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
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyAuditRepository]:
    """Built inside the test's own loop and disposed before it closes."""
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield SqlAlchemyAuditRepository(relational)
    finally:
        await relational.dispose()


async def _append(repo: SqlAlchemyAuditRepository, n: int) -> None:
    for i in range(n):
        await repo.insert(
            {
                "record_id": uuid.uuid4(),
                "actor_label": "it",
                "action": "auth.login",
                "outcome": "success",
                "severity": "info",
                "event_ts": (_T0 + timedelta(seconds=i)).isoformat(),
            }
        )


async def _checkpoint(repo: SqlAlchemyAuditRepository, head_id: int, head_hash: str) -> None:
    await repo.write_checkpoint(
        checkpoint_id=str(uuid.uuid4()), head_id=head_id, head_hash=head_hash, row_count=0,
        signed_by="it",
    )  # fmt: skip


async def test_checkpoints_are_checked_in_id_order_against_real_tables(
    repo: SqlAlchemyAuditRepository,
) -> None:
    svc = AuditQueryService(repo)
    await _append(repo, 3)
    head = await repo.read_head()
    assert head is not None
    assert await repo.fetch_checkpoints(head[0]) == []
    await _checkpoint(repo, head[0], head[1])  # a checkpoint that matches
    assert (await svc.verify()).verified

    # Since 0045 an insert draws two ids (the default's, unused, then the trigger's under the
    # chain lock), so the fourth entry appended below gets the id `ahead`.
    ahead = head[0] + 8
    await _checkpoint(repo, ahead, "e" * 64)  # names an id above the head: a truncated tail
    whole = await svc.verify()
    assert (whole.first_bad_id, whole.kind) == (ahead, ChainBreakKind.TAIL_TRUNCATED)
    past = await svc.verify(from_id=head[0] + 1)  # beyond the head: the truncation, not a 404
    assert (past.first_bad_id, past.from_id, past.to_id, past.entries_checked) == (
        ahead,
        head[0] + 1,
        head[0],
        0,
    )

    await _append(repo, 4)  # the fourth has the id `ahead`, with another hash
    assert [(h, e is not None) for h, _, e in await repo.fetch_checkpoints(ahead)] == [
        (head[0], True),
        (ahead, True),
    ]
    broken = await svc.verify()
    assert (broken.first_bad_id, broken.kind) == (ahead, ChainBreakKind.CHECKPOINT_MISMATCH)
    assert (broken.entries_checked, broken.verified) == (7, False)
