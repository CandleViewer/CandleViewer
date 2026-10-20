"""Inputs and result types of the indicator kernels (E13-T02, ADR-0034, 24-internal-schemas §7).

The kernels are float64 inside and `Decimal` outside (24-internal-schemas §1.1 C3). A bar
crosses into a kernel exactly once, through `bar_input()`: `float(Decimal)` is correctly
rounded, so it equals JavaScript `Number(str)` on the same decimal string and the TS worker
mirror reads bit-identical inputs (ADR-0034 rule 3). Values leave through
`boundary.to_decimal()`.

Nothing here imports M8 `bars`. M15 `rules` will import the indicator catalogue, and its
import-linter contract forbids reaching `bars` even indirectly, so `BarLike` is the structural
view of `bars.models.Bar` that the conversion needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, NamedTuple, Protocol

from candleviewer.orderflow.errors import IndicatorParamError

type ParamValue = bool | int | float | Decimal | str
"""A parameter value as a caller supplies it; `identity.canonical_number` normalises numbers."""

type Outputs = tuple[float | None, ...]
"""One value per declared output, in declaration order; `None` while the value is undefined."""

UnavailableReason = Literal["warmup", "nan", "stale", "parity_flagged", "missing"]
"""Why a value is not available (IR-45, SR-E13-12). The source side is E13-T02's."""

MINUTES_PER_DAY: Final = 1440


class BarLike(Protocol):
    """The fields of a closed bar (24-internal-schemas §3.1) that the kernels read."""

    @property
    def open_time(self) -> int: ...

    @property
    def open(self) -> Decimal: ...

    @property
    def high(self) -> Decimal: ...

    @property
    def low(self) -> Decimal: ...

    @property
    def close(self) -> Decimal: ...

    @property
    def volume(self) -> Decimal: ...

    @property
    def delta(self) -> Decimal: ...

    @property
    def synthetic(self) -> bool: ...


class BarInput(NamedTuple):
    """One bar as a kernel sees it: binary64 values, converted once at the boundary.

    `t` is the bar's `open_time` in microseconds UTC (C4). `delta` is the aggressor
    `buy_volume - sell_volume`. `synthetic` marks a `densify()` filler: it advances the
    kernel state like any bar, but the engine publishes no point for it, because it shares
    the preceding real bar's `index` (24-internal-schemas §3.1).
    """

    t: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float
    synthetic: bool


def bar_input(bar: BarLike) -> BarInput:
    """Convert a `Decimal` bar into kernel inputs (the inbound C3 boundary)."""
    return BarInput(
        bar.open_time,
        float(bar.open),
        float(bar.high),
        float(bar.low),
        float(bar.close),
        float(bar.volume),
        float(bar.delta),
        bar.synthetic,
    )


@dataclass(frozen=True, slots=True)
class KernelContext:
    """Series facts a kernel needs besides its params; all of them are part of the bar spec.

    `session_anchor_utc_min` is `BarSpec.session_anchor_utc_min`: a session starts that many
    minutes after 00:00 UTC. Session-anchored kernels (`vwap`, `cvd`) restart there.
    """

    session_anchor_utc_min: int = 0

    def __post_init__(self) -> None:
        anchor = self.session_anchor_utc_min
        if isinstance(anchor, bool) or not isinstance(anchor, int):
            raise IndicatorParamError("session_anchor_utc_min must be a whole number of minutes.")
        if not 0 <= anchor < MINUTES_PER_DAY:
            raise IndicatorParamError(
                f"session_anchor_utc_min must be between 0 and {MINUTES_PER_DAY - 1}."
            )


@dataclass(frozen=True, slots=True)
class Unavailable:
    """A typed "no value": `None` and NaN never cross the boundary as numbers (SR-E13-12)."""

    reason: UnavailableReason
