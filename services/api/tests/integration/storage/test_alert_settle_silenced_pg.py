"""Integration: the held-row settles of `SqlAlchemyAlertDispatchStore` on real Postgres 16 (#1130).

A firing a mute or quiet hours holds settles its `in_app` row `sent` with `context.silenced` in the
same row update, and its `desktop` row `suppressed` with the reason; both settles are guarded by
`status = 'queued'`, so a settled row is never settled again. Not run locally (no docker); the
integration CI job runs it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    OutboxJobRow,
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_alerts_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture


def _seed(dsn: str, channel: str) -> OutboxJobRow:
    """One queued delivery on `channel` and its outbox job, as the dispatcher claims it."""
    with _mig._conn(dsn) as c:
        aid = _mig._alert(c)
        uid = c.execute("SELECT owner_user_id FROM alerts WHERE id = %s", (aid,)).fetchone()
        assert uid is not None
        row = c.execute(
            "INSERT INTO alert_deliveries (alert_id, user_id, channel, title, context) "
            "VALUES (%s, %s, %s, 't', '{\"kept\": 1}'::jsonb) RETURNING id",
            (aid, uid[0], channel),
        ).fetchone()
        assert row is not None
        did = int(str(row[0]))
        ob = c.execute(
            "INSERT INTO outbox (topic, dedup_key, payload) VALUES (%s, %s, %s::jsonb) "
            "RETURNING id, attempts, max_attempts",
            (TOPIC_ALERT_DELIVER, alert_deliver_dedup_key(did), json.dumps({"delivery_id": did})),
        ).fetchone()
        assert ob is not None
    return OutboxJobRow(id=int(str(ob[0])), delivery_id=did, attempts=int(str(ob[1])),
                        max_attempts=int(str(ob[2])))  # fmt: skip


def _delivery(dsn: str, did: int) -> tuple[Any, ...]:
    with _mig._conn(dsn) as c:
        row = c.execute(
            "SELECT status::text, context, error_message, sent_at IS NOT NULL "
            "FROM alert_deliveries WHERE id = %s",
            (did,),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _processed(dsn: str, job: OutboxJobRow) -> bool:
    with _mig._conn(dsn) as c:
        row = c.execute("SELECT processed_at IS NOT NULL FROM outbox WHERE id = %s", (job.id,))
        got = row.fetchone()
    assert got is not None
    return bool(got[0])


def _store(dsn: str) -> SqlAlchemyAlertDispatchStore:
    return SqlAlchemyAlertDispatchStore(SqlAlchemyRelationalRepository(dsn, "settle-it"))


@pytest.mark.parametrize("reason", ["muted_symbol", "quiet_hours"])
async def test_settle_sent_with_silenced_marks_the_in_app_row_in_one_update(
    pg_dsn: str, reason: str
) -> None:
    job = _seed(pg_dsn, "in_app")
    assert await _store(pg_dsn).settle_sent(job, attempt=1, http_status=None, silenced=reason)
    status, context, error, sent = _delivery(pg_dsn, job.delivery_id)
    assert (status, error, sent) == ("sent", None, True)
    assert context == {"kept": 1, "silenced": reason}  # merged, never replacing the context
    assert _processed(pg_dsn, job)


async def test_settle_sent_without_silenced_leaves_the_context_untouched(pg_dsn: str) -> None:
    job = _seed(pg_dsn, "in_app")
    assert await _store(pg_dsn).settle_sent(job, attempt=1, http_status=None)
    status, context, _, _ = _delivery(pg_dsn, job.delivery_id)
    assert (status, context) == ("sent", {"kept": 1})


async def test_settle_suppressed_records_the_reason_on_the_desktop_row(pg_dsn: str) -> None:
    job = _seed(pg_dsn, "desktop")
    assert await _store(pg_dsn).settle_suppressed(job, reason="quiet_hours")
    status, context, error, sent = _delivery(pg_dsn, job.delivery_id)
    assert (status, error, sent) == ("suppressed", "quiet_hours", False)
    assert context == {"kept": 1, "suppression_reason": "quiet_hours"}
    assert _processed(pg_dsn, job)


async def test_a_settled_row_is_not_settled_again(pg_dsn: str) -> None:
    store = _store(pg_dsn)
    job = _seed(pg_dsn, "in_app")
    assert await store.settle_sent(job, attempt=1, http_status=None, silenced="quiet_hours")
    assert not await store.settle_sent(job, attempt=2, http_status=None, silenced="muted_symbol")
    assert not await store.settle_suppressed(job, reason="desktop_off")
    status, context, error, _ = _delivery(pg_dsn, job.delivery_id)
    assert (status, error) == ("sent", None)
    assert context == {"kept": 1, "silenced": "quiet_hours"}  # the first settle's, unchanged
