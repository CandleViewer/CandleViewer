"""`is_storage_outage` branches (#2478): same semantics as workspaces' `_is_outage`."""

from typing import Any

import pytest
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.storage.errors import StorageTierUnavailable


class _Driver(Exception):
    def __init__(self, sqlstate: str | None = None, attr: str = "sqlstate") -> None:
        super().__init__("driver")
        if sqlstate is not None:
            setattr(self, attr, sqlstate)


def _dbapi(orig: Any, cls: type[DBAPIError] = DBAPIError, **kw: Any) -> DBAPIError:
    return cls("SELECT 1", {}, orig, **kw)


@pytest.mark.parametrize(
    "exc",
    [OSError("refused"), ConnectionResetError("reset"), StorageTierUnavailable("down")],
)
def test_is_storage_outage_os_and_tier_errors_are_outages(exc: Exception) -> None:
    assert is_storage_outage(exc)


@pytest.mark.parametrize("cls", [OperationalError, InterfaceError])
def test_is_storage_outage_named_driver_classes_are_outages(cls: type[DBAPIError]) -> None:
    assert is_storage_outage(_dbapi(_Driver(), cls))


def test_is_storage_outage_pool_timeout_is_outage() -> None:
    assert is_storage_outage(PoolTimeoutError("pool"))


def test_is_storage_outage_invalidated_connection_is_outage() -> None:
    assert is_storage_outage(_dbapi(_Driver(), connection_invalidated=True))


@pytest.mark.parametrize("state", ["08006", "40P01", "53300", "57014", "58000", "55P03"])
def test_is_storage_outage_outage_sqlstates_are_outages(state: str) -> None:
    assert is_storage_outage(_dbapi(_Driver(state)))


def test_is_storage_outage_pgcode_attribute_is_read() -> None:
    assert is_storage_outage(_dbapi(_Driver("57014", "pgcode")))


def test_is_storage_outage_sqlstate_from_orig_cause() -> None:
    orig = _Driver()
    orig.__cause__ = _Driver("08006")
    assert is_storage_outage(_dbapi(orig))


def test_is_storage_outage_sqlstate_from_exc_cause() -> None:
    exc = _dbapi(_Driver())
    exc.__cause__ = _Driver("57014")
    assert is_storage_outage(exc)


@pytest.mark.parametrize("state", ["22001", "23505", "42P01", "55000"])
def test_is_storage_outage_bug_sqlstates_are_not_outages(state: str) -> None:
    assert not is_storage_outage(_dbapi(_Driver(state)))


@pytest.mark.parametrize("orig", [_Driver(), _Driver("123")])
def test_is_storage_outage_missing_or_malformed_sqlstate_is_not_outage(orig: _Driver) -> None:
    assert not is_storage_outage(_dbapi(orig))


@pytest.mark.parametrize("cls", [IntegrityError, ProgrammingError])
def test_is_storage_outage_integrity_and_programming_are_not_outages(
    cls: type[DBAPIError],
) -> None:
    assert not is_storage_outage(_dbapi(_Driver(), cls))


def test_is_storage_outage_unrelated_error_is_not_outage() -> None:
    assert not is_storage_outage(ValueError("x"))
