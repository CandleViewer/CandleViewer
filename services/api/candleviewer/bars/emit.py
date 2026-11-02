"""The single bar emit path (E12-T03): every `BarUpdate` a builder produces, live or replayed,
goes through `EmitRouter.emit`, which hands the same emission, in the same order, to every sink.

Sinks are injected by the composition root, so `bars` gains no import edge: the QuestDB write
path is `WriterSink` around E12-T02's `BarWriter` (structurally typed), and the WS publisher
(E12-T06, not built yet) plugs in as another `BarSink`.

Backpressure policy (20 §4.2, `Bars lane → sinks`): `emit` awaits each sink in turn, bounded by
`timeout_s` per sink. A slow sink slows the symbol's fan-out loop and, through its `NEVER_DROP`
bus queue, the trade publisher, but for at most `timeout_s` per emission. After that the
emission is skipped for that sink, counted and reported as degraded health. Trades are never
dropped. A closed bar the writer does not take is recorded as a coverage hole (#5396,
`WriterSink`), served until stored and queued for heal by a rebuild (ADR-0033).
A sink that raises is counted (`bar_emit_sink_errors_total{reason=<sink>}`) and logged; the
other sinks still get the emission, and
`CancelledError` is never swallowed.

`generation` is stamped on every emission: the series' epoch (`BarBuilderSet._Entry.generation`).
A restored series keeps its blob's, a cold start begins a new one (#2662), so
`(bar_param, generation, index)` (#2019) does not repeat (barring the clock-regression residual
and a restore whose tape lost trades after the watermark, `builder_set.py`). `WriterSink` stores
it on every row, and `BarSubmitter.submit` has no default
for it, so an emission's generation cannot be dropped silently. An ADR-0033 rebuild (E12-S12,
not implemented) would write under a generation of its own and swap a pointer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import structlog

from candleviewer.bars.errors import BarsError
from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.rows import bar_param_for
from candleviewer.bars.write_holes import HoleKey, HoleRecorder

#: Per-sink emit bound (§4.2 `Bars lane → sinks` row).
SINK_TIMEOUT_S: Final = 5.0


@dataclass(frozen=True, slots=True)
class BarEmission:
    spec: BarSpec
    generation: int
    updates: Sequence[BarUpdate]


class BarSink(Protocol):
    name: str

    async def emit(self, emission: BarEmission) -> None: ...


class BarSubmitter(Protocol):
    """The slice of E12-T02 `BarWriter` this module needs."""

    async def submit(
        self, bars: Sequence[Bar], spec: BarSpec, *, source: str = ..., generation: int
    ) -> None: ...


class WriterSink:
    """Persists `close` emissions (amended closes included; DEDUP keeps the last write).

    Forming-bar `open`/`update` emissions are for the live wire only: writing one row per trade
    would multiply the QuestDB write rate by the trade rate for no reader.

    #5396: an emission whose closed bars the writer does not take has them recorded in `holes`
    before its exception propagates: reason `sink_timeout` when the emission is cancelled,
    `refused` otherwise. `abandon` records them as `shutdown` when the router is cancelled before
    it reaches this sink. Recording is synchronous. A bar the writer took is cleared again once
    it is stored.
    """

    name = "questdb"

    def __init__(self, writer: BarSubmitter, *, holes: HoleRecorder | None = None) -> None:
        self._writer = writer
        self._holes = holes

    async def emit(self, emission: BarEmission) -> None:
        closed = [u.bar for u in emission.updates if u.kind == "close"]
        if not closed:
            return
        try:
            await self._writer.submit(
                closed, emission.spec, source="tape", generation=emission.generation
            )
        except asyncio.CancelledError:
            self._record(closed, emission, "sink_timeout")
            raise
        except Exception:
            self._record(closed, emission, "refused")
            raise

    def abandon(self, emission: BarEmission) -> None:
        """The router was cancelled before this sink got `emission`: its closed bars are holes."""
        closed = [u.bar for u in emission.updates if u.kind == "close"]
        if closed:
            self._record(closed, emission, "shutdown")

    def _record(self, closed: list[Bar], emission: BarEmission, reason: str) -> None:
        if self._holes is None:
            return
        spec, gen = emission.spec, emission.generation
        try:
            param = bar_param_for(spec)
        except BarsError:  # a spec with no stored form: its key still names the series
            param = ""
        keys = [
            HoleKey(b.symbol, spec.spec_hash, spec.kind, param, gen, b.index, b.open_time,
                    b.close_time + 1)
            for b in closed if not b.synthetic
        ]  # fmt: skip
        self._holes.lost(keys, reason)


class EmitRouter:
    """`timeout_s` bounds each sink call. A sink that does not accept an emission in time
    is skipped for that emission, counted as `bar_emit_sink_errors_total{reason=<sink>_timeout}`
    and logged, and `timed_out` turns on (sticky; `BarBuilderSet` reports it as DEGRADED).
    The bound protects the trade publisher: without it, one hung sink would stall the lane,
    then the lane's `NEVER_DROP` queue, then every publisher of the symbol's trades.

    A cancellation of `emit` itself (a stop of the lane or the ticker) propagates, never
    swallowed; first every sink the emission has not reached yet that has a synchronous
    `abandon(emission)` hook gets it, so `WriterSink` records the closed bars it will not get
    (#5396). A hook that raises is logged and the others still run."""

    def __init__(self, sinks: Sequence[BarSink], *, timeout_s: float = SINK_TIMEOUT_S) -> None:
        self._sinks = tuple(sinks)
        self._timeout_s = timeout_s
        self.timed_out = False

    async def emit(self, spec: BarSpec, updates: Sequence[BarUpdate], generation: int) -> None:
        emission = BarEmission(spec, generation, updates)
        for n, sink in enumerate(self._sinks):
            try:
                async with asyncio.timeout(self._timeout_s):
                    await sink.emit(emission)
            except asyncio.CancelledError:  # not the bound: `asyncio.timeout` raises TimeoutError
                _abandon(self._sinks[n + 1 :], emission)
                raise
            except TimeoutError:
                self.timed_out = True
                bar_emit_sink_errors_total.labels(reason=f"{sink.name}_timeout").inc()
                structlog.get_logger(__name__).warning(
                    "bars_emit_sink_timeout", sink=sink.name, spec_hash=spec.spec_hash
                )
            except Exception as exc:  # one failing sink must not starve the others
                bar_emit_sink_errors_total.labels(reason=sink.name).inc()
                structlog.get_logger(__name__).warning(
                    "bars_emit_sink_failed",
                    sink=sink.name,
                    spec_hash=spec.spec_hash,
                    error_type=type(exc).__name__,
                )


def _abandon(sinks: Sequence[BarSink], emission: BarEmission) -> None:
    """Hand `emission` to the `abandon` hook of every sink in `sinks` that has one."""
    for sink in sinks:
        hook = getattr(sink, "abandon", None)
        if hook is None:
            continue
        try:
            hook(emission)
        except Exception as exc:  # the other sinks' hooks still run
            structlog.get_logger(__name__).error(
                "bars_emit_abandon_failed", sink=sink.name, error_type=type(exc).__name__
            )
