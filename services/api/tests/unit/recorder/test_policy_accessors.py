"""The read accessors #492's status binding calls on the policy (#2188 S3b)."""

from __future__ import annotations

import copy
import inspect
from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, StartRefused, user_actor
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem

OWNER = user_actor("owner-1")
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def disk() -> list[bool]:
    return [False]  # the flag the capped policy's `disk_refuses` reads


@pytest.fixture
async def capped(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit, store: Mem, disk: list[bool]
) -> AsyncIterator[RecordingPolicy]:
    clock.t = NOW.timestamp()  # wall-clock seconds, as the policy's clock reads
    p = RecordingPolicy(
        bus=bus,
        audit=audit,
        env="demo",
        now=clock,
        recorded=store,
        disk_refuses=lambda: disk[0],
        config=PolicyConfig(max_symbols=1),
    )
    p.positions_reloaded()
    yield p
    await p.stop()


async def test_linger_until_is_the_grace_end_as_an_aware_utc_instant(
    capped: RecordingPolicy, clock: FakeClock
) -> None:
    assert capped.linger_until("BTCUSDT") is None  # unknown
    await capped.add_manual("BTCUSDT", OWNER)
    await capped.set_pin("BTCUSDT", True, OWNER, restricted=False)  # a pin outlives the stop
    assert capped.linger_until("BTCUSDT") is None  # recording
    await capped.remove_manual("BTCUSDT", OWNER)
    until = capped.linger_until("BTCUSDT")
    assert until == NOW + timedelta(seconds=1800)  # an aware instant never equals a naive one
    assert until is not None and until.utcoffset() == timedelta(0)
    clock.advance(1800)
    await capped.tick()  # the grace ends and the symbol stops
    assert capped.leaf("BTCUSDT") is None and capped.linger_until("BTCUSDT") is None


async def test_chart_open_holds_while_any_chart_ref_is_held(capped: RecordingPolicy) -> None:
    assert not capped.chart_open("BTCUSDT")  # unknown
    await capped.on_chart_opened("BTCUSDT", "c1")
    await capped.on_chart_opened("BTCUSDT", "c2")
    assert capped.chart_open("BTCUSDT") and capped.leaf("BTCUSDT") is None  # not recording yet
    await capped.on_chart_closed("BTCUSDT", "c1")
    assert capped.chart_open("BTCUSDT")  # c2 remains
    await capped.on_chart_closed("BTCUSDT", "c2")
    assert not capped.chart_open("BTCUSDT")
    await capped.on_position_opened("ETHUSDT", "p1")
    assert not capped.chart_open("ETHUSDT")  # a position is not a chart


async def test_start_refusal_names_its_cause_until_the_start_succeeds(
    capped: RecordingPolicy, clock: FakeClock, disk: list[bool]
) -> None:
    assert capped.start_refusal("SOLUSDT") is None  # unknown
    await capped.on_chart_opened("SOLUSDT", "c1")
    disk[0] = True
    clock.advance(60)
    await capped.tick()
    assert capped.start_refusal("SOLUSDT") == "disk_pressure"
    assert capped.start_refusal("BTCUSDT") is None  # another symbol
    disk[0] = False
    await capped.tick()  # the pressure eases and it starts
    assert capped.leaf("SOLUSDT") == "recording" and capped.start_refusal("SOLUSDT") is None
    await capped.on_chart_opened("ETHUSDT", "c2")
    clock.advance(60)
    await capped.tick()  # the one slot is SOL's
    assert capped.start_refusal("ETHUSDT") == "symbol_cap"


async def test_start_refusal_follows_the_latest_cause_and_lapses_with_the_trigger(
    capped: RecordingPolicy, clock: FakeClock, disk: list[bool]
) -> None:
    await capped.add_manual("BTCUSDT", OWNER)  # takes the slot
    await capped.on_chart_opened("SOLUSDT", "c1")
    clock.advance(60)
    await capped.tick()
    assert capped.start_refusal("SOLUSDT") == "symbol_cap"
    disk[0] = True
    await capped.tick()  # still wanted, now refused for the disk too
    assert capped.start_refusal("SOLUSDT") == "disk_pressure"
    await capped.on_chart_opened("SOLUSDT", "c2")  # a young second chart keeps the entry
    await capped.on_chart_closed("SOLUSDT", "c1")  # the one that waited goes: nothing is wanted
    assert capped.start_refusal("SOLUSDT") is None


async def test_start_refusal_with_two_reasons_refused_answers_the_last_one(
    capped: RecordingPolicy, clock: FakeClock, disk: list[bool]
) -> None:
    await capped.add_manual("BTCUSDT", OWNER)  # takes the slot
    await capped.on_position_opened("SOLUSDT", "p1")  # refused for the cap
    await capped.on_chart_opened("SOLUSDT", "c1")
    clock.advance(60)
    disk[0] = True
    await capped.tick()  # the chart's start is refused too, for the disk
    assert capped.start_refusal("SOLUSDT") == "disk_pressure"  # the lowest reason, refused last


