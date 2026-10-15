"""Postgres replay-session repository (migration `0023_replay_sessions`, E26-T01 slice 2/3).

SQLAlchemy Core statements against `db.models.replay_sessions`: every value is a bound parameter,
the `LIVE_STATES` list is rendered by the dialect from a closed enum (so Postgres sees constants it
can match against the partial index `ix_rps_live`), and nothing is built from strings. The other
adapters in this package use static `sa.text`; this table's statements vary by optional filters,
and Core keeps them checked against the model that `alembic check` pins to the migration.

Every statement but `list_idle_since` is filtered by `user_id` (C-12.4 data-layer re-check). A write
that matches no row is disambiguated in the same unit of work: no row for this owner is
`ReplaySessionNotFoundError`; a terminal row, or a lost compare-and-set, is
`ReplaySessionIllegalUpdateError`. Reads select explicit column allow-lists (`ROW_COLUMNS`,
`IDLE_COLUMNS`), never `*`, and the system-only sweep never selects `bookmarks` (P1, 21 §12).
Timestamps come from the injected clock (UTC), so tests need no sleeps.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NoReturn

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from candleviewer.db.models import replay_sessions as _TABLE
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
)
from candleviewer.storage.repositories.replay_sessions import (
    LIVE_STATES,
    TERMINAL_STATES,
    IdleReplaySession,
    ReplaySessionConstraintError,
    ReplaySessionCreate,
    ReplaySessionIllegalUpdateError,
    ReplaySessionNotFoundError,
    ReplaySessionPage,
    ReplaySessionRow,
    ReplayState,
    SourceTier,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    require_aware,
    require_counters,
    state_columns,
)

_C = _TABLE.c

#: Explicit read allow-lists, in dataclass field order (a unit test pins both).
ROW_COLUMNS = (
    _C.id, _C.user_id, _C.recording_session_id, _C.symbol, _C.range_start, _C.range_end,
    _C.cursor_ts, _C.speed, _C.state, _C.source_tier, _C.paper_trading, _C.paper_account_id,
    _C.bookmarks, _C.loop_enabled, _C.events_emitted, _C.gap_warnings, _C.error_message,
    _C.created_at, _C.updated_at, _C.finished_at,
)  # fmt: skip
IDLE_COLUMNS = (_C.id, _C.user_id, _C.symbol, _C.state, _C.paper_account_id, _C.updated_at)

#: Statements allowed to omit the `user_id` filter (see module docstring); tested.
UNSCOPED = frozenset({"idle_statement"})

_LIVE_VALUES = sorted(s.value for s in LIVE_STATES)
_TERMINAL_VALUES = sorted(s.value for s in TERMINAL_STATES)
#: SQLSTATEs that carry a constraint name: check_violation, foreign_key_violation, unique_violation.
_NAMED_VIOLATIONS = frozenset({"23514", "23503", "23505"})
#: numeric_value_out_of_range: `speed numeric(6,2)` is the only column that can overflow server-side
#: (the integer counters are range-checked by the driver before they are sent).
_NUMERIC_OUT_OF_RANGE = "22003"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid(value: str) -> uuid.UUID | None:
    """A malformed id can match no row, so callers treat it as not found (never a driver error)."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _live() -> sa.BindParameter[Any]:
    return sa.bindparam("live", _LIVE_VALUES, expanding=True, literal_execute=True)


def _bump(at: datetime) -> sa.ColumnElement[Any]:
    """`updated_at` never moves backwards, whatever order late calls arrive in."""
    return sa.func.greatest(_C.updated_at, sa.literal(at, _C.updated_at.type))


def get_statement(uid: uuid.UUID, sid: uuid.UUID) -> sa.Select[Any]:
    return sa.select(*ROW_COLUMNS).where(_C.user_id == uid, _C.id == sid)


def list_statement(
    uid: uuid.UUID, state: ReplayState | None, after: tuple[datetime, str] | None, limit: int
) -> sa.Select[Any]:
    """Keyset page for `ix_rps_user_time`; `created_at <=` is the redundant index-range bound."""
    stmt = sa.select(*ROW_COLUMNS).where(_C.user_id == uid)
    if state is not None:
        stmt = stmt.where(_C.state == state.value)
    if after is not None:
        ts, rid = after
        stmt = stmt.where(_C.created_at <= ts, sa.or_(_C.created_at < ts, _C.id < uuid.UUID(rid)))
    return stmt.order_by(_C.created_at.desc(), _C.id.desc()).limit(limit)


def count_statement(uid: uuid.UUID) -> sa.Select[Any]:
    return (
        sa.select(sa.func.count())
        .select_from(_TABLE)
        .where(_C.user_id == uid, _C.state.in_(_live()))
    )


