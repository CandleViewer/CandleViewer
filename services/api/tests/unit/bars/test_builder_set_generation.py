"""A builder cold start begins a new bar generation (#2662): `(generation, index)` does not repeat.

`24-internal-schemas.md` §3.5. A restored series keeps its blob's generation; a cold start takes
`max(now_ms, floor + 1)` (floor: the highest generation a parseable blob or this process knew) and
writes a floor record at once: the new generation with no watermark, so a restart never restores it.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import orjson
import pytest
from structlog.testing import capture_logs

from candleviewer.bars import builder_set
from candleviewer.bars.activity_builders import TickBarBuilder
from candleviewer.bars.builder_set import STATE_COLD_STARTED, BarBuilderSet
from candleviewer.bars.emit import BarEmission, WriterSink
from candleviewer.bars.models import Bar, BarSpec, BuilderState
from candleviewer.bars.rows import KLINE_GENERATION, MAX_GENERATION, BarPersistError, bar_row
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bars.writer import BarWriter
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.schemas import BAR_SCHEMAS_BY_FAMILY

from ._set_harness import (
    T3,
    TOPIC,
    Clock,
    FakeTape,
    RecordingSink,
    blob_discards,
    make_set,
    settle,
    write_failures,
)
from ._trades import SYM, trade, us

T0 = us("10:00:00")
COLD_US = T0 + 600_000_000  # the restart happens ten minutes later
COLD_MS = COLD_US // 1000
A2 = BarSpec(kind="tick", tick_count=2)  # the other series that keeps a lane busy


class _Rows:
    """`RowSink` stand-in: keeps the row dicts the writer hands to QuestDB."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self.rows.extend(rows)


def _ticks(lo: int, hi: int) -> list[TradeEvent]:
    """Trades `lo..hi-1`, one microsecond apart: three per `T3` bar."""
    return [trade(T0 + i, seq=i) for i in range(lo, hi)]


def _blob(root: Path) -> Path:
    return StateStore(root).path(SYM, T3.spec_hash)


async def _disk_full(_: StoredState) -> None:
    raise OSError(28, os.strerror(28))


async def _run(
    root: Path,
    now_us: int,
    trades: list[TradeEvent],
    *,
    tape: FakeTape | None = None,
    sinks: Sequence[object] = (),
    busy: bool = False,
) -> tuple[RecordingSink, BarBuilderSet]:
    """Register `T3` (restore or cold start, by what is on disk), publish, let the lane drain.
    `busy`: `A2` streams trades 0..2 first, so the lane already has a watermark."""
    bus, rec = Bus(), RecordingSink()
    s = make_set(root, bus=bus, sinks=[rec, *sinks], tape=tape, clock=Clock(now_us))
    if busy:
        await s.register(A2, SYM, "busy")
        for t in _ticks(0, 3):
            await bus.publish(TOPIC, t)
        await settle(bus, s)
    await s.register(T3, SYM, "c")
    for t in trades:
        await bus.publish(TOPIC, t)
    await settle(bus, s)
    return rec, s


async def _refused_blob(root: Path, refusal: str, recorded: int) -> FakeTape | None:
    """Leave T3's blob on disk with `recorded` as its generation, refused on the next start for
    `refusal`. Returns the tape that restart needs (`ahead_of_tape` only)."""
    _, s1 = await _run(root, T0, _ticks(0, 4))
    await s1.stop()
    doc = orjson.loads(_blob(root).read_bytes())
    doc["generation"] = recorded
    tape = None
    if refusal == "restore_failed":
        doc["state_version"] = 7  # the builder refuses it on restore
    else:
        tape = FakeTape(_ticks(0, 1))  # tape head T0 is behind the blob's watermark T0 + 3
    _blob(root).write_bytes(orjson.dumps(doc))
    return tape


def _keys(*runs: RecordingSink, spec_hash: str = T3.spec_hash) -> list[tuple[int, int]]:
    return [(g, i) for r in runs for h, g, k, i, _ in r.seen if h == spec_hash and k == "close"]


