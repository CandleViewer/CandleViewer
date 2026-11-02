"""Bar -> `bars_*` row mapping at the storage boundary (E12-T02, #345).

`21-database-schema.md` §4.8. The domain model stays exact (`Decimal`, E12-T01); this module is
the only place a `Decimal` becomes a `DOUBLE`.

**Decimal -> DOUBLE rounding rule** (`to_double`): the nearest IEEE-754 binary64, ties to even
(CPython's correctly rounded `float(Decimal)`). Non-finite values are refused, `-0` is stored
as `0.0`. A value that is not exactly representable (e.g. `0.1`) therefore reads back as the
nearest double, never as a neighbour; it never goes through an intermediate `float` of a
`float`. Reads convert back with `Decimal(repr(x))`, which round-trips every stored double.
An OHLC price that does not read back as itself (more digits than a double holds) is still
stored, and counted (`to_price_double`, `bars_write_roundtrip_mismatch_total`, BR-14).

Persistence refuses `synthetic` bars (`assert_persistable`) and any spec whose options have no
wire form (so `bar_param` is always rendered from a *validated* spec, never from client text).
No import of `candleviewer.storage` (C-3.1): the row dicts go to any sink with IlpWriter's
`write_rows(table, rows, ts_key)` shape, composed at the composition root.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from decimal import Decimal
from typing import Final

from candleviewer.bars.errors import BarsError
from candleviewer.bars.metrics import bars_write_roundtrip_mismatch_total
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
#: Provenance cutover (BR-05), bar open time in µs: 2026-10-07T00:00:00Z, the day QuestDB
#: migration 0003 added `source` and `row_checksum` and the bar writer began stamping both on
#: every row. A row with NULL `source` AND NULL `row_checksum` is trusted as legacy only when it
#: opens before this instant; from it on, and for any other NULL checksum, it is "missing".
PROVENANCE_CUTOVER_US: Final = 1_791_331_200_000_000
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
#: The bar flags (QuestDB 0008, #5396; 21 §4.8). The checksum appends each only when true, as
#: `name=True`, so a row written before 0008 (every flag false or absent) verifies unchanged.
FLAG_COLUMNS: Final = ("gap_before", "partial", "tape_gap")


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


def to_price_double(value: Decimal) -> float:
    """`to_double` for an OHLC price, counting one whose double reads back as another decimal
    (BR-14: two reads, or a read and a rebuild, would then differ). Volumes and the derived
    `vwap` / `delta_pct` are not checked: a quotient is inexact by construction."""
    out = to_double(value)
    if Decimal(repr(out)) != value:
        bars_write_roundtrip_mismatch_total.inc()
    return out


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
    """63-bit sha256 prefix over the value columns (SR-E12-11); timestamps are the key, not data.

    From 0008 the flags a row holds as true are appended (`FLAG_COLUMNS`, `name=True`): a false
    or absent flag adds nothing, so a pre-0008 row's checksum is the one it was written with."""
    fields = [f"{k}={row.get(k)!r}" for k in _CHECKSUM_FIELDS]
    fields += [f"{k}={True!r}" for k in FLAG_COLUMNS if row.get(k) is True]
    blob = "\x1f".join(fields)
    return int.from_bytes(hashlib.sha256(blob.encode()).digest()[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def table_for(spec: BarSpec) -> str:
    return f"bars_{spec.kind}"


#: Generation of a kline-sourced row: an exchange kline has no builder epoch (`kline_rows`). Every
#: other row carries its series' epoch (`BarBuilderSet`, #2662), so `bar_row` has no default.
KLINE_GENERATION: Final = 0
#: Largest generation a row or a state blob may carry. Below 2**53, so it stays a safe JSON integer
#: on the WS wire (the TS converter rejects larger values), with headroom for the `floor + 1` step.
MAX_GENERATION: Final = 2**52


def check_generation(generation: object, *, source: str) -> None:
    """Refuse a generation outside 0..`MAX_GENERATION`, or a kline row's that is not the kline one.

    The write boundary: a float or a bool would break the LONG column, and a runaway value would
    outgrow what the wire and the state loader accept."""
    if type(generation) is not int or not 0 <= generation <= MAX_GENERATION:
        raise BarPersistError(f"A bar generation must be an integer in 0..{MAX_GENERATION}.")
    if source == "kline" and generation != KLINE_GENERATION:
        raise BarPersistError("A kline row carries the kline generation: it has no builder epoch.")


def bar_row(bar: Bar, spec: BarSpec, *, source: str = "tape", generation: int) -> dict[str, object]:
    """One ILP-ready row (designated timestamp `ts` = bar open, µs). Raises on synthetic bars."""
    return _row(bar, spec, source, generation, to_price_double)


def tape_row_checksum(bar: Bar, spec: BarSpec, generation: int) -> int | None:
    """The `row_checksum` the writer stores for `bar` as a tape row of `generation`: the version
    `bars.write_holes` compares (#5396). None when the bar has no stored form. It counts no
    `bars_write_roundtrip_mismatch_total`: nothing is written."""
    try:
        value = _row(bar, spec, "tape", generation, to_double)["row_checksum"]
    except (BarsError, ValueError):
        return None
    return int(str(value))


def _row(
    bar: Bar, spec: BarSpec, source: str, generation: int, price: Callable[[Decimal], float]
) -> dict[str, object]:
    """`bar_row`, with `price` turning an OHLC price into its column (both give the same value)."""
    assert_persistable(bar)
    if source not in SOURCES:
        raise BarPersistError(f"The source '{source}' is not one of {', '.join(SOURCES)}.")
    check_generation(generation, source=source)
    delta_pct = to_double(bar.delta / bar.volume * 100) if bar.volume else 0.0
    row: dict[str, object] = {
        "ts": bar.open_time,
        "close_ts": bar.close_time,
        "symbol": bar.symbol,
        "bar_param": bar_param_for(spec),
        "open": price(bar.open),
        "high": price(bar.high),
        "low": price(bar.low),
        "close": price(bar.close),
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
        "gap_before": bar.gap_before,  # the flags as the builder set them (21 §4.8, 0008)
        "partial": bar.partial,
        "tape_gap": bar.tape_gap,
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