def idle_statement(before: datetime, limit: int) -> sa.Select[Any]:
    """System-only sweep over `ix_rps_live`; the one statement that is not owner-scoped."""
    return (
        sa.select(*IDLE_COLUMNS)
        .where(_C.state.in_(_live()), _C.updated_at < before)
        .order_by(_C.updated_at, _C.id)
        .limit(limit)
    )


def update_statement(
    uid: uuid.UUID, sid: uuid.UUID, values: Mapping[str, Any], expected: ReplayState | None
) -> sa.Update:
    """Owner-scoped UPDATE that matches nothing once the row is terminal or `expected` is stale."""
    stmt = (
        sa.update(_TABLE)
        .where(_C.user_id == uid, _C.id == sid, _C.state.not_in(_TERMINAL_VALUES))
        .values(**values)
    )
    return stmt if expected is None else stmt.where(_C.state == expected.value)


def _to_row(m: Mapping[Any, Any]) -> ReplaySessionRow:  # RowMapping keys are not just str
    d = dict(m)
    for key in ("id", "user_id", "recording_session_id", "paper_account_id"):
        d[key] = None if d[key] is None else str(d[key])
    marks = json.loads(d["bookmarks"]) if isinstance(d["bookmarks"], str) else d["bookmarks"]
    d["bookmarks"] = tuple(marks)
    d["state"], d["source_tier"] = ReplayState(d["state"]), SourceTier(d["source_tier"])
    return ReplaySessionRow(**d)


def _to_idle(m: Mapping[Any, Any]) -> IdleReplaySession:
    return IdleReplaySession(
        id=str(m["id"]),
        user_id=str(m["user_id"]),
        symbol=m["symbol"],
        state=ReplayState(m["state"]),
        paper_account_id=None if m["paper_account_id"] is None else str(m["paper_account_id"]),
        updated_at=m["updated_at"],
    )


def _violated_constraint(exc: DBAPIError) -> str | None:
    """Name of the constraint a database error reports, or None when it is not one of ours.

    asyncpg's wrapper exposes `sqlstate`, but the name lives on the driver exception
    (`__cause__`, or `diag` for psycopg); look in all of those places.
    """
    orig: Any = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate == _NUMERIC_OUT_OF_RANGE:
        return "rps_speed"
    if sqlstate not in _NAMED_VIOLATIONS:
        return None
    for src in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(src, "constraint_name", None) or getattr(
            getattr(src, "diag", None), "constraint_name", None
        )
        if name:
            return str(name)
    return None


@contextmanager
def _constraints() -> Iterator[None]:
    try:
        yield
    except DBAPIError as exc:
        name = _violated_constraint(exc)
        if name is None:
            raise
        raise ReplaySessionConstraintError(name) from exc


