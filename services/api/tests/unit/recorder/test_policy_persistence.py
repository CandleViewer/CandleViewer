"""#2188 S2b: the recording policy writes `recorded_symbols` first and memory second."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Coroutine

import pytest
from structlog.testing import capture_logs

from candleviewer.recorder.errors import RecorderSymbolNotRecordedError
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.policy import RecordedStore, RecordingPolicy, user_actor
from candleviewer.recorder.sessions import DEFAULT_STREAMS, SessionManager
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

OWNER = user_actor("owner-1")
POS, CHART = {"kind": "position", "id": "p1"}, {"kind": "chart", "id": "c1"}


def test_the_repository_has_every_port_method_with_its_parameters() -> None:
    for name, port_method in vars(RecordedStore).items():
        if callable(port_method) and not name.startswith("_"):
            ours = list(inspect.signature(port_method).parameters)
            theirs = list(inspect.signature(getattr(SqlAlchemyRecorderRepository, name)).parameters)
            assert ours == theirs, name  # M10's repository is what gets injected


def _row(store: Mem) -> dict[str, object]:
    row = store.active("BTCUSDT")
    assert row is not None
    return row


async def _lingering(policy: RecordingPolicy) -> None:
    """BTCUSDT recorded for a position that closed: lingering, the grace not over."""
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.on_position_closed("BTCUSDT", "p1")


async def _expire(policy: RecordingPolicy, clock: FakeClock) -> None:
    clock.advance(1_800)
    await policy.tick()


async def _spin() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_add_manual_writes_the_row_before_it_audits(
    policy: RecordingPolicy, store: Mem, trace: list[str]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 50)
    row = _row(store)
    assert (row["env"], row["reason"], row["added_by"]) == ("demo", "manual", "owner-1")
    assert (row["streams"], row["orderbook_depth"]) == (["trades"], 50)
    assert trace == ["upsert_manual", "audit:recorder.start"]


async def test_add_manual_names_the_recorders_default_streams(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    assert _row(store)["streams"] == list(DEFAULT_STREAMS)  # the DDL default has one fewer


async def test_a_failed_add_raises_and_starts_and_audits_nothing(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, bus: FakeBus, clock: FakeClock
) -> None:
    store.fail.add("upsert_manual")
    with pytest.raises(OSError, match="pg down"):
        await policy.add_manual("BTCUSDT", OWNER)
    await _expire(policy, clock)  # a manual entry left in memory would start here
    assert (policy.leaf("BTCUSDT"), audit.records, bus.events) == (None, [], [])
    assert policy._syms == {}  # nothing is left behind


async def test_remove_manual_clears_the_row(policy: RecordingPolicy, store: Mem) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.remove_manual("BTCUSDT", OWNER)
    assert store.active("BTCUSDT") is None


async def test_remove_manual_demotes_a_row_that_holds_a_trigger(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.remove_manual("BTCUSDT", OWNER)
    assert (_row(store)["reason"], _row(store)["reason_refs"]) == ("position_open", [POS])


async def test_a_failed_remove_leaves_the_entry_manual(policy: RecordingPolicy, store: Mem) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",))
    store.fail.add("clear_manual")
    with pytest.raises(OSError, match="pg down"):
        await policy.remove_manual("BTCUSDT", OWNER)
    assert policy.effective_set()["BTCUSDT"].streams == ("trades",)  # still the manual entry


async def test_set_pin_audits_then_writes_then_applies(
    policy: RecordingPolicy, store: Mem, trace: list[str]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    trace.clear()
    await policy.set_pin("BTCUSDT", True, OWNER)
    assert trace == ["get_by_symbol", "audit:retention.change", "set_pinned"]
    assert _row(store)["pinned"] and policy.effective_set()["BTCUSDT"].pinned


async def test_a_failed_pin_write_leaves_memory_unchanged(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    store.fail.add("set_pinned")
    with pytest.raises(OSError, match="pg down"):
        await policy.set_pin("BTCUSDT", True, OWNER)
    assert not policy.effective_set()["BTCUSDT"].pinned


async def test_a_pin_needs_an_active_row(policy: RecordingPolicy, audit: FakeAudit) -> None:
    with pytest.raises(RecorderSymbolNotRecordedError):
        await policy.set_pin("BTCUSDT", True, OWNER)
    assert audit.records == [] and policy._syms == {}


async def test_set_pin_does_not_swallow_a_false_from_the_store(
    policy: RecordingPolicy, store: Mem, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def row_gone(recorded_id: str, pinned: bool) -> bool:
        return False

    await policy.add_manual("BTCUSDT", OWNER)
    monkeypatch.setattr(store, "set_pinned", row_gone)
    with pytest.raises(RecorderSymbolNotRecordedError):
        await policy.set_pin("BTCUSDT", True, OWNER)
    assert not policy.effective_set()["BTCUSDT"].pinned


async def test_unpinning_an_idle_symbol_soft_removes_the_row_only_the_pin_kept(
    policy: RecordingPolicy, store: Mem
) -> None:
    await store.upsert_auto("BTCUSDT", "chart_open", CHART, "demo")  # a row from an earlier run
    await policy.set_pin("BTCUSDT", True, OWNER)
    await policy.set_pin("BTCUSDT", False, OWNER)
    assert store.active("BTCUSDT") is None


async def test_a_start_writes_the_auto_row_with_the_refs_the_symbol_holds(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await policy.on_chart_opened("BTCUSDT", "c1")
    clock.advance(60)
    await policy.on_position_opened("BTCUSDT", "p1")
    row = _row(store)
    assert (row["env"], row["reason"], row["reason_refs"]) == (
        "demo",
        "position_open",
        [POS, CHART],
    )


async def test_refs_follow_triggers_as_they_open_and_close(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.on_chart_opened("BTCUSDT", "c1")
    assert _row(store)["reason_refs"] == [POS, CHART]
    await policy.on_position_closed("BTCUSDT", "p1")
    await policy.on_chart_closed("BTCUSDT", "c1")
    assert _row(store)["reason_refs"] == []


async def test_a_failed_ref_mirror_never_skips_the_reconcile(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")
    store.fail.add("remove_reason_ref")
    await policy.on_position_closed("BTCUSDT", "p1")  # the ref write fails, the grace still starts
    assert policy.effective_set()["BTCUSDT"].lingering


async def test_a_failed_start_write_starts_nothing_and_the_next_tick_retries(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit
) -> None:
    store.fail.add("upsert_auto")
    with pytest.raises(OSError, match="pg down"):
        await policy.on_position_opened("BTCUSDT", "p1")
    assert (policy.leaf("BTCUSDT"), audit.records) == (None, [])
    store.fail.clear()
    await policy.tick()
    assert policy.leaf("BTCUSDT") == "recording" and store.active("BTCUSDT") is not None


async def test_a_symbol_that_raises_does_not_starve_the_tick(
    policy: RecordingPolicy, store: Mem, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.fail.add("upsert_auto")
    for symbol in ("BTCUSDT", "ETHUSDT"):
        with pytest.raises(OSError, match="pg down"):
            await policy.on_position_opened(symbol, "p1")
    store.fail.clear()
    real = policy._reconcile

    async def reconcile(symbol: str) -> None:
        if symbol == "BTCUSDT":
            raise OSError("poison")
        await real(symbol)

    monkeypatch.setattr(policy, "_reconcile", reconcile)
    await policy.tick()
    assert policy.leaf("ETHUSDT") == "recording"


async def test_a_stop_soft_removes_the_auto_row(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await _lingering(policy)
    assert store.active("BTCUSDT") is not None  # still recorded in the grace window
    await _expire(policy, clock)
    assert store.active("BTCUSDT") is None and len(store.rows) == 1  # soft: the row is kept


async def test_a_stop_keeps_a_manual_row(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await store.upsert_manual("BTCUSDT", None, (), None, "demo")  # a row from an earlier run
    await _lingering(policy)
    await _expire(policy, clock)
    assert _row(store)["reason"] == "manual"


async def test_a_stop_keeps_a_pinned_row(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.set_pin("BTCUSDT", True, OWNER)
    await policy.on_position_closed("BTCUSDT", "p1")
    await _expire(policy, clock)
    assert (policy.leaf("BTCUSDT"), _row(store)["pinned"]) == (None, True)


async def _stop_races(
    policy: RecordingPolicy, store: Mem, clock: FakeClock, racer: Coroutine[object, object, None]
) -> object:
    """A stop whose row removal waits on a gate, `racer` started behind it, then the gate opens.
    Returns what `racer` raised, if it did."""
    await _lingering(policy)
    clock.advance(1_800)
    store.hold["soft_remove"] = gate = asyncio.Event()
    stop = asyncio.create_task(policy.tick())
    await _spin()
    racing = asyncio.create_task(racer)
    await _spin()
    gate.set()
    return (await asyncio.gather(stop, racing, return_exceptions=True))[1]


async def test_a_stop_in_flight_cannot_erase_a_manual_add(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await _stop_races(policy, store, clock, policy.add_manual("BTCUSDT", OWNER))
    assert _row(store)["reason"] == "manual"


async def test_a_stop_in_flight_cannot_erase_a_pin(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    raised = await _stop_races(policy, store, clock, policy.set_pin("BTCUSDT", True, OWNER))
    assert isinstance(raised, RecorderSymbolNotRecordedError)  # the row went first, unpinned
    assert not any(r["pinned"] and r["removed"] for r in store.rows.values())


async def test_a_set_change_with_no_row_opens_on_the_constant_ref_and_warns() -> None:
    mgr = SessionManager(MemRecorderStore(), now_us=UsClock(0), audit=FakeAudit())
    event = RecorderSetChanged(
        symbol="BTCUSDT", change="added", reason="manual", reasons=("manual",),
        priority=300, auto_evictable=False, ts_event=0,
    )  # fmt: skip
    with capture_logs() as logs:
        await mgr.on_set_changed(event)
    levels = [e["log_level"] for e in logs if e["event"] == "recorder_session_row_fallback"]
    assert levels == ["warning"]
