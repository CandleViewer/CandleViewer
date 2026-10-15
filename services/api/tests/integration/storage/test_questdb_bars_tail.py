"""E12-T06 (#2195): `read_tail`, the WS snapshot store's hydration read, on a real QuestDB.

C-13.3: the tail SQL (a `ts` lower bound, `"index" IS NOT NULL`, the three-key DESC order and
the inline LIMIT) runs on the pinned engine, not only against a fake that ignores it.
"""

from __future__ import annotations

from decimal import Decimal

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
async def test_read_tail_returns_the_newest_bars_inside_its_window_on_real_questdb(
    questdb_container: tuple[str, int, int],
) -> None:
    """Five tape rows across generations 0 and 1 at minutes 100..102 (two each at 101 and 102),
    an old tape row at minute 0, a tampered row at minute 103 and a NULL-index kline row at
    minute 104, newest of all. The read is newest-N by `(ts, generation, index)`, oldest
    first, without the kline row; the tampered row is dropped and counted; a row older than
    the window is not returned even when the LIMIT would admit it."""
    from candleviewer.bars.kline_rows import KLINE_SOURCE, ORDERFLOW_NULL_COLUMNS
    from candleviewer.bars.models import Bar, BarSpec
    from candleviewer.bars.reader import BarReader, BarTail
    from candleviewer.bars.rows import bar_row, row_checksum
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    spec, sym = BarSpec(kind="time", interval_ms=60_000), "BTCUSDT"
    t0, minute = 1_700_000_040_000_000, 60_000_000

    def row(
        i: int, at: int, gen: int = 0, change: dict[str, object] | None = None
    ) -> dict[str, object]:
        t, one = t0 + at * minute, Decimal(1)
        bar = Bar.model_validate(
            dict(
                spec_hash=spec.spec_hash, symbol=sym, index=i, open_time=t,
                close_time=t + minute - 1, open=one, high=Decimal(2), low=one, close=one,
                volume=Decimal(4), buy_volume=Decimal("2.5"), sell_volume=Decimal("1.5"),
                delta=one, min_delta=one * 0, max_delta=one, trade_count=4, turnover=Decimal(4),
                vwap=one, closed=True, partial=False, gap_before=False,
            )
        )  # fmt: skip
        out = bar_row(bar, spec, generation=gen)  # exact short doubles: delta_pct is 25.0
        out.update(change or {})
        out["row_checksum"] = row_checksum(out)
        return out

    tampered = row(4, 103)
    tampered["close"] = 9.0  # edited after its checksum: an integrity event on read
    flowless = dict.fromkeys(ORDERFLOW_NULL_COLUMNS)
    kline = row(5, 104, change={"source": KLINE_SOURCE, "index": None, **flowless})
    rows = [
        row(0, 0), row(1, 100), row(2, 101), row(3, 102), row(0, 101, gen=1),
        row(1, 102, gen=1), tampered, kline,
    ]  # fmt: skip
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    sink = QuestDbRowSink(f"{host}:{ilp_port}", f"{host}:{pg_port}", _PGWIRE_USER, _PGWIRE_PASSWORD)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        await sink.write_rows("bars_time", rows, "ts")
        await sink.stop()
        await wait_for_row_count(conn, "bars_time", len(rows))

        class _Conn:
            async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
                return [dict(r) for r in await conn.fetch(sql, *params)]

        async def _noop(*_: object) -> None: ...

        async def tail(now_minute: int, limit: int) -> BarTail:
            reader = BarReader(_Conn(), _noop, now_us=lambda: t0 + now_minute * minute)
            return await reader.read_tail(sym, spec, limit)

        def keys(got: BarTail) -> list[tuple[int, int, int]]:
            return [((b.open_time - t0) // minute, gen, b.index) for gen, b in got.bars]

        # limit 4 at minute 105 (window from minute 97): the newest four are the tampered row,
        # (102, 1, 1), (102, 0, 3) and (101, 1, 0); the kline row never takes a LIMIT slot.
        got = await tail(105, 4)
        assert keys(got) == [(101, 1, 0), (102, 0, 3), (102, 1, 1)]
        assert (got.dropped, got.skipped, got.integrity_degraded) == (1, 0, True)
        # limit 10 (window from minute 85): five bars; the minute-0 row would rank but is older.
        got = await tail(105, 10)
        assert keys(got) == [(100, 0, 1), (101, 0, 2), (101, 1, 0), (102, 0, 3), (102, 1, 1)]
        # Control: from minute 19 the window starts at minute -1, and the same read has it.
        assert keys(await tail(19, 10))[:2] == [(0, 0, 0), (100, 0, 1)]
    finally:
        await conn.close()
