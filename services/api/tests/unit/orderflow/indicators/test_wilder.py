"""Wilder smoothing, not an EMA, for ATR, RSI and ADX (ticket "Technical notes"; #426).

Each kernel equals the exact Wilder reference, and differs by more than 1e-6, at each of the
`K` bars after its seed (where (b) shares the seed), from the same indicator smoothed by (a) an
EMA with `alpha = 1/n` seeded at the first value and (b) an EMA with `alpha = 2/(n+1)` seeded
with the SMA of the first `n` values.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from decimal import Decimal
from fractions import Fraction

import pytest

from candleviewer.orderflow.indicators import KERNELS, BarInput, KernelContext, compute
from tests.unit.orderflow.indicators.reference import reference

N, K = 14, 20
type Smoother = Callable[[Sequence[float], int], list[float | None]]


def ema_seeded_at_first(xs: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    v: float | None = None
    for x in xs:
        v = x if v is None else v + (x - v) / n
        out.append(v)
    return out


def ema_seeded_with_sma(xs: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    v: float | None = None
    for i, x in enumerate(xs):
        if v is not None:
            v = v + (x - v) * 2 / (n + 1)
        elif i == n - 1:
            v = sum(xs[:n]) / n
        out.append(v)
    return out


def _true_ranges(bars: Sequence[BarInput]) -> list[float]:
    trs = [bars[0].high - bars[0].low]
    for prev, b in itertools.pairwise(bars):
        trs.append(max(b.high, prev.close) - min(b.low, prev.close))
    return trs


def atr_with(smooth: Smoother, bars: Sequence[BarInput]) -> list[float | None]:
    return smooth(_true_ranges(bars), N)


def rsi_with(smooth: Smoother, bars: Sequence[BarInput]) -> list[float | None]:
    changes = [b.close - a.close for a, b in itertools.pairwise(bars)]
    gains = smooth([max(d, 0.0) for d in changes], N)
    losses = smooth([max(-d, 0.0) for d in changes], N)
    out: list[float | None] = [None]
    for g, lo in zip(gains, losses, strict=True):
        out.append(None if g is None or lo is None or g + lo == 0 else 100 * g / (g + lo))
    return out


def adx_with(smooth: Smoother, bars: Sequence[BarInput]) -> list[float | None]:
    pairs = list(itertools.pairwise(bars))
    tr = smooth(_true_ranges(bars)[1:], N)
    ups = [b.high - a.high for a, b in pairs]
    downs = [a.low - b.low for a, b in pairs]
    plus = smooth([u if u > d and u > 0 else 0.0 for u, d in zip(ups, downs, strict=True)], N)
    minus = smooth([d if d > u and d > 0 else 0.0 for u, d in zip(ups, downs, strict=True)], N)
    dx: list[float] = []
    for t, p, m in zip(tr, plus, minus, strict=True):
        if t is not None and p is not None and m is not None:
            pdi, mdi = (100 * p / t, 100 * m / t) if t > 0 else (0.0, 0.0)
            dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else 0.0)
    smoothed = smooth(dx, N)
    return [None] * (len(bars) - len(smoothed)) + smoothed


VARIANTS: dict[str, Callable[[Smoother, Sequence[BarInput]], list[float | None]]] = {
    "atr": atr_with,
    "rsi": rsi_with,
    "adx": adx_with,
}
SOURCES = {"atr": None, "rsi": "close", "adx": None}


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_kernel_equals_the_wilder_reference(name: str, kline: list[BarInput]) -> None:
    rows = compute(name, kline, {"n": N}, source=SOURCES[name])
    ref = reference(name, kline, {"n": N}, KernelContext())
    for (got, *_), (want, *_) in zip(rows, ref, strict=True):
        assert (got is None) == (want is None)
        if got is not None and want is not None:
            exact = Fraction(want) if isinstance(want, Decimal) else want
            assert abs(Fraction(got) - exact) <= Fraction(1, 10**8) * max(Fraction(1), abs(exact))


@pytest.mark.parametrize("smooth", [ema_seeded_at_first, ema_seeded_with_sma])
@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_kernel_differs_from_ema_smoothing(
    name: str, smooth: Smoother, kline: list[BarInput]
) -> None:
    rows = compute(name, kline, {"n": N}, source=SOURCES[name])
    other = VARIANTS[name](smooth, kline)
    start = KERNELS[name].warmup_bars({"n": N})  # the first smoothing step after the seed
    for i in range(start, start + K):
        got, alt = rows[i][0], other[i]
        assert got is not None
        assert alt is not None
        assert abs(got - alt) > 1e-6, f"{name} at bar {i} looks EMA-smoothed"
