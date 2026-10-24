"""#2188 S2b: the recording policy audits, writes `recorded_symbols`, then changes memory."""

from __future__ import annotations

import asyncio
import copy
import inspect
from collections.abc import Coroutine
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.recorder.errors import InvalidRecorderActorError, RecorderSymbolNotRecordedError
from candleviewer.recorder.models import SYSTEM_ACTOR, RecorderSetChanged
from candleviewer.recorder.policy import PolicyConfig, RecordedStore, RecordingPolicy, user_actor
from candleviewer.recorder.sessions import DEFAULT_STREAMS, SessionManager
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

OWNER, MANAGER = user_actor("owner-1"), user_actor("mgr-2")
POS, CHART = {"kind": "position", "id": "p1"}, {"kind": "chart", "id": "c1"}
SYSTEM = "system:recorder-policy"


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


def _trail(audit: FakeAudit) -> list[tuple[str, str]]:
    """The audit records as `(action, actor_label)`."""
    return [(a, kw["actor_label"]) for a, kw in audit.records]


def _refuse_audits(audit: FakeAudit, monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(action: str, **kw: Any) -> None:
        raise OSError("audit down")

    monkeypatch.setattr(audit, "emit", refuse)


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


async def _stale_row(store: Mem) -> None:
    """An auto row from an earlier run whose trigger is gone: only a pin would keep it."""
    rid = await store.upsert_auto("BTCUSDT", "chart_open", CHART, "demo")
    store.rows[rid]["reason_refs"].clear()


async def test_add_manual_writes_the_row(policy: RecordingPolicy, store: Mem) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 50)
    row = _row(store)
    assert (row["env"], row["reason"], row["added_by"]) == ("demo", "manual", "owner-1")
    assert (row["streams"], row["orderbook_depth"]) == (["trades"], 50)


