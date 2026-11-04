"""#2017: `/market/bars` keyset paging over same-ts non-time bars on a real QuestDB.

Kept out of `test_questdb_hot_tier.py` so this PR does not touch (and the pre-commit
formatter does not re-wrap) that module's pragma lines.
"""

from __future__ import annotations

import pytest

from candleviewer.storage.questdb.runner import run_migrations
from tests.integration.storage.test_questdb_hot_tier import (
    _PGWIRE_PASSWORD,
    _PGWIRE_USER,
    DDL_DIR,
    _AsyncpgExecutor,
    _connect,
    questdb_container,
    wait_for_row_count,
)

__all__ = ["questdb_container"]  # fixture re-export for this module

pytestmark = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_ts_renko_bricks_page_by_key_on_real_questdb(
    questdb_container: tuple[str, int, int],
) -> None:
    """#2017: three same-ts bricks (index 0..2) paged with limit=1 through `BarReader` (the
    `/market/bars` read path) and the expanded keyset predicate -> [0], [1], [2], then done."""
    from decimal import Decimal

    from candleviewer.bars.models import Bar, BarSpec
    from candleviewer.bars.reader import BarReader, row_key
    from candleviewer.bars.rows import bar_row
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    sink = QuestDbRowSink(f"{host}:{ilp_port}", f"{host}:{pg_port}", _PGWIRE_USER, _PGWIRE_PASSWORD)
    spec = BarSpec(kind="renko", range_ticks=20)
    ts = 1_700_000_000_000_000
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)

        # Rows as `BarWriter` stamps them (`bar_row`: `source`, `row_checksum`): the reader
        # withholds a row without provenance at any open time (BR-05).
        def _row(i: int) -> dict[str, object]:
            bar = Bar.model_validate(
                dict(
                    spec_hash=spec.spec_hash, symbol="BTCUSDT", index=i, open_time=ts,
                    close_time=ts, open=Decimal("1"), high=Decimal("2"), low=Decimal("0.5"),
                    close=Decimal("1.5"), volume=Decimal("3"), buy_volume=Decimal("2"),
                    sell_volume=Decimal("1"), delta=Decimal("1"), min_delta=Decimal("0"),
                    max_delta=Decimal("1"), trade_count=3, turnover=Decimal("4.5"),
                    vwap=Decimal("1.5"), closed=True, partial=False, gap_before=False,
                )
            )  # fmt: skip
            return bar_row(bar, spec, generation=0)

        rows = [_row(i) for i in (2, 0, 1)]
        await sink.write_rows("bars_renko", rows, "ts")
        await sink.stop()
        await wait_for_row_count(conn, "bars_renko", 3)
        wal = await conn.fetchrow("SELECT * FROM wal_tables() WHERE name = 'bars_renko'")
        assert wal is not None and not wal["suspended"], f"bars_renko WAL suspended: {wal}"
        assert int(wal["sequencerTxn"]) > 0, f"no ILP commit reached bars_renko: {dict(wal)}"

        class _Conn:
            async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
                return [dict(r) for r in await conn.fetch(sql, *params)]

        async def _noop(*_: object) -> None: ...

        reader, key, pages = BarReader(_Conn(), _noop), None, []
        for _ in range(5):
            page = await reader.read_bars("BTCUSDT", spec, ts - 1, ts + 1, 2, at_key=key)
            nxt = page.next_key
            pages.append([r["index"] for r in page.rows if nxt is None or row_key(r) < nxt])
            if (key := nxt) is None:
                break
        assert pages == [[0], [1], [2]]
    finally:
        await conn.close()
