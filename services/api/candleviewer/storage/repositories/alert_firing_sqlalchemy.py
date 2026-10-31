"""The alert firing transaction (E40-T03; 21-database-schema.md §3.10.4).

`record_firing` commits the `alert_deliveries` row(s), the `outbox` row(s) and the
`alerts` counter / `enabled` updates in ONE unit of work, so a crash between "decide"
and "send" can neither lose nor duplicate a delivery: either every row exists (and the
E40-T04 poller delivers the pending outbox row exactly once, `ux_outbox_dedup`) or none.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import sqlalchemy as sa

from candleviewer.storage.repositories.alerts import AlertRow
from candleviewer.storage.repositories.alerts_sqlalchemy import _alert
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Static literal SQL only (no string building: Bandit B608 / Semgrep). Columns mirror
#: `ALERT_COLUMNS` (drift asserted by a unit test) plus the `bar_open_ms` of the latest
#: delivery, so a restart rebuilds `once_per_bar` memory from exchange event time.
_LIVE = sa.text(
    "SELECT "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason, "
    "(SELECT (d.context->>'bar_open_ms')::bigint FROM alert_deliveries d "
    "WHERE d.alert_id = alerts.id AND d.context->>'bar_open_ms' IS NOT NULL "
    "ORDER BY d.queued_at DESC, d.id DESC LIMIT 1) AS last_bar_open_ms "
    "FROM alerts WHERE enabled AND deleted_at IS NULL"
)
_GET = sa.text(
    "SELECT "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason, "
    "(SELECT (d.context->>'bar_open_ms')::bigint FROM alert_deliveries d "
    "WHERE d.alert_id = alerts.id AND d.context->>'bar_open_ms' IS NOT NULL "
    "ORDER BY d.queued_at DESC, d.id DESC LIMIT 1) AS last_bar_open_ms "
    "FROM alerts WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
#: Conditional disarm: zero rows => another worker already fired this `once` alert.
_DISARM_ONCE = sa.text(
    "UPDATE alerts SET enabled = false, updated_at = clock_timestamp() "
    "WHERE id = CAST(:id AS uuid) AND enabled AND deleted_at IS NULL"
)
#: The same conditional disarm, recording why the server (not the user) did it (CC-3).
_DISARM_SOURCE = sa.text(
    "UPDATE alerts SET enabled = false, disarm_reason = :reason, "
    "updated_at = clock_timestamp() WHERE id = CAST(:id AS uuid) AND enabled AND deleted_at IS NULL"
)
_BUMP = sa.text(
    "UPDATE alerts SET fire_count = fire_count + 1, last_fired_at = :fired_at "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
_INSERT_DELIVERY = sa.text(
    "INSERT INTO alert_deliveries (alert_id, user_id, channel, status, title, body, context, "
    "error_message) VALUES (CAST(:alert_id AS uuid), CAST(:user_id AS uuid), "
    "CAST(:channel AS alert_channel), CAST(:status AS delivery_status), :title, :body, "
    "CAST(:context AS jsonb), :error) RETURNING id"
)
_INSERT_OUTBOX = sa.text(
    "INSERT INTO outbox (topic, dedup_key, payload) VALUES (:topic, :dedup, "
    "CAST(:payload AS jsonb)) ON CONFLICT (topic, dedup_key) DO NOTHING"
)


@dataclass(frozen=True, slots=True)
class FiringAlertRow(AlertRow):
    """`AlertRow` plus the exchange-time bar of the latest firing (`once_per_bar`)."""

    last_bar_open_ms: int | None = None


def _firing_row(m: Any) -> FiringAlertRow:
    d = dict(m)
    bar = d.pop("last_bar_open_ms", None)
    base = _alert(d)
    return FiringAlertRow(**{f: getattr(base, f) for f in base.__dataclass_fields__},
                          last_bar_open_ms=None if bar is None else int(bar))  # fmt: skip


class SqlAlchemyAlertFiringStore:
    """`alerts.ports.FiringStore` over Postgres."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        topic: str,
        dedup_key: Callable[[int], str],
    ) -> None:
        """`topic`/`dedup_key` come from `alerts.outbox` (M10 may not import M22)."""
        self._relational, self._topic, self._dedup = relational, topic, dedup_key

    async def load_live(self) -> list[AlertRow]:
        async with self._relational.unit_of_work() as uow:
            return [_firing_row(m) for m in (await uow.session.execute(_LIVE)).mappings()]

    async def get(self, alert_id: str) -> AlertRow | None:
        async with self._relational.unit_of_work() as uow:
            m = (await uow.session.execute(_GET, {"id": alert_id})).mappings().first()
        return None if m is None else _firing_row(m)

    async def record_firing(
        self,
        *,
        alert_id: str,
        user_id: str,
        channels: Sequence[str],
        status: str,
        title: str,
        body: str,
        context: dict[str, Any],
        fired_at: datetime,
        once: bool,
        bump: bool,
        disarm_reason: Literal["source_unavailable"] | None = None,
    ) -> list[int] | None:
        ids: list[int] = []
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            if once or disarm_reason is not None:  # both conditional on `enabled`: never interleave
                res = await run(
                    _DISARM_ONCE if disarm_reason is None else _DISARM_SOURCE,
                    (
                        {"id": alert_id}
                        if disarm_reason is None
                        else {"id": alert_id, "reason": disarm_reason}
                    ),
                )
                if not int(getattr(res, "rowcount", 0) or 0):
                    return None  # already disarmed/fired elsewhere; nothing committed
            if bump:
                await run(_BUMP, {"id": alert_id, "fired_at": fired_at})
            ctx_json = json.dumps(context, sort_keys=True, default=str)
            for ch in channels:
                row = await run(_INSERT_DELIVERY, {
                    "alert_id": alert_id, "user_id": user_id, "channel": ch, "status": status,
                    "title": title, "body": body, "context": ctx_json,
                    "error": "storm" if status == "suppressed" else None,
                })  # fmt: skip
                did = int(row.scalar_one())
                ids.append(did)
                if status == "queued":
                    await run(_INSERT_OUTBOX, {
                        "topic": self._topic, "dedup": self._dedup(did),
                        "payload": json.dumps({"delivery_id": did, "alert_id": alert_id,
                                               "channel": ch}),
                    })  # fmt: skip
            await uow.commit()
        return ids
