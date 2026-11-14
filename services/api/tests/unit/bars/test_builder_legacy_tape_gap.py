"""#5396: a builder blob written before `tape_gap` (#5338) marked a tape gap with `gap_before`.
Restoring it moves that mark to `tape_gap` where `gap_before` can mean nothing else."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.bars.builder_set import production_factory
from candleviewer.bars.models import BarSpec
from candleviewer.bars.time_builder import _SLOTS, TimeBarBuilder

from ._trades import SYM, trade, us

T0 = us("10:00:00")
STEP = 10_000_000
GAP = _SLOTS.index("gap_before")
SPEC = BarSpec(kind="time", interval_ms=10_000)


def _blob() -> tuple[Any, dict[str, Any]]:
    """Three contiguous 10 s bars (0 and 1 closed, 2 open), then bar 2 moved one interval later:
    an empty interval precedes it, as after a quiet stretch."""
    b = TimeBarBuilder(SPEC, SYM)
    for i in range(3):
        b.on_trade(trade(T0 + i * STEP + 1, seq=i))
    state = b.snapshot()
    doc = json.loads(state.blob)
    assert len(doc["closed"]) == 2 and doc.pop("tape_gap") == []  # a legacy blob lacks the key
    for slot in ("open_time", "close_time"):
        doc["cur"][_SLOTS.index(slot)] += STEP
    doc["cur"][GAP] = True
    return state, doc


def _restore(state: Any, doc: dict[str, Any]) -> list[tuple[int, bool, bool]]:
    b = TimeBarBuilder(SPEC, SYM)
    b.restore(state.model_copy(update={"blob": json.dumps(doc).encode()}))
    return sorted((d.index, d.gap_before, d.tape_gap) for d in [b._cur, *b._closed] if d)


def test_time_old_blob_contiguous_gap_before_restores_as_tape_gap() -> None:
    state, doc = _blob()
    doc["closed"][1][GAP] = True  # bar 1 starts where bar 0 closed: no empty interval
    assert _restore(state, doc) == [(0, False, False), (1, False, True), (2, True, True)]


def test_time_old_blob_empty_interval_gap_before_keeps_it_and_adds_tape_gap() -> None:
    """Ambiguous (an empty interval precedes it; a tape gap may too): both flags, so data loss is
    never under-reported."""
    state, doc = _blob()
    assert _restore(state, doc) == [(0, False, False), (1, False, False), (2, True, True)]


def test_time_old_blob_first_bar_gap_before_is_a_tape_gap() -> None:
    state, doc = _blob()
    doc["closed"][0][GAP] = True  # nothing precedes the first bar: no empty interval
    assert _restore(state, doc)[0] == (0, False, True)


def test_time_old_blob_open_draft_with_pruned_predecessor_settles_by_last_close() -> None:
    """The closed predecessor is pruned 60 s after the watermark passes its close, so the open
    draft's predecessor can be gone: `last_close` (the previous bar's close) settles it."""
    spec = BarSpec(kind="time", interval_ms=300_000)
    width = 300_000_000
    b = TimeBarBuilder(spec, SYM)
    b.on_trade(trade(T0 + 1, seq=0))
    b.on_trade(trade(T0 + width + 1, seq=1))
    state = b.snapshot()
    doc = json.loads(state.blob)
    assert len(doc["closed"]) == 1
    doc["closed"] = []  # pruned, as 60 s after its close the watermark has passed it
    assert doc["last_close"] == doc["cur"][_SLOTS.index("open_time")]
    assert doc.pop("tape_gap") == []
    doc["cur"][GAP] = True

    def restored(blob: dict[str, Any]) -> tuple[bool, bool]:
        r = TimeBarBuilder(spec, SYM)
        r.restore(state.model_copy(update={"blob": json.dumps(blob).encode()}))
        assert r._cur is not None
        return r._cur.gap_before, r._cur.tape_gap

    assert restored(doc) == (False, True)  # starts where the previous bar closed
    doc["last_close"] -= 1  # an empty interval precedes it
    assert restored(doc) == (True, True)


def test_time_new_blob_always_writes_the_tape_gap_key() -> None:
    b = TimeBarBuilder(SPEC, SYM)
    b.on_trade(trade(T0 + 1, seq=0))
    assert json.loads(b.snapshot().blob)["tape_gap"] == []


def test_time_new_code_empty_interval_survives_snapshot_and_restore() -> None:
    """A real empty interval built by new code: `gap_before` only; the key is present (empty), so
    a restore leaves the flags as written."""
    b = TimeBarBuilder(SPEC, SYM)
    b.on_trade(trade(T0 + 1, seq=0))
    b.on_trade(trade(T0 + 2 * STEP + 1, seq=1))  # bar 1's interval is empty
    state = b.snapshot()
    doc = json.loads(state.blob)
    assert doc["tape_gap"] == []
    assert _restore(state, doc) == [(0, False, False), (1, True, False)]


def test_time_blob_with_the_tape_gap_key_restores_exactly_as_stored() -> None:
    state, doc = _blob()
    doc["closed"][1][GAP] = True  # would convert in an old blob; here the key is authoritative
    doc["tape_gap"] = [2]
    assert _restore(state, doc) == [(0, False, False), (1, True, False), (2, True, True)]


@pytest.mark.parametrize("name", ["tick", "volume", "delta", "renko", "range"])
def test_activity_old_blob_gap_before_restores_by_what_it_can_mean(name: str) -> None:
    specs = {
        "tick": BarSpec(kind="tick", tick_count=1000),
        "volume": BarSpec(kind="volume", volume_threshold=Decimal(1000)),
        "delta": BarSpec(kind="delta", delta_threshold=Decimal(1000)),
        "renko": BarSpec(kind="renko", range_ticks=2),
        "range": BarSpec(kind="range", range_ticks=1000),
    }
    factory = production_factory(lambda _s: Decimal("0.01"), renko_enabled=True)
    b = factory(specs[name], SYM)
    b.on_trade(trade(T0, seq=0))
    state = b.snapshot()
    doc = json.loads(state.blob)
    assert doc.pop("tape_gap") == []  # a legacy blob lacks the key
    doc["cur"][GAP] = True
    restored = factory(specs[name], SYM)
    restored.restore(state.model_copy(update={"blob": json.dumps(doc).encode()}))
    assert (restored._cur.gap_before, restored._cur.tape_gap) == (
        (True, True) if name == "range" else (False, True)  # range: a jump or a tape gap: both
    )
    doc["tape_gap"] = []
    other = factory(specs[name], SYM)
    other.restore(state.model_copy(update={"blob": json.dumps(doc).encode()}))
    assert (other._cur.gap_before, other._cur.tape_gap) == (True, False)
