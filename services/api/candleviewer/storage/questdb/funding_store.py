"""QuestDB `funding_rates` store (E24-T02, `21-database-schema.md` §4.7).

Settled rows only. The write path refuses anything that is not a
`SettledFunding` from the `history` source - a predicted/estimated value can
never become a row (STRIDE T: predicted presented as settled). Dedup key
`(ts, symbol)` (table DDL) makes a re-run backfill idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from candleviewer.domain.funding import (
    SOURCE_HISTORY,
    PredictedFundingRefused,
    SettledFunding,
)
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import (
    QuestDbReader,
    build_funding_coverage,
    build_read_funding,
)
from candleviewer.storage.sql_identifiers import checked_identifier


class QuestDbFundingStore:
    def __init__(self, writer: IlpWriter, reader: QuestDbReader) -> None:
        self._writer = writer
        self._reader = reader

    async def write_settled(self, rows: Sequence[SettledFunding]) -> None:
        payload: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, SettledFunding) or row.source != SOURCE_HISTORY:
                raise PredictedFundingRefused("only settled history rows may be persisted")
            payload.append(
                {
                    "ts": row.ts_us,
                    "symbol": row.symbol,
                    "funding_rate": float(row.funding_rate),
                    "annualised_pct": float(row.annualised_pct),
                    "interval_min": row.interval_min,
                    "source": row.source,
                }
            )
        if payload:
            await self._writer.write_rows("funding_rates", payload, "ts")

    async def read_settled(self, symbol: str, rng: TimeRange, limit: int) -> list[SettledFunding]:
        checked_identifier(symbol)
        rows = await self._reader.run(build_read_funding(symbol, rng, limit))
        return [
            SettledFunding(
                ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                funding_rate=Decimal(repr(float(str(r["funding_rate"])))),
                interval_min=int(str(r["interval_min"])),
                annualised_pct=Decimal(repr(float(str(r["annualised_pct"])))),
                source=str(r["source"]),
            )
            for r in rows
        ]

    async def coverage(self, symbol: str) -> tuple[int, int] | None:
        checked_identifier(symbol)
        rows = await self._reader.run(build_funding_coverage(symbol))
        if not rows or rows[0]["lo"] is None or rows[0]["hi"] is None:
            return None
        return ts_us_from_row(rows[0]["lo"]), ts_us_from_row(rows[0]["hi"])


class InMemoryFundingStore:
    """Test/fake-backend store with the same dedup `(ts, symbol)` and guard."""

    def __init__(self) -> None:
        self._rows: dict[tuple[int, str], SettledFunding] = {}

    async def write_settled(self, rows: Sequence[SettledFunding]) -> None:
        for row in rows:
            if not isinstance(row, SettledFunding) or row.source != SOURCE_HISTORY:
                raise PredictedFundingRefused("only settled history rows may be persisted")
            self._rows[(row.ts_us, row.symbol)] = row

    async def read_settled(self, symbol: str, rng: TimeRange, limit: int) -> list[SettledFunding]:
        hits = [
            r
            for r in self._rows.values()
            if r.symbol == symbol and rng.start_us <= r.ts_us < rng.end_us
        ]
        return sorted(hits, key=lambda r: r.ts_us)[:limit]

    async def coverage(self, symbol: str) -> tuple[int, int] | None:
        stamps = [ts for ts, sym in self._rows if sym == symbol]
        return (min(stamps), max(stamps)) if stamps else None

    def __len__(self) -> int:
        return len(self._rows)
