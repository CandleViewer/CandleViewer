"""Test-only scalar kernels of the client-worker moving averages (E13-S02, #424; 24 §7.4).

`wma`, `vwma`, `smma`, `dema`, `tema` and `ma_ribbon` are `compute: client_worker` (ADR-0034
rule 1): no production kernel, so nothing here is in `KERNELS` or `SERVER_DEFINITIONS`. These
classes hold the operation order the TS worker plugins follow, so the golden vectors can pin it
bit for bit and a parity test can hold the TS mirror to it. Each fold reads the applied price
`x` and the bar volume `w` and returns its raw value, `None` while undefined; `offset` then
displaces the line (`OffsetLine`, the production helper), and the ribbon runs five folds.

Orders (24 §7.4, left to right):

- WMA: `u` and `s` run over the window. While it fills (bar `k < n`): `u = u + (k + 1) * x`,
  `s = s + x`. Once full: `u = u - s + n * x` with the old `s`, then `s = s - leaving + x`. The
  value is `u / (n * (n + 1) / 2)` from bar `n - 1`.
- VWMA: running `sw` (of `x * w`) and `sv` (of `w`), kept like SMA's sum, and an exact count `nz`
  of window bars with `w > 0`. While `nz = 0` both are reset to `0.0` and the value is `None`;
  else `sw / sv`.
- SMMA: `WilderAverage`. DEMA: `2 * e1 - e2`. TEMA: `3 * e1 - 3 * e2 + e3`; each inner EMA is an
  `ExponentialAverage` seeded on the first `n` values of the one before.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import ClassVar, Final

from candleviewer.orderflow.indicators.kernel import (
    ExponentialAverage,
    OffsetLine,
    WilderAverage,
    applied_price,
    choice_param,
    int_param,
)
from candleviewer.orderflow.indicators.limits import MA_SOURCES
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue

#: Each average's first value on bar `scale * n + offset` (24 7.4).
SHAPES: Final = {
    "sma": (1, 0), "ema": (1, 0), "wma": (1, 0), "vwma": (1, 0), "smma": (1, 0),
    "dema": (2, -1), "tema": (3, -2),
}  # fmt: skip


class Fold:
    """One moving average over (price, volume) pairs."""

    def update(self, x: float, w: float) -> float | None:
        raise NotImplementedError


class SmaFold(Fold):
    def __init__(self, n: int) -> None:
        self._n, self._k, self._sum, self._ring = n, 0, 0.0, [0.0] * n

    def update(self, x: float, w: float) -> float | None:
        j = self._k % self._n
        if self._k >= self._n:
            self._sum = self._sum - self._ring[j]
        self._ring[j] = x
        self._sum = self._sum + x
        self._k += 1
        return self._sum / self._n if self._k >= self._n else None


class EmaFold(Fold):
    def __init__(self, n: int) -> None:
        self._avg = ExponentialAverage(n)

    def update(self, x: float, w: float) -> float | None:
        return self._avg.update(x)


class SmmaFold(Fold):
    def __init__(self, n: int) -> None:
        self._avg = WilderAverage(n)

    def update(self, x: float, w: float) -> float | None:
        return self._avg.update(x)


class WmaFold(Fold):
    def __init__(self, n: int) -> None:
        self._n, self._k, self._u, self._s, self._ring = n, 0, 0.0, 0.0, [0.0] * n
        self._den = n * (n + 1) / 2

    def update(self, x: float, w: float) -> float | None:
        j = self._k % self._n
        if self._k >= self._n:
            self._u = self._u - self._s + self._n * x
            self._s = self._s - self._ring[j] + x
        else:
            self._u = self._u + (self._k + 1) * x
            self._s = self._s + x
        self._ring[j] = x
        self._k += 1
        return self._u / self._den if self._k >= self._n else None


class VwmaFold(Fold):
    def __init__(self, n: int) -> None:
        self._n, self._k, self._sw, self._sv, self._nz = n, 0, 0.0, 0.0, 0
        self._ring = [(0.0, 0.0)] * n

    def update(self, x: float, w: float) -> float | None:
        j = self._k % self._n
        if self._k >= self._n:
            old_w, old_v = self._ring[j]
            self._sw = self._sw - old_w
            self._sv = self._sv - old_v
            self._nz -= old_v > 0
        self._ring[j] = (x * w, w)
        self._sw = self._sw + x * w
        self._sv = self._sv + w
        self._nz += w > 0
        self._k += 1
        if self._nz == 0:
            self._sw = self._sv = 0.0
            return None
        return self._sw / self._sv if self._k >= self._n else None


class DemaFold(Fold):
    def __init__(self, n: int) -> None:
        self._e1, self._e2 = ExponentialAverage(n), ExponentialAverage(n)

    def update(self, x: float, w: float) -> float | None:
        e1 = self._e1.update(x)
        e2 = None if e1 is None else self._e2.update(e1)
        return None if e1 is None or e2 is None else 2 * e1 - e2


class TemaFold(Fold):
    def __init__(self, n: int) -> None:
        self._e1, self._e2, self._e3 = (ExponentialAverage(n) for _ in range(3))

    def update(self, x: float, w: float) -> float | None:
        e1 = self._e1.update(x)
        e2 = None if e1 is None else self._e2.update(e1)
        e3 = None if e2 is None else self._e3.update(e2)
        return None if e1 is None or e2 is None or e3 is None else 3 * e1 - 3 * e2 + e3


FOLDS: Final[Mapping[str, Callable[[int], Fold]]] = {
    "sma": SmaFold, "ema": EmaFold, "wma": WmaFold, "vwma": VwmaFold, "smma": SmmaFold,
    "dema": DemaFold, "tema": TemaFold,
}  # fmt: skip


class TestKernel:
    """The shape the golden harness reads from a kernel class."""

    __test__ = False  # not a pytest class

    indicator: ClassVar[str]
    outputs: ClassVar[tuple[str, ...]]
    build_version: ClassVar[int] = 1
    sources: ClassVar[tuple[str | None, ...]] = MA_SOURCES

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        self._price = choice_param(params, "source", MA_SOURCES)
        if source != self._price:
            raise ValueError("source must equal the source parameter")

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        raise NotImplementedError

    def update(self, bar: BarInput) -> Outputs:
        raise NotImplementedError

    def run(self, bars: Iterable[BarInput]) -> list[Outputs]:
        return [self.update(bar) for bar in bars]


class _Single(TestKernel):
    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        self._fold = FOLDS[self.indicator](int_param(params, "n"))
        self._line = OffsetLine(int_param(params, "offset", minimum=0))

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        scale, extra = SHAPES[cls.indicator]
        return scale * int_param(params, "n") + extra + int_param(params, "offset", minimum=0)

    def update(self, bar: BarInput) -> Outputs:
        raw = self._fold.update(applied_price(bar, self._price), bar.volume)
        return (self._line.push(raw),)


class WmaKernel(_Single):
    indicator = "wma"
    outputs = ("wma",)


class VwmaKernel(_Single):
    indicator = "vwma"
    outputs = ("vwma",)


class SmmaKernel(_Single):
    indicator = "smma"
    outputs = ("smma",)


class DemaKernel(_Single):
    indicator = "dema"
    outputs = ("dema",)


class TemaKernel(_Single):
    indicator = "tema"
    outputs = ("tema",)


class MaRibbonKernel(TestKernel):
    """Five folds of the chosen average at `n1`..`n5`; no offset."""

    indicator = "ma_ribbon"
    outputs = ("ma_1", "ma_2", "ma_3", "ma_4", "ma_5")

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        ma = choice_param(params, "ma", tuple(SHAPES))
        self._folds = [FOLDS[ma](int_param(params, f"n{i}")) for i in range(1, 6)]

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        scale, extra = SHAPES[choice_param(params, "ma", tuple(SHAPES))]
        return max(scale * int_param(params, f"n{i}") + extra for i in range(1, 6))

    def update(self, bar: BarInput) -> Outputs:
        x = applied_price(bar, self._price)
        return tuple(fold.update(x, bar.volume) for fold in self._folds)


TEST_KERNELS: Final[Mapping[str, type[TestKernel]]] = {
    k.indicator: k
    for k in (WmaKernel, VwmaKernel, SmmaKernel, DemaKernel, TemaKernel, MaRibbonKernel)
}
