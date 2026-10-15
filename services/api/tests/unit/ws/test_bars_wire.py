"""E12-T06 slice C (#399): `bars` wire forms, `23-ws-protocol.md` §3.4 kind 4 and §14.3."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from itertools import accumulate
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.spec import WireBarType
from candleviewer.ws.bars_wire import (
    MAX_TS_SPAN_MS,
    bar_item,
    bar_record,
    bars_frames,
    covering_scales,
)
from candleviewer.ws.binary import BARS, Frame, FrameEncodeError, decode, encode
from candleviewer.ws.cvwb_vectors import structured

SPEC = BarSpec(kind="time", interval_ms=300_000)
T0_US = 1_700_000_000_000_000
T0_MS = 1_700_000_000_000
DAY_US = 86_400_000_000
_SCHEMAS: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[5] / "docs/plan/ws-schema.json").read_text(encoding="utf-8")
)["schemas"]
#: §14.3 straight from the schema bundle: a unit test stays off the contract harness.
_BATCH = Draft202012Validator(
    _SCHEMAS["cv://ws/v1/bars.schema.json"],
    registry=Registry().with_resources((k, Resource.from_contents(v)) for k, v in _SCHEMAS.items()),
)


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


def _invalid(*items: dict[str, Any], bar_type: str = "time") -> list[str]:
    batch = {"symbol": "BTCUSDT", "bar_type": bar_type, "param": "5", "bars": list(items)}
    return [e.message for e in _BATCH.iter_errors(batch)]


def _record(bar: Bar, *, include_delta: bool = True, ts_base_ms: int = T0_MS) -> tuple[int, ...]:
    return bar_record(
        bar,
        generation=0,
        include_delta=include_delta,
        price_scale=1,
        qty_scale=3,
        ts_base_ms=ts_base_ms,
    )


def _frames(bars: list[Bar], **scales: int) -> tuple[Frame, ...]:
    scales = {"price_scale": 1, "qty_scale": 3, **scales}
    return bars_frames(bars, generation=0, include_delta=False, **scales)


def test_bar_item_is_the_section_14_3_item_of_a_closed_time_bar() -> None:
    item = bar_item(_bar(), generation=2, bar_kind="time", include_delta=False)
    assert item == {
        "generation": 2, "index": 3, "t_ms": T0_MS, "o": "100.1", "h": "101",
        "l": "99.5", "c": "100.5", "v": "10", "turnover": "1001", "trades": 7, "confirm": True,
    }  # fmt: skip
    assert _invalid(item) == []


def test_bar_item_flags_the_forming_bar_and_an_amended_close() -> None:
    forming = bar_item(_bar(closed=False), generation=0, bar_kind="time", include_delta=False)
    amended = bar_item(_bar(), generation=0, bar_kind="time", include_delta=False, amended=True)
    assert (forming["confirm"], "amended" in forming) == (False, False)
    assert (amended["confirm"], amended["amended"]) == (True, True)
    assert _invalid(forming, amended) == []


def test_bar_item_refuses_an_amended_forming_bar() -> None:
    """§8.2: `amended` marks a confirmed update; builders amend only a close."""
    with pytest.raises(FrameEncodeError, match=r"bars \(0, 3\): only a closed bar"):
        bar_item(_bar(closed=False), generation=0, bar_kind="time", include_delta=False,
                 amended=True)  # fmt: skip


def test_bar_item_adds_the_order_flow_fields_only_with_include_delta() -> None:
    plain = bar_item(_bar(), generation=0, bar_kind="time", include_delta=False)
    flow = bar_item(_bar(), generation=0, bar_kind="time", include_delta=True)
    assert not {"delta", "min_delta", "max_delta", "cvd"} & set(plain)
    assert (flow["delta"], flow["min_delta"], flow["max_delta"]) == ("2", "-1", "3")
    assert "cvd" not in flow  # a series running sum; never from a single bar
    assert _invalid(flow) == []


@pytest.mark.parametrize(
    ("kind", "close_t_ms"),
    [("time", None), ("heikin_ashi", None), ("tick", 1_700_000_299_999),
     ("renko", 1_700_000_299_999)],
)  # fmt: skip
def test_bar_item_sends_close_t_ms_for_non_time_bars(
    kind: WireBarType, close_t_ms: int | None
) -> None:
    item = bar_item(_bar(), generation=0, bar_kind=kind, include_delta=False)
    assert item.get("close_t_ms") == close_t_ms
    assert _invalid(item, bar_type=kind) == []


def test_bar_item_never_writes_an_exponent_or_a_negative_zero() -> None:
    bar = _bar(volume=Decimal("1E+2"), buy_volume=Decimal("60"), sell_volume=Decimal("40"),
               turnover=Decimal("0E-8"), delta=Decimal("-0.0"))  # fmt: skip
    item = bar_item(bar, generation=0, bar_kind="time", include_delta=True)
    assert (item["v"], item["turnover"], item["delta"]) == ("100", "0.00000000", "0.0")
    assert _invalid(item) == []


def test_both_forms_floor_a_microsecond_open_time_to_the_millisecond() -> None:
    bar = _bar(open_time=T0_US + 999)
    assert bar_item(bar, generation=0, bar_kind="time", include_delta=False)["t_ms"] == T0_MS
    assert _record(bar, ts_base_ms=T0_MS)[2] == 0
    assert _frames([bar])[0].ts_base_ms == T0_MS


@pytest.mark.parametrize("include_delta", [False, True])
def test_kind_4_round_trip_matches_the_structured_item(include_delta: bool) -> None:
    """Binary and structured forms agree (§16.4), field by field, as decimals."""
    bars = [_bar(index=3), _bar(index=4, open_time=T0_US + 300_000_000, closed=False,
                                delta=Decimal("-0.5"), min_delta=Decimal("-1"))]  # fmt: skip
    (frame,) = bars_frames(
        bars, generation=1, include_delta=include_delta, price_scale=1, qty_scale=3
    )
    numeric = ("o", "h", "l", "c", "v", "turnover")
    exact = ("generation", "index", "t_ms", "trades", "confirm")
    wants = [
        bar_item(bar, generation=1, bar_kind="time", include_delta=include_delta) for bar in bars
    ]
    gots = structured(decode(encode(frame)))["bars"]
    assert [[g[k] for k in exact] for g in gots] == [[w[k] for k in exact] for w in wants]
    assert [[Decimal(g[k]) for k in numeric] for g in gots] == [
        [Decimal(w[k]) for k in numeric] for w in wants
    ]
    assert [Decimal(g["delta"]) for g in gots] == [Decimal(w.get("delta", 0)) for w in wants]


@pytest.mark.parametrize(
    ("turnover", "scaled"), [(Decimal("1001.0005"), 1_001_000), (Decimal("1001.0015"), 1_001_002)]
)
def test_kind_4_rounds_turnover_half_even(turnover: Decimal, scaled: int) -> None:
    """Price x qty has more places than qty: ties go to the even neighbour, both directions."""
    assert _record(_bar(turnover=turnover))[8] == scaled


def test_kind_4_scales_prices_and_sizes_and_keeps_signs() -> None:
    bar = _bar(delta=Decimal("-2.25"), min_delta=Decimal("-3"))
    record = _record(bar)
    assert record[3:8] == (1_001, 1_010, 995, 1_005, 10_000)  # o, h, l, c at 1; v at 3
    assert record[10] == -2_250  # delta is signed, at qty_scale


@pytest.mark.parametrize(
    ("field", "value"),
    [("open", Decimal("100.15")), ("close", Decimal("100.55")), ("volume", Decimal("10.0005")),
     ("delta", Decimal("2.0005")), ("open", Decimal("1.0000000000000000000000000001"))],
)  # fmt: skip
def test_kind_4_refuses_a_value_its_scale_cannot_hold_exactly(field: str, value: Decimal) -> None:
    """A price finer than price_scale is never rounded to one that did not trade (§16.4), and a
    29-digit value is not rounded by the default 28-digit context into passing."""
    bar = _bar().model_copy(update={field: value})  # skips validation: a builder's frozen draft
    with pytest.raises(FrameEncodeError, match=rf"bars \(0, 3\): {field} .* not exact at scale"):
        _record(bar)


def test_kind_4_exactness_ignores_the_callers_decimal_context() -> None:
    with localcontext() as ctx:
        ctx.prec = 3
        assert _record(_bar())[3] == 1_001
        with pytest.raises(FrameEncodeError, match="not exact"):
            _record(_bar(open=Decimal("100.15")))


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", ["open", "volume", "delta"])
def test_both_forms_refuse_a_value_that_is_not_finite(field: str, value: str) -> None:
    bar = _bar().model_copy(update={field: Decimal(value)})
    with pytest.raises(FrameEncodeError, match=rf"{field} .*{value.lstrip('-s')} is not finite"):
        _record(bar)
    with pytest.raises(FrameEncodeError, match=rf"{field} .* is not finite"):
        bar_item(bar, generation=0, bar_kind="time", include_delta=True)


def test_kind_4_refuses_a_huge_exponent_before_building_the_integer() -> None:
    bar = _bar().model_copy(update={"volume": Decimal("1E+999999")})
    with pytest.raises(FrameEncodeError, match="volume 1E\\+999999 overflows every field"):
        _record(bar)


@pytest.mark.parametrize(
    ("generation", "update"), [(-1, {}), (0, {"trade_count": -1}), (0, {"index": -1})]
)
def test_both_forms_refuse_a_negative_key_or_trade_count(
    generation: int, update: dict[str, Any]
) -> None:
    bar = _bar().model_copy(update=update)
    with pytest.raises(FrameEncodeError, match="negative"):
        bar_item(bar, generation=generation, bar_kind="time", include_delta=False)
    with pytest.raises(FrameEncodeError, match="negative"):
        bar_record(bar, generation=generation, include_delta=False, price_scale=1, qty_scale=3,
                   ts_base_ms=T0_MS)  # fmt: skip


@pytest.mark.parametrize(
    ("update", "index", "accepted"),
    [({"volume": Decimal("18446744073709551.615")}, 7, 2**64 - 1),
     ({"turnover": Decimal("18446744073709551.615")}, 8, 2**64 - 1),
     ({"delta": Decimal("-9223372036854775.808")}, 10, -(2**63)),
     ({"delta": Decimal("9223372036854775.807")}, 10, 2**63 - 1)],
)  # fmt: skip
def test_kind_4_accepts_each_width_up_to_its_edge(
    update: dict[str, Any], index: int, accepted: int
) -> None:
    assert _record(_bar().model_copy(update=update))[index] == accepted


@pytest.mark.parametrize(
    "update",
    [{"volume": Decimal("18446744073709551.616")}, {"delta": Decimal("-9223372036854775.809")},
     {"delta": Decimal("9223372036854775.808")}],
)  # fmt: skip
def test_kind_4_refuses_one_past_each_width(update: dict[str, Any]) -> None:
    with pytest.raises(FrameEncodeError, match="is outside"):
        _record(_bar().model_copy(update=update))


def test_kind_4_ignores_the_delta_scale_without_include_delta() -> None:
    assert _record(_bar(delta=Decimal("2.0005")), include_delta=False)[10] == 0


@pytest.mark.parametrize(
    ("update", "field"),
    [({"turnover": Decimal("-1")}, "turnover"), ({"volume": Decimal("2E+16")}, "volume"),
     ({"open": Decimal("1E+18")}, "open"), ({"trade_count": 2**32}, "trades"),
     ({"index": 2**64}, "index")],
)  # fmt: skip
def test_kind_4_refuses_a_value_outside_its_field_range(update: dict[str, Any], field: str) -> None:
    bar = _bar().model_copy(update=update)
    with pytest.raises(FrameEncodeError, match=rf"bars \(0, \d+\): {field} -?\d+ is outside \["):
        _record(bar)


def test_kind_4_refuses_a_bar_opening_before_the_frame_base() -> None:
    with pytest.raises(FrameEncodeError, match=r"ts_offset_ms -1 is outside \[0, 4294967295\]"):
        _record(_bar(), ts_base_ms=T0_MS + 1)


def test_wire_forms_refuse_a_densify_filler() -> None:
    """`24-internal-schemas.md` §3.1: a filler repeats a real bar's index; it never goes out."""
    filler = _bar(synthetic=True)
    with pytest.raises(FrameEncodeError, match="densify"):
        bar_item(filler, generation=0, bar_kind="time", include_delta=False)
    with pytest.raises(FrameEncodeError, match="densify"):
        _frames([_bar(index=2), filler])


