"""`SqlAlchemyBackups`: the `backups` catalogue on Postgres (E42-T05 #966 BK-3a, the reads;
BK-3b adds the writes), built, not wired. Values bound, statements over `COLUMNS` (never
`encryption_ref`), pages `started_at DESC, id DESC` strictly after a keyset position, one unit of
work per call, its statements capped at 1 s (lock waits too) by a transaction-local
`statement_timeout`. Errors are classed by SQLSTATE as in `incidents_sqlalchemy`, but no driver
error leaves (a CHECK's `DETAIL` is the whole row): 08/53/57/58/none/pool/unlisted is
`StorageTierUnavailable`; 22/23/42/XX `StorageQueryFailed`, a 23514 typed by the constraint its
violation names (none: `0032`'s guard). Logged with the call, type and SQLSTATE only; raised
outside the `except`, with no cause or context.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy import exc as sa_exc

from candleviewer.db.models import backups as _TABLE
from candleviewer.storage.errors import (
    BackupCheckViolation,
    BackupWriteOnceViolation,
    StorageError,
    StorageQueryFailed,
    StorageTierUnavailable,
)
from candleviewer.storage.repositories import backups as port
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

_C = _TABLE.c
STATEMENT_TIMEOUT: Final = "1s"  # per statement, lock waits included: the admin reads' cap
_TIMEOUT = sa.text("SELECT set_config('statement_timeout', :timeout, true)")  # true: this txn only
_SQLSTATE = re.compile(r"[0-9A-Z]{5}")
_BUG_CLASSES = frozenset({"22", "23", "42", "XX"})  # data, constraint, syntax/access, internal
_REFUSED = "23514"  # check_violation: `0032`'s guard, a CHECK, or a domain's
COLUMNS = (
    _C.id, _C.kind, _C.status, _C.target_path, _C.size_bytes, _C.checksum_sha256, _C.encrypted,
    _C.covers_to, _C.verified_at, _C.error_message, _C.triggered_by, _C.started_at,
    _C.finished_at, _C.retention_until, _C.deleted_at,
)  # fmt: skip


def _sqlstate(exc: BaseException) -> str | None:
    """The five-character SQLSTATE the driver reported, if it is one: never its message."""
    state = getattr(getattr(exc, "orig", None), "sqlstate", None)
    return state if isinstance(state, str) and _SQLSTATE.fullmatch(state) else None


def _constraint(exc: BaseException) -> str | None:
    """The constraint named on asyncpg's error (the adapted one's cause) or in psycopg's `diag`."""
    orig = getattr(exc, "orig", None)
    sources = (getattr(orig, "__cause__", None), getattr(orig, "diag", None))
    names = [getattr(source, "constraint_name", None) for source in sources]
    return next((name for name in names if isinstance(name, str)), None)


def _failure(op: str, exc: Exception) -> StorageError:
    state = _sqlstate(exc)
    if isinstance(exc, sa_exc.DBAPIError):  # the driver's own error: the statement, or the server
        outage = (state or "")[:2] not in _BUG_CLASSES
    else:  # unreachable, or the pool is exhausted; any other is a statement SQLAlchemy refused
        outage = isinstance(exc, OSError | sa_exc.TimeoutError)
    structlog.get_logger(__name__).error(
        "backups_store_failed", op=op, outage=outage, error=type(exc).__name__, sqlstate=state
    )
    if outage:
        return StorageTierUnavailable(f"backups: {op} failed")
    if state == _REFUSED:
        name = _constraint(exc)
        if name is None:  # `0032`'s guard raises naming no constraint; a CHECK names its own
            return BackupWriteOnceViolation("backups: the write-once guard refused the write")
        if name in port.BACKUP_CHECKS:
            return BackupCheckViolation(name)
    return StorageQueryFailed(state)


class SqlAlchemyBackups:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational

    async def _run(self, op: str, stmt: sa.Executable) -> list[dict[str, Any]]:
        """One statement in its own capped unit of work."""
        try:
            async with self._rel.unit_of_work() as uow:
                await uow.session.execute(_TIMEOUT, {"timeout": STATEMENT_TIMEOUT})
                return [dict(row) for row in (await uow.session.execute(stmt)).mappings()]
        except (OSError, sa_exc.SQLAlchemyError) as exc:
            failure = _failure(op, exc)
        raise failure  # outside the `except`: no cause and no context, so no driver text

    async def _one(self, op: str, stmt: sa.Executable) -> port.BackupRow | None:
        rows = await self._run(op, stmt)
        return port.BackupRow(**rows[0]) if rows else None

    async def page(
        self,
        kind: port.BackupKind | None,
        status: port.BackupStatus | None,
        after: port.Position | None,
        limit: int,
    ) -> list[port.BackupRow]:
        stmt = sa.select(*COLUMNS)
        if kind is not None:
            stmt = stmt.where(_C.kind == kind)
        if status is not None:
            stmt = stmt.where(_C.status == status)
        if after is not None:  # `started_at <=` is the index-range bound beside the keyset
            at, rid = after
            stmt = stmt.where(_C.started_at <= at, sa.or_(_C.started_at < at, _C.id < rid))
        stmt = stmt.order_by(_C.started_at.desc(), _C.id.desc()).limit(limit)
        return [port.BackupRow(**row) for row in await self._run("page", stmt)]

    async def get(self, backup_id: UUID) -> port.BackupRow | None:
        return await self._one("get", sa.select(*COLUMNS).where(_C.id == backup_id))

    async def last_success_by_kind(self) -> dict[port.BackupKind, datetime]:
        kept = sa.and_(_C.deleted_at.is_(None), _C.finished_at.is_not(None))
        latest = sa.func.max(_C.finished_at).label("finished_at")
        stmt = sa.select(_C.kind, latest).where(_C.status.in_(port.SUCCESS_STATUSES), kept)
        rows = await self._run("last_success_by_kind", stmt.group_by(_C.kind))
        return {row["kind"]: row["finished_at"] for row in rows}

    async def usable_count(self, kind: port.BackupKind) -> int:
        verified = sa.and_(_C.status.in_(port.VERIFIED_STATUSES), _C.verified_at.is_not(None))
        usable = sa.and_(_C.kind == kind, verified, _C.deleted_at.is_(None))
        rows = await self._run("usable_count", sa.select(sa.func.count().label("n")).where(usable))
        return int(rows[0]["n"])


#: Checked by mypy, which CI runs on `candleviewer`: the store satisfies its port at each slice.
_SATISFIES_PORT: Callable[[SqlAlchemyRelationalRepository], port.BackupStore] = SqlAlchemyBackups
