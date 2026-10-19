"""Moving-average kernels: `sma`, `ema` (E13-T02, #426; 24-internal-schemas §7.4)."""

from __future__ import annotations

from collections.abc import Mapping

from candleviewer.orderflow.indicators.kernel import (
    ExponentialAverage,
    Kernel,
    State,
    as_count,
    as_float,
    as_float_list,
    int_param,
)
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue


class SmaKernel(Kernel):
    """Simple moving average of the last `n` closes.

    Operation order: a running sum over a ring of the last `n` inputs. For bar `k` (0-based),
    with `x = close`: when `k >= n`, `s = s - ring[k % n]` and `ring[k % n] = x`; then
    `s = s + x`. The value is `s / n` from `k = n - 1` on.
    """

    indicator = "sma"
    outputs = ("sma",)
    build_version = 1
    param_names = ("n",)
    sources = ("close",)
    nullable_when = "None until n bars exist; then the mean of the last n closes."

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        self._n = int_param(params, "n")
        self._ring: list[float] = []
        self._k = 0
        self._sum = 0.0

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return int_param(params, "n")

    def update(self, bar: BarInput) -> Outputs:
        x = bar.close
        if self._k >= self._n:
            j = self._k % self._n
            self._sum = self._sum - self._ring[j]
            self._ring[j] = x
        else:
            self._ring.append(x)
        self._sum = self._sum + x
        self._k += 1
        return (self._sum / self._n if self._k >= self._n else None,)

    def _dump(self) -> State:
        return {"k": self._k, "sum": self._sum, "ring": list(self._ring)}

    def _load(self, state: State) -> None:
        k, total, ring = as_count(state["k"]), as_float(state["sum"]), as_float_list(state["ring"])
        if len(ring) != min(k, self._n):
            raise ValueError("ring length does not match the bar count")
        self._k, self._sum, self._ring = k, total, ring


class EmaKernel(Kernel):
    """Exponential moving average of the close (`ExponentialAverage`: the mean of the first `n`
    closes, then `v = (x - v) * alpha + v` with `alpha = 2 / (n + 1)`)."""

    indicator = "ema"
    outputs = ("ema",)
    build_version = 1
    param_names = ("n",)
    sources = ("close",)
    nullable_when = (
        "None until n bars exist; the first value is the mean of the first n closes, then each "
        "bar weighs its close by alpha = 2/(n+1)."
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
        self._avg = ExponentialAverage(self._n)

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return int_param(params, "n")

    def update(self, bar: BarInput) -> Outputs:
        return (self._avg.update(bar.close),)

    def _dump(self) -> State:
        return {"avg": self._avg.dump()}

    def _load(self, state: State) -> None:
        avg = ExponentialAverage(self._n)
        avg.load(state["avg"])
        self._avg = avg
