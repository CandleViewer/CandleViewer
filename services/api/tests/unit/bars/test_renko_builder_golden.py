"""Golden test (BI-4): recorded BTCUSDT tape -> `renko:10` bricks (E12-S04).

Same tape as the other bar goldens (`ws/clean_publicTrade_BTCUSDT.jsonl`, C-13.5), tick 0.10, so a
brick is 1.00. The builder is checked against `_reference`, an independent pure-Python model
written here: it works in integer ticks, keeps only (anchor, direction) and re-derives each brick
from the definition (24 §3.3) with no `Decimal` brick arithmetic, no draft and no shared helper.
Output is byte-compared with `packages/fixtures/golden/bars/renko_bars_BTCUSDT.jsonl`
(`CV_REGEN_GOLDEN=1` rewrites it).
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.renko_builder import RenkoBarBuilder, RenkoBarUpdate
from tests.unit.bars._trades import final_bars
from tests.unit.bars.test_time_builder_golden import GOLDEN as TIME_GOLDEN
from tests.unit.bars.test_time_builder_golden import _row, _tape

GOLDEN = TIME_GOLDEN.parent / "renko_bars_BTCUSDT.jsonl"
TICK = Decimal("0.10")
SPECS = {
    "renko:10": BarSpec(kind="renko", range_ticks=10),
    "renko:10:wick:rev3": BarSpec(kind="renko", range_ticks=10, renko_wick=True, reversal_bricks=3),
}


def _build(spec: BarSpec) -> tuple[list[Bar], list[BarUpdate]]:
    b = RenkoBarBuilder(spec, "BTCUSDT", lambda _s: TICK)
    out: list[BarUpdate] = []
    for t in _tape():
        out += b.on_trade(t)
    return final_bars(out, b), out


def _reference(n: int, rev: int) -> list[tuple[int, int, int, Decimal]]:
    """(open_ticks, close_ticks, trades, volume) per closed brick; volume on the run's last."""
    anchor: int | None = None
    direction = 0
    trades, vol = 0, Decimal(0)
    out: list[tuple[int, int, int, Decimal]] = []
    for t in _tape():
        p = int(t.price / TICK)
        anchor = p if anchor is None else anchor
        trades, vol = trades + 1, vol + t.qty
        moved = (p - anchor) // n if p >= anchor else -((anchor - p) // n)
        if moved == 0:
            continue
        sgn = 1 if moved > 0 else -1
        k = abs(moved)
        if direction == -sgn:
            if k < rev:
                continue
            anchor, k = anchor + sgn * (rev - 1) * n, k - (rev - 1)
        for i in range(k):
            o = anchor + sgn * i * n
            last = i == k - 1
            out.append((o, o + sgn * n, trades if last else 0, vol if last else Decimal(0)))
        anchor, direction = anchor + sgn * k * n, sgn
        trades, vol = 0, Decimal(0)
    return out


def test_golden_renko_matches_reference() -> None:
    for spec in SPECS.values():
        bars, ups = _build(spec)
        got = [
            (int(b.open / TICK), int(b.close / TICK), b.trade_count, b.volume)
            for b in bars
            if b.closed
        ]
        assert got == _reference(10, spec.reversal_bricks)
        assert len(got) >= 3
        assert sum(b.volume for b in bars) == sum(t.qty for t in _tape())  # BI-1
        owners = [u.bar.index for u in ups if isinstance(u, RenkoBarUpdate) and u.volume_allocated]
        assert all(b.volume == 0 for b in bars if b.closed and b.index not in owners)


def test_golden_renko_matches_committed_bricks_byte_for_byte() -> None:
    lines = [
        json.dumps({"spec": label, **_row(b)}, sort_keys=True, separators=(",", ":"))
        for label, spec in SPECS.items()
        for b in _build(spec)[0]
    ]
    text = "\n".join(lines) + "\n"
    if os.environ.get("CV_REGEN_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    assert GOLDEN.read_text(encoding="utf-8") == text
    assert _build(SPECS["renko:10"])[0] == _build(SPECS["renko:10"])[0]  # BI-4


# TODO(#2131): QuestDB integration test (`@pytest.mark.integration`, tests/integration/bars/) that
# writes one multi-brick run and asserts all N same-ts bricks survive, once migration 0004 lands.
