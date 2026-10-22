"""`SqlAlchemySessionRepository` with a fake unit of work (no DB available; the
real-Postgres round trip is an integration test, not run locally: no docker)."""

from __future__ import annotations

import functools
import re
import traceback
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import asyncpg

from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsState
from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories import sessions_sqlalchemy
from candleviewer.storage.repositories.sessions_sqlalchemy import (
    _COLUMNS,
    SqlAlchemySessionRepository,
    row_to_fields,
)

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
#: `(step_up_elevations, step_up_failures, readonly_until)` as `update_step_up_state` passes it.
StepUpColumns = tuple[dict[str, datetime], int, datetime | None]
#: #3085: the `sessions` view-as columns (`0042_sessions_view_as`), one per `ViewAsState` field.
_VIEW_AS_COLUMNS = tuple(f"view_as_{name}" for name in ViewAsState.model_fields)


def _row(**over: Any) -> SimpleNamespace:
    m: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "refresh_token_hash": "h",
        "access_token_jti": str(uuid.uuid4()),
        "issued_at": _NOW,
        "last_seen_at": _NOW,
        "expires_at": _NOW,
        "revoked_at": None,
        "revoked_reason": None,
        "ip": "10.0.0.1/32",
        "user_agent": "ua",
        "device_label": None,
        "is_electron": False,
        "mfa_satisfied_at": None,
        "idle_timeout_s": 900,
        "step_up_elevations": "{}",
        "step_up_failures": 0,
        "readonly_until": None,
        **dict.fromkeys(_VIEW_AS_COLUMNS),
    }
    m.update(over)
    return SimpleNamespace(_mapping=m)


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def first(self) -> SimpleNamespace | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _Session:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _Result:
        self.calls.append((str(stmt), params))
        return _Result(self.rows)


class _Relational:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.session = _Session(rows)
        self.commits = 0
        self.units = 0  # transactions opened

    @asynccontextmanager
    async def unit_of_work(self) -> Any:
        rel = self
        self.units += 1

        async def commit() -> None:
            rel.commits += 1

        yield SimpleNamespace(session=self.session, commit=commit)


def _repo(rows: list[SimpleNamespace]) -> tuple[SqlAlchemySessionRepository, _Relational]:
    rel = _Relational(rows)
    return SqlAlchemySessionRepository(rel, dict), rel  # type: ignore[arg-type]  # fake relational stub, structurally compatible


def test_row_to_fields_strips_inet_mask_and_parses_uuids() -> None:
    f = row_to_fields(_row())
    assert f["ip"] == "10.0.0.1"
    assert isinstance(f["id"], uuid.UUID)
    assert f["idle_timeout_s"] == 900


async def test_revoke_is_conditional_update_returning_and_parameterised() -> None:
    repo, rel = _repo([_row(revoked_reason="logout")])
    got = await repo.revoke("sid", reason="logout", now=_NOW)
    sql, params = rel.session.calls[0]
    assert "revoked_at IS NULL" in sql
    assert "RETURNING" in sql
    assert params == {"id": "sid", "reason": "logout", "now": _NOW}
    assert got["revoked_reason"] == "logout"
    assert rel.commits == 1


async def test_revoke_already_revoked_returns_none() -> None:
    repo, _ = _repo([])
    assert await repo.revoke("sid", reason="x", now=_NOW) is None


async def test_revoke_all_passes_except_session() -> None:
    repo, rel = _repo([_row(), _row()])
    out = await repo.revoke_all_for_user("u", reason="logout_all", now=_NOW, except_session_id="e")
    assert len(out) == 2
    assert rel.session.calls[0][1]["except_id"] == "e"


async def test_family_walk_returns_ids_and_lookup_by_jti_is_bound() -> None:
    repo, _rel = _repo(
        [SimpleNamespace(_mapping={"id": "a"}), SimpleNamespace(_mapping={"id": "b"})]
    )
    assert await repo.walk_rotation_family("a") == ("a", "b")
    repo2, rel2 = _repo([_row()])
    await repo2.find_by_access_token_jti("jti")
    assert rel2.session.calls[0][1] == {"j": "jti"}