def test_covering_scales_keep_history_finer_than_the_instrument_exact() -> None:
    """Bars recorded before a tick or qty-step coarsening still go out exactly."""
    old = _bar(open=Decimal("100.15"), volume=Decimal("10.0005"), delta=Decimal("2.10"))
    scales = covering_scales([_bar(), old], price_scale=1, qty_scale=3)
    assert scales == (2, 4)
    (frame,) = bars_frames([old], generation=0, include_delta=True, price_scale=2, qty_scale=4)
    (got,) = structured(decode(encode(frame)))["bars"]
    assert (got["o"], got["v"], got["delta"]) == ("100.15", "10.0005", "2.1000")


@pytest.mark.parametrize(
    ("field", "value", "scales"),
    [("open", "100.15", (2, 3)), ("high", "101.25", (2, 3)), ("low", "99.55", (2, 3)),
     ("close", "100.45", (2, 3)), ("volume", "10.0005", (1, 4)), ("delta", "2.0005", (1, 4))],
)  # fmt: skip
def test_covering_scales_widen_for_each_field_alone(
    field: str, value: str, scales: tuple[int, int]
) -> None:
    bar = _bar().model_copy(update={field: Decimal(value)})
    assert covering_scales([bar], price_scale=1, qty_scale=3) == scales


