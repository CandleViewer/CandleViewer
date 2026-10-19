"""D2-M2 (#3688) on a REAL QuestDB 8.1.1: the WS bars tail read's two statements return the rows
of the one they replace, every column, in order (CI's `integration` job; the py job's
db-chaos lane under `--cov`).

SYNTHETIC rows (pure functions of their position, no exchange data) go in through `bar_row` and
`QuestDbRowSink`. `bars_range` and `bars_renko` each hold one series per case, smallest param:
`run`, 200 runs of 6 bars on one `ts` (a renko trade's bricks; even indexes in a later commit),
one straddling the 1 000th newest row (4 in, 2 out), beside a `:3` series on the same `ts`;
`gen`, two generations on each `ts` but the newest, split there; `few`, 400 rows in the window,
300 below it (the newest 1 us before its start) and 700 newer rows with no bar index; `exact`,
1 000 in the window and the same 300; `sparse`, 50 across the window, the oldest at its start;
`dense`, `D2M2_DENSE_ROWS` (default 200 000) over 29 d. Each is read by `main`'s statement (`ONE`)
and by `read_tail` over a recorder. One JSON line, `D2M2_TAIL_READS=`, records the warm times of
both reads of `dense` and `sparse`; no time is asserted. The two statements of `dense` are also
EXPLAINed (`D2M2_PLANS=`): the first must plan as a backward scan that stops at the limit, with no
sort, and the second must start its interval at the bound.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import time
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from decimal import Decimal
from itertools import batched
from typing import NamedTuple

import asyncpg
import pytest
import pytest_asyncio

from candleviewer.bars.limits import MAX_NON_TIME_WINDOW_US, MAX_TAIL
from candleviewer.bars.models import Bar, BarKind, BarSpec
from candleviewer.bars.reader import BarReader, row_key
from candleviewer.bars.rows import bar_param_for, bar_row, row_checksum
from candleviewer.domain.sql_names import ts_param, ts_us_from_row
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.wiring import LazyPgWire, QuestDbRowSink
from tests.integration.storage.test_questdb_hot_tier import (
    _PGWIRE_PASSWORD,
    _PGWIRE_USER,
    DDL_DIR,
    _AsyncpgExecutor,
    _connect,
    wait_for_row_count,
)

pytestmark = pytest.mark.integration

#: The image `infra/compose/docker-compose.yml` pins, by digest.
QDB_IMAGE = (
    "questdb/questdb:8.1.1@sha256:82ef61a3919f4014e2aae1216f2803288b176a54c197d0933863bdc8c04a2e03"
)
NOW_US = 1_700_000_000_000_000  # the reader's clock: every window is fixed
SINCE = NOW_US - MAX_NON_TIME_WINDOW_US  # the window start
MIN_US, DAY_US, CHUNK, REPEATS = 60_000_000, 86_400_000_000, 5_000, 5
OLD, NEW = 1_699_000_000_000, 1_699_900_000_000  # two generations (builder cold starts, ms)
DENSE_ROWS = int(os.environ.get("D2M2_DENSE_ROWS") or 200_000)
#: The one statement `main`'s `read_tail` ran (#2195), as its `build_tail_query` wrote it.
ONE = {
    "range": 'SELECT * FROM bars_range WHERE symbol = $1 AND bar_param = $2 AND ts >= $3 AND '
    '"index" IS NOT NULL ORDER BY ts DESC, generation DESC, "index" DESC LIMIT 1000',
    "renko": 'SELECT * FROM bars_renko WHERE symbol = $1 AND bar_param = $2 AND ts >= $3 AND '
    '"index" IS NOT NULL ORDER BY ts DESC, generation DESC, "index" DESC LIMIT 1000',
}  # fmt: skip
#: case -> (rows read, of them on the oldest `ts`, the series' rows on that `ts`).
FACTS = {
    "run": (1_000, 4, 6), "gen": (1_000, 1, 2), "few": (400, 1, 1), "exact": (1_000, 1, 1),
    "sparse": (50, 1, 1), "dense": (1_000, 1, 1),
}  # fmt: skip
KINDS: tuple[BarKind, ...] = ("range", "renko")
Row = dict[str, object]
Key = tuple[int, int, int]  # `(ts, generation, index)`
#: A plan's `ts` interval as 8.1.1 prints it for `ts >= $3`: `intervals: [("<ISO time>","MAX")]`.
INTERVAL = re.compile(r'intervals: \[\("([^"]+)","MAX"\)\]')


@pytest_asyncio.fixture
async def questdb() -> AsyncIterator[tuple[str, int, int]]:
    from testcontainers.core.container import DockerContainer

    with DockerContainer(QDB_IMAGE).with_exposed_ports(8812, 9009) as c:
        host, pg = c.get_container_host_ip(), int(c.get_exposed_port(8812))
        for _ in range(60):
            try:
                await (await _connect(host, pg)).close()
                break
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(1.0)
        yield host, pg, int(c.get_exposed_port(9009))


def _stamps() -> dict[str, list[tuple[int, int]]]:
    """Each case's builder rows as `(ts, generation)`, oldest first."""
    below = [(SINCE - 1 - k * MIN_US, OLD) for k in range(300)]  # `few`'s and `exact`'s
    lone, both = [(NOW_US - MIN_US, OLD)], (OLD, NEW)  # `gen`'s newest `ts`, then both
    step = 29 * DAY_US // DENSE_ROWS
    cases = {
        "run": [(NOW_US - k * MIN_US, NEW) for k in range(1, 201) for _ in range(6)],
        "gen": lone + [(NOW_US - k * MIN_US, g) for k in range(2, 601) for g in both],
        "few": below + [(NOW_US - k * 90 * MIN_US, OLD) for k in range(1, 401)],
        "exact": below + [(NOW_US - k * 40 * MIN_US, OLD) for k in range(1, 1_001)],
        "sparse": [(SINCE + k * (MAX_NON_TIME_WINDOW_US // 50), OLD) for k in range(50)],
        "dense": [(NOW_US - (DENSE_ROWS - i) * step, OLD) for i in range(DENSE_ROWS)],
    }  # fmt: skip
    return {case: sorted(stamps) for case, stamps in cases.items()}


def _keys(stamps: list[tuple[int, int]]) -> list[Key]:
    """Each row's key, indexed in `ts` order within its generation (oldest first)."""
    nth: dict[int, int] = {}
    keys = []
    for ts, gen in stamps:
        nth[gen] = nth.get(gen, -1) + 1
        keys.append((ts, gen, nth[gen]))
    return keys


def _symbol(case: str) -> str:
    return f"D2M2{case.upper()}USDT"


def _row(spec: BarSpec, case: str, key: Key) -> Row:
    """A stored bar: a pure function of its arguments (whole-cent prices)."""
    ts, gen, i = key
    px = Decimal(10_000 + (i * 7_919 + ts // MIN_US) % 977) / 100
    bar = Bar.model_construct(
        spec_hash=spec.spec_hash, symbol=_symbol(case), index=i, open_time=ts, close_time=ts + 1,
        open=px, high=px + 1, low=px - 1, close=px + Decimal("0.5"), volume=Decimal(4),
        buy_volume=Decimal("2.5"), sell_volume=Decimal("1.5"), delta=Decimal(1),
        min_delta=Decimal(0), max_delta=Decimal(1), trade_count=4, turnover=4 * px, vwap=px,
        closed=True, partial=False, gap_before=False,
    )  # fmt: skip
    return bar_row(bar, spec, generation=gen)


async def _write(host: str, pg: int, ilp: int, table: str, rows: Iterable[Row]) -> int:
    """`rows` through one production sink, `CHUNK` at a time (never all held at once)."""
    sink, n = QuestDbRowSink(f"{host}:{ilp}", f"{host}:{pg}", _PGWIRE_USER, _PGWIRE_PASSWORD), 0
    try:
        for chunk in batched(rows, CHUNK):
            await sink.write_rows(table, list(chunk), "ts")
            n += len(chunk)
    finally:
        await sink.stop()  # drains the ILP buffer
    return n


async def _seed(host: str, pg: int, ilp: int, kind: BarKind, cases: dict[str, list[Key]]) -> int:
    """Every case's rows in `bars_<kind>`; the run's even indexes go in a later commit."""
    two, three = BarSpec(kind=kind, range_ticks=2), BarSpec(kind=kind, range_ticks=3)

    def first() -> Iterable[Row]:
        for case, keys in cases.items():
            yield from (_row(two, case, k) for k in keys if case != "run" or k[2] % 2)
        yield from (_row(three, "run", k) for k in cases["run"])  # the `:3` series
        for k in range(1, 701):  # `few`'s rows with no bar index, newer than its builder rows
            row = _row(two, "few", (NOW_US - k * 7_000_000, OLD, 0))
            row["index"] = None
            yield {**row, "row_checksum": row_checksum(row)}

    later = (_row(two, "run", k) for k in cases["run"] if not k[2] % 2)
    table = f"bars_{kind}"
    return await _write(host, pg, ilp, table, first()) + await _write(host, pg, ilp, table, later)


class _Call(NamedTuple):
    sql: str
    binds: tuple[object, ...]
    rows: list[Row]
    ms: float


class _Recorder:
    """`read_tail`'s connection: the wire, with each statement's text, binds, rows and time (ms)."""

    def __init__(self, wire: LazyPgWire) -> None:
        self.wire, self.calls = wire, list[_Call]()

    async def fetch(self, sql: str, *params: object) -> list[Row]:
        t = time.perf_counter()
        rows = await self.wire.fetch(sql, *params)
        self.calls.append(_Call(sql, params, rows, (time.perf_counter() - t) * 1e3))
        return rows


async def _plans(conn: asyncpg.Connection, calls: list[_Call], start: int) -> list[str]:
    """QuestDB's `EXPLAIN` of the two statements `read_tail` ran, on their binds, checked: the
    first is a backward scan that stops at the limit, a sort here being the whole-window read
    again; the second's interval begins at the bound `start`."""
    plans = [
        "\n".join(str(r[0]) for r in await conn.fetch("EXPLAIN " + c.sql, *c.binds)) for c in calls
    ]
    bound, tail = plans
    assert "Row backward scan" in bound and f"limit: {MAX_TAIL}" in bound, bound
    assert "Sort" not in bound, bound
    found = INTERVAL.search(tail)
    assert found and ts_us_from_row(datetime.fromisoformat(found[1])) == start, tail
    return plans


async def _no_rebuild(symbol: str, spec_hash: str, from_us: int, to_us: int) -> None:
    """`app._no_rebuild_executor`: stale-build rebuilds have no executor yet."""


async def _reads(wire: LazyPgWire, spec: BarSpec, case: str) -> tuple[list[Row], _Recorder, float]:
    """The one statement from the window start and its time (ms), then `read_tail`'s two."""
    t = time.perf_counter()
    one = await wire.fetch(ONE[spec.kind], _symbol(case), bar_param_for(spec), ts_param(SINCE))
    one_ms = (time.perf_counter() - t) * 1e3
    rec = _Recorder(wire)
    tail = await BarReader(rec, _no_rebuild, now_us=lambda: NOW_US).read_tail(
        _symbol(case), spec, MAX_TAIL
    )
    assert (tail.fetched, tail.dropped, tail.skipped, len(tail.bars)) == (len(one), 0, 0, len(one))
    return one, rec, one_ms


async def _times(wire: LazyPgWire, spec: BarSpec, case: str) -> dict[str, object]:
    """Both reads' warm times (ms): `REPEATS` passes after one that warms, and their medians."""
    runs: dict[str, list[float]] = {"one": [], "two": [], "first": [], "second": []}
    for n in range(REPEATS + 1):
        _, rec, one_ms = await _reads(wire, spec, case)
        (_, _, _, first), (_, _, _, second) = rec.calls
        for name, ms in zip(runs, (one_ms, first + second, first, second), strict=True):
            runs[name] += [round(ms, 1)] if n else []  # the first pass only warms
    return {**runs, "median": {name: statistics.median(ms) for name, ms in runs.items()}}


@pytest.mark.asyncio
async def test_d2_m2_the_two_statements_return_the_one_statement_s_rows_on_questdb(
    questdb: tuple[str, int, int],
) -> None:
    host, pg, ilp = questdb
    conn = await _connect(host, pg)
    wire = LazyPgWire(host, pg, _PGWIRE_USER, _PGWIRE_PASSWORD)
    cases = {case: _keys(stamps) for case, stamps in _stamps().items()}
    rows: dict[str, int] = {}
    times: dict[str, dict[str, dict[str, object]]] = {}
    plans: dict[str, list[str]] = {}
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        for kind in KINDS:
            rows[kind] = await _seed(host, pg, ilp, kind, cases)
            await wait_for_row_count(conn, f"bars_{kind}", rows[kind], timeout_s=180)
        for kind in KINDS:
            spec = BarSpec(kind=kind, range_ticks=2)
            for case, keys in cases.items():
                one, rec, _ = await _reads(wire, spec, case)
                want = sorted((k for k in keys if k[0] >= SINCE), reverse=True)[:MAX_TAIL]
                assert [row_key(r) for r in one] == want, (kind, case)  # the reference read
                (_, _, first, _), (_, binds, two, _) = rec.calls
                assert [list(r.items()) for r in two] == [list(r.items()) for r in one], case
                start = want[-1][0] if len(want) == MAX_TAIL else SINCE
                assert (len(first), ts_us_from_row(binds[2])) == (len(want), start), case
                at = want[-1][0]
                got = (len(want), sum(k[0] == at for k in want), sum(k[0] == at for k in keys))
                assert got == FACTS[case], (kind, case)
                if case == "dense":  # their plans; both reads' times are recorded below
                    plans[kind] = await _plans(conn, rec.calls, start)
            times[kind] = {c: await _times(wire, spec, c) for c in ("dense", "sparse")}
        machine = os.environ.get("D2M2_MACHINE") or ("CI" if os.environ.get("CI") else "?")
        doc = {"machine": machine, "questdb": QDB_IMAGE, "dense_rows": DENSE_ROWS}
        print("D2M2_TAIL_READS=" + json.dumps({**doc, "table_rows": rows, "ms": times}))
        print("D2M2_PLANS=" + json.dumps(plans))
    finally:
        await wire.close()
        await conn.close()
