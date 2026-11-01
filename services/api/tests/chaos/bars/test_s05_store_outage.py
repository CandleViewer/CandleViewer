"""Scenario 5 - the bar store goes away and comes back. C-13.6 #10 (datastore outage).

Declared (E12-Q06 AC2, with clause 2 as amended on #529): a bar the store rejected is never
*reported as persisted*, and the outage is either ridden out or loud.

* **Short outage** (inside `BarWriter`'s retry budget, 0.5 + 1 + 2 + 4 = 7.5 s): every row lands
  once, the persisted series equals the golden, nothing is counted as failed.
* **Long outage** (past the budget): the batches that exhaust their attempts are dropped
  *loudly* (`bars_write_failed_total{reason="transient_exhausted"}`, the writer `degraded`, an
  ERROR `bars_write_exhausted`), and the accounting closes: stored + dropped == submitted.
* "Reported as persisted" is `bars_rows_written_total`: it moves only with rows the store
  acknowledged. `confirm` on the wire still means *closed*, not *stored* (design, emit.py).

Replaying the rows an exhausted batch dropped is not built: the strict xfail below is carried to
#531 and goes green when it is.

Negative control: a sink that acknowledges and discards passes every counter and fails the
golden comparison, so the comparison, not the counters, is the oracle.

Store seam: `WriterSink` -> `BarWriter` (virtual-clock `sleep`) -> `FlakyRowSink` (in-memory
tables, outage windows on the virtual clock). The real QuestDB leg is `test_s05b`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import pytest
from structlog.testing import capture_logs

from candleviewer.bars.emit import WriterSink
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.rows import table_for
from candleviewer.bars.writer import BarWriter, bars_rows_written_total, bars_write_failed_total
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SYMBOL, VOLUME_1, BarsRig
from tests.chaos.bars._sinks import FlakyRowSink
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

#: `BarWriter`'s transient retry budget: sleeps of 0.5, 1, 2 and 4 s between its 5 attempts.
RETRY_BUDGET_S = 7.5
SHORT_OUTAGE_S = 4.0
LONG_OUTAGE_S = 30.0
RUN_S = 60.0
#: A 5 s time bar has no wire interval code, so it can never be persisted: the store scenarios
#: run on the two activity series (volume and tick bars), which close every few seconds.
STORE_SPECS = {"vol:1": VOLUME_1, "tick:20": BarSpec(kind="tick", tick_count=20)}
TABLES = {label: table_for(spec) for label, spec in STORE_SPECS.items()}


class _BlackHoleSink:
    """Negative control: acknowledges every batch and keeps nothing."""

    def __init__(self) -> None:
        self.acked = 0

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self.acked += len(rows)


@dataclass
class _Stack:
    rig: Rig
    bars: BarsRig
    writer: BarWriter
    sink: FlakyRowSink
    feed: Feeder
    t0: float

    async def run(self, seconds: float) -> None:
        await self.bars.run(self.feed, seconds)

    async def drain(self) -> None:
        """Finish the bars, then let the writer retry and write everything it still holds."""
        await self.bars.finish()
        assert await self.rig.call(self.writer.stop()) == 0, "writer left rows behind"

    def closes(self) -> int:
        """Close emissions the store was asked to persist (what `WriterSink` submits)."""
        return sum(1 for seq in self.bars.sink.updates.values() for u in seq if u.kind == "close")


async def _build(rig: Rig, sink: FlakyRowSink | _BlackHoleSink) -> tuple[BarsRig, BarWriter]:
    writer = BarWriter(sink, sleep=rig.clock.sleep)
    await writer.start()
    bars = BarsRig(rig, STORE_SPECS, extra_sinks=[WriterSink(writer)])
    await bars.start()
    return bars, writer


Make = Callable[..., Awaitable[_Stack]]


@pytest.fixture
async def make(rig: Rig) -> AsyncIterator[Make]:
    created: list[BarWriter] = []

    async def build(*outages: tuple[float, float]) -> _Stack:
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        t0 = rig.clock.now
        sink = FlakyRowSink(rig.clock, [(t0 + a, t0 + b) for a, b in outages])
        bars, writer = await _build(rig, sink)
        created.append(writer)
        return _Stack(rig, bars, writer, sink, Feeder(rig.ex), t0)

    try:
        yield build
    finally:
        for writer in created:
            await writer.stop(timeout_s=0)  # a failed test must not leave the drain task running


def _written() -> float:
    return sum(
        metric(bars_rows_written_total, kind=t.removeprefix("bars_")) for t in TABLES.values()
    )


def _failed(reason: str) -> float:
    return metric(bars_write_failed_total, reason=reason)


async def _expected(rig: Rig) -> dict[str, list[Bar]]:
    return await golden.golden_bars(golden.venue_tape(rig, SYMBOL), STORE_SPECS, SYMBOL)


async def _assert_store_equals_golden(stack: _Stack) -> None:
    expected = await _expected(stack.rig)
    for label, table in TABLES.items():
        problems = golden.row_problems(expected[label], stack.sink.stored(table))
        assert not problems, f"{table}: {problems[:3]}"


async def test_s05_short_outage_loses_nothing_and_the_store_equals_the_golden(
    rig: Rig, make: Make
) -> None:
    stack = await make((6.0, 6.0 + SHORT_OUTAGE_S))
    written, exhausted = _written(), _failed("transient_exhausted")
    await stack.run(RUN_S / 2)
    await stack.drain()
    assert stack.sink.rejected_batches > 0, "the outage never hit a write: the test proves nothing"
    assert SHORT_OUTAGE_S < RETRY_BUDGET_S
    assert _failed("transient_exhausted") == exhausted  # nothing dropped
    assert not stack.writer.degraded
    assert _written() - written == stack.sink.accepted_rows  # reported == acknowledged
    await _assert_store_equals_golden(stack)
    assert len({k[3] for k in stack.sink.rows}) == 1, "one generation: no cold start in between"


async def test_s05_no_row_is_reported_persisted_while_the_store_rejects_it(
    rig: Rig, make: Make
) -> None:
    stack = await make((0.0, 1_000.0))
    written = _written()
    await stack.run(20.0)  # inside the outage, past one batch's whole retry budget
    assert stack.sink.rejected_batches > 0
    assert stack.sink.accepted_rows == 0
    assert _written() == written, "bars_rows_written_total moved without the store's ack"
    # The wire's `confirm` means closed, not stored (emit.py): clients have bars the store lacks.
    assert stack.closes() > 0
    assert not stack.sink.rows


async def test_s05_long_outage_drops_loudly_and_the_accounting_closes(rig: Rig, make: Make) -> None:
    stack = await make((6.0, 6.0 + LONG_OUTAGE_S))
    exhausted = _failed("transient_exhausted")
    with capture_logs() as logs:
        await stack.run(6.0 + RETRY_BUDGET_S + 8.0)  # inside the outage, past the first budget
        assert stack.writer.degraded, "a batch exhausted its attempts but the writer is healthy"
        assert _failed("transient_exhausted") > exhausted
        await stack.run(RUN_S - (6.0 + RETRY_BUDGET_S + 8.0))
        await stack.drain()
    errors = [e for e in logs if e["event"] == "bars_write_exhausted"]
    assert errors
    assert {e["log_level"] for e in errors} == {"error"}
    dropped = _failed("transient_exhausted") - exhausted
    assert dropped > 0
    assert stack.sink.accepted_rows + dropped == stack.closes(), "a row was lost without a count"
    assert sum(len(stack.sink.stored(t)) for t in TABLES.values()) < stack.closes()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="rows an exhausted batch dropped are never re-emitted: replay is carried to #531",
)
async def test_s05_rows_dropped_by_an_exhausted_batch_are_replayed_exactly_once(
    rig: Rig, make: Make
) -> None:
    stack = await make((6.0, 6.0 + LONG_OUTAGE_S))
    await stack.run(RUN_S)
    await stack.drain()
    await _assert_store_equals_golden(stack)


async def test_s05_negative_control_a_sink_that_acks_and_discards_fails_the_golden(
    rig: Rig,
) -> None:
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    sink = _BlackHoleSink()
    bars, writer = await _build(rig, sink)
    written = _written()
    await bars.run(Feeder(rig.ex), 20.0)
    await bars.finish()
    assert await rig.call(writer.stop()) == 0
    expected = await _expected(rig)
    # every counter says "persisted" ...
    assert sink.acked > 0
    assert _written() - written == sink.acked
    # ... and the golden comparison says nothing is there
    problems = golden.row_problems(expected["vol:1"], [])
    assert any("missing from the store" in p for p in problems)
    zeros = dict.fromkeys(("open", "high", "low", "close", "volume", "trade_count"), 0)
    stale: list[dict[str, object]] = [{"index": 0, **zeros}]
    assert any("golden" in p for p in golden.row_problems(expected["vol:1"], stale))
