"""`SqlAlchemyIncidents`: the read side of the `incidents` table (E42-T05, migration `0028`).

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
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy import exc as sa_exc

from candleviewer.db.models import incidents as _TABLE
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import _TIMEOUT, READ_TIMEOUT
from candleviewer.storage.repositories.incidents import IncidentRow, Position
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_C = _TABLE.c
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
