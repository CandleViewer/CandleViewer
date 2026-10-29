"""The scanner's evaluation (E08-T09 PR 2b, #4708; 22 `runScanner`, `ScannerRow`, `ScannerMeta`).
Pure: no I/O, no asyncio, no clock. `scanner_service` runs it off the event loop (C-2.18).

- **Universe.** Every ticker whose symbol is a 22 `Symbol`, narrowed to the catalogue's
  `trading` symbols when a catalogue snapshot exists (`listed`); with none, the bulk snapshot as
  it is. The symbols the catalogue drops are counted (`ScanResult.dropped`), never served.
- **Values.** Read from the `TickerEvent`, with the two derived ones in decimal arithmetic:
  `spread_bps` quantised to 4 places and `range_pct_24h` to 8 (ROUND_HALF_EVEN), and the row
  compared on the quantised value, so the value shown is the value compared. The recorded-history
  values (`recorded_values`) are read for `recorded` rows only.
- **Matching.** Each active criterion in `criteria` order: one that needs recording is skipped
  for a `live_only` row (listed in `skipped_criteria`, its field `null`, never read as zero); a
  missing live value does not match; a range is inclusive at both bounds; a class set matches on
  membership.
- **Ranking.** Highest first on the `sort` value; `null` after every value; ties and the `null`
  rows by `symbol` ascending. At most `limit` rows; `capped` when more matched.
"""

from __future__ import annotations

import heapq
import re
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Final

import orjson

from candleviewer.api.scanner_criteria import ScannerCriterionDef
from candleviewer.exchange.base.models import TickerEvent

#: 22 `Symbol`: a USDT linear perpetual.
SYMBOL: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
#: The quantum of each derived value: basis points to 4 places, a fraction to 8 (22 `ScannerRow`).
BPS_QUANTUM: Final = Decimal("0.0001")
FRACTION_QUANTUM: Final = Decimal("0.00000001")
_BPS: Final = Decimal(10000)
_TWO: Final = Decimal(2)
#: `ScannerRow` decimals that are left out when there is no value (not nullable).
_OMITTED: Final = (
    "last_price", "price_change_pct_24h", "volume_24h", "open_interest", "cvd", "tape_speed",
    "liquidation_intensity",
)  # fmt: skip
#: `ScannerRow` fields that are `null` when there is no value.
_NULLABLE: Final = (
    "turnover_24h", "funding_rate", "spread_bps", "range_pct_24h", "oi_change_pct_24h",
    "tape_speed_zscore", "regime",
)  # fmt: skip
#: The values read from recorded history (or `orderflow_metrics`), never from the ticker.
RECORDED_FIELDS: Final = frozenset(
    {"oi_change_pct_24h", "tape_speed_zscore", "regime", "cvd", "tape_speed",
     "liquidation_intensity"}
)  # fmt: skip
#: A ticker that has gone this long without a fresh read is `stale` (22 `Ticker.stale`, 5 s).
STALE_AFTER_US: Final = 5_000_000

Value = Decimal | str
#: One criterion of a canonical filter: an inclusive (min, max) range or a set of classes.
Bound = tuple[Decimal | None, Decimal | None] | frozenset[str]


@dataclass(frozen=True, slots=True)
class ScanQuery:
    """A checked scan request in canonical form, hashable: the cache key's request part. Bounds
    are compared as numbers, so `"0.10"` and `"0.1"` give the same query."""

    filters: tuple[tuple[str, Bound], ...]
    sort: str
    limit: int


@dataclass(frozen=True, slots=True)
class ScanRow:
    symbol: str
    recorded: bool
    values: Mapping[str, Value | None]
    skipped: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScanResult:
    rows: tuple[ScanRow, ...]
    matched: int
    #: Ticker symbols the catalogue snapshot does not list as trading (left out of the scan).
    dropped: int

    @property
    def capped(self) -> bool:
        return self.matched > len(self.rows)


def canonical_filter(
    checked: Mapping[str, Any], criteria: Mapping[str, ScannerCriterionDef]
) -> tuple[tuple[str, Bound], ...]:
    """A filter `check_filter` passed, by criterion id: each range as decimals, each class set
    as a frozenset."""
    out: list[tuple[str, Bound]] = []
    for cid in sorted(checked):
        value = checked[cid]
        if criteria[cid].kind == "class_set":
            out.append((cid, frozenset(value["classes"])))
        else:
            lo, hi = value.get("min"), value.get("max")
            out.append((cid, (_bound(lo), _bound(hi))))
    return tuple(out)


