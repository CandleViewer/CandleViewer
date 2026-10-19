"""Independent reference for the server indicator kernels (E13-T02 plan §3.9, D7).

Written from the published definitions, not from the kernels, and offline with no dependency:

- Inputs are the exact rational values of the binary64 inputs a kernel reads
  (`Fraction(float)`). A tie in a decimal source that rounds apart in binary64 (ADX's
  directional-movement test, a swing pivot) is then decided as the kernel decides it, which is
  also what the TS mirror sees; every other difference comes from the kernel's own rounding,
  which the 1e-8 tolerance bounds.
- Arithmetic is exact (`fractions.Fraction`); square roots use `decimal` at 50 significant
  digits. ADX is the exception: DX is a ratio of Wilder averages and feeds a second Wilder
  average, so exact denominators grow to about a million digits over 1,440 bars; DX and ADX
  use a 60-digit decimal context instead (rounding error below 1e-55).
- Windowed values (SMA, swing pivots) are recomputed from the whole window at every bar;
  recurrences (EMA, Wilder) run exactly from the first bar, in their textbook form.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, localcontext
from fractions import Fraction

from candleviewer.orderflow.indicators.types import BarInput, KernelContext

type Exact = Fraction | Decimal
type Row = tuple[Exact | None, ...]

_DAY_US = 86_400_000_000
_SQRT_DIGITS = 50
#: VWAP's band_sigma is undefined while sigma <= |vwap| * 2**-40 (sigma is rounding noise).
_SIGMA_FLOOR = Fraction(1, 2**40)
_ADX_DIGITS = 60


def _dec(x: Fraction, digits: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = digits
        return Decimal(x.numerator) / Decimal(x.denominator)


def _sqrt(x: Fraction) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _SQRT_DIGITS
        return _dec(x, _SQRT_DIGITS).sqrt()


def _seeded[T: (Fraction, Decimal)](
    xs: Sequence[T], n: int, step: Callable[[T, T], T]
) -> list[T | None]:
    """Mean of the first `n` inputs at index `n - 1`, then `v = step(v, x)`."""
    out: list[T | None] = []
    v: T | None = None
    for i, x in enumerate(xs):
        if v is not None:
            v = step(v, x)
        elif i == n - 1:
            v = sum(xs[1:n], xs[0]) / n
        out.append(v)
    return out


def _wilder[T: (Fraction, Decimal)](xs: Sequence[T], n: int) -> list[T | None]:
    return _seeded(xs, n, lambda v, x: v + (x - v) / n)


def sma(bars: Sequence[BarInput], n: int) -> list[Row]:
    c = [Fraction(b.close) for b in bars]
    out: list[Row] = []
    for i in range(len(c)):
        out.append((sum(c[i - n + 1 : i + 1], Fraction(0)) / n,) if i >= n - 1 else (None,))
    return out


def ema(bars: Sequence[BarInput], n: int) -> list[Row]:
    alpha = Fraction(2, n + 1)
    c = [Fraction(b.close) for b in bars]
    return [(v,) for v in _seeded(c, n, lambda v, x: v + alpha * (x - v))]


def rsi(bars: Sequence[BarInput], n: int) -> list[Row]:
    c = [Fraction(b.close) for b in bars]
    changes = [c[i] - c[i - 1] for i in range(1, len(c))]
    gain = _wilder([max(d, Fraction(0)) for d in changes], n)
    loss = _wilder([max(-d, Fraction(0)) for d in changes], n)
    out: list[Row] = [(None,)] if c else []
    for g, lo in zip(gain, loss, strict=True):
        if g is None or lo is None or (g == 0 and lo == 0):
            out.append((None,))
        elif lo == 0:
            out.append((Fraction(100),))
        else:
            out.append((100 - 100 / (1 + g / lo),))
    return out


def _true_ranges(bars: Sequence[BarInput]) -> list[Fraction]:
    out = []
    for i, b in enumerate(bars):
        h, lo = Fraction(b.high), Fraction(b.low)
        if i == 0:
            out.append(h - lo)
        else:
            pc = Fraction(bars[i - 1].close)
            out.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return out


def atr(bars: Sequence[BarInput], n: int) -> list[Row]:
    return [(v,) for v in _wilder(_true_ranges(bars), n)]


def adx(bars: Sequence[BarInput], n: int) -> list[Row]:
    plus_dm, minus_dm = [], []
    for prev, b in itertools.pairwise(bars):
        up = Fraction(b.high) - Fraction(prev.high)
        down = Fraction(prev.low) - Fraction(b.low)
        plus_dm.append(up if up > down and up > 0 else Fraction(0))
        minus_dm.append(down if down > up and down > 0 else Fraction(0))
    tr = _wilder(_true_ranges(bars)[1:], n)
    plus, minus = _wilder(plus_dm, n), _wilder(minus_dm, n)
    di: list[tuple[Fraction, Fraction] | None] = []
    for t, p, m in zip(tr, plus, minus, strict=True):
        if t is None or p is None or m is None:
            di.append(None)
        else:
            di.append((100 * p / t, 100 * m / t) if t > 0 else (Fraction(0), Fraction(0)))
    with localcontext() as ctx:
        ctx.prec = _ADX_DIGITS
        dx: list[Decimal] = []
        for pair in di:
            if pair is not None:
                pdi, mdi = _dec(pair[0], _ADX_DIGITS), _dec(pair[1], _ADX_DIGITS)
                dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else Decimal(0))
        smoothed = _wilder(dx, n)
    first = next((i for i, pair in enumerate(di) if pair is not None), len(di))
    out: list[Row] = [(None, None, None)] if bars else []
    for i, pair in enumerate(di):
        if pair is None:
            out.append((None, None, None))
        else:
            out.append((smoothed[i - first], pair[0], pair[1]))
    return out


def _period(t: int, anchor_us: int) -> int:
    return (t - anchor_us) // _DAY_US


def vwap(bars: Sequence[BarInput], context: KernelContext) -> list[Row]:
    anchor_us = context.session_anchor_utc_min * 60_000_000
    out: list[Row] = []
    period, w_sum, m1, m2 = None, Fraction(0), Fraction(0), Fraction(0)
    for b in bars:
        if _period(b.t, anchor_us) != period:
            period, w_sum, m1, m2 = _period(b.t, anchor_us), Fraction(0), Fraction(0), Fraction(0)
        w = Fraction(b.volume)
        if w > 0:
            x = (Fraction(b.high) + Fraction(b.low) + Fraction(b.close)) / 3
            w_sum, m1, m2 = w_sum + w, m1 + w * x, m2 + w * x * x
        if w_sum == 0:
            out.append((None,) * 9)
            continue
        mean = m1 / w_sum
        variance = m2 / w_sum - mean * mean
        sigma = _sqrt(variance)
        with localcontext() as ctx:
            ctx.prec = _SQRT_DIGITS
            centre = _dec(mean, _SQRT_DIGITS)
            bands = [centre + s * k * sigma for k in (1, 2, 3) for s in (1, -1)]
            defined = Fraction(sigma) > abs(mean) * _SIGMA_FLOOR
            z = (_dec(Fraction(b.close), _SQRT_DIGITS) - centre) / sigma if defined else None
        out.append((mean, sigma, *bands, z))
    return out


def cvd(bars: Sequence[BarInput], anchor: str, context: KernelContext) -> list[Row]:
    minutes = context.session_anchor_utc_min if anchor == "session" else 0
    out: list[Row] = []
    period, total = None, Fraction(0)
    for b in bars:
        if _period(b.t, minutes * 60_000_000) != period:
            period, total = _period(b.t, minutes * 60_000_000), Fraction(0)
        total += Fraction(b.delta)
        out.append((total,))
    return out


def zigzag(bars: Sequence[BarInput], depth: int, deviation_pct: float) -> list[Row]:
    high = [Fraction(b.high) for b in bars]
    low = [Fraction(b.low) for b in bars]
    deviation = Fraction(deviation_pct)

    def clears(p: Fraction, other: Fraction | None) -> bool:
        return other is None or abs(p - other) * 100 >= deviation * other

    swing_high: Fraction | None = None
    swing_low: Fraction | None = None
    out: list[Row] = []
    for j in range(len(bars)):
        c = j - depth
        if c - depth >= 0:
            before, after = range(c - depth, c), range(c + 1, c + depth + 1)
            if all(high[c] > high[i] for i in before) and all(high[c] >= high[i] for i in after):
                swing_high = high[c] if clears(high[c], swing_low) else swing_high
            if all(low[c] < low[i] for i in before) and all(low[c] <= low[i] for i in after):
                swing_low = low[c] if clears(low[c], swing_high) else swing_low
        out.append((swing_high, swing_low))
    return out


def reference(
    indicator: str,
    bars: Sequence[BarInput],
    params: Mapping[str, object],
    context: KernelContext,
) -> list[Row]:
    """The reference series of a server indicator, one row per bar."""
    match indicator:
        case "sma" | "ema" | "rsi" | "atr" | "adx":
            fn = {"sma": sma, "ema": ema, "rsi": rsi, "atr": atr, "adx": adx}[indicator]
            return fn(bars, int(str(params["n"])))
        case "vwap":
            return vwap(bars, context)
        case "cvd":
            return cvd(bars, str(params["anchor"]), context)
        case "volume":
            return [(Fraction(b.volume),) for b in bars]
        case "delta":
            return [(Fraction(b.delta),) for b in bars]
        case "zigzag":
            return zigzag(bars, int(str(params["depth"])), float(str(params["deviation_pct"])))
    raise KeyError(indicator)
