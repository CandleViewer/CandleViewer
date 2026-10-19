"""Renko builder (E12-S04): Gherkin scenarios, edge cases and snapshot/restore."""

from __future__ import annotations

from decimal import Decimal as D

import orjson
import pytest
from pydantic import ValidationError

from candleviewer.bars.builder_set import default_factory, renko_factory
from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.models import Bar, BarSpec, BarUpdate, BuilderState
from candleviewer.bars.renko_builder import RenkoBarBuilder, RenkoBarUpdate
from candleviewer.bars.series import layout, require_time_aligned
from candleviewer.bars.spec import RENKO_ATR_DEFERRED, from_wire
from tests.unit.bars._trades import SYM, closes, final_bars, trade


def _renko(ticks: int = 10, tick: str = "0.10", **kw: object) -> RenkoBarBuilder:
    spec = BarSpec.model_validate({"kind": "renko", "range_ticks": ticks} | kw)
    return RenkoBarBuilder(spec, SYM, lambda _s: D(tick))


def _feed(b: RenkoBarBuilder, pxs: list[str], qty: str = "1") -> list[BarUpdate]:
    out: list[BarUpdate] = []
    for i, p in enumerate(pxs):
        out += b.on_trade(trade(1_000 + i, p, qty, seq=i))
    return out


def _oc(bars: list[Bar]) -> list[tuple[str, str]]:
    return [(str(b.open), str(b.close)) for b in bars]


# --- Scenario: A brick forms on a full move -------------------------------------------------


def test_renko_full_move_emits_one_up_brick_closing_at_target() -> None:
    b = _renko()
    ups = _feed(b, ["100.00", "100.50", "100.99"])
    assert closes(ups) == []
    ups = _feed(b, ["101.00"])
    assert [u.kind for u in ups] == ["close"]
    assert _oc(closes(ups)) == [("100.00", "101.00")]


# --- Scenario: Reversal costs two bricks ----------------------------------------------------


def test_renko_reversal_one_brick_short_emits_nothing_then_two_bricks_reverse() -> None:
    b = _renko()
    _feed(b, ["100.00", "101.00"])  # up brick, last close 101.00
    assert closes(_feed(b, ["100.10"])) == []
    assert closes(_feed(b, ["100.00"])) == []  # exactly one brick against the trend
    got = closes(_feed(b, ["99.00"]))
    assert _oc(got) == [("100.00", "99.00")]  # opens at the previous brick's open


@pytest.mark.parametrize("rev", [1, 3])
def test_renko_reversal_cost_follows_reversal_bricks(rev: int) -> None:
    b = _renko(reversal_bricks=rev)
    _feed(b, ["100", "101"])
    assert closes(_feed(b, [f"{101 - rev + 1}"])) == []  # one brick short of the cost
    got = closes(_feed(b, [f"{101 - rev}"]))
    assert _oc(got)[-1] == (f"{D(101 - rev + 1):.2f}", f"{D(101 - rev):.2f}")


def test_renko_continuation_in_trend_needs_one_brick() -> None:
    b = _renko()
    _feed(b, ["100", "99"])  # first move down sets the direction
    assert _oc(closes(_feed(b, ["98"]))) == [("99.00", "98.00")]


# --- Scenario: One trade moving N bricks allocates volume once ------------------------------


def test_renko_one_trade_three_bricks_single_volume_allocation() -> None:
    b = _renko()
    pre = _feed(b, ["100.00", "100.40"], qty="2")
    ups = b.on_trade(trade(5_000, "103.05", "7", seq=9))
    assert all(isinstance(u, RenkoBarUpdate) for u in ups)
    bricks = [u.bar for u in ups]
    assert [u.kind for u in ups] == ["close"] * 3
    assert len({(x.open_time, x.close_time) for x in bricks}) == 1
    assert [x.index for x in bricks] == [0, 1, 2]
    flags = [u.volume_allocated for u in ups if isinstance(u, RenkoBarUpdate)]
    assert flags == [False, False, True]
    assert [x.volume for x in bricks] == [0, 0, D(11)]
    assert {u.open_source_ts for u in ups if isinstance(u, RenkoBarUpdate)} == {1_000}
    assert sum(x.volume for x in final_bars(pre + list(ups))) == D(11)  # BI-1