async def test_update_step_up_state_rewrites_the_row_it_locked_in_one_transaction() -> None:
    """#2304: the step-up columns are read under the row lock and rewritten from that read in
    the same transaction, never from a copy of the row read before it."""
    until = datetime(2026, 9, 30, 0, 5, tzinfo=UTC)
    stored = '{"keys": "2026-09-30T00:05:00+00:00"}'
    repo, rel = _repo([_row(step_up_elevations=stored, step_up_failures=1)])
    seen: list[StepUpColumns] = []

    def change(state: StepUpColumns) -> StepUpColumns:
        seen.append(state)
        return {"users": until}, 2, None

    got = await repo.update_step_up_state("sid", change)

    (lock_sql, lock_params), (write_sql, params) = rel.session.calls
    assert "revoked_at IS NULL" in lock_sql and lock_sql.endswith("FOR NO KEY UPDATE")
    assert lock_params == {"id": "sid"} and seen == [({"keys": until}, 1, None)]
    assert write_sql.startswith("UPDATE sessions SET step_up_elevations = CAST(:elevations")
    assert "revoked_at IS NULL" in write_sql and "RETURNING" in write_sql
    elevations = '{"users": "2026-09-30T00:05:00+00:00"}'
    assert params == {"id": "sid", "elevations": elevations, "failures": 2, "readonly_until": None}
    assert rel.commits == 1 and got is not None


async def test_update_step_up_state_of_a_revoked_or_absent_row_writes_nothing() -> None:
    repo, rel = _repo([])
    seen: list[StepUpColumns] = []

    def change(state: StepUpColumns) -> StepUpColumns:
        seen.append(state)
        return state

    assert await repo.update_step_up_state("sid", change) is None
    assert seen == [] and len(rel.session.calls) == 1 and rel.commits == 0


async def test_lift_idle_lock_restamps_and_clears_elevations_in_one_conditional_write() -> None:
    """#2301 (B16.7): one UPDATE re-stamps `last_seen_at` and clears
    `step_up_elevations`; `step_up_failures` and `readonly_until` are kept."""
    repo, rel = _repo([_row(step_up_failures=2)])
    got = await repo.lift_idle_lock("sid", now=_NOW)
    ((sql, params),) = rel.session.calls
    assignments = sql.split("WHERE", 1)[0]
    assert "last_seen_at = :now" in assignments
    assert "step_up_elevations = '{}'::jsonb" in assignments
    assert "step_up_failures" not in assignments and "readonly_until" not in assignments
    assert "revoked_at IS NULL" in sql and "RETURNING" in sql
    assert params == {"id": "sid", "now": _NOW}
    assert rel.commits == 1 and got["step_up_failures"] == 2


async def test_consume_step_up_key_is_one_conditional_update_of_the_live_unexpired_key() -> None:
    """#2304: a one-shot grant is removed by one conditional UPDATE, never read-modify-write, so
    of two concurrent consumers only one gets the row."""
    key = "once:killswitch:" + str(uuid.UUID(int=1)) + ":" + "a" * 64
    repo, rel = _repo([_row()])
    got = await repo.consume_step_up_key("sid", key=key, now=_NOW)
    sql, params = rel.session.calls[0]
    assert "SET step_up_elevations = step_up_elevations - CAST(:key AS text)" in sql
    assert "revoked_at IS NULL" in sql and "RETURNING" in sql
    assert "CAST(step_up_elevations ->> CAST(:key AS text) AS timestamptz) > :now" in sql
    assert params == {"id": "sid", "key": key, "now": _NOW}
    assert got is not None and rel.commits == 1


async def test_consume_step_up_key_that_updates_no_row_returns_none() -> None:
    repo, _ = _repo([])
    assert await repo.consume_step_up_key("sid", key="once:killswitch", now=_NOW) is None


_STATUS_READ = (
    "(SELECT u.status::text FROM users u WHERE u.id = sessions.user_id "
    "AND u.deleted_at IS NULL) AS user_status"
)


def _new_session() -> SimpleNamespace:
    return SimpleNamespace(**row_to_fields(_row()))


async def test_create_session_inserts_under_the_users_row_lock_in_one_transaction() -> None:
    """#2911: the user's status is read `FOR SHARE` (which conflicts with the disable's
    `FOR NO KEY UPDATE`) in the insert's own transaction, before the insert."""
    repo, rel = _repo([SimpleNamespace(_mapping={"status": "active"})])
    session = _new_session()

    got = await repo.create_session(session)

    (lock_sql, lock_params), (insert_sql, insert_params) = rel.session.calls
    assert lock_sql == (
        "SELECT status::text AS status FROM users WHERE id = CAST(:id AS uuid) "
        "AND deleted_at IS NULL FOR SHARE"
    )
    assert lock_params == {"id": str(session.user_id)}
    assert insert_sql.lstrip().startswith("INSERT INTO sessions")
    assert insert_params["user_id"] == str(session.user_id)
    assert (rel.units, rel.commits) == (1, 1) and got is session


