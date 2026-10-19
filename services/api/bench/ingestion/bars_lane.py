"""The bars path in a soak lane (#399 D2-G4): bar builders and the WS series store at the cap.

With `LaneConfig.bars_specs`, each lane composes for its symbol what `create_app` composes with
`bars_enabled` on (`bars_wiring.wire_bars`): a `BarBuilderSet` on the lane's bus, fed by the lane's
`TradeStream`, emitting through an `EmitRouter` to a `SeriesStore` that holds `bars_specs` series
(`SPECS`: the per-symbol cap of 32 at most), each hydrated with `bars_per_series` stored bars (the
1 000-bar cap at most) through the production `BarReader.read_tail`. Each series is subscribed in
the WS path's order (`ensure`, then `register`) by a system consumer: no per-user cap is measured.

- **Stored tail:** `_Table` answers `read_tail`'s statements as a QuestDB `bars_*` table would. Its
  rows take their values from the closed golden bars (`packages/fixtures/golden/bars`, built by the
  production builders from the recorded capture, C-13.5), encoded by the production row mapping
  (`bar_row`; the read verifies each checksum), in `GENERATION` and ending before the feed starts.
  It keeps no row: a read builds its rows and drops them, as a fetch's records go.
- **Restart at the cap:** each builder restores from a state blob that resumes it at bar
  `bars_per_series` of `GENERATION` (`_resumed`), the steady state after a restart: the store holds
  the stored tail and folds each live close onto it, the oldest bar dropped past the cap.
- **Clock:** the lane's virtual clock is the set's and the reader's; the engine calls `tick` once a
  second of it (the set's ticker cadence: clock closes, the 60 s state blobs).
- Not composed: the WS publisher (a small fixed record per series; with no subscriber, no frame),
  the bar writer (its buffer is bounded process-wide, not per series) and the heal driver (it reads
  only a series not hydrated or gapped; these hydrate once and take every close in index order).
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Final

import orjson

from bench.ingestion.engine import T0_MS
from candleviewer.bars.builder_set import BarBuilderSet, production_factory
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.leases import CAP_PER_SYMBOL
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader
from candleviewer.bars.rows import BUILD_VERSIONS, bar_param_for, bar_row, row_checksum
from candleviewer.bars.series_store import MAX_HISTORY, Hold, SeriesStore
from candleviewer.bars.spec import from_wire
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bus.bus import Bus
from candleviewer.domain.sql_names import ts_us_from_row

GOLDEN: Final = Path(__file__).resolve().parents[4] / "packages" / "fixtures" / "golden" / "bars"
#: The series' epoch began a day before the feed (a cold start's generation is its wall time in
#: ms, #2662). The stored tail ends a second before the feed's first trade.
GENERATION: Final = T0_MS - 86_400_000
HISTORY_END_US: Final = T0_MS * 1_000 - 1_000_000
#: Non-time bars of the stored tail open a minute apart: 1 000 span under 17 h of the 31-day window.
NON_TIME_STEP_US: Final = 60_000_000
#: A subscriber's 32 series on one symbol, as `bars.*` wire pairs, the quickest to close first. Time
#: stops at 6 h, whose tail window (`tail_window_us`) holds 1 000 bars; renko is off (its flag).
WIRE: Final = (
    *(("tick", p) for p in ("100", "200", "300", "500", "1000", "2000")),
    *(("time", p) for p in ("1", "3", "5", "15", "30", "60", "120", "240", "360")),
    *(("volume", p) for p in ("1", "2", "5", "10", "25", "50")),
    *(("range", p) for p in ("2", "3", "5", "10", "20", "50")),
    *(("delta", p) for p in ("1", "2", "5", "10", "25")),
)
SPECS: Final = tuple(from_wire(kind, param) for kind, param in WIRE)
#: The synthetic market's price grid (`SyntheticMarket`: ticks / 10) is the range builders' tick.
FACTORY: Final = production_factory(lambda _symbol: Decimal("0.1"), renko_enabled=False)


def _templates() -> list[dict[str, object]]:
    """Every closed golden bar as a stored row (`bar_row`), in `GENERATION`."""
    rows: list[dict[str, object]] = []
    for path in sorted(GOLDEN.glob("*_bars_BTCUSDT.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            doc = json.loads(line)
            doc.pop("spec")
            if doc["closed"]:
                rows.append(bar_row(Bar.model_validate(doc), SPECS[0], generation=GENERATION))
    return rows


def _step_us(spec: BarSpec) -> int:
    return int(spec.param_value) * 1_000 if spec.kind == "time" else NON_TIME_STEP_US


def _resumed(spec: BarSpec, symbol: str, index: int) -> StoredState:
    """A state blob that resumes `spec`'s builder at bar `index` of `GENERATION`, as the set
    persists one: its fresh state with the next index moved (`next_index` for time bars, `next` for
    every other kind; any other layout raises), the watermark at the stored tail's end."""
    state = FACTORY(spec, symbol).snapshot()
    doc = orjson.loads(state.blob)
    (key,) = {"next_index", "next"} & doc.keys()
    doc[key] = index
    blob = state.model_copy(update={"blob": orjson.dumps(doc)})
    return StoredState(blob, Watermark(HISTORY_END_US - 1, frozenset()), GENERATION)


