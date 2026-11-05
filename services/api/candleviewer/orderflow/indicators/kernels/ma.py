"""Moving-average kernels: `sma`, `ema` (E13-T02, #426; E13-S02, #424; 24-internal-schemas §7.4).

Both read the applied price `source` (`applied_price`, default `close`) and shift their line by
`offset` bars (`OffsetLine`), and both are parameters: part of the identity. The client-worker
moving averages (WMA, VWMA, SMMA, DEMA, TEMA) have no production kernel (ADR-0034 rule 1)."""

from __future__ import annotations

from collections.abc import Mapping

from candleviewer.orderflow.errors import IndicatorParamError
from candleviewer.orderflow.indicators.kernel import (
    ExponentialAverage,
    Kernel,
    OffsetLine,
    State,
    applied_price,
    as_count,
    as_float,
    as_float_list,
    choice_param,
    int_param,
)
from candleviewer.orderflow.indicators.limits import MA_SOURCES
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue


def _price_source(params: Mapping[str, ParamValue], source: str | None) -> str:
    """The `source` parameter, which the caller's `source` must equal: one price, one identity."""
    price = choice_param(params, "source", MA_SOURCES)
    if source != price:
        raise IndicatorParamError("The source argument must equal the source parameter.")
    return price


class SmaKernel(Kernel):
    """Simple moving average of the last `n` applied prices.

    Operation order: a running sum over a ring of the last `n` inputs. For bar `k` (0-based),
    with `x = applied_price(bar, source)`: when `k >= n`, `s = s - ring[k % n]` and
    `ring[k % n] = x`; then `s = s + x`. The raw value is `s / n` from `k = n - 1` on; the
    output is the raw value `offset` bars before (`OffsetLine`).
    """

    indicator = "sma"
    outputs = ("sma",)
    # build_version 1 -> 2: the snapshot state layout gains a `line` key (the offset line), which
    # alone forces the bump (the output digest changes too, but the layout rule applies first).
    build_version = 2
    param_names = ("n", "source", "offset")
    sources = MA_SOURCES
    nullable_when = (
        "None until n bars exist, and for the first offset bars after; then the mean of the "
        "last n applied prices, offset bars late."
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
        self._price = _price_source(params, source)
        self._line_offset = int_param(params, "offset", minimum=0)
        self._line = OffsetLine(self._line_offset)
        self._ring: list[float] = []
        self._k = 0
        self._sum = 0.0

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return int_param(params, "n") + int_param(params, "offset", minimum=0)

    def update(self, bar: BarInput) -> Outputs:
        x = applied_price(bar, self._price)
        if self._k >= self._n:
            j = self._k % self._n
            self._sum = self._sum - self._ring[j]
            self._ring[j] = x
        else:
            self._ring.append(x)
        self._sum = self._sum + x
        self._k += 1
        return (self._line.push(self._sum / self._n if self._k >= self._n else None),)

    def _dump(self) -> State:
        return {"k": self._k, "sum": self._sum, "ring": list(self._ring), "line": self._line.dump()}

    def _load(self, state: State) -> None:
        k, total, ring = as_count(state["k"]), as_float(state["sum"]), as_float_list(state["ring"])
        if len(ring) != min(k, self._n):
            raise ValueError("ring length does not match the bar count")
        line = OffsetLine(self._line_offset)
        line.load(state["line"])
        self._k, self._sum, self._ring, self._line = k, total, ring, line


class EmaKernel(Kernel):
    """Exponential moving average of the applied price (`ExponentialAverage`: the mean of the
    first `n` prices, then `v = (x - v) * alpha + v` with `alpha = 2 / (n + 1)`), `offset` bars
    late (`OffsetLine`)."""

    indicator = "ema"
    outputs = ("ema",)
    # build_version 1 -> 2: the snapshot state layout gains a `line` key (the offset line), which
    # alone forces the bump (the output digest changes too, but the layout rule applies first).
    build_version = 2
    param_names = ("n", "source", "offset")
    sources = MA_SOURCES
    nullable_when = (
        "None until n bars exist, and for the first offset bars after; the first value is the "
        "mean of the first n applied prices, then each bar weighs its price by alpha = 2/(n+1), "
        "offset bars late."
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
        self._price = _price_source(params, source)
        self._line_offset = int_param(params, "offset", minimum=0)
        self._line = OffsetLine(self._line_offset)
        self._avg = ExponentialAverage(self._n)

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return int_param(params, "n") + int_param(params, "offset", minimum=0)

    def update(self, bar: BarInput) -> Outputs:
        return (self._line.push(self._avg.update(applied_price(bar, self._price))),)

    def _dump(self) -> State:
        return {"avg": self._avg.dump(), "line": self._line.dump()}

    def _load(self, state: State) -> None:
        avg = ExponentialAverage(self._n)
        avg.load(state["avg"])
        line = OffsetLine(self._line_offset)
        line.load(state["line"])
        self._avg, self._line = avg, line
