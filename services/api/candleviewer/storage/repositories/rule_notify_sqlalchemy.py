"""The `rule.notify` outbox writer (E35-T13; 21-database-schema.md §3.10.4, 24 §11.5).

A rule's `send_notification` writes one `outbox` row per action, keyed by its fire key, so a
retried notification lands once (`ux_outbox_dedup`). No consumer claims the topic until E40 binds
its delivery channels, and the table keeps no retention, so the same unit of work dead-letters the
topic's rows still unclaimed past their TTL (`dead_at`, `last_error` `unclaimed_ttl`), at most a
bounded number per write, never one a worker holds: each row is kept, so its key still dedupes.
`storage` may not import `rules`, so the topic, the TTL and the bound come from the composition
root. Static, parameterised SQL; the payload is never logged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: `last_error` of a row dead-lettered unclaimed: no delivery failed, so no system event.
UNCLAIMED: Final = "unclaimed_ttl"
_INSERT = sa.text(
    "INSERT INTO outbox (topic, dedup_key, payload) VALUES (:topic, :dedup, "
    "CAST(:payload AS jsonb)) ON CONFLICT (topic, dedup_key) DO NOTHING"
)
_DEAD_LETTER = sa.text(
    "UPDATE outbox SET dead_at = now(), last_error = :reason WHERE id IN (SELECT id FROM outbox "
    "WHERE topic = :topic AND processed_at IS NULL AND dead_at IS NULL "
    "AND (locked_until IS NULL OR locked_until < now()) "
    "AND created_at < now() - make_interval(secs => :ttl) ORDER BY id LIMIT :limit "
    "FOR UPDATE SKIP LOCKED)"
)


class SqlAlchemyRuleNotifyOutbox:
    """One topic's writer over Postgres."""

    def __init__(
        self, relational: SqlAlchemyRelationalRepository, *, topic: str, ttl_s: float, limit: int
    ) -> None:
        self._relational, self._topic, self._ttl_s, self._limit = relational, topic, ttl_s, limit

    async def enqueue(self, dedup_key: str, payload: Mapping[str, Any]) -> int:
        """The row, landed once per key, and the topic's expired unclaimed rows dead-lettered, in
        one unit of work; how many were dead-lettered."""
        params = {"topic": self._topic, "dedup": dedup_key,
                  "payload": json.dumps(dict(payload), sort_keys=True)}  # fmt: skip
        sweep = {"topic": self._topic, "reason": UNCLAIMED, "ttl": self._ttl_s,
                 "limit": self._limit}  # fmt: skip
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_INSERT, params)
            swept = await uow.session.execute(_DEAD_LETTER, sweep)
            await uow.commit()
        return int(getattr(swept, "rowcount", 0) or 0)
