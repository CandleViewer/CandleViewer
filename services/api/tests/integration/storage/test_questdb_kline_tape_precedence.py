"""BR-07 / SR-E12-10 on a real QuestDB: a kline-sourced `bars_time` row never overwrites or
shadows a tape row.

C-13.3: the stored-tape lookup SQL, the composed `KlineBarsSink` -> `BarWriter` -> ILP path and
`BarReader.read_bars` run on the pinned engine. The DEDUP key includes `generation` and `index`,
so a kline row (generation 0, NULL index) and a tape row CAN share an open time: the write side
keeps it out, and the read side serves the tape row where one exists anyway.
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
async def test_kline_backfill_rows_never_overwrite_or_shadow_tape_rows_on_real_questdb(
    questdb_container: tuple[str, int, int],
) -> None:
    from candleviewer.bars.kline_rows import KLINE_SOURCE
    from candleviewer.bars.models import BarSpec
    from candleviewer.bars.reader import BarReader, stored_bar
    from candleviewer.bars.rows import bar_row
    from candleviewer.bars.writer import BarWriter, bars_source_overwrite_refused_total
    from candleviewer.bars_wiring import KlineBarsSink, kline_tape_lookup
    from candleviewer.domain.sql_names import ts_us_from_row
    from candleviewer.storage.questdb.wiring import QuestDbRowSink
    from tests.unit.bars.test_kline_rows import SPEC, T0, W5, _k, _tape_bar

    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)

    def sink() -> QuestDbRowSink:
        return QuestDbRowSink(
            f"{host}:{ilp_port}", f"{host}:{pg_port}", _PGWIRE_USER, _PGWIRE_PASSWORD
        )

    async def commit(rows: list[dict[str, object]]) -> None:
        s = sink()
        await s.write_rows("bars_time", rows, "ts")
        await s.stop()

    def tape(open_time: int, index: int) -> dict[str, object]:
        bar = _tape_bar(open_time).model_copy(update={"index": index})
        return bar_row(bar, SPEC, generation=1)

    class _Conn:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            return [dict(r) for r in await conn.fetch(sql, *params)]

    def refusals() -> float:
        return float(bars_source_overwrite_refused_total.labels(KLINE_SOURCE, "tape")._value.get())

    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        # A stored tape row at T0+W5 (written by an earlier process: not in the writer's map).
        await commit([tape(T0 + W5, 1)])
        await wait_for_row_count(conn, "bars_time", 1)

        # The composed sink over the real lookup and a real BarWriter -> ILP.
        rows_sink = sink()
        writer = BarWriter(rows_sink)
        await writer.start()
        kline_bars = KlineBarsSink()
        kline_bars.bind(writer, kline_tape_lookup(_Conn()))
        before = refusals()
        await kline_bars("BTCUSDT", "5", [_k(T0), _k(T0 + W5)])
        assert await writer.stop() == 0
        await rows_sink.stop()
        await wait_for_row_count(conn, "bars_time", 2)
        assert refusals() == before + 1
        assert not kline_bars.health.degraded
        got = await conn.fetch("SELECT ts, source FROM bars_time ORDER BY ts, source")
        stored = [(ts_us_from_row(r["ts"]), r["source"]) for r in got]
        assert stored == [(T0, KLINE_SOURCE), (T0 + W5, "tape")]  # the tape row is untouched

        # Coexistence the write side cannot prevent: the tape builder writes T0 after the kline
        # row landed (and an earlier tape bar); the DEDUP key keeps both T0 rows.
        await commit([tape(T0 - W5, 0), tape(T0, 2)])
        await wait_for_row_count(conn, "bars_time", 4)

        async def noop(*_: object) -> None: ...

        reader = BarReader(_Conn(), noop)
        spec: BarSpec = SPEC
        whole = await reader.read_bars("BTCUSDT", spec, T0 - W5, T0 + 2 * W5, 10)
        served = [(b.ts_us, b.source) for b in map(stored_bar, whole.rows)]
        assert served == [(T0 - W5, "tape"), (T0, "tape"), (T0 + W5, "tape")]

        # Paged two rows at a time, as `after_us` callers resume: the same three tape rows,
        # never the kline row, whichever side of a page boundary the T0 rows fall.
        paged: list[tuple[int, str]] = []
        after: int | None = None
        for _ in range(10):
            page = await reader.read_bars("BTCUSDT", spec, T0 - W5, T0 + 2 * W5, 2, after_us=after)
            paged += [(b.ts_us, b.source) for b in map(stored_bar, page.rows)]
            if page.next_cursor is None:
                break
            after = page.next_cursor
        assert paged == served
    finally:
        await conn.close()
