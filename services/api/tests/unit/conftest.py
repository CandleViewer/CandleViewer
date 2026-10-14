"""Unit-suite guard: no DuckDB extension download/load from unit tests (C-13.5, #2194)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import duckdb
import pytest


class ExtensionDownloadInUnitTest(AssertionError):
    """A unit test tried to INSTALL (download) a DuckDB extension."""


class _GuardedConnection:
    """Proxy: the C connection type is immutable, so wrap instead of patching."""

    def __init__(self, inner: duckdb.DuckDBPyConnection) -> None:
        self._inner = inner

    def execute(self, query: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(query, str):
            words = query.split()
            head = [w.upper() for w in words[:2]]
            if "INSTALL" in head:
                raise ExtensionDownloadInUnitTest(f"network: {query!r} in a unit test")
        return self._inner.execute(query, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture(autouse=True)
def _cv_no_duckdb_install(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_connect = duckdb.connect

    def guarded(*args: Any, **kwargs: Any) -> _GuardedConnection:
        return _GuardedConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(duckdb, "connect", guarded)
    yield
