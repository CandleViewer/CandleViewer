"""Golden test (BI-4): recorded BTCUSDT tape -> tick and volume bars (E12-S02).

Same tape as the time-bar golden (`ws/clean_publicTrade_BTCUSDT.jsonl`, C-13.5). The recorded
day holds 542 prints / 137.534 BTC, so the ticket's `tick:500`/`vol:1000` are scaled to specs
that close several bars on this tape (`tick:50`, `tick:500`, `vol:5`, `vol:0.25`). Checked
against an independent reference split and byte-for-byte against
`packages/fixtures/golden/bars/activity_bars_BTCUSDT.jsonl` (`CV_REGEN_GOLDEN=1` rewrites it).
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from tests.unit.bars._trades import final_bars
from tests.unit.bars.test_time_builder_golden import GOLDEN as TIME_GOLDEN
from tests.unit.bars.test_time_builder_golden import _row, _tape

GOLDEN = TIME_GOLDEN.parent / "activity_bars_BTCUSDT.jsonl"
SPECS = {
    "tick:50": BarSpec(kind="tick", tick_count=50),
    "tick:500": BarSpec(kind="tick", tick_count=500),
    "vol:5": BarSpec(kind="volume", volume_threshold=Decimal("5")),
    "vol:0.25": BarSpec(kind="volume", volume_threshold=Decimal("0.25")),
}


def _build(spec: BarSpec) -> list[Bar]:
    b = (
        TickBarBuilder(spec, "BTCUSDT")
        if spec.kind == "tick"
        else VolumeBarBuilder(spec, "BTCUSDT")
    )
    out: list[BarUpdate] = []
    for t in _tape():
        out += b.on_trade(t)
    return final_bars(out, b)


def _reference_volumes(threshold: Decimal) -> list[Decimal]:
    """Independent model: chop the cumulative volume into threshold-sized pieces."""
    total = sum((t.qty for t in _tape()), Decimal(0))
    full = int(total // threshold)
    rest = total - full * threshold
    return [threshold] * full + ([rest] if rest else [])


def test_golden_volume_bars_match_reference_split() -> None:
    for spec in (SPECS["vol:5"], SPECS["vol:0.25"]):
        assert [b.volume for b in _build(spec)] == _reference_volumes(Decimal(spec.param_value))


def test_golden_tick_bars_hold_exact_trade_counts() -> None:
    n = len(_tape())
    assert [b.trade_count for b in _build(SPECS["tick:50"])] == [50] * (n // 50) + [n % 50]


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
    assert _build(SPECS["vol:5"]) == _build(SPECS["vol:5"])  # BI-4
