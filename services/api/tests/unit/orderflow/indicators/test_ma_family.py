"""The moving-average family (E13-S02, #424; 24 §7.4): sma and ema with `source` and `offset`, and
the test-only reference kernels of `wma`, `vwma`, `smma`, `dema`, `tema` and `ma_ribbon`.

The traps the ticket names are asserted by value: the EMA seed is the mean of the first `n`
prices (not the first price), SMMA is Wilder's `1/n` smoothing and not the EMA, the DEMA and
TEMA warmups compose (`2n - 1`, `3n - 2`), VWMA is undefined (never 0, never a division by zero)
while its window holds no volume, a source changes the result and the identity, and an offset
only displaces a line, even through a snapshot.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from candleviewer.orderflow.errors import IndicatorParamError, InvalidParamsError
from candleviewer.orderflow.indicators import BarInput, IndicatorSpec, build_kernel, compute
from candleviewer.orderflow.indicators.catalogue import MA_RIBBON, SMA, validate_params
from candleviewer.orderflow.indicators.kernel import applied_price
from candleviewer.orderflow.indicators.types import ParamValue
from tests.unit.orderflow.indicators._bars import T0, bar, bits
from tests.unit.orderflow.indicators._ma_family import FOLDS, SHAPES, TEST_KERNELS
from tests.unit.orderflow.indicators.test_properties import SEED, series

FAMILY = tuple(SHAPES)
OHLC = BarInput(T0, 10.0, 16.0, 7.0, 12.0, 5.0, 0.0, False)


def _params(n: int, source: str = "close", offset: int = 0) -> dict[str, ParamValue]:
    return {"n": n, "source": source, "offset": offset}


def _run(
    ma: str, bars: list[BarInput], n: int, source: str = "close", offset: int = 0
) -> list[float | None]:
    params = _params(n, source, offset)
    if ma in ("sma", "ema"):
        rows = compute(ma, bars, params, source=source)
    else:
        rows = TEST_KERNELS[ma](params, source=source).run(bars)
    return [row[0] for row in rows]


def _ramp(count: int) -> list[BarInput]:
    return [
        bar(i, 100.0 + i, high=103.0 + i, low=99.0 + i, volume=1.0 + i % 3) for i in range(count)
    ]


def test_applied_price_orders_are_left_to_right_sums_then_a_division() -> None:
    assert [
        applied_price(OHLC, s) for s in ("close", "open", "high", "low", "hl2", "hlc3", "ohlc4")
    ] == [
        12.0,
        10.0,
        16.0,
        7.0,
        (16.0 + 7.0) / 2,
        (16.0 + 7.0 + 12.0) / 3,
        (10.0 + 16.0 + 7.0 + 12.0) / 4,
    ]


def test_applied_price_refuses_an_unknown_source() -> None:
    with pytest.raises(IndicatorParamError, match="source"):
        applied_price(OHLC, "median")


@pytest.mark.parametrize("ma", FAMILY)
def test_a_source_changes_the_values_and_the_identity(ma: str) -> None:
    bars = _ramp(60)
    on_close, on_hl2 = _run(ma, bars, 5), _run(ma, bars, 5, "hl2")
    assert on_close != on_hl2
    keys = {
        IndicatorSpec.of(ma, _params(5, s), bar_spec_hash="0" * 64).spec_hash
        for s in ("close", "hl2")
    }
    assert len(keys) == 2


def test_the_ema_seed_is_the_mean_of_the_first_n_prices_not_the_first_price() -> None:
    bars = [bar(i, c) for i, c in enumerate((10.0, 20.0, 30.0, 40.0))]
    out = _run("ema", bars, 3)
    assert out[:2] == [None, None] and out[2] == 20.0
    assert out[3] == (40.0 - 20.0) * (2 / 4) + 20.0


def test_smma_is_wilder_smoothing_and_differs_from_the_ema() -> None:
    bars = [bar(i, c) for i, c in enumerate((10.0, 20.0, 30.0, 70.0, 10.0))]
    smma, ema = _run("smma", bars, 3), _run("ema", bars, 3)
    assert smma[2] == ema[2] == 20.0  # the same seed
    assert smma[3] == (20.0 * 2 + 70.0) / 3
    assert smma[3] != ema[3] and smma[4] != ema[4]


@pytest.mark.parametrize(("ma", "n", "first"), [("dema", 4, 6), ("tema", 4, 9), ("dema", 1, 0)])
def test_dema_and_tema_warmups_compose(ma: str, n: int, first: int) -> None:
    out = _run(ma, _ramp(30), n)
    assert out.index(next(v for v in out if v is not None)) == first
    assert TEST_KERNELS[ma].warmup_bars(_params(n)) == first + 1


def test_dema_and_tema_of_a_constant_are_the_constant() -> None:
    bars = [bar(i, 42.5) for i in range(40)]
    for ma in ("dema", "tema"):
        assert [v for v in _run(ma, bars, 5) if v is not None] == [42.5] * (
            40 - SHAPES[ma][0] * 5 - SHAPES[ma][1] + 1
        )


def test_wma_weights_one_to_n_with_the_newest_heaviest() -> None:
    bars = [bar(i, c) for i, c in enumerate((10.0, 20.0, 40.0))]
    assert _run("wma", bars, 3)[2] == (1 * 10.0 + 2 * 20.0 + 3 * 40.0) / 6


def test_vwma_weights_by_volume_and_is_none_while_the_window_holds_none() -> None:
    bars = [bar(i, c, volume=v) for i, (c, v) in enumerate(((10.0, 1.0), (20.0, 3.0), (30.0, 0.0)))]
    assert _run("vwma", bars, 2)[1] == (10.0 * 1.0 + 20.0 * 3.0) / 4.0
    quiet = [bar(i, 50.0 + i, volume=0.0) for i in range(6)]
    out = _run("vwma", quiet, 3)
    assert out == [None] * 6  # a zero divisor is "no value": never 0, never an error
    mixed = [bar(0, 10.0, volume=2.0), *quiet[1:5], bar(5, 70.0, volume=1.0)]
    assert _run("vwma", mixed, 3)[2:] == [10.0, None, None, 70.0]  # the volume leaves, then returns


@pytest.mark.parametrize("ma", FAMILY)
def test_values_before_the_warmup_are_none_never_zero(ma: str) -> None:
    out = _run(ma, _ramp(40), 6, offset=2)
    kernel_cls = (
        TEST_KERNELS[ma]
        if ma in TEST_KERNELS
        else type(build_kernel(ma, _params(6), source="close"))
    )
    warmup = kernel_cls.warmup_bars(_params(6, "close", 2))
    assert out[: warmup - 1] == [None] * (warmup - 1)
    assert out[warmup - 1] is not None
    assert all(v is None or v > 0 for v in out)


@pytest.mark.parametrize("ma", FAMILY)
def test_an_offset_only_displaces_the_line(ma: str) -> None:
    bars = _ramp(50)
    raw, shifted = _run(ma, bars, 5), _run(ma, bars, 5, "close", 7)
    assert shifted == [None] * 7 + raw[:-7]
    assert not any(isinstance(v, float) and math.isnan(v) for v in shifted if v is not None)


def test_an_offset_longer_than_the_series_is_all_none() -> None:
    assert _run("sma", _ramp(10), 3, offset=500) == [None] * 10


@pytest.mark.parametrize("ma", ("sma", "ema"))
def test_a_server_kernel_snapshot_carries_the_offset_ring(ma: str) -> None:
    bars = _ramp(40)
    params = _params(4, "ohlc4", 6)
    whole = compute(ma, bars, params, source="ohlc4")
    first = build_kernel(ma, params, source="ohlc4")
    head = first.run(bars[:17])
    second = build_kernel(ma, params, source="ohlc4")
    second.restore(first.snapshot())
    assert bits(head + second.run(bars[17:])) == bits(whole)


def test_the_source_argument_must_equal_the_source_parameter() -> None:
    with pytest.raises(IndicatorParamError, match="source"):
        build_kernel("sma", _params(5, "hl2"), source="close")
    with pytest.raises(IndicatorParamError, match="source"):
        build_kernel("sma", {"n": 5, "source": "median", "offset": 0}, source="median")


def test_an_offset_past_the_bound_or_an_unknown_source_is_refused_never_clamped() -> None:
    for bad in ({"offset": 501}, {"offset": -1}, {"offset": 2.5}, {"source": "median"}):
        with pytest.raises(InvalidParamsError):
            validate_params(SMA, bad)
    assert validate_params(SMA, {"offset": 500})["offset"] == 500


def test_the_ribbon_lines_equal_the_single_averages_at_their_periods() -> None:
    bars = _ramp(90)
    periods = (2, 3, 5, 8, 13)
    for ma in FAMILY:
        params = {f"n{i}": n for i, n in enumerate(periods, 1)} | {"ma": ma, "source": "hl2"}
        rows = TEST_KERNELS["ma_ribbon"](params, source="hl2").run(bars)
        for i, n in enumerate(periods):
            assert [r[i] for r in rows] == _run(ma, bars, n, "hl2"), (ma, n)


def test_the_ribbon_warmup_is_the_longest_line() -> None:
    params = {f"n{i}": n for i, n in enumerate((2, 3, 5, 8, 13), 1)} | {
        "ma": "tema",
        "source": "close",
    }
    assert TEST_KERNELS["ma_ribbon"].warmup_bars(params) == 3 * 13 - 2
    assert MA_RIBBON.warmup_bars(params) == 3 * 13 - 2


def test_the_ribbon_warmup_refuses_an_unvalidated_average_with_a_param_error() -> None:
    params: dict[str, ParamValue] = {f"n{i}": 5 for i in range(1, 6)}
    params["source"] = "close"
    for ma in (None, "hma"):
        with pytest.raises(IndicatorParamError, match=r"^ma must be one of"):
            MA_RIBBON.warmup_bars(params if ma is None else params | {"ma": ma})


def test_the_test_only_averages_are_not_production_kernels() -> None:
    from candleviewer.orderflow.indicators import KERNELS
    from candleviewer.orderflow.indicators.catalogue import SERVER_DEFINITIONS

    for name in ("wma", "vwma", "smma", "dema", "tema", "ma_ribbon"):
        assert name not in KERNELS and name not in SERVER_DEFINITIONS


def test_the_sma_fold_of_the_ribbon_is_the_production_sma_bit_for_bit() -> None:
    bars = _ramp(80)
    fold = FOLDS["sma"](9)
    outs = [fold.update(b.close, b.volume) for b in bars]
    assert bits([(v,) for v in outs]) == bits(compute("sma", bars, _params(9), source="close"))


@seed(SEED)
@settings(max_examples=120, deadline=None)
@given(
    bars=series(),
    ma=st.sampled_from(FAMILY),
    n=st.integers(1, 12),
    offset=st.integers(0, 6),
    source=st.sampled_from(["close", "open", "high", "low", "hl2", "hlc3", "ohlc4"]),
    data=st.data(),
)
def test_incremental_equals_full_over_generated_series(
    bars: list[BarInput], ma: str, n: int, offset: int, source: str, data: st.DataObject
) -> None:
    """The ticket's property: appending bars one at a time gives every value of the full run,
    through a fresh kernel or (the server pair) a snapshot at a random cut."""
    full = _run(ma, bars, n, source, offset)
    stepped: list[float | None] = []
    params = _params(n, source, offset)
    kernel = (
        build_kernel(ma, params, source=source)
        if ma in ("sma", "ema")
        else TEST_KERNELS[ma](params, source=source)
    )
    for b in bars:
        stepped.append(kernel.update(b)[0])
    assert bits([(v,) for v in stepped]) == bits([(v,) for v in full])
    assert all(v is None or math.isfinite(v) for v in full)


@seed(SEED)
@settings(max_examples=80, deadline=None)
@given(bars=series(), n=st.integers(1, 8), offset=st.integers(0, 8))
def test_a_displaced_line_is_the_raw_line_shifted_for_every_average(
    bars: list[BarInput], n: int, offset: int
) -> None:
    for ma in FAMILY:
        raw = _run(ma, bars, n)
        got = _run(ma, bars, n, "close", offset)
        assert got == ([None] * offset + raw)[: len(bars)], ma
