"""Unit tests: DuckDB view layer (AC 8, R0 exit criterion 6)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import duckdb
import pytest

from candleviewer.storage.cold.duckdb_views import build_views, query_symbol_day_count
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.models import StreamKind
from tests.unit.storage.cold._helpers import FakeHotSource, day_range, fixed_clock, trades_table


async def _export(root: Path, n: int) -> None:
    await ColdExporter(
        DatasetRegistry(root), FakeHotSource(trades_table(n)), clock=fixed_clock
    ).export_partition("BTCUSDT", StreamKind.TRADES, day_range())


async def test_symbol_day_count_equals_exported_rows_within_budget(tmp_path: Path) -> None:
    await _export(tmp_path, 1234)
    db = tmp_path / "analytics.duckdb"
    build_views(db, DatasetRegistry(tmp_path))
    started = time.perf_counter()
    count = query_symbol_day_count(db, "trades", "BTCUSDT", "2026-10-17")
    elapsed = time.perf_counter() - started
    assert count == 1234
    assert elapsed < 2.0  # Sec.13.3: <2 s for a month of trades; one day is far below


async def test_views_rebuild_idempotently_and_expose_utc_micros(tmp_path: Path) -> None:
    await _export(tmp_path, 3)
    db = tmp_path / "analytics.duckdb"
    build_views(db, DatasetRegistry(tmp_path))
    build_views(db, DatasetRegistry(tmp_path))
    con = duckdb.connect(str(db), read_only=True)
    try:
        con.execute("SET TimeZone = 'UTC'")
        row = con.execute("SELECT min(epoch_us(ts)), typeof(ts) FROM trades GROUP BY 2").fetchone()
        stats = con.execute("SELECT sum(prints) FROM v_session_tape_stats").fetchone()
    finally:
        con.close()
    assert row == (day_range().start_us, "TIMESTAMP WITH TIME ZONE")
    assert stats == (3,)


def test_views_exist_and_are_empty_before_any_export(tmp_path: Path) -> None:
    db = tmp_path / "analytics.duckdb"
    build_views(db, DatasetRegistry(tmp_path))
    for view in ("trades", "orderbook_deltas", "bars", "footprint_cells"):
        assert query_symbol_day_count(db, view, "BTCUSDT", "2026-10-17") == 0


def test_journal_views_union_cold_parquet(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    oms = tmp_path / "oms" / "journal_trades" / "ym=2026-09"
    oms.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "opened_at": pa.array([1], type=pa.timestamp("us", tz="UTC")),
                "exchange_account_id": ["a"],
                "env": ["demo"],
                "net_pnl": pa.array([1.5]),
                "r_multiple": pa.array([0.5]),
            }
        ),
        oms / "part-0000.parquet",
    )
    db = tmp_path / "analytics.duckdb"
    build_views(db, DatasetRegistry(tmp_path))
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute("SELECT trades, win_rate FROM v_daily_pnl").fetchall() == [(1, 1.0)]
    finally:
        con.close()


def test_query_symbol_day_count_rejects_unregistered_view(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unregistered view"):
        query_symbol_day_count(tmp_path / "x.duckdb", "pg.public.users", "BTCUSDT", "2026-10-17")


@pytest.mark.parametrize(
    "dsn",
    [
        "dbname=candleviewer user=cv_app host=127.0.0.1",
        "dbname=x user=cv_ro' AS pg; ATTACH 'y",
        "dbname=x user=cv_ro\nhost=evil",
    ],
)
def test_postgres_attach_rejects_non_cv_ro_or_injected_dsn(tmp_path: Path, dsn: str) -> None:
    from candleviewer.storage.cold.duckdb_views import UnsafeAnalyticsDsn

    with pytest.raises(UnsafeAnalyticsDsn):
        build_views(tmp_path / "a.duckdb", DatasetRegistry(tmp_path), pg_dsn=dsn)


def test_unsafe_dsn_refused_before_any_duckdb_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (#2235): refusal must precede connect/INSTALL/LOAD (no network)."""
    from candleviewer.storage.cold import duckdb_views
    from candleviewer.storage.cold.duckdb_views import UnsafeAnalyticsDsn

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("duckdb touched before DSN validation")

    monkeypatch.setattr(duckdb_views.duckdb, "connect", _boom)
    with pytest.raises(UnsafeAnalyticsDsn):
        build_views(tmp_path / "a.duckdb", DatasetRegistry(tmp_path), pg_dsn="dbname=x user=cv_app")


@pytest.mark.parametrize(
    "dsn",
    [
        "dbname=x user=cv_ro user=cv_app",
        "dbname=x user=cv_app user=cv_ro",
        "dbname=x user=cv_ro host=evil sslmode=require",
        "dbname=x user=cv_ro host=postgres.evil",
        "dbname=x user=cv_ro host=10.0.0.5",
        "dbname=x user=cv_ro service=svc",
        "dbname=x user=cv_ro passfile=/etc/pw",
        "dbname=x user=cv_ro options=-cx=y",
        "dbname=x user=cv_ro host=postgres sslmode=disable",
        "dbname=x user=cv_ro host=a\\b",
        "dbname=x user=cv_ro host=a'b",
        "dbname=x user=cv_ro\nhost=127.0.0.1",
        "dbname=x user=cv_ro host=/var/tmpx,evil.example.com",
        "dbname=x user=cv_ro host=/var/run/postgresql,10.0.0.5",
        "dbname=x user=cv_ro host=/run/postgresql/../evil",
        "dbname=x user=cv_ro host=/tmp sslmode=require",
        "dbname=x user=cv_ro host=/",
        "dbname=postgresql://evil/x user=cv_ro host=localhost",
        "dbname=-x user=cv_ro host=localhost",
        "dbname=x user=cv_ro host=localhost port=abc",
        "dbname=x user=cv_ro host=localhost port=99999999999",
        "dbname=x user=cv_ro host=localhost host=postgres",
        "dbname=x user=cv_ro host=localhost bare",
        "dbname=x user=cv_ro host=localhost port=",
        "dbname=x USER=cv_ro host=localhost",
        "dbname=x\tuser=cv_ro host=localhost",
        "dbname=x user=cv_ro2 host=localhost",
        "dbname=x user=cv_ro",
        "dbname=x user=cv_ro host=postgres",
        "dbname=x user=cv_ro host=postgres sslmode=prefer",
        "dbname=x user=cv_ro host=localhost sslmode=allow",
        "dbname=x user=cv_ro host=lo\x7fcalhost",
        "dbname=x user=cv_ro host=localhost\u00e9",
        "dbname=x user=cv_ro host=127.0.0.1 port=1=2",
    ],
)
def test_checked_ro_dsn_rejects_bypass_cases(dsn: str) -> None:
    from candleviewer.storage.cold.duckdb_views import UnsafeAnalyticsDsn, _checked_ro_dsn

    with pytest.raises(UnsafeAnalyticsDsn):
        _checked_ro_dsn(dsn)