async def test_cold_start_after_stored_bars_never_repeats_a_key(tmp_path: Path) -> None:
    store = _Rows()
    writer = BarWriter(store)
    await writer.start()
    first, s1 = await _run(tmp_path, T0, _ticks(0, 7), sinks=[WriterSink(writer)])  # bars 0, 1
    await s1.stop()
    _blob(tmp_path).unlink()  # the restart finds no blob: a cold start
    second, s2 = await _run(tmp_path, COLD_US, _ticks(100, 107), sinks=[WriterSink(writer)])
    await s2.stop()
    assert await writer.stop() == 0
    wire = _keys(first, second)
    assert len(wire) == 4 and len(set(wire)) == 4  # bars 0 and 1 of both runs: four distinct keys
    assert [g for g, _ in wire] == [T0 // 1000] * 2 + [COLD_MS] * 2  # the later run is higher
    assert [(r["generation"], r["index"]) for r in store.rows] == wire  # stored rows agree


async def test_restore_keeps_the_blobs_generation_and_continues_the_index(tmp_path: Path) -> None:
    _, s1 = await _run(tmp_path, T0, _ticks(0, 4))  # bar 0 closed, bar 1 forming
    await s1.stop()
    second, s2 = await _run(tmp_path, COLD_US, _ticks(4, 7))  # a cold start now would differ
    await s2.stop()
    assert {g for _, g, *_ in second.seen} == {T0 // 1000}
    assert [i for _, i in _keys(second)] == [1]


@pytest.mark.parametrize("refusal", ["restore_failed", "ahead_of_tape"])
@pytest.mark.parametrize(
    ("recorded", "expected"), [(COLD_MS + 5_000_000, COLD_MS + 5_000_001), (7, COLD_MS)]
)
async def test_cold_start_after_a_refused_blob_goes_above_its_generation(
    tmp_path: Path, refusal: str, recorded: int, expected: int
) -> None:
    """A blob that parsed but was refused still sets the floor: with the clock behind the blob's
    epoch the new generation is `recorded + 1`; a lower floor leaves `now_ms`."""
    tape = await _refused_blob(tmp_path, refusal, recorded)
    with capture_logs() as logs:
        second, s2 = await _run(tmp_path, COLD_US, _ticks(100, 101), tape=tape)
    assert STATE_COLD_STARTED in s2.health_reasons()
    assert {g for _, g, *_ in second.seen} == {expected}
    discarded = [e["reason"] for e in logs if e["event"] == "bars_state_blob_discarded"]
    started = [
        (e["reason"], e["generation"]) for e in logs if e["event"] == "bars_series_cold_started"
    ]
    assert discarded == [refusal] and started == [(refusal, expected)]
    await s2.stop()


async def test_the_floor_of_a_refused_blob_survives_a_crash_and_a_clock_step_back(
    tmp_path: Path,
) -> None:
    """The floor record overwrites the refused blob, so it carries the floor: a crash before the
    first 60 s persist and a clock that stepped back must not fall below it."""
    ahead = COLD_MS + 5_000_000
    await _refused_blob(tmp_path, "restore_failed", ahead)
    _, s2 = await _run(tmp_path, COLD_US, _ticks(100, 101))  # cold start: ahead + 1
    s2._lanes.clear()  # crash: no final blob, only the floor record
    third, s3 = await _run(tmp_path, COLD_US - 3_600_000_000, _ticks(200, 201))  # clock -1 h
    assert {g for _, g, *_ in third.seen} == {ahead + 2}
    await s3.stop()


@pytest.mark.parametrize("busy", [False, True])
async def test_crash_after_a_cold_start_restarts_in_a_new_generation(
    tmp_path: Path, busy: bool
) -> None:
    """The cold-start record is a floor, never a restore point. On a busy lane another series
    gave the lane a watermark, so a blob built with `_stored()` would be fresh state plus that
    watermark and a restart would reuse `index` 0 inside the same generation."""
    first, s1 = await _run(tmp_path, T0, _ticks(3 if busy else 0, 10 if busy else 7), busy=busy)
    stored, reason = await StateStore(tmp_path).load(SYM, T3.spec_hash)
    assert reason == "ok" and stored is not None and stored.watermark is None  # a floor record
    s1._lanes.clear()  # crash before the first periodic save
    tape = FakeTape(_ticks(0, 10))  # the tape holds every trade: a restore would replay them
    with capture_logs() as logs:
        second, s2 = await _run(tmp_path, T0, _ticks(100, 107), tape=tape)
    keys = _keys(first, second)
    assert len(keys) == 4 and len(set(keys)) == 4  # T3 closes bars 0 and 1 in each run
    assert [g for g, _ in keys] == [T0 // 1000] * 2 + [T0 // 1000 + 1] * 2  # the generation rose
    assert tape.reads == 0  # nothing was restored or replayed
    started = [e["reason"] for e in logs if e["event"] == "bars_series_cold_started"]
    assert started == ["no_watermark"] and STATE_COLD_STARTED not in s2.health_reasons()
    await s2.stop()


@pytest.mark.parametrize("first_start", ["cold", "restored"])
async def test_reregister_after_a_lost_final_save_stays_above_the_issued_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_start: str
) -> None:
    """Teardown whose final save failed, the blob gone and the clock stepped back an hour: the
    in-process floor (what this process issued or restored) still holds."""
    known = COLD_MS
    if first_start == "restored":
        _, s0 = await _run(tmp_path, T0, _ticks(0, 4))
        await s0.stop()  # a blob with a watermark: the next start restores it
        known = T0 // 1000
    clock, bus, rec = Clock(COLD_US), Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[rec], clock=clock)
    await s.register(T3, SYM, "a")
    monkeypatch.setattr(s._store, "save", _disk_full)  # the final save fails
    s.release(T3.spec_hash, SYM, "a")
    clock.t += 30_000_000  # grace over
    before = write_failures("final")
    await s.tick()
    assert s.active(SYM) == () and write_failures("final") == before + 1
    _blob(tmp_path).unlink(missing_ok=True)  # the blob is gone too
    monkeypatch.undo()
    clock.t = T0 - 3_600_000_000  # the clock stepped back
    await s.register(T3, SYM, "b")
    await bus.publish(TOPIC, _ticks(100, 101)[0])
    await settle(bus, s)
    assert {g for _, g, *_ in rec.seen} == {known + 1}
    await s.stop()


@pytest.mark.parametrize(
    ("recorded", "expected", "discarded"),
    [
        (MAX_GENERATION, COLD_MS, ["restore_failed", "corrupt"]),  # no room above it: refused
        (MAX_GENERATION - 1, MAX_GENERATION, ["restore_failed"]),  # the highest honest floor
    ],
)
async def test_a_floor_at_max_generation_is_refused_and_the_one_below_is_loadable(
    tmp_path: Path, recorded: int, expected: int, discarded: list[str]
) -> None:
    """`MAX_GENERATION + 1` would be refused by its own loader, so a floor at `MAX_GENERATION` is
    counted like a corrupt blob and the clock decides; one below it issues `MAX_GENERATION`."""
    await _refused_blob(tmp_path, "restore_failed", recorded)
    corrupt = blob_discards("corrupt")
    with capture_logs() as logs:
        second, s2 = await _run(tmp_path, COLD_US, _ticks(100, 101))
    assert {g for _, g, *_ in second.seen} == {expected}
    assert [e["reason"] for e in logs if e["event"] == "bars_state_blob_discarded"] == discarded
    assert blob_discards("corrupt") == corrupt + discarded.count("corrupt")
    loaded, reason = await StateStore(tmp_path).load(SYM, T3.spec_hash)
    assert reason == "ok" and loaded is not None and loaded.generation == expected  # loadable
    await s2.stop()


async def test_an_in_process_floor_at_max_generation_is_ignored(tmp_path: Path) -> None:
    bus, rec = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[rec], clock=Clock(COLD_US))
    s._remember((SYM, T3.spec_hash), MAX_GENERATION)  # as left by a forged floor
    await s.register(T3, SYM, "a")
    await bus.publish(TOPIC, _ticks(0, 1)[0])
    await settle(bus, s)
    assert {g for _, g, *_ in rec.seen} == {COLD_MS}
    await s.stop()


