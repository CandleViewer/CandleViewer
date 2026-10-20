"""Shared helpers for the indicator engine tests (E13-T02, #426): bars, emissions through the
series store then the engine (the emit router's order), a recording listener, and deep instances
primed on a dense one-second series."""

from __future__ import annotations

import asyncio
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import Hold, SeriesStore
from candleviewer.orderflow.indicators.engine import (
    Batch,
    IndicatorEngine,
    Reprime,
    Requested,
    resolve_instances,
)
from candleviewer.orderflow.indicators.leases import InstanceLeases
from candleviewer.orderflow.indicators.types import BarInput, bar_input

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


def instances(engine: IndicatorEngine, spec: BarSpec = M1, symbol: str = SYM) -> int:
    """Instances running on a series, in their grace too (white box: no caller needs a count)."""
    return len(engine._series.get((symbol, spec.spec_hash), {}))


def holders(leases: InstanceLeases, key: tuple[str, str]) -> int:
    """Leases held on an instance (white box, as `instances`)."""
    entry = leases._held.get(key)
    return 0 if entry is None else len(entry.holders)


@dataclass(frozen=True)
class Primed:
    store: SeriesStore
    hold: Hold
    engine: IndicatorEngine
    requested: tuple[Requested, ...]
    bars: list[Bar]


async def primed(raw: Sequence[Mapping[str, Any]], *, stored: int, live: int = 0) -> Primed:
    """`raw`, a system consumer's instances, on a dense one-second series (`wave` bars) whose
    generation holds `stored` closes: the series store holds the newest 1 000, and a full
    recompute reads the rest (a slice of the bars, converted once up front: a one-second series
    has no stored rows, as `bar_row` persists wire intervals only). Then `live` more closes."""
    bars = [wave(i, spec=S1) for i in range(stored + live)]
    inputs = [(b.index, bar_input(b)) for b in bars[:stored]]
    opens = [b.open_time for b in bars[:stored]]

    async def read(
        symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> list[tuple[int, BarInput]]:
        return inputs[bisect_left(opens, start_us) : bisect_left(opens, end_us)]

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        newest = bars[:stored][-limit:]
        return BarTail([(0, b) for b in newest], since_us=0, fetched=len(newest))

    store = SeriesStore(tail)
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store, history=read)
    requested = resolve_instances(raw, S1)
    engine.admit(SYM, S1, requested, "c1", None, history=500)
    await asyncio.gather(*list(engine._tasks))
    for b in bars[stored:]:
        await close(store, engine, b, spec=S1)
    return Primed(store, hold, engine, requested, bars)


def late(p: Primed, age: int) -> Bar:
    """A late trade's re-close, with another close, of the bar `age` seconds before the newest.
    White box: it is the seventh bar after a checkpoint in every instance's ring, the worst
    offset: each replay starts seven bars before it."""
    target = p.bars[-1 - age]
    for r in p.requested:
        ring = p.engine._instances[(SYM, r.key)].ring
        near = [e for e in ring if target.index - 7 <= e.index <= target.index]
        assert [e.checkpoint is not None for e in near] == [True] + [False] * 7
    return target.model_copy(update={"close": target.close + 1})
