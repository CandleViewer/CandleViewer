"""Postgres repository for `alert_deliveries` (migration `0014_alerts`, E40-T01).

Append-only history: UPDATE (queued->sent->acked) is allowed, DELETE is refused
by `trg_ad_append` for every role except the `cv_owner` retention job; this
module therefore exposes no delete. Keyset pagination on `(queued_at, id)`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.alerts_sqlalchemy import (
    Page,
    decode_cursor,
    encode_cursor,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_COLS = (
    "id, alert_id::text AS alert_id, user_id::text AS user_id, channel::text AS channel, "
    "status::text AS status, title, body, context, attempt, http_status, error_message, "
    "queued_at, sent_at, acked_at, acked_by::text AS acked_by, "
    "(SELECT a.severity::text FROM alerts a WHERE a.id = alert_deliveries.alert_id) AS severity"
)


def _sql(template: str) -> sa.TextClause:
    # Only the static column fragment is substituted, never caller data.
    return sa.text(template.replace("@C@", _COLS))


_INSERT = _sql(
    "INSERT INTO alert_deliveries (alert_id, user_id, channel, title, body, context) VALUES "
    "(CAST(:alert_id AS uuid), CAST(:user_id AS uuid), CAST(:channel AS alert_channel), :title, "
    ":body, CAST(:context AS jsonb)) RETURNING @C@"
)
_MARK_SENT = _sql(
    "UPDATE alert_deliveries SET status = 'sent', sent_at = now(), attempt = attempt + 1, "
    "http_status = :http_status, error_message = NULL WHERE id = :id AND status = 'queued' "
    "RETURNING @C@"
)
_MARK_FAILED = _sql(
    "UPDATE alert_deliveries SET status = 'failed', attempt = least(attempt + 1, 10), "
    "http_status = :http_status, error_message = :error WHERE id = :id AND status = 'queued' "
    "RETURNING @C@"
)
_MARK_SUPPRESSED = _sql(
    "UPDATE alert_deliveries SET status = 'suppressed', error_message = :reason "
    "WHERE id = :id AND status = 'queued' RETURNING @C@"
)
_ACK_ONE = _sql(
    "UPDATE alert_deliveries SET status = 'acked', acked_at = now(), "
    "acked_by = CAST(:by AS uuid) WHERE id = :id AND user_id = CAST(:by AS uuid) "
    "AND status = 'sent' AND acked_at IS NULL RETURNING @C@"
)
#: Bounded (ticket DoS note): one batch of at most `:cap` rows via `ix_ad_user_unack`.
_ACK_ALL = _sql(
    "UPDATE alert_deliveries SET status = 'acked', acked_at = now(), "
    "acked_by = CAST(:by AS uuid) WHERE id IN (SELECT id FROM alert_deliveries "
    "WHERE user_id = CAST(:by AS uuid) AND status = 'sent' AND acked_at IS NULL "
    "ORDER BY queued_at DESC LIMIT :cap FOR UPDATE SKIP LOCKED) RETURNING id"
)
_GET_OWNED = _sql("SELECT @C@ FROM alert_deliveries WHERE id = :id AND user_id = CAST(:by AS uuid)")
#: Unscoped: the REST layer compares `user_id` itself, so a foreign id is audited before its 404.
_GET = _sql("SELECT @C@ FROM alert_deliveries WHERE id = :id")
#: The owner of an alert, soft-deleted or not: its delivery history outlives the alert.
_ALERT_OWNER = sa.text("SELECT owner_user_id::text FROM alerts WHERE id = CAST(:id AS uuid)")
#: E40-T04 desktop report-back: only the caller's own `desktop` row still `queued` moves (a
#: conditional update that re-checks the owner, as `_ACK_ONE` does: C-12.4).
_DESKTOP_SENT = _sql(
    "UPDATE alert_deliveries SET status = 'sent', sent_at = now(), error_message = NULL "
    "WHERE id = :id AND user_id = CAST(:by AS uuid) AND channel = 'desktop' "
    "AND status = 'queued' RETURNING @C@"
)
_DESKTOP_FAILED = _sql(
    "UPDATE alert_deliveries SET status = 'failed', error_message = :error "
    "WHERE id = :id AND user_id = CAST(:by AS uuid) AND channel = 'desktop' "
    "AND status = 'queued' RETURNING @C@"
)
#: The channel-failure notice: an already-`sent` in_app record, so it never re-enters the
#: outbox (no notice-about-a-notice loop) and shows in the inbox / `unacked_count`.
CHANNEL_FAILURE_NOTICE = sa.text(
    "INSERT INTO alert_deliveries (alert_id, user_id, channel, status, title, body, context, "
    "sent_at) VALUES (CAST(:alert_id AS uuid), CAST(:user_id AS uuid), 'in_app', 'sent', :title, "
    "'', CAST(:context AS jsonb), now())"
)

#: E40-T04 `alerts` topic: the rows a change named, and the channel-failure notice each failed one
#: raised (written `sent`, so `ix_ad_user_unack` serves it while it is unacknowledged).
_GET_MANY = _sql(
    "SELECT @C@ FROM alert_deliveries WHERE id = ANY(CAST(:ids AS bigint[])) ORDER BY id"
)
_NOTICES = _sql(
    "SELECT @C@ FROM alert_deliveries WHERE user_id = ANY(CAST(:users AS uuid[])) "
    "AND status = 'sent' AND acked_at IS NULL AND channel = 'in_app' "
    "AND context->>'failed_delivery_id' = ANY(CAST(:failed AS text[])) ORDER BY id"
)
_UNACKED = _sql(
    "SELECT count(*) FROM alert_deliveries WHERE user_id = CAST(:user AS uuid) "
    "AND status = 'sent' AND acked_at IS NULL"
)
_EXPIRED = _sql(
    "SELECT @C@ FROM alert_deliveries WHERE queued_at < now() - make_interval(days => :days) "
    "ORDER BY id LIMIT :limit"
)
_DELETE_IDS = sa.text("DELETE FROM alert_deliveries WHERE id = ANY(:ids)")
_LIST = _sql(
    "SELECT @C@ FROM alert_deliveries WHERE user_id = CAST(:user AS uuid) "
    "AND (CAST(:alert_id AS uuid) IS NULL OR alert_id = CAST(:alert_id AS uuid)) "
    "AND (CAST(:status AS text) IS NULL OR status::text = :status) "
    "AND (NOT :unacked_only OR (status = 'sent' AND acked_at IS NULL)) "
    "AND (CAST(:from_ts AS timestamptz) IS NULL OR queued_at >= :from_ts) "
    "AND (CAST(:to_ts AS timestamptz) IS NULL OR queued_at < :to_ts) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR "
    "(queued_at, id) < (CAST(:after_ts AS timestamptz), CAST(:after_id AS bigint))) "
    "ORDER BY queued_at DESC, id DESC LIMIT :limit"
)


_INT64_MAX = 2**63 - 1


def failure_notice_context(failed_delivery_id: int) -> str:
    """`CHANNEL_FAILURE_NOTICE`'s `context`: which delivery failed (SCR-090 links to it)."""
    return json.dumps(
        {"channel_failure": True, "failed_delivery_id": failed_delivery_id}, sort_keys=True
    )