_OK_DSN = "dbname=x user=cv_ro host=localhost"


class _RecordingCon:
    def __init__(self, fail_load: bool) -> None:
        self.sql: list[str] = []
        self._fail_load = fail_load

    def execute(self, sql: str, *_a: object) -> _RecordingCon:
        self.sql.append(sql)
        if self._fail_load and sql == "LOAD postgres":
            raise duckdb.IOException("extension not found")
        return self

    def close(self) -> None:
        return None


def _patch_connect(monkeypatch: pytest.MonkeyPatch, con: _RecordingCon) -> None:
    from candleviewer.storage.cold import duckdb_views

    monkeypatch.setattr(duckdb_views.duckdb, "connect", lambda *_a, **_k: con)


def test_valid_cv_ro_dsn_reaches_load_and_never_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = _RecordingCon(fail_load=False)
    _patch_connect(monkeypatch, con)
    dsn = "dbname=candleviewer user=cv_ro host=127.0.0.1 port=5432 sslmode=prefer"
    build_views(tmp_path / "a.duckdb", DatasetRegistry(tmp_path), pg_dsn=dsn)
    assert "LOAD postgres" in con.sql
    assert not any(q.upper().startswith("INSTALL") for q in con.sql)
    assert any(q.startswith("ATTACH") for q in con.sql)


def test_missing_extension_raises_typed_error_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.storage.cold.duckdb_views import PostgresExtensionUnavailable

    con = _RecordingCon(fail_load=True)
    _patch_connect(monkeypatch, con)
    with pytest.raises(PostgresExtensionUnavailable):
        build_views(tmp_path / "a.duckdb", DatasetRegistry(tmp_path), pg_dsn=_OK_DSN)
    assert not any(q.upper().startswith("INSTALL") for q in con.sql)


@pytest.mark.parametrize(
    "host", ["postgres", "127.0.0.1", "::1", "localhost", "/var/run/postgresql", "/run/postgresql"]
)
def test_checked_ro_dsn_accepts_allowed_hosts(host: str) -> None:
    from candleviewer.storage.cold.duckdb_views import _checked_ro_dsn

    dsn = f"dbname=x user=cv_ro host={host} sslmode=require"
    assert _checked_ro_dsn(dsn) == dsn


def test_local_hosts_allow_prefer_disable_or_absent_sslmode() -> None:
    from candleviewer.storage.cold.duckdb_views import _checked_ro_dsn

    for ssl in ("", " sslmode=prefer", " sslmode=disable"):
        dsn = f"dbname=x user=cv_ro host=/run/postgresql{ssl}"
        assert _checked_ro_dsn(dsn) == dsn


def test_validated_dsn_reaches_attach_as_escaped_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = _RecordingCon(fail_load=False)
    _patch_connect(monkeypatch, con)
    build_views(tmp_path / "a.duckdb", DatasetRegistry(tmp_path), pg_dsn=_OK_DSN)
    attach = next(q for q in con.sql if q.startswith("ATTACH"))
    assert attach == "ATTACH 'dbname=x user=cv_ro host=localhost' AS pg (TYPE postgres, READ_ONLY)"


def test_build_views_disables_extension_autoload_and_autoinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (#2194): a LOAD of a missing extension must never autoload/download."""
    con = _RecordingCon(fail_load=False)
    _patch_connect(monkeypatch, con)
    build_views(tmp_path / "a.duckdb", DatasetRegistry(tmp_path))
    assert "SET autoinstall_known_extensions = false" in con.sql
    assert "SET autoload_known_extensions = false" in con.sql


def test_real_connection_has_autoload_off_and_missing_extension_is_typed(tmp_path: Path) -> None:
    """Real DuckDB, empty extension dir: typed error, nothing downloaded."""
    from candleviewer.storage.cold import duckdb_views
    from candleviewer.storage.cold.duckdb_views import PostgresExtensionUnavailable

    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()
    seen: list[object] = []
    real = duckdb.connect

    class _Spy:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def close(self) -> None:
            row = self._inner.execute("SELECT current_setting('autoload_known_extensions')")
            seen.append(row.fetchone())
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    def connect(path: str) -> object:
        return _Spy(real(path, config={"extension_directory": str(ext_dir)}))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(duckdb_views.duckdb, "connect", connect)
        with pytest.raises(PostgresExtensionUnavailable):
            build_views(tmp_path / "a.duckdb", DatasetRegistry(tmp_path), pg_dsn=_OK_DSN)
    assert not any(ext_dir.iterdir())
    assert seen
    assert all(row == (False,) for row in seen)
