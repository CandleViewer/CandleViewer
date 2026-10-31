"""Composition of the recorded heatmap read behind `GET /market/heatmap` (E21-T03, #606).

`StoredHeatmapReader` is the `orderflow.heatmap_history.HeatmapHistoryReader` over the two tiers
(`orderflow` may not import `storage`, CONSTITUTION §3, so the adapter lives here):

- **Cells.** The span the Parquet manifests cover (`archived`, what roll-off writes before it
  may drop a hot day, 21 §5.3) is read from the cold tier, the rest from QuestDB, oldest first.
  Each tier is read a page at a time, `CELL_SPAN_ROWS` rows at most (C-2.18): a full page drops
  its newest native column, which opens the next page, so a column is never split across two
  and the read always advances. A page holds one row per `(ts, price)`, the copy read last
  winning (a re-export can leave a row in two parts).
- **Book.** The anchor is the newest recorded snapshot in the hot tier, else the cold one;
  stored snapshots carry no checksum today, so every rebuilt column is `estimated` (BQ-4). The
  deltas come from the cold tier when its manifests cover the whole range, else from QuestDB,
  at most `BOOK_CHANGE_ROWS` (more raise `HeatmapReadLimit`).
- **Range.** `first_available` is the oldest stored heatmap cell or book snapshot of either
  tier (BQ-3; the recorder forces a snapshot a minute, so the first delta is no older).

Only on the `real` storage backend: one lazily opened QuestDB wire and one cold reader, both
released by `HeatmapWiring.aclose()` when the app stops.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from candleviewer.orderflow.heatmap_history import (
    BOOK_CHANGE_ROWS,
    CELL_SPAN_ROWS,
    BookAnchor,
    BookChange,
    CellRow,
    CellSpan,
    HeatmapReadLimit,
)
from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Settings
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.recorded_reader import QuestDbRecordedReader
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.recorded import (
    HeatmapCell,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
)

type Tier = Literal["hot", "cold"]


class HeatmapTier(Protocol):
    """What one tier's reader serves (`QuestDbRecordedReader`, `ParquetRecordedReader`)."""

    async def heatmap_cells(
        self, symbol: str, rng: TimeRange, *, limit: int
    ) -> list[HeatmapCell]: ...

    async def earliest(self, symbol: str, stream: StreamKind) -> int | None: ...

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None: ...

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]: ...


class ColdHeatmapTier(HeatmapTier, Protocol):
    async def archived(
        self, symbol: str, stream: StreamKind, rng: TimeRange
    ) -> list[TimeRange]: ...


def _split(lo_us: int, hi_us: int, cold: Sequence[TimeRange]) -> list[tuple[int, int, Tier]]:
    """`[lo_us, hi_us)` as consecutive spans, `cold` where the manifests cover it."""
    out: list[tuple[int, int, Tier]] = []
    at = lo_us
    for span in sorted(cold, key=lambda r: r.start_us):
        a, b = max(span.start_us, at), min(span.end_us, hi_us)
        if b <= a:
            continue
        if a > at:
            out.append((at, a, "hot"))
        out.append((a, b, "cold"))
        at = b
    if at < hi_us:
        out.append((at, hi_us, "hot"))
    return out


def _rows(cells: Sequence[HeatmapCell]) -> list[CellRow]:
    """Worker thread: one `CellRow` per `(ts, price)`, the copy read last winning."""
    last = {(c[0], c[1]): c for c in cells}
    return [CellRow(*c) for c in last.values()]


def _anchor(event: RecordedEvent | None) -> BookAnchor | None:
    if event is None or not isinstance(event.payload, RecordedBookSnapshot):
        return None
    snap = event.payload
    return BookAnchor(event.ts_us, snap.update_id, snap.bids, snap.asks, None)


def _changes(events: Sequence[RecordedEvent]) -> list[BookChange]:
    """Worker thread: recorded delta rows (`side` is `bid` or `ask`, 21 §4.2) as changes."""
    out: list[BookChange] = []
    for e in events:
        d = e.payload
        if isinstance(d, RecordedBookDelta):
            out.append(BookChange(e.ts_us, d.update_id, "bid" if d.side == "bid" else "ask",
                                  d.price, d.size))  # fmt: skip
    return out