async def test_create_session_binds_the_activity_stamp_the_record_carries() -> None:
    """#4012: a refresh carries `last_seen_at` to its successor, so the insert binds the record's
    stamp, never the column's `DEFAULT now()`."""
    repo, rel = _repo([SimpleNamespace(_mapping={"status": "active"})])
    session = SimpleNamespace(**row_to_fields(_row(last_seen_at=_NOW - timedelta(minutes=7))))

    await repo.create_session(session)

    _, (_, insert_params) = rel.session.calls
    assert insert_params["last_seen_at"] == session.last_seen_at != session.issued_at


async def test_create_session_binds_the_step_up_penalty_the_record_carries() -> None:
    """#4051: a refresh carries the step-up penalty to its successor (SR-025), so the insert
    binds the record's strikes and read-only window, never the columns' defaults."""
    repo, rel = _repo([SimpleNamespace(_mapping={"status": "active"})])
    until = _NOW + timedelta(minutes=5)
    session = SimpleNamespace(**row_to_fields(_row(step_up_failures=3, readonly_until=until)))

    await repo.create_session(session)

    _, (_, insert_params) = rel.session.calls
    assert (insert_params["step_up_failures"], insert_params["readonly_until"]) == (3, until)


@pytest.mark.parametrize("status", ["disabled", None])
async def test_create_session_for_a_disabled_user_inserts_nothing(status: str | None) -> None:
    """`None`: no such user, or a soft-deleted one."""
    repo, rel = _repo([] if status is None else [SimpleNamespace(_mapping={"status": status})])

    assert await repo.create_session(_new_session()) is None
    assert len(rel.session.calls) == 1 and rel.commits == 0


@pytest.mark.parametrize("status", ["locked", "invited"])
async def test_create_session_for_a_locked_or_invited_user_still_inserts(status: str) -> None:
    """#2911 keeps `locked` and `invited` as login does: only `disabled` (or gone) is refused."""
    repo, rel = _repo([SimpleNamespace(_mapping={"status": status})])
    session = _new_session()

    assert await repo.create_session(session) is session
    assert len(rel.session.calls) == 2 and rel.commits == 1  # the lock read, then the insert
    assert rel.session.calls[1][0].lstrip().startswith("INSERT INTO sessions")


async def test_reads_by_id_and_refresh_hash_carry_the_users_status_in_one_statement() -> None:
    """#2911: `require_active` and `refresh` decide on the status read with the session row,
    so an active user's request costs no extra round trip."""
    repo, rel = _repo([_row(user_status="disabled")])

    by_id = await repo.find_by_id("sid")
    by_hash = await repo.find_by_refresh_hash("h")

    assert [_STATUS_READ in sql for sql, _ in rel.session.calls] == [True, True]
    assert by_id["user_status"] == by_hash["user_status"] == "disabled"
    assert rel.units == 2


async def test_touch_last_seen_is_conditional_on_the_lock() -> None:
    """#2300 (B16.7): activity never lifts a lock, not even one that engaged after the
    caller's own check: the write keeps only a row still unlocked at `:now`."""
    repo, rel = _repo([_row()])
    await repo.touch_last_seen("sid", now=_NOW)
    ((sql, params),) = rel.session.calls
    assignments, condition = sql.split("WHERE", 1)
    assert "last_seen_at = :now" in assignments
    assert "revoked_at IS NULL" in condition and "RETURNING" in condition
    assert "last_seen_at + make_interval(secs => idle_timeout_s) > :now" in condition
    assert params == {"id": "sid", "now": _NOW}


# -- #3085: the view-as columns (`0042_sessions_view_as`) on every record the repository builds.

_T0 = datetime(2026, 10, 20, 12, tzinfo=UTC)
_LIVE = ViewAsState.start(uuid.UUID(int=1), uuid.UUID(int=2), now=_T0)
_END, _CLEAR = _T0 + timedelta(minutes=10), _T0 + timedelta(minutes=40)


def _revised(**changes: Any) -> ViewAsState:
    """`_LIVE` with `changes`, validated as the row's CHECK validates it."""
    return ViewAsState.model_validate({**dict(_LIVE), **changes})