def test_covering_scales_take_no_places_from_a_positive_exponent_or_a_nan() -> None:
    bars = [_bar(volume=Decimal("1E+2")), _bar().model_copy(update={"open": Decimal("NaN")})]
    assert covering_scales(bars, price_scale=0, qty_scale=0) == (1, 0)


def test_covering_scales_count_every_digit_of_a_29_digit_price() -> None:
    bar = _bar().model_copy(update={"open": Decimal("1.0000000000000000000000000001")})
    assert covering_scales([bar], price_scale=1, qty_scale=3) == (28, 3)


def test_covering_scales_never_go_below_the_instrument() -> None:
    assert covering_scales([_bar(volume=Decimal("1E+2"))], price_scale=4, qty_scale=6) == (4, 6)


def test_covering_scales_ignore_trailing_zeros() -> None:
    bar = _bar(open=Decimal("100.1000"), volume=Decimal("10.000000"))
    assert covering_scales([bar], price_scale=1, qty_scale=3) == (1, 3)


def test_bars_frames_split_a_1000_bar_daily_history_at_the_u32_offset_span() -> None:
    """1 000 daily bars span ~1 000 days, far past `ts_offset_ms`'s ~49.7 days: 50 per frame."""
    bars = [
        _bar(index=i, open_time=T0_US + i * DAY_US, close_time=T0_US + (i + 1) * DAY_US - 1)
        for i in range(1000)
    ]
    frames = _frames(bars)
    assert [len(f.records) for f in frames] == [50] * 20
    assert all(f.body_kind == BARS and f.records[-1][2] <= MAX_TS_SPAN_MS for f in frames)
    decoded = [b for f in frames for b in structured(decode(encode(f)))["bars"]]
    assert [(b["index"], b["t_ms"]) for b in decoded] == [
        (i, T0_MS + i * 86_400_000) for i in range(1000)
    ]


