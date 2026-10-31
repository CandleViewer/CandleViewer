"""E21-T03 (#606) `heatmap_wiring.StoredHeatmapReader`: the tiers behind `GET /market/heatmap`.

Fake tiers stand in for QuestDB and the Parquet cold tier (their own reads are covered in
`tests/unit/storage`); the rows are generated heatmap cells, not exchange payloads."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from candleviewer import heatmap_wiring
from candleviewer.heatmap_wiring import StoredHeatmapReader, build_heatmap_wiring
from candleviewer.orderflow.heatmap_history import CELL_SPAN_ROWS, CellSpan, HeatmapReadLimit
from candleviewer.settings import Settings
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    HeatmapCell,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
)

SYM = "BTCUSDT"
T0 = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC
S = 1_000_000


def _cell(ts: int, price: float, bid: float = 1.0) -> HeatmapCell:
    return (ts, price, bid, 0.0, 1, False)


def _event(ts: int, payload: Any, stream: StreamKind) -> RecordedEvent:
    return RecordedEvent(ts, 0, SYM, stream, (0,), payload)


class FakeTier:
    def __init__(
        self,
        cells: Sequence[HeatmapCell] = (),
        *,
        earliest: dict[StreamKind, int] | None = None,
        snapshot: RecordedEvent | None = None,
        deltas: Sequence[RecordedEvent] = (),
        archived: Sequence[TimeRange] = (),
    ) -> None:
        self.rows, self.first = sorted(cells, key=lambda c: c[0]), earliest or {}
        self.snapshot, self.deltas, self.covered = snapshot, list(deltas), list(archived)
        self.limits: list[int] = []
        self.reads: list[TimeRange] = []

    async def heatmap_cells(self, symbol: str, rng: TimeRange, *, limit: int) -> list[HeatmapCell]:
        self.limits.append(limit)
        return [c for c in self.rows if rng.start_us <= c[0] < rng.end_us][:limit]

    async def earliest(self, symbol: str, stream: StreamKind) -> int | None:
        return self.first.get(stream)

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        return self.snapshot

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        self.reads.append(rng)
        return self.deltas[:limit]

    async def archived(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[TimeRange]:
        return [
            TimeRange(start_us=max(c.start_us, rng.start_us), end_us=min(c.end_us, rng.end_us))
            for c in self.covered
            if c.start_us < rng.end_us and rng.start_us < c.end_us
        ]


async def _spans(reader: StoredHeatmapReader, lo: int, hi: int) -> list[CellSpan]:
    return [span async for span in reader.cells(SYM, lo, hi)]


async def test_cells_page_by_the_bound_and_never_split_a_native_column() -> None:
    """C-2.18 (review r1): every read asks for at most a page; a full page hands its newest
    column to the next, so spans are contiguous, bounded and each column is read whole."""
    rows = [_cell(T0 + s * S, 100.0 + p) for s in range(3) for p in range(3)]
    hot = FakeTier(rows)
    spans = await _spans(StoredHeatmapReader(hot, FakeTier(), page_rows=4), T0, T0 + 10 * S)
    assert hot.limits and set(hot.limits) == {4}
    assert all(len(s.rows) <= 4 for s in spans)
    assert [(s.lo_us, s.hi_us) for s in spans] == [
        (T0, T0 + S), (T0 + S, T0 + 2 * S), (T0 + 2 * S, T0 + 10 * S)
    ]  # fmt: skip
    assert [len({r.ts_us for r in s.rows}) for s in spans] == [1, 1, 1]


async def test_the_default_page_is_the_engines_bound() -> None:
    hot = FakeTier([_cell(T0, 1.0)])
    await _spans(StoredHeatmapReader(hot, FakeTier()), T0, T0 + S)
    assert hot.limits == [CELL_SPAN_ROWS]
    with pytest.raises(ValueError, match="page_rows"):
        StoredHeatmapReader(hot, FakeTier(), page_rows=CELL_SPAN_ROWS + 1)


async def test_a_column_wider_than_a_page_is_refused() -> None:
    hot = FakeTier([_cell(T0, 100.0 + p) for p in range(5)])
    with pytest.raises(HeatmapReadLimit):
        await _spans(StoredHeatmapReader(hot, FakeTier(), page_rows=4), T0, T0 + S)


async def test_archived_spans_read_cold_and_the_rest_hot_oldest_first() -> None:
    mid = T0 + 5 * S
    cold = FakeTier([_cell(T0, 1.0)], archived=[TimeRange(start_us=T0 - S, end_us=mid)])
    hot = FakeTier([_cell(mid, 2.0)])
    spans = await _spans(StoredHeatmapReader(hot, cold), T0, T0 + 10 * S)
    assert [(s.tier, s.lo_us, s.hi_us) for s in spans] == [
        ("cold", T0, mid), ("hot", mid, T0 + 10 * S)
    ]  # fmt: skip
    assert [r.price for s in spans for r in s.rows] == [1.0, 2.0]


async def test_a_row_read_twice_keeps_the_copy_read_last() -> None:
    cold = FakeTier(
        [_cell(T0, 1.0, bid=2.0), _cell(T0, 1.0, bid=3.0)],
        archived=[TimeRange(start_us=T0, end_us=T0 + S)],
    )
    (span,) = await _spans(StoredHeatmapReader(FakeTier(), cold), T0, T0 + S)
    assert [(r.price, r.bid_size) for r in span.rows] == [(1.0, 3.0)]


async def test_first_available_is_the_oldest_of_either_tier() -> None:
    hot = FakeTier(earliest={StreamKind.HEATMAP_CELLS: T0 + 9 * S})
    cold = FakeTier(earliest={StreamKind.ORDERBOOK_SNAPSHOT: T0})
    assert await StoredHeatmapReader(hot, cold).first_available(SYM) == T0
    assert await StoredHeatmapReader(FakeTier(), FakeTier()).first_available(SYM) is None


async def test_the_anchor_falls_back_to_the_cold_tier_and_is_unverified() -> None:
    level = (Decimal("100.1"), Decimal("2"))
    snap = RecordedBookSnapshot(200, 7, None, (level,), ())
    cold = FakeTier(snapshot=_event(T0, snap, StreamKind.ORDERBOOK_SNAPSHOT))
    anchor = await StoredHeatmapReader(FakeTier(), cold).book_anchor(
        SYM, 200, T0, not_before_us=T0 - 60 * S
    )
    assert anchor is not None
    assert (anchor.ts_us, anchor.update_id, anchor.bids, anchor.checksum) == (T0, 7, (level,), None)
    assert await StoredHeatmapReader(FakeTier(), FakeTier()).book_anchor(
        SYM, 200, T0, not_before_us=T0
    ) is None  # fmt: skip


async def test_book_changes_read_cold_only_when_its_manifests_cover_the_range() -> None:
    delta = RecordedBookDelta(200, "ask", Decimal("100.2"), Decimal("0"), 8, None)
    rows = [_event(T0 + S, delta, StreamKind.ORDERBOOK_DELTA)]
    rng = TimeRange(start_us=T0, end_us=T0 + 60 * S)
    cold, hot = FakeTier(deltas=rows, archived=[rng]), FakeTier()
    (change,) = await StoredHeatmapReader(hot, cold).book_changes(SYM, 200, T0, T0 + 60 * S)
    assert (change.side, change.price, change.size, change.update_id) == (
        "ask", Decimal("100.2"), Decimal("0"), 8
    )  # fmt: skip
    assert cold.reads == [rng] and hot.reads == []
    partial = FakeTier(archived=[TimeRange(start_us=T0, end_us=T0 + S)])
    await StoredHeatmapReader(hot, partial).book_changes(SYM, 200, T0, T0 + 60 * S)
    assert hot.reads == [rng] and partial.reads == []


async def test_a_minute_past_the_delta_bound_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heatmap_wiring, "BOOK_CHANGE_ROWS", 1)
    delta = RecordedBookDelta(200, "bid", Decimal("1"), Decimal("1"), 1, None)
    hot = FakeTier(deltas=[_event(T0, delta, StreamKind.ORDERBOOK_DELTA)] * 2)
    with pytest.raises(HeatmapReadLimit):
        await StoredHeatmapReader(hot, FakeTier()).book_changes(SYM, 200, T0, T0 + S)


async def test_wired_only_on_the_real_backend(tmp_path: Path) -> None:
    fake = Settings(_env_file=None, storage_backend="fake")  # type: ignore[call-arg]  # reason: pydantic-settings kwarg
    assert build_heatmap_wiring(fake) is None
    real = Settings(  # type: ignore[call-arg]  # reason: pydantic-settings kwarg
        _env_file=None,
        storage_backend="real",
        questdb_pg="questdb:8812",
        parquet_root=str(tmp_path / "parquet"),
    )
    wiring = build_heatmap_wiring(real)
    assert wiring is not None and isinstance(wiring.cold, ParquetRecordedReader)
    await wiring.aclose()  # never connected: closing is a no-op on the wire
