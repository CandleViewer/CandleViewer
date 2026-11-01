"""Scenario 1b - the process dies in the middle of a bar. C-13.6 #12 (process kill).

Declared (E12-Q06 scenario 1, BQ-9 b): a restart resumes the series from its last state blob and
replays the tape after the blob's watermark, so the bars after the restart equal the golden of
an uninterrupted run, in the epoch the blob recorded (same `generation`, so the store's
`(bar_param, generation, index)` key makes the replayed closes idempotent), and a replayed close
is byte-identical to the one emitted before the kill. When the tape cannot cover what the blob
missed (it lags by more than the lane's recent-trade ring), the restore is *marked*, not silent:
`bars_restore_gap_total`, the `bar_restore_gap` health reason and a WARN log.

The crash: the first process persists a blob on its periodic tick (10 s here, 60 s in production),
keeps trading, and is "killed" by copying its state directory at that moment and carrying on with
the copy: the later trades and the final blobs the graceful `stop()` writes never reach it.

No exchange: the tape is the recorded trade corpus, re-timed (`golden.corpus_tape`), published on
a real bus; `settle()` and the injected clock replace every wait.

Negative control: a restart that ignores the tape loses the trades since the blob, and the
conservation helper fails on it.
"""

from __future__ import annotations

import shutil
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.bars import builder_set
from candleviewer.bars.builder_set import BarBuilderSet, BarsHealthReason, default_factory
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.metrics import bars_restore_gap_total
from candleviewer.bars.models import Bar
from candleviewer.bars.state_store import StateStore
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.models import TradeEvent
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SYMBOL, TIME_5S, VOLUME_1
from tests.chaos.bars._sinks import CaptureSink
from tests.chaos.ingestion._clock import EPOCH_S
from tests.unit.bars._set_harness import Clock, FakeTape, settle

pytestmark = pytest.mark.chaos

ENV = "live"
TOPIC = Topic(env=ENV, domain="md", symbol=SYMBOL, detail="trade")
SPECS = {"vol:1": VOLUME_1, "time:5s": TIME_5S}
START_US = round(EPOCH_S * 1_000_000)
PERSIST_EVERY_US = 10_000_000
BLOB_AT_US = START_US + 25_000_000  # first tick past 10 s of the series' life: the blob
CRASH_AT_US = START_US + 33_000_000  # 8 s after the blob: no second blob yet
OVERLAP = 5  # trades the bus redelivers after the restart although the tape holds them


def _tape() -> list[TradeEvent]:
    return golden.corpus_tape(SYMBOL, frames_n=120, start_ms=round(EPOCH_S * 1000))


def _cut(tape: list[TradeEvent], at_us: int) -> int:
    return next(i for i, t in enumerate(tape) if t.ts_event >= at_us)


class _Process:
    """One life of the bars service: a bus, a capture sink and a `BarBuilderSet` on a state dir."""

    def __init__(self, root: Path, *, now_us: int, tape: FakeTape | None = None) -> None:
        self.bus, self.sink, self.clock = Bus(), CaptureSink(), Clock(now_us)
        self.set = BarBuilderSet(
            self.bus,
            ENV,
            EmitRouter([self.sink]),
            StateStore(root),
            tape=tape,
            now_us=self.clock,
            factory=default_factory,
            persist_every_us=PERSIST_EVERY_US,
        )

    async def register(self, *labels: str) -> None:
        for label in labels or tuple(SPECS):
            await self.set.register(SPECS[label], SYMBOL, f"chaos:{label}")

    async def feed(self, trades: list[TradeEvent]) -> None:
        for t in trades:
            await self.bus.publish(TOPIC, t)
        await settle(self.bus, self.set)
        self.clock.t = max(self.clock.t, trades[-1].ts_event)
        await self.set.tick()

    def forming(self, label: str) -> bool:
        updates = self.sink.updates[SPECS[label].spec_hash]
        return bool(updates) and updates[-1].kind != "close"


def _merged(label: str, *lives: _Process) -> list[Bar]:
    """What the store/clients end up with: the latest emission per index across both lives."""
    latest: dict[int, Bar] = {}
    for life in lives:
        for seen in life.sink.updates.get(SPECS[label].spec_hash, []):
            latest[seen.bar.index] = seen.bar
    return [latest[i] for i in sorted(latest)]


def _closes(label: str, life: _Process) -> dict[int, Bar]:
    return {
        s.bar.index: s.bar for s in life.sink.updates[SPECS[label].spec_hash] if s.kind == "close"
    }


