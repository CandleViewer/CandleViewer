"""QuestDB `open_interest` store (E24-T01 #665, `21-database-schema.md` §4.7).

Writes go through the hot tier's ILP writer; the dedup key `(ts, symbol, interval, source)`
makes a re-run backfill and an at-least-once ticker tap idempotent. Reads are one
`(symbol, interval, source)` series per call, parameterised (SR-047), plus its coverage.

Precision: `oi` and `oi_value` are QuestDB `DOUBLE` columns (`0001_core_tables.sql`), so a
value is written as a `float` and read back as the `Decimal` of its shortest repr. A value
with more than ~15 significant digits loses its tail. These are open-interest quantities,
never order prices or sizes, so no C-2.x money rule applies; the in-memory store keeps the
exact `Decimal`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from candleviewer.domain.open_interest import OiPoint
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import QuestDbReader, build_oi_coverage, build_read_oi
from candleviewer.storage.sql_identifiers import checked_identifier


class _Range(Protocol):
    """A `[start_us, end_us)` window: `storage.models.TimeRange` or the service's own."""

    @property
    def start_us(self) -> int: ...
    @property
    def end_us(self) -> int: ...


def _row(point: OiPoint) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": point.ts_us,
        "symbol": point.symbol,
        "oi": float(point.open_interest),
        "interval": point.interval,
        "source": point.source,
    }
    if point.open_interest_value is not None:  # a REST row has none: the column stays NULL
        row["oi_value"] = float(point.open_interest_value)
    return row


def _dec(value: object) -> Decimal | None:
    return None if value is None else Decimal(repr(float(str(value))))


class QuestDbOiStore:
    def __init__(self, writer: IlpWriter, reader: QuestDbReader) -> None:
        self._writer = writer
        self._reader = reader

    async def write_points(self, rows: Sequence[OiPoint]) -> None:
        if rows:
            await self._writer.write_rows("open_interest", [_row(p) for p in rows], "ts")

    async def read_points(
        self, symbol: str, interval: str, source: str, rng: _Range, limit: int
    ) -> list[OiPoint]:
        checked_identifier(symbol)
        window = TimeRange(start_us=rng.start_us, end_us=rng.end_us)
        rows = await self._reader.run(build_read_oi(symbol, interval, source, window, limit))
        out: list[OiPoint] = []
        for r in rows:
            oi = _dec(r["oi"])
            if oi is None:  # never written without `oi`; a NULL is skipped, never read as 0
                continue
            out.append(
                OiPoint(
                    ts_us=ts_us_from_row(r["ts"]),
                    symbol=str(r["symbol"]),
                    open_interest=oi,
                    open_interest_value=_dec(r["oi_value"]),
                    interval=str(r["interval"]),
                    source=str(r["source"]),
                )
            )
        return out

    async def coverage(self, symbol: str, interval: str, source: str) -> tuple[int, int] | None:
        checked_identifier(symbol)
        rows = await self._reader.run(build_oi_coverage(symbol, interval, source))
        if not rows or rows[0]["lo"] is None or rows[0]["hi"] is None:
            return None
        return ts_us_from_row(rows[0]["lo"]), ts_us_from_row(rows[0]["hi"])


class InMemoryOiStore:
    """Fake-backend / test store with the same dedup key `(ts, symbol, interval, source)`,
    bounded: past `max_rows` the oldest-written row is evicted (the dev ticker tap never grows
    it without end)."""

    def __init__(self, max_rows: int = 200_000) -> None:
        self._rows: dict[tuple[int, str, str, str], OiPoint] = {}
        self._max = max_rows

    async def write_points(self, rows: Sequence[OiPoint]) -> None:
        for p in rows:
            self._rows[(p.ts_us, p.symbol, p.interval, p.source)] = p
        while len(self._rows) > self._max:
            del self._rows[next(iter(self._rows))]

    def _series(self, symbol: str, interval: str, source: str) -> list[OiPoint]:
        return sorted(
            (
                p
                for p in self._rows.values()
                if (p.symbol, p.interval, p.source) == (symbol, interval, source)
            ),
            key=lambda p: p.ts_us,
        )

    async def read_points(
        self, symbol: str, interval: str, source: str, rng: _Range, limit: int
    ) -> list[OiPoint]:
        hits = self._series(symbol, interval, source)
        return [p for p in hits if rng.start_us <= p.ts_us < rng.end_us][:limit]

    async def coverage(self, symbol: str, interval: str, source: str) -> tuple[int, int] | None:
        hits = self._series(symbol, interval, source)
        return (hits[0].ts_us, hits[-1].ts_us) if hits else None

    def __len__(self) -> int:
        return len(self._rows)
