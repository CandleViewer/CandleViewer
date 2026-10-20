"""D2-M4 (#2787) on a REAL QuestDB 8.1.1 (CI's `integration` job): a non-time WS tail read starts
at the later of its window start and the `ts` of its kind's table's k-th newest row in the window.

On D2-M2's tables (its seeding, by import), at k = `K` and at a k whose row is tied with the next:
every case's rows equal one statement of `main`'s read from the bound (every column, in order),
whose keys a model of every seeded row predicts (the `:3` series and the rows with no bar index
too); `dense` reads as with no bound; `count()` from the bound is k and its ties. The bound plans
as a `Limit lo hi` over a backward scan from the window start, with no sort and no filter; the
series bound starts at the bound, the tail there or later. The bound at the shipped K
(`MAX_TAIL_SCAN_ROWS`) is EXPLAINed too: a plan needs no 500 000 rows, so nothing runs at it, and
`D2M4_TAIL_READS=` records the warm times of each statement of a `dense` and a `sparse` read at
k = 50 000 only; no time is asserted.
"""

from __future__ import annotations

import json
import os
import statistics
from datetime import datetime

import asyncpg
import pytest

from candleviewer.bars.limits import MAX_TAIL, MAX_TAIL_SCAN_ROWS
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarReader, build_tail_scan_bound_query, row_key
from candleviewer.bars.rows import bar_param_for
from candleviewer.domain.sql_names import ts_param, ts_us_from_row
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.wiring import LazyPgWire
from tests.integration.bench import test_d2_m2_tail_bound_questdb as m2
from tests.integration.bench.test_d2_m2_tail_bound_questdb import questdb
from tests.integration.storage import test_questdb_hot_tier as hot

pytestmark = pytest.mark.integration
__all__ = ["questdb"]  # D2-M2's fixture: a fresh QuestDB 8.1.1 container for this module

K = 50_000  # its k-th newest row lies inside `dense`'s 29 d (at its default 200 000 rows)


def _newest_first(cases: dict[str, list[m2.Key]]) -> list[int]:
    """Every `ts` `m2._seed` writes to a table, newest first: each case's rows, the `:3` series'
    (`run`'s keys) and `few`'s 700 rows with no bar index."""
    stamps = [key[0] for keys in [*cases.values(), cases["run"]] for key in keys]
    return sorted(stamps + [m2.NOW_US - k * 7_000_000 for k in range(1, 701)], reverse=True)


async def _read(wire: LazyPgWire, spec: BarSpec, case: str, k: int) -> m2._Recorder:
    rec = m2._Recorder(wire)
    reader = BarReader(rec, m2._no_rebuild, now_us=lambda: m2.NOW_US, tail_scan_rows=k)
    await reader.read_tail(m2._symbol(case), spec, MAX_TAIL)
    return rec


def _start(plan: str) -> int:
    """The `ts` a plan's interval starts at (`intervals: [("<ISO time>","MAX")]`)."""
    found = m2.INTERVAL.search(plan)
    assert found, plan
    return ts_us_from_row(datetime.fromisoformat(found[1]))


def _scan_plan(plan: str, k: int) -> None:
    """The table-row bound plans as a `Limit` of its k-th row over a backward scan of the
    designated timestamp from the window start, with no sort and no filter."""
    assert f"Limit lo: {k - 1} hi: {k}" in plan and "Row backward scan" in plan, plan
    assert "Interval backward scan on: bars_" in plan, plan
    assert "Sort" not in plan and "filter" not in plan.lower(), plan


async def _plans(conn: asyncpg.Connection, rec: m2._Recorder, k: int, at: list[int]) -> list[str]:
    """QuestDB's `EXPLAIN` of the three statements `read_tail` ran, on their binds, checked; `at`:
    where each one's interval starts. Once per text: 8.1.1 caches an `EXPLAIN` and explains the
    same text again with the first one's intervals, whatever the binds (runs use their own)."""
    plans = [
        "\n".join(str(r[0]) for r in await conn.fetch("EXPLAIN " + c.sql, *c.binds))
        for c in rec.calls
    ]
    scan, bound = plans[:2]
    _scan_plan(scan, k)
    assert "Row backward scan" in bound and f"limit: {MAX_TAIL}" in bound, bound
    assert "Sort" not in bound, bound
    assert [_start(p) for p in plans] == at, plans
    return plans


