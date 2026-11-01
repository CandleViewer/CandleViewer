"""Scenario 5b - the real QuestDB container is stopped under the bars writer. C-13.6 #10.

The container leg of `test_s05_store_outage.py` (E12-Q06 AC2), run only by the nightly /
merge-queue integration job that brings up the compose stack (`-m "chaos and integration"`,
`tests/chaos/storage/_stack.py`). Without a reachable QuestDB the test is skipped: it never
starts a container itself.

`BarWriter` over the production `IlpWriter` over a real TCP socket writes the recorded-corpus
volume bars of a unique symbol; QuestDB is stopped half way (the second half is submitted while
it is down, `IlpWriter` keeps those rows buffered, `BarWriter` sees no failure), then started.
Declared: after recovery the table holds each golden bar exactly once (the DEDUP key
`(bar_param, generation, index)` makes a re-sent row idempotent), with the golden's prices.
The fake-store half of the scenario (retry budget, loud drops, accounting) is the sibling file.
"""

from __future__ import annotations

import uuid

import pytest

from candleviewer.bars.writer import BarWriter
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import VOLUME_1
from tests.chaos.ingestion._clock import EPOCH_S
from tests.chaos.storage import _stack as st

pytestmark = [pytest.mark.chaos, pytest.mark.integration]

GENERATION = 1
VISIBLE_S = 60.0


class _Exec:
    def __init__(self, conn: object) -> None:
        self._c = conn

    async def execute(self, sql: str, *args: object) -> None:
        await self._c.execute(sql, *args)  # type: ignore[attr-defined]  # asyncpg.Connection

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        return [dict(r) for r in await self._c.fetch(sql, *args)]  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
async def _questdb_reachable() -> None:
    if not await st.qdb_up():
        pytest.skip("QuestDB compose stack not reachable: nightly integration lane only")


async def _stored(symbol: str) -> list[tuple[int, float]]:
    conn = await st.qdb_connect()
    try:
        rows = await conn.fetch(
            'SELECT "index", close FROM bars_volume WHERE symbol = $1 ORDER BY "index"', symbol
        )
        return [(int(r[0]), float(r[1])) for r in rows]
    finally:
        await conn.close()


async def _has(symbol: str, n: int) -> bool:
    try:
        return len(await _stored(symbol)) == n
    except Exception:
        return False  # QuestDB still answering from its restart


async def test_s05b_questdb_stopped_mid_stream_leaves_each_bar_once() -> None:
    conn = await st.qdb_connect()
    try:
        await run_migrations(_Exec(conn), st.QDB_DDL)
    finally:
        await conn.close()
    symbol = f"CH{uuid.uuid4().hex[:8].upper()}"
    tape = golden.corpus_tape(symbol, frames_n=120, start_ms=round(EPOCH_S * 1000))
    expected = (await golden.golden_bars(tape, {"vol:1": VOLUME_1}, symbol))["vol:1"][:-1]
    half = len(expected) // 2
    assert half > 3, "the corpus tape is too short to split"
    ilp = IlpWriter(st.TcpIlpTransport(), ALL_SCHEMAS, flush_rows=50)
    writer = BarWriter(ilp)
    await ilp.start()
    await writer.start()
    try:
        await writer.submit(expected[:half], VOLUME_1, generation=GENERATION)
        await ilp.flush("bars_volume")
        await st.until(lambda: _has(symbol, half), "arrange: first half visible", VISIBLE_S)
        async with st.stopped("questdb", st.qdb_up):
            await writer.submit(expected[half:], VOLUME_1, generation=GENERATION)
        await st.until(lambda: _has(symbol, len(expected)), "recovery: every bar", 120)
        assert await writer.stop() == 0
        await ilp.stop()
        assert await _stored(symbol) == [(b.index, float(b.close)) for b in expected]
    finally:
        await writer.stop(timeout_s=0)
        await ilp.stop()
