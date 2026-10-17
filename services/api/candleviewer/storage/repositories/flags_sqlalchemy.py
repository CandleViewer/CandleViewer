"""Postgres flag repository over `feature_flags` and `feature_flag_overrides` (migration
`0027_feature_flags`, E42-T03, `21-database-schema.md` 3.9). `storage` may not import `admin`
(C-3.1), so its rows are storage types; the composition root adapts them to the admin `FlagStore`.

Static, parameterised `sa.text` only. Values are JSON as stored and never interpreted here: a
value that does not fit its flag's kind reaches the service as it is, and only that flag fails
closed (`22-api-openapi.yaml` `listFeatureFlags`: "A single unreadable stored row ... is not an
outage"). A `percentage` row's value is `rollout_pct`, any other row's `default_value` (3.9), by
the row's own `kind`. `ensure` is one `INSERT ... ON CONFLICT (key) DO NOTHING`: insert-only, so
a flag whose kind changes in code keeps its old row until a data migration rewrites it. `load` is
one statement, so one snapshot, with every override kept; `feature_flag_overrides.expires_at` is
not read, as nothing defines or writes it.

`write` is one READ COMMITTED transaction: the read budget as `statement_timeout` and
`lock_timeout`, the row `FOR UPDATE` and its overrides, `prepare` with the row as stored, the
`updated_at` check, the value, the user overrides (role overrides are kept), the commit.
`updated_at` compares exactly: `timestamptz` and `datetime.isoformat()` both carry microseconds,
and each write moves it on by at least one, by the database clock. A `percentage` row takes only
an integer: repairing it to another kind's value needs the data migration too (`ff_shape`).

A database that cannot serve the call is `StorageTierUnavailable` with a fixed message (no driver
text, no bound value: C-12.6), a failed COMMIT included, though that write may have landed; any
other database error is a bug and keeps its type, and what `prepare` raises reaches the caller as
is.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy import exc as sa_exc

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)


@dataclass(frozen=True, slots=True)
class FlagSeed:
    """A registered flag at its default, for `ensure`; `kind` is a `flag_kind` value."""

    key: str
    kind: str
    description: str
    default: object
    is_killswitch: bool
    variants: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FlagRow:
    """One flag as stored, with every override keyed by user id or by role name."""

    value: object
    user_overrides: Mapping[UUID, object]
    role_overrides: Mapping[str, object]
    updated_at: datetime
    updated_by: UUID | None


@dataclass(frozen=True, slots=True)
class FlagChange:
    """The value, the whole new set of user overrides, the `updated_at` read, and the writer."""

    value: object
    user_overrides: Mapping[UUID, object]
    expected_updated_at: datetime
    actor: UUID


class StaleFlagRowError(Exception):
    """`expected_updated_at` does not name the locked row; `current` is that row."""

    def __init__(self, current: FlagRow) -> None:
        super().__init__("stale flag row")
        self.current = current


class FlagRowMissingError(LookupError):
    """A row the write needs is gone: the flag's own (its start-up `ensure` failed) or an override
    user's (deleted after the writer checked it)."""


#: Awaited under the row lock with the row as stored; returns the change, or raises to write none.
RowPrepare = Callable[[FlagRow], Awaitable[FlagChange]]

#: SQLSTATE classes of "the database cannot serve this now": connection (08), transaction rollback
#: incl. deadlock (40), resources (53), operator intervention incl. statement timeout 57014 (57),
#: system (58); plus lock_not_available 55P03. Data (22), integrity (23) and syntax or access (42)
#: errors are bugs, and so is a missing SQLSTATE (as the settings repository, #2944).
_OUTAGE_CLASSES: Final = frozenset({"08", "40", "53", "57", "58"})
_LOCK_NOT_AVAILABLE: Final = "55P03"
_FOREIGN_KEY: Final = "23503"

