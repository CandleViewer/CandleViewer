"""Scenario 5b - the real QuestDB container is stopped under the bars writer. C-13.6 #10.

The container leg of `test_s05_store_outage.py` (E12-Q06 AC2). It runs only in the integration job
(`_job-integration.yml`'s storage chaos step, `pytest tests/chaos -m "chaos and integration"`),
which brings the compose stack up under the pinned project `cv-chaos`. It is NOT run by the bars
nightly (`chaos-bars-nightly.yml` starts no stack, so it skips there) nor by the PR lane. It stops
and starts the compose QuestDB, so `_gate.py` opens only on a github-hosted runner with the
pinned project, or locally with `CV_CHAOS_STACK=1` and that project. Anywhere else, and without
a reachable QuestDB, it skips; it never starts a container that was not already up.

`BarWriter` over the production `IlpWriter` over a real TCP socket writes the recorded-corpus
volume bars of a unique symbol; QuestDB is stopped half way (the second half is submitted while
it is down, `IlpWriter` keeps those rows buffered, `BarWriter` sees no failure), then started.
Declared: after recovery the table holds each golden bar exactly once (the DEDUP key
`(bar_param, generation, index)` makes a re-sent row idempotent), with the golden's prices.
The fake-store half of the scenario (retry budget, loud drops, accounting) is the sibling file.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable

import pytest

from candleviewer.bars.writer import BarWriter
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._gate import questdb_ownership_skip, stack_skip_reason
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
    if (reason := stack_skip_reason(os.environ)) is not None:
        pytest.skip(reason)
    if (reason := questdb_ownership_skip([st.QDB_PG_PORT, st.QDB_ILP_PORT])) is not None:
        pytest.skip(reason)  # never talk to a port we cannot prove is our own container
    if not await st.qdb_up():
        pytest.skip("QuestDB compose stack not reachable: integration job only")


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


def _flushed_and_has(ilp: IlpWriter, symbol: str, n: int) -> Callable[[], Awaitable[bool]]:
    """Poll body: `BarWriter` hands rows to the ILP writer asynchronously, so push whatever it has
    reached by now (a batch under `flush_rows` waits for the next flush) and count what landed."""

    async def check() -> bool:
        try:
            await ilp.flush("bars_volume")
        except Exception:
            return False  # QuestDB still down or restarting: the rows stay buffered
        return await _has(symbol, n)

    return check


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
        await st.until(
            _flushed_and_has(ilp, symbol, half), "arrange: first half visible", VISIBLE_S
        )
        async with st.stopped("questdb", st.qdb_up):
            await writer.submit(expected[half:], VOLUME_1, generation=GENERATION)
        await st.until(_flushed_and_has(ilp, symbol, len(expected)), "recovery: every bar", 120)
        assert await writer.stop() == 0
        await ilp.stop()
        assert await _stored(symbol) == [(b.index, float(b.close)) for b in expected]
    finally:
        await writer.stop(timeout_s=0)
        await ilp.stop()
