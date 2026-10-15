"""Bar -> `bars_*` row mapping at the storage boundary (E12-T02, #345).

`21-database-schema.md` §4.8. The domain model stays exact (`Decimal`, E12-T01); this module is
the only place a `Decimal` becomes a `DOUBLE`.

**Decimal -> DOUBLE rounding rule** (`to_double`): the nearest IEEE-754 binary64, ties to even
(CPython's correctly rounded `float(Decimal)`). Non-finite values are refused, `-0` is stored
as `0.0`. A value that is not exactly representable (e.g. `0.1`) therefore reads back as the
nearest double, never as a neighbour; it never goes through an intermediate `float` of a
`float`. Reads convert back with `Decimal(repr(x))`, which round-trips every stored double.

Persistence refuses `synthetic` bars (`assert_persistable`) and any spec whose options have no
wire form (so `bar_param` is always rendered from a *validated* spec, never from client text).
No import of `candleviewer.storage` (C-3.1): the row dicts go to any sink with IlpWriter's
`write_rows(table, rows, ts_key)` shape, composed at the composition root.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Final

from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.series import assert_persistable
from candleviewer.bars.spec import to_wire

#: Bumped by a builder-algorithm change; rows below it are served stale + rebuilt (E12-T02).
BUILD_VERSIONS: Final[dict[str, int]] = {
    "time": 1,
    "tick": 1,
    "volume": 1,
    "range": 1,
    "renko": 1,
    "delta": 1,
}
#: `bar_param` SYMBOL CAPACITY (21-database-schema.md §4.8): a hard cardinality budget.
BAR_PARAM_CAPACITY: Final = 64
SOURCES: Final = ("tape", "kline", "parquet")
#: Source precedence (SR-E12-10/BR-07): a lower-ranked source never overwrites a higher one.
#: Parquet rows are restored tape, so they rank with tape; exchange klines are cross-check only.
SOURCE_RANK: Final = {"tape": 2, "parquet": 2, "kline": 1}
#: Unkeyed sha256 prefix: tamper-evidence for naive edits only (no HMAC; see 21-database-schema).
#: Rows with NULL `source` AND NULL `row_checksum` predate migration 0003 (which is the first
#: writer of both columns) and are trusted as legacy; any other NULL checksum is "missing".
_PREFIX: Final = {
    "tick": "tick",
    "volume": "vol",
    "range": "range",
    "renko": "renko",
    "delta": "delta",
}
_CHECKSUM_FIELDS: Final = (
    "symbol", "bar_param", "open", "high", "low", "close", "volume", "buy_volume",
    "sell_volume", "delta", "min_delta", "max_delta", "delta_pct", "trade_count", "vwap",
    "is_closed", "build_version", "source", "generation", "index",
)  # fmt: skip


class BarPersistError(BarsError):
    """A bar cannot be turned into a storable row (non-finite value, unrenderable spec)."""


class BarParamCapacityExceeded(BarsError):
    """A new `bar_param` would exceed the SYMBOL capacity of its table (alertable, never grown)."""


def to_double(value: Decimal) -> float:
    """The documented Decimal -> DOUBLE rule: nearest binary64, ties-to-even; no NaN/Inf."""
    if not value.is_finite():
        raise BarPersistError(f"Cannot store the non-finite value {value} as a DOUBLE.")
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        raise BarPersistError(f"The value {value} overflows a DOUBLE.")
    return out + 0.0  # -0.0 -> 0.0


def bar_param_for(spec: BarSpec) -> str:
    """Human-readable `bar_param` (`5m`, `tick:500`, ...), rendered from the validated spec."""
    try:
        _, param = to_wire(spec)
    except BarsError as exc:
        raise BarPersistError(f"The spec cannot be persisted: {exc}") from exc
    if spec.kind != "time":
        return f"{_PREFIX[spec.kind]}:{param}"
    minutes = int(spec.param_value) // 60_000
    if minutes % 10_080 == 0:
        return f"{minutes // 10_080}w"
    if minutes % 1_440 == 0:
        return f"{minutes // 1_440}d"
    return f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"


def row_checksum(row: dict[str, object]) -> int:
    """63-bit sha256 prefix over the value columns (SR-E12-11); timestamps are the key, not data."""
    blob = "\x1f".join(f"{k}={row.get(k)!r}" for k in _CHECKSUM_FIELDS)
    return int.from_bytes(hashlib.sha256(blob.encode()).digest()[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def table_for(spec: BarSpec) -> str:
    return f"bars_{spec.kind}"


#: Generation of a kline-sourced row: an exchange kline has no builder epoch (`kline_rows`). Every
#: other row carries its series' epoch (`BarBuilderSet`, #2662), so `bar_row` has no default.
KLINE_GENERATION: Final = 0


def bar_row(bar: Bar, spec: BarSpec, *, source: str = "tape", generation: int) -> dict[str, object]:
    """One ILP-ready row (designated timestamp `ts` = bar open, µs). Raises on synthetic bars."""
    assert_persistable(bar)
    if source not in SOURCES:
        raise BarPersistError(f"The source '{source}' is not one of {', '.join(SOURCES)}.")
    delta_pct = to_double(bar.delta / bar.volume * 100) if bar.volume else 0.0
    row: dict[str, object] = {
        "ts": bar.open_time,
        "close_ts": bar.close_time,
        "symbol": bar.symbol,
        "bar_param": bar_param_for(spec),
        "open": to_double(bar.open),
        "high": to_double(bar.high),
        "low": to_double(bar.low),
        "close": to_double(bar.close),
        "volume": to_double(bar.volume),
        "buy_volume": to_double(bar.buy_volume),
        "sell_volume": to_double(bar.sell_volume),
        "delta": to_double(bar.delta),
        "min_delta": to_double(bar.min_delta),
        "max_delta": to_double(bar.max_delta),
        "delta_pct": delta_pct,
        "trade_count": bar.trade_count,
        "vwap": to_double(bar.vwap),
        "is_closed": bar.closed,
        "build_version": BUILD_VERSIONS[spec.kind],
        "source": source,
        "generation": generation,
        "index": bar.index,  # bar identity with (bar_param, generation); NOT derived from ts
    }
    row["row_checksum"] = row_checksum(row)
    return row


#: Retention registration (`21-database-schema.md` §7). Execution is E16; this is the policy +
#: archive path it consumes. `cold_days=None` = forever.
RETENTION: Final[dict[str, tuple[int, int | None]]] = {
    "bars_time": (365, None),
    **{f"bars_{k}": (90, 730) for k in ("tick", "volume", "range", "renko", "delta")},
}
ARCHIVE_ACTION: Final = "archive_parquet"
