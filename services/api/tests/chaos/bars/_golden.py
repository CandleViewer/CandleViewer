"""Goldens and invariants for the bars chaos suite (E12-Q06), over the E12-Q02 machinery.

The golden of a scenario is what the **venue** printed (`StubExchange.trades`, the truth the
wire faults never touch), folded through E12-Q02's runner: the live `BarBuilderSet` fan-out
(`bench.bar_conformance.runner.run_set`), compared with E12-Q02's canonical comparator. The
runner ticks its clock to the last print, so the last time bar is still open there and closed
by the clock in the rig; that one `closed` flag is the only difference ignored (the same
documented tolerance as `runner.reference_diffs`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

from bench.bar_conformance import runner
from bench.bar_determinism import comparator
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.trade_stream import GapEvent
from tests.chaos.ingestion._rig import Rig

_EID = uuid.UUID(int=1)


def venue_tape(rig: Rig, symbol: str) -> list[TradeEvent]:
    """Every print the venue emitted, in the `(ts_event, trade_id)` order `TradeStream` merges."""
    events: list[TradeEvent] = []
    for rec in rig.ex.trades.prints[symbol]:
        price, qty = Decimal(rec["p"]), Decimal(rec["v"])
        events.append(
            TradeEvent.model_construct(
                schema_version=1,
                event_id=_EID,
                ts_event=int(rec["T"]) * 1000,
                ts_ingest=int(rec["T"]) * 1000,
                source="replay",
                category="linear",
                symbol=symbol,
                trade_id=rec["i"],
                price=price,
                qty=qty,
                side=rec["S"].lower(),
                is_block_trade=bool(rec.get("BT", False)),
                price_ticks=0,
                notional=price * qty,
                seq=len(events),
            )
        )
    return sorted(events, key=lambda t: (t.ts_event, t.trade_id))


async def golden_bars(
    tape: Sequence[TradeEvent], specs: dict[str, BarSpec], symbol: str
) -> dict[str, list[Bar]]:
    """Final bars per spec label through E12-Q02's runner."""
    return await runner.run_set(list(tape), specs, symbol)


def diffs(golden: Sequence[Bar], actual: Sequence[Bar]) -> list[comparator.Diff]:
    """Golden vs actual, ignoring the golden tail's `closed` flag (see the module docstring)."""
    last = len(golden) - 1
    return [
        d
        for d in comparator.compare(golden, actual)
        if not (d.field == "closed" and d.position == last)
    ]


def assert_matches_golden(golden: Sequence[Bar], actual: Sequence[Bar], what: str) -> None:
    found = diffs(golden, actual)
    assert not found, f"{what} differs from the golden:\n{comparator.render(found)}"


def total_volume(bars: Sequence[Bar]) -> Decimal:
    return sum((b.volume for b in bars), Decimal(0))


def assert_conserved(golden: Sequence[Bar], actual: Sequence[Bar], what: str) -> None:
    """Volume and print count are conserved: nothing lost, nothing counted twice."""
    assert total_volume(actual) == total_volume(golden), f"{what}: volume not conserved"
    assert sum(b.trade_count for b in actual) == sum(b.trade_count for b in golden), (
        f"{what}: trade count not conserved"
    )


def assert_monotonic(bars: Sequence[Bar], what: str) -> None:
    """No bar opens before its predecessor, and indices strictly increase (AC3)."""
    for prev, cur in pairwise(bars):
        assert cur.index > prev.index, f"{what}: index {cur.index} after {prev.index}"
        assert cur.open_time >= prev.open_time, f"{what}: bar {cur.index} opens before {prev.index}"


def assert_gap_marked(bars: Sequence[Bar], gap: GapEvent, what: str) -> None:
    """AC1: the first bar to close after an unrecovered hole is not presented as complete."""
    after = [b for b in bars if b.close_time >= gap.end_us]
    if not after:
        # A distinct type, so the strict xfail (raises=AssertionError) cannot pass for this reason.
        raise LookupError(f"{what}: no bar closes after the gap")
    first = after[0]
    assert first.gap_before or first.partial, f"{what}: bar {first.index} hides the gap"