_AT_EXPIRY = {"ended_at": _LIVE.expires_at, "end_reason": ViewAsEndReason.EXPIRED}
#: case id -> the state a row holds: none, each phase, and an end whose record is still owed.
_STATES: dict[str, ViewAsState | None] = {
    "none": None,
    "live": _LIVE,
    "held": _revised(ended_at=_END, end_reason=ViewAsEndReason.ENDED, end_recorded_at=_END),
    "cleared": _revised(**_AT_EXPIRY, end_recorded_at=_CLEAR, cleared_at=_CLEAR),
    "pending-end": _revised(ended_at=_END, end_reason="session_ended", cleared_at=_CLEAR),
}


def _view_as_columns(state: ViewAsState | None) -> dict[str, Any]:
    """The columns as `_COLUMNS` reads them: uuids and the reason as text; none: no context."""
    text = {"context_id", "target_user_id", "end_reason"}
    return {
        f"view_as_{name}": str(value) if name in text and value is not None else value
        for name, value in (state.model_dump() if state else {}).items()
    }


@pytest.mark.parametrize("state", list(_STATES.values()), ids=list(_STATES))
def test_row_to_fields_reads_the_view_as_columns_into_the_state_the_row_holds(
    state: ViewAsState | None,
) -> None:
    """None for a row holding no context, else a plain dict of `ViewAsState`'s fields (storage
    never imports `auth`, C-3.1): `SessionRecord` validates it into the very state the row holds."""
    fields = row_to_fields(_row(**_view_as_columns(state)))
    assert fields["view_as"] == (None if state is None else state.model_dump())
    assert SessionRecord.model_validate(fields).view_as == state


@pytest.mark.parametrize("column", _VIEW_AS_COLUMNS)
def test_row_to_fields_refuses_a_row_read_without_a_view_as_column(column: str) -> None:
    """Fail closed: a read that misses a view-as column raises; it never reports no context for a
    session whose row holds one (which would let a viewing session act as the viewer)."""
    row = _row(**_view_as_columns(_LIVE))
    del row._mapping[column]
    with pytest.raises(KeyError, match=column):
        row_to_fields(row)


def test_every_statement_on_sessions_selects_the_columns_or_builds_no_record() -> None:
    """Every statement whose row becomes a record (`RETURNING` included) selects `_COLUMNS`, the
    view-as uuids as text like the others; the insert and the step-up lock read build none."""
    statements = {
        name: str(value)
        for name, value in vars(sessions_sqlalchemy).items()
        if isinstance(value, sa.TextClause)
        and re.search(r"\b(?:FROM|UPDATE|INTO) sessions\b", str(value))
    }
    build_none = {"_INSERT_SQL", "_LOCK_STEP_UP_SQL"}
    assert build_none < set(statements)
    assert {name for name, sql in statements.items() if _COLUMNS not in sql} == build_none
    assert all(column in _COLUMNS for column in _VIEW_AS_COLUMNS)
    for column in ("view_as_context_id", "view_as_target_user_id"):
        assert f"{column}::text AS {column}" in _COLUMNS


# -- #3085 S2b: the `ViewAsSessionStore` statements, offline (rendered for asyncpg, never run here;
# `tests/integration/storage/test_sessions_view_as_store_pg.py` runs them on Postgres).

