"""The indicator pipeline end to end on the emit path (E13-T02, #426; scenarios 1, 2 and 5): the
recorded BTCUSDT tape (C-13.5) through the real `BarBuilderSet` and `EmitRouter` into the series
store, the indicator engine and a writer, in the order `wire_bars` wires them, with a gap (four
quiet minutes) and a late trade (an amended close). Every instance ends as a from-scratch fold of
the densified series the builder ended with, and the late trade reached subscribers as amended
points."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from candleviewer.bars.emit import WriterSink
from candleviewer.bars.models import BarUpdate
from candleviewer.bars.series import BarSeries
from candleviewer.bars.series_store import SeriesStore
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.indicators.engine import IndicatorEngine, resolve_instances
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.types import KernelContext, bar_input
from tests.unit.bars._set_harness import TOPIC, FakeWriter, make_set, settle
from tests.unit.bars._trades import final_bars, trade
from tests.unit.bars.test_time_builder_golden import _tape
from tests.unit.orderflow.indicators._engine import M1, SYM, Listener

MINUTE: Final = 60_000_000
INSTANCES: Final[list[dict[str, Any]]] = [
    {"indicator": "ema", "params": {"n": 9}},
    {"indicator": "rsi", "params": {"n": 7}},
    {"indicator": "vwap"},
    {"indicator": "cvd"},
    {"indicator": "adx", "params": {"n": 5}},
]


def _script() -> tuple[list[TradeEvent], int]:
    """The tape with minutes 20-23 removed (a gap) and, right after the first trade of minute 61,
    a late trade inside minute 60 at a price far off its close; returns it and minute 60's open."""
    tape = _tape()
    start = tape[0].ts_event // MINUTE * MINUTE
    quiet = range(start + 20 * MINUTE, start + 24 * MINUTE)
    kept = [t for t in tape if t.ts_event not in quiet]
    late_bar = start + 60 * MINUTE
    at = next(i for i, t in enumerate(kept) if t.ts_event >= late_bar + MINUTE)
    late = trade(late_bar + 30_000_000, px=str(kept[at].price + 500), qty="0.5", seq=10**9)
    return [*kept[: at + 1], late, *kept[at + 1 :]], late_bar


async def test_the_tape_with_a_gap_and_a_late_trade_ends_as_a_from_scratch_fold(
    tmp_path: Path,
) -> None:
    trades, late_bar = _script()
    bus, store, listener, writer = Bus(), SeriesStore(), Listener(), FakeWriter()
    engine = IndicatorEngine(store)
    engine.listen(listener)
    bars_set = make_set(tmp_path, bus=bus, sinks=[store, engine, WriterSink(writer)])
    await bars_set.register(M1, SYM, "c1")
    hold = await store.ensure(SYM, M1)
    requested = resolve_instances(INSTANCES, M1)
    for n in range(10):  # ten consumers: one instance each, one fold per close (scenario 2)
        engine.admit(SYM, M1, requested, f"c{n}", f"u{n}", history=500)
    for t in trades:
        await bus.publish(TOPIC, t)
    await settle(bus, bars_set)
    await bars_set.stop()

    builder, updates = TimeBarBuilder(M1, SYM), list[BarUpdate]()
    for t in trades:
        updates += builder.on_trade(t)
    closed = [b for b in final_bars(updates) if b.closed]
    dense = BarSeries(M1, closed).densify()
    assert len(dense) > len(closed)  # the gap was filled
    amended = [b for b in closed if b.open_time == late_bar]
    assert len(amended) == 1  # the late trade re-closed minute 60
    for r in requested:
        snapshot = engine.snapshot(SYM, r.key, 1000)
        assert snapshot is not None
        rows = compute(
            r.definition.id, [bar_input(b) for b in dense], r.params,
            source=r.kernel.sources[0], context=KernelContext(),
        )  # fmt: skip
        expected = [
            tuple(map(repr, row)) for row, b in zip(rows, dense, strict=True) if not b.synthetic
        ]
        assert [tuple(map(repr, p.values)) for p in snapshot.points] == expected, r.definition.id
        assert [p.index for p in snapshot.points] == [b.index for b in closed]
    republished = [
        p for kind, batches in listener.events if kind == "points"
        for batch in batches.values() for p in batch.points if p.amended
    ]  # fmt: skip
    assert republished and {p.index for p in republished} >= {amended[0].index}
    assert {index for _, index, _ in writer.rows} >= {b.index for b in closed}  # last sink
    hold.release()