async def test_a_refused_blob_keeps_its_floor_when_the_cold_start_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refused blob is not deleted before its replacement lands: with the floor record
    unwritable it stays, is refused again on the next start and still supplies its floor."""
    ahead = COLD_MS + 5_000_000
    await _refused_blob(tmp_path, "restore_failed", ahead)
    s = make_set(tmp_path, clock=Clock(COLD_US))
    monkeypatch.setattr(s._store, "save", _disk_full)
    await s.register(T3, SYM, "a")  # refused, cold-started, the floor record cannot be written
    assert orjson.loads(_blob(tmp_path).read_bytes())["generation"] == ahead  # still on disk
    s._lanes.clear()  # crash
    monkeypatch.undo()
    third, s3 = await _run(tmp_path, COLD_US - 3_600_000_000, _ticks(200, 201))  # clock -1 h
    assert {g for _, g, *_ in third.seen} == {ahead + 1}
    await s3.stop()


async def test_the_issued_generation_floor_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_set, "ISSUED_FLOOR_CAP", 2)
    s = make_set(tmp_path, clock=Clock(COLD_US))
    specs = [BarSpec(kind="tick", tick_count=n) for n in (2, 3, 4)]
    for spec in specs:
        await s.register(spec, SYM, "a")
    assert list(s._issued) == [(SYM, specs[1].spec_hash), (SYM, specs[2].spec_hash)]  # LRU
    await s.stop()


def test_remembering_a_lower_generation_never_lowers_the_floor(tmp_path: Path) -> None:
    """A restore adopts its blob's generation, but what this process issued stays the floor."""
    s = make_set(tmp_path)
    key = (SYM, T3.spec_hash)
    s._remember(key, 9)
    s._remember(key, 5)  # e.g. an older blob was restored
    assert s._issued[key] == 9