_CID, _ASKED, _GRACE = _LIVE.context_id, ViewAsEndReason.ENDED, timedelta(minutes=2)
_TARGET = _LIVE.target_user_id
_IN_ROW = {"id": "sid", "context_id": str(_CID)}
Call = Callable[[SqlAlchemySessionRepository], Awaitable[Any]]
#: method -> (a call, its statement, the parameters it must bind)
_VIEW_AS_CALLS: dict[str, tuple[Call, str, dict[str, Any]]] = {
    "start_view_as": (
        lambda r: r.start_view_as("sid", _LIVE, now=_T0),
        "_VIEW_AS_START_SQL",
        {"id": "sid", "now": _T0, "context_id": str(_CID), "target_user_id": str(_TARGET)}
        | {"started_at": _LIVE.started_at, "view_as_expires_at": _LIVE.expires_at},
    ),
    "end_view_as": (
        lambda r: r.end_view_as("sid", _CID, ended_at=_END, reason=_ASKED),
        "_VIEW_AS_END_SQL",
        _IN_ROW | {"ended_at": _END, "reason": "ended"},
    ),
    "leave_view_as": (
        lambda r: r.leave_view_as("sid", _CID, ended_at=_END, reason=_ASKED, now=_CLEAR),
        "_VIEW_AS_LEAVE_SQL",
        _IN_ROW | {"ended_at": _END, "reason": "ended", "now": _CLEAR},
    ),
    "clear_view_as": (
        lambda r: r.clear_view_as("sid", _CID, now=_CLEAR),
        "_VIEW_AS_CLEAR_SQL",
        _IN_ROW | {"now": _CLEAR},
    ),
    "mark_view_as_recorded": (
        lambda r: r.mark_view_as_recorded("sid", _CID, now=_CLEAR),
        "_VIEW_AS_RECORDED_SQL",
        _IN_ROW | {"now": _CLEAR},
    ),
    "list_view_as_due": (
        lambda r: r.list_view_as_due(now=_T0, rotated_grace=_GRACE, limit=7),
        "_VIEW_AS_DUE_SQL",
        {"now": _T0, "cutoff": _T0 - _GRACE, "limit": 7},
    ),
    "list_live_view_as": (
        lambda r: r.list_live_view_as(limit=7),
        "_VIEW_AS_LIVE_SQL",
        {"limit": 7},
    ),
    "list_live_view_as_by_target": (
        lambda r: r.list_live_view_as_by_target(_TARGET),
        "_VIEW_AS_LIVE_BY_TARGET_SQL",
        {"target": str(_TARGET)},
    ),
    "list_live_view_as_by_viewer": (
        lambda r: r.list_live_view_as_by_viewer(_TARGET),
        "_VIEW_AS_LIVE_BY_VIEWER_SQL",
        {"viewer": str(_TARGET)},
    ),
}
_WRITES = [method for method in _VIEW_AS_CALLS if not method.startswith("list_")]


def _binds(stmt: sa.TextClause) -> set[str]:
    """The placeholders `stmt` has once rendered for asyncpg (`$n`): a name the call does not bind
    would fail only when Postgres runs it."""
    return set(stmt.compile(dialect=asyncpg.dialect()).binds)


@pytest.mark.parametrize("method", _VIEW_AS_CALLS)
async def test_each_view_as_call_is_one_statement_binding_exactly_its_parameters(
    method: str,
) -> None:
    call, name, params = _VIEW_AS_CALLS[method]
    stmt = getattr(sessions_sqlalchemy, name)
    repo, rel = _repo([_row(**_view_as_columns(_LIVE), ended_now=True)])

    got = await call(repo)

    assert rel.session.calls == [(str(stmt), params)] and (rel.units, rel.commits) == (1, 1)
    assert _binds(stmt) == set(params)
    assert got is not None and (_COLUMNS in str(stmt))  # every row read builds a record


@pytest.mark.parametrize("method", _WRITES)
async def test_a_view_as_write_whose_condition_fails_returns_none(method: str) -> None:
    repo, rel = _repo([])
    assert await _VIEW_AS_CALLS[method][0](repo) is None and rel.commits == 1


@pytest.mark.parametrize("ended_now", [True, False])
async def test_leave_returns_the_row_and_whether_this_call_ended_it(ended_now: bool) -> None:
    repo, _ = _repo([_row(**_view_as_columns(_LIVE), ended_now=ended_now)])
    left = await repo.leave_view_as("sid", _CID, ended_at=_END, reason=_ASKED, now=_CLEAR)
    assert left is not None
    assert left[1] is ended_now and SessionRecord.model_validate(left[0]).view_as == _LIVE


async def test_start_refuses_an_ended_state_before_any_statement() -> None:
    repo, rel = _repo([_row()])
    with pytest.raises(ValueError, match="fresh"):
        await repo.start_view_as("sid", _STATES["held"], now=_T0)
    assert rel.session.calls == []


class _DriverError(Exception):
    """asyncpg's own error: the constraint it names, and the failing row as its DETAIL."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__("DETAIL: Failing row contains (a refresh token hash)")
        self.constraint_name = constraint_name


class _AdapterError(Exception):
    """SQLAlchemy's asyncpg adapter error: the SQLSTATE, and the driver error it chains."""

    def __init__(self, sqlstate: str, driver: _DriverError) -> None:
        super().__init__(str(driver))
        self.sqlstate = sqlstate
        self.__cause__ = driver


def _violation(constraint: str, sqlstate: str) -> sa.exc.IntegrityError:
    adapter = _AdapterError(sqlstate, _DriverError(constraint))
    return sa.exc.IntegrityError("UPDATE sessions", None, adapter)


