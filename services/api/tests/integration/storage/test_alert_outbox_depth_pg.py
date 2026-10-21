"""Integration: `SqlAlchemyAlertDispatchStore.depth` on real Postgres 16 (#1016, E40-T04).

The backlog a topic's `cv_outbox_depth` gauge reports: its rows neither processed nor dead,
whether ready, backing off or leased, and no other topic's. Not run in the PR lane; exercised by
the integration CI job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_alerts_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture

_NOW = datetime.now(UTC)
_LATER = _NOW + timedelta(hours=1)
#: (topic, dedup_key, available_at, locked_until, processed_at, dead_at)
_ROWS = [
    ("alert.deliver", "ready", _NOW, None, None, None),
    ("alert.deliver", "backing-off", _LATER, None, None, None),
    ("alert.deliver", "leased", _NOW, _LATER, None, None),
    ("alert.deliver", "processed-1", _NOW, None, _NOW, None),
    ("alert.deliver", "processed-2", _NOW, None, _NOW, None),
    ("alert.deliver", "dead", _NOW, None, None, _NOW),
    ("webhook.post", "ready-1", _NOW, None, None, None),
    ("webhook.post", "ready-2", _NOW, None, None, None),
]


async def test_depth_counts_one_topics_backlog_whatever_its_state(pg_dsn: str) -> None:
    with _mig._conn(pg_dsn) as c:
        for row in _ROWS:
            c.execute(
                "INSERT INTO outbox (topic, dedup_key, payload, available_at, locked_until, "
                "processed_at, dead_at) VALUES (%s, %s, '{}'::jsonb, %s, %s, %s, %s)",
                row,
            )
    repo = SqlAlchemyRelationalRepository(pg_dsn, "outbox-depth-it")
    store = SqlAlchemyAlertDispatchStore(repo)
    got = [await store.depth(t) for t in ("alert.deliver", "webhook.post", "metrics.export")]
    assert got == [3, 2, 0]  # ready, backing off and leased; processed and dead rows are no backlog
