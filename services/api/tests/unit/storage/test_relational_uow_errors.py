"""#2748 (C-12.6): an error leaving a unit of work carries none of the database server's text.

`str(DBAPIError)` and its cause chain hold the server's message and `DETAIL` (`Key (col)=(val)`,
`Failing row contains (...)`), which `hide_parameters=True` leaves, and `traceback` renders them
in the log. `SqlAlchemyUnitOfWork.__aexit__` strips them in place: each driver error keeps its
type, SQLSTATE, constraint name and `connection_invalidated`, so every caller's classification
holds (`api.storage_outage`, the adapters' constraint maps). The errors are built as SQLAlchemy's
asyncpg dialect builds them; the session is a fake. No DB, no network.
"""

from __future__ import annotations

import asyncio
import pickle
import traceback
from collections.abc import Callable
from typing import Any, cast

import asyncpg
import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi as _Dbapi

from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.storage.errors import (
    BackupCheckViolation,
    BackupWriteOnceViolation,
    StorageConstraintViolated,
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories import account_access_sqlalchemy as account_access
from candleviewer.storage.repositories import audit_sqlalchemy as audit
from candleviewer.storage.repositories import backups_sqlalchemy as backups
from candleviewer.storage.repositories import drawings_sqlalchemy as drawings
from candleviewer.storage.repositories import orders_sqlalchemy as orders
from candleviewer.storage.repositories import relational_sqlalchemy as relational
from candleviewer.storage.repositories import statechart_sqlalchemy as statechart
from candleviewer.storage.repositories import trade_groups_sqlalchemy as trade_groups
from candleviewer.storage.repositories import workspaces_codec
from candleviewer.storage.repositories.account_access import AccessBusyError
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyUnitOfWork,
    constraint_of,
    is_outage,
    query_failure,
    sqlstate_of,
    strip_driver_text,
)
from candleviewer.storage.retention import users_purge_tasks as purge

_P1 = "canary-2748@example.test"  # test-only literal standing for a P1 column value


def _driver(cls: type[Exception], message: str, **facts: str) -> Exception:
    error = cls(message)
    for name, value in facts.items():
        setattr(error, name, value)
    return error


def _wrapped(driver: Exception, adapted: type[Exception], wrapper: type[Exception]) -> Exception:
    """`driver` as the dialect raises it (adapted `from` the driver error), then as SQLAlchemy
    raises it from the statement (`from` the adapted one)."""
    try:
        try:
            raise driver
        except Exception as raw:
            raise adapted(raw.args[0], raw) from raw
    except Exception as dbapi_error:
        try:
            raise wrapper(  # type: ignore[call-arg]  # SQLAlchemy's (statement, params, orig, ...)
                "INSERT INTO users (email) VALUES ($1)", (_P1,), dbapi_error, hide_parameters=True
            ) from dbapi_error
        except Exception as statement_error:
            return statement_error


def _unique() -> Exception:
    driver = _driver(
        asyncpg.exceptions.UniqueViolationError,
        'duplicate key value violates unique constraint "users_email_key"',
        detail=f"Key (email)=({_P1}) already exists.",
        constraint_name="users_email_key",
    )
    return _wrapped(driver, _Dbapi.IntegrityError, sa_exc.IntegrityError)


def _rendered(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc)) + str(exc) + repr(exc)


