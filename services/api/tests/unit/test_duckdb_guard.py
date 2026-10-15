"""Suite-wide DuckDB INSTALL guard (C-13.5, #2194).

The proxy tests use a recording stand-in for the real connection, so a regression in the guard
can never reach the network from here; the real-connection tests only use inputs that also
fail locally (a missing extension repository) if the guard were lost.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest

from tests._duckdb_guard import ExtensionDownloadInUnitTest, GuardedConnection


class _Recorder:
    """Stands in for the real connection and records every call that reaches it."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def execute(self, query: str, *args: Any, **kwargs: Any) -> _Recorder:
        self.calls.append((query, args, kwargs))
        return self

    executemany = sql = query = from_query = execute

    def cursor(self) -> _Recorder:
        return self

    duplicate = cursor

    def install_extension(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("install_extension", args, kwargs))


# The last three hide the INSTALL from anything that strips comments with a regex: a `--` or
# `/*` inside a string literal, and a nested block comment.
INSTALL_SCRIPTS = (
    "INSTALL httpfs",
    "install httpfs",
    "FORCE INSTALL httpfs",
    "force /* why */ install httpfs",
    "INSTALL httpfs FROM core",
    "-- c\nINSTALL httpfs",
    "/*x*/INSTALL httpfs",
    "SELECT 1; INSTALL httpfs",
    "SELECT 1;\n-- c\nINSTALL httpfs",
    "SELECT '--' AS dashes;\nINSTALL httpfs",
    "SELECT '/*' AS open; INSTALL httpfs; SELECT '*/'",
    "/* a /* nested */ b */ INSTALL httpfs",
)

# Statements that only mention the word; a `;` inside a literal is not a statement boundary.
NON_INSTALL_SCRIPTS = (
    "SELECT 1",
    "LOAD postgres",
    "SELECT 'x; INSTALL y' AS note",
    "SELECT 1 -- INSTALL httpfs",
    "-- INSTALL httpfs\nSELECT 1",
    "/* INSTALL httpfs */ SELECT 1",
    'SELECT "install" FROM t',
    "FORCE CHECKPOINT",
    "INSTALL",  # not parseable: DuckDB raises its own error when it runs, nothing to refuse
)

REPOSITORY_SETTINGS = ("custom_extension_repository", "autoinstall_extension_repository")


@pytest.mark.parametrize("script", INSTALL_SCRIPTS)
def test_guard_refuses_install_script_before_duckdb_sees_it(script: str) -> None:
    inner = _Recorder()

    with pytest.raises(ExtensionDownloadInUnitTest):
        GuardedConnection(inner).execute(script)

    assert inner.calls == []


@pytest.mark.parametrize("entry_point", ["execute", "executemany", "sql", "query", "from_query"])
def test_guard_refuses_install_on_every_sql_entry_point(entry_point: str) -> None:
    inner = _Recorder()

    with pytest.raises(ExtensionDownloadInUnitTest):
        getattr(GuardedConnection(inner), entry_point)("INSTALL httpfs FROM core")

    assert inner.calls == []


@pytest.mark.parametrize("make_cursor", ["cursor", "duplicate"])
def test_guard_refuses_install_on_cursors(make_cursor: str) -> None:
    inner = _Recorder()
    cursor = getattr(GuardedConnection(inner), make_cursor)()

    with pytest.raises(ExtensionDownloadInUnitTest):
        cursor.execute("INSTALL httpfs")

    assert inner.calls == []


def test_guard_cursor_still_runs_ordinary_statements() -> None:
    inner = _Recorder()

    GuardedConnection(inner).cursor().execute("SELECT 1")

    assert inner.calls == [("SELECT 1", (), {})]


def test_guard_refuses_install_extension_calls() -> None:
    inner = _Recorder()

    with pytest.raises(ExtensionDownloadInUnitTest):
        GuardedConnection(inner).install_extension("httpfs", repository="core")

    assert inner.calls == []


@pytest.mark.parametrize("script", NON_INSTALL_SCRIPTS)
def test_guard_forwards_statements_that_only_mention_install(script: str) -> None:
    inner = _Recorder()

    GuardedConnection(inner).execute(script)

    assert inner.calls == [(script, (), {})]


def test_guard_forwards_arguments_and_result_unchanged() -> None:
    inner = _Recorder()

    result = GuardedConnection(inner).execute("SELECT ?", [1], extra=True)

    assert result is inner
    assert inner.calls == [("SELECT ?", ([1],), {"extra": True})]


def test_connect_returns_a_guarded_connection_that_refuses_install() -> None:
    con = duckdb.connect(":memory:")

    assert isinstance(con, GuardedConnection)
    with pytest.raises(ExtensionDownloadInUnitTest):
        con.execute("SELECT 1;\n-- c\nINSTALL httpfs")


@pytest.mark.parametrize("entry_point", ["execute", "sql", "query", "from_query"])
def test_default_connection_entry_points_refuse_install(entry_point: str) -> None:
    with pytest.raises(ExtensionDownloadInUnitTest):
        getattr(duckdb, entry_point)("INSTALL httpfs")


def test_default_connection_install_extension_is_refused() -> None:
    with pytest.raises(ExtensionDownloadInUnitTest):
        duckdb.install_extension("httpfs")


def test_load_and_attach_of_a_missing_extension_fail_locally() -> None:
    con = duckdb.connect(":memory:")

    with pytest.raises(duckdb.Error):
        con.execute("LOAD postgres")
    with pytest.raises(duckdb.Error):
        con.sql("ATTACH 'x' AS p (TYPE postgres)")


@pytest.mark.parametrize("setting", REPOSITORY_SETTINGS)
def test_new_connection_extension_repository_is_a_missing_local_dir(setting: str) -> None:
    row = duckdb.connect(":memory:").execute("SELECT current_setting(?)", [setting]).fetchone()

    assert row is not None
    assert Path(row[0]).is_absolute()
    assert not Path(row[0]).exists()


@pytest.mark.parametrize("setting", REPOSITORY_SETTINGS)
def test_default_connection_extension_repository_is_a_missing_local_dir(setting: str) -> None:
    row = duckdb.execute("SELECT current_setting(?)", [setting]).fetchone()

    assert row is not None
    assert Path(row[0]).is_absolute()
    assert not Path(row[0]).exists()
