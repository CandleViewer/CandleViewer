"""Warmup is honoured (E13-T02 AC "Warmup is honoured"; 24-internal-schemas §7.3).

Before `warmup_bars(params)` bars exist a value is `None`, never 0 and never NaN, and the
descriptor text `nullable_when` states exactly why, naming the bar count.
"""

from __future__ import annotations

import pytest

from candleviewer.orderflow.indicators import KERNELS, BarInput, compute
from tests.unit.orderflow.indicators._bars import VALID

COUNT_PHRASES = {
    "sma": "None until n bars exist",
    "ema": "None until n bars exist",
    "rsi": "None until n+1 bars exist",
    "atr": "None until n bars exist",
    "adx": "adx is None until 2n bars exist",
    "vwap": "None until a bar with volume closes in the current session",
    "cvd": "None only before the first bar",
    "volume": "None only before the first bar",
    "delta": "None only before the first bar",
    "zigzag": "at least 2*depth+1 bars",
}


def test_atr14_with_10_bars_is_none_never_zero(kline: list[BarInput]) -> None:
    out = compute("atr", kline[:10], {"n": 14}, source=None)
    assert out == [(None,)] * 10
    assert KERNELS["atr"].warmup_bars({"n": 14}) == 14


def test_atr14_takes_its_first_value_on_the_14th_bar(kline: list[BarInput]) -> None:
    out = compute("atr", kline[:14], {"n": 14}, source=None)
    assert out[12] == (None,)
    first = out[13][0]
    assert first is not None
    assert first > 0.0


def test_nullable_when_names_the_warmup_count() -> None:
    assert set(COUNT_PHRASES) == set(KERNELS)
    for name, phrase in COUNT_PHRASES.items():
        assert phrase in KERNELS[name].nullable_when, name


@pytest.mark.parametrize("name", sorted(KERNELS))
def test_the_first_value_lands_on_the_warmup_boundary(name: str, kline: list[BarInput]) -> None:
    params, source = VALID[name]
    rows = compute(name, kline, params, source=source)
    first = next(i for i, row in enumerate(rows) if row[0] is not None)
    warmup = KERNELS[name].warmup_bars(params)
    if name == "zigzag":  # a swing also needs a pivot in the data
        assert first >= warmup - 1
    else:
        assert first == warmup - 1


@pytest.mark.parametrize("name", ["sma", "ema", "rsi", "atr", "adx"])
@pytest.mark.parametrize("n", [1, 2, 5, 14, 50])
def test_period_kernels_warm_up_after_exactly_their_bar_count(
    name: str, n: int, kline: list[BarInput]
) -> None:
    rows = compute(name, kline, {"n": n}, source=VALID[name][1])
    warmup = KERNELS[name].warmup_bars({"n": n})
    assert [row[0] for row in rows[: warmup - 1]] == [None] * (warmup - 1)
    assert rows[warmup - 1][0] is not None


def test_a_period_longer_than_the_series_stays_none(kline: list[BarInput]) -> None:
    assert compute("sma", kline, {"n": 5000}, source="close") == [(None,)] * len(kline)
