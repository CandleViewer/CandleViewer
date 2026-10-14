"""Suite-wide DuckDB guard (C-13.5, #2194): extension repos point at a missing local dir so any
implicit/explicit INSTALL/LOAD/ATTACH autoinstall fails locally with zero egress."""

from __future__ import annotations

import re
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


@pytest.fixture(autouse=True, scope="session")
def _cv_no_duckdb_install(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    real_connect = duckdb.connect
    tmp = str(tmp_path_factory.mktemp("duckdb-ext"))
    missing = tmp + "/no-such-repo"
    settings = {
        "custom_extension_repository": missing,
        "autoinstall_extension_repository": missing,
        "extension_directory": tmp + "/ext",
    }

    def guarded(*args: Any, **kwargs: Any) -> _GuardedConnection:
        cfg = dict(kwargs.pop("config", None) or (args[2] if len(args) > 2 else {}))
        pos = args[:2]
        for k, v in settings.items():
            cfg.setdefault(k, v)
        return _GuardedConnection(real_connect(*pos, config=cfg, **kwargs))

    # Default connection (duckdb.execute/sql) is used by module-level code too.
    default = (
        duckdb.default_connection()
        if callable(duckdb.default_connection)
        else duckdb.default_connection
    )
    for k, v in settings.items():
        default.execute(f"SET {k}='{v}'")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(duckdb, "connect", guarded)
        yield