async def test_a_failed_cold_start_save_is_logged_counted_and_the_series_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus, rec = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[rec], clock=Clock(COLD_US))
    monkeypatch.setattr(s._store, "save", _disk_full)
    before = write_failures("cold_start")
    with capture_logs() as logs:
        await s.register(T3, SYM, "a")  # `_save` logs and swallows the OSError
    assert write_failures("cold_start") == before + 1  # the floor is not durable: counted
    failed = [
        (e["stage"], e["generation"]) for e in logs if e["event"] == "bars_state_write_failed"
    ]
    assert failed == [("cold_start", COLD_MS)]  # and warned about
    for t in _ticks(0, 4):
        await bus.publish(TOPIC, t)
    await settle(bus, s)
    assert {g for _, g, *_ in rec.seen} == {COLD_MS} and not _blob(tmp_path).exists()
    monkeypatch.undo()
    await s.stop()


def _state() -> BuilderState:
    return TickBarBuilder(T3, SYM).snapshot()


def _v1_envelope(state: BuilderState) -> dict[str, object]:
    """A pre-#2662 envelope written by hand: version 1, no `generation` key."""
    return {
        "v": 1,
        "symbol": state.symbol,
        "spec_hash": state.spec_hash,
        "state_version": state.state_version,
        "last_trade_seq": state.last_trade_seq,
        "blob": state.blob.decode(),
        "wm": [5, ["a"]],
    }


async def _load(root: Path, doc: dict[str, object]) -> tuple[StoredState | None, str]:
    store = StateStore(root)
    store.path(SYM, T3.spec_hash).parent.mkdir(parents=True)
    store.path(SYM, T3.spec_hash).write_bytes(orjson.dumps(doc))
    return await store.load(SYM, T3.spec_hash)


@pytest.mark.parametrize("generation", [0, COLD_MS, MAX_GENERATION])
async def test_store_v2_roundtrips_the_generation(tmp_path: Path, generation: int) -> None:
    store = StateStore(tmp_path)
    stored = StoredState(_state(), Watermark(5, frozenset({"a"})), generation)
    await store.save(stored)
    assert orjson.loads(_blob(tmp_path).read_bytes())["v"] == 2
    assert await store.load(SYM, T3.spec_hash) == (stored, "ok")


async def test_store_loads_a_v1_envelope_as_generation_zero(tmp_path: Path) -> None:
    state = _state()
    stored, reason = await _load(tmp_path, _v1_envelope(state))
    assert reason == "ok"
    assert stored == StoredState(state, Watermark(5, frozenset({"a"})), 0)


