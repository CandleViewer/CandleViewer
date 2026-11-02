"""Integration: the `rule.notify` outbox writer on real Postgres 16 (E35-T13, #5005; 21 §3.10.4,
24 §11.5).

A retried notification lands one row (`ux_outbox_dedup`); a row still unclaimed past its TTL is
dead-lettered by the next write and kept, so its key still dedupes; a processed row, a dead one, a
leased one and another topic's are never touched. Not run in the PR lane; exercised by the
integration CI job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.rule_notify_sqlalchemy import (
    UNCLAIMED,
    SqlAlchemyRuleNotifyOutbox,
)
from tests.integration.storage import test_alerts_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture

TOPIC = "rule.notify"
DAY_S = 86_400.0


def _writer(pg_dsn: str, *, limit: int = 100) -> SqlAlchemyRuleNotifyOutbox:
    relational = SqlAlchemyRelationalRepository(pg_dsn, "rule-notify-it")
    return SqlAlchemyRuleNotifyOutbox(relational, topic=TOPIC, ttl_s=DAY_S, limit=limit)


def _rows(pg_dsn: str, key: str | None = None) -> list[tuple[str, str, str | None]]:
    """`(topic, dedup_key, last_error)` of the topic's rows, dead ones marked by their error."""
    with _mig._conn(pg_dsn) as c:
        cur = c.execute(
            "SELECT topic, dedup_key, CASE WHEN dead_at IS NULL THEN NULL ELSE last_error END "
            "FROM outbox WHERE (%s::text IS NULL OR dedup_key = %s) ORDER BY id",
            (key, key),
        )
        return [(str(t), str(k), None if e is None else str(e)) for t, k, e in cur.fetchall()]


async def test_a_retried_notification_lands_one_outbox_row(pg_dsn: str) -> None:
    """A repeat of the action's fire key, the retry's, lands no second row: the first payload
    stays, as `ux_outbox_dedup` keeps it."""
    writer = _writer(pg_dsn)
    key = "a" * 64
    assert await writer.enqueue(key, {"text": "first", "rule_id": "r1"}) == 0
    assert await writer.enqueue(key, {"text": "again", "rule_id": "r1"}) == 0
    assert _rows(pg_dsn, key) == [(TOPIC, key, None)]
    with _mig._conn(pg_dsn) as c:
        stored = c.execute("SELECT payload FROM outbox WHERE dedup_key = %s", (key,)).fetchone()
    assert stored is not None and stored[0] == {"text": "first", "rule_id": "r1"}


async def test_an_unclaimed_row_is_dead_lettered_after_its_ttl_and_kept(pg_dsn: str) -> None:
    """BQ-8 of #5005: the next write dead-letters the topic's rows unclaimed for more than a day
    (`unclaimed_ttl`), at most its bound, and keeps them, so a retry of one still lands once; a
    fresh row, a processed one, a dead one, a leased one and another topic's stay as they were."""
    old, now = datetime.now(UTC) - timedelta(days=2), datetime.now(UTC)
    later = now + timedelta(hours=1)
    #: (topic, dedup_key, created_at, locked_until, processed_at, dead_at)
    seeded = [
        (TOPIC, "stale-1", old, None, None, None),
        (TOPIC, "stale-2", old, None, None, None),
        (TOPIC, "stale-3", old, None, None, None),
        (TOPIC, "fresh", now, None, None, None),
        (TOPIC, "processed", old, None, now, None),
        (TOPIC, "leased", old, later, None, None),
        ("alert.deliver", "stale-other-topic", old, None, None, None),
    ]
    with _mig._conn(pg_dsn) as c:
        for row in seeded:
            c.execute(
                "INSERT INTO outbox (topic, dedup_key, payload, created_at, locked_until, "
                "processed_at, dead_at) VALUES (%s, %s, '{}'::jsonb, %s, %s, %s, %s)",
                row,
            )
    assert await _writer(pg_dsn, limit=2).enqueue("new-1", {"text": "x"}) == 2  # the bound
    assert await _writer(pg_dsn, limit=2).enqueue("new-2", {"text": "y"}) == 1  # the rest
    dead = {key: error for topic, key, error in _rows(pg_dsn) if error is not None}
    assert dead == {"stale-1": UNCLAIMED, "stale-2": UNCLAIMED, "stale-3": UNCLAIMED}
    assert await _writer(pg_dsn).enqueue("stale-1", {"text": "retry"}) == 0
    assert _rows(pg_dsn, "stale-1") == [(TOPIC, "stale-1", UNCLAIMED)]  # kept, and still one
    for key in ("fresh", "processed", "leased", "stale-other-topic", "new-1", "new-2"):
        assert [error for _, _, error in _rows(pg_dsn, key)] == [None], key
