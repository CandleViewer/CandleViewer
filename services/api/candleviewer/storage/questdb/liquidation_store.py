"""QuestDB `liquidations` store (E24-T03 #667, `21-database-schema.md` §4.6).

Writes go through the hot tier's ILP writer with `stream='all'`; the dedup key `(ts, symbol, side,
price, size, batch_index)` makes a replayed push idempotent and keeps two identical prints of one
push apart. Reads are parameterised (SR-047): one symbol's prints in the key's order, optionally
one side, plus the first stored `ts` (coverage).

Precision: `price`, `size` and `notional` are `DOUBLE` columns (`0001_core_tables.sql`); a value
is read back as the `Decimal` of its shortest repr. The in-memory store keeps the exact `Decimal`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from candleviewer.domain.liquidations import STREAM_ALL, LiqPrint
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import (
    QuestDbReader,
    build_liquidations_first,
    build_read_liquidations,
)
from candleviewer.storage.sql_identifiers import checked_identifier


class _Range(Protocol):
    @property
    def start_us(self) -> int: ...
    @property
    def end_us(self) -> int: ...


def _row(p: LiqPrint) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": p.ts_us,
        "symbol": p.symbol,
        "side": p.side,
        "price": float(p.price),
        "size": float(p.size),
        "notional": float(p.notional),
        "stream": STREAM_ALL,
        "batch_index": p.batch_index,
    }
    if p.recv_ts_us is not None:
        row["recv_ts"] = p.recv_ts_us
    return row


def _dec(value: object) -> Decimal:
    return Decimal(repr(float(str(value))))


class QuestDbLiquidationStore:
    def __init__(self, writer: IlpWriter, reader: QuestDbReader) -> None:
        self._writer = writer
        self._reader = reader

    async def write_prints(self, rows: Sequence[LiqPrint]) -> None:
        if rows:
            await self._writer.write_rows("liquidations", [_row(p) for p in rows], "ts")

    async def read_prints(
        self, symbol: str, rng: _Range, side: str | None, limit: int
    ) -> list[LiqPrint]:
        checked_identifier(symbol)
        window = TimeRange(start_us=rng.start_us, end_us=rng.end_us)
        rows = await self._reader.run(build_read_liquidations(symbol, window, side, limit))
        return [
            LiqPrint(
                ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                side="sell" if r["side"] == "sell" else "buy",
                price=_dec(r["price"]),
                size=_dec(r["size"]),
                notional=_dec(r["notional"]),
                batch_index=0 if r["batch_index"] is None else int(str(r["batch_index"])),
            )
            for r in rows
        ]

    async def first_ts(self, symbol: str) -> int | None:
        checked_identifier(symbol)
        rows = await self._reader.run(build_liquidations_first(symbol))
        if not rows or rows[0]["lo"] is None:
            return None
        return ts_us_from_row(rows[0]["lo"])


class InMemoryLiquidationStore:
    """Fake-backend / test store with the same dedup key, bounded: past `max_rows` the
    oldest-written row is evicted (the dev feed never grows it without end)."""

    def __init__(self, max_rows: int = 200_000) -> None:
        self._rows: dict[tuple[object, ...], LiqPrint] = {}
        self._max = max_rows

    async def write_prints(self, rows: Sequence[LiqPrint]) -> None:
        for p in rows:
            self._rows[(p.symbol, *p.key())] = p
        while len(self._rows) > self._max:
            del self._rows[next(iter(self._rows))]

    async def read_prints(
        self, symbol: str, rng: _Range, side: str | None, limit: int
    ) -> list[LiqPrint]:
        hits = sorted(
            (
                p
                for p in self._rows.values()
                if p.symbol == symbol
                and rng.start_us <= p.ts_us < rng.end_us
                and (side is None or p.side == side)
            ),
            key=LiqPrint.key,
        )
        return hits[:limit]

    async def first_ts(self, symbol: str) -> int | None:
        return min((p.ts_us for p in self._rows.values() if p.symbol == symbol), default=None)

    def __len__(self) -> int:
        return len(self._rows)


__all__ = ["InMemoryLiquidationStore", "QuestDbLiquidationStore"]
