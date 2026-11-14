"""Golden test (BI-4): recorded BTCUSDT tape → 1m/5m/1h time bars (E12-S01).

The tape is the corpus `ws/clean_publicTrade_BTCUSDT.jsonl`, read through `tests/_corpus.py`
(the production parser, C-13.5). Bars are checked two ways:
1. OHLCV, delta, turnover and VWAP against a small, independent reference aggregation
   (group by bucket, sort).
2. Every field against `packages/fixtures/golden/bars/time_bars_BTCUSDT.jsonl`. Set
   `CV_REGEN_GOLDEN=1` to rewrite that file (review the diff).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from decimal import Decimal

import pytest

from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from tests import _corpus
from tests.unit.bars._trades import final_bars, trade

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
CORPUS = "ws/clean_publicTrade_BTCUSDT.jsonl"
GOLDEN = _corpus.CORPUS_ROOT.parent / "golden" / "bars" / "time_bars_BTCUSDT.jsonl"
SPECS = {
    "1m": BarSpec(kind="time", interval_ms=60_000),
    "5m": BarSpec(kind="time", interval_ms=300_000),
    "1h": BarSpec(kind="time", interval_ms=3_600_000),
}


def _tape() -> list[TradeEvent]:
    out: list[TradeEvent] = []
    for frame in _corpus.frames(CORPUS):
        for p in _corpus.normalize(frame):
            assert isinstance(p, TradePrint)
            out.append(trade(p.ts_event_us, p.price, p.qty, p.side, seq=len(out)))
    return out


def _build(spec: BarSpec, tape: list[TradeEvent]) -> list[Bar]:
    b = TimeBarBuilder(spec, "BTCUSDT")
    out: list[BarUpdate] = []
    for t in tape:
        out += b.on_trade(t)
        out += b.on_clock(t.ts_event)
    out += b.on_clock(tape[-1].ts_event + int(spec.param_value) * 1000)
    return final_bars(out)


def _reference_ohlcv(spec: BarSpec, tape: list[TradeEvent]) -> list[tuple[str, ...]]:
    step = int(spec.param_value) * 1000
    groups: dict[int, list[TradeEvent]] = defaultdict(list)
    for t in sorted(tape, key=lambda t: (t.ts_event, t.seq)):
        groups[t.ts_event // step * step].append(t)
    rows = []
    for start in sorted(groups):
        g = groups[start]
        px = [t.price for t in g]
        vol = sum((t.qty for t in g), Decimal(0))
        delta = sum((t.qty if t.side == "buy" else -t.qty for t in g), Decimal(0))
        turnover = sum((t.price * t.qty for t in g), Decimal(0))
        vwap = (turnover / vol).quantize(Decimal("1e-8"))
        ohlcv = (start, g[0].price, max(px), min(px), g[-1].price, vol)
        rows.append(tuple(map(str, (*ohlcv, delta, turnover, vwap))))
    return rows


def _row(b: Bar) -> dict[str, object]:
    """Every field; `tape_gap` (#5396) only when true, as the wires send it, so a golden written
    before the field existed stays byte-identical and a bar that sets it shows as a diff."""
    dumped = b.model_dump(exclude=None if b.tape_gap else {"tape_gap"})
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in dumped.items()}


@pytest.mark.parametrize("label", list(SPECS))
def test_golden_recorded_tape_matches_reference_ohlcv_delta_vwap(label: str) -> None:
    tape = _tape()
    bars = _build(SPECS[label], tape)
    fields = ("open_time", "open", "high", "low", "close", "volume", "delta", "turnover", "vwap")
    got = [tuple(str(getattr(b, f)) for f in fields) for b in bars]
    assert got == _reference_ohlcv(SPECS[label], tape)
    assert all(b.closed for b in bars)


def test_golden_recorded_tape_matches_committed_bars_byte_for_byte() -> None:
    tape = _tape()
    lines = [
        json.dumps({"spec": label, **_row(b)}, sort_keys=True, separators=(",", ":"))
        for label, spec in SPECS.items()
        for b in _build(spec, tape)
    ]
    text = "\n".join(lines) + "\n"
    if os.environ.get("CV_REGEN_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    assert GOLDEN.read_text(encoding="utf-8") == text
    assert _build(SPECS["1m"], tape) == _build(SPECS["1m"], _tape())  # BI-4