async def _no_rebuild(symbol: str, spec_hash: str, from_us: int, to_us: int) -> None:
    """Every stored row is at the running `build_version`: no rebuild is ever scheduled."""


class _Table:
    """The `bars_*` rows of one lane's series: `per_series` each, the newest a step before the
    stored tail's end. `fetch` answers `read_tail`'s two statements (module docstring)."""

    def __init__(self, templates: list[dict[str, object]], symbol: str, per_series: int) -> None:
        self._templates, self._symbol, self._n = templates, symbol, per_series
        self._specs = {bar_param_for(s): s for s in SPECS}

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        """The series' rows from the `ts` bind on, newest first, at most the `LIMIT`; the bound's
        statement takes their `ts` only."""
        param, since = str(params[1]), ts_us_from_row(params[2])
        spec, limit = self._specs[param], int(sql.rsplit(" LIMIT ", 1)[1])
        step = _step_us(spec)
        end = HISTORY_END_US // step * step
        out: list[dict[str, object]] = []
        for i in range(self._n - 1, max(-1, self._n - 1 - limit), -1):
            ts = end - (self._n - i) * step
            if ts < since:
                break
            if sql.startswith("SELECT ts "):
                out.append({"ts": ts})
                continue
            row = {**self._templates[i % len(self._templates)], "ts": ts, "close_ts": ts + step - 1}
            row.update(symbol=self._symbol, bar_param=param, index=i)
            row["build_version"] = BUILD_VERSIONS[spec.kind]
            row["row_checksum"] = row_checksum(row)
            out.append(row)
        return out


class BarsFixture:
    """The specs and the recorded rows, loaded once a run, before the pre-lanes RSS sample (the
    harness's, not a lane's); `lane` builds one lane's bars path, hydrated."""

    def __init__(self, specs: int, per_series: int) -> None:
        if not 0 < specs <= CAP_PER_SYMBOL or not 0 < per_series <= MAX_HISTORY:
            raise ValueError(f"bars path: 1-{CAP_PER_SYMBOL} specs of 1-{MAX_HISTORY} bars each")
        self.specs, self.per_series, self.templates = SPECS[:specs], per_series, _templates()

    async def lane(self, symbol: str, bus: Bus, clock: Callable[[], int]) -> BarsLane:
        lane = BarsLane(self, symbol, bus, clock)
        for spec in self.specs:
            await lane.states.save(_resumed(spec, symbol, self.per_series))
            lane.holds.append(await lane.store.ensure(symbol, spec))
            await lane.set.register(spec, symbol, "bench-bars")
        return lane


class BarsLane:
    """One symbol's bar builders and series store (module docstring)."""

    def __init__(self, fx: BarsFixture, symbol: str, bus: Bus, clock: Callable[[], int]) -> None:
        self.symbol, self._fx = symbol, fx
        self._dir = tempfile.TemporaryDirectory(prefix="cv-bench-bars-")
        reader = BarReader(_Table(fx.templates, symbol, fx.per_series), _no_rebuild, now_us=clock)
        self.store = SeriesStore(reader.read_tail)
        self.states = StateStore(Path(self._dir.name))
        self.set = BarBuilderSet(
            bus, "demo", EmitRouter([self.store]), self.states, now_us=clock, factory=FACTORY
        )
        self.holds: list[Hold] = []

    async def tick(self) -> None:
        await self.set.tick()

    def count(self) -> tuple[int, int]:
        """The closed bars the store holds over the lane's series, and the live closes it folded
        past the stored tail (the indexes above its last bar)."""
        held = folded = 0
        for spec in self._fx.specs:
            got = self.store.latest(self.symbol, spec.spec_hash, MAX_HISTORY + 1)
            if got is not None and got.closed:
                held += len(got.closed)
                folded += max(0, got.closed[-1].index + 1 - self._fx.per_series)
        return held, folded

    async def stop(self) -> int:
        """Stop the set (its queued trades applied, final blobs written); the closes folded."""
        await self.set.stop()
        folded = self.count()[1]
        for hold in self.holds:
            hold.release()
        self._dir.cleanup()
        return folded
