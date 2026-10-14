"""Suite-wide DuckDB guard (C-13.5, #2194): extension repos point at a missing local dir so any
implicit/explicit INSTALL/LOAD/ATTACH autoinstall fails locally with zero egress."""

from __future__ import annotations

import re
import tempfile
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
            stripped = re.sub(r"(--[^\n]*\n|/\*.*?\*/)", " ", query, flags=re.S)
            if re.search(r"(^|;)\s*(FORCE\s+)?INSTALL\b", stripped, re.I):
                raise ExtensionDownloadInUnitTest(f"network: {query!r} in a unit test")
        return self._inner.execute(query, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture(autouse=True)
def _cv_no_duckdb_install(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_connect = duckdb.connect

    tmp = tempfile.mkdtemp(prefix="cv-duckdb-ext-")
    missing = tmp + "/no-such-repo"

    def guarded(*args: Any, **kwargs: Any) -> _GuardedConnection:
        cfg = dict(kwargs.pop("config", None) or (args[2] if len(args) > 2 else {}))
        pos = args[:2]
        cfg.setdefault("custom_extension_repository", missing)
        cfg.setdefault("autoinstall_extension_repository", missing)
        cfg.setdefault("extension_directory", tmp + "/ext")
        return _GuardedConnection(real_connect(*pos, config=cfg, **kwargs))

    monkeypatch.setattr(duckdb, "connect", guarded)
    yield
