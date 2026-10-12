"""DuckDB view layer over the Parquet lake — `21-database-schema.md` Sec.5.5.

Views hold no state and are rebuilt from source on every start. DuckDB runs
in-process only (SR-048: no server mode, no port). The optional Postgres
attachment is `READ_ONLY` as the `cv_ro` role, so analytics can never mutate
the ledger. No `INSTALL` is issued for the Parquet path (the reader is built
in), so building the lake views needs no network; the `postgres` extension
is only LOADed (never installed at runtime) when a DSN is supplied (deployment-time).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.models import StreamKind
from candleviewer.storage.sql_identifiers import checked_identifier, sql_string_literal

#: View name -> registered stream (Sec.5.5's worked list).
VIEW_STREAMS: dict[str, StreamKind] = {
    "trades": StreamKind.TRADES,
    "orderbook_deltas": StreamKind.ORDERBOOK_DELTA,
    "bars": StreamKind.BARS,
    "footprint_cells": StreamKind.FOOTPRINT_CELLS,
    # E16-T05: the roll-off archives these too; `_quarantine/` is outside every glob.
    "tickers": StreamKind.TICKERS,
    "liquidations": StreamKind.LIQUIDATIONS,
    "heatmap_cells": StreamKind.HEATMAP_CELLS,
}

#: OMS-sourced views (producers are E41/E29); `oms/<name>/ym=*/`.
_OMS_VIEWS: dict[str, str] = {
    "executions_cold": "executions",
    "journal_cold": "journal_trades",
}

_EMPTY_MARKET_VIEW = (
    "SELECT NULL::VARCHAR AS symbol, NULL::VARCHAR AS dt, "
    "NULL::TIMESTAMPTZ AS ts, NULL::DOUBLE AS price, NULL::DOUBLE AS size, "
    "NULL::DOUBLE AS notional, NULL::VARCHAR AS side WHERE false"
)


def _create_parquet_view(con: duckdb.DuckDBPyConnection, name: str, glob: str) -> bool:
    """DuckDB cannot bind parameters in DDL, so `name` is validated as a plain
    identifier and `glob` is emitted as an escaped string literal."""
    sql = "".join(
        (
            "CREATE OR REPLACE VIEW ",
            checked_identifier(name),
            " AS SELECT * FROM read_parquet(",
            sql_string_literal(glob),
            ", hive_partitioning = true, union_by_name = true)",
        )
    )
    try:
        con.execute(sql)
    except duckdb.IOException:
        return False
    return True


class UnsafeAnalyticsDsn(ValueError):
    """The Postgres DSN for the analytics attachment is not a plain `cv_ro`
    key/value DSN (SR-048: analytics must never hold a writable role)."""


_DSN_FORBIDDEN = frozenset((chr(39), chr(34), ";", chr(10), chr(13)))  # quote, dquote, ;, LF, CR


def _checked_ro_dsn(dsn: str) -> str:
    """Accept only a libpq key/value DSN for the `cv_ro` role with no quote,
    semicolon or newline characters. The DSN is never logged."""
    if any(ch in dsn for ch in _DSN_FORBIDDEN) or "user=cv_ro" not in dsn.split():
        raise UnsafeAnalyticsDsn("analytics attachment requires a plain cv_ro key/value DSN")
    return dsn


def build_views(db_path: Path, registry: DatasetRegistry, *, pg_dsn: str | None = None) -> None:
    """(Re)create every cold-tier view in `db_path` (idempotent).

    The DSN is validated before DuckDB is even opened, so a refused DSN never
    touches extensions or the network. The `postgres` extension is only ever
    LOADed (never INSTALLed at runtime): the deployment image must preinstall it.
    """
    checked_dsn = _checked_ro_dsn(pg_dsn) if pg_dsn else None
    con = duckdb.connect(str(db_path))
    try:
        con.execute("SET TimeZone = 'UTC'")
        con.execute("SET autoinstall_known_extensions = false")
        for view_name, stream in VIEW_STREAMS.items():
            if not _create_parquet_view(con, view_name, registry.dataset_glob(stream)):
                # Not yet exported: a typed empty view so queries return 0 rows.
                empty_ddl = " ".join(
                    (
                        "CREATE OR REPLACE VIEW",
                        checked_identifier(view_name),
                        "AS",
                        _EMPTY_MARKET_VIEW,
                    )
                )
                con.execute(empty_ddl)
        oms_ok: dict[str, bool] = {}
        for view_name, sub in _OMS_VIEWS.items():
            glob = (registry.root / "oms" / sub / "*" / "*.parquet").as_posix()
            oms_ok[view_name] = _create_parquet_view(con, view_name, glob)

        journal_parts = ["SELECT * FROM journal_cold"] if oms_ok["journal_cold"] else []
        if checked_dsn:
            con.execute("LOAD postgres")  # preinstalled in the image; no runtime INSTALL
            con.execute("DETACH DATABASE IF EXISTS pg")
            dsn = checked_dsn
            # ATTACH has no bind params (DuckDB grammar); DSN validated above
            # and emitted as an escaped string literal.
            attach = " ".join(
                ("ATTACH", sql_string_literal(dsn), "AS pg (TYPE postgres, READ_ONLY)")
            )
            con.execute(attach)
            journal_parts.append(
                "SELECT * FROM pg.public.journal_trades "
                "WHERE opened_at >= (current_date - INTERVAL 90 DAY)"
            )
        if journal_parts:
            # `journal_parts` holds only the fixed SELECTs above.
            journal_ddl = "CREATE OR REPLACE VIEW journal_all AS " + " UNION ALL BY NAME ".join(
                journal_parts
            )
            con.execute(journal_ddl)
            con.execute(
                "CREATE OR REPLACE VIEW v_daily_pnl AS "
                "SELECT date_trunc('day', opened_at) AS d, exchange_account_id, env, "
                "sum(net_pnl) AS net_pnl, count(*) AS trades, "
                "sum(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END)::DOUBLE"
                " / nullif(count(*), 0) AS win_rate, avg(r_multiple) AS avg_r "
                "FROM journal_all GROUP BY 1, 2, 3"
            )
        con.execute(
            "CREATE OR REPLACE VIEW v_session_tape_stats AS "
            "SELECT symbol, date_trunc('hour', ts) AS h, count(*) AS prints, "
            "sum(notional) AS notional, "
            "sum(CASE WHEN side = 'Buy' THEN size ELSE -size END) AS delta "
            "FROM trades GROUP BY 1, 2"
        )
    finally:
        con.close()


def query_symbol_day_count(db_path: Path, view: str, symbol: str, dt: str) -> int:
    """R0 exit criterion #6: `SELECT count(*) FROM <view> WHERE symbol=? AND
    dt=?`. `view` must be a registered view name; values are bound."""
    if view not in VIEW_STREAMS:
        raise ValueError(f"unregistered view: {view!r}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        count_sql = " ".join(
            ("SELECT count(*) FROM", checked_identifier(view), "WHERE symbol = ? AND dt = ?")
        )
        row = con.execute(count_sql, [symbol, dt]).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()
