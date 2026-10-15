"""A builder cold start begins a new bar generation (#2662): `(generation, index)` never repeats.

`24-internal-schemas.md` §3.1/§3.5. The set stamps every emission with its series' generation. A
restored series keeps the generation its blob recorded; a cold start takes `max(now_ms, floor + 1)`
where `floor` is the generation of a discarded blob that still parsed (else -1).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import orjson
import pytest
from structlog.testing import capture_logs

from candleviewer.bars.activity_builders import TickBarBuilder
from candleviewer.bars.builder_set import STATE_COLD_STARTED, BarBuilderSet
from candleviewer.bars.emit import BarEmission, WriterSink
from candleviewer.bars.models import BuilderState
from candleviewer.bars.state_store import MAX_GENERATION, StateStore, StoredState, Watermark
from candleviewer.bars.writer import BarWriter
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import T3, TOPIC, Clock, FakeTape, RecordingSink, make_set, settle
from ._trades import SYM, trade, us

T0 = us("10:00:00")
COLD_US = T0 + 600_000_000  # the restart happens ten minutes later
COLD_MS = COLD_US // 1000


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


async def _run(
    root: Path,
    now_us: int,
    trades: list[TradeEvent],
    *,
    tape: FakeTape | None = None,
    sinks: Sequence[object] = (),
) -> tuple[RecordingSink, BarBuilderSet]:
    """Register `T3` (restore or cold start, by what is on disk), publish, let the lane drain."""
    bus, rec = Bus(), RecordingSink()
    s = make_set(root, bus=bus, sinks=[rec, *sinks], tape=tape, clock=Clock(now_us))
    await s.register(T3, SYM, "c")
    for t in trades:
        await bus.publish(TOPIC, t)
    await settle(bus, s)
    return rec, s


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
    wire = [(g, i) for _, g, k, i, _ in (*first.seen, *second.seen) if k == "close"]
    assert len(wire) == 4 and len(set(wire)) == 4  # bars 0 and 1 of both runs: four distinct keys
    assert [g for g, _ in wire] == [T0 // 1000] * 2 + [COLD_MS] * 2  # the later run is higher
    assert [(r["generation"], r["index"]) for r in store.rows] == wire  # stored rows agree


async def test_restore_keeps_the_blobs_generation_and_continues_the_index(tmp_path: Path) -> None:
    _, s1 = await _run(tmp_path, T0, _ticks(0, 4))  # bar 0 closed, bar 1 forming
    await s1.stop()
    second, s2 = await _run(tmp_path, COLD_US, _ticks(4, 7))  # a cold start now would differ
    await s2.stop()
    assert {g for _, g, *_ in second.seen} == {T0 // 1000}
    assert [i for _, _, k, i, _ in second.seen if k == "close"] == [1]


@pytest.mark.parametrize("refusal", ["restore_failed", "ahead_of_tape"])
@pytest.mark.parametrize(
    ("recorded", "expected"), [(COLD_MS + 5_000_000, COLD_MS + 5_000_001), (7, COLD_MS)]
)
async def test_cold_start_after_a_refused_blob_goes_above_its_generation(
    tmp_path: Path, refusal: str, recorded: int, expected: int
) -> None:
    """A blob that parsed but was refused still sets the floor: when the clock reads lower than
    the blob's epoch the new generation is `recorded + 1`; a lower floor leaves `now_ms`."""
    _, s1 = await _run(tmp_path, T0, _ticks(0, 4))
    await s1.stop()
    doc = orjson.loads(_blob(tmp_path).read_bytes())
    doc["generation"] = recorded
    tape = None
    if refusal == "restore_failed":
        doc["state_version"] = 7  # the builder refuses it on restore
    else:
        tape = FakeTape(_ticks(0, 1))  # tape head T0 is behind the blob's watermark T0 + 3
    _blob(tmp_path).write_bytes(orjson.dumps(doc))
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
