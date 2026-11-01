"""The bars half of the E12-Q06 chaos rig: a production `BarBuilderSet` on the ingestion `Rig`.

The ingestion `Rig` (production `wire_public_ws` composition over the stub exchange, virtual
clock, seeded) is used through its public attributes only: `bus`, `clock`, `ex`, `env`,
`clock_guard`, `host_now_us`, `observe()`, `health_report()` and `call()`. `BarBuilderSet` is
registered on its bus exactly as `wire_bars` registers it (same topic, same `EmitRouter`, same
`default_factory`), with a `CaptureSink` as the only sink: the store seam is E12-Q06 PR-2.

Deviations from the composition root (keep in sync with SCENARIOS.md):

* `BarBuilderSet.start()` is never called (it spawns a real-time ticker). `tick()` is driven
  from the virtual clock once per virtual second, which is what `_tick_loop` does.
* The set's "now" is `corrected_now_us(ClockGuard.offset_us, rig.host_now_us)`, the same
  composition as `app.exchange_corrected_clock` (unit-tested in `test_bars_clock_wiring.py`)
  over the rig's skewable host clock. `clock="raw"` is the pre-#529 wiring (the host clock
  alone) and exists only for the negative controls.
* No WS publisher or indicator engine: `CaptureSink` stands for the emit path. `extra_sinks`
  adds the store seam (`WriterSink` over a `BarWriter` over a `FlakyRowSink`, scenario 5).
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

from candleviewer.bars.builder_set import BarBuilderSet, default_factory
from candleviewer.bars.emit import BarSink, EmitRouter
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.state_store import StateStore
from candleviewer.ingestion.rejection import corrected_now_us
from tests.chaos.bars._sinks import CaptureSink
from tests.chaos.ingestion._feed import TICK_S, Feeder
from tests.chaos.ingestion._rig import Rig

SYMBOL = "BTCUSDT"
#: Virtual seconds between `tick()` calls: `builder_set.TICK_S`, what the real ticker sleeps.
BARS_TICK_S = 1.0
#: 5 s time bars (their boundaries fall on multiples of 5 s of the virtual wall clock) and
#: volume bars of 1 BTC (the corpus prints are 0.05-0.3 BTC, so a few prints close one).
TIME_5S = BarSpec(kind="time", interval_ms=5_000)
VOLUME_1 = BarSpec(kind="volume", volume_threshold=Decimal(1))
SPECS: dict[str, BarSpec] = {"time:5s": TIME_5S, "vol:1": VOLUME_1}

ClockSource = Literal["corrected", "raw"]


class BarsRig:
    """One `BarBuilderSet` per `Rig`, fed by the rig's own `TradeStream` on `rig.bus`."""

    def __init__(
        self,
        rig: Rig,
        specs: dict[str, BarSpec] | None = None,
        *,
        clock: ClockSource = "corrected",
        symbol: str = SYMBOL,
        extra_sinks: Sequence[BarSink] = (),
    ) -> None:
        self.rig = rig
        self.symbol = symbol
        self.specs = specs if specs is not None else SPECS
        self.sink = CaptureSink()
        self._root = tempfile.TemporaryDirectory(prefix="bars-chaos-")
        self.now_us = (
            corrected_now_us(rig.clock_guard.offset_us, rig.host_now_us)
            if clock == "corrected"
            else rig.host_now_us
        )
        self.set = BarBuilderSet(
            rig.bus,
            rig.env,
            EmitRouter([self.sink, *extra_sinks]),
            StateStore(Path(self._root.name)),
            now_us=self.now_us,
            factory=default_factory,
        )
        self._stopped = False

    async def start(self) -> None:
        for label, spec in self.specs.items():
            await self.set.register(spec, self.symbol, f"chaos:{label}")
        await self.rig.clock.settle()

    async def run(self, feed: Feeder, seconds: float) -> None:
        """Run the venue for `seconds` of virtual time, ticking the set every second.

        The tick follows the step's own frames (a print is stamped 5 ms before its frame, so
        a frame published at a bar's close time still belongs to that bar): it is the real
        ticker's behaviour with the venue's latency below one virtual step."""
        steps_per_tick = round(BARS_TICK_S / TICK_S)
        for n in range(round(seconds / TICK_S)):
            feed.step()
            await self.rig.clock.settle()
            if (n + 1) % steps_per_tick == 0:
                await self.set.tick()
            await self.rig.clock.advance(TICK_S)

    async def finish(self) -> None:
        """Settle, take the last clock tick, then stop the set (which drains its lane queue)."""
        if self._stopped:
            return
        self._stopped = True
        await self.rig.clock.settle()
        await self.set.tick()
        await self.set.stop()
        self._root.cleanup()

    def bars(self, label: str) -> list[Bar]:
        return self.sink.final_bars(self.specs[label].spec_hash)

    def amended(self, label: str) -> int:
        return len(self.sink.amended(self.specs[label].spec_hash))
