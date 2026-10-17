"""`SqlAlchemyIncidents`: the read side of the `incidents` table (E42-T05, migration `0028`), and
`record_occurrence`, its write side.

One keyset page of the materialised incident read model behind `GET /admin/incidents`. The
statement is SQLAlchemy Core over `db.models.incidents` with every value bound, an explicit
column list and no `system_events` read; the serving order `last_seen_at DESC, id DESC` rides
`ix_incidents_seen` and `ix_incidents_status_seen`. A read caps server work at `READ_TIMEOUT`.

An error is classed by its SQLSTATE, the code the driver reports, not by the SQLAlchemy exception
type: asyncpg reports a statement timeout and a data error as the same generic `DBAPIError`. A
database that cannot serve the read leaves as `StorageTierUnavailable` with no driver text (it can
carry the DSN), its class and SQLSTATE logged here: classes 08 (connection), 53 (resources), 57
(operator intervention, with the statement timeout 57014), 58 (system), no SQLSTATE at all, a lost
socket or an exhausted pool. A statement the database refuses is a bug and keeps its type:
classes 22 (data), 23 (constraint), 42 (syntax or access rule) and XX (internal). Any other class
is an outage too: the read is idempotent, so a retry is harmless, and the logged SQLSTATE shows one
that never clears. Rows are `IncidentRow`s built by column name, so a drifted column fails loudly.

The write side materialises an `error` or `critical` system event into its incident in the
writer's own transaction (`21-database-schema.md` 3.10.2a): one `INSERT ... ON CONFLICT
(component, signature) DO UPDATE` on `ux_incidents_group`, never a read followed by a write. Under
READ COMMITTED a second writer of the same group waits for the first one's row lock, then applies
its update to the committed row, so concurrent writers never raise a unique violation and never
lose an occurrence. The `SET` holds the rules: one more occurrence; the first and last seen times
widen to the event's time; `detail` follows the latest event; `severity` keeps the worst; a
`resolved` incident reopens as `open`, and an `acknowledged` one does only when the event raises
`severity` from `error` to `critical`, both clearing the acknowledgement; `resolved_at` is cleared,
since the group now holds an unresolved event, so `inc_resolved` holds. `title` is the normalised
message, the same for the whole group, so a conflict never rewrites it.

`purge_resolved` is the retention side (21 Sec.7): one batch of `resolved` incidents last seen more
than the given months ago, oldest first, on `ix_incidents_status_seen`; open and acknowledged rows
are kept.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.db.models import incidents as _TABLE
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import _TIMEOUT, READ_TIMEOUT
from candleviewer.storage.repositories.incident_grouping import IncidentOccurrence
from candleviewer.storage.repositories.incidents import IncidentRow, Position
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_C = _TABLE.c
#: Upper bound for one purge call, so a single transaction stays short.
MAX_PURGE_BATCH: Final = 10_000
_SQLSTATE = re.compile(r"[0-9A-Z]{5}")
#: SQLSTATE classes of a statement the database refuses: data, constraint, syntax/access, internal.
_BUG_CLASSES = frozenset({"22", "23", "42", "XX"})
COLUMNS = (
    _C.id, _C.component, _C.signature, _C.severity, _C.status, _C.title, _C.detail,
    _C.occurrences, _C.first_seen_at, _C.last_seen_at, _C.acknowledged_by, _C.acknowledged_at,
    _C.resolved_at, _C.runbook_ref,
)  # fmt: skip


def _sqlstate(exc: BaseException) -> str | None:
    """The five-character SQLSTATE the driver reported, if it is one: never its message."""
    state = getattr(getattr(exc, "orig", None), "sqlstate", None)
    return state if isinstance(state, str) and _SQLSTATE.fullmatch(state) else None


def _is_outage(exc: BaseException) -> bool:
    if isinstance(exc, sa_exc.DBAPIError):  # the driver's own error: the statement, or the server
        return (_sqlstate(exc) or "")[:2] not in _BUG_CLASSES
    return isinstance(exc, OSError | sa_exc.TimeoutError)  # unreachable; or the pool is exhausted


def purge_statement(older_than_months: int, limit: int) -> sa.Delete:
    """At most `limit` expired `resolved` rows, oldest first. The `DELETE` repeats the predicate:
    under READ COMMITTED a row a new occurrence reopened after the batch was picked is re-checked
    against its new version and kept."""
    cutoff = sa.func.now() - sa.func.make_interval(0, older_than_months)
    expired = sa.and_(_C.status == "resolved", _C.last_seen_at < cutoff)
    batch = sa.select(_C.id).where(expired).order_by(_C.last_seen_at).limit(limit)
    return sa.delete(_TABLE).where(_C.id.in_(batch), expired)


def page_statement(status: str | None, after: Position | None, limit: int) -> sa.Select[Any]:
    """`last_seen_at <=` is the redundant index-range bound beside the keyset comparison."""
    stmt = sa.select(*COLUMNS)
    if status is not None:
        stmt = stmt.where(_C.status == status)
    if after is not None:
        seen, rid = after
        stmt = stmt.where(_C.last_seen_at <= seen, sa.or_(_C.last_seen_at < seen, _C.id < rid))
    return stmt.order_by(_C.last_seen_at.desc(), _C.id.desc()).limit(limit)


class SqlAlchemyIncidents:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational

    async def page(
        self, *, status: str | None, after: Position | None, limit: int
    ) -> list[IncidentRow]:
        try:
            async with self._rel.unit_of_work() as uow:  # read-only: no commit
                await uow.session.execute(_TIMEOUT, {"timeout": READ_TIMEOUT})
                result = await uow.session.execute(page_statement(status, after, limit))
                return [IncidentRow(**row) for row in result.mappings()]
        except (OSError, sa_exc.SQLAlchemyError) as exc:
            if not _is_outage(exc):
                raise
            structlog.get_logger(__name__).error(
                "incidents_read_failed", error=type(exc).__name__, sqlstate=_sqlstate(exc)
            )
            raise StorageTierUnavailable("incidents: read failed") from None

    async def purge_resolved(self, older_than_months: int, limit: int) -> int:
        """Delete one batch of expired `resolved` incidents; the number of rows deleted."""
        if older_than_months < 1 or not 1 <= limit <= MAX_PURGE_BATCH:
            raise ValueError("purge needs older_than_months >= 1 and 1 <= limit <= MAX_PURGE_BATCH")
        async with self._rel.unit_of_work() as uow:
            result = await uow.session.execute(purge_statement(older_than_months, limit))
            await uow.commit()
        return int(getattr(result, "rowcount", 0))


def upsert_statement(occ: IncidentOccurrence, *, seen_at: datetime, incident_id: UUID) -> Insert:
    """The occurrence as a new `open` incident, or, for a known group, its update in place."""
    new = pg_insert(_TABLE).values(
        id=incident_id,
        component=occ.component,
        signature=occ.signature,
        severity=occ.severity,
        status="open",
        title=occ.title,
        detail=occ.detail,
        occurrences=1,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    old, event = _C, new.excluded
    reset = sa.or_(  # back to `open`, acknowledgement cleared
        old.status == "resolved",
        sa.and_(
            old.status == "acknowledged", old.severity == "error", event.severity == "critical"
        ),
    )
    return new.on_conflict_do_update(
        index_elements=[old.component, old.signature],
        set_={
            "occurrences": old.occurrences + 1,
            "first_seen_at": sa.func.least(old.first_seen_at, event.first_seen_at),
            "last_seen_at": sa.func.greatest(old.last_seen_at, event.last_seen_at),
            "detail": sa.case(
                (event.last_seen_at >= old.last_seen_at, event.detail), else_=old.detail
            ),
            "severity": sa.func.greatest(old.severity, event.severity),
            "status": sa.case((reset, "open"), else_=old.status),
            "acknowledged_by": sa.case((reset, sa.null()), else_=old.acknowledged_by),
            "acknowledged_at": sa.case((reset, sa.null()), else_=old.acknowledged_at),
            "resolved_at": sa.null(),
        },
    )


async def record_occurrence(
    session: AsyncSession, occ: IncidentOccurrence, *, seen_at: datetime
) -> None:
    """Upsert the event's incident in the caller's transaction; the caller commits both rows."""
    await session.execute(upsert_statement(occ, seen_at=seen_at, incident_id=uuid4()))