@dataclass(frozen=True, slots=True)
class DeliveryRow:
    id: int
    alert_id: str
    user_id: str | None
    channel: str
    status: str
    title: str
    body: str
    context: dict[str, Any]
    attempt: int
    http_status: int | None
    error_message: str | None
    queued_at: datetime
    sent_at: datetime | None
    acked_at: datetime | None
    acked_by: str | None
    #: `alerts.severity` of the parent alert (`AlertDelivery.severity`).
    severity: str | None = None


def _row(m: Any) -> DeliveryRow:
    return DeliveryRow(**dict(m))


row_of = _row


class SqlAlchemyAlertDeliveryRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def insert(
        self,
        *,
        alert_id: str,
        channel: str,
        title: str,
        body: str = "",
        context: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> DeliveryRow:
        params = {
            "alert_id": alert_id,
            "user_id": user_id,
            "channel": channel,
            "title": title,
            "body": body,
            "context": json.dumps(context or {}, sort_keys=True),
        }
        return (await self._write(_INSERT, params)) or _never()

    async def mark_sent(
        self, delivery_id: int, http_status: int | None = None
    ) -> DeliveryRow | None:
        return await self._write(_MARK_SENT, {"id": delivery_id, "http_status": http_status})

    async def mark_failed(
        self, delivery_id: int, error: str, http_status: int | None = None
    ) -> DeliveryRow | None:
        return await self._write(
            _MARK_FAILED, {"id": delivery_id, "error": error, "http_status": http_status}
        )

    async def mark_suppressed(self, delivery_id: int, reason: str) -> DeliveryRow | None:
        return await self._write(_MARK_SUPPRESSED, {"id": delivery_id, "reason": reason})

    async def ack(self, delivery_id: int, user_id: str) -> DeliveryRow | None:
        return await self._write(_ACK_ONE, {"id": delivery_id, "by": user_id})

    async def get_owned(self, delivery_id: int, user_id: str) -> DeliveryRow | None:
        """`scope: self`: another user's delivery is indistinguishable from a missing one."""
        async with self._relational.unit_of_work() as uow:
            m = await uow.session.execute(_GET_OWNED, {"id": delivery_id, "by": user_id})
            row = m.mappings().first()
        return None if row is None else _row(row)

    async def get(self, delivery_id: int) -> DeliveryRow | None:
        """Unscoped read; the caller decides ownership (and audits a foreign id)."""
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_GET, {"id": delivery_id})).mappings().first()
        return None if row is None else _row(row)

    async def alert_owner(self, alert_id: str) -> str | None:
        """`alerts.owner_user_id`, deleted alerts included; None for an unknown alert."""
        async with self._relational.unit_of_work() as uow:
            got = (await uow.session.execute(_ALERT_OWNER, {"id": alert_id})).first()
        return None if got is None else str(got[0])

    async def report_desktop(
        self, delivery_id: int, *, user_id: str, error: str | None, notice_title: str
    ) -> DeliveryRow | None:
        """The shell's outcome for *user_id*'s `desktop` row still `queued`: `error is None` is
        `queued -> sent`; otherwise `queued -> failed` with *error* plus ONE in-app
        channel-failure notice, in one transaction (as the dispatcher's terminal failure).
        None when the row is not that user's queued desktop delivery: a repeated report, or one
        racing another, is a no-op."""
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            params: dict[str, Any] = {"id": delivery_id, "by": user_id}
            if error is None:
                m = (await run(_DESKTOP_SENT, params)).mappings().first()
            else:
                m = (await run(_DESKTOP_FAILED, params | {"error": error})).mappings().first()
                if m is not None:
                    await run(CHANNEL_FAILURE_NOTICE, {
                        "alert_id": m["alert_id"], "user_id": m["user_id"], "title": notice_title,
                        "context": failure_notice_context(delivery_id),
                    })  # fmt: skip
            await uow.commit()
        return None if m is None else _row(m)

    async def ack_all(self, user_id: str, cap: int = 1000) -> list[int]:
        """One bounded batch: the ids it acknowledged (the `alerts` topic's deltas); callers
        loop while a batch comes back full (`cap` ids)."""
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_ACK_ALL, {"by": user_id, "cap": cap})
            ids = [int(r[0]) for r in res.all()]
            await uow.commit()
        return ids

    async def fetch_expired(self, days: int, limit: int = 5000) -> list[DeliveryRow]:
        """Oldest rows past the hot window (E40-T01); archived before `delete_ids`."""
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_EXPIRED, {"days": days, "limit": limit})).mappings()
            return [_row(m) for m in rows]

    async def delete_ids(self, ids: list[int]) -> int:
        """Retention delete; the DB trigger permits it only for `cv_owner` sessions."""
        if not ids:
            return 0
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_DELETE_IDS, {"ids": ids})
            await uow.commit()
        return int(getattr(res, "rowcount", 0) or 0)

    async def get_many(self, delivery_ids: Sequence[int]) -> list[DeliveryRow]:
        """The rows of *delivery_ids* that exist, by id (the `alerts` topic's deltas). Unscoped and
        internal, never a request path: the topic routes each row by its own `user_id`."""
        if not delivery_ids:
            return []
        params = {"ids": sorted(set(delivery_ids))}
        async with self._relational.unit_of_work() as uow:
            return [_row(m) for m in (await uow.session.execute(_GET_MANY, params)).mappings()]

    async def failure_notices(
        self, user_ids: Sequence[str], failed_ids: Sequence[int]
    ) -> list[DeliveryRow]:
        """The unacknowledged channel-failure notices raised for *failed_ids* (the dispatcher's
        terminal failure and the desktop report-back write one each, in the failure's own
        transaction). Internal, never a request path: the topic routes each by its `user_id`."""
        if not user_ids or not failed_ids:
            return []
        params = {"users": sorted(set(user_ids)), "failed": sorted({str(i) for i in failed_ids})}
        async with self._relational.unit_of_work() as uow:
            return [_row(m) for m in (await uow.session.execute(_NOTICES, params)).mappings()]

    async def unacked_count(self, user_id: str) -> int:
        async with self._relational.unit_of_work() as uow:
            return int((await uow.session.execute(_UNACKED, {"user": user_id})).scalar_one())

    async def list_page(
        self,
        *,
        user_id: str,
        alert_id: str | None = None,
        status: str | None = None,
        unacked_only: bool = False,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[DeliveryRow]:
        after_ts, after_id = _delivery_cursor(cursor) if cursor else (None, None)
        params: dict[str, Any] = {
            "user": user_id,
            "alert_id": alert_id,
            "status": status,
            "unacked_only": unacked_only,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "after_ts": after_ts,
            "after_id": after_id,
            "limit": limit + 1,
        }
        async with self._relational.unit_of_work() as uow:
            rows = [_row(r) for r in (await uow.session.execute(_LIST, params)).mappings()]
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = encode_cursor(rows[-1].queued_at, rows[-1].id) if more and rows else None
        return Page(rows, nxt)

    async def _write(self, stmt: sa.TextClause, params: dict[str, Any]) -> DeliveryRow | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(stmt, params)).mappings().first()
            await uow.commit()
        return None if row is None else _row(row)


def _delivery_cursor(cursor: str) -> tuple[datetime, int]:
    """The keyset of `list_page`: a forged id that is no bigint is a `ValueError` (the route's
    400), never a driver error at bind time (#3917)."""
    ts, raw = decode_cursor(cursor)
    try:
        row_id = int(raw)
    except ValueError:
        raise ValueError("invalid cursor") from None
    if not 0 < row_id <= _INT64_MAX:
        raise ValueError("invalid cursor")
    return ts, row_id


def _never() -> DeliveryRow:
    raise RuntimeError("INSERT ... RETURNING produced no row")
