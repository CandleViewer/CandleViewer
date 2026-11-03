"""E12-Q02 seeded mutations: each defect is injected only here (monkeypatch/wrapper) and must make
the golden conformance comparison fail, naming the first divergent bar and the triggering trade.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from bench.bar_conformance import runner as cf
from bench.bar_determinism import tapes
from candleviewer.bars import activity_builders as ab
from candleviewer.bars.models import BarUpdate
from candleviewer.exchange.base.models import TradeEvent

TAPE = "edge-ticks"


def _check(label: str) -> str:
    spec = cf.live_cases()[label]
    tape = tapes.read_tape(TAPE)
    got = cf.run(tape, "BTCUSDT")[label]
    return cf.explain(spec, "BTCUSDT", tape, cf.read_golden(TAPE, label), cf.lines(got))


def test_clean_builders_pass_on_the_edge_tape() -> None:
    assert _check("vol:50") == ""


def test_mutant_volume_closes_at_ge_instead_of_gt_names_bar_and_trade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off-by-one boundary: an exact fill is treated as an overshoot (`rem >= room`)."""
    real = ab.VolumeBarBuilder.on_trade

    def mutant(self: ab.VolumeBarBuilder, t: TradeEvent) -> Sequence[BarUpdate]:
        if t.qty + self._cur_volume() == self._quota:  # type: ignore[attr-defined]
            t = t.model_copy(update={"qty": t.qty + Decimal("0.001")})  # exact fill overshoots
        return real(self, t)

    monkeypatch.setattr(ab.VolumeBarBuilder, "_cur_volume", _cur, raising=False)
    monkeypatch.setattr(ab.VolumeBarBuilder, "on_trade", mutant)
    msg = _check("vol:50")
    assert "first divergence: bar " in msg and "field " in msg and "triggering trade #" in msg


def _cur(self: ab.VolumeBarBuilder) -> Decimal:
    d = self._cur
    return Decimal(0) if d is None else d.buy + d.sell


def test_mutant_dropped_overshoot_split_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The overshoot remainder is thrown away instead of opening the next bar."""
    real = ab.VolumeBarBuilder.on_trade

    def mutant(self: ab.VolumeBarBuilder, t: TradeEvent) -> Sequence[BarUpdate]:
        room = self._quota - _cur(self)
        if t.qty > room:
            t = t.model_copy(update={"qty": room})
        return real(self, t)

    monkeypatch.setattr(ab.VolumeBarBuilder, "on_trade", mutant)
    assert "first divergence" in _check("vol:50")


def test_mutant_swapped_high_low_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    from candleviewer.bars.threshold_builders import RangeBarBuilder

    real = RangeBarBuilder.on_trade

    def mutant(self: RangeBarBuilder, t: TradeEvent) -> Sequence[BarUpdate]:
        out = real(self, t)
        return [
            (
                u.model_copy(
                    update={"bar": u.bar.model_copy(update={"high": u.bar.low, "low": u.bar.high})}
                )
                if u.kind == "close"
                else u
            )
            for u in out
        ]

    monkeypatch.setattr(RangeBarBuilder, "on_trade", mutant)
    msg = _check("range:20")
    assert "first divergence: bar " in msg
    assert "field high" in msg or "field low" in msg


def test_mutant_range_jump_gt_instead_of_ge_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off-by-one jump boundary: a close at exactly 2 x width is not flagged (`>` not `>=`)."""
    from candleviewer.bars.threshold_builders import RangeBarBuilder

    real = RangeBarBuilder.on_trade

    def mutant(self: RangeBarBuilder, t: TradeEvent) -> Sequence[BarUpdate]:
        out = real(self, t)
        if any(u.kind == "close" and u.bar.high - u.bar.low == self._two_widths for u in out):
            self._gap = False  # the exact-2x close is not a jump under `>`
        return out

    monkeypatch.setattr(RangeBarBuilder, "on_trade", mutant)
    msg = _check("range:20")
    assert "first divergence: bar 28" in msg and "field gap_before" in msg