_TIMEOUTS = sa.text(
    "SELECT set_config('statement_timeout', :budget, true), "
    "set_config('lock_timeout', :budget, true)"
)
_ENSURE = sa.text(
    "INSERT INTO feature_flags (id, key, kind, description, default_value, rollout_pct, "
    "variants, is_killswitch) SELECT gen_random_uuid(), s.key, s.kind, s.description, "
    "s.default_value, s.rollout_pct, s.variants, s.is_killswitch "
    "FROM jsonb_to_recordset(CAST(:seeds AS jsonb)) AS s(key text, kind flag_kind, "
    "description text, default_value jsonb, rollout_pct smallint, variants jsonb, "
    "is_killswitch boolean) ON CONFLICT (key) DO NOTHING"
)
_LOAD = sa.text(
    "SELECT f.key, f.kind::text AS kind, f.default_value, f.rollout_pct, f.updated_at, "
    "f.updated_by, o.user_id, r.name::text AS role, o.value AS override FROM feature_flags f "
    "LEFT JOIN feature_flag_overrides o ON o.feature_flag_id = f.id "
    "LEFT JOIN roles r ON r.id = o.role_id ORDER BY f.key, o.created_at, o.id"
)
_LOCK = sa.text(
    "SELECT id, kind::text AS kind, default_value, rollout_pct, updated_at, updated_by "
    "FROM feature_flags WHERE key = :key FOR UPDATE"
)
_OVERRIDES = sa.text(
    "SELECT o.user_id, r.name::text AS role, o.value AS override FROM feature_flag_overrides o "
    "LEFT JOIN roles r ON r.id = o.role_id WHERE o.feature_flag_id = CAST(:id AS uuid) "
    "ORDER BY o.created_at, o.id"
)
# clock_timestamp(), not now(): a writer queued on the lock is stamped after its wait; greatest()
# keeps the token moving even if the clock steps back.
_UPDATE = sa.text(
    "UPDATE feature_flags SET "
    "default_value = CASE WHEN kind = 'percentage' THEN default_value "
    "ELSE CAST(:value AS jsonb) END, "
    "rollout_pct = CASE WHEN kind = 'percentage' THEN CAST(:pct AS smallint) "
    "ELSE rollout_pct END, updated_by = CAST(:by AS uuid), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:id AS uuid) "
    "RETURNING kind::text AS kind, default_value, rollout_pct, updated_at, updated_by"
)
_DROP_USERS = sa.text(
    "DELETE FROM feature_flag_overrides WHERE feature_flag_id = CAST(:id AS uuid) "
    "AND user_id IS NOT NULL AND user_id <> ALL(CAST(:keep AS uuid[]))"
)
# An unchanged override keeps its row (`set_by`, `created_at`): only a new value is written.
# `->` keeps a JSON null a jsonb null (`jsonb_to_recordset` would make it SQL NULL).
_PUT_USERS = sa.text(
    "INSERT INTO feature_flag_overrides (id, feature_flag_id, user_id, value, set_by) "
    "SELECT gen_random_uuid(), CAST(:id AS uuid), CAST(o ->> 'user_id' AS uuid), o -> 'value', "
    "CAST(:by AS uuid) FROM jsonb_array_elements(CAST(:overrides AS jsonb)) AS o "
    "ON CONFLICT (feature_flag_id, user_id) WHERE user_id IS NOT NULL DO UPDATE "
    "SET value = EXCLUDED.value, set_by = EXCLUDED.set_by "
    "WHERE feature_flag_overrides.value IS DISTINCT FROM EXCLUDED.value"
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
def _outage(own: Sequence[BaseException] = ()) -> Iterator[None]:
    """A database that cannot serve the call becomes `StorageTierUnavailable`; a bug, and what
    `prepare` raised (`own`, by identity), stay as they are."""
    try:
        yield
    except (OSError, sa_exc.SQLAlchemyError) as exc:
        if any(exc is mine for mine in own) or not _is_outage(exc):
            raise
        state = _sqlstate(exc)
        _log().error(
            "feature_flag_repository_unavailable", error=type(exc).__name__, sqlstate=state
        )
        raise StorageTierUnavailable("the feature-flag store is unavailable") from None


def _seed(seed: FlagSeed) -> dict[str, Any]:
    pct = seed.kind == "percentage"
    return {
        "key": seed.key,
        "kind": seed.kind,
        "description": seed.description,
        "default_value": False if pct else seed.default,  # the column default: unread when pct
        "rollout_pct": seed.default if pct else None,
        "variants": list(seed.variants) if seed.kind == "variant" else None,
        "is_killswitch": seed.is_killswitch,
    }


def _flag(head: Mapping[Any, Any], overrides: Iterable[Mapping[Any, Any]] = ()) -> FlagRow:
    users: dict[UUID, object] = {}
    roles: dict[str, object] = {}
    for o in overrides:  # a JSON null is an (unreadable) override; NULL targets are none at all
        if o["user_id"] is not None:
            users[o["user_id"]] = o["override"]
        elif o["role"] is not None:
            roles[o["role"]] = o["override"]
    value = head["rollout_pct"] if head["kind"] == "percentage" else head["default_value"]
    return FlagRow(value, users, roles, head["updated_at"].astimezone(UTC), head["updated_by"])


class SqlAlchemyFlagRepository:
    """The flag rows over one relational repository; a read or a write runs under the budget."""

    def __init__(self, relational: SqlAlchemyRelationalRepository, *, read_budget_ms: int) -> None:
        if read_budget_ms < 1:  # `0` would switch the server-side bound off
            raise ValueError("the read budget must be at least 1 ms")
        self._relational, self._budget = relational, f"{read_budget_ms}ms"

    async def ensure(self, seeds: Iterable[FlagSeed]) -> None:
        """Insert every seed that has no row, at its default; an existing row is left alone."""
        payload = json.dumps([_seed(seed) for seed in seeds])
        with _outage():
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_ENSURE, {"seeds": payload})
                await uow.commit()

    async def load(self) -> Mapping[str, FlagRow]:
        """Every flag and its overrides, from one statement."""
        with _outage():
            async with self._relational.unit_of_work() as uow:  # read-only: no commit
                await uow.session.execute(_TIMEOUTS, {"budget": self._budget})
                rows = (await uow.session.execute(_LOAD)).mappings().all()
        flags: dict[str, list[Mapping[Any, Any]]] = {}
        for r in rows:  # one row per override, or one with NULL targets for a flag with none
            flags.setdefault(r["key"], []).append(r)
        return {key: _flag(rs[0], rs) for key, rs in flags.items()}

    async def write(self, key: str, prepare: RowPrepare) -> FlagRow:
        """Lock the row, `prepare` it once, refuse a stale change, write it; the new row."""
        own: list[BaseException] = []
        with _outage(own):
            async with self._relational.unit_of_work() as uow:
                s = uow.session
                await s.execute(_TIMEOUTS, {"budget": self._budget})
                head = (await s.execute(_LOCK, {"key": key})).mappings().first()
                if head is None:
                    raise FlagRowMissingError(key)
                flag_id = str(head["id"])
                row = _flag(head, (await s.execute(_OVERRIDES, {"id": flag_id})).mappings().all())
                try:
                    change = await prepare(row)
                except Exception as exc:
                    own.append(exc)
                    raise
                if change.expected_updated_at != row.updated_at:
                    raise StaleFlagRowError(row)
                value, by = change.value, str(change.actor)
                pct = value if type(value) is int else None  # never a bool: it is an int too
                params = {"id": flag_id, "value": json.dumps(value), "pct": pct, "by": by}
                written = (await s.execute(_UPDATE, params)).mappings().one()
                users = [{"user_id": str(u), "value": v} for u, v in change.user_overrides.items()]
                keep = [o["user_id"] for o in users]
                await s.execute(_DROP_USERS, {"id": flag_id, "keep": keep})
                put = {"id": flag_id, "overrides": json.dumps(users), "by": by}
                try:
                    await s.execute(_PUT_USERS, put)
                except sa_exc.IntegrityError as exc:
                    if _sqlstate(exc) != _FOREIGN_KEY:
                        raise
                    raise FlagRowMissingError("an override's user") from None
                await uow.commit()
        new = dict(change.user_overrides)
        return replace(_flag(written), user_overrides=new, role_overrides=row.role_overrides)


__all__ = [
    "FlagChange",
    "FlagRow",
    "FlagRowMissingError",
    "FlagSeed",
    "RowPrepare",
    "SqlAlchemyFlagRepository",
    "StaleFlagRowError",
]
