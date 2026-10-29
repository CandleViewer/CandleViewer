"""QuestDB `heatmap_cells` store (E21-T02, #605; `21-database-schema.md` §4.12, `24` §6.5).

One row per populated level of the heatmap engine's native column (100 ms, one tick a row). The
column's `estimated`, `samples` and off-window totals repeat on each of its rows. A column with no
populated level is never written (an empty bucket reads `samples = 0`), and a size that is
negative or not finite is refused before anything is buffered. Dedup key `(ts, symbol, price)`
(the table DDL) makes a re-write idempotent. The engine computes in `float` (C3) and `price` is
the `DOUBLE` of the level's `Decimal` price (24 §6.5).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final, Protocol

TABLE: Final = "heatmap_cells"


class RowWriter(Protocol):
    """`IlpWriter.write_rows`, or the bars sink that wraps one (`QuestDbRowSink`)."""

    async def write_rows(
        self, table: str, rows: list[dict[str, object]], ts_us_key: str
    ) -> None: ...


class HeatmapCellError(ValueError):
    """A size or total that is negative or not finite: nothing of the column is written."""


def _checked(value: float) -> float:
    if not math.isfinite(value) or value < 0:
        raise HeatmapCellError("a heatmap size is negative or not finite")
    return value


class QuestDbHeatmapStore:
    """`HeatmapStore` over the hot-tier ILP writer; `close` stops a writer that has `stop`."""

    def __init__(self, writer: RowWriter) -> None:
        self._writer = writer

    async def write_column(
        self,
        symbol: str,
        ts_us: int,
        cells: Sequence[tuple[float, float, float]],
        *,
        estimated: bool,
        samples: int,
        off_window_bid_qty: float,
        off_window_ask_qty: float,
    ) -> None:
        off_bid, off_ask = _checked(off_window_bid_qty), _checked(off_window_ask_qty)
        rows: list[dict[str, object]] = []
        for price, bid, ask in cells:
            if not math.isfinite(price):
                raise HeatmapCellError("a heatmap price is not finite")
            bid, ask = _checked(bid), _checked(ask)
            if not (bid or ask):
                continue  # not a populated level
            rows.append(
                {
                    "ts": ts_us,
                    "symbol": symbol,
                    "price": price,
                    "bid_size": bid,
                    "ask_size": ask,
                    "estimated": estimated,
                    "samples": samples,
                    "off_window_bid_qty": off_bid,
                    "off_window_ask_qty": off_ask,
                }
            )
        if rows:
            await self._writer.write_rows(TABLE, rows, "ts")

    async def close(self) -> None:
        stop = getattr(self._writer, "stop", None)
        if stop is not None:
            await stop()


__all__ = ["TABLE", "HeatmapCellError", "QuestDbHeatmapStore", "RowWriter"]