def _bound(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def scan_query(
    checked: Mapping[str, Any], sort: str, limit: int, criteria: Mapping[str, ScannerCriterionDef]
) -> ScanQuery:
    return ScanQuery(canonical_filter(checked, criteria), sort, limit)


def _quantised(value: Decimal, quantum: Decimal) -> Decimal | None:
    try:
        return value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation:  # beyond the context's precision: no value, never a guess
        return None


def spread_bps(t: TickerEvent) -> Decimal | None:
    """`(ask - bid) / mid * 10000`, `mid` the two sides' mean, to 4 places; `None` without both
    sides or with a mid at or below zero."""
    bid, ask = t.bid1_price, t.ask1_price
    if bid is None or ask is None:
        return None
    mid = (ask + bid) / _TWO
    if mid <= 0:
        return None
    return _quantised((ask - bid) / mid * _BPS, BPS_QUANTUM)


def range_pct_24h(t: TickerEvent) -> Decimal | None:
    """`(high - low) / low`, a fraction to 8 places; `None` while either is unknown or the low is
    at or below zero."""
    high, low = t.high_24h, t.low_24h
    if high is None or low is None or low <= 0:
        return None
    return _quantised((high - low) / low, FRACTION_QUANTUM)


def ticker_values(t: TickerEvent) -> dict[str, Value | None]:
    """The `ScannerRow` values a ticker gives."""
    return {
        "last_price": t.last_price, "price_change_pct_24h": t.price_24h_pcnt,
        "volume_24h": t.volume_24h, "open_interest": t.open_interest,
        "turnover_24h": t.turnover_24h, "funding_rate": t.funding_rate,
        "spread_bps": spread_bps(t), "range_pct_24h": range_pct_24h(t),
    }  # fmt: skip


def _matches(value: Value | None, bound: Bound) -> bool:
    if value is None:
        return False
    if isinstance(bound, frozenset):
        return isinstance(value, str) and value in bound
    if not isinstance(value, Decimal):
        return False
    lo, hi = bound
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def _rank(row: ScanRow, sort: str) -> tuple[int, Decimal, str]:
    """Highest first, `null` after every value, then `symbol` ascending."""
    value = row.values.get(sort)
    if isinstance(value, Decimal):
        return 0, -value, row.symbol
    return 1, Decimal(0), row.symbol


def evaluate(
    tickers: Mapping[str, TickerEvent],
    recorded: Set[str],
    recorded_values: Mapping[str, Mapping[str, Value]],
    q: ScanQuery,
    *,
    criteria: Sequence[ScannerCriterionDef],
    listed: Set[str] | None = None,
) -> ScanResult:
    """The rows of `q` over `tickers` (module docstring). `recorded` holds the symbols with
    active recording; `listed`, the catalogue's trading symbols (`None`: no catalogue yet)."""
    active = dict(q.filters)
    order = [c for c in criteria if c.id in active]
    matched: list[ScanRow] = []
    dropped = 0
    for symbol, ticker in tickers.items():
        if not SYMBOL.fullmatch(symbol):
            continue
        if listed is not None and symbol not in listed:
            dropped += 1
            continue
        is_recorded = symbol in recorded
        values = ticker_values(ticker)
        extra = recorded_values.get(symbol, {}) if is_recorded else {}
        values |= {f: extra.get(f) for f in RECORDED_FIELDS}
        skipped: list[str] = []
        ok = True
        for c in order:
            if c.needs_recording and not is_recorded:
                skipped.append(c.id)
            elif not _matches(values.get(c.id), active[c.id]):
                ok = False
                break
        if ok:
            matched.append(ScanRow(symbol, is_recorded, values, tuple(skipped)))
    top = heapq.nsmallest(q.limit, matched, key=lambda r: _rank(r, q.sort))
    return ScanResult(tuple(top), len(matched), dropped)


def _dec(value: Value | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return format(value, "f")


def row_body(row: ScanRow) -> dict[str, object]:
    """22 `ScannerRow`: a non-nullable decimal with no value left out, a nullable one `null`,
    `price_path_24h` left out (no hourly source yet) and `skipped_criteria` always there."""
    body: dict[str, object] = {"symbol": row.symbol}
    for name in _OMITTED:
        value = row.values.get(name)
        if value is not None:
            body[name] = _dec(value)
    body["recording"] = row.recorded
    body["coverage"] = "recorded" if row.recorded else "live_only"
    for name in _NULLABLE:
        body[name] = _dec(row.values.get(name))
    body["skipped_criteria"] = list(row.skipped)
    return body


def iso(us: int) -> str:
    """UTC, six fractional digits and a `Z`."""
    return datetime.fromtimestamp(us / 1e6, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def build_body(
    result: ScanResult, *, generated_at_us: int, inputs: Sequence[Mapping[str, object]]
) -> bytes:
    """The `runScanner` 200 body, serialised once (a cache hit serves these bytes)."""
    meta = {
        "next_cursor": None, "has_more": result.capped, "count": len(result.rows),
        "capped": result.capped, "generated_at": iso(generated_at_us),
        "sources": ["memory", "postgres"], "inputs": [dict(i) for i in inputs],
    }  # fmt: skip
    return orjson.dumps({"items": [row_body(r) for r in result.rows], "meta": meta})


def tickers_input(exchange_ts_us: int, received_at_us: int, now_us: int) -> dict[str, object]:
    """`ScannerInputFreshness` for the ticker snapshot: `stale` as `Ticker.stale` is (5 s)."""
    stale = now_us - received_at_us > STALE_AFTER_US
    return {"input": "tickers", "as_of": iso(exchange_ts_us), "stale": stale}


__all__ = [
    "BPS_QUANTUM", "FRACTION_QUANTUM", "RECORDED_FIELDS", "STALE_AFTER_US", "SYMBOL", "Bound",
    "ScanQuery", "ScanResult", "ScanRow", "build_body", "canonical_filter", "evaluate", "iso",
    "range_pct_24h", "row_body", "scan_query", "spread_bps", "ticker_values", "tickers_input",
]  # fmt: skip