class _Refusing(_Session):
    """A session whose statement fails: Postgres refused it."""

    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self._error = error

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _Result:
        await super().execute(stmt, params)
        raise self._error


async def test_start_of_a_state_naming_the_rows_own_user_is_a_value_error_naming_nothing() -> None:
    """Only the row knows its user, so the CHECK refuses the state (where the write would apply)
    and the store turns that into the caller error the fake raises: a fixed message, no id and no
    chained DETAIL (the failing row), and nothing committed."""
    repo, rel = _repo([])
    rel.session = _Refusing(_violation("sessions_view_as_shape", "23514"))
    sid = str(uuid.uuid4())

    with pytest.raises(ValueError, match="own user") as refused:
        await repo.start_view_as(sid, _LIVE, now=_T0)

    assert not any(value in str(refused.value) for value in (sid, str(_CID), str(_TARGET)))
    assert refused.value.__cause__ is None and refused.value.__suppress_context__
    assert len(rel.session.calls) == 1 and rel.commits == 0


@pytest.mark.parametrize(
    ("constraint", "sqlstate"),
    [("sessions_view_as_target_user_id_fkey", "23503"), ("sessions_view_as_end_reason", "23514")],
    ids=["no-such-target", "unknown-reason"],
)
async def test_start_types_any_other_refusal_by_the_database_as_a_store_failure(
    constraint: str, sqlstate: str
) -> None:
    """Only the self-target is the caller's error: a missing target or a bad stored value is a
    store failure and must not read as one. Typed by its SQLSTATE and constraint alone (#2748):
    nothing chains the driver error, whose DETAIL is the failing row."""
    repo, rel = _repo([])
    rel.session = _Refusing(_violation(constraint, sqlstate))
    with pytest.raises(StorageConstraintViolated) as refused:
        await repo.start_view_as("sid", _LIVE, now=_T0)
    assert (refused.value.sqlstate, refused.value.constraint) == (sqlstate, constraint)
    assert refused.value.__cause__ is None and refused.value.__suppress_context__
    assert "Failing row" not in "".join(traceback.format_exception(refused.value))


@pytest.mark.parametrize("state", list(_STATES.values()), ids=list(_STATES))
async def test_create_session_inserts_the_context_the_record_carries(
    state: ViewAsState | None,
) -> None:
    """S3's carry: the insert writes a record's context as `_COLUMNS` reads it back, eight NULLs
    when it holds none, and binds exactly what its statement names."""
    repo, rel = _repo([SimpleNamespace(_mapping={"status": "active"})])
    await repo.create_session(SimpleNamespace(**{**row_to_fields(_row()), "view_as": state}))
    _, (_, params) = rel.session.calls
    written = {k: v for k, v in params.items() if k.startswith("view_as_")}
    assert written == (_view_as_columns(state) or dict.fromkeys(_VIEW_AS_COLUMNS))
    assert _binds(sessions_sqlalchemy._INSERT_SQL) == set(params)


def _assigned(stmt: sa.TextClause) -> set[str]:
    """The `sessions` columns an UPDATE assigns or an INSERT names."""
    sql = str(stmt)
    if update := re.search(r"\bUPDATE sessions SET (.*?) (?:WHERE|FROM)\b", sql, re.S):
        return set(re.findall(r"(\w+) = ", update.group(1)))
    if insert := re.search(r"\bINSERT INTO sessions \((.*?)\)", sql, re.S):
        return {column.strip() for column in insert.group(1).split(",")}
    return set()


def test_only_the_insert_and_the_view_as_writes_write_a_view_as_column() -> None:
    """Refresh, activity, unlock, step-up and revocation never write the context (22: nothing
    extends it), and each view-as write writes only its own columns."""
    writes = {
        name: {column for column in _assigned(value) if column.startswith("view_as_")}
        for name, value in vars(sessions_sqlalchemy).items()
        if isinstance(value, sa.TextClause)
    }
    assert {name: columns for name, columns in writes.items() if columns} == {
        "_INSERT_SQL": set(_VIEW_AS_COLUMNS),
        "_VIEW_AS_START_SQL": set(_VIEW_AS_COLUMNS),
        "_VIEW_AS_END_SQL": {"view_as_ended_at", "view_as_end_reason"},
        "_VIEW_AS_LEAVE_SQL": {"view_as_ended_at", "view_as_end_reason", "view_as_cleared_at"},
        "_VIEW_AS_CLEAR_SQL": {"view_as_cleared_at"},
        "_VIEW_AS_RECORDED_SQL": {"view_as_end_recorded_at"},
    }


