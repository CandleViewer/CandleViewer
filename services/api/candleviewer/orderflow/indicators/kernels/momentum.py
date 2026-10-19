"""Momentum kernels: `rsi` (E13-T02; plan §3.3)."""

from __future__ import annotations

from collections.abc import Mapping

from candleviewer.orderflow.indicators.kernel import (
    Kernel,
    State,
    WilderAverage,
    as_optional_float,
    int_param,
)
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue


class RsiKernel(Kernel):
    """Wilder RSI of the close.

    From the second bar on, with `d = close - prev_close`: `up = d if d > 0.0 else 0.0` and
    `down = -d if d < 0.0 else 0.0` feed two `WilderAverage(n)`, `gain` and `loss`. Once both
    are seeded, `rsi = 100.0 * gain / (gain + loss)`; it is `None` while `gain + loss == 0.0`.
    """

    indicator = "rsi"
    outputs = ("rsi",)
    build_version = 1
    param_names = ("n",)
    sources = ("close",)
    nullable_when = (
        "None until n+1 bars exist (n close-to-close changes seed Wilder's average gain and "
        "loss), and while the average gain and the average loss are both 0."
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
        self._prev: float | None = None
        self._gain = WilderAverage(self._n)
        self._loss = WilderAverage(self._n)

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return int_param(params, "n") + 1

    def update(self, bar: BarInput) -> Outputs:
        x, prev = bar.close, self._prev
        self._prev = x
        if prev is None:
            return (None,)
        d = x - prev
        gain = self._gain.update(d if d > 0.0 else 0.0)
        loss = self._loss.update(-d if d < 0.0 else 0.0)
        if gain is None or loss is None:
            return (None,)
        total = gain + loss
        return (100.0 * gain / total if total > 0.0 else None,)

    def _dump(self) -> State:
        return {"prev": self._prev, "gain": self._gain.dump(), "loss": self._loss.dump()}

    def _load(self, state: State) -> None:
        prev = as_optional_float(state["prev"])
        gain, loss = WilderAverage(self._n), WilderAverage(self._n)
        gain.load(state["gain"])
        loss.load(state["loss"])
        self._prev, self._gain, self._loss = prev, gain, loss