@pytest.mark.parametrize("version", [0, 3, 99])
async def test_store_still_refuses_an_unknown_version(tmp_path: Path, version: int) -> None:
    doc = {**_v1_envelope(_state()), "v": version, "generation": 1}
    assert await _load(tmp_path, doc) == (None, "version")


@pytest.mark.parametrize(
    "extra",
    [
        {},  # no `generation` key at all
        {"generation": None},
        {"generation": -1},
        {"generation": 1.5},
        {"generation": True},
        {"generation": "7"},
        {"generation": MAX_GENERATION + 1},
    ],
)
async def test_store_refuses_a_v2_envelope_without_a_usable_generation(
    tmp_path: Path, extra: dict[str, object]
) -> None:
    doc = {**_v1_envelope(_state()), "v": 2, **extra}
    assert await _load(tmp_path, doc) == (None, "corrupt")


async def test_writer_sink_stamps_the_emissions_generation_on_every_stored_row() -> None:
    store = _Rows()
    writer = BarWriter(store)
    await writer.start()
    builder = TickBarBuilder(T3, SYM)
    updates = [u for t in _ticks(0, 7) for u in builder.on_trade(t)]  # forming updates, 2 closes
    await WriterSink(writer).emit(BarEmission(T3, 42, updates))
    assert await writer.stop() == 0
    assert [(r["generation"], r["index"]) for r in store.rows] == [(42, 0), (42, 1)]


def _a_bar() -> Bar:
    return TickBarBuilder(T3, SYM).on_trade(_ticks(0, 1)[0])[0].bar


def test_ilp_line_renders_a_13_digit_generation_as_a_long() -> None:
    row = bar_row(_a_bar(), T3, generation=COLD_MS)
    fields = {k: v for k, v in row.items() if k != "ts"}
    line = serialize_ilp_line(BAR_SCHEMAS_BY_FAMILY["tick"], fields, int(str(row["ts"])))
    assert len(str(COLD_MS)) == 13 and f"generation={COLD_MS}i" in line  # LONG, never a double


async def test_generation_has_no_silent_default() -> None:
    bar = _a_bar()
    with pytest.raises(TypeError, match="generation"):
        StoredState(_state(), None)  # type: ignore[call-arg]  # the default is gone on purpose
    with pytest.raises(TypeError, match="generation"):
        bar_row(bar, T3)  # type: ignore[call-arg]  # same
    with pytest.raises(TypeError, match="generation"):
        await BarWriter(_Rows()).submit([bar], T3)  # type: ignore[call-arg]  # same


@pytest.mark.parametrize("bad", [-1, MAX_GENERATION + 1, 1.5, True, "7", None])
def test_bar_row_refuses_a_generation_outside_the_range(bad: object) -> None:
    with pytest.raises(BarPersistError, match="generation"):
        bar_row(_a_bar(), T3, generation=bad)  # type: ignore[arg-type]  # a bad value is the point


@pytest.mark.parametrize("ok", [0, COLD_MS, MAX_GENERATION])
def test_bar_row_accepts_a_generation_in_the_range(ok: int) -> None:
    assert bar_row(_a_bar(), T3, generation=ok)["generation"] == ok


def test_a_kline_row_must_carry_the_kline_generation() -> None:
    row = bar_row(_a_bar(), T3, source="kline", generation=KLINE_GENERATION)
    assert row["generation"] == KLINE_GENERATION
    with pytest.raises(BarPersistError, match="kline"):
        bar_row(_a_bar(), T3, source="kline", generation=KLINE_GENERATION + 1)


async def test_the_writer_refuses_a_bad_generation_before_queueing_anything() -> None:
    writer = BarWriter(_Rows())
    with pytest.raises(BarPersistError):
        await writer.submit([_a_bar()], T3, generation=MAX_GENERATION + 1)
    tape_row = bar_row(_a_bar(), T3, generation=1)
    kline_row = bar_row(_a_bar(), T3, source="kline", generation=KLINE_GENERATION)
    with pytest.raises(BarPersistError):  # pre-mapped rows pass the same boundary
        await writer.submit_rows([{**tape_row, "generation": -1}], T3, source="tape")
    with pytest.raises(BarPersistError, match="kline"):
        await writer.submit_rows([{**kline_row, "generation": 5}], T3, source="kline")
    assert writer.depth == 0