def test_the_due_read_states_its_index_predicate_so_the_partial_index_serves_it() -> None:
    sql = str(sessions_sqlalchemy._VIEW_AS_DUE_SQL)
    assert "s.view_as_context_id IS NOT NULL AND s.view_as_end_recorded_at IS NULL" in sql
    assert "o.view_as_context_id = s.view_as_context_id" in sql  # `ix_sessions_view_as_context`
    assert sql.endswith("ORDER BY s.view_as_expires_at LIMIT :limit")


#: statement -> the clauses that make a write safe or a read complete. The scenario table proves
#: each on Postgres only (CI), so a clause dropped from the text passes every offline test above.
_CLAUSES = {
    "_VIEW_AS_LEAVE_SQL": (
        "view_as_cleared_at IS NULL AND revoked_at IS NULL",  # a revoked row is not left
        "COALESCE(view_as_ended_at, :ended_at)",  # the end it finds stays, its reason too
        "COALESCE(view_as_end_reason, :reason)",
    ),
    "_VIEW_AS_END_SQL": (
        "(revoked_at IS NULL OR NOT EXISTS (SELECT 1 FROM sessions o ",  # a carried copy is not
        "o.id <> sessions.id AND o.revoked_at IS NULL)",  # ended: only a live other row carries
    ),
    "_VIEW_AS_DUE_SQL": (
        "s.view_as_expires_at <= :now",  # due at the expiry itself, as is the absolute one
        "s.expires_at <= :now",
        "OR o.revoked_at IS NULL OR o.revoked_at > :cutoff",  # a rotated row with no time carries
    ),
}


@pytest.mark.parametrize("name", _CLAUSES)
def test_a_statement_states_the_clauses_only_the_postgres_table_proves(name: str) -> None:
    sql = str(getattr(sessions_sqlalchemy, name))
    assert [clause for clause in _CLAUSES[name] if clause not in sql] == []


# -- #3085 S13a: the start's unit of work (`start_view_as_unit`), offline: the statements in order,
# where the write-ahead hooks run, and each branch (Postgres: the store scenarios, in CI).

_FRESH = ViewAsState.start(uuid.UUID(int=3), uuid.UUID(int=2), now=_T0)
_NOTICE = SimpleNamespace(target_user_id=_FRESH.target_user_id, message="m", correlation_id=None)


class _Scripted(_Session):
    """Each statement answers the rows `script` gives the module statement of that name."""

    def __init__(self, script: dict[str, list[SimpleNamespace]], log: list[str]) -> None:
        super().__init__([])
        self.script, self.log = script, log

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _Result:
        await super().execute(stmt, params)
        name = next(
            n
            for n, v in vars(sessions_sqlalchemy).items()
            if isinstance(v, sa.TextClause) and str(v) == str(stmt)
        )
        self.log.append(name)
        return _Result(self.script.get(name, []))


def _unit(
    held: ViewAsState | None, **row: Any
) -> tuple[SqlAlchemySessionRepository, _Relational, list[str], Call]:
    """A store whose locked row holds `held`, the order of its statements and hooks (`log`), and
    the start call with hooks that log themselves."""
    log: list[str] = []
    rel = _Relational([])
    started = _row(**_view_as_columns(_FRESH))
    script = {
        "_VIEW_AS_START_LOCK_SQL": [_row(**_view_as_columns(held), **row)],
        "_VIEW_AS_START_SQL": [started],
    }
    rel.session = _Scripted(script, log)
    repo = SqlAlchemySessionRepository(
        rel,  # type: ignore[arg-type]  # fake relational stub, structurally compatible
        lambda **f: SessionRecord.model_validate(f),
    )

    async def hook(name: str, _record: Any) -> None:
        log.append(name)

    def call(r: SqlAlchemySessionRepository) -> Awaitable[Any]:
        return r.start_view_as_unit(
            "sid",
            _FRESH,
            now=_T0,
            notice=_NOTICE,
            flush_pending_end=functools.partial(hook, "flush"),
            write_ahead=functools.partial(hook, "ahead"),
            audit_timeout_s=1.0,
        )

    return repo, rel, log, call


