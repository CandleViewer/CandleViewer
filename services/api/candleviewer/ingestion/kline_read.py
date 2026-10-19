"""Cache-first `/market/klines` read path (E12-S05, `22-api-openapi.yaml` `/market/klines`).

Source priority (OpenAPI): (1) tape-built bars, (2) exchange REST kline backfill for windows
the store does not hold, (3) the Parquet cold tier for windows older than QuestDB hot
retention.

**Tape wins over klines on overlap (E12-T05, #398).** When the composition root injects a
`tape` reader (tape-built `bars_time` rows), its bars replace kline rows with the same open time
and `sources` gains `tape` only when such a row is actually returned. Without one (no `BarWriter`
composed, `bars_enabled` off) the read is klines-only and never claims tape.
The cold tier is wired by the composition root (`ParquetKlineReader`, #2048); the route's
catalogue check precedes any cold path join.

`read()` never waits on the exchange: it serves what the tiers hold now and, if the hot part
of the window has holes, starts (or joins) the single background backfill job for that
`(symbol, interval)`; the chart is interactive before paging finishes, and the next read picks
up the new rows. Every result states the tiers it touched (`sources`) and where tick-accurate
data begins (`recording_started_at`; before it, delta/footprint are null).

Backfill only targets the **hot** part of the window (older history is the cold tier's job),
which also bounds how far back one request can make the exchange page (security notes).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import BAR_WIDTH_US, Range

#: `meta.sources` values (OpenAPI `DataMeta.sources` enum).
SOURCE_HOT: Final = "questdb"
SOURCE_COLD: Final = "parquet"
SOURCE_EXCHANGE: Final = "exchange_rest"
SOURCE_TAPE: Final = "tape"
#: Row `source` tags that mean "this bar came from the exchange REST kline endpoint".
_EXCHANGE_ROW_SOURCES: Final = frozenset({"rest", "kline"})


class KlineRowLike(Protocol):
    @property
    def ts_us(self) -> int: ...
    @property
    def open(self) -> str: ...
    @property
    def high(self) -> str: ...
    @property
    def low(self) -> str: ...
    @property
    def close(self) -> str: ...
    @property
    def volume(self) -> str: ...
    @property
    def turnover(self) -> str: ...
    @property
    def confirmed(self) -> bool: ...
    @property
    def source(self) -> str: ...


class HotKlineReader(Protocol):
    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto", limit: int | None = None
    ) -> Sequence[KlineRowLike]: ...


#: `symbol -> µs of the oldest recorded trade` (where tick-accurate data begins); `None` = no
#: tape. The composition root reads it from the hot `trades` table.
RecordingStart = Callable[[str], Awaitable[int | None]]

ColdKlineReader = Callable[[str, str, Range], Awaitable[Sequence[KlineRowLike]]]
#: `(symbol, interval, window, limit) -> tape-built time bars`, ascending; rows report
#: `source == "tape"`. Composed from `bars.reader` at the composition root (ingestion never
#: imports bars, C-3.1).
TapeBarReader = Callable[[str, str, Range, int | None], Awaitable[Sequence[KlineRowLike]]]


@dataclass(frozen=True, slots=True)
class KlineRead:
    rows: list[KlineRowLike]
    sources: list[str]
    recording_started_at_us: int | None
    holes: list[Range]
    backfilling: bool


class KlineReadService:
    """Tier-merging, non-blocking kline reads for `GET /market/klines`."""

    def __init__(
        self,
        hot: HotKlineReader,
        *,
        backfill: KlineBackfillService | None = None,
        cold: ColdKlineReader | None = None,
        hot_boundary_us: Callable[[], int] = lambda: 0,
        recording_started_at_us: RecordingStart | None = None,
        tape: TapeBarReader | None = None,
        max_backfill_bars: int = 400_000,
        max_tracked_keys: int = 512,
    ) -> None:
        self._hot = hot
        self._backfill = backfill
        self._cold = cold
        self._boundary = hot_boundary_us
        self._recording_started = recording_started_at_us
        self._tape = tape
        self._max_backfill_bars = max_backfill_bars
        self._primed: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._max_primed = max(1, max_tracked_keys)

    def attach_tape(self, tape: TapeBarReader) -> None:
        """Compose tier (1) once a `bars_time` reader exists (wired after the bars runtime)."""
        self._tape = tape

    async def read(
        self, symbol: str, interval: str, rng: Range, limit: int | None = None
    ) -> KlineRead:
        """`symbol` must already be validated against the instrument catalogue by the caller
        (the route returns 422 first): this method may start an exchange backfill for it."""
        boundary = self._boundary()
        sources: list[str] = []
        rows: list[KlineRowLike] = []
        cold_ids: set[int] = set()
        hot_ids: set[int] = set()
        if self._cold is not None and rng.start_us < boundary:
            cold_rows = await self._cold(
                symbol, interval, Range(rng.start_us, min(rng.end_us, boundary))
            )
            rows.extend(cold_rows)
            cold_ids = {id(r) for r in cold_rows}
        holes: list[Range] = []
        backfilling = False
        if rng.end_us > boundary:
            hot_rng = Range(max(rng.start_us, boundary), rng.end_us)
            hot_rows = await self._hot.read_klines(symbol, interval, hot_rng, limit=limit)
            rows.extend(hot_rows)
            hot_ids = {id(r) for r in hot_rows}
            holes, backfilling = await self._schedule_backfill(symbol, interval, hot_rng)
        tape_ids: set[int] = set()
        if self._tape is not None:
            tape_rows = await self._tape(symbol, interval, rng, limit)
            if tape_rows:
                taped = {r.ts_us for r in tape_rows}
                rows = [r for r in rows if r.ts_us not in taped]  # tape wins on overlap
                rows.extend(tape_rows)
                tape_ids = {id(r) for r in tape_rows}
        # A4: claim the exchange tier only once exchange-sourced rows are actually merged into
        # this response; a running job alone is reported via `backfilling`, not `sources`.
        rows.sort(key=lambda r: r.ts_us)
        if limit is not None:
            rows = rows[-limit:] if limit else []  # newest `limit` across both tiers
        # `sources` describes the rows actually returned (a tier whose rows were all trimmed
        # away is not claimed).
        if any(id(r) in cold_ids for r in rows):
            sources.append(SOURCE_COLD)
        if any(id(r) in hot_ids for r in rows):
            sources.append(SOURCE_HOT)
        if any(id(r) in tape_ids for r in rows):
            sources.append(SOURCE_TAPE)
        if any(r.source in _EXCHANGE_ROW_SOURCES for r in rows):
            sources.append(SOURCE_EXCHANGE)
        started = await self._recording_started(symbol) if self._recording_started else None
        return KlineRead(rows, sources, started, holes, backfilling)

    async def _schedule_backfill(
        self, symbol: str, interval: str, hot_rng: Range
    ) -> tuple[list[Range], bool]:
        width = BAR_WIDTH_US.get(interval)  # `M`: no fixed width, served from the store only
        if self._backfill is None or width is None:
            return [], False
        # Bound how far back one request can page (SR-E12-08, security notes).
        start = max(hot_rng.start_us, hot_rng.end_us - self._max_backfill_bars * width)
        target = Range(start, hot_rng.end_us)
        key = (symbol, interval)
        if key not in self._primed:
            await self._backfill.load_coverage_from_cache(symbol, interval, target)
            self._primed[key] = None
            while len(self._primed) > self._max_primed:  # LRU; re-priming is only a cache read
                self._primed.popitem(last=False)
        self._primed.move_to_end(key)
        index = self._backfill.coverage(symbol, interval)
        holes = index.holes(target) if index is not None else [target]
        if holes:
            self._backfill.start_backfill(symbol, interval, target)
        return holes, self._backfill.job_running(symbol, interval)


__all__ = [
    "SOURCE_COLD",
    "SOURCE_EXCHANGE",
    "SOURCE_HOT",
    "SOURCE_TAPE",
    "ColdKlineReader",
    "HotKlineReader",
    "KlineRead",
    "KlineReadService",
    "RecordingStart",
    "TapeBarReader",
]