class _Session:
    def __init__(self, **fail: BaseException) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def _step(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    async def commit(self) -> None:
        await self._step("commit")

    async def rollback(self) -> None:
        await self._step("rollback")

    async def close(self) -> None:
        await self._step("close")


def _uow(session: _Session) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(cast(Any, session), cast(Any, None))


@pytest.mark.parametrize("where", ["statement", "commit"])
async def test_a_driver_error_leaves_the_unit_of_work_without_the_servers_text(where: str) -> None:
    error = _unique()
    assert _P1 in _rendered(error)  # the control: the planted value is in the chain before
    session = _Session(commit=error) if where == "commit" else _Session()
    with pytest.raises(sa_exc.IntegrityError) as raised:
        async with _uow(session) as uow:
            if where == "commit":
                await uow.commit()
            raise error
    assert raised.value is error and _P1 not in _rendered(error)
    assert (error.__cause__, error.__context__, error.__suppress_context__) == (None, None, True)
    assert (cast(Any, error).statement, cast(Any, error).params) == (None, None)
    assert (sqlstate_of(error), constraint_of(error)) == ("23505", "users_email_key")
    # the database's error, never a client's: no class name stands in for its message
    assert str(error).startswith("database error (sqlstate 23505, constraint users_email_key)")
    assert cast(Any, error).orig.client is None
    assert not is_storage_outage(error)
    assert session.calls[-2:] == ["rollback", "close"]


@pytest.mark.parametrize("link", ["cause", "context", "driver-cause"])
async def test_a_domain_error_keeps_its_type_and_loses_the_driver_text(link: str) -> None:
    error = _unique()
    with pytest.raises(LookupError) as raised:
        async with _uow(_Session()):
            try:
                raise error
            except sa_exc.IntegrityError as exc:
                if link == "cause":
                    raise LookupError("name taken") from exc
                if link == "driver-cause":
                    raise LookupError("name taken") from exc.orig
                raise LookupError("name taken")  # noqa: B904 -- the implicit context is the case
    assert str(raised.value) == "name taken" and _P1 not in _rendered(raised.value)


@pytest.mark.parametrize(
    ("driver_cls", "adapted", "state", "invalidated"),
    [
        (asyncpg.exceptions.QueryCanceledError, _Dbapi.Error, "57014", False),
        (asyncpg.exceptions.DeadlockDetectedError, _Dbapi.Error, "40P01", False),
        (asyncpg.exceptions.ConnectionFailureError, _Dbapi.Error, "08006", True),
    ],
    ids=["statement-timeout", "deadlock", "connection-lost"],
)
async def test_an_outage_keeps_its_class_its_invalidated_flag_and_its_sqlstate(
    driver_cls: type[Exception], adapted: type[Exception], state: str, invalidated: bool
) -> None:
    driver = _driver(driver_cls, f"server says no: {_P1}")
    error = cast(sa_exc.DBAPIError, _wrapped(driver, adapted, sa_exc.DBAPIError))
    error.connection_invalidated = invalidated
    kind = type(error)
    with pytest.raises(sa_exc.DBAPIError) as raised:
        async with _uow(_Session()):
            raise error
    assert type(raised.value) is kind and raised.value.connection_invalidated is invalidated
    assert sqlstate_of(raised.value) == state and is_storage_outage(raised.value)
    assert _P1 not in _rendered(raised.value)


async def test_a_rollback_that_fails_escapes_stripped_and_the_session_still_closes() -> None:
    first, second = _unique(), _unique()
    session = _Session(rollback=second)
    with pytest.raises(sa_exc.IntegrityError) as raised:
        async with _uow(session):
            raise first
    assert raised.value is second and session.calls == ["rollback", "close"]
    assert raised.value.__context__ is first and not raised.value.__suppress_context__
    assert _P1 not in _rendered(raised.value)


@pytest.mark.parametrize("ended", ["commit", "rollback"])
async def test_an_error_after_the_transaction_ended_rolls_back_nothing_more(ended: str) -> None:
    error = _unique()
    session = _Session()
    with pytest.raises(sa_exc.IntegrityError):
        async with _uow(session) as uow:
            await getattr(uow, ended)()
            raise error
    assert session.calls == [ended, "close"] and _P1 not in _rendered(error)


async def test_a_close_that_fails_after_a_clean_block_escapes_stripped() -> None:
    lost = _wrapped(
        _driver(asyncpg.exceptions.ConnectionFailureError, f"lost: {_P1}"),
        _Dbapi.Error,
        sa_exc.DBAPIError,
    )
    session = _Session(close=lost)
    with pytest.raises(sa_exc.DBAPIError) as raised:
        async with _uow(session):
            pass
    assert raised.value is lost and session.calls == ["close"]
    assert raised.value.__context__ is None and _P1 not in _rendered(raised.value)


async def test_every_error_of_an_exception_group_leaves_stripped() -> None:
    session = _Session()
    with pytest.raises(ExceptionGroup) as raised:
        async with _uow(session):
            raise ExceptionGroup("two writes failed", [_unique(), _unique()])
    assert session.calls == ["rollback", "close"] and _P1 not in _rendered(raised.value)
    assert [sqlstate_of(e) for e in raised.value.exceptions] == ["23505", "23505"]


async def test_a_cancellation_leaves_with_its_driver_context_stripped() -> None:
    error = _unique()
    session = _Session()
    with pytest.raises(asyncio.CancelledError) as raised:
        async with _uow(session):
            try:
                raise error
            except sa_exc.IntegrityError:
                raise asyncio.CancelledError  # noqa: B904 -- the implicit context is the case
    assert raised.value.__context__ is error and session.calls == ["rollback", "close"]
    assert _P1 not in _rendered(raised.value)


def test_a_note_added_to_a_driver_error_goes_with_its_text() -> None:
    error = _unique()
    error.add_note(f"while writing {_P1}")
    strip_driver_text(error)
    assert not hasattr(error, "__notes__") and _P1 not in _rendered(error)


def test_a_stripped_error_survives_a_pickle_round_trip() -> None:
    error = _unique()
    strip_driver_text(error)
    copy = pickle.loads(pickle.dumps(error))  # noqa: S301 -- our own object, built above
    assert type(copy) is type(error) and _P1 not in _rendered(copy)
    assert (sqlstate_of(copy), constraint_of(copy)) == ("23505", "users_email_key")


async def test_a_write_ahead_timeout_passes_through_as_it_is() -> None:
    cause = TimeoutError("hook outlived its bound")
    timeout = WriteAheadTimeout("write-ahead audit hook timed out")
    timeout.__cause__ = cause
    with pytest.raises(WriteAheadTimeout) as raised:
        async with _uow(_Session()):
            raise timeout
    assert raised.value is timeout and raised.value.__cause__ is cause
    assert str(raised.value) == "write-ahead audit hook timed out"


# -- every catch site still classifies a stripped error as it did the raw one (#2748 rider) ------


def _twins(
    driver_cls: type[Exception], message: str, *, invalidated: bool = False, **facts: str
) -> tuple[sa_exc.DBAPIError, sa_exc.DBAPIError]:
    """The same failure twice: as the driver raised it, and as it leaves a unit of work."""
    build = (_driver(driver_cls, message, **facts) for _ in range(2))
    raw, stripped = (
        cast(sa_exc.DBAPIError, _wrapped(d, _Dbapi.Error, sa_exc.DBAPIError)) for d in build
    )
    raw.connection_invalidated = stripped.connection_invalidated = invalidated
    strip_driver_text(stripped)
    assert _P1 not in _rendered(stripped)
    return raw, stripped


def _raised(run: Callable[[], object]) -> tuple[type[BaseException] | None, object]:
    try:
        run()
    except Exception as exc:
        return type(exc), getattr(exc, "sqlstate", None)
    return None, None


_TIMEOUT = (asyncpg.exceptions.QueryCanceledError, f"canceling statement: {_P1}")


def test_the_oms_stores_map_a_stripped_statement_timeout_as_before() -> None:
    def classify(error: Exception) -> Callable[[], object]:
        def run() -> None:
            with orders._constraints():
                raise error

        return run

    raw, stripped = _twins(*_TIMEOUT)
    assert _raised(classify(stripped)) == _raised(classify(raw))
    assert _raised(classify(stripped))[0] in (StorageQueryFailed, StorageTierUnavailable)


@pytest.mark.parametrize("module", [backups, statechart], ids=["backups", "statechart"])
def test_backups_and_statechart_map_a_stripped_statement_timeout_as_before(module: Any) -> None:
    raw, stripped = _twins(*_TIMEOUT)
    assert type(module._failure("op", stripped)) is type(module._failure("op", raw))
    assert isinstance(module._failure("op", stripped), StorageTierUnavailable)


def test_the_audit_reads_still_see_a_stripped_statement_timeout() -> None:
    raw, stripped = _twins(*_TIMEOUT)
    assert audit._sqlstate(stripped) == audit._sqlstate(raw) == audit._QUERY_CANCELED


def test_drawings_still_retries_a_stripped_deadlock() -> None:
    raw, stripped = _twins(asyncpg.exceptions.DeadlockDetectedError, f"deadlock: {_P1}")
    assert drawings._is_deadlock(stripped) and drawings._is_deadlock(raw)


@pytest.mark.parametrize(
    "driver_cls",
    [asyncpg.exceptions.LockNotAvailableError, asyncpg.exceptions.DeadlockDetectedError],
    ids=["lock-not-available", "deadlock"],
)
def test_account_access_still_answers_busy_to_a_stripped_lock_failure(
    driver_cls: type[Exception],
) -> None:
    raw, stripped = _twins(driver_cls, f"lock failure: {_P1}")
    assert isinstance(account_access._db_refusal(stripped), AccessBusyError)
    assert type(account_access._db_refusal(raw)) is AccessBusyError


def test_the_users_purge_counts_and_ends_on_a_stripped_error_as_before() -> None:
    raw, stripped = _twins(
        asyncpg.exceptions.ConnectionFailureError, f"lost: {_P1}", invalidated=True
    )
    assert type(stripped).__name__ == "DBAPIError"  # the batch's error-counter key
    assert purge._shared(stripped) and purge._shared(raw)


# -- the constraint name each reader finds on a stripped error (#4074 round 1) ----------------

_CHECK = (asyncpg.exceptions.CheckViolationError, f"check: {_P1}")


@pytest.mark.parametrize(
    "reader",
    [orders._violated_constraint, trade_groups._violated_constraint, drawings._constraint_name],
    ids=["orders", "trade-groups", "drawings"],
)
def test_the_constraint_readers_name_a_stripped_violation_as_before(
    reader: Callable[[Any], str | None],
) -> None:
    raw, stripped = _twins(*_CHECK, constraint_name="rps_range")
    assert reader(stripped) == reader(raw) == "rps_range"


@pytest.mark.parametrize(
    ("name", "refusal"),
    [("bk_verify", BackupCheckViolation), (None, BackupWriteOnceViolation)],
    ids=["a-named-check", "the-write-once-guard"],
)
def test_backups_maps_a_stripped_check_violation_as_before(
    name: str | None, refusal: type[Exception]
) -> None:
    raw, stripped = _twins(*_CHECK) if name is None else _twins(*_CHECK, constraint_name=name)
    assert type(backups._failure("op", stripped)) is type(backups._failure("op", raw)) is refusal


def test_workspaces_maps_a_stripped_unique_violation_as_before() -> None:
    raw, stripped = _twins(
        asyncpg.exceptions.UniqueViolationError, f"dup: {_P1}", constraint_name="ux_ws_name"
    )
    before, after = (
        workspaces_codec.map_integrity(cast(sa_exc.IntegrityError, e)) for e in (raw, stripped)
    )
    assert before is not None and after is not None and after.args == before.args


class _PsycopgCheckViolation(Exception):
    """psycopg's shape: the SQLSTATE on the error itself, the constraint name in `diag`."""

    def __init__(self, message: str, constraint: str) -> None:
        super().__init__(message)
        self.sqlstate = self.pgcode = "23514"
        self.diag = type("Diag", (), {"constraint_name": constraint})()


def test_a_psycopg_shaped_violation_keeps_its_state_and_constraint() -> None:
    driver = _PsycopgCheckViolation(f"check: {_P1}", "bk_verify")
    error = sa_exc.IntegrityError("INSERT INTO backups ...", (_P1,), driver, hide_parameters=True)
    before = type(backups._failure("op", error))
    strip_driver_text(error)
    assert (sqlstate_of(error), constraint_of(error)) == ("23514", "bk_verify")
    assert type(backups._failure("op", error)) is before is BackupCheckViolation
    assert _P1 not in _rendered(error)


def test_a_sentinel_in_a_bound_parameter_or_a_trigger_raise_never_leaves() -> None:
    """A parameter and a trigger's RAISE text, each carrying a sentinel: after the strip no form
    of the error renders the statement, the parameters, the DETAIL or the driver's message."""
    raise_text = _driver(asyncpg.exceptions.RaiseError, f"trigger refused row {_P1}")
    error = _wrapped(raise_text, _Dbapi.Error, sa_exc.DBAPIError)
    assert _P1 in _rendered(error)
    strip_driver_text(error)
    text = _rendered(error)
    assert _P1 not in text and "INSERT INTO" not in text and "DETAIL" not in text
    assert sqlstate_of(error) == "P0001"


# -- the 1a review's follow-ups (#2748 slice 2d) ---------------------------------------------------


#: asyncpg's text fields, its statement included, and the adapted error's `detail`: the strip's
#: list, pinned here so that dropping a name from it fails a test.
_TEXT_FIELDS = ("message", "detail", "hint", "context", "internal_query", "query")


def _asyncpg_unique() -> Exception:
    """A unique violation as asyncpg's protocol builds it, the failing statement included."""
    fields = {
        "C": "23505",
        "M": f"duplicate key {_P1}",
        "D": f"Key (email)=({_P1}) already exists.",
        "H": f"see {_P1}",
        "W": f"PL/pgSQL function near {_P1}",
        "q": f"internal {_P1}",
        "n": "users_email_key",
    }
    query = f"INSERT INTO users (email) VALUES ('{_P1}')"  # noqa: S608 -- error text, never run
    return cast(Exception, asyncpg.exceptions.PostgresError.new(fields, query=query))


@pytest.mark.parametrize("shape", ["asyncpg", "emulated"])
def test_an_unwrapped_driver_error_loses_its_text_and_keeps_its_codes(shape: str) -> None:
    raw = _asyncpg_unique()
    adapted: type[Exception] = _Dbapi.IntegrityError
    error = raw if shape == "asyncpg" else adapted(f"adapted: {_P1}", raw)
    error.add_note(f"retried for {_P1}")
    assert _P1 in _rendered(error)
    strip_driver_text(error)
    assert _P1 not in _rendered(error) and not hasattr(error, "__notes__")
    assert all(getattr(error, name, None) is None for name in _TEXT_FIELDS)
    assert getattr(error, "sqlstate", None) == "23505"
    if shape == "emulated":  # the raw error it wrapped is gone, from a pickle too
        assert cast(Any, error).orig is not raw and _P1.encode() not in pickle.dumps(error)
        assert constraint_of(cast(Any, type("Wrapped", (), {"orig": error})())) == "users_email_key"


def test_a_driver_error_raised_in_an_exception_group_loses_its_text() -> None:
    member = _asyncpg_unique()
    group = ExceptionGroup("writes failed", [member])
    strip_driver_text(group)
    assert _P1 not in _rendered(group) and getattr(member, "sqlstate", None) == "23505"
    assert all(getattr(member, name, None) is None for name in _TEXT_FIELDS)


class _PsycopgUnwrapped(Exception):
    """A psycopg error raised as it is: the SQLSTATE as `pgcode`, the constraint in `diag`."""

    __module__ = "psycopg.errors"  # a driver's own error, as `_is_driver` sees it

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.pgcode = "23514"
        self.diag = type("Diag", (), {"constraint_name": "bk_verify"})()


def test_an_unwrapped_psycopg_shaped_error_keeps_its_codes() -> None:
    error = _PsycopgUnwrapped(f"check: {_P1}")
    strip_driver_text(error)
    assert str(error) == "database error (sqlstate 23514, constraint bk_verify)"
    assert _P1 not in _rendered(error)


def test_a_pending_rollback_error_no_longer_quotes_the_error_before_it() -> None:
    error = sa_exc.PendingRollbackError(
        f"This Session's transaction has been rolled back. Original exception was: {_P1}"
    )
    strip_driver_text(error)
    assert type(error) is sa_exc.PendingRollbackError and _P1 not in _rendered(error)


def test_a_client_side_failure_keeps_its_class_name_never_its_text() -> None:
    error = sa_exc.StatementError(
        "bind failed", "INSERT INTO users (email) VALUES ($1)", (_P1,), ValueError(f"bad {_P1}")
    )
    strip_driver_text(error)
    strip_driver_text(error)  # a second strip keeps the client's class name
    copy = pickle.loads(pickle.dumps(error))  # noqa: S301 -- our own object, built above
    assert cast(Any, copy).orig.client == "ValueError"  # `_DriverFacts` pickles its client
    strip_driver_text(copy)  # and a copy stripped again still names it
    for stripped in (error, copy):
        assert "ValueError raised before the database" in str(stripped)
        assert _P1 not in _rendered(stripped) and sqlstate_of(stripped) is None


def test_a_statement_error_with_no_error_behind_it_names_no_client() -> None:
    error = sa_exc.StatementError("no driver error", "SELECT 1", None, None)
    strip_driver_text(error)
    assert str(error).startswith("database error (sqlstate unknown)")
    assert cast(Any, error).orig.client is None


def test_a_domain_error_caused_by_the_adapted_driver_error_loses_that_link() -> None:
    dialect_error: type[Exception] = _Dbapi.Error
    adapted = dialect_error(f"canceling statement: {_P1}", _asyncpg_unique())
    domain = LookupError("name taken")
    domain.__cause__ = adapted
    strip_driver_text(domain)
    assert domain.__cause__ is None and _P1 not in _rendered(domain)


class _Connection:
    def __init__(self, fail: BaseException | None, fail_on: int) -> None:
        self.fail, self.fail_on = fail, fail_on
        self.statements: list[str] = []

    async def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)
        if self.fail is not None and len(self.statements) == self.fail_on:
            raise self.fail