@pytest.mark.parametrize("name", ["linger_until", "start_refusal", "chart_open"])
async def test_an_accessor_is_sync_and_changes_nothing(
    capped: RecordingPolicy, clock: FakeClock, name: str
) -> None:
    await capped.add_manual("BTCUSDT", OWNER)
    await capped.remove_manual("BTCUSDT", OWNER)  # lingers, holding the slot
    await capped.on_chart_opened("SOLUSDT", "c1")
    clock.advance(60)
    await capped.tick()  # SOL waits, refused for the cap
    before = copy.deepcopy(capped._syms)
    accessor = getattr(capped, name)
    assert not inspect.iscoroutinefunction(accessor)
    answers = [accessor(symbol) for symbol in ("BTCUSDT", "SOLUSDT", "XRPUSDT")]  # one unknown
    assert not any(inspect.isawaitable(answer) for answer in answers)
    assert capped._syms == before


async def test_start_refused_lists_a_cap_refusal_with_its_reasons_top_first(
    capped: RecordingPolicy, clock: FakeClock
) -> None:
    await capped.add_manual("BTCUSDT", OWNER)  # takes the one slot
    await capped.on_chart_opened("SOLUSDT", "c1")
    clock.advance(60)
    await capped.tick()  # the chart's start is refused for the cap first ...
    await capped.on_position_opened("SOLUSDT", "p1")  # ... then the position's
    assert capped.start_refused() == (
        StartRefused("SOLUSDT", "symbol_cap", ("position_open", "chart_open")),
    )


async def test_start_refused_is_empty_until_a_start_is_refused_and_after_it_succeeds(
    capped: RecordingPolicy, clock: FakeClock, disk: list[bool]
) -> None:
    assert capped.start_refused() == ()  # nothing tracked
    disk[0] = True
    await capped.on_chart_opened("SOLUSDT", "c1")
    assert capped.start_refused() == ()  # waiting out its dwell: not refused yet
    clock.advance(60)
    await capped.tick()
    assert capped.start_refused() == (StartRefused("SOLUSDT", "disk_pressure", ("chart_open",)),)
    disk[0] = False
    await capped.tick()  # the pressure eases and it starts
    assert capped.leaf("SOLUSDT") == "recording" and capped.start_refused() == ()


async def test_start_refused_drops_a_symbol_whose_trigger_lapses_and_lists_in_symbol_order(
    capped: RecordingPolicy, clock: FakeClock
) -> None:
    await capped.add_manual("BTCUSDT", OWNER)
    await capped.on_chart_opened("SOLUSDT", "c1")
    await capped.on_chart_opened("ETHUSDT", "c2")
    clock.advance(60)
    await capped.tick()
    assert [r.symbol for r in capped.start_refused()] == ["ETHUSDT", "SOLUSDT"]  # not arrival order
    await capped.on_chart_opened("ETHUSDT", "c3")  # a young second chart keeps the entry
    await capped.on_chart_closed("ETHUSDT", "c2")  # the one that waited goes: nothing is wanted
    assert [r.symbol for r in capped.start_refused()] == ["SOLUSDT"]


async def test_start_refused_agrees_with_start_refusal_for_every_symbol(
    capped: RecordingPolicy, clock: FakeClock, disk: list[bool]
) -> None:
    await capped.add_manual("BTCUSDT", OWNER)  # takes the one slot
    await capped.on_position_opened("SOLUSDT", "p1")  # refused for the cap
    await capped.on_position_opened("XRPUSDT", "p2")  # likewise
    await capped.on_chart_opened("SOLUSDT", "c1")
    await capped.on_chart_opened("ETHUSDT", "c2")
    clock.advance(60)
    disk[0] = True
    await capped.tick()  # the chart starts are refused for the disk; SOL's position still the cap
    listed = {r.symbol: r.cause for r in capped.start_refused()}
    every = ("BTCUSDT", "SOLUSDT", "ETHUSDT", "XRPUSDT", "DOGEUSDT")  # one recorded, one unknown
    assert listed == {sym: c for sym in every if (c := capped.start_refusal(sym)) is not None}
    causes = {"ETHUSDT": "disk_pressure", "SOLUSDT": "disk_pressure", "XRPUSDT": "symbol_cap"}
    assert listed == causes


async def test_start_refused_is_a_snapshot_that_later_changes_do_not_touch(
    capped: RecordingPolicy, clock: FakeClock, disk: list[bool]
) -> None:
    disk[0] = True
    await capped.on_chart_opened("SOLUSDT", "c1")
    clock.advance(60)
    await capped.tick()
    snapshot = capped.start_refused()
    disk[0] = False
    await capped.tick()  # it starts: the live view is empty now
    assert capped.start_refused() == ()
    assert snapshot == (StartRefused("SOLUSDT", "disk_pressure", ("chart_open",)),)
    entry: Any = snapshot[0]
    with pytest.raises(FrozenInstanceError):
        entry.cause = "symbol_cap"


async def test_start_refused_is_sync_and_changes_nothing(
    capped: RecordingPolicy, clock: FakeClock
) -> None:
    await capped.add_manual("BTCUSDT", OWNER)
    await capped.on_chart_opened("SOLUSDT", "c1")
    clock.advance(60)
    await capped.tick()  # SOL waits, refused for the cap
    before = copy.deepcopy(capped._syms)
    assert not inspect.iscoroutinefunction(capped.start_refused)
    assert not inspect.isawaitable(capped.start_refused()) and capped._syms == before
