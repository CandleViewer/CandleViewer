"""A generated two-hour corpus, not a recording, shared by the cold-tier and straddle tests.

Rows are shaped as QuestDB stores them (21 Sec.4: DOUBLE prices, integer microsecond `ts`), so
the same rows can be exported to Parquet, written to QuestDB, or mapped with `event_from_row`,
and every path must replay to the same committed digest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pyarrow as pa

from candleviewer.storage.models import StreamKind, TimeRange

#: 2026-10-01 00:00 UTC: the two generated hours start here.
H0 = 1_790_812_800_000_000
HOUR = 3_600_000_000
SYMBOL = "BTCUSDT"


def generated_rows() -> dict[StreamKind, list[dict[str, object]]]:
    """Trades every 20 s, two-level book deltas every 30 s, sharing instants on the minute."""
    trades: list[dict[str, object]] = []
    deltas: list[dict[str, object]] = []
    for i in range(360):  # 2 h of trades, every 20 s
        trades.append(
            {
                "ts": H0 + i * 20_000_000,
                "symbol": SYMBOL,
                "side": "buy" if i % 3 else "sell",
                "price": 65_000.0 + (i % 7) * 0.5,
                "size": 0.001 * (i % 5 + 1),
                "trade_id": f"t{i:04}",
                "seq": 10 * i + 5,
                "is_block": False,
            }
        )
    for i in range(240):  # 2 h of deltas, every 30 s, two levels each
        for side, price in (("bid", 64_999.5 - i % 3), ("ask", 65_000.5 + i % 4)):
            deltas.append(
                {
                    "ts": H0 + i * 30_000_000,
                    "symbol": SYMBOL,
                    "depth": 200,
                    "side": side,
                    "price": price,
                    "size": 0.0 if i % 11 == 0 else 1.25,
                    "update_id": 1_000 + i,
                    "cross_seq": 10 * (i * 3 // 2) + 7,
                }
            )
    return {StreamKind.TRADES: trades, StreamKind.ORDERBOOK_DELTA: deltas}


def rows_in(rows: list[dict[str, object]], rng: TimeRange) -> list[dict[str, object]]:
    return [r for r in rows if rng.start_us <= int(str(r["ts"])) < rng.end_us]


class MemHotSource:
    """The exporter's `HotTierSource` over in-memory rows (what roll-off reads from QuestDB)."""

    def __init__(self, rows: dict[StreamKind, list[dict[str, object]]]) -> None:
        self.rows = rows

    async def iter_partition(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, batch_rows: int
    ) -> AsyncIterator[pa.Table]:
        picked = rows_in(self.rows[stream], rng)
        for start in range(0, len(picked), batch_rows):
            yield pa.Table.from_pylist(picked[start : start + batch_rows])

    async def count_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> int:
        return len(rows_in(self.rows[stream], rng))
