"""AUDIT-CONCURRENT (E42-Q01, #962): AC-ADM-16's 1,000 audit rows, from two connections.

The seed runs 500 rounds, and in each round two inserts race for the chain lock: one through the
app's insert path (`SqlAlchemyAuditRepository.insert`, the writer's flusher's own), the other a raw
`INSERT` on a psycopg connection, which meets the lock only in the trigger. Either may win a round,
but a round ends before the next begins, so the rows alternate in pairs. The trigger chains both
(ids are drawn under the lock since 0045), so a verify over the rows must find no break:
`check_concurrent_rows` runs the app's own verify over them.

It writes 1,000 rows that can never be removed (C-5.7), so a database not named for tests is
`FixtureRefused` before anything is read or written, on the pool and on the psycopg connection. A
second run finds the rows and writes nothing; a part of them is refused. A verify over a range that
holds the fixture's rows passes only if the range holds no altered entry, so the database must not
also hold AUDIT-CORRUPT's chain within it.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Final

import psycopg
import sqlalchemy as sa

from candleviewer.audit.models import AuditEmission
from candleviewer.audit.query import AuditQueryService
from candleviewer.db import models as m
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.fixtures.admin.audit_session import checked_pool
from tests.fixtures.admin.seed import FixtureCheckError, connect_test_database, require_aware

#: Rounds, and the rows each connection writes: two a round, AC-ADM-16's 1,000 in all.
ROUNDS: Final = 500
APP_ACTOR: Final = "fixture-concurrent-app"
RAW_ACTOR: Final = "fixture-concurrent-raw"
ACTION: Final = "auth.login"
_RAW_ROW: Final = (
    "INSERT INTO audit_log (record_id, actor_label, action, object_id, event_ts)"
    " VALUES (%s, %s, %s, %s, %s)"
)


async def _held(relational: SqlAlchemyRelationalRepository) -> list[tuple[int, str]]:
    """The fixture's rows in chain order: each one's id and actor."""
    log = m.audit_log
    read = sa.select(log.c.id, log.c.actor_label).order_by(log.c.id)
    read = read.where(log.c.actor_label.in_((APP_ACTOR, RAW_ACTOR)))
    async with relational.engine.connect() as conn:
        return [(int(row_id), who) for row_id, who in (await conn.execute(read)).all()]


async def _app_row(repository: SqlAlchemyAuditRepository, i: int, now: datetime) -> None:
    record = AuditEmission(
        record_id=uuid.uuid4(),
        action=ACTION,
        actor_label=APP_ACTOR,
        object_id=f"fixture-{i}",
        event_ts=now,
    )
    await repository.insert(record.model_dump(mode="json"))


def _raw_row(conn: psycopg.Connection[Any], i: int, now: datetime) -> None:
    conn.execute(_RAW_ROW, (uuid.uuid4(), RAW_ACTOR, ACTION, f"fixture-{i}", now))


async def _race(relational: SqlAlchemyRelationalRepository, dsn: str, now: datetime) -> None:
    repository = SqlAlchemyAuditRepository(relational)
    raw = await asyncio.to_thread(
        connect_test_database, dsn.replace("postgresql+asyncpg", "postgresql")
    )
    try:
        for i in range(ROUNDS):
            await asyncio.gather(
                _app_row(repository, i, now), asyncio.to_thread(_raw_row, raw, i, now)
            )
    finally:
        raw.close()


async def seed_concurrent_rows(dsn: str, *, now: datetime) -> tuple[int, int]:
    """The 1,000 rows, and the ids of the first and the last: the range for a verify. `dsn` is the
    SQLAlchemy asyncpg URL of a migrated test database."""
    require_aware(now)
    async with checked_pool(dsn) as relational:
        who = [actor for _, actor in await _held(relational)]
        counts = (who.count(APP_ACTOR), who.count(RAW_ACTOR))
        if counts == (0, 0):
            await _race(relational, dsn, now)
        elif counts != (ROUNDS, ROUNDS):
            raise FixtureCheckError(
                f"AUDIT-CONCURRENT: {counts[0]} app and {counts[1]} raw rows are present, not "
                f"{ROUNDS} each; audit rows can never be removed (C-5.7), so load it into a fresh "
                "test database"
            )
        rows = await _held(relational)
    return rows[0][0], rows[-1][0]


async def check_concurrent_rows(dsn: str) -> None:
    """`FixtureCheckError` unless each connection wrote its 500 rows, the rows alternate in pairs,
    and the app's own verify over them finds no break."""
    async with checked_pool(dsn) as relational:
        rows = await _held(relational)
        actors = [who for _, who in rows]
        failed: list[str] = []
        if (actors.count(APP_ACTOR), actors.count(RAW_ACTOR)) != (ROUNDS, ROUNDS):
            failed.append(f"the rows are not {ROUNDS} from each connection")
        pairs = [set(actors[i : i + 2]) for i in range(0, len(actors), 2)]
        if any(pair != {APP_ACTOR, RAW_ACTOR} for pair in pairs):
            failed.append("the two connections' rows do not alternate in pairs")
        if rows:
            query = AuditQueryService(SqlAlchemyAuditRepository(relational))
            try:
                result = await query.verify(from_id=rows[0][0], to_id=rows[-1][0])
            finally:
                query.close()
            if not result.verified or result.entries_checked < len(rows):
                failed.append(
                    f"verify of the {len(rows)} rows: verified {result.verified}, checked "
                    f"{result.entries_checked}, first bad id {result.first_bad_id}"
                )
    if failed:
        raise FixtureCheckError("AUDIT-CONCURRENT: " + "; ".join(failed))