async def _times(wire: LazyPgWire, spec: BarSpec, case: str) -> dict[str, float]:
    """Each statement's warm time (ms), the median of `REPEATS` passes after one that warms."""
    runs: dict[str, list[float]] = {"bound": [], "series": [], "tail": []}
    for n in range(m2.REPEATS + 1):
        rec = await _read(wire, spec, case, K)
        for name, call in zip(runs, rec.calls, strict=False):  # no tail: an empty series
            runs[name] += [round(call.ms, 2)] if n else []
    return {name: statistics.median(ms) for name, ms in runs.items() if ms}


@pytest.mark.asyncio
async def test_d2_m4_the_table_row_bound_is_a_backward_scan_of_k_rows_on_questdb(
    questdb: tuple[str, int, int],
) -> None:
    host, pg, ilp = questdb
    conn = await hot._connect(host, pg)
    wire = LazyPgWire(host, pg, hot._PGWIRE_USER, hot._PGWIRE_PASSWORD, name="bars_hydrate")
    cases = {case: m2._keys(stamps) for case, stamps in m2._stamps().items()}
    every = _newest_first(cases)
    window = [t for t in every if t >= m2.SINCE]
    tied = next(k for k in range(2_000, len(window)) if window[k - 1] == window[k])
    plans: dict[str, list[str]] = {}
    times: dict[str, dict[str, dict[str, float]]] = {}
    try:
        await run_migrations(hot._AsyncpgExecutor(conn), hot.DDL_DIR)
        for kind in m2.KINDS:  # both first, as in D2-M2: 8.1.1 refused a later count's binds
            assert await m2._seed(host, pg, ilp, kind, cases) == len(every)  # the model holds all
            await hot.wait_for_row_count(conn, f"bars_{kind}", len(every), timeout_s=180)
        for kind in m2.KINDS:
            table, spec = f"bars_{kind}", BarSpec(kind=kind, range_ticks=2)
            sql, binds = build_tail_scan_bound_query(kind, m2.SINCE, now_us=m2.NOW_US)  # shipped K
            shipped = "\n".join(str(r[0]) for r in await conn.fetch("EXPLAIN " + sql, *binds))
            _scan_plan(shipped, MAX_TAIL_SCAN_ROWS)
            assert _start(shipped) == m2.SINCE, shipped
            for k in (K, tied):
                at = window[k - 1]  # the k-th newest `ts` in the window
                sql = f"SELECT count() FROM {table} WHERE ts >= $1"  # noqa: S608  # nosec B608 - test-owned literal table name
                ties = sum(t == at for t in window[k:])
                assert int(await conn.fetchval(sql, ts_param(at))) == k + ties, (kind, k)
                assert m2.SINCE < at and (k == K or ties), (kind, k)
                for case, keys in cases.items():
                    binds = (m2._symbol(case), bar_param_for(spec), ts_param(at))
                    one = await wire.fetch(m2.ONE[kind], *binds)
                    rec = await _read(wire, spec, case, k)
                    want = sorted((key for key in keys if key[0] >= at), reverse=True)[:MAX_TAIL]
                    tail = want[-1][0] if len(want) == MAX_TAIL else at
                    starts = [m2.SINCE, at, tail][: len(rec.calls)]
                    assert [ts_us_from_row(c.binds[-1]) for c in rec.calls] == starts, case
                    if case == "dense" and k == K:  # its three statements start apart
                        plans[kind] = await _plans(conn, rec, k, starts)
                    assert [ts_us_from_row(r["ts"]) for r in rec.calls[0].rows] == [at], case
                    two = rec.calls[2].rows if len(rec.calls) == 3 else []
                    assert [list(r.items()) for r in two] == [list(r.items()) for r in one], case
                    assert [row_key(r) for r in one] == want, (kind, case, k)
                    if case == "dense" and k == K:  # its newest `MAX_TAIL` all lie above the bound
                        assert want == sorted(keys, reverse=True)[:MAX_TAIL]
            times[kind] = {case: await _times(wire, spec, case) for case in ("dense", "sparse")}
        machine = os.environ.get("D2M4_MACHINE") or ("CI" if os.environ.get("CI") else "?")
        doc = {"machine": machine, "questdb": m2.QDB_IMAGE, "k": K, "tied_k": tied}
        print("D2M4_TAIL_READS=" + json.dumps({**doc, "table_rows": len(every), "ms": times}))
        print("D2M4_PLANS=" + json.dumps(plans))
    finally:
        await wire.close()
        await conn.close()
