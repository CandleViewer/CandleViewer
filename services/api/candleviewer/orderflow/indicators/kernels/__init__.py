"""The server kernels (the nine `compute: server` indicators of ADR-0034, decision 1, and the
assignment table of `docs/plan/spikes/e13-o4.md` §5) and the `delta` pass-through behind the
`delta` and `cvd` metrics (#426).

`compute()` is the full form: a fresh kernel folded over a window, the same code path as
incremental `update()` calls, so the two cannot disagree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final

from candleviewer.orderflow.errors import UnknownIndicatorError
from candleviewer.orderflow.indicators.kernel import Kernel
from candleviewer.orderflow.indicators.kernels.ma import EmaKernel, SmaKernel
from candleviewer.orderflow.indicators.kernels.momentum import RsiKernel
from candleviewer.orderflow.indicators.kernels.trend import ZigzagKernel
from candleviewer.orderflow.indicators.kernels.volatility import AdxKernel, AtrKernel
from candleviewer.orderflow.indicators.kernels.volume import (
    CvdKernel,
    DeltaKernel,
    VolumeKernel,
    VwapKernel,
)
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue

KERNELS: Final[Mapping[str, type[Kernel]]] = MappingProxyType(
    {
        k.indicator: k
        for k in (
            SmaKernel,
            EmaKernel,
            RsiKernel,
            AtrKernel,
            AdxKernel,
            VwapKernel,
            CvdKernel,
            VolumeKernel,
            ZigzagKernel,
            DeltaKernel,
        )
    }
)


def kernel_class(indicator: str) -> type[Kernel]:
    """The kernel class of a server indicator; `UnknownIndicatorError` otherwise."""
    try:
        return KERNELS[indicator]
    except KeyError:
        raise UnknownIndicatorError("No server kernel exists for that indicator.") from None


def build_kernel(
    indicator: str,
    params: Mapping[str, ParamValue],
    *,
    source: str | None,
    context: KernelContext | None = None,
) -> Kernel:
    """A fresh kernel; params must be complete (defaults written out) and in its domain."""
    return kernel_class(indicator)(params, source=source, context=context)


def compute(
    indicator: str,
    bars: Iterable[BarInput],
    params: Mapping[str, ParamValue],
    *,
    source: str | None,
    context: KernelContext | None = None,
) -> list[Outputs]:
    """Full form: one fresh kernel folded over `bars`, one output tuple per bar."""
    return build_kernel(indicator, params, source=source, context=context).run(bars)


__all__ = [
    "KERNELS",
    "AdxKernel",
    "AtrKernel",
    "CvdKernel",
    "DeltaKernel",
    "EmaKernel",
    "RsiKernel",
    "SmaKernel",
    "VolumeKernel",
    "VwapKernel",
    "ZigzagKernel",
    "build_kernel",
    "compute",
    "kernel_class",
]
