"""Per-table ILP tag schemas for the hot-tier writer (E07-T03).

One `TableSchema` per table this ticket's write path exercises (the tables
named by `MarketDataRepository`: `trades`, `orderbook_deltas`,
`orderbook_snapshots`, `tickers`, `bars_*`). `SYMBOL` columns from
`docs/plan/21-database-schema.md` Sec.4 are tags; everything else is a
field — this file is the single place that decides which, never inferred
per-row (`ilp_writer.py` docstring).
"""

from __future__ import annotations

from candleviewer.storage.questdb.ilp_writer import TableSchema

TRADES_SCHEMA = TableSchema(
    name="trades",
    tag_columns=("symbol", "side", "tick_dir"),
    string_field_columns=("trade_id",),
    boolean_field_columns=("is_block",),
)

# `ts_match` (the exchange's match time, µs) is a TIMESTAMP column (0006, E26-T03), so it is
# written as a timestamp field, never as a LONG.
ORDERBOOK_DELTAS_SCHEMA = TableSchema(
    name="orderbook_deltas",
    tag_columns=("symbol", "side", "action"),
    timestamp_field_columns=("ts_match",),
)

ORDERBOOK_SNAPSHOTS_SCHEMA = TableSchema(
    name="orderbook_snapshots",
    tag_columns=("symbol", "source"),
    string_field_columns=("bids", "asks"),
    timestamp_field_columns=("ts_match",),
)

TICKERS_SCHEMA = TableSchema(
    name="tickers",
    tag_columns=("symbol",),
    timestamp_field_columns=("next_funding_ts",),
)

# E24-T03 (#667): `recv_ts` is a TIMESTAMP column (0001), so it is written as one, never a LONG.
LIQUIDATIONS_SCHEMA = TableSchema(
    name="liquidations",
    tag_columns=("symbol", "side", "stream"),
    timestamp_field_columns=("recv_ts",),
)

KLINES_SCHEMA = TableSchema(
    name="klines",
    tag_columns=("symbol", "interval", "source"),
    boolean_field_columns=("confirmed",),
)

_BAR_TAG_COLUMNS = ("symbol", "bar_param", "source")
_BAR_BOOL_COLUMNS = ("is_closed",)


def _bar_schema(name: str, *, has_open_source_ts: bool = False) -> TableSchema:
    ts_fields = ("close_ts",) + (("open_source_ts",) if has_open_source_ts else ())
    return TableSchema(
        name=name,
        tag_columns=_BAR_TAG_COLUMNS,
        boolean_field_columns=_BAR_BOOL_COLUMNS,
        timestamp_field_columns=ts_fields,
    )


BARS_TIME_SCHEMA = _bar_schema("bars_time")
BARS_TICK_SCHEMA = _bar_schema("bars_tick")
BARS_VOLUME_SCHEMA = _bar_schema("bars_volume")
BARS_RANGE_SCHEMA = _bar_schema("bars_range", has_open_source_ts=True)
BARS_RENKO_SCHEMA = _bar_schema("bars_renko", has_open_source_ts=True)
BARS_DELTA_SCHEMA = _bar_schema("bars_delta")

BAR_SCHEMAS_BY_FAMILY = {
    "time": BARS_TIME_SCHEMA,
    "tick": BARS_TICK_SCHEMA,
    "volume": BARS_VOLUME_SCHEMA,
    "range": BARS_RANGE_SCHEMA,
    "renko": BARS_RENKO_SCHEMA,
    "delta": BARS_DELTA_SCHEMA,
}

FOOTPRINT_CELLS_SCHEMA = TableSchema(
    name="footprint_cells",
    tag_columns=("symbol", "bar_family", "bar_param", "imbalance_flag"),
    boolean_field_columns=("is_poc", "is_va"),
)

ORDERFLOW_METRICS_SCHEMA = TableSchema(
    name="orderflow_metrics",
    tag_columns=("symbol", "regime"),
)

FUNDING_RATES_SCHEMA = TableSchema(
    name="funding_rates",
    tag_columns=("symbol", "source"),
)

# E24-T01 (#665, 21 Sec.4.7): `oi` / `oi_value` are fields; `oi_value` is absent on a REST row.
OPEN_INTEREST_SCHEMA = TableSchema(
    name="open_interest",
    tag_columns=("symbol", "interval", "source"),
)

# E21-T02 (#605, 21 Sec.4.12): the heatmap engine's native column, one row a populated level.
HEATMAP_CELLS_SCHEMA = TableSchema(
    name="heatmap_cells",
    tag_columns=("symbol",),
    boolean_field_columns=("estimated",),
)

ALL_SCHEMAS: dict[str, TableSchema] = {
    "trades": TRADES_SCHEMA,
    "orderbook_deltas": ORDERBOOK_DELTAS_SCHEMA,
    "orderbook_snapshots": ORDERBOOK_SNAPSHOTS_SCHEMA,
    "tickers": TICKERS_SCHEMA,
    "liquidations": LIQUIDATIONS_SCHEMA,
    "klines": KLINES_SCHEMA,
    "footprint_cells": FOOTPRINT_CELLS_SCHEMA,
    "orderflow_metrics": ORDERFLOW_METRICS_SCHEMA,
    "funding_rates": FUNDING_RATES_SCHEMA,
    "open_interest": OPEN_INTEREST_SCHEMA,
    "heatmap_cells": HEATMAP_CELLS_SCHEMA,
    **{schema.name: schema for schema in BAR_SCHEMAS_BY_FAMILY.values()},
}
