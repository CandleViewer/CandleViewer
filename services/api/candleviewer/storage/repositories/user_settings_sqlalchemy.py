"""Postgres `UserSettings` over the `settings` table (migration `0025_settings`; E02-T13, #5181).

Static, parameterised `sa.text` only, every statement pinned to `scope = 'user'` and the one user
the call names (`user_id = CAST(:user_id AS uuid)`; the INSERT binds both), so a system-scope row
or another user's row is never read, locked or written. A read caps server work at `READ_TIMEOUT`.
One row per leaf: `key` is the leaf's dotted path (`st_key_fmt`), `value` its JSON and
`value_type` its JSON type, which `jsonb_typeof` reads off the value itself (`st_vtype`).

`apply` is one READ COMMITTED transaction: the user's advisory lock (writers of one user queue, also
when there is no row to lock yet) -> the user's rows as they stand, row-locked (the record's
"before") -> one upsert or delete per leaf, by key, each a no-op unless it changes the row (`jsonb`
equality: a value equal to the stored one moves no `updated_at`) -> when anything changed, the
write-ahead hook (C-2.9), bounded while the locks are held (#2510) -> the commit. A refused or
timed-out hook rolls everything back. The append cannot be undone, so a COMMIT that fails after the
hook can leave a record for an unchanged setting: the trail may over-report an attempt, never
under-report (as `SqlAlchemySystemSettings`).

A database that cannot serve the call is `StorageTierUnavailable` with a fixed message (no driver
text, no bound value: C-12.6); any other database error is a bug, raised as `query_failure` (#2748).
"""

from __future__ import annotations

import json
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
    constraint_of,
    is_outage,
    query_failure,
    sqlstate_of,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)
from candleviewer.storage.repositories.user_settings import (
    LeafChange,
    UserSetting,
    UserSettingsWriteAhead,
)

#: Server-side cap per read: a settings read is one indexed scan of at most one row per leaf.
READ_TIMEOUT: Final = "1s"

_TIMEOUT = sa.text("SELECT set_config('statement_timeout', :timeout, true)")
_LOCK = sa.text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('cv.settings.user:' || CAST(:user_id AS text), 0))"
)
_SELECT = sa.text(
    "SELECT key, value::text AS value, updated_at FROM settings "
    "WHERE scope = 'user' AND user_id = CAST(:user_id AS uuid) ORDER BY key"
)
# FOR UPDATE: the row locks too, so a writer that skips the advisory lock still waits for this one.
_SELECT_LOCKED = sa.text(
    "SELECT key, value::text AS value, updated_at FROM settings "
    "WHERE scope = 'user' AND user_id = CAST(:user_id AS uuid) ORDER BY key FOR UPDATE"
)
# clock_timestamp(), not now(): now() is the transaction's start, before a queued writer's wait. The
# conflict arm writes only a changed value, so RETURNING answers a row only for a change.
_UPSERT = sa.text(
    "INSERT INTO settings (id, scope, user_id, key, value, value_type, is_secret, updated_by, "
    "created_at, updated_at) SELECT gen_random_uuid(), 'user', CAST(:user_id AS uuid), :key, "
    "v.j, jsonb_typeof(v.j), false, CAST(:user_id AS uuid), v.t, v.t "
    "FROM (SELECT CAST(:value AS jsonb) AS j, clock_timestamp() AS t) v "
    "ON CONFLICT (user_id, key) WHERE scope = 'user' DO UPDATE SET value = EXCLUDED.value, "
    "value_type = EXCLUDED.value_type, is_secret = false, updated_by = EXCLUDED.updated_by, "
    "updated_at = EXCLUDED.updated_at WHERE settings.value IS DISTINCT FROM EXCLUDED.value "
    "RETURNING key, value::text AS value, updated_at"
)
_DELETE = sa.text(
    "DELETE FROM settings WHERE scope = 'user' AND user_id = CAST(:user_id AS uuid) "
    "AND key = :key RETURNING key"
)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@contextmanager
def _outage() -> Iterator[None]:
    """A database that cannot serve the call becomes `StorageTierUnavailable`, any other database
    error a `StorageQueryFailed` typed by its facts (#2748), each raised `from None`."""
    try:
        yield
    except WriteAheadTimeout:
        raise  # the hook's bound, not the database's, although it is a `TimeoutError` too
    except (OSError, sa_exc.SQLAlchemyError) as exc:
        if not is_outage(exc):
            raise query_failure(sqlstate_of(exc), constraint_of(exc)) from None
        _log().error(
            "user_settings_store_unavailable", error=type(exc).__name__, sqlstate=sqlstate_of(exc)
        )
        raise StorageTierUnavailable("the settings store is unavailable") from None


def _stored(row: Mapping[Any, Any]) -> UserSetting:
    return UserSetting(str(row["key"]), json.loads(row["value"]), row["updated_at"].astimezone(UTC))


class SqlAlchemyUserSettings:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        self._relational, self._audit_timeout_s = relational, audit_timeout_s

    async def read(self, user_id: UUID) -> tuple[UserSetting, ...]:
        with _outage():
            async with self._relational.unit_of_work() as uow:  # read-only: no commit
                await uow.session.execute(_TIMEOUT, {"timeout": READ_TIMEOUT})
                found = await uow.session.execute(_SELECT, {"user_id": str(user_id)})
                return tuple(_stored(row) for row in found.mappings())

    async def apply(
        self, user_id: UUID, patch: Mapping[str, object], *, write_ahead: UserSettingsWriteAhead
    ) -> tuple[UserSetting, ...]:
        uid = str(user_id)
        with _outage():
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                await s.execute(_LOCK, {"user_id": uid})
                locked = await s.execute(_SELECT_LOCKED, {"user_id": uid})
                held = {row.key: row for row in map(_stored, locked.mappings())}
                after, changes = dict(held), []
                for key in sorted(patch):
                    value, row = patch[key], held.get(key)
                    before = None if row is None else row.value
                    if value is None:
                        if (await s.execute(_DELETE, {"user_id": uid, "key": key})).first():
                            changes.append(LeafChange(key, before, None))
                            after.pop(key, None)
                        continue
                    text = json.dumps(value, allow_nan=False)
                    params = {"user_id": uid, "key": key, "value": text}
                    written = (await s.execute(_UPSERT, params)).mappings().first()
                    if written is not None:
                        after[key] = _stored(written)
                        changes.append(LeafChange(key, before, after[key].value))
                if changes:
                    await bounded_write_ahead(write_ahead(tuple(changes)), self._audit_timeout_s)
                    await uow.commit()
        return tuple(after[key] for key in sorted(after))


__all__ = ["READ_TIMEOUT", "SqlAlchemyUserSettings"]
