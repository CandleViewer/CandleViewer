"""The bars path in a soak lane (#399 D2-G4): bar builders and the WS series store at the cap.

With `LaneConfig.bars_specs`, each lane composes for its symbol what `create_app` composes
(`bars_wiring.wire_bars`): a `BarBuilderSet` on the lane's bus, fed by the lane's
`TradeStream`, emitting through an `EmitRouter` to a `SeriesStore` and then E13's indicator engine
(the sink, #399). The store holds `bars_specs` series (`SPECS`: the per-symbol cap of 32 at most),
each hydrated with `bars_per_series` stored bars (the 1 000-bar cap at most) through the production
`BarReader.read_tail`. A system consumer hydrates each series (`ensure`) and registers it with the
bar set (`register`): no per-user cap is measured.

- **Stored tail:** `_Table` answers `read_tail`'s statements as a QuestDB `bars_*` table would. Its
  rows take their values from the closed golden bars (`packages/fixtures/golden/bars`, built by the
  production builders from the recorded capture, C-13.5), encoded by the production row mapping
  (`bar_row`; the read verifies each checksum), in `GENERATION` and ending before the feed starts.
  It keeps no row: a read builds its rows and drops them, as a fetch's records go. A kind's table
  holds `per_series` rows for each of `SPECS`' series of the kind (6 000 at most for a non-time
  kind: 6 series of 1 000 rows), far fewer than `MAX_TAIL_SCAN_ROWS`, so the table-row bound (D2-M4)
  finds no row and every read starts at its window start, as before that bound.
- **Restart at the cap:** each builder restores from a state blob that resumes it at bar
  `bars_per_series` of `GENERATION` (`_resumed`), the steady state after a restart: the store holds
  the stored tail and folds each live close onto it, the oldest bar dropped past the cap.
- **Clock:** the lane's virtual clock is the set's and the reader's; the engine calls `tick` once a
  second of it (the set's ticker cadence: clock closes, the 60 s state blobs).
- **Judged by:** budget #8's figure (R1) and its flatness from hour 2 (R2), the cap checks (R3) and,
  on the full profile, the plateau (R4): the Theil-Sen slope of the RSS the lanes add per symbol
  over the last 12 h of scenario time, at most 0.18 MB/h, MB a MiB (`budgets.check_plateau`; the
  flatness band alone admits about 0.42). The smoke has no such window.
- **Inert series:** the five `delta` series never close here. The feed alternates buy and sell
  prints of 0.001 (`Lane._trade_frame`), so a draft's |delta| stays at or under 0.001, and a delta
  bar closes only once |delta| reaches its threshold, which is 1 or more on the wire. Their
  5 x 1 000 hydrated bars are in the level; their fold path is not exercised, and they add nothing
  to `bars_closes_folded`.
- **Not composed**, with what each leaves out of budget #8's figure:
  - the bar writer: its queue (10 000 rows, about 10-17 MiB full) and its source-precedence map
    (the last 200 000 row keys, about 70 MiB at that cap, reached after about 15 h with 3
    symbols). Both are process-wide, not per series: up to about 85 MiB, all on one symbol in a
    one-symbol process;
  - the WS publisher (a small fixed record per series; with no subscriber, no frame);
  - the heal driver (it reads only a series not hydrated or gapped; these hydrate once and take
    every close in index order);
  - the tape (`StorageTape`): no watermark replay and no `ahead_of_tape` check on a restore;
  - `start()`: its `sweep_tmp` and its ticker (the engine drives `tick` directly);
  - the one set and one store the app shares across symbols: a lane has its own pair per symbol,
    so `CAP_GLOBAL` (512 series) is never approached;
  - the indicators sink's collaborators: the lane composes the engine as `wire_bars` does (after the
    store, its repair hook on the store's) but with no history reader and no listener, so no
    indicator instance is created and no frame is built.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Final

import orjson

from bench.ingestion.engine import T0_MS, stop_each
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
from candleviewer.orderflow.indicators.engine import IndicatorEngine

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
    stored tail's end. `fetch` answers `read_tail`'s three statements (module docstring)."""

    def __init__(self, templates: list[dict[str, object]], symbol: str, per_series: int) -> None:
        self._templates, self._symbol, self._n = templates, symbol, per_series
        self._specs = {bar_param_for(s): s for s in SPECS}

    def _stamps(self, spec: BarSpec) -> range:
        """The `ts` of the series' rows, oldest first: the newest a step before the tail's end."""
        step = _step_us(spec)
        end = HISTORY_END_US // step * step
        return range(end - self._n * step, end, step)

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        """The series' rows from the `ts` bind on, newest first, at most the `LIMIT`; the series
        bound's statement takes their `ts` only. The table-row bound's (one bind, D2-M4) is the
        `ts` of the kind's rows at or after the bind, of any series, newest first, from the
        `LIMIT`'s offset to its end (`LIMIT k - 1, k`: the k-th newest), or none."""
        if len(params) == 1:
            kind = sql.split(" FROM bars_", 1)[1].split(" ", 1)[0]
            lo, hi = (int(n) for n in sql.rsplit(" LIMIT ", 1)[1].split(", "))
            since0 = ts_us_from_row(params[0])
            stamps = sorted(
                (t for s in SPECS if s.kind == kind for t in self._stamps(s) if t >= since0),
                reverse=True,
            )
            return [{"ts": t} for t in stamps[lo:hi]]
        param, since = str(params[1]), ts_us_from_row(params[2])
        spec, limit = self._specs[param], int(sql.rsplit(" LIMIT ", 1)[1])
        step, stamps_of_series = _step_us(spec), self._stamps(spec)
        out: list[dict[str, object]] = []
        for i in range(self._n - 1, max(-1, self._n - 1 - limit), -1):
            ts = stamps_of_series[i]
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
    harness's, not a lane's); `lane` builds one lane's bars path, hydrated. The lanes' state blobs
    go under `state_root` (a test's `tmp_path`), else to a temp dir each lane removes when it stops.
    """

    def __init__(self, specs: int, per_series: int, state_root: Path | None = None) -> None:
        if not 0 < specs <= CAP_PER_SYMBOL or not 0 < per_series <= MAX_HISTORY:
            raise ValueError(f"bars path: 1-{CAP_PER_SYMBOL} specs of 1-{MAX_HISTORY} bars each")
        self.specs, self.per_series, self.templates = SPECS[:specs], per_series, _templates()
        self.state_root = state_root

    async def lane(self, symbol: str, bus: Bus, clock: Callable[[], int]) -> BarsLane:
        lane = BarsLane(self, symbol, bus, clock, self.state_root)
        try:
            for spec in self.specs:
                await lane.states.save(_resumed(spec, symbol, self.per_series))
                lane.holds.append(await lane.store.ensure(symbol, spec))
                await lane.set.register(spec, symbol, "bench-bars")
        except BaseException:
            await stop_each([lane])  # the caller never gets it to stop: its task, holds, temp dir
            raise
        return lane


class BarsLane:
    """One symbol's bar builders and series store (module docstring)."""

    def __init__(
        self,
        fx: BarsFixture,
        symbol: str,
        bus: Bus,
        clock: Callable[[], int],
        state_root: Path | None = None,
    ) -> None:
        self.symbol, self._fx = symbol, fx
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        if state_root is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="cv-bench-bars-")
            state_root = Path(self._tmp.name)
        self._stopped: tuple[int, tuple[str, ...]] | None = None
        reader = BarReader(_Table(fx.templates, symbol, fx.per_series), _no_rebuild, now_us=clock)
        self.store = SeriesStore(reader.read_tail)
        self.states = StateStore(state_root)
        # E13-T02 (#426) as `wire_bars` composes it: the engine on the emit path after the store,
        # primed from it, its repair hook on the store's. No history reader (no database in the
        # lane) and no listener (no WS publisher, so no subscriber and no frame).
        self.indicators = IndicatorEngine(self.store, now_us=clock)
        self.store.on_repair(self.indicators.history_repair)
        self.set = BarBuilderSet(
            bus,
            "demo",
            EmitRouter([self.store, self.indicators]),
            self.states,
            now_us=clock,
            factory=FACTORY,
        )
        self.holds: list[Hold] = []

    async def tick(self) -> None:
        await self.set.tick()

    def _closed(self, spec: BarSpec) -> list[Bar]:
        got = self.store.latest(self.symbol, spec.spec_hash, MAX_HISTORY + 1)
        return [] if got is None else got.closed

    def count(self) -> tuple[int, int]:
        """The closed bars the store holds over the lane's series, and the live closes it folded
        past the stored tail (the indexes above its last bar)."""
        held = folded = 0
        for spec in self._fx.specs:
            closed = self._closed(spec)
            held += len(closed)
            if closed:
                folded += max(0, closed[-1].index + 1 - self._fx.per_series)
        return held, folded

    def fewest(self) -> int:
        """The fewest closed bars any one of the lane's series holds. A series only grows from its
        stored tail, so one below it was reset or never hydrated: a sum over the series hides that
        whenever another has grown past the tail."""
        return min(len(self._closed(spec)) for spec in self._fx.specs)

    async def stop(self) -> tuple[int, tuple[str, ...]]:
        """Stop the set (its queued trades applied, final blobs written) and release the holds,
        once: a second call returns the first's answer. The answer is the live closes folded past
        the stored tail and the set's health reasons, read after the drain (which can still
        quarantine a builder): one live builder folds closes whatever the others did."""
        if self._stopped is None:
            await self.indicators.stop()
            await self.set.stop()
            reasons = tuple(str(reason) for reason in self.set.health_reasons())
            self._stopped = (self.count()[1], reasons)
            for hold in self.holds:
                hold.release()
            if self._tmp is not None:
                self._tmp.cleanup()
        return self._stopped