# --- Scenario: Wicks are opt-in --------------------------------------------------------------


def test_renko_without_wick_high_low_are_brick_bounds() -> None:
    bars = closes(_feed(_renko(), ["100", "99.5", "101.3", "102.4", "101"]))
    assert bars
    for x in bars:
        assert (x.high, x.low) == (max(x.open, x.close), min(x.open, x.close))


def test_renko_with_wick_records_extremes_while_forming() -> None:
    bars = closes(_feed(_renko(renko_wick=True), ["100", "99.5", "101.3"]))
    assert len(bars) == 1
    assert (bars[0].low, bars[0].high) == (D("99.5"), D("101.3"))


def test_renko_wick_down_brick_and_forming_update() -> None:
    b = _renko(renko_wick=True)
    ups = _feed(b, ["100", "100.4", "98.8"])
    (x,) = closes(ups)
    assert (x.open, x.close, x.high, x.low) == (D(100), D(99), D("100.4"), D("98.8"))
    assert ups[0].kind == "open" and ups[1].kind == "update" and not ups[1].bar.closed


# --- Scenario: Time-based indicators are refused, not silently wrong -------------------------


def test_renko_series_layout_is_index_spaced_and_time_indicators_refused() -> None:
    spec = BarSpec(kind="renko", range_ticks=10)
    meta = layout(spec)
    assert (meta.is_time_aligned, meta.spacing) == (False, "index")
    with pytest.raises(BarsError, match="renko bars have no fixed time width"):
        require_time_aligned(spec, "VWAP session")
    t = BarSpec(kind="time", interval_ms=60_000)
    assert layout(t).is_time_aligned and layout(t).spacing == "time"
    require_time_aligned(t, "VWAP session")
    assert not layout(BarSpec(kind="tick", tick_count=100)).is_time_aligned


# --- Scenario: ATR bricks follow the ADR (ADR-0033: deferred, 422) ----------------------------


@pytest.mark.parametrize("param", ["atr:14", "atr:2", "atr:100", "atr:14:150"])
def test_renko_atr_param_rejected_with_reason_and_alternative(param: str) -> None:
    with pytest.raises(BarSpecError) as e:
        from_wire("renko", param)
    assert str(e.value) == RENKO_ATR_DEFERRED
    assert "brick size in ticks" in str(e.value)


@pytest.mark.parametrize("param", ["atr:1", "atr:101", "atr:", "atr:14:0", "ATR:14", "atr:014"])
def test_renko_malformed_atr_is_an_ordinary_invalid_param(param: str) -> None:
    with pytest.raises(BarSpecError, match="positive whole number"):
        from_wire("renko", param)


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("param", ["atr:14", "atr:14:150"])
def test_renko_atr_param_ending_in_a_newline_falls_through_and_is_refused(
    param: str, tail: str
) -> None:
    """#3555: `$` also matches before a final newline, so `match` took it as the deferred ATR
    form. Outside the pattern it falls through to the whole-number check, which refuses it."""
    with pytest.raises(BarSpecError) as e:
        from_wire("renko", param)
    assert str(e.value) == RENKO_ATR_DEFERRED
    with pytest.raises(BarSpecError, match="positive whole number"):
        from_wire("renko", param + tail)


# --- Spec bounds (security note) and construction ---------------------------------------------


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"range_ticks": 1}, "between 2 and 100000"),
        ({"range_ticks": 100_001}, "between 2 and 100000"),
        ({"range_ticks": 10, "reversal_bricks": 11}, "at most 10"),
    ],
)
def test_renko_spec_bounds_rejected(kw: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):  # rejected at BarSpec, before any builder
        _renko(**kw)