class SqlAlchemyReplaySessionRepository:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._relational = relational
        self._clock = clock

    async def create(self, row: ReplaySessionCreate) -> ReplaySessionRow:
        now = self._clock()
        values: dict[str, Any] = {
            "id": uuid.UUID(row.id),
            "user_id": uuid.UUID(row.user_id),
            "recording_session_id": _opt_uuid(row.recording_session_id),
            "symbol": row.symbol,
            "range_start": row.range_start,
            "range_end": row.range_end,
            "cursor_ts": row.cursor_ts,
            "speed": row.speed,
            "source_tier": str(row.source_tier),
            "paper_trading": row.paper_trading,
            "paper_account_id": _opt_uuid(row.paper_account_id),
            "bookmarks": list(row.bookmarks),
            "loop_enabled": row.loop_enabled,
            "created_at": now,
            "updated_at": now,
        }
        stmt = sa.insert(_TABLE).values(**values).returning(*ROW_COLUMNS)
        with _constraints():
            async with self._relational.unit_of_work() as uow:
                got = (await uow.session.execute(stmt)).mappings().one()
                await uow.commit()
        return _to_row(got)

    async def get(self, user_id: str, session_id: str) -> ReplaySessionRow | None:
        uid, sid = _uuid(user_id), _uuid(session_id)
        if uid is None or sid is None:
            return None
        async with self._relational.unit_of_work() as uow:
            got = (await uow.session.execute(get_statement(uid, sid))).mappings().first()
        return None if got is None else _to_row(got)

    async def list_page(
        self,
        user_id: str,
        *,
        state: ReplayState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ReplaySessionPage:
        n = clamp_limit(limit)
        after = decode_cursor(cursor) if cursor else None
        wanted = None if state is None else ReplayState(state)
        uid = _uuid(user_id)
        if uid is None:
            return ReplaySessionPage((), None)
        async with self._relational.unit_of_work() as uow:
            result = await uow.session.execute(list_statement(uid, wanted, after, n + 1))
            rows = [_to_row(m) for m in result.mappings()]
        page = rows[:n]
        more = len(rows) > n
        return ReplaySessionPage(
            tuple(page), encode_cursor(page[-1].created_at, page[-1].id) if more else None
        )

    async def update_state(
        self,
        user_id: str,
        session_id: str,
        *,
        state: ReplayState,
        expected_state: ReplayState | None = None,
        finished: bool = False,
        error_message: str | None = None,
    ) -> ReplaySessionRow:
        target = ReplayState(state)
        expected = None if expected_state is None else ReplayState(expected_state)
        now = self._clock()
        finished_at, message = state_columns(
            target, now=now, finished=finished, error_message=error_message
        )
        values = {
            "state": target.value,
            "updated_at": _bump(now),
            "finished_at": finished_at,
            "error_message": message,
        }
        return _to_row(await self._write(user_id, session_id, values, expected))

    async def update_cursor(
        self,
        user_id: str,
        session_id: str,
        *,
        cursor_ts: datetime,
        events_emitted: int | None = None,
        gap_warnings: int | None = None,
    ) -> None:
        require_aware(cursor_ts, "cursor_ts")
        require_counters(events_emitted, gap_warnings)
        values: dict[str, Any] = {"cursor_ts": cursor_ts}
        if events_emitted is not None:
            values["events_emitted"] = events_emitted
        if gap_warnings is not None:
            values["gap_warnings"] = gap_warnings
        await self._write(user_id, session_id, values, columns=(_C.id,))

    async def update_speed(
        self, user_id: str, session_id: str, *, speed: Decimal
    ) -> ReplaySessionRow:
        values = {"speed": speed, "updated_at": _bump(self._clock())}
        return _to_row(await self._write(user_id, session_id, values))

    async def touch(self, user_id: str, session_id: str, at: datetime) -> None:
        require_aware(at, "at")
        await self._write(user_id, session_id, {"updated_at": _bump(at)}, columns=(_C.id,))

    async def count_active(self, user_id: str) -> int:
        uid = _uuid(user_id)
        if uid is None:
            return 0
        async with self._relational.unit_of_work() as uow:
            return int((await uow.session.execute(count_statement(uid))).scalar_one())

    async def list_idle_since(self, before: datetime, limit: int) -> list[IdleReplaySession]:
        require_aware(before, "before")
        async with self._relational.unit_of_work() as uow:
            result = await uow.session.execute(idle_statement(before, clamp_limit(limit)))
            return [_to_idle(m) for m in result.mappings()]

    async def delete(self, user_id: str, session_id: str) -> bool:
        uid, sid = _uuid(user_id), _uuid(session_id)
        if uid is None or sid is None:
            return False
        stmt = sa.delete(_TABLE).where(_C.user_id == uid, _C.id == sid).returning(_C.id)
        async with self._relational.unit_of_work() as uow:
            got = (await uow.session.execute(stmt)).first()
            await uow.commit()
        return got is not None

    async def _write(
        self,
        user_id: str,
        session_id: str,
        values: Mapping[str, Any],
        expected: ReplayState | None = None,
        *,
        columns: Sequence[sa.ColumnElement[Any]] = ROW_COLUMNS,
    ) -> Mapping[Any, Any]:
        uid, sid = _uuid(user_id), _uuid(session_id)
        if uid is None or sid is None:
            raise ReplaySessionNotFoundError(session_id)
        stmt = update_statement(uid, sid, values, expected).returning(*columns)
        with _constraints():
            async with self._relational.unit_of_work() as uow:
                got = (await uow.session.execute(stmt)).mappings().first()
                if got is None:
                    await _refuse(uow, uid, sid, expected)
                await uow.commit()
        return got


def _opt_uuid(value: str | None) -> uuid.UUID | None:
    return None if value is None else uuid.UUID(value)


async def _refuse(
    uow: SqlAlchemyUnitOfWork, uid: uuid.UUID, sid: uuid.UUID, expected: ReplayState | None
) -> NoReturn:
    """The UPDATE matched nothing: say why, in the same transaction (no existence oracle)."""
    stmt = sa.select(_C.state).where(_C.user_id == uid, _C.id == sid)
    current = (await uow.session.execute(stmt)).scalar_one_or_none()
    if current is None:
        raise ReplaySessionNotFoundError(str(sid))
    raise ReplaySessionIllegalUpdateError(str(sid), ReplayState(current), expected)


__all__ = [
    "IDLE_COLUMNS", "ROW_COLUMNS", "UNSCOPED", "SqlAlchemyReplaySessionRepository",
    "count_statement", "get_statement", "idle_statement", "list_statement", "update_statement",
]  # fmt: skip
