"""#2188 S3a: the startup reconcile on the real policy: the rows and open positions are taken
back, and nothing stops before the warm-up gate opens. The step order: `test_sessions.py`."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from structlog.testing import capture_logs

from candleviewer.recorder.errors import RecorderGateOpenError
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy
from candleviewer.recorder.sessions import SessionManager, startup_reconcile
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, FakeSeed, Mem, no_restore
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

GRACE = 1_800.0  # `PolicyConfig.autostop_grace_s`
CHART = {"kind": "chart", "id": "c1"}


@pytest.fixture
async def cold(
    request: pytest.FixtureRequest, clock: FakeClock, bus: FakeBus, audit: FakeAudit, store: Mem
) -> AsyncIterator[RecordingPolicy]:
    """A policy of env "demo", its warm-up gate closed; `parametrize("cold", [n], indirect=True)`
    sets the cap (else 20)."""
    config = PolicyConfig(max_symbols=getattr(request, "param", 20))
    p = RecordingPolicy(
        disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock, recorded=store,
        config=config,
    )  # fmt: skip
    yield p
    await p.stop()


async def _startup(policy: RecordingPolicy, pairs: list[tuple[str, str]] | None = None) -> None:
    sessions = SessionManager(MemRecorderStore(), now_us=UsClock(0), audit=FakeAudit())
    seed = FakeSeed(pairs or [])
    await startup_reconcile(sessions, policy, process_start_us=0, restore_b11=no_restore, seed=seed)


def _starts(audit: FakeAudit) -> list[tuple[str, str, str, str | None]]:
    """`(symbol, actor, reason, trigger_ref)` of each `recorder.start`."""
    return [
        (kw["object_id"], kw["actor_label"], kw["reason"], kw["after_state"]["trigger_ref"])
        for action, kw in audit.records
        if action == "recorder.start"
    ]


async def test_manual_rows_resume_with_one_system_start_each_and_are_not_rewritten(
    cold: RecordingPolicy, store: Mem, audit: FakeAudit
) -> None:
    await store.upsert_manual("BTCUSDT", "u-1", ("trades", "tickers"), 50, "demo")
    await store.upsert_manual("ETHUSDT", None, ("trades",), 500, "demo")  # its user was deleted
    before = copy.deepcopy(store.rows)
    await _startup(cold)
    assert [cold.leaf(s) for s in ("BTCUSDT", "ETHUSDT")] == ["recording", "recording"]
    assert _starts(audit) == [
        ("BTCUSDT", "system:recorder-policy", "manual", "manual:u-1"),
        ("ETHUSDT", "system:recorder-policy", "manual", "manual:recorder-policy"),
    ]
    entry = cold.effective_set()["BTCUSDT"]
    assert (entry.streams, entry.depth) == (("trades", "tickers"), 50)
    assert store.rows == before  # its streams, depth and adder stay as they were


async def test_auto_rows_nothing_holds_linger_from_now_and_a_pin_is_restored(
    cold: RecordingPolicy, store: Mem, audit: FakeAudit, clock: FakeClock
) -> None:
    await store.upsert_auto("BTCUSDT", "chart_open", CHART, "demo")
    await store.upsert_auto("ETHUSDT", "chart_open", {"kind": "recorder", "id": "session"}, "demo")
    await store.upsert_auto("SOLUSDT", "position_open", {"kind": "position", "id": "gone"}, "demo")
    await store.set_pinned(await store.upsert_auto("XRPUSDT", "chart_open", CHART, "demo"), True)
    await _startup(cold)
    deadline = datetime.fromtimestamp(clock() + GRACE, UTC)
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    found = {
        s: (cold.leaf(s), cold.linger_until(s), cold.effective_set()[s].pinned) for s in symbols
    }
    assert found == {s: ("lingering", deadline, s == "XRPUSDT") for s in symbols}
    assert [(s, r) for s, _, r, _ in _starts(audit)] == [  # each resumes for its row's reason
        ("BTCUSDT", "chart_open"), ("ETHUSDT", "chart_open"),
        ("SOLUSDT", "position_open"), ("XRPUSDT", "chart_open"),
    ]  # fmt: skip


async def test_a_resumed_auto_row_keeps_its_reason_in_its_set_changes_and_its_stop_record(
    cold: RecordingPolicy, store: Mem, bus: FakeBus, audit: FakeAudit, clock: FakeClock
) -> None:
    """Derived: the position of a `position_open` row is gone, so the row lingers, then stops."""
    await store.upsert_auto("SOLUSDT", "position_open", {"kind": "position", "id": "gone"}, "demo")
    await _startup(cold)
    clock.advance(GRACE + 60)
    await cold.tick()
    stops = [(kw["object_id"], kw["reason"]) for a, kw in audit.records if a == "recorder.stop"]
    assert stops == [("SOLUSDT", "position_open")]
    changes = [
        (e.change, e.reason, e.priority) for _, e in bus.events if getattr(e, "change", None)
    ]
    assert changes == [("added", "position_open", 200), ("removed", "position_open", 200)]


async def test_a_row_reason_no_trigger_of_the_policy_holds_is_skipped_with_a_warning(
    cold: RecordingPolicy, store: Mem
) -> None:
    """Derived: a `rule_dependency` row, a reason nothing in the policy starts or stops."""
    await store.upsert_auto("ADAUSDT", "rule_dependency", {"kind": "rule", "id": "r1"}, "demo")
    await store.upsert_auto("SOLUSDT", "chart_open", CHART, "demo")
    with capture_logs() as logs:
        await _startup(cold)
    assert list(cold.effective_set()) == ["SOLUSDT"]  # and reading the set raises nothing
    assert cold.leaf("ADAUSDT") is None
    skipped = [log for log in logs if log["event"] == "recorder_adopt_skipped"]
    assert [(log["symbol"], log["reason"], log["log_level"]) for log in skipped] == [
        ("ADAUSDT", "rule_dependency", "warning")
    ]


async def test_a_store_failure_on_one_symbol_starts_the_rest_and_a_later_tick_retries_it(
    cold: RecordingPolicy, store: Mem
) -> None:
    """Derived: the seeded position's start writes its row, and that write fails once."""
    await store.upsert_manual("BTCUSDT", "u-1", ("trades",), 50, "demo")
    store.fail.add("upsert_auto")
    await _startup(cold, [("SOLUSDT", "p1")])  # `reconcile_all` isolates the failing symbol
    assert (cold.leaf("BTCUSDT"), cold.leaf("SOLUSDT")) == ("recording", None)
    assert cold.position_open("SOLUSDT") and not cold.position_open("XRPUSDT")  # the gate opened
    store.fail.discard("upsert_auto")
    await cold.tick()
    assert cold.leaf("SOLUSDT") == "recording"