async def test_the_start_unit_locks_then_writes_the_notice_the_record_ahead_and_the_start() -> None:
    repo, rel, log, call = _unit(None)
    started, held = await call(repo)
    assert log == ["_VIEW_AS_START_LOCK_SQL", "_VIEW_AS_NOTICE_SQL", "ahead", "_VIEW_AS_START_SQL"]
    assert held is None and started.view_as == _FRESH and (rel.units, rel.commits) == (1, 1)
    lock, notice, start = rel.session.calls
    assert lock[1] == {"id": "sid", "now": _T0} and "FOR NO KEY UPDATE" in lock[0]
    assert notice[1] == {
        "message": "m",
        "correlation_id": None,
        "recipient": str(_FRESH.target_user_id),
    }
    assert _binds(sessions_sqlalchemy._VIEW_AS_NOTICE_SQL) == set(notice[1])
    assert start[1] == _VIEW_AS_CALLS["start_view_as"][2] | {"context_id": str(_FRESH.context_id)}


def test_the_notice_names_no_account_or_symbol() -> None:
    """The addressed read filters on the environment alone, never on the caller's grants, so the
    notice names no account and no symbol (#3085 S13a; the #4139 re-check's Info 7)."""
    sql = str(sessions_sqlalchemy._VIEW_AS_NOTICE_SQL)
    columns = re.search(r"INSERT INTO system_events \(([^)]*)\)", sql)
    assert columns is not None
    assert [c.strip() for c in columns.group(1).split(",")] == [
        "component",
        "kind",
        "severity",
        "message",
        "correlation_id",
        "recipient_user_id",
    ]


async def test_the_start_unit_writes_a_pending_ends_record_late_and_marks_it_first() -> None:
    repo, rel, log, call = _unit(_STATES["pending-end"])
    started, _held = await call(repo)
    assert log == [
        "_VIEW_AS_START_LOCK_SQL", "flush", "_VIEW_AS_RECORDED_SQL", "_VIEW_AS_NOTICE_SQL",
        "ahead", "_VIEW_AS_START_SQL",
    ]  # fmt: skip
    assert started is not None and rel.commits == 1


@pytest.mark.parametrize("state", ["live", "held"])
async def test_the_start_unit_answers_a_context_it_cannot_replace_as_held(state: str) -> None:
    repo, rel, log, call = _unit(_STATES[state])
    started, held = await call(repo)
    assert started is None and held.view_as == _STATES[state]
    assert log == ["_VIEW_AS_START_LOCK_SQL"] and rel.commits == 0


async def test_the_start_unit_of_a_gone_or_revoked_row_writes_nothing() -> None:
    repo, rel, log, call = _unit(None)
    rel.session.script["_VIEW_AS_START_LOCK_SQL"] = []  # the lock reads no row
    assert await call(repo) == (None, None) and log == ["_VIEW_AS_START_LOCK_SQL"]


async def test_the_start_unit_refuses_a_self_targeting_state_before_any_write() -> None:
    repo, rel, log, call = _unit(None, user_id=str(_FRESH.target_user_id))
    with pytest.raises(ValueError, match="its own user"):
        await call(repo)
    assert log == ["_VIEW_AS_START_LOCK_SQL"] and rel.commits == 0


async def test_the_start_unit_refuses_a_notice_to_another_user_before_any_statement() -> None:
    repo, rel, log, _call = _unit(None)
    elsewhere = SimpleNamespace(target_user_id=uuid.UUID(int=7), message="m", correlation_id=None)

    async def never(_record: Any) -> None:
        raise AssertionError("no hook runs")

    with pytest.raises(ValueError, match="addressed to its target"):
        await repo.start_view_as_unit(
            "sid", _FRESH, now=_T0, notice=elsewhere, flush_pending_end=never,
            write_ahead=never, audit_timeout_s=1.0,
        )  # fmt: skip
    assert log == [] and (rel.units, rel.commits) == (0, 0)


async def test_a_failing_write_ahead_commits_nothing() -> None:
    repo, rel, log, _call = _unit(None)

    async def fails(_record: Any) -> None:
        raise ConnectionError("audit down")

    with pytest.raises(ConnectionError):
        await repo.start_view_as_unit(
            "sid", _FRESH, now=_T0, notice=_NOTICE, flush_pending_end=fails,
            write_ahead=fails, audit_timeout_s=1.0,
        )  # fmt: skip
    assert log == ["_VIEW_AS_START_LOCK_SQL", "_VIEW_AS_NOTICE_SQL"] and rel.commits == 0
