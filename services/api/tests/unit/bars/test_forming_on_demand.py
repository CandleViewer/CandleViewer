"""Builders materialise a bar only on open, close and amend; the forming bar on demand (#2022).

`24-internal-schemas.md` §3.2 "What a builder emits": `on_trade`/`on_clock` return only an
`open`, a `close` or an amended `close`; `forming()` is the forming bar's `update`, built by the
close's own path, with no state change. Every builder kind is checked against the independent
reference model (`bench.bar_determinism.reference`), so the forming bar carries every field the
old per-trade `update` carried.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from bench.bar_determinism import comparator, goldens, invariants, reference
from bench.bar_determinism.generator import SYMBOL, TICK, GenConfig, generate
from candleviewer.bars.activity_builders import ActivityBarUpdate
from candleviewer.bars.models import BarBuilder, BarUpdate
from candleviewer.bars.renko_builder import RenkoBarUpdate
from candleviewer.bars.threshold_builders import RangeBarUpdate
from candleviewer.exchange.base.models import TradeEvent

SEED = 2022
_TAPE: list[TradeEvent] = []


def tape() -> list[TradeEvent]:
    """Adversarial generated tape (splits, exact hits, huge prints, reversals); built on use."""
    if not _TAPE:
        cfg = GenConfig(
            seed=SEED, n=240, p_exact=0.05, p_huge=0.01, p_reversal=0.05, threshold_lots=250
        )
        _TAPE.extend(generate(cfg))
    return _TAPE


def _feed(b: BarBuilder, t: TradeEvent) -> Sequence[BarUpdate]:
    ups = list(b.on_trade(t))
    if b.spec.kind == "time":
        ups += b.on_clock(t.ts_event)
    return ups


@pytest.mark.parametrize("label", list(invariants.STANDARD_SPECS))
def test_forming_equals_the_reference_bar_field_for_field_after_every_trade(label: str) -> None:
    """After every print, `forming()` is the reference model's bar of that index on the prefix:
    every `Bar` field (the time tail's `closed` excepted: the reference flushes it), the kind's
    `BarUpdate` subclass and its side fields."""
    spec, tp = invariants.STANDARD_SPECS[label], tape()
    b = invariants.make_builder(spec)
    seen = 0
    for i, t in enumerate(tp):
        _feed(b, t)
        f = b.forming()
        if f is None:
            continue
        seen += 1
        assert f.kind == "update" and not f.bar.closed and not f.amended
        ref = {r.index: r for r in reference.build(spec, SYMBOL, tp[: i + 1], TICK).bars}
        want = ref[f.bar.index]
        if spec.kind == "time":
            want = want.model_copy(update={"closed": False})
        diffs = comparator.compare([want], [f.bar])
        assert not diffs, f"{label} after trade #{i}:\n{comparator.render(diffs)}"
        if spec.kind in ("tick", "volume", "delta"):
            assert type(f) is ActivityBarUpdate and f.split_from_trade_id is None
        elif spec.kind == "range":
            assert type(f) is RangeBarUpdate
        elif spec.kind == "renko":
            assert type(f) is RenkoBarUpdate and f.volume_allocated
            assert f.open_source_ts == f.bar.open_time
    assert seen  # the tape leaves a bar forming somewhere for every kind


def test_range_forming_carries_the_open_source_ts_of_its_first_print() -> None:
    spec = invariants.STANDARD_SPECS["range:20"]
    b = invariants.make_builder(spec)
    opened: int | None = None
    for t in tape():
        for u in b.on_trade(t):
            if u.kind == "open":
                assert isinstance(u, RangeBarUpdate)
                opened = u.open_source_ts
        f = b.forming()
        if f is not None:
            assert isinstance(f, RangeBarUpdate) and f.open_source_ts == opened


@pytest.mark.parametrize("label", list(invariants.STANDARD_SPECS))
def test_forming_changes_no_state(label: str) -> None:
    """A twin that never asks for the forming bar emits the same and snapshots the same."""
    spec = invariants.STANDARD_SPECS[label]
    asked, twin = invariants.make_builder(spec), invariants.make_builder(spec)
    for t in tape():
        before = asked.snapshot()
        first, second = asked.forming(), asked.forming()
        assert first == second and asked.snapshot() == before
        assert _feed(asked, t) == _feed(twin, t)
    assert asked.snapshot() == twin.snapshot() and asked.forming() == twin.forming()


@pytest.mark.parametrize("label", list(invariants.STANDARD_SPECS))
def test_builders_emit_only_opens_closes_and_amends(label: str) -> None:
    spec = invariants.STANDARD_SPECS[label]
    b = invariants.make_builder(spec)
    kinds = {(u.kind, u.amended) for t in tape() for u in _feed(b, t)}
    assert kinds <= {("open", False), ("close", False), ("close", True)}
    assert ("open", False) in kinds  # (tick:1000 and delta:2 close none on this short tape)


@pytest.mark.parametrize("label", list(goldens.GOLDEN_SPECS))
def test_close_set_on_the_golden_day_is_unchanged_by_reading_forming(label: str) -> None:
    """Reading `forming()` after every print leaves the closes, their order and the final bars
    equal to the committed golden file (the harness reads it once, at the end of the tape)."""
    spec, day = goldens.GOLDEN_SPECS[label], goldens.load_tape()
    plain, probed = invariants.make_builder(spec), invariants.make_builder(spec)
    closes_plain: list[BarUpdate] = []
    closes_probed: list[BarUpdate] = []
    probed_out: list[BarUpdate] = []
    for t in day:
        closes_plain += [u for u in _feed(plain, t) if u.kind == "close"]
        ups = _feed(probed, t)
        probed_out += ups
        closes_probed += [u for u in ups if u.kind == "close"]
        probed.forming()
    assert closes_probed == closes_plain
    tail = probed_out + invariants.flush(probed, day)
    got = [comparator.line(x) for x in invariants.final_bars(tail, probed)]
    assert got == goldens.read(label)


def test_volume_forming_after_a_split_is_the_remainder_without_a_split_id() -> None:
    b = invariants.make_builder(invariants.STANDARD_SPECS["volume:5"])
    t = tape()[0].model_copy(update={"qty": Decimal(12), "trade_id": "split-me"})
    ups = b.on_trade(t)
    assert [u.kind for u in ups] == ["close", "close", "open"]
    f = b.forming()
    assert isinstance(f, ActivityBarUpdate) and f.split_from_trade_id is None
    assert f.bar == ups[-1].bar  # the remainder, as its `open` carried it
