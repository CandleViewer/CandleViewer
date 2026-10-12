"""Unit tests: DuckDB view layer (AC 8, R0 exit criterion 6)."""

from __future__ import annotations

import time
from pathlib import Path

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
