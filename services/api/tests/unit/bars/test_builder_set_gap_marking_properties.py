"""A backlogged lane flags the bar holding the first print after the hole, nothing else (#529).

While `lane.lock` is held the lane applies nothing: the pre-hole prints, the gap and the post-hole
prints all queue, and the gap is drained before the first of them. The builder must flag by the
print's own time (`ts_event > GapEvent.start_us`), not by what it has applied so far.
"""

from __future__ import annotations

import asyncio
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.builder_set import production_factory
from candleviewer.bars.models import BarSpec
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import TOPIC, RecordingSink, settle
from ._trades import SYM, trade, us
from .test_builder_set_gap_marking import GAP_TOPIC, SPECS, _gap, _make

T0 = us("10:00:00")
TICK = Decimal("0.01")

# Per print: seconds since the last (1..5, so no empty 60 s interval), a one-tick step, a size.
_steps = st.lists(
    st.tuples(st.integers(1, 5), st.sampled_from((-1, 1)), st.integers(1, 4)),
    min_size=6,
    max_size=40,
)


def _tape(raw: list[tuple[int, int, int]]) -> list[TradeEvent]:
    ts, px, out = T0, 10_000, []
    for i, (dt, step, qty) in enumerate(raw):
        ts += dt * 1_000_000
        px += step
        out.append(trade(ts, px=str(Decimal(px) * TICK), qty=str(qty), seq=i))
    return out


def _first_index_after(spec: BarSpec, tape: list[TradeEvent], hole: int) -> int:
    """The index of the first bar update the print right after the hole produces, no gap."""
    builder = production_factory(lambda _s: TICK, renko_enabled=True)(spec, SYM)
    for t in tape[:hole]:
        builder.on_trade(t)
    return builder.on_trade(tape[hole])[0].bar.index


async def _backlogged(
    spec: BarSpec, tape: list[TradeEvent], hole: int, *, recovered: bool
) -> list[int]:
    """Indices flagged `gap_before` when every print queues behind a held lane lock."""
    with tempfile.TemporaryDirectory() as root:
        bus, sink = Bus(), RecordingSink()
        s = _make(Path(root), bus, sink)
        await s.register(spec, SYM, "a")
        async with s._lanes[SYM].lock:
            for t in tape[:hole]:
                await bus.publish(TOPIC, t)
            await bus.publish(GAP_TOPIC, _gap(recovered, start_us=tape[hole - 1].ts_event))
            for t in tape[hole:]:
                await bus.publish(TOPIC, t)
            await asyncio.sleep(0)  # the gap task marks every builder before a print applies
            await asyncio.sleep(0)
        await settle(bus, s)
        await s.stop()
        return sorted({b.index for _, _, b in sink.bars if b.gap_before})


@pytest.mark.parametrize("name", list(SPECS))
@settings(max_examples=25, deadline=None, derandomize=True)
@given(raw=_steps, cut=st.integers(0, 10**6))
def test_backlogged_unrecovered_gap_flags_exactly_the_bar_after_the_hole(
    name: str, raw: list[tuple[int, int, int]], cut: int
) -> None:
    tape = _tape(raw)
    hole = 1 + cut % (len(tape) - 1)  # prints before the hole, 1..len-1
    flagged = asyncio.run(_backlogged(SPECS[name], tape, hole, recovered=False))
    assert flagged == [_first_index_after(SPECS[name], tape, hole)]


@pytest.mark.parametrize("name", list(SPECS))
@settings(max_examples=10, deadline=None, derandomize=True)
@given(raw=_steps, cut=st.integers(0, 10**6))
def test_backlogged_recovered_gap_flags_nothing(
    name: str, raw: list[tuple[int, int, int]], cut: int
) -> None:
    tape = _tape(raw)
    hole = 1 + cut % (len(tape) - 1)
    assert asyncio.run(_backlogged(SPECS[name], tape, hole, recovered=True)) == []