@pytest.mark.parametrize(("gap_ms", "frames"), [(4_294_967_295, 1), (4_294_967_296, 2)])
def test_bars_frames_offset_span_is_inclusive(gap_ms: int, frames: int) -> None:
    """The whole u32 range is usable: 2^32 - 1 ms after the base still fits."""
    bars = [_bar(index=3), _bar(index=4, open_time=T0_US + gap_ms * 1000)]
    assert (MAX_TS_SPAN_MS, len(_frames(bars))) == (2**32 - 1, frames)


def test_bars_frames_of_nothing_is_no_frame() -> None:
    assert _frames([]) == ()


def test_bars_frames_never_encode_a_negative_offset() -> None:
    """A bar opening before the current frame's base starts its own frame (u32 offsets)."""
    late, early = _bar(index=4, open_time=T0_US + DAY_US), _bar(index=5, open_time=T0_US)
    frames = _frames([late, early])
    assert [f.ts_base_ms for f in frames] == [T0_MS + 86_400_000, T0_MS]
    assert [decode(encode(f)).records[0][2] for f in frames] == [0, 0]


@settings(max_examples=60, deadline=None)
@given(
    gaps_us=st.lists(st.integers(0, 3 * MAX_TS_SPAN_MS * 1000), min_size=1, max_size=10),
    include_delta=st.booleans(),
)
def test_bars_frames_keep_every_bar_in_order_at_its_floored_time(
    gaps_us: list[int], include_delta: bool
) -> None:
    opens = [T0_US + t for t in accumulate(gaps_us)]
    bars = [_bar(index=i, open_time=t, close_time=t + 1) for i, t in enumerate(opens)]
    frames = bars_frames(
        bars, generation=0, include_delta=include_delta, price_scale=1, qty_scale=3
    )
    decoded = [b for f in frames for b in structured(decode(encode(f)))["bars"]]
    assert [(b["index"], b["t_ms"]) for b in decoded] == [
        (i, t // 1000) for i, t in enumerate(opens)
    ]
