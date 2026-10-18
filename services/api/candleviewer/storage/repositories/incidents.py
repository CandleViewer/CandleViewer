"""The `incidents` port and its row (E42-T05): what `GET /admin/incidents` reads from the
materialised table (`21-database-schema.md` 3.10.2a), and the acknowledge transition. No driver is
imported here, so the admin module depends on this and never on SQLAlchemy;
`incidents_sqlalchemy` is the Postgres side."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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


class AckOutcome(StrEnum):
    ACKNOWLEDGED = "acknowledged"  # was `open`: moved, the record written
    ALREADY = "already"  # was `acknowledged`: left as it is
    RESOLVED = "resolved"  # nothing to acknowledge: left as it is
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class AckResult:
    outcome: AckOutcome
    row: IncidentRow | None  # as it now stands; `None` only when `MISSING`


#: Awaited in the transition's transaction, after the update and before the commit, with the row
#: as it stood and as it now is, the row locked: it writes the audit record (C-2.9). What it raises
#: rolls the transition back and reaches the caller as it is, so it must raise a type of its own
#: (an `OSError` would be taken for a store outage).
AckWriteAhead = Callable[[IncidentRow, IncidentRow], Awaitable[None]]


class IncidentStore(Protocol):
    async def page(
        self, *, status: str | None, after: Position | None, limit: int
    ) -> list[IncidentRow]:
        """At most `limit` rows, newest first, strictly after `after` (the top when `None`);
        `StorageTierUnavailable` when the table cannot be read."""

    async def acknowledge(
        self, incident_id: UUID, *, by: UUID, write_ahead: AckWriteAhead
    ) -> AckResult:
        """Move an `open` incident to `acknowledged` for `by` under its row lock, `write_ahead`
        awaited before the commit; any other status comes back as it is, with no call to it.
        `StorageTierUnavailable`, `WriteAheadTimeout` and what the hook raises change nothing."""
