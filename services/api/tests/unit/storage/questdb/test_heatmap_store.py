"""E21-T02 (#605; 21 §4.12, 24 §6.5): `QuestDbHeatmapStore` writes one `heatmap_cells` row per
populated level of a native column, the column's `estimated`, `samples` and off-window totals on
each row, nothing for an empty column, and refuses a size that is negative or not finite before
anything is buffered. The rows go through the hot-tier ILP schema (`heatmap_cells` tags `symbol`,
`estimated` a boolean field). No QuestDB: a fake writer, and the line the real writer would send."""

from __future__ import annotations

import pytest

from candleviewer.storage.questdb.heatmap_store import TABLE, HeatmapCellError, QuestDbHeatmapStore
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS, HEATMAP_CELLS_SCHEMA

TS_US = 1_700_000_000_000_000


class Writer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]], str]] = []
        self.stopped = False

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self.calls.append((table, rows, ts_us_key))

    async def stop(self) -> None:
        self.stopped = True


async def _write(store: QuestDbHeatmapStore, cells: list[tuple[float, float, float]]) -> None:
    await store.write_column("BTCUSDT", TS_US, cells, estimated=True, samples=1,
                             off_window_bid_qty=2.5, off_window_ask_qty=0.0)  # fmt: skip


async def test_the_store_writes_populated_levels_with_the_column_fields() -> None:
    writer = Writer()
    store = QuestDbHeatmapStore(writer)
    await _write(store, [(63118.0, 1.5, 0.0), (63118.1, 0.0, 0.0), (63118.2, 0.0, 2.0)])
    [(table, rows, key)] = writer.calls
    assert (table, key) == (TABLE, "ts") == ("heatmap_cells", "ts")
    assert [r["price"] for r in rows] == [63118.0, 63118.2]  # the empty level is no row
    assert rows[0] == {
        "ts": TS_US, "symbol": "BTCUSDT", "price": 63118.0, "bid_size": 1.5, "ask_size": 0.0,
        "estimated": True, "samples": 1, "off_window_bid_qty": 2.5, "off_window_ask_qty": 0.0,
    }  # fmt: skip
    await store.close()
    assert writer.stopped


async def test_an_empty_column_is_never_written() -> None:
    writer = Writer()
    await _write(QuestDbHeatmapStore(writer), [(63118.0, 0.0, 0.0)])
    await _write(QuestDbHeatmapStore(writer), [])
    assert writer.calls == []


@pytest.mark.parametrize(
    "cells",
    [
        [(63118.0, float("nan"), 1.0)],
        [(63118.0, 1.0, -0.5)],
        [(float("inf"), 1.0, 1.0)],
    ],
    ids=["nan", "negative", "price"],
)
async def test_a_size_that_is_negative_or_not_finite_writes_nothing(
    cells: list[tuple[float, float, float]],
) -> None:
    writer = Writer()
    with pytest.raises(HeatmapCellError):
        await _write(QuestDbHeatmapStore(writer), [(63117.9, 1.0, 1.0), *cells])
    assert writer.calls == []


async def test_a_writer_without_stop_closes_quietly() -> None:
    class Bare:
        async def write_rows(self, table: str, rows: list[dict[str, object]], key: str) -> None:
            return None

    await QuestDbHeatmapStore(Bare()).close()


def test_heatmap_cells_is_a_registered_ilp_table_with_its_column_types() -> None:
    assert ALL_SCHEMAS["heatmap_cells"] is HEATMAP_CELLS_SCHEMA
    row: dict[str, object] = {"symbol": "BTCUSDT", "price": 63118.0, "bid_size": 1.5,
                              "ask_size": 0.0, "estimated": False, "samples": 3,
                              "off_window_bid_qty": 0.0, "off_window_ask_qty": 2.0}  # fmt: skip
    line = serialize_ilp_line(HEATMAP_CELLS_SCHEMA, row, TS_US)
    assert line == (
        "heatmap_cells,symbol=BTCUSDT price=63118.0,bid_size=1.5,ask_size=0.0,estimated=false,"
        f"samples=3i,off_window_bid_qty=0.0,off_window_ask_qty=2.0 {TS_US * 1000}"
    )


def test_the_exporter_widens_heatmap_cells_by_exactly_the_0007_columns() -> None:
    """21 §5.2: the cold export registers the four 0007 columns (C-5.8), typed, and nothing else."""
    import pyarrow as pa

    from candleviewer.storage.cold.exporter import ALLOWED_ADDITIONS
    from candleviewer.storage.models import StreamKind

    assert dict(ALLOWED_ADDITIONS[StreamKind.HEATMAP_CELLS.value]) == {
        "estimated": pa.bool_(),
        "samples": pa.int32(),
        "off_window_bid_qty": pa.float64(),
        "off_window_ask_qty": pa.float64(),
    }
