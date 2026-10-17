"""The `incidents` read port and its row (E42-T05): what `GET /admin/incidents` reads from the
materialised table (`21-database-schema.md` 3.10.2a). No driver is imported here, so the admin
module depends on this and never on SQLAlchemy; `incidents_sqlalchemy` is the Postgres side."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

#: A keyset position: `(last_seen_at, id)` of the last row of the previous page.
Position = tuple[datetime, UUID]


@dataclass(frozen=True, slots=True)
class IncidentRow:
    """One `incidents` row; the field names are the contract's `Incident` properties. `title` is
    `None` only after the admin read model dropped a text it could not redact."""

    id: UUID
    component: str
    signature: str
    severity: str
    status: str
    title: str | None
    detail: str | None
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    runbook_ref: str | None


class IncidentStore(Protocol):
    async def page(
        self, *, status: str | None, after: Position | None, limit: int
    ) -> list[IncidentRow]:
        """At most `limit` rows, newest first, strictly after `after` (the top when `None`);
        `StorageTierUnavailable` when the table cannot be read."""
