"""E12-T06 slice C (#399): `bars` wire forms, `23-ws-protocol.md` §3.4 kind 4 and §14.3."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.ws.bars_wire import (
    MAX_TS_SPAN_MS,
    bar_item,
    bar_record,
    bars_frames,
)
from candleviewer.ws.binary import BARS, decode, encode
from candleviewer.ws.cvwb_vectors import structured
from tests.contract.ws._harness import check_schema

SPEC = BarSpec(kind="time", interval_ms=300_000)
T0_US = 1_700_000_000_000_000
DAY_US = 86_400_000_000


def _bar(**kw: object) -> Bar:
    base = dict(
        spec_hash=SPEC.spec_hash, symbol="BTCUSDT", index=3, open_time=T0_US,
        close_time=T0_US + 299_999_999, open=Decimal("100.1"), high=Decimal("101"),
        low=Decimal("99.5"), close=Decimal("100.5"), volume=Decimal("10"),
        buy_volume=Decimal("6"), sell_volume=Decimal("4"), delta=Decimal("2"),
        min_delta=Decimal("-1"), max_delta=Decimal("3"), trade_count=7, turnover=Decimal("1001"),
        vwap=Decimal("100.3"), closed=True, partial=False, gap_before=False,
    )  # fmt: skip
    base.update(kw)
    return Bar.model_validate(base)


def _batch(*items: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": "BTCUSDT", "bar_type": "time", "param": "5", "bars": list(items)}


def test_bar_item_is_the_section_14_3_item_of_a_closed_time_bar() -> None:
    item = bar_item(_bar(), generation=2, bar_kind="time", include_delta=False)
    assert item == {
        "generation": 2, "index": 3, "t_ms": T0_US // 1000, "o": "100.1", "h": "101",
        "l": "99.5", "c": "100.5", "v": "10", "turnover": "1001", "trades": 7, "confirm": True,
    }  # fmt: skip
    check_schema("cv://ws/v1/bars.schema.json", _batch(item), "bars batch")


def test_bar_item_flags_the_forming_bar_and_an_amended_close() -> None:
    forming = bar_item(_bar(closed=False), generation=0, bar_kind="time", include_delta=False)
    amended = bar_item(_bar(), generation=0, bar_kind="time", include_delta=False, amended=True)
    assert (forming["confirm"], "amended" in forming) == (False, False)
    assert (amended["confirm"], amended["amended"]) == (True, True)
    check_schema("cv://ws/v1/bars.schema.json", _batch(forming, amended), "bars batch")


def test_bar_item_adds_the_order_flow_fields_only_with_include_delta() -> None:
    plain = bar_item(_bar(), generation=0, bar_kind="time", include_delta=False)
    flow = bar_item(_bar(), generation=0, bar_kind="time", include_delta=True)
    assert not {"delta", "min_delta", "max_delta", "cvd"} & set(plain)
    assert (flow["delta"], flow["min_delta"], flow["max_delta"]) == ("2", "-1", "3")
    assert "cvd" not in flow  # a series running sum; never from a single bar
    check_schema("cv://ws/v1/bars.schema.json", _batch(flow), "bars batch")


@pytest.mark.parametrize(("kind", "has_close"), [("time", False), ("heikin_ashi", False),
                                                 ("tick", True), ("renko", True)])  # fmt: skip
def test_bar_item_sends_close_t_ms_for_non_time_bars(kind: str, has_close: bool) -> None:
    item = bar_item(_bar(), generation=0, bar_kind=kind, include_delta=False)
    assert ("close_t_ms" in item) is has_close
    if has_close:
        assert item["close_t_ms"] == (T0_US + 299_999_999) // 1000


def test_bar_item_never_writes_an_exponent() -> None:
    bar = _bar(volume=Decimal("1E+2"), buy_volume=Decimal("60"), sell_volume=Decimal("40"),
               turnover=Decimal("0E-8"))  # fmt: skip
    item = bar_item(bar, generation=0, bar_kind="time", include_delta=False)
    assert (item["v"], item["turnover"]) == ("100", "0.00000000")
    check_schema("cv://ws/v1/bars.schema.json", _batch(item), "bars batch")


@pytest.mark.parametrize("include_delta", [False, True])
def test_kind_4_round_trip_matches_the_structured_item(include_delta: bool) -> None:
    """Binary and structured forms agree (§16.4), field by field, as decimals."""
    bars = [_bar(index=3), _bar(index=4, open_time=T0_US + 300_000_000, closed=False,
                                delta=Decimal("-0.5"), min_delta=Decimal("-1"))]  # fmt: skip
    (frame,) = bars_frames(
        bars, generation=1, include_delta=include_delta, price_scale=1, qty_scale=3
    )
    decoded = structured(decode(encode(frame)))["bars"]
    for bar, got in zip(bars, decoded, strict=True):
        want = bar_item(bar, generation=1, bar_kind="time", include_delta=include_delta)
        for key in ("generation", "index", "t_ms", "trades", "confirm"):
            assert got[key] == want[key], key
        for key in ("o", "h", "l", "c", "v", "turnover"):
            assert Decimal(got[key]) == Decimal(want[key]), key
        assert Decimal(got["delta"]) == (bar.delta if include_delta else 0)


def test_kind_4_scales_round_half_even_and_keep_signs() -> None:
    bar = _bar(turnover=Decimal("1001.0005"), delta=Decimal("-2.25"), min_delta=Decimal("-3"))
    record = bar_record(
        bar, generation=0, include_delta=True, price_scale=1, qty_scale=3, ts_base_ms=0
    )
    assert record[8] == 1_001_000  # turnover 1001.0005 at 3 places: half-even rounds down
    assert record[10] == -2_250  # delta is signed
    assert record[3:7] == (1_001, 1_010, 995, 1_005)  # o, h, l, c at price_scale 1


def test_bars_frames_start_a_new_frame_past_the_u32_offset_span() -> None:
    """1 000 daily bars span ~1 000 days, far past `ts_offset_ms`'s ~49.7 days."""
    bars = [
        _bar(index=i, open_time=T0_US + i * DAY_US, close_time=T0_US + (i + 1) * DAY_US - 1)
        for i in range(120)
    ]
    frames = bars_frames(bars, generation=0, include_delta=False, price_scale=1, qty_scale=3)
    assert len(frames) == 3  # 50 + 50 + 20 days at most 49.7 days after each base
    assert sum(len(f.records) for f in frames) == 120
    for frame in frames:
        assert frame.body_kind == BARS
        assert all(0 <= r[2] <= MAX_TS_SPAN_MS for r in frame.records)
        decode(encode(frame))  # every frame is encodable on its own
    starts = [f.ts_base_ms for f in frames]
    assert starts == sorted(starts) and starts[0] == T0_US // 1000


def test_bars_frames_of_nothing_is_no_frame() -> None:
    assert bars_frames([], generation=0, include_delta=False, price_scale=1, qty_scale=3) == ()


def test_bars_frames_never_encode_a_negative_offset() -> None:
    """A bar opening before the current frame's base starts its own frame (u32 offsets)."""
    late, early = _bar(index=4, open_time=T0_US + DAY_US), _bar(index=5, open_time=T0_US)
    frames = bars_frames([late, early], generation=0, include_delta=False, price_scale=1,
                         qty_scale=3)  # fmt: skip
    assert [f.ts_base_ms for f in frames] == [(T0_US + DAY_US) // 1000, T0_US // 1000]
    assert [decode(encode(f)).records[0][2] for f in frames] == [0, 0]