async def test_a_seeded_position_resumes_recording_for_position_open_with_or_without_a_row(
    cold: RecordingPolicy, store: Mem, audit: FakeAudit
) -> None:
    await store.upsert_auto("ETHUSDT", "chart_open", CHART, "demo")  # the row of a chart now gone
    await _startup(cold, [("ETHUSDT", "p1"), ("SOLUSDT", "p2")])  # SOLUSDT has no row at all
    assert [(e.reason, e.lingering) for e in cold.effective_set().values()] == [
        ("position_open", False)
    ] * 2
    assert _starts(audit) == [
        ("ETHUSDT", "system:recorder-policy", "position_open", "position:p1"),
        ("SOLUSDT", "system:recorder-policy", "position_open", "position:p2"),
    ]


@pytest.mark.parametrize("cold", [1], indirect=True)
async def test_no_symbol_stops_before_the_gate_opens_and_the_expired_ones_stop_after_it(
    cold: RecordingPolicy, store: Mem, bus: FakeBus, audit: FakeAudit, clock: FakeClock
) -> None:
    await store.upsert_auto("ETHUSDT", "chart_open", CHART, "demo")  # a chart of the dead process
    await cold.adopt_recorded(await cold.load_recorded())
    await cold.reconcile_all()
    assert cold.leaf("ETHUSDT") == "lingering"
    clock.advance(GRACE + 60)  # its grace is over
    await cold.on_position_opened("XRPUSDT", "p1")  # the one slot is taken
    for _ in range(3):
        await cold.tick()
    assert (cold.leaf("ETHUSDT"), cold.leaf("XRPUSDT")) == ("lingering", None)  # no stop, no evict
    assert cold.start_refusal("XRPUSDT") == "symbol_cap"  # the position waits, queued
    assert "recorder.stop" not in audit.actions()
    assert all(getattr(event, "change", "") != "removed" for _, event in bus.events)
    assert cold.position_open("SOLUSDT")  # while the gate is closed, true for every symbol
    cold.positions_reloaded()
    await cold.tick()
    stops = [kw["object_id"] for action, kw in audit.records if action == "recorder.stop"]
    assert stops == ["ETHUSDT"] and cold.leaf("XRPUSDT") == "recording"


async def test_a_soft_removed_row_and_a_row_of_another_env_are_not_adopted(
    cold: RecordingPolicy, store: Mem
) -> None:
    other = await store.upsert_manual("BTCUSDT", "u-1", ("trades",), 50, "live")
    gone = await store.upsert_manual("ETHUSDT", "u-1", ("trades",), 50, "demo")
    await store.soft_remove(gone["id"])
    await store.upsert_manual("SOLUSDT", "u-1", ("trades",), 50, "demo")
    removed = {**gone, "removed_at": datetime(2026, 10, 1, tzinfo=UTC)}  # as a wrong read hands it
    await cold.adopt_recorded([other, removed])  # skipped all the same
    await _startup(cold)
    assert list(cold.effective_set()) == ["SOLUSDT"]  # the read is the policy's env, active only


async def test_adoption_is_refused_once_the_gate_is_open(cold: RecordingPolicy) -> None:
    cold.positions_reloaded()
    with pytest.raises(RecorderGateOpenError):
        await cold.adopt_recorded([])
    with pytest.raises(RecorderGateOpenError):
        await cold.adopt_positions([])
