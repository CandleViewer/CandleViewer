"""Golden test (BI-4): recorded BTCUSDT tape -> range and delta bars (E12-S03).

Same tape as the time/activity goldens (`ws/clean_publicTrade_BTCUSDT.jsonl`, C-13.5): 542 prints,
63120.30..63127.60, net delta +4.986 BTC. `range:20` (tick 0.10, width 2.00) is the ticket's value
and yields 9 bars; the ticket's `delta:500` would give ONE bar on a 137 BTC day, so delta is scaled
to `delta:1` (39 bars) and `delta:2` (11 bars). Checked against an independent reference and
byte-for-byte against `packages/fixtures/golden/bars/threshold_bars_BTCUSDT.jsonl`
(`CV_REGEN_GOLDEN=1` rewrites it).
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from tests.unit.bars._trades import final_bars
from tests.unit.bars.test_time_builder_golden import GOLDEN as TIME_GOLDEN
from tests.unit.bars.test_time_builder_golden import _row, _tape

GOLDEN = TIME_GOLDEN.parent / "threshold_bars_BTCUSDT.jsonl"
TICK = Decimal("0.10")
SPECS = {
    "range:20": BarSpec(kind="range", range_ticks=20),
    "delta:1": BarSpec(kind="delta", delta_threshold=Decimal(1)),
    "delta:2": BarSpec(kind="delta", delta_threshold=Decimal(2)),
}


def _build(spec: BarSpec) -> list[Bar]:
    b = (
        RangeBarBuilder(spec, "BTCUSDT", lambda _s: TICK)
        if spec.kind == "range"
        else DeltaBarBuilder(spec, "BTCUSDT")
    )
    out: list[BarUpdate] = []
    for t in _tape():
        out += b.on_trade(t)
    return final_bars(out, b)


def _reference_range(width: Decimal) -> list[tuple[int, Decimal, Decimal]]:
    """Independent model: (trades, volume, high-low) per bar by a plain scan."""
    bars: list[tuple[int, Decimal, Decimal]] = []
    lo = hi = Decimal(0)
    n, vol = 0, Decimal(0)
    for t in _tape():
        lo, hi = (t.price, t.price) if n == 0 else (min(lo, t.price), max(hi, t.price))
        n, vol = n + 1, vol + t.qty
        if hi - lo >= width:
            bars.append((n, vol, hi - lo))
            n, vol = 0, Decimal(0)
    if n:
        bars.append((n, vol, hi - lo))
    return bars


def _reference_delta(thr: Decimal) -> list[tuple[int, Decimal]]:
    bars: list[tuple[int, Decimal]] = []
    n, delta = 0, Decimal(0)
    for t in _tape():
        n, delta = n + 1, delta + (t.qty if t.side == "buy" else -t.qty)
        if abs(delta) >= thr:
            bars.append((n, delta))
            n, delta = 0, Decimal(0)
    if n:
        bars.append((n, delta))
    return bars


def test_golden_range_bars_match_reference_and_have_no_phantoms() -> None:
    bars = _build(SPECS["range:20"])
    ref = _reference_range(Decimal("2.0"))
    assert [(b.trade_count, b.volume, b.high - b.low) for b in bars] == ref
    assert len(bars) == 9
    assert all(b.trade_count >= 1 for b in bars)
    assert sum(b.volume for b in bars) == sum(t.qty for t in _tape())  # BI-1


def test_golden_delta_bars_match_reference_without_splitting() -> None:
    for label in ("delta:1", "delta:2"):
        bars = _build(SPECS[label])
        assert [(b.trade_count, b.delta) for b in bars] == _reference_delta(
            Decimal(SPECS[label].param_value)
        )
        assert sum(b.trade_count for b in bars) == len(_tape())  # whole trades only
        assert sum(b.volume for b in bars) == sum(t.qty for t in _tape())


def test_golden_recorded_tape_matches_committed_bars_byte_for_byte() -> None:
    lines = [
        json.dumps({"spec": label, **_row(b)}, sort_keys=True, separators=(",", ":"))
        for label, spec in SPECS.items()
        for b in _build(spec)
    ]
    text = "\n".join(lines) + "\n"
    if os.environ.get("CV_REGEN_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    assert GOLDEN.read_text(encoding="utf-8") == text
    assert _build(SPECS["range:20"]) == _build(SPECS["range:20"])  # BI-4
