"""Suite-wide DuckDB guard (C-13.5, #2194).

Every connection from `duckdb.connect`, and the default connection behind the module-level
`duckdb.execute`/`sql`/..., is a `GuardedConnection`:
- an INSTALL / FORCE INSTALL statement or an `install_extension()` call raises
  `ExtensionDownloadInUnitTest` before DuckDB sees it (execute, executemany, sql, query,
  from_query, and cursors), so `INSTALL ... FROM core` cannot reach the network;
- the extension repositories and directory point at a missing local path, so LOAD, ATTACH and
  autoinstall fail locally instead of downloading.
DuckDB's own parser splits and tokenises the SQL, so comments, string literals and
multi-statement scripts are read exactly as DuckDB reads them (no regex over SQL text).
Not covered (follow-up): a connection opened through a reference to the real `duckdb.connect`
taken before this fixture ran, and OS-level egress blocking.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

import duckdb
import pytest

from candleviewer.storage.sql_identifiers import sql_string_literal

_INSTALL_WORD = re.compile(r"\binstall\b", re.IGNORECASE)
_WORD = re.compile(r"\w+")
# Connection methods whose first argument is SQL text that DuckDB runs (sql/query/from_query
# run non-SELECT statements eagerly too).
_SQL_ENTRY_POINTS = ("execute", "executemany", "sql", "query", "from_query")
# Methods that return another connection on the same database.
_CURSOR_ENTRY_POINTS = ("cursor", "duplicate")


class ExtensionDownloadInUnitTest(AssertionError):
    """A unit test tried to INSTALL (download) a DuckDB extension."""


def _leading_words(statement: str, count: int) -> list[str]:
    """The first `count` tokens of one statement, upper-cased (the tokenizer skips comments)."""
    words: list[str] = []
    for offset, _kind in duckdb.tokenize(statement)[:count]:
        match = _WORD.match(statement, offset)
        words.append(match.group().upper() if match else "")
    return words


def _is_install(statement: str) -> bool:
    words = _leading_words(statement, 2)
    return words[:1] == ["INSTALL"] or words == ["FORCE", "INSTALL"]


def _installs_extension(sql_text: str) -> bool:
    """True if any statement in `sql_text` is INSTALL or FORCE INSTALL."""
    if not _INSTALL_WORD.search(sql_text):
        return False  # the word is nowhere in the text: skip the parse on the common path
    try:
        statements = duckdb.extract_statements(sql_text)
    except duckdb.Error:
        return False  # unparseable: DuckDB raises its own error and runs nothing
    return any(_is_install(statement.query) for statement in statements)


def _refuse_install_extension(*_args: Any, **_kwargs: Any) -> None:
    raise ExtensionDownloadInUnitTest("network: install_extension() in a unit test")


def _checked(run: Callable[..., Any]) -> Callable[..., Any]:
    def checked(query: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(query, str) and _installs_extension(query):
            raise ExtensionDownloadInUnitTest(f"network: {query!r} in a unit test")
        return run(query, *args, **kwargs)

    return checked


class GuardedConnection:
    """Proxy: the C connection type is immutable, so wrap instead of patching."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if name in _SQL_ENTRY_POINTS:
            return _checked(attribute)
        if name in _CURSOR_ENTRY_POINTS:
            return lambda: GuardedConnection(attribute())
        if name == "install_extension":
            return _refuse_install_extension
        return attribute


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

    def guarded(*args: Any, **kwargs: Any) -> GuardedConnection:
        cfg = dict(kwargs.pop("config", None) or (args[2] if len(args) > 2 else {}))
        pos = args[:2]
        for k, v in settings.items():
            cfg.setdefault(k, v)
        return GuardedConnection(real_connect(*pos, config=cfg, **kwargs))

    # Default connection (duckdb.execute/sql) is used by module-level code too.
    default = (
        duckdb.default_connection()
        if callable(duckdb.default_connection)
        else duckdb.default_connection
    )
    for k, v in settings.items():
        default.execute(" ".join(("SET", k, "=", sql_string_literal(v))))
    guarded_default = GuardedConnection(default)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(duckdb, "connect", guarded)
        for name in (*_SQL_ENTRY_POINTS, *_CURSOR_ENTRY_POINTS, "install_extension"):
            mp.setattr(duckdb, name, getattr(guarded_default, name))
        yield
