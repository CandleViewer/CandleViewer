"""Kernel declarations, parameter validation and per-kernel semantics (E13-T02 plan §3.3, D11)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.orderflow.errors import IndicatorParamError, UnknownIndicatorError
from candleviewer.orderflow.indicators import (
    KERNELS,
    BarInput,
    KernelContext,
    build_kernel,
    compute,
    kernel_class,
)
from candleviewer.orderflow.indicators.kernels.volume import SIGMA_FLOOR
from candleviewer.orderflow.indicators.types import Outputs, ParamValue
from tests.unit.orderflow.indicators._bars import VALID, bar, highs_lows

#: ADR-0034 §5: the nine `compute: server` indicators, plus the `delta` pass-through (plan D2).
SERVER_SET = {"sma", "ema", "rsi", "atr", "adx", "vwap", "cvd", "volume", "zigzag"}


def _zigzag(points: Sequence[tuple[float, float]], depth: int, deviation: float) -> list[Outputs]:
    params: dict[str, ParamValue] = {"depth": depth, "deviation_pct": deviation}
    return compute("zigzag", highs_lows(points), params, source=None)


def test_registry_is_the_adr_0034_server_set_plus_delta() -> None:
    assert set(KERNELS) == SERVER_SET | {"delta"}
    assert all(cls.indicator == name for name, cls in KERNELS.items())
    assert kernel_class("atr") is KERNELS["atr"]


@pytest.mark.parametrize("name", sorted(KERNELS))
def test_kernel_declarations_are_complete(name: str) -> None:
    cls = KERNELS[name]
    params, source = VALID[name]
    assert cls.outputs
    assert len(set(cls.outputs)) == len(cls.outputs)
    assert cls.build_version >= 1
    assert source in cls.sources
    assert set(cls.param_names) == set(params)
    assert "None" in cls.nullable_when
    assert cls.warmup_bars(params) >= 1


def test_an_indicator_without_a_server_kernel_is_refused() -> None:
    with pytest.raises(UnknownIndicatorError):
        build_kernel("bollinger", {"n": 20}, source="close")


def test_unknown_and_missing_parameters_are_named() -> None:
    with pytest.raises(IndicatorParamError, match="no parameter named x"):
        build_kernel("sma", {"n": 20, "x": 1}, source="close")
    with pytest.raises(IndicatorParamError, match="needs the parameter n"):
        build_kernel("sma", {}, source="close")


@pytest.mark.parametrize(("name", "source"), [("sma", "hlc3"), ("atr", "close"), ("vwap", None)])
def test_a_source_the_kernel_does_not_read_is_refused(name: str, source: str | None) -> None:
    with pytest.raises(IndicatorParamError, match="source"):
        build_kernel(name, VALID[name][0], source=source)


BAD_PERIODS: tuple[object, ...] = (0, -1, 2.5, True, "14", None, float("nan"), float("inf"))
BAD_PERIODS += (Decimal("NaN"), Decimal("sNaN"), Decimal("2.5"), Decimal("Infinity"))


@pytest.mark.parametrize("n", BAD_PERIODS)
def test_a_period_must_be_a_whole_number_of_at_least_one(n: object) -> None:
    with pytest.raises(IndicatorParamError) as err:
        build_kernel("ema", {"n": cast(Any, n)}, source="close")
    assert str(err.value).startswith("n must be ")
    assert repr(n) not in str(err.value)


def test_integral_float_and_decimal_periods_equal_the_int() -> None:
    bars = [bar(i, 100.0 + i % 7) for i in range(40)]
    want = compute("sma", bars, {"n": 21}, source="close")
    assert compute("sma", bars, {"n": 21.0}, source="close") == want
    assert compute("sma", bars, {"n": Decimal("21.00")}, source="close") == want


def test_a_decimal_deviation_reads_as_its_binary64_value() -> None:
    points = [(102.0, 101.0), (101.0, 100.0), (105.0, 102.0), (103.0, 101.0), (120.0, 105.0)]
    params: dict[str, ParamValue] = {"depth": 1, "deviation_pct": Decimal("4.9")}
    as_float: dict[str, ParamValue] = {"depth": 1, "deviation_pct": 4.9}
    bars = highs_lows(points)
    assert compute("zigzag", bars, params, source=None) == compute(
        "zigzag", bars, as_float, source=None
    )


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), "0.1", True, Decimal("NaN")])
def test_deviation_must_be_a_finite_non_negative_number(value: object) -> None:
    with pytest.raises(IndicatorParamError, match="deviation_pct"):
        build_kernel("zigzag", {"depth": 5, "deviation_pct": cast(Any, value)}, source=None)


@pytest.mark.parametrize(("name", "anchor"), [("vwap", "utc_day"), ("cvd", "custom_ts")])
def test_an_anchor_outside_the_supported_choices_is_refused(name: str, anchor: str) -> None:
    with pytest.raises(IndicatorParamError, match="anchor must be one of"):
        build_kernel(name, {"anchor": anchor}, source=VALID[name][1])


@pytest.mark.parametrize("minutes", [-1, 1440, True, 1.5])
def test_kernel_context_bounds_the_session_anchor(minutes: object) -> None:
    with pytest.raises(IndicatorParamError, match="session_anchor_utc_min"):
        KernelContext(cast(Any, minutes))


@pytest.mark.parametrize("name", sorted(KERNELS))
def test_run_and_compute_are_the_same_fold_as_update(name: str) -> None:
    params, source = VALID[name]
    bars = [
        bar(i, 100.0 + (i * 7) % 11, high=112.0, low=99.0, delta=i % 3 - 1.0) for i in range(60)
    ]
    stepwise = build_kernel(name, params, source=source)
    expected = [stepwise.update(b) for b in bars]
    assert build_kernel(name, params, source=source).run(bars) == expected
    assert compute(name, bars, params, source=source) == expected


def test_sma_of_one_bar_is_the_close() -> None:
    bars = [bar(i, 100.0 + i * 0.1) for i in range(10)]
    assert compute("sma", bars, {"n": 1}, source="close") == [(b.close,) for b in bars]


def test_rsi_is_none_on_a_flat_series_and_100_on_a_rising_one() -> None:
    flat = compute("rsi", [bar(i, 100.0) for i in range(30)], {"n": 14}, source="close")
    rising = compute("rsi", [bar(i, 100.0 + i) for i in range(30)], {"n": 14}, source="close")
    assert flat == [(None,)] * 30
    assert rising[:14] == [(None,)] * 14
    assert rising[14:] == [(100.0,)] * 16


def test_adx_on_flat_bars_is_zero_after_its_warmup() -> None:
    out = compute("adx", [bar(i, 100.0) for i in range(40)], {"n": 5}, source=None)
    assert out[:5] == [(None, None, None)] * 5
    assert out[5:9] == [(None, 0.0, 0.0)] * 4
    assert out[9:] == [(0.0, 0.0, 0.0)] * 31


def test_vwap_restarts_at_the_session_anchor() -> None:
    bars = [bar(m, 100.0 + m - 478, volume=2.0) for m in (478, 479, 480, 481)]
    out = compute("vwap", bars, {"anchor": "session"}, source="hlc3", context=KernelContext(480))
    assert [row[0] for row in out] == [100.0, 100.5, 102.0, 102.5]
    assert [row[1] for row in out] == [0.0, 0.5, 0.0, 0.5]


def test_vwap_skips_zero_volume_bars_and_starts_without_a_value() -> None:
    bars = [bar(0, 90.0, volume=0.0), bar(1, 100.0, volume=2.0), bar(2, 200.0, volume=0.0)]
    bars.append(bar(3, 110.0, volume=2.0))
    out = compute("vwap", bars, {"anchor": "session"}, source="hlc3")
    assert out[0] == (None,) * 9
    assert out[1] == (100.0, 0.0, *([100.0] * 6), None)
    assert out[2][:2] == (100.0, 0.0)
    assert out[3][:2] == (105.0, 5.0)
    assert out[3][2:8] == (110.0, 100.0, 115.0, 95.0, 120.0, 90.0)
    assert out[3][8] == 1.0


def test_vwap_band_sigma_stays_none_while_sigma_is_rounding_noise() -> None:
    """Both typical prices are 300.3 / 3 in decimal but round apart in binary64: sigma is
    1.4e-14, and without the floor band_sigma would be about -7e12."""
    bars = [bar(0, 100.1, high=100.1, low=100.1), bar(1, 100.0, high=100.3, low=100.0)]
    out = compute("vwap", bars, {"anchor": "session"}, source="hlc3")
    sigma = out[1][1]
    assert sigma is not None
    assert 0.0 < sigma < 1e-13
    assert out[1][8] is None
    assert SIGMA_FLOOR == 2.0**-40


def test_cvd_restarts_at_its_anchor_period() -> None:
    minutes = (478, 479, 480, 481, 1438, 1439, 1440, 1441)
    bars = [bar(m, 100.0, delta=1.0) for m in minutes]
    ctx = KernelContext(480)
    session = compute("cvd", bars, {"anchor": "session"}, source=None, context=ctx)
    utc_day = compute("cvd", bars, {"anchor": "utc_day"}, source=None, context=ctx)
    assert [v for (v,) in session] == [1.0, 2.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert [v for (v,) in utc_day] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 1.0, 2.0]


def test_volume_and_delta_pass_the_bar_fields_through() -> None:
    bars = [bar(i, 100.0, volume=i * 0.5, delta=-i * 0.25) for i in range(5)]
    assert compute("volume", bars, {}, source=None) == [(b.volume,) for b in bars]
    assert compute("delta", bars, {}, source=None) == [(b.delta,) for b in bars]


def test_zigzag_flat_top_keeps_its_first_bar_and_needs_strictly_lower_bars_before() -> None:
    out = _zigzag([(1, 0), (2, 1), (5, 4), (5, 4), (3, 2), (2, 1), (1, 0)], 2, 0.0)
    assert [row[0] for row in out] == [None] * 4 + [5.0] * 3


def test_zigzag_confirms_a_pivot_exactly_depth_bars_later() -> None:
    points = [(1, 0), (2, 1), (3, 2), (9, 8), (3, 2), (2, 1), (1, 0), (1, 0)]
    out = _zigzag(points, 3, 0.0)
    assert [row[0] for row in out] == [None] * 6 + [9.0] * 2


def test_zigzag_deviation_drops_swings_too_close_to_the_last_opposite_swing() -> None:
    points = [(102, 101), (101, 100), (105, 102), (103, 101), (120, 105), (110, 108)]
    out = _zigzag(points, 1, 10.0)
    assert out[2:] == [(None, 100.0), (None, 100.0), (None, 101.0), (120.0, 101.0)]


def test_zigzag_tests_an_outside_bar_high_before_its_low() -> None:
    points = [(101, 99), (110, 90), (102, 98)]
    assert _zigzag(points, 1, 0.0)[2] == (110.0, 90.0)
    assert _zigzag(points, 1, 20.0)[2] == (110.0, None)


def test_kernels_never_emit_nan(kline: list[BarInput]) -> None:
    for name, (params, source) in VALID.items():
        for row in compute(name, kline, params, source=source):
            assert all(v is None or v == v for v in row)