class _StartingSession(_Session):
    """`at`: "connection", or the `SET LOCAL` that fails ("set-local-1", "set-local-2"); any
    other value starts cleanly."""

    def __init__(self, at: str, failure: BaseException | None, close: BaseException | None) -> None:
        super().__init__(**({} if close is None else {"close": close}))
        self.at, self.failure = at, failure
        self.connected: _Connection | None = None

    async def connection(self) -> _Connection:
        self.calls.append("connection")
        if self.at == "connection" and self.failure is not None:
            raise self.failure
        if self.at.startswith("set-local"):
            self.connected = _Connection(self.failure, int(self.at[-1]))
        else:
            self.connected = _Connection(None, 0)
        return self.connected


@pytest.mark.parametrize("at", ["connection", "set-local-1", "set-local-2"])
@pytest.mark.parametrize("close_fails", [False, True], ids=["closed", "close-failed"])
async def test_a_unit_of_work_that_cannot_start_closes_its_session_and_leaves_stripped(
    at: str, close_fails: bool
) -> None:
    failure = _unique()
    close = _wrapped(
        _driver(asyncpg.exceptions.ConnectionFailureError, f"lost: {_P1}"),
        _Dbapi.Error,
        sa_exc.DBAPIError,
    )
    session = _StartingSession(at, failure, close if close_fails else None)
    pending = relational._PendingUnitOfWork(cast(Any, lambda: session), "test")
    with pytest.raises(sa_exc.DBAPIError) as raised:
        async with pending:
            pytest.fail("the unit of work must not start")
    assert session.calls == ["connection", "close"]
    assert raised.value is (close if close_fails else failure)
    if close_fails:  # the close's error keeps the start's failure as its context
        assert raised.value.__context__ is failure and not raised.value.__suppress_context__
    assert _P1 not in _rendered(raised.value)


