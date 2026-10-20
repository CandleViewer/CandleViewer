"""`SqlAlchemyAlertDispatchStore` + deliveries repo additions with a fake UoW (E40-T04).

Real-DB behaviour (SKIP LOCKED, the no-DELETE trigger) is covered in CI integration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from test_alerts_repository_sqlalchemy import _Rel, _Result

from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    SqlAlchemyAlertDeliveryRepository,
)
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    OutboxJobRow,
    SqlAlchemyAlertDispatchStore,
)

_T0 = datetime(2026, 10, 6, tzinfo=UTC)
JOB = OutboxJobRow(id=3, delivery_id=7, attempts=2, max_attempts=8)


def _row(**over: Any) -> dict[str, Any]:
    return {
        "id": 7, "alert_id": "a", "user_id": "u1", "channel": "email", "status": "queued",
        "title": "t", "body": "", "context": {}, "attempt": 0, "http_status": None,
        "error_message": None, "queued_at": _T0, "sent_at": None, "acked_at": None,
        "acked_by": None, "severity": "info",
    } | over  # fmt: skip


def _store(*results: _Result) -> tuple[SqlAlchemyAlertDispatchStore, _Rel]:
    rel = _Rel(*results)
    return SqlAlchemyAlertDispatchStore(rel), rel  # type: ignore[arg-type]  # structural fake


async def test_claim_leases_with_skip_locked_and_maps_rows() -> None:
    store, rel = _store(_Result([{"id": 3, "delivery_id": 7, "attempts": 2, "max_attempts": 8}]))
    jobs = await store.claim(topic="alert.deliver", worker="w1", lease_s=60, limit=5)
    assert jobs == [JOB] and rel.commits == 1
    sql, p = rel.calls[0]
    assert "FOR UPDATE SKIP LOCKED" in sql and "locked_until < now()" in sql
    assert p == {"topic": "alert.deliver", "worker": "w1", "lease": 60, "limit": 5}


async def test_load_returns_row_or_none() -> None:
    store, _ = _store(_Result([_row()]), _Result([]))
    got = await store.load(7)
    assert got is not None and got.channel == "email" and got.severity == "info"
    assert await store.load(8) is None


async def test_settle_sent_is_conditional_and_marks_outbox_in_one_tx() -> None:
    store, rel = _store(_Result([], rowcount=1), _Result([]))
    assert await store.settle_sent(JOB, attempt=3, http_status=None) is True
    (s1, p1), (s2, p2) = rel.calls
    assert "status = 'queued'" in s1 and p1["attempt"] == 3
    assert "processed_at = now()" in s2 and p2 == {"id": 3, "attempts": 3}
    assert rel.commits == 1
    store, _ = _store(_Result([], rowcount=0), _Result([]))
    assert await store.settle_sent(JOB, attempt=3, http_status=None) is False


async def test_settle_suppressed_retry_processed() -> None:
    store, rel = _store(_Result([], rowcount=1), _Result([]))
    assert await store.settle_suppressed(JOB, reason="email_relay_off") is True
    assert "suppression_reason" in str(rel.calls[0][0])
    assert rel.calls[0][1] == {"id": 7, "reason": "email_relay_off"}
    store, rel = _store(_Result([]), _Result([]))
    await store.settle_retry(JOB, attempt=3, error="e", delay_s=4.0)
    assert rel.calls[0][1] == {"id": 7, "attempt": 3, "error": "e"}
    assert rel.calls[1][1] == {"id": 3, "attempts": 3, "error": "e", "delay": 4.0}
    store, rel = _store(_Result([]))
    await store.settle_processed(JOB)
    assert rel.calls[0][1] == {"id": 3, "attempts": 2}


async def test_settle_failed_dead_letters_and_raises_one_notice() -> None:
    store, rel = _store(_Result([("a", "u1")]), _Result([]), _Result([]))
    assert await store.settle_failed(JOB, attempt=3, error="500", http_status=500,
                                     notice_title="email delivery failed: t") is True  # fmt: skip
    assert "dead_at = now()" in rel.calls[1][0]
    sql, p = rel.calls[2]
    assert "'in_app', 'sent'" in sql and p["alert_id"] == "a" and p["user_id"] == "u1"
    assert '"failed_delivery_id": 7' in p["context"]
    store, rel = _store(_Result([]), _Result([]))  # lost the race: no notice
    assert await store.settle_failed(JOB, attempt=3, error="x", http_status=None,
                                     notice_title="n") is False  # fmt: skip
    assert len(rel.calls) == 2


async def test_get_owned_and_bounded_ack_all() -> None:
    rel = _Rel(_Result([_row(status="sent")]), _Result([]), _Result([(4,), (3,), (2,), (1,)]))
    repo = SqlAlchemyAlertDeliveryRepository(rel)  # type: ignore[arg-type]  # structural fake
    got = await repo.get_owned(7, "u1")
    assert got is not None and got.id == 7
    assert await repo.get_owned(7, "u2") is None
    assert rel.calls[1][1] == {"id": 7, "by": "u2"}
    assert await repo.ack_all("u1", cap=4) == [4, 3, 2, 1]  # the ids, for the alerts topic
    sql, p = rel.calls[2]
    assert "LIMIT :cap" in sql and "RETURNING id" in sql and p == {"by": "u1", "cap": 4}


def test_outbox_job_row_satisfies_the_dispatcher_port() -> None:
    from candleviewer.alerts.dispatcher import OutboxJob

    job: OutboxJob = JOB  # mypy proves the structural fit
    assert (job.id, job.delivery_id, job.attempts, job.max_attempts) == (3, 7, 2, 8)
