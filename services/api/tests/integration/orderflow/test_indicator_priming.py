"""E13-T02 (#426): an indicator instance primed through `BarReader` on a real QuestDB (C-13.3).

The series store hydrates from the newest stored rows (`read_tail`); an instance that needs more
bars than the store holds reads the older ones of the series' generation through
`stored_history` (`read_bars`, parameterised SQL), on one of the recompute slots, and ends as a
from-scratch fold of the whole window. Another generation's rows and a kline row are left out.
"""

from __future__ import annotations

import asyncio
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
async def test_an_instance_primes_older_bars_through_bar_reader_on_real_questdb(
    questdb_container: tuple[str, int, int],
) -> None:
    from candleviewer.bars.kline_rows import KLINE_SOURCE, ORDERFLOW_NULL_COLUMNS
    from candleviewer.bars.models import Bar, BarSpec
    from candleviewer.bars.reader import BarReader, BarTail
    from candleviewer.bars.rows import bar_row, row_checksum
    from candleviewer.bars.series_store import SeriesStore
    from candleviewer.orderflow.indicators.engine import (
        IndicatorEngine,
        resolve_instances,
        stored_history,
    )
    from candleviewer.orderflow.indicators.kernels import compute
    from candleviewer.orderflow.indicators.types import KernelContext, bar_input
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    spec, sym = BarSpec(kind="time", interval_ms=60_000), "BTCUSDT"
    t0, minute = 1_700_000_040_000_000, 60_000_000

    def bar(i: int) -> Bar:
        t, close = t0 + i * minute, Decimal(100 + i % 7)
        return Bar.model_validate(
            dict(
                spec_hash=spec.spec_hash, symbol=sym, index=i, open_time=t,
                close_time=t + minute - 1, open=close, high=close + 2, low=close - 1,
                close=close, volume=Decimal(3), buy_volume=Decimal(2), sell_volume=Decimal(1),
                delta=Decimal(1), min_delta=Decimal(0), max_delta=Decimal(1), trade_count=3,
                turnover=close * 3, vwap=close, closed=True, partial=False, gap_before=False,
            )
        )  # fmt: skip

    def row(i: int, gen: int = 0, **change: object) -> dict[str, object]:
        out = {**bar_row(bar(i), spec, generation=gen), **change}
        out["row_checksum"] = row_checksum(out)
        return out

    flowless = dict.fromkeys(ORDERFLOW_NULL_COLUMNS)
    rows = [row(i) for i in range(40)]  # generation 0, minutes 0..39
    # Inside the window the read takes, and left out: another generation's bar, a kline row.
    rows += [row(20, gen=1), row(21, source=KLINE_SOURCE, index=None, **flowless)]
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        sink = QuestDbRowSink(
            f"{host}:{ilp_port}", f"{host}:{pg_port}", _PGWIRE_USER, _PGWIRE_PASSWORD
        )
        await sink.write_rows("bars_time", rows, "ts")
        await sink.stop()
        await wait_for_row_count(conn, "bars_time", len(rows))

        class _Conn:
            async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
                return [dict(r) for r in await conn.fetch(sql, *params)]

        async def _noop(*_: object) -> None: ...

        now = t0 + 40 * minute
        reader = BarReader(_Conn(), _noop, now_us=lambda: now)

        async def tail(symbol: str, s: BarSpec, limit: int) -> BarTail:
            return await reader.read_tail(symbol, s, 10)  # the store holds the newest ten

        store = SeriesStore(tail)
        hold = await store.ensure(sym, spec)
        engine = IndicatorEngine(store, history=stored_history(reader))
        (r,) = resolve_instances([{"indicator": "sma", "params": {"n": 20}}], spec)
        engine.admit(sym, spec, (r,), "c1", "u1", history=5)  # 25 bars: 15 must be read
        await asyncio.gather(*list(engine._tasks))
        batch = engine.snapshot(sym, r.key, 100)
        assert batch is not None
        assert [p.index for p in batch.points] == list(range(15, 40))
        expected = compute(
            "sma", [bar_input(bar(i)) for i in range(15, 40)], r.params, source="close",
            context=KernelContext(),
        )  # fmt: skip
        assert [p.values for p in batch.points] == expected
        hold.release()
    finally:
        await conn.close()
