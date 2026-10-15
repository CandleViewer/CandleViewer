"""Kline -> `bars_time` rows (E12-S05, BR-07, SR-E12-10).

Exchange klines carry OHLCV only. A kline-sourced row therefore stores **NULL** — never zero —
in every order-flow column (`buy_volume`, `sell_volume`, `delta`, `min_delta`, `max_delta`,
`delta_pct`, `trade_count`, `vwap`): a zero delta is a lie, a NULL is a fact
(`22-api-openapi.yaml` `/market/klines`: "before that point delta/footprint fields are null").
The ILP serializer omits `None` fields, so they read back as NULL.

Rows are tagged `source="kline"`, which ranks below `tape`/`parquet` (`rows.SOURCE_RANK`), and
only *confirmed* klines become rows (an unconfirmed candle is never persisted as closed).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final, Protocol

import structlog

from candleviewer.bars.errors import BarsError
from candleviewer.bars.metrics import bars_kline_refused_total
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import RowFetcher
from candleviewer.bars.rows import (
    BUILD_VERSIONS,
    KLINE_GENERATION,
    BarPersistError,
    bar_param_for,
    row_checksum,
    to_double,
)
from candleviewer.bars.spec import from_wire
from candleviewer.bars.writer import SourceOverwriteRefused, bars_source_overwrite_refused_total
from candleviewer.domain.sql_names import ts_param, ts_us_from_row
from candleviewer.exchange.base.models import KlineEvent


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


KLINE_SOURCE: Final = "kline"
#: Allow-listed `reason` values of `bars_kline_refused_total` (bounded cardinality).
REFUSE_PRECEDENCE_UNKNOWN: Final = "precedence_unknown"
KLINE_REFUSE_REASONS: Final = frozenset({REFUSE_PRECEDENCE_UNKNOWN})
#: Health reason surfaced while the stored-tape lookup is failing (#2053).
PRECEDENCE_HEALTH_REASON: Final = "tape_precedence_unknown"
DEFAULT_LOOKUP_TIMEOUT_S: Final = 2.0
#: Columns a kline cannot know; always NULL on a kline-sourced row.
ORDERFLOW_NULL_COLUMNS: Final = (
    "buy_volume",
    "sell_volume",
    "delta",
    "min_delta",
    "max_delta",
    "delta_pct",
    "trade_count",
    "vwap",
)


class KlineRowError(BarsError):
    """A kline cannot become a `bars_time` row (unconfirmed, wrong symbol/interval)."""


def kline_spec(interval: str) -> BarSpec:
    """The time `BarSpec` for an exchange kline interval code (`"5"` -> 5-minute bars)."""
    return from_wire("time", interval)


def kline_row(event: KlineEvent, spec: BarSpec) -> dict[str, object]:
    """One ILP-ready `bars_time` row for a confirmed kline (designated `ts` = open, µs)."""
    if not event.confirmed:
        raise KlineRowError("An unconfirmed kline is never persisted as a closed bar.")
    if spec.kind != "time" or spec.interval_ms is None:
        raise KlineRowError("Kline rows only exist for time bars.")
    row: dict[str, object] = {
        "ts": event.start,
        "close_ts": event.start + spec.interval_ms * 1000,
        "symbol": event.symbol,
        "bar_param": bar_param_for(spec),
        "open": to_double(event.open),
        "high": to_double(event.high),
        "low": to_double(event.low),
        "close": to_double(event.close),
        "volume": to_double(event.volume),
        **dict.fromkeys(ORDERFLOW_NULL_COLUMNS),
        "is_closed": True,
        "build_version": BUILD_VERSIONS["time"],
        "source": KLINE_SOURCE,
        "generation": KLINE_GENERATION,
        "index": None,  # a kline has no builder index (NULL, never a guess)
    }
    row["row_checksum"] = row_checksum(row)
    return row


def kline_rows(events: Sequence[KlineEvent], spec: BarSpec) -> list[dict[str, object]]:
    """Rows for every confirmed kline in `events`; unconfirmed ones are skipped, not stored."""
    return [kline_row(e, spec) for e in events if e.confirmed]


class RowSubmitter(Protocol):
    async def submit_rows(
        self, rows: list[dict[str, object]], spec: BarSpec, *, source: str
    ) -> None: ...


#: `(symbol, bar_param, open-time µs list) -> open times already holding a tape/parquet row`.
#: The stored-row half of SR-E12-10 (the writer only knows rows this process wrote).
StoredHigherSource = Callable[[str, str, list[int]], Awaitable[set[int]]]


class TapePrecedenceUnknown(BarPersistError):
    """The stored-tape lookup failed, so tape precedence (BR-07) cannot be proven: the kline
    rows are refused, never written over an unknown tape state (#2053)."""


class PrecedenceHealth:
    """Per-(symbol, interval) refusal flags: a success for one key never clears another's."""

    def __init__(self) -> None:
        self._keys: set[tuple[str, str]] = set()

    @property
    def degraded(self) -> bool:
        return bool(self._keys)

    def mark(self, key: tuple[str, str]) -> None:
        self._keys.add(key)

    def clear(self, key: tuple[str, str]) -> None:
        self._keys.discard(key)

    def reason(self) -> str:
        return PRECEDENCE_HEALTH_REASON if self.degraded else ""


def guarded_tape_lookup(
    lookup: StoredHigherSource,
    *,
    timeout_s: float = DEFAULT_LOOKUP_TIMEOUT_S,
    transient: tuple[type[Exception], ...] = (),  # caller-supplied driver errors
) -> StoredHigherSource:
    """Wrap a stored-tape lookup: `OSError`, timeouts and the caller's driver errors
    (`transient`, e.g. asyncpg's, supplied by the composition root: `bars` imports no driver)
    become `TapePrecedenceUnknown`. Cancellation is never swallowed."""
    # Default `(OSError, TimeoutError)`. asyncpg errors derive from `asyncpg.PostgresError` /
    # `asyncpg.InterfaceError`, NOT `OSError`, so they are NOT caught until the caller passes
    # them in `transient` (#398 must wire `(asyncpg.PostgresError, asyncpg.InterfaceError)`;
    # `bars` may not import a driver, #2053).
    caught: tuple[type[BaseException], ...] = (OSError, TimeoutError, *transient)

    async def guarded(symbol: str, bar_param: str, ts: list[int]) -> set[int]:
        try:
            async with asyncio.timeout(timeout_s):
                return await lookup(symbol, bar_param, ts)
        except caught as exc:
            raise TapePrecedenceUnknown(
                f"Stored-tape lookup failed ({type(exc).__name__})."
            ) from exc

    return guarded


async def submit_kline_bars(
    writer: RowSubmitter,
    symbol: str,
    interval: str,
    events: Sequence[KlineEvent],
    *,
    stored_higher: StoredHigherSource,
    health: PrecedenceHealth | None = None,
) -> int:
    """Persist confirmed klines as `source=kline` rows; returns rows queued.

    A kline never overwrites tape (BR-07), **across restarts too**: `stored_higher` is
    mandatory — the writer's own precedence map only knows rows this process wrote, so open
    times already holding a stored tape/parquet row (`stored_tape_lookup`, keyed on the
    deployed dedup key `(ts, symbol, bar_param)`) are refused and counted up front. If the
    writer still refuses the batch (`SourceOverwriteRefused`, a tape row written by this
    process), rows are retried one by one so only the conflicting ones are skipped — never
    forced through. If the lookup itself fails (`TapePrecedenceUnknown`) the whole batch is
    refused: counted (`bars_kline_refused_total{reason=precedence_unknown}`), `health` set,
    nothing queued.
    """
    spec = kline_spec(interval)
    rows = [r for r in kline_rows(events, spec) if r["symbol"] == symbol]
    if rows:
        try:
            taken = await stored_higher(
                symbol, bar_param_for(spec), [ts_us_from_row(r["ts"]) for r in rows]
            )
        except TapePrecedenceUnknown as exc:
            bars_kline_refused_total.labels(REFUSE_PRECEDENCE_UNKNOWN).inc(len(rows))
            if health is not None:
                health.mark((symbol, interval))
            _log().error(
                "kline_rows_refused_precedence_unknown",
                symbol=symbol,
                refused=len(rows),
                error=type(exc.__cause__ or exc).__name__,
            )
            return 0
        if health is not None:
            health.clear((symbol, interval))
        if taken:
            refused = [r for r in rows if ts_us_from_row(r["ts"]) in taken]
            bars_source_overwrite_refused_total.labels(KLINE_SOURCE, "tape").inc(len(refused))
            _log().info("kline_rows_refused_over_stored_tape", symbol=symbol, refused=len(refused))
            rows = [r for r in rows if ts_us_from_row(r["ts"]) not in taken]
    if not rows:
        return 0
    try:
        await writer.submit_rows(rows, spec, source=KLINE_SOURCE)
        return len(rows)
    except SourceOverwriteRefused:
        queued = 0
        for row in rows:
            try:
                await writer.submit_rows([row], spec, source=KLINE_SOURCE)
                queued += 1
            except SourceOverwriteRefused:
                continue  # counted by the writer (`bars_source_overwrite_refused_total`)
        _log().info("kline_rows_skipped_over_tape", symbol=symbol, skipped=len(rows) - queued)
        return queued


_STORED_HIGHER_SQL: Final = (
    "SELECT ts FROM bars_time WHERE symbol = $1 AND bar_param = $2 AND ts >= $3 AND ts <= $4 "
    "AND (source IS NULL OR source != 'kline')"
)  # NULL source = pre-0003 legacy row, which only the tape builder ever wrote


def stored_tape_lookup(conn: RowFetcher) -> StoredHigherSource:
    """The stored-row half of SR-E12-10 over the hot tier: open times in `ts` that already hold
    a tape/parquet (or legacy) `bars_time` row. Parameterised; one bounded range query."""

    async def lookup(symbol: str, bar_param: str, ts: list[int]) -> set[int]:
        if not ts:
            return set()
        rows = await conn.fetch(
            _STORED_HIGHER_SQL, symbol, bar_param, ts_param(min(ts)), ts_param(max(ts))
        )
        wanted = set(ts)
        return {t for t in (ts_us_from_row(r["ts"]) for r in rows) if t in wanted}

    return lookup


__all__ = [
    "KLINE_REFUSE_REASONS",
    "KLINE_SOURCE",
    "ORDERFLOW_NULL_COLUMNS",
    "PRECEDENCE_HEALTH_REASON",
    "KlineRowError",
    "PrecedenceHealth",
    "RowSubmitter",
    "StoredHigherSource",
    "TapePrecedenceUnknown",
    "bars_kline_refused_total",
    "guarded_tape_lookup",
    "kline_row",
    "kline_rows",
    "kline_spec",
    "stored_tape_lookup",
    "submit_kline_bars",
]