def test_renko_builder_rechecks_bounds_defence_in_depth() -> None:
    spec = BarSpec.model_construct(kind="renko", range_ticks=1, reversal_bricks=2)
    with pytest.raises(BarSpecError, match="between 2 and 100000"):
        RenkoBarBuilder(spec, SYM, lambda _s: D("0.1"))


def test_renko_one_trade_over_brick_cap_raises() -> None:
    b = _renko(ticks=2, tick="0.01")
    b.on_trade(trade(1, "100", seq=1))
    with pytest.raises(BarsError, match="cap 1000"):
        b.on_trade(trade(2, "10100", seq=2))  # 1e6 ticks in one print
    assert closes(b.on_trade(trade(3, "120", seq=3)))  # 1000 bricks exactly: allowed


def test_renko_mark_price_source_refused() -> None:
    with pytest.raises(BarSpecError, match="mark price"):
        _renko(price_source="mark")


def test_renko_rejects_wrong_kind_unknown_tick_and_foreign_symbol() -> None:
    with pytest.raises(BarSpecError, match="kind 'renko'"):
        RenkoBarBuilder(BarSpec(kind="range", range_ticks=10), SYM, lambda _s: D(1))
    with pytest.raises(BarSpecError, match="No tick size"):
        _renko(tick="0")
    with pytest.raises(BarSpecError, match="No tick size"):
        RenkoBarBuilder(BarSpec(kind="renko", range_ticks=10), SYM, lambda _s: None)
    t = trade(1, "100").model_copy(update={"symbol": "ETHUSDT"})
    with pytest.raises(BarsError, match="ETHUSDT"):
        _renko().on_trade(t)
    assert _renko().on_clock(10**12) == ()


def test_renko_factory_is_composed_only_behind_the_flag() -> None:
    spec = BarSpec(kind="renko", range_ticks=10)
    with pytest.raises(BarSpecError, match="not available yet"):
        default_factory(spec, SYM)
    make = renko_factory(lambda _s: D("0.1"))
    assert isinstance(make(spec, SYM), RenkoBarBuilder)
    assert make(BarSpec(kind="tick", tick_count=100), SYM).spec.kind == "tick"


# --- Direction state and snapshot/restore ------------------------------------------------------


def test_renko_restore_preserves_direction_for_the_next_reversal() -> None:
    a = _renko()
    _feed(a, ["100", "101", "100.5"])
    b = _renko()
    b.restore(a.snapshot())
    assert b.snapshot() == a.snapshot()
    assert closes(b.on_trade(trade(9, "100", seq=9))) == []  # still costs 2 bricks
    assert _oc(closes(b.on_trade(trade(10, "99", seq=10)))) == [("100.00", "99.00")]


def _state(b: RenkoBarBuilder, **patch: object) -> BuilderState:
    s = b.snapshot()
    doc = orjson.loads(s.blob)
    doc.update(patch)
    doc = {k: v for k, v in doc.items() if v != "DROP"}
    return s.model_copy(update={"blob": orjson.dumps(doc)})


def test_renko_restore_refusals() -> None:
    a = _renko()
    _feed(a, ["100"])
    with pytest.raises(BarsError, match="incomplete"):
        _renko().restore(_state(a, dir="DROP"))
    with pytest.raises(BarsError, match="corrupt"):
        _renko().restore(a.snapshot().model_copy(update={"blob": b"{not json"}))
    with pytest.raises(BarsError, match="corrupt"):
        _renko().restore(_state(a, width="x"))
    with pytest.raises(BarsError, match="invalid direction"):
        _renko().restore(_state(a, dir=2))
    with pytest.raises(BarsError, match="new epoch"):
        _renko(tick="0.5").restore(a.snapshot())  # tick-size change (ADR-0033)
    with pytest.raises(BarsError, match="version"):
        _renko().restore(a.snapshot().model_copy(update={"state_version": 9}))
    with pytest.raises(BarsError, match="different"):
        _renko(ticks=20).restore(a.snapshot())
    fresh = _renko()
    fresh.restore(_renko().snapshot())  # empty state round-trips
    assert fresh.snapshot() == _renko().snapshot()