async def test_a_fresh_add_audits_the_user_before_its_row_then_the_system_starts_the_session(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    assert trace == ["audit:recorder.start", "upsert_manual", "audit:recorder.start"]
    assert _trail(audit) == [("recorder.start", "user:owner-1"), ("recorder.start", SYSTEM)]
    assert audit.records[0][1]["after_state"] == {
        "symbol": "BTCUSDT", "reason": "manual", "actor": "owner-1", "trigger_ref": "manual:owner-1"
    }  # fmt: skip


async def test_add_manual_names_the_recorders_default_streams(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    assert _row(store)["streams"] == list(DEFAULT_STREAMS)  # the DDL default has one fewer


async def test_a_refused_add_write_leaves_the_record_and_starts_nothing(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, bus: FakeBus, clock: FakeClock
) -> None:
    store.fail.add("upsert_manual")
    with pytest.raises(OSError, match="pg down"):
        await policy.add_manual("BTCUSDT", OWNER)
    await _expire(policy, clock)  # a manual entry left in memory would start here
    assert (policy.leaf("BTCUSDT"), audit.actions(), bus.events) == (None, ["recorder.start"], [])
    assert policy._syms == {}  # nothing is left behind


async def test_a_failed_add_audit_writes_no_row_and_changes_no_memory(
    policy: RecordingPolicy,
    store: Mem,
    bus: FakeBus,
    audit: FakeAudit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _refuse_audits(audit, monkeypatch)
    with pytest.raises(OSError, match="audit down"):
        await policy.add_manual("BTCUSDT", OWNER)
    assert (store.rows, policy._syms, bus.events) == ({}, {}, [])


@pytest.mark.parametrize("failing", ["the audit", "the row write"])
async def test_a_failed_add_keeps_a_lingering_symbols_entry_so_it_still_stops(
    policy: RecordingPolicy,
    store: Mem,
    audit: FakeAudit,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    failing: str,
) -> None:
    await _lingering(policy)
    if failing == "the audit":
        _refuse_audits(audit, monkeypatch)
    else:
        store.fail.add("upsert_manual")
    with pytest.raises(OSError):
        await policy.add_manual("BTCUSDT", OWNER)
    monkeypatch.undo()
    store.fail.clear()
    await _expire(policy, clock)  # the entry holds the grace deadline
    assert (policy.leaf("BTCUSDT"), store.active("BTCUSDT")) == (None, None)


async def test_an_add_over_a_position_recorded_symbol_writes_one_user_record_and_promotes_it(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")
    audit.records.clear()
    await policy.add_manual("BTCUSDT", OWNER)
    assert _trail(audit) == [("recorder.start", "user:owner-1")]
    assert (_row(store)["reason"], _row(store)["reason_refs"]) == ("manual", [POS])


async def test_a_re_add_of_a_manual_entry_changes_nothing_and_writes_no_record(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, trace: list[str]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 50)
    audit.records.clear()
    trace.clear()
    await policy.add_manual("BTCUSDT", MANAGER, ("tickers",), 500)  # a change goes through update
    assert (audit.records, trace) == ([], [])
    row = _row(store)
    assert (row["streams"], row["orderbook_depth"], row["added_by"]) == (["trades"], 50, "owner-1")


async def test_an_add_writes_the_refs_the_symbol_already_holds(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.on_chart_opened("BTCUSDT", "c1")  # not recording yet: no row to mirror to
    await policy.on_chart_opened("BTCUSDT", "c2")
    await policy.add_manual("BTCUSDT", OWNER)
    assert _row(store)["reason_refs"] == [CHART, {"kind": "chart", "id": "c2"}]


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


async def test_remove_manual_audits_the_remover_before_it_clears_the_row(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    trace.clear()
    await policy.remove_manual("BTCUSDT", MANAGER)
    assert trace == ["audit:recorder.stop", "get_by_symbol", "clear_manual"]
    assert _trail(audit)[-1] == ("recorder.stop", "user:mgr-2")
    assert audit.records[-1][1]["after_state"] == {
        "symbol": "BTCUSDT", "reason": "manual", "actor": "mgr-2", "trigger_ref": "manual:owner-1"
    }  # fmt: skip


async def test_a_remove_on_a_symbol_that_keeps_a_chart_writes_one_user_record(
    policy: RecordingPolicy, audit: FakeAudit, clock: FakeClock
) -> None:
    await policy.on_chart_opened("BTCUSDT", "c1")
    clock.advance(60)
    await policy.tick()  # recording for the chart
    await policy.add_manual("BTCUSDT", OWNER)
    audit.records.clear()
    await policy.remove_manual("BTCUSDT", MANAGER)  # no session stops
    assert _trail(audit) == [("recorder.stop", "user:mgr-2")]


async def test_a_failed_remove_audit_leaves_the_row_and_the_entry(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, monkeypatch: pytest.MonkeyPatch
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",))
    _refuse_audits(audit, monkeypatch)
    with pytest.raises(OSError, match="audit down"):
        await policy.remove_manual("BTCUSDT", OWNER)
    assert _row(store)["reason"] == "manual"
    assert policy.effective_set()["BTCUSDT"].streams == ("trades",)


async def test_a_failed_remove_leaves_the_entry_manual(policy: RecordingPolicy, store: Mem) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",))
    store.fail.add("clear_manual")
    with pytest.raises(OSError, match="pg down"):
        await policy.remove_manual("BTCUSDT", OWNER)
    assert policy.effective_set()["BTCUSDT"].streams == ("trades",)  # still the manual entry


async def test_a_remove_writes_a_ref_whose_mirror_failed(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    store.fail.add("add_reason_ref")
    await policy.on_position_opened("BTCUSDT", "p1")  # the mirror fails: best effort
    store.fail.clear()
    await policy.remove_manual("BTCUSDT", OWNER)  # `clear_manual` must still see the position
    assert (_row(store)["reason"], _row(store)["reason_refs"]) == ("position_open", [POS])


async def test_a_trigger_held_before_the_manual_row_survives_the_remove(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await policy.on_chart_opened("BTCUSDT", "c1")
    await policy.add_manual("BTCUSDT", OWNER)
    clock.advance(60)
    await policy.tick()  # the chart's dwell passes
    await policy.remove_manual("BTCUSDT", OWNER)
    assert (_row(store)["reason"], _row(store)["reason_refs"]) == ("chart_open", [CHART])
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)  # a pin needs the active row
    assert _row(store)["pinned"]


async def test_set_pin_audits_then_writes_then_applies(
    policy: RecordingPolicy, store: Mem, trace: list[str]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    trace.clear()
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert trace == ["get_by_symbol", "audit:retention.change", "set_pinned"]
    assert _row(store)["pinned"] and policy.effective_set()["BTCUSDT"].pinned


async def test_a_failed_pin_write_leaves_memory_unchanged(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    store.fail.add("set_pinned")
    with pytest.raises(OSError, match="pg down"):
        await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert not policy.effective_set()["BTCUSDT"].pinned


async def test_a_pin_needs_an_active_row(policy: RecordingPolicy, audit: FakeAudit) -> None:
    with pytest.raises(RecorderSymbolNotRecordedError):
        await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert audit.records == [] and policy._syms == {}


async def test_set_pin_does_not_swallow_a_false_from_the_store(
    policy: RecordingPolicy, store: Mem, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def row_gone(recorded_id: str, pinned: bool) -> bool:
        return False

    await policy.add_manual("BTCUSDT", OWNER)
    monkeypatch.setattr(store, "set_pinned", row_gone)
    with pytest.raises(RecorderSymbolNotRecordedError):
        await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert not policy.effective_set()["BTCUSDT"].pinned


async def test_unpinning_an_idle_symbol_soft_removes_the_row_only_the_pin_kept(
    policy: RecordingPolicy, store: Mem
) -> None:
    await _stale_row(store)
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    await policy.set_pin("BTCUSDT", False, OWNER, restricted=False)
    assert store.active("BTCUSDT") is None


@pytest.mark.parametrize("earlier_run", ["manual", "refs"])
async def test_unpinning_keeps_a_row_whose_reason_memory_does_not_hold(
    policy: RecordingPolicy, store: Mem, earlier_run: str
) -> None:
    if earlier_run == "manual":
        await store.upsert_manual("BTCUSDT", None, (), None, "demo")
    else:
        await store.upsert_auto("BTCUSDT", "chart_open", CHART, "demo")
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    await policy.set_pin("BTCUSDT", False, OWNER, restricted=False)
    assert not _row(store)["pinned"]  # still active: the row's own reason kept it


@pytest.mark.parametrize("held", ["manual", "chart", "position", "lingering"])
async def test_unpinning_keeps_the_row_and_the_entry_of_a_symbol_still_held(
    policy: RecordingPolicy, store: Mem, held: str
) -> None:
    if held == "manual":
        await policy.add_manual("BTCUSDT", OWNER)
    elif held == "chart":  # not recording (the dwell is 60 s): the row is one from an earlier run
        await _stale_row(store)
        await policy.on_chart_opened("BTCUSDT", "c1")
    elif held == "position":
        await policy.on_position_opened("BTCUSDT", "p1")
    else:
        await _lingering(policy)
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    await policy.set_pin("BTCUSDT", False, OWNER, restricted=False)
    assert not _row(store)["pinned"] and "BTCUSDT" in policy._syms


async def test_an_unpinned_lingering_symbol_still_stops_after_the_grace(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await _lingering(policy)
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    await policy.set_pin("BTCUSDT", False, OWNER, restricted=False)
    await _expire(policy, clock)
    assert (policy.leaf("BTCUSDT"), store.active("BTCUSDT")) == (None, None)


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


async def test_a_trigger_that_is_already_held_is_not_mirrored_again(
    policy: RecordingPolicy, trace: list[str]
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.on_chart_opened("BTCUSDT", "c1")
    trace.clear()
    await policy.on_position_opened("BTCUSDT", "p1")  # the same ids again
    await policy.on_chart_opened("BTCUSDT", "c1")
    assert trace == []


async def test_a_start_whose_trigger_closed_meanwhile_writes_and_starts_nothing(
    policy: RecordingPolicy, store: Mem
) -> None:
    s = policy._sym("XRPUSDT", kind="protected")
    assert s is not None
    await policy._add("XRPUSDT", s, "position_open")  # its position closed while the start waited
    assert (policy.leaf("XRPUSDT"), store.rows) == (None, {})


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
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    await policy.on_position_closed("BTCUSDT", "p1")
    await _expire(policy, clock)
    assert (policy.leaf("BTCUSDT"), _row(store)["pinned"]) == (None, True)


async def test_a_stop_clears_the_grace_deadline_so_a_pinned_entry_is_not_due_again(
    policy: RecordingPolicy, clock: FakeClock
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.set_pin("BTCUSDT", True, OWNER)
    await policy.on_position_closed("BTCUSDT", "p1")
    await _expire(policy, clock)  # it stops; the pin keeps its entry
    assert not policy._due("BTCUSDT", policy._syms["BTCUSDT"])  # a spent deadline stayed due


async def test_a_stop_whose_row_removal_fails_stays_due_so_a_later_tick_retries_it(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    await _lingering(policy)
    store.fail.add("soft_remove")
    await _expire(policy, clock)  # the stop's row removal fails
    assert policy._due("BTCUSDT", policy._syms["BTCUSDT"])  # the deadline is cleared only after
    store.fail.discard("soft_remove")
    await policy.tick()
    assert store.active("BTCUSDT") is None  # the retry removed the row


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
    pin = policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    raised = await _stop_races(policy, store, clock, pin)
    assert isinstance(raised, RecorderSymbolNotRecordedError)  # the row went first, unpinned
    assert not any(r["pinned"] and r["removed"] for r in store.rows.values())


async def test_a_stop_in_flight_cannot_take_a_retention_change(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    change = policy.set_retention("BTCUSDT", 10, OWNER, restricted=False)
    raised = await _stop_races(policy, store, clock, change)
    assert isinstance(raised, RecorderSymbolNotRecordedError)  # the row went first, unwritten
    assert not any(r["retention_days"] is not None for r in store.rows.values())


def _live_rows(store: Mem) -> list[dict[str, Any]]:
    return [copy.deepcopy(r) for r in store.rows.values() if r["env"] == "live"]


async def test_the_demo_policy_leaves_the_live_rows_alone(
    policy: RecordingPolicy, store: Mem, clock: FakeClock
) -> None:
    """Demo/live isolation (C-2.11): every store call of the policy carries its own env, so no
    write, pin, ref mirror or stop reaches the `live` row of the same symbol."""
    await store.upsert_manual("BTCUSDT", None, ("trades",), 50, "live")
    await store.upsert_auto("ETHUSDT", "chart_open", CHART, "live")
    before = _live_rows(store)
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.update_manual("BTCUSDT", OWNER, depth=500)
    await policy.on_position_opened("BTCUSDT", "p1")  # the ref mirror
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)  # left pinned, never unpinned
    await policy.remove_manual("BTCUSDT", OWNER)
    await policy.on_position_opened("ETHUSDT", "p1")
    await policy.on_position_closed("ETHUSDT", "p1")
    await _expire(policy, clock)  # ETHUSDT stops, its demo row goes
    assert _live_rows(store) == before
    demo = store.active("BTCUSDT", "demo")
    assert demo is not None and (demo["reason"], demo["pinned"]) == ("position_open", True)
    assert store.active("ETHUSDT", "demo") is None


async def test_a_set_change_with_no_row_opens_on_the_constant_ref_and_warns() -> None:
    store = MemRecorderStore()
    mgr = SessionManager(store, now_us=UsClock(0), audit=FakeAudit())
    event = RecorderSetChanged(
        symbol="BTCUSDT", change="added", reason="manual", reasons=("manual",),
        priority=300, auto_evictable=False, ts_event=0,
    )  # fmt: skip
    with capture_logs() as logs:
        await mgr.on_set_changed(event)
    levels = [e["log_level"] for e in logs if e["event"] == "recorder_session_row_fallback"]
    assert levels == ["warning"]
    assert store.refs == {"BTCUSDT": {"kind": "recorder", "id": "session"}}  # the row it opened
    assert mgr.live_session("BTCUSDT") is not None  # and the session on it


async def test_the_auto_row_is_written_before_b11_starts_and_removed_after_it_stops(
    policy: RecordingPolicy, store: Mem, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invariant the orchestrator asked to see stated: `_add` writes the auto row before B11
    starts, and `_prune` soft-removes it once B11 has stopped, both under the policy's lock. The
    B11 hooks are bounded by `_settle` and may run after the lock is released, so no row write
    lives in them."""
    seen: list[tuple[str, bool, str | None]] = []
    enter = store._enter

    async def probe(op: str) -> None:
        if op in ("upsert_auto", "soft_remove"):
            seen.append((op, policy._lock.locked(), policy.leaf("BTCUSDT")))
        await enter(op)

    monkeypatch.setattr(store, "_enter", probe)
    await _lingering(policy)
    await _expire(policy, clock)
    assert seen == [("upsert_auto", True, None), ("soft_remove", True, "stopped")]


async def test_unpinning_keeps_the_row_of_a_refused_position(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit, store: Mem
) -> None:
    """Delta D-3: the cap is full of manual entries, so a position is refused and has no
    session; its symbol's idle row from an earlier run is kept by the position alone."""
    p = RecordingPolicy(
        disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock,
        config=PolicyConfig(max_symbols=1), recorded=store,
    )  # fmt: skip
    p.positions_reloaded()
    await p.add_manual("ETHUSDT", OWNER)
    await _stale_row(store)
    await p.on_position_opened("BTCUSDT", "p1")  # refused: no victim, no B11
    await p.set_pin("BTCUSDT", True, OWNER, restricted=False)
    await p.set_pin("BTCUSDT", False, OWNER, restricted=False)
    assert not _row(store)["pinned"]  # still active: the position kept it
    await p.stop()


async def test_a_trigger_during_the_linger_after_a_remove_gets_its_row(
    policy: RecordingPolicy, store: Mem
) -> None:
    """Delta D-1: the remove cleared the manual row while B11 lingers; a position opened then
    keeps the session, and writes the row its reason needs, so a pin still finds it."""
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.remove_manual("BTCUSDT", OWNER)
    assert store.active("BTCUSDT") is None  # lingering, with no row
    await policy.on_position_opened("BTCUSDT", "p1")
    assert (_row(store)["reason"], _row(store)["reason_refs"]) == ("position_open", [POS])
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert _row(store)["pinned"]


async def test_a_failed_ref_sync_at_the_add_still_applies_the_entry(
    policy: RecordingPolicy, store: Mem
) -> None:
    """Delta D-2: the refs are written best effort after the entry is applied; the remove
    brings them up to date before it decides, so the row is demoted, not lost."""
    await policy.on_chart_opened("BTCUSDT", "c1")
    store.fail.add("add_reason_ref")
    with capture_logs() as logs:
        await policy.add_manual("BTCUSDT", OWNER)
    assert policy._syms["BTCUSDT"].manual is not None and _row(store)["reason"] == "manual"
    assert [e["event"] for e in logs if e["log_level"] == "warning"] == ["recorder_ref_sync_failed"]
    store.fail.discard("add_reason_ref")
    await policy.remove_manual("BTCUSDT", OWNER)
    assert (_row(store)["reason"], _row(store)["reason_refs"]) == ("chart_open", [CHART])


@pytest.mark.parametrize("op", ["remove", "pin"])
async def test_remove_and_pin_refuse_a_non_user_actor_before_any_io(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str], op: str
) -> None:
    """Delta D-4: as add and update do; a user's list change is never recorded as the system's."""
    await policy.add_manual("BTCUSDT", OWNER)
    audit.records.clear()
    trace.clear()
    with pytest.raises(InvalidRecorderActorError):
        if op == "remove":
            await policy.remove_manual("BTCUSDT", SYSTEM_ACTOR)
        else:
            await policy.set_pin("BTCUSDT", True, SYSTEM_ACTOR, restricted=False)
    assert (audit.records, trace) == ([], [])