async def _crash_mid_bar(tmp_path: Path, tape: list[TradeEvent]) -> tuple[_Process, Path, int]:
    """Life 1 up to the crash. Returns it, the state dir a kill would have left, the cut index."""
    first_root, crashed = tmp_path / "life1", tmp_path / "crashed"
    life1 = _Process(first_root, now_us=START_US)
    await life1.register()
    blob_cut, cut = _cut(tape, BLOB_AT_US), _cut(tape, CRASH_AT_US)
    await life1.feed(tape[:blob_cut])  # the periodic tick writes the blobs
    await life1.feed(tape[blob_cut:cut])  # more trades; no blob for them
    shutil.copytree(first_root, crashed)  # the kill: this is all that survives
    return life1, crashed, cut


async def test_s01b_a_restart_mid_bar_resumes_to_the_golden_in_the_same_epoch(
    tmp_path: Path,
) -> None:
    tape = _tape()
    life1, crashed, cut = await _crash_mid_bar(tmp_path, tape)
    assert life1.forming("vol:1"), "the kill did not fall inside a volume bar"
    life2 = _Process(crashed, now_us=tape[cut - 1].ts_event, tape=FakeTape(tape[:cut]))
    await life2.register()
    await life2.feed(tape[cut - OVERLAP :])  # the redelivered prints must not count twice
    await life1.set.stop()
    await life2.set.stop()
    expected = await golden.golden_bars(tape, SPECS, SYMBOL)
    for label in SPECS:
        merged = _merged(label, life1, life2)
        golden.assert_matches_golden(expected[label], merged, label)
        golden.assert_monotonic(merged, label)
        epochs = {
            s.generation
            for life in (life1, life2)
            for s in life.sink.updates[SPECS[label].spec_hash]
        }
        assert len(epochs) == 1, f"{label}: the restore began a new epoch {epochs}"
        replayed = _closes(label, life1).keys() & _closes(label, life2).keys()
        assert all(_closes(label, life1)[i] == _closes(label, life2)[i] for i in replayed), (
            f"{label}: a replayed close differs from the one emitted before the kill"
        )
    assert _closes("vol:1", life1).keys() & _closes("vol:1", life2).keys(), "nothing was replayed"


async def test_s01b_negative_control_a_restart_that_ignores_the_tape_loses_prints(
    tmp_path: Path,
) -> None:
    tape = _tape()
    life1, crashed, cut = await _crash_mid_bar(tmp_path, tape)
    life2 = _Process(crashed, now_us=tape[cut - 1].ts_event, tape=None)
    await life2.register()
    await life2.feed(tape[cut - OVERLAP :])
    await life1.set.stop()
    await life2.set.stop()
    expected = await golden.golden_bars(tape, SPECS, SYMBOL)
    with pytest.raises(AssertionError, match="not conserved"):
        golden.assert_conserved(expected["vol:1"], _merged("vol:1", life1, life2), "vol:1")


async def _restore_with_tape_ending_at(
    tmp_path: Path, tape: list[TradeEvent], tape_end: int
) -> tuple[BarBuilderSet, list[MutableMapping[str, Any]]]:
    """Life 1 stops at the blob; life 2 runs the lane on, then a late spec restores that blob."""
    blob_cut = _cut(tape, BLOB_AT_US)
    life1 = _Process(tmp_path / "state", now_us=START_US)
    await life1.register("vol:1")
    await life1.feed(tape[:blob_cut])
    await life1.set.stop()  # the final blob: watermark at the last trade fed
    life2 = _Process(
        tmp_path / "state", now_us=tape[blob_cut].ts_event, tape=FakeTape(tape[:tape_end])
    )
    await life2.register("time:5s")  # a different series: it holds the lane open, no blob read
    await life2.feed(tape[blob_cut : blob_cut + 40])
    with capture_logs() as logs:
        await life2.register("vol:1")  # restores the old blob; the ring keeps only the last 4
    return life2.set, logs


async def test_s01b_a_tape_that_lags_past_the_ring_is_marked_never_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_set, "RECENT_RING", 4)
    tape = _tape()
    before = bars_restore_gap_total._value.get()
    bars_set, logs = await _restore_with_tape_ending_at(tmp_path, tape, _cut(tape, BLOB_AT_US) + 2)
    assert bars_restore_gap_total._value.get() == before + 1
    assert BarsHealthReason.RESTORE_GAP in bars_set.health_reasons()
    warned = [e for e in logs if e["event"] == "bars_restore_gap"]
    assert [e["log_level"] for e in warned] == ["warning"]
    await bars_set.stop()


async def test_s01b_negative_control_a_tape_that_reaches_the_ring_raises_no_alarm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_set, "RECENT_RING", 4)
    tape = _tape()
    blob_cut = _cut(tape, BLOB_AT_US)
    before = bars_restore_gap_total._value.get()
    bars_set, _ = await _restore_with_tape_ending_at(tmp_path, tape, blob_cut + 40)
    assert bars_restore_gap_total._value.get() == before
    assert BarsHealthReason.RESTORE_GAP not in bars_set.health_reasons()
    await bars_set.stop()