class StoredHeatmapReader:
    """`HeatmapHistoryReader` over QuestDB (`hot`) and the Parquet cold tier (`cold`)."""

    def __init__(
        self, hot: HeatmapTier, cold: ColdHeatmapTier, *, page_rows: int = CELL_SPAN_ROWS
    ) -> None:
        if not 1 <= page_rows <= CELL_SPAN_ROWS:
            raise ValueError(f"page_rows must be in 1..{CELL_SPAN_ROWS}")
        self._hot, self._cold, self._page = hot, cold, page_rows

    async def first_available(self, symbol: str) -> int | None:
        found: list[int | None] = []
        for tier in (self._hot, self._cold):
            for stream in (StreamKind.HEATMAP_CELLS, StreamKind.ORDERBOOK_SNAPSHOT):
                found.append(await tier.earliest(symbol, stream))
        known = [v for v in found if v is not None]
        return min(known) if known else None

    async def cells(self, symbol: str, lo_us: int, hi_us: int) -> AsyncIterator[CellSpan]:
        rng = TimeRange(start_us=lo_us, end_us=hi_us)
        archived = await self._cold.archived(symbol, StreamKind.HEATMAP_CELLS, rng)
        for a, b, tier in _split(lo_us, hi_us, archived):
            reader: HeatmapTier = self._cold if tier == "cold" else self._hot
            at = a
            while at < b:
                got = await reader.heatmap_cells(
                    symbol, TimeRange(start_us=at, end_us=b), limit=self._page
                )
                end = b
                if len(got) >= self._page:  # full: its newest column opens the next page
                    end = got[-1][0]
                    got = [c for c in got if c[0] < end]
                    if not got:
                        raise HeatmapReadLimit("one native column holds more rows than a page")
                yield CellSpan(at, end, tier, await asyncio.to_thread(_rows, got))
                at = end

    async def book_anchor(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> BookAnchor | None:
        found = await self._hot.snapshot_at(symbol, depth, at_us, not_before_us=not_before_us)
        if found is None:
            found = await self._cold.snapshot_at(symbol, depth, at_us, not_before_us=not_before_us)
        return _anchor(found)

    async def book_changes(
        self, symbol: str, depth: int, lo_us: int, hi_us: int
    ) -> Sequence[BookChange]:
        rng = TimeRange(start_us=lo_us, end_us=hi_us)
        covered = await self._cold.archived(symbol, StreamKind.ORDERBOOK_DELTA, rng)
        whole = len(covered) == 1 and covered[0] == rng
        reader: HeatmapTier = self._cold if whole else self._hot
        events = await reader.read(
            symbol, StreamKind.ORDERBOOK_DELTA, rng, depth=depth, limit=BOOK_CHANGE_ROWS + 1
        )
        if len(events) > BOOK_CHANGE_ROWS:
            raise HeatmapReadLimit("a reconstructed minute holds more deltas than one may")
        return await asyncio.to_thread(_changes, events)


@dataclass(frozen=True, slots=True)
class HeatmapWiring:
    """The reader and what it holds open, released by `aclose()`."""

    reader: StoredHeatmapReader
    pg: LazyPgWire
    cold: ParquetRecordedReader

    async def aclose(self) -> None:
        self.cold.shutdown()
        await self.pg.close()


def build_heatmap_wiring(settings: Settings) -> HeatmapWiring | None:
    """The real tiers, or `None` off the `real` storage backend (the route then answers 503).
    Connects lazily: no I/O here. The wire is labelled `storage` (the closed `WireName` set:
    the storage module's market-data reads) and is its own connection."""
    if settings.storage_backend != "real":
        return None
    host, _, port = settings.questdb_pg.partition(":")
    pg = LazyPgWire(
        host,
        int(port or QUESTDB_PG_DEFAULT_PORT),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
        name="storage",
    )
    cold = ParquetRecordedReader(DatasetRegistry(settings.parquet_root))
    reader = StoredHeatmapReader(QuestDbRecordedReader(pg), cold)
    return HeatmapWiring(reader=reader, pg=pg, cold=cold)


__all__ = ["HeatmapWiring", "StoredHeatmapReader", "build_heatmap_wiring"]
