"""#2748 (C-12.6): an error leaving a unit of work carries none of the database server's text.

`str(DBAPIError)` and its cause chain hold the server's message and `DETAIL` (`Key (col)=(val)`,
`Failing row contains (...)`), which `hide_parameters=True` leaves, and `traceback` renders them
in the log. `SqlAlchemyUnitOfWork.__aexit__` strips them in place: each driver error keeps its
type, SQLSTATE, constraint name and `connection_invalidated`, so every caller's classification
holds (`api.storage_outage`, the adapters' constraint maps). The errors are built as SQLAlchemy's
asyncpg dialect builds them; the session is a fake. No DB, no network.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, cast

import asyncpg
import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi as _Dbapi

from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories import account_access_sqlalchemy as account_access
from candleviewer.storage.repositories import audit_sqlalchemy as audit
from candleviewer.storage.repositories import backups_sqlalchemy as backups
from candleviewer.storage.repositories import drawings_sqlalchemy as drawings
from candleviewer.storage.repositories import orders_sqlalchemy as orders
from candleviewer.storage.repositories import statechart_sqlalchemy as statechart
from candleviewer.storage.repositories.account_access import AccessBusyError
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyUnitOfWork,
    constraint_of,
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
    driver_cls: type[Exception], message: str, **facts: str
) -> tuple[sa_exc.DBAPIError, sa_exc.DBAPIError]:
    """The same failure twice: as the driver raised it, and as it leaves a unit of work."""
    build = (_driver(driver_cls, message, **facts) for _ in range(2))
    raw, stripped = (
        cast(sa_exc.DBAPIError, _wrapped(d, _Dbapi.Error, sa_exc.DBAPIError)) for d in build
    )
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
    raw, stripped = _twins(asyncpg.exceptions.ConnectionFailureError, f"lost: {_P1}")
    raw.connection_invalidated = stripped.connection_invalidated = True
    assert type(stripped).__name__ == type(raw).__name__  # the batch's error-counter key
    assert purge._shared(stripped) and purge._shared(raw)


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
