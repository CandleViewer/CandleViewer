"""Shared helpers for the indicator engine tests (E13-T02, #426): bars, emissions through the
series store then the engine (the emit router's order), and a recording listener."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.indicators.engine import (
    Batch,
    IndicatorEngine,
    Reprime,
    Requested,
    resolve_instances,
)

SYM: Final = "BTCUSDT"
M1: Final = BarSpec(kind="time", interval_ms=60_000)
S1: Final = BarSpec(kind="time", interval_ms=1_000)
T5: Final = BarSpec(kind="tick", tick_count=5)
#: 2026-10-05 00:00 UTC in microseconds.
T0: Final = 1_791_158_400_000_000

ATR14: Final = [{"indicator": "atr", "params": {"n": 14}}]
EMA3: Final = [{"indicator": "ema", "params": {"n": 3}}]


def _d(x: float) -> Decimal:
    return Decimal(repr(x))


def bar(
    index: int,
    close: float = 100.0,
    *,
    spec: BarSpec = M1,
    slot: int | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1.0,
    delta: float = 0.0,
) -> Bar:
    """A closed bar `index` of `spec`, opening `slot` (default `index`) steps after `T0`."""
    step = int(spec.interval_ms or 60_000) * 1_000
    t = T0 + (index if slot is None else slot) * step
    c, v = _d(close), _d(volume)
    h = _d(close if high is None else high)
    lo = _d(close if low is None else low)
    return Bar.model_construct(
        spec_hash=spec.spec_hash, symbol=SYM, index=index, open_time=t, close_time=t + step,
        open=c, high=h, low=lo, close=c, volume=v, buy_volume=v, sell_volume=Decimal(0),
        delta=_d(delta), min_delta=Decimal(0), max_delta=_d(delta), trade_count=1,
        turnover=c * v, vwap=c, closed=True, partial=False, gap_before=False,
    )  # fmt: skip


def wave(index: int, **kw: Any) -> Bar:
    """A bar on a deterministic zig-zag with a range, so every kernel has values to move."""
    c = 100.0 + (index % 7) * 1.5 - (index % 3) * 0.75
    return bar(index, c, high=c + 1.25 + index % 2, low=c - 0.5 - index % 4 * 0.25, **kw)


async def close(
    store: SeriesStore,
    engine: IndicatorEngine,
    b: Bar,
    *,
    spec: BarSpec = M1,
    generation: int = 0,
    amended: bool = False,
) -> None:
    """One close through the store, then the engine: the emit router's order."""
    update = BarUpdate.model_construct(kind="close", bar=b, amended=amended)
    emission = BarEmission(spec, generation, (update,))
    await store.emit(emission)
    await engine.emit(emission)


def admit(
    engine: IndicatorEngine,
    raw: Sequence[Mapping[str, Any]],
    *,
    spec: BarSpec = M1,
    consumer: str = "c1",
    user: str | None = "u1",
    history: int = 500,
) -> tuple[Requested, ...]:
    requested = resolve_instances(raw, spec)
    engine.admit(SYM, spec, requested, consumer, user, history=history)
    return requested


class Listener:
    """Records what the engine reports, in order."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def points(self, symbol: str, spec: BarSpec, batches: Mapping[str, Batch]) -> None:
        self.events.append(("points", dict(batches)))

    def resnapshot(self, symbol: str, spec: BarSpec, reason: Reprime) -> None:
        self.events.append(("resnapshot", reason))

    def ready(self, symbol: str, spec: BarSpec) -> None:
        self.events.append(("ready", spec.spec_hash))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]


def counter(metric: Any) -> float:
    """A counter child's (or an unlabelled counter's) current value."""
    return float(metric._value.get())
