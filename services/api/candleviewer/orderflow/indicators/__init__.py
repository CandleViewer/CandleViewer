"""Indicator kernels of M9 `orderflow` (E13-T02; ADR-0034; 24-internal-schemas §7).

The authoritative backend kernels of the `compute: server` indicators: pure float64 folds over
closed bars (`kernel`, `kernels`), their identity (`identity.spec_hash`), and the C3 Decimal
boundary (`boundary.to_decimal`). Nothing here imports M8 `bars` (see `types`).
"""

from __future__ import annotations

from candleviewer.orderflow.indicators.boundary import to_decimal
from candleviewer.orderflow.indicators.identity import (
    INDICATOR_SPEC_VERSION,
    IndicatorSpec,
    canonical_json,
    compute_spec_hash,
)
from candleviewer.orderflow.indicators.kernel import STATE_VERSION, Kernel
from candleviewer.orderflow.indicators.kernels import KERNELS, build_kernel, compute, kernel_class
from candleviewer.orderflow.indicators.types import (
    BarInput,
    BarLike,
    KernelContext,
    Unavailable,
    bar_input,
)

__all__ = [
    "INDICATOR_SPEC_VERSION",
    "KERNELS",
    "STATE_VERSION",
    "BarInput",
    "BarLike",
    "IndicatorSpec",
    "Kernel",
    "KernelContext",
    "Unavailable",
    "bar_input",
    "build_kernel",
    "canonical_json",
    "compute",
    "compute_spec_hash",
    "kernel_class",
    "to_decimal",
]
