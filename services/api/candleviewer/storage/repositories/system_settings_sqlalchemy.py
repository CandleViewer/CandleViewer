"""Postgres `SystemSettings` over the `settings` table (migration `0025_settings`, E42-T01).

Static, parameterised `sa.text` only, every statement pinned to `scope = 'system'` (no `UNSCOPED`
exception, unlike the neighbouring repositories). A read caps server work at `READ_TIMEOUT`.

`put_string` is one READ COMMITTED transaction: the key's advisory lock (writers of one key queue,
also the first, when there is no row to lock yet) -> the row as it stands (the audit record's
"before") -> the upsert -> the write-ahead hook (C-2.9), bounded while the locks are held (#2510)
-> the commit. A refused or timed-out hook rolls everything back. The append cannot be undone, so
a COMMIT that fails after the hook can leave a record for an unchanged setting: the trail may
over-report an attempt, never under-report (as `SqlAlchemyUserRoleStore.apply_roles`).

A database that cannot serve the call is `StorageTierUnavailable` with a fixed message (no driver
text, no bound value: C-12.6); any other database error is a bug and keeps its type.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy import exc as sa_exc

from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.system_settings import StoredSetting, WriteAhead
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

#: Server-side cap per read, above the admin slice's 300 ms budget, which cancels client-side first.
READ_TIMEOUT: Final = "1s"
#: SQLSTATE classes of "the database cannot serve this now": connection (08), transaction rollback
#: incl. deadlock (40), resources (53), operator intervention incl. statement timeout 57014 (57),
#: system (58); plus lock_not_available 55P03. Data (22), integrity (23) and syntax or access (42)
#: errors are bugs, and so is a missing SQLSTATE.
_OUTAGE_CLASSES: Final = frozenset({"08", "40", "53", "57", "58"})
_LOCK_NOT_AVAILABLE: Final = "55P03"

_TIMEOUT = sa.text("SELECT set_config('statement_timeout', :timeout, true)")
_LOCK = sa.text(
    "SELECT pg_advisory_xact_lock(hashtextextended('cv.settings.system:' || CAST(:key AS text), 0))"
)
_SELECT = sa.text(
    "SELECT value #>> '{}' AS value, updated_at FROM settings WHERE scope = 'system' AND key = :key"
)
# FOR UPDATE: the row lock too, so a writer that skips the advisory lock still waits for this one.
_SELECT_LOCKED = sa.text(
    "SELECT value #>> '{}' AS value, updated_at FROM settings "
    "WHERE scope = 'system' AND key = :key FOR UPDATE"
)
# clock_timestamp(), not now(): now() is the transaction's start, before a queued writer's wait.
_UPSERT = sa.text(
    "INSERT INTO settings (id, scope, key, value, value_type, is_secret, updated_by, "
    "created_at, updated_at) SELECT gen_random_uuid(), 'system', :key, "
    "to_jsonb(CAST(:value AS text)), 'string', false, CAST(:by AS uuid), c.t, c.t "
    "FROM (SELECT clock_timestamp() AS t) c "
    "ON CONFLICT (key) WHERE scope = 'system' DO UPDATE SET value = EXCLUDED.value, "
    "value_type = 'string', is_secret = false, updated_by = EXCLUDED.updated_by, "
    "updated_at = EXCLUDED.updated_at "
    "RETURNING value #>> '{}' AS value, updated_at"
)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _sqlstate(exc: BaseException) -> str | None:
    """The SQLSTATE a driver error carries: its wrapped error (`orig`), then its causes."""
    orig = getattr(exc, "orig", None)
    for src in (orig, getattr(orig, "__cause__", None), exc.__cause__):
        for attr in ("sqlstate", "pgcode"):
            code = getattr(src, attr, None)
            if isinstance(code, str) and len(code) == 5:
                return code
    return None


def _is_outage(exc: BaseException) -> bool:
    if isinstance(
        exc, OSError | sa_exc.OperationalError | sa_exc.InterfaceError | sa_exc.TimeoutError
    ):
        return True  # unreachable, closed, pool exhausted
    if not isinstance(exc, sa_exc.DBAPIError):
        return False
    if exc.connection_invalidated:
        return True
    state = _sqlstate(exc)
    return state is not None and (state[:2] in _OUTAGE_CLASSES or state == _LOCK_NOT_AVAILABLE)


@contextmanager
def _outage() -> Iterator[None]:
    """A database that cannot serve the call becomes `StorageTierUnavailable`; a bug stays one."""
    try:
        yield
    except WriteAheadTimeout:
        raise  # the hook's bound, not the database's, although it is a `TimeoutError` too
    except (OSError, sa_exc.SQLAlchemyError) as exc:
        if not _is_outage(exc):
            raise
        _log().error(
            "settings_store_unavailable", error=type(exc).__name__, sqlstate=_sqlstate(exc)
        )
        raise StorageTierUnavailable("the settings store is unavailable") from None


def _stored(row: Mapping[Any, Any]) -> StoredSetting:
    text = row["value"]  # `#>>` is SQL NULL for a JSON null: its text is "null"
    return StoredSetting("null" if text is None else str(text), row["updated_at"].astimezone(UTC))


class SqlAlchemySystemSettings:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        self._relational, self._audit_timeout_s = relational, audit_timeout_s

    async def get_string(self, key: str) -> StoredSetting | None:
        with _outage():
            async with self._relational.unit_of_work() as uow:  # read-only: no commit
                await uow.session.execute(_TIMEOUT, {"timeout": READ_TIMEOUT})
                row = (await uow.session.execute(_SELECT, {"key": key})).mappings().first()
        return None if row is None else _stored(row)

    async def put_string(
        self, key: str, value: str, *, updated_by: UUID, write_ahead: WriteAhead
    ) -> StoredSetting:
        with _outage():
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                await s.execute(_LOCK, {"key": key})
                found = (await s.execute(_SELECT_LOCKED, {"key": key})).mappings().first()
                params = {"key": key, "value": value, "by": str(updated_by)}
                stored = _stored((await s.execute(_UPSERT, params)).mappings().one())
                before = None if found is None else _stored(found)
                await bounded_write_ahead(write_ahead(before), self._audit_timeout_s)
                await uow.commit()
        return stored


__all__ = ["READ_TIMEOUT", "SqlAlchemySystemSettings"]
