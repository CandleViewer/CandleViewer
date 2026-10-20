"""Postgres `DispatchStore` for the alert dispatcher (E40-T04).

Lease: `FOR UPDATE SKIP LOCKED` over `ix_outbox_ready`, honouring an unexpired
`locked_until` held by another worker. Every settle is one transaction that updates the
delivery conditionally (`WHERE status = 'queued'`) and the outbox row together, so a crash
between adapter call and settle re-delivers at most the adapter call, never the record
(the outbox row is unique on `(topic, dedup_key)` — `ux_outbox_dedup`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    CHANNEL_FAILURE_NOTICE,
    DeliveryRow,
    failure_notice_context,
    row_of,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_CLAIM = sa.text(
    "UPDATE outbox SET locked_by = :worker, "
    "locked_until = now() + make_interval(secs => :lease) "
    "WHERE id IN (SELECT id FROM outbox WHERE topic = :topic AND processed_at IS NULL "
    "AND dead_at IS NULL AND available_at <= now() "
    "AND (locked_until IS NULL OR locked_until < now()) "
    "ORDER BY available_at, id LIMIT :limit FOR UPDATE SKIP LOCKED) "
    "RETURNING id, (payload->>'delivery_id')::bigint AS delivery_id, attempts, max_attempts"
)
#: Fixed SQL, bound params only (same columns as `alert_deliveries_sqlalchemy._COLS`).
_LOAD = sa.text(
    "SELECT id, alert_id::text AS alert_id, user_id::text AS user_id, channel::text AS channel, "
    "status::text AS status, title, body, context, attempt, http_status, error_message, "
    "queued_at, sent_at, acked_at, acked_by::text AS acked_by, "
    "(SELECT a.severity::text FROM alerts a WHERE a.id = alert_deliveries.alert_id) AS severity "
    "FROM alert_deliveries WHERE id = :id"
)
_OB_DONE = sa.text(
    "UPDATE outbox SET processed_at = now(), locked_by = NULL, locked_until = NULL, "
    "attempts = :attempts WHERE id = :id"
)
_OB_RETRY = sa.text(
    "UPDATE outbox SET attempts = :attempts, last_error = :error, locked_by = NULL, "
    "locked_until = NULL, available_at = now() + make_interval(secs => :delay) WHERE id = :id"
)
_OB_DEAD = sa.text(
    "UPDATE outbox SET attempts = :attempts, last_error = :error, dead_at = now(), "
    "locked_by = NULL, locked_until = NULL WHERE id = :id"
)
_AD_SENT = sa.text(
    "UPDATE alert_deliveries SET status = 'sent', sent_at = now(), attempt = :attempt, "
    "http_status = :http, error_message = NULL WHERE id = :id AND status = 'queued'"
)
_AD_SUPPRESSED = sa.text(
    "UPDATE alert_deliveries SET status = 'suppressed', error_message = :reason, "
    "context = context || jsonb_build_object('suppression_reason', CAST(:reason AS text)) "
    "WHERE id = :id AND status = 'queued'"
)
_AD_ATTEMPT = sa.text(
    "UPDATE alert_deliveries SET attempt = :attempt, error_message = :error "
    "WHERE id = :id AND status = 'queued'"
)
_AD_FAILED = sa.text(
    "UPDATE alert_deliveries SET status = 'failed', attempt = :attempt, http_status = :http, "
    "error_message = :error WHERE id = :id AND status = 'queued' "
    "RETURNING alert_id, user_id"
)


@dataclass(frozen=True, slots=True)
class OutboxJobRow:
    id: int
    delivery_id: int
    attempts: int
    max_attempts: int


def _rc(res: Any) -> int:
    return int(getattr(res, "rowcount", 0) or 0)


class SqlAlchemyAlertDispatchStore:
    """`alerts.dispatcher.DispatchStore` over Postgres."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def claim(
        self, *, topic: str, worker: str, lease_s: float, limit: int
    ) -> list[OutboxJobRow]:
        params = {"topic": topic, "worker": worker, "lease": lease_s, "limit": limit}
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_CLAIM, params)).mappings().all()
            await uow.commit()
        return [OutboxJobRow(**dict(m)) for m in rows]

    async def load(self, delivery_id: int) -> DeliveryRow | None:
        async with self._relational.unit_of_work() as uow:
            m = (await uow.session.execute(_LOAD, {"id": delivery_id})).mappings().first()
        return None if m is None else row_of(m)

    async def settle_processed(self, job: Any) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_OB_DONE, {"id": job.id, "attempts": job.attempts})
            await uow.commit()

    async def settle_sent(self, job: Any, *, attempt: int, http_status: int | None) -> bool:
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            won = _rc(await run(_AD_SENT, {"id": job.delivery_id, "attempt": attempt,
                                           "http": http_status}))  # fmt: skip
            await run(_OB_DONE, {"id": job.id, "attempts": job.attempts + 1})
            await uow.commit()
        return won > 0

    async def settle_suppressed(self, job: Any, *, reason: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            won = _rc(await run(_AD_SUPPRESSED, {"id": job.delivery_id, "reason": reason}))
            await run(_OB_DONE, {"id": job.id, "attempts": job.attempts})
            await uow.commit()
        return won > 0

    async def settle_retry(self, job: Any, *, attempt: int, error: str, delay_s: float) -> None:
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            await run(_AD_ATTEMPT, {"id": job.delivery_id, "attempt": attempt, "error": error})
            await run(_OB_RETRY, {"id": job.id, "attempts": job.attempts + 1, "error": error,
                                  "delay": delay_s})  # fmt: skip
            await uow.commit()

    async def settle_failed(
        self, job: Any, *, attempt: int, error: str, http_status: int | None, notice_title: str
    ) -> bool:
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            params = {"id": job.delivery_id, "attempt": attempt, "http": http_status,
                      "error": error}  # fmt: skip
            got = (await run(_AD_FAILED, params)).first()
            await run(_OB_DEAD, {"id": job.id, "attempts": job.attempts + 1, "error": error})
            if got is not None:  # the shared notice row (desktop report-back writes it too)
                await run(CHANNEL_FAILURE_NOTICE, {
                    "alert_id": got[0], "user_id": got[1], "title": notice_title,
                    "context": failure_notice_context(job.delivery_id),
                })  # fmt: skip
            await uow.commit()
        return got is not None
