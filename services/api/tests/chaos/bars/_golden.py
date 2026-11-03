"""Goldens and invariants for the bars chaos suite (E12-Q06), over the E12-Q02 machinery.

The golden of a scenario is what the **venue** printed (`StubExchange.trades`, the truth the
wire faults never touch), folded through E12-Q02's runner: the live `BarBuilderSet` fan-out
(`bench.bar_conformance.runner.run_set`), compared with E12-Q02's canonical comparator. The
runner ticks its clock to the last print, so the last time bar is still open there and closed
by the clock in the rig; that one `closed` flag, of a time series only, is the only difference
ignored (the same documented tolerance as `runner.reference_diffs`).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Any

from bench.bar_conformance import runner
from bench.bar_determinism import comparator, tapes
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.trade_stream import GapEvent
from tests._corpus import frames
from tests.chaos.ingestion._feed import retime
from tests.chaos.ingestion._rig import Rig


def venue_tape(rig: Rig, symbol: str) -> list[TradeEvent]:
    """Every print the venue emitted, in the `(ts_event, trade_id)` order `TradeStream` merges."""
    return _tape(list(rig.ex.trades.prints[symbol]), symbol)


def corpus_tape(
    symbol: str, *, frames_n: int, start_ms: int, step_ms: int = 500
) -> list[TradeEvent]:
    """The recorded BTC trade corpus re-timed to one frame per `step_ms` from `start_ms`.

    Only the timestamps are rewritten (the feeder's own `retime`); prices, sizes, sides and trade
    ids are the recorded ones (C-13.5)."""
    recs: list[dict[str, Any]] = []
    for k, frame in enumerate(frames("ws/clean_publicTrade_BTCUSDT.jsonl")[:frames_n]):
        recs.extend(json.loads(retime(frame, start_ms + k * step_ms))["data"])
    return _tape(recs, symbol)


def _tape(recs: Sequence[dict[str, Any]], symbol: str) -> list[TradeEvent]:
    events = [
        tapes.event(
            seq,
            int(rec["T"]) * 1000,
            Decimal(str(rec["p"])),
            Decimal(str(rec["v"])),
            rec["S"].lower(),
            symbol,
            rec["i"],
        )
        for seq, rec in enumerate(recs)
    ]
    return sorted(events, key=lambda t: (t.ts_event, t.trade_id))


async def golden_bars(
    tape: Sequence[TradeEvent], specs: dict[str, BarSpec], symbol: str
) -> dict[str, list[Bar]]:
    """Final bars per spec label through E12-Q02's runner."""
    return await runner.run_set(list(tape), specs, symbol)


def diffs(golden: Sequence[Bar], actual: Sequence[Bar], *, kind: str) -> list[comparator.Diff]:
    """Golden vs actual. For time bars only, the golden tail's `closed` flag is ignored (the
    module docstring): every other series' tail is still forming in both, so there it must match."""
    last = len(golden) - 1
    return [
        d
        for d in comparator.compare(golden, actual)
        if not (kind == "time" and d.field == "closed" and d.position == last)
    ]


def assert_matches_golden(
    golden: Sequence[Bar], actual: Sequence[Bar], what: str, *, kind: str
) -> None:
    found = diffs(golden, actual, kind=kind)
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


class GapNotMarkedError(AssertionError):
    """The first bar after an unrecovered hole is presented as complete (AC1).

    Its own type, so a strict xfail can name exactly this failure and not, say, a scenario timeout
    (`ScenarioTimeoutError` is also an `AssertionError`).
    """


def assert_gap_marked(bars: Sequence[Bar], gap: GapEvent, what: str) -> None:
    """AC1: the first bar to close after an unrecovered hole is not presented as complete."""
    after = [b for b in bars if b.close_time >= gap.end_us]
    if not after:
        # Not a GapNotMarkedError, so the strict xfail cannot pass for this reason.
        raise LookupError(f"{what}: no bar closes after the gap")
    first = after[0]
    if not (first.gap_before or first.partial):
        raise GapNotMarkedError(f"{what}: bar {first.index} hides the gap")


_ROW_COLUMNS = ("open", "high", "low", "close", "volume", "trade_count")


def row_problems(golden: Sequence[Bar], rows: Sequence[dict[str, object]]) -> list[str]:
    """What is wrong with the persisted rows of one series, against its golden (empty = right).

    Every golden bar except the still-forming tail is stored, each exactly once (the store is
    keyed by index), with the golden's OHLCV and trade count; nothing is stored that the venue
    did not print."""
    by_index: dict[int, dict[str, object]] = {}
    problems: list[str] = []
    for row in rows:
        index = int(str(row["index"]))
        if index in by_index:
            problems.append(f"bar {index} stored twice")
        by_index[index] = row
    problems += [
        f"bar {i} missing from the store" for i in range(len(golden) - 1) if i not in by_index
    ]
    for index, row in by_index.items():
        if index >= len(golden):
            problems.append(f"bar {index} stored but never printed")
            continue
        bar = golden[index]
        want = {
            "open": float(bar.open), "high": float(bar.high), "low": float(bar.low),
            "close": float(bar.close), "volume": float(bar.volume), "trade_count": bar.trade_count,
        }  # fmt: skip
        problems += [
            f"bar {index} {col}: stored {row[col]!r}, golden {want[col]!r}"
            for col in _ROW_COLUMNS
            if row[col] != want[col]
        ]
    return problems
