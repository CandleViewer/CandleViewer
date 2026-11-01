"""E24-T06 reference oracle: DuckDB SQL over Parquet files. Imports NO engine code.

`reference/oi.sql` and `reference/funding_basis.sql` are written from 24 §7.2 / §2.7 (plus the
two rulings the SQL headers list). Numbers load as DECIMAL(38,18); the two divisions are exact
HUGEINT arithmetic (DuckDB decimal division is DOUBLE) and come back as scaled integers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from tests.golden.e24._loader import Rows, write_parquet

_SQL = Path(__file__).parent / "reference"
#: Spec-by-ruling: the OI staleness bound (#723 BQ-5). Restated here, not read from the engine.
STALENESS_MS = 600_000
_MS_PER_MIN = 60_000

Ref = dict[int, dict[str, Any]]


def _e(v: int | None, exp: int) -> Decimal | None:
    return None if v is None else Decimal(v).scaleb(-exp)


def run(rows: Rows, root: Path) -> Ref:
    """Write `rows` as Parquet under `root`, run both SQL files, one dict of values per bar."""
    write_parquet(rows, root)
    con = duckdb.connect(":memory:")
    for name, pattern in (
        ("bars", "bars/*/*.parquet"),
        ("oi", "open_interest/*/*/*.parquet"),
        ("funding", "funding_rates/*/*/*.parquet"),
        ("tickers", "tickers/*/*/*.parquet"),
    ):
        con.read_parquet((root / pattern).as_posix(), hive_partitioning=True).create_view(name)
    oi = con.execute((_SQL / "oi.sql").read_text(), {"staleness_ms": STALENESS_MS})
    out: Ref = {}
    for start, oi_, val, delta, quad in oi.fetchall():
        out[start] = {
            "open_interest": oi_, "open_interest_value": val,
            "open_interest_delta": delta, "oi_price_quadrant": quad,
        }  # fmt: skip
    params = {"interval_ms": rows.interval_min * _MS_PER_MIN, "interval_min": rows.interval_min}
    macro, query = (_SQL / "funding_basis.sql").read_text().split(";\n", 1)
    con.execute(macro)  # the half-away-from-zero integer division macro
    fb = con.execute(query, params)
    for start, rate, ann, ttf, bl, bm, pl, pm in fb.fetchall():
        out[start] |= {
            "funding_rate": rate, "funding_annualized": _e(ann, 18), "time_to_funding_ms": ttf,
            "basis:last": bl, "basis:mark": bm,
            "premium_pct:last": _e(pl, 12), "premium_pct:mark": _e(pm, 12),
        }  # fmt: skip
    con.close()
    return out
