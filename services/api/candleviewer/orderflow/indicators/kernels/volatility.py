"""Volatility kernels: `atr`, `adx` (E13-T02, #426; 24-internal-schemas §7.4)."""

from __future__ import annotations

from collections.abc import Mapping

from candleviewer.orderflow.indicators.kernel import (
    Kernel,
    State,
    WilderAverage,
    as_float_list,
    as_optional_float,
    int_param,
)
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue


def true_range(bar: BarInput, prev_close: float | None) -> float:
    """`high - low` on the first bar, then `max(high, prev_close) - min(low, prev_close)`:
    one subtraction of two selected inputs, equal to the textbook three-way maximum."""
    if prev_close is None:
        return bar.high - bar.low
    return max(bar.high, prev_close) - min(bar.low, prev_close)


class AtrKernel(Kernel):
    """Wilder average true range: `WilderAverage(n)` of `true_range`."""

    indicator = "atr"
    outputs = ("atr",)
    build_version = 1
    param_names = ("n",)
    sources = (None,)
    nullable_when = (
        "None until n bars exist: the first value is the mean of the first n true ranges "
        "(Wilder's seed), then Wilder smoothing."
    )

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        self._n = int_param(params, "n")
        self._prev_close: float | None = None
        self._avg = WilderAverage(self._n)

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return int_param(params, "n")

    def update(self, bar: BarInput) -> Outputs:
        tr = true_range(bar, self._prev_close)
        self._prev_close = bar.close
        return (self._avg.update(tr),)

    def _dump(self) -> State:
        return {"prev_close": self._prev_close, "avg": self._avg.dump()}

    def _load(self, state: State) -> None:
        prev_close = as_optional_float(state["prev_close"])
        avg = WilderAverage(self._n)
        avg.load(state["avg"])
        self._prev_close, self._avg = prev_close, avg


class AdxKernel(Kernel):
    """Wilder ADX with the directional indicators.

    From the second bar on: `up = high - prev_high`, `down = prev_low - low`;
    `plus_dm = up if up > down and up > 0.0 else 0.0`,
    `minus_dm = down if down > up and down > 0.0 else 0.0`, `tr = true_range(...)`. Each feeds a
    `WilderAverage(n)`: `atr`, `plus`, `minus`. Once they are seeded,
    `plus_di = 100.0 * plus / atr` and `minus_di = 100.0 * minus / atr` when `atr > 0.0`, else
    both `0.0`; `dx = 100.0 * abs(plus_di - minus_di) / (plus_di + minus_di)` when that sum is
    `> 0.0`, else `0.0`; `adx` is a `WilderAverage(n)` of `dx`.

    The two `0.0` branches read "no range" as "no directional movement". They are the one
    exception to "a value without a defined operation is `None`, never 0" (24 §7.4): a flat
    market reads ADX 0 after its warmup, not `None`, and `nullable_when` says so.
    """

    indicator = "adx"
    outputs = ("adx", "plus_di", "minus_di")
    build_version = 1
    param_names = ("n",)
    sources = (None,)
    nullable_when = (
        "adx is None until 2n bars exist (n+1 bars seed the directional indicators, n-1 more "
        "complete Wilder's average of DX); plus_di and minus_di are None until n+1 bars exist. "
        "After that nothing is None: with no true range plus_di and minus_di read 0, and DX "
        "reads 0 while both are 0, so a flat market reads ADX 0."
    )

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        self._n = int_param(params, "n")
        self._prev: list[float] | None = None  # [high, low, close] of the previous bar
        self._atr, self._plus, self._minus, self._dx = (WilderAverage(self._n) for _ in range(4))

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return 2 * int_param(params, "n")

    def update(self, bar: BarInput) -> Outputs:
        prev = self._prev
        self._prev = [bar.high, bar.low, bar.close]
        if prev is None:
            return (None, None, None)
        up = bar.high - prev[0]
        down = prev[1] - bar.low
        atr = self._atr.update(true_range(bar, prev[2]))
        plus = self._plus.update(up if up > down and up > 0.0 else 0.0)
        minus = self._minus.update(down if down > up and down > 0.0 else 0.0)
        if atr is None or plus is None or minus is None:
            return (None, None, None)
        plus_di, minus_di = 0.0, 0.0
        if atr > 0.0:
            plus_di = 100.0 * plus / atr
            minus_di = 100.0 * minus / atr
        di_sum = plus_di + minus_di
        dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum > 0.0 else 0.0
        return (self._dx.update(dx), plus_di, minus_di)

    def _dump(self) -> State:
        averages = [a.dump() for a in (self._atr, self._plus, self._minus, self._dx)]
        return {"prev": self._prev, "averages": averages}

    def _load(self, state: State) -> None:
        prev = None if state["prev"] is None else as_float_list(state["prev"])
        if prev is not None and len(prev) != 3:
            raise ValueError("prev is [high, low, close]")
        raw = state["averages"]
        if not isinstance(raw, list) or len(raw) != 4:
            raise TypeError("expected four averages")
        averages = [WilderAverage(self._n) for _ in range(4)]
        for avg, item in zip(averages, raw, strict=True):
            avg.load(item)
        self._prev = prev
        self._atr, self._plus, self._minus, self._dx = averages
