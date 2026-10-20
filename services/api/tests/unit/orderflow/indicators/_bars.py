"""Bar builders and valid parameter sets for the indicator kernel tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from candleviewer.orderflow.indicators import BarInput
from candleviewer.orderflow.indicators.types import Outputs, ParamValue

#: 2026-10-05 00:00 UTC in microseconds; one test minute is 60e6 µs.
T0: Final = 1_791_158_400_000_000
MINUTE: Final = 60_000_000

#: One valid `(params, source)` per server kernel.
VALID: Final[Mapping[str, tuple[Mapping[str, ParamValue], str | None]]] = {
    "sma": ({"n": 20}, "close"),
    "ema": ({"n": 21}, "close"),
    "rsi": ({"n": 14}, "close"),
    "atr": ({"n": 14}, None),
    "adx": ({"n": 14}, None),
    "vwap": ({"anchor": "session"}, "hlc3"),
    "cvd": ({"anchor": "session"}, None),
    "volume": ({}, None),
    "delta": ({}, None),
    "zigzag": ({"depth": 5, "deviation_pct": 0.1}, None),
}


def bar(
    minute: int,
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1.0,
    delta: float = 0.0,
) -> BarInput:
    """A 1m bar opening `minute` minutes after `T0`; high/low default to the close."""
    h = close if high is None else high
    lo = close if low is None else low
    return BarInput(T0 + minute * MINUTE, close, h, lo, close, volume, delta, False)


def highs_lows(points: Sequence[tuple[float, float]]) -> list[BarInput]:
    """Bars from `(high, low)` pairs, one per minute, closing at the midpoint."""
    return [bar(i, (h + lo) / 2, high=h, low=lo) for i, (h, lo) in enumerate(points)]


def bits(rows: list[Outputs]) -> list[tuple[str, ...]]:
    """Rows as reprs: equal reprs are equal binary64 values, `-0.0` included."""
    return [tuple(repr(v) for v in row) for row in rows]
