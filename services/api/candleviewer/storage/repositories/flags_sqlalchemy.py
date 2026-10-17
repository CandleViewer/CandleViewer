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

A database that cannot serve the call is `StorageTierUnavailable` with a fixed message (no driver
text, no bound value: C-12.6); any other database error is a bug and keeps its type.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
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


#: SQLSTATE classes of "the database cannot serve this now": connection (08), transaction rollback
#: incl. deadlock (40), resources (53), operator intervention incl. statement timeout 57014 (57),
#: system (58); plus lock_not_available 55P03. Data (22), integrity (23) and syntax or access (42)
#: errors are bugs, and so is a missing SQLSTATE (as the settings repository, #2944).
_OUTAGE_CLASSES: Final = frozenset({"08", "40", "53", "57", "58"})
_LOCK_NOT_AVAILABLE: Final = "55P03"

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
    except (OSError, sa_exc.SQLAlchemyError) as exc:
        if not _is_outage(exc):
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
    """The flag rows over one relational repository; reads run under the read budget."""

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


__all__ = ["FlagRow", "FlagSeed", "SqlAlchemyFlagRepository"]
