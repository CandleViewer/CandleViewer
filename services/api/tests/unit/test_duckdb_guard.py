from __future__ import annotations

import duckdb
import pytest

from tests._duckdb_guard import ExtensionDownloadInUnitTest


def test_guard_blocks_install_and_fails_load_offline() -> None:
    con = duckdb.connect(":memory:")
    for q in ("-- c\nINSTALL httpfs", "/*x*/INSTALL httpfs", "SELECT 1; INSTALL httpfs"):
        with pytest.raises(ExtensionDownloadInUnitTest):
            con.execute(q)
    with pytest.raises(duckdb.Error):
        con.execute("LOAD postgres")
    with pytest.raises(duckdb.Error):
        con.sql("ATTACH 'x' AS p (TYPE postgres)")
    with pytest.raises(duckdb.Error):
        con.install_extension("httpfs")


def test_default_connection_install_fails_locally() -> None:
    import duckdb

    with pytest.raises(duckdb.Error):
        duckdb.execute("INSTALL httpfs")