async def test_a_cancelled_start_closes_its_session_and_the_cancellation_goes_on() -> None:
    session = _StartingSession("connection", asyncio.CancelledError(), None)
    pending = relational._PendingUnitOfWork(cast(Any, lambda: session), "test")
    with pytest.raises(asyncio.CancelledError):
        async with pending:
            pytest.fail("the unit of work must not start")
    assert session.calls == ["connection", "close"]


async def test_a_unit_of_work_starts_with_its_statement_timeout_and_application_name() -> None:
    session = _StartingSession("started", None, None)
    pending = relational._PendingUnitOfWork(cast(Any, lambda: session), "test")
    async with pending as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork) and uow.session is cast(Any, session)
    assert session.connected is not None and session.connected.statements == [
        "SET LOCAL statement_timeout = '30000'",
        "SET LOCAL application_name = 'candleviewer:test'",
    ]
    assert session.calls == ["connection", "close"]


# -- the shared classifier and the typed error a refused statement leaves as (#2748 slice 2a) -----


@pytest.mark.parametrize(
    ("driver_cls", "invalidated"),
    [
        (asyncpg.exceptions.QueryCanceledError, False),
        (asyncpg.exceptions.DeadlockDetectedError, False),
        (asyncpg.exceptions.ConnectionFailureError, True),
        (asyncpg.exceptions.LockNotAvailableError, False),
        (asyncpg.exceptions.UniqueViolationError, False),
        (asyncpg.exceptions.UniqueViolationError, True),
        (asyncpg.exceptions.CheckViolationError, False),
        (asyncpg.exceptions.InvalidTextRepresentationError, False),
        (asyncpg.exceptions.UndefinedTableError, False),
        (asyncpg.exceptions.RaiseError, False),
        (asyncpg.exceptions.InFailedSQLTransactionError, False),
    ],
    ids=[
        *("57014", "40P01", "08006", "55P03", "23505", "23505-invalidated", "23514"),
        *("22P02", "42P01", "P0001", "25P02"),
    ],
)
def test_is_outage_classes_a_driver_error_as_the_http_edge_does(
    driver_cls: type[Exception], invalidated: bool
) -> None:
    raw, stripped = _twins(driver_cls, f"server says: {_P1}", invalidated=invalidated)
    for error in (raw, stripped):
        assert is_outage(error) is is_storage_outage(error)


@pytest.mark.parametrize(
    "error",
    [
        OSError("refused"),
        sa_exc.TimeoutError("pool exhausted"),
        sa_exc.InvalidRequestError("not a statement"),
        sa_exc.OperationalError("SELECT 1", None, Exception("gone")),
        ValueError("not storage"),
    ],
    ids=["oserror", "pool-timeout", "invalid-request", "operational", "other"],
)
def test_is_outage_classes_the_other_failures_as_the_http_edge_does(error: Exception) -> None:
    assert is_outage(error) is is_storage_outage(error)


@pytest.mark.parametrize(
    ("state", "constraint", "kind"),
    [
        ("23505", "users_email_key", StorageConstraintViolated),
        ("23502", None, StorageConstraintViolated),
        ("22P02", None, StorageQueryFailed),
        ("42P01", None, StorageQueryFailed),
        (None, None, StorageQueryFailed),
    ],
)
def test_query_failure_types_a_refused_statement_by_its_facts(
    state: str | None, constraint: str | None, kind: type[StorageQueryFailed]
) -> None:
    failure = query_failure(state, constraint)
    assert type(failure) is kind and failure.sqlstate == state
    if isinstance(failure, StorageConstraintViolated):
        assert failure.constraint == constraint
