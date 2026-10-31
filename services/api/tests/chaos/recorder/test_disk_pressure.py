"""C-13.6 #13 (disk full during recording), E16-Q04: the disk-pressure ladder end to end.

The ladder at the CODE's thresholds (BQ-3 ruling: `BudgetConfig` warn 80, autostop 90 or free
< 15 %, halt 95 or free < 5 %), not the ticket's 76/81/91/96 reading of ADR-0015: 76 % is the
no-action control, 81 % warns, 91 % stops new chart-open recording and accelerates retention,
96 % halts the writer for symbols without a position and pauses the non-pinned auto-recorded ones.
Throughout, every pinned byte is unchanged (sha256), and the negative control proves that
assertion can fail. Each step is arrange -> fill -> sample + reaper pass -> assert.
"""

from __future__ import annotations

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms.ports import RequestRecord
from candleviewer.recorder.budget import SUGGESTED_ACTIONS
from candleviewer.recorder.models import DiskPressureLevel as L
from candleviewer.recorder.policy import user_actor
from candleviewer.recorder.writer import GAP_CAUSE
from candleviewer.storage.retention.ports import Partition
from candleviewer.storage.retention.reaper import Reaper, Reason
from tests.chaos.recorder._ladder import AUTO, PINNED, LadderRig
from tests.unit.oms.submit_rig import STOP, rigged

pytestmark = pytest.mark.chaos
FEED = 300


def _codes(rig: LadderRig) -> list[tuple[str, str]]:
    return [(sev, code) for sev, code, _ in rig.retention.events]


def _drops(rig: LadderRig) -> list[str]:
    return [e for e in rig.retention.log if e.startswith("drop:")]


def _balanced(rig: LadderRig) -> None:
    produced = sum(rig.mix.produced_rows.values())
    assert produced == rig.written() + rig.dropped(), "INVARIANT: no silent loss"


async def test_disk_ladder_76_takes_no_action(ladder: LadderRig) -> None:
    await ladder.at(76)
    await ladder.feed(FEED)
    assert ladder.budget.level is L.NORMAL and not ladder.budget.accelerate_retention
    assert not ladder.budget.halted and not ladder.budget.refuses_auto_record
    assert not [c for c in _codes(ladder) if c[1].startswith("recorder.disk")], "no ladder event"
    assert ladder.retention.paused == [] and _drops(ladder) == [] and not ladder.reaper.accelerated
    assert ladder.dropped() == 0 and ladder.store.gaps == []
    _balanced(ladder)


async def test_disk_ladder_81_warns_with_suggested_actions(ladder: LadderRig) -> None:
    await ladder.at(81)
    assert ladder.budget.level is L.WARN
    [(severity, code, detail)] = [e for e in ladder.retention.events if e[1].startswith("recorder")]
    assert (severity, code) == ("WARNING", "recorder.disk_budget_warning")
    assert detail["actions"] == SUGGESTED_ACTIONS == "reduce_depth,shorten_retention,unpin"
    assert (detail["trigger"], detail["used_pct"], detail["free_pct"]) == ("threshold", 81, 19)
    assert not ladder.budget.refuses_auto_record and not ladder.reaper.accelerated  # 19 % free
    assert _drops(ladder) == [] and ladder.retention.paused == []


async def test_disk_ladder_91_refuses_auto_record_keeps_explicit(ladder: LadderRig) -> None:
    await ladder.at(91)
    assert ladder.budget.level is L.AUTOSTOP and ladder.budget.refuses_auto_record
    assert ("WARNING", "recorder.disk_autostop") in _codes(ladder)
    policy = ladder.policy
    await policy.add_manual("SOLUSDT", user_actor("owner-1"))  # explicit: keeps recording
    await policy.on_chart_opened("XRPUSDT", "chart-1")  # a new chart-open start: refused
    ladder.clock.advance(60)
    await policy.tick()
    await policy.tick()
    assert {"SOLUSDT", PINNED} <= set(policy.effective_set()) and "XRPUSDT" not in set(
        policy.effective_set()
    )
    refused = [e for key, e in ladder.bus.events if key == "demo.recorder.cap_refused"]
    assert [(e.symbol, e.cause) for e in refused] == [("XRPUSDT", "disk_pressure")]
    assert not ladder.budget.halted, "level 2 never closes the write gate"
    await ladder.feed(FEED)
    assert ladder.written(AUTO) > 0 and ladder.dropped() == 0
    _balanced(ladder)


async def test_disk_ladder_91_accelerates_reaper_below_15_free(ladder: LadderRig) -> None:
    await ladder.at(91)
    assert ladder.reaper.accelerated and ladder.budget.accelerate_retention  # 9 % free
    log = ladder.retention.log
    assert _drops(ladder) == [f"drop:{AUTO}:hot"], "the 20 d partition, past the halved window"
    alert = log.index("event:WARNING:STORAGE_ACCELERATED_RETENTION")
    assert alert < log.index(f"drop:{AUTO}:hot"), "INVARIANT: alert before deletion (SR-096)"
    assert ladder.retention.paused == []
    ladder.assert_pins_intact()


async def test_disk_ladder_96_pauses_unpinned_auto_symbols(ladder: LadderRig) -> None:
    await ladder.at(96)
    assert ladder.budget.level is L.HALT and ladder.budget.halted
    assert ("CRITICAL", "recorder.disk_halt") in _codes(ladder)
    log = ladder.retention.log
    assert ladder.retention.paused == [AUTO], "pinned symbols are never paused"
    assert log.index("event:CRITICAL:STORAGE_DISK_CRITICAL") < log.index(f"pause:{AUTO}")
    await ladder.feed(FEED)
    assert ladder.written(AUTO) == 0, "the gate drops a symbol without a position"
    assert ladder.written(PINNED) > 0, "an open position keeps writing (INV-B11-a)"
    assert ladder.dropped() > 0 and {g["symbol"] for g in ladder.store.gaps} == {AUTO}
    assert {g["cause"] for g in ladder.store.gaps} == {GAP_CAUSE}
    _balanced(ladder)


async def test_disk_ladder_pinned_bytes_identical_throughout(ladder: LadderRig) -> None:
    for pct in (76, 81, 91, 96):
        await ladder.at(pct)
        await ladder.feed(FEED // 3)
        ladder.assert_pins_intact()
    skips = [d for a, d in ladder.retention.audits if a == "retention.skip"]
    assert skips and {d["symbol"] for d in skips} == {PINNED}, "every pinned skip is audited"
    assert all(not e.startswith(f"drop:{PINNED}") for e in ladder.retention.log)


async def test_order_placed_at_96_percent_succeeds_with_native_sl(ladder: LadderRig) -> None:
    """BQ-4: the real submit pipeline (`tests/unit/oms/submit_rig.rigged`: the OMS's in-memory
    `FakeTradingPort` venue and in-memory stores, not `packages/fixtures` captures and not on the
    near-full volume; SCENARIOS.md "Deviations") while the recording volume is at 96 %: the order
    is accepted, its write-ahead audit record (C-2.9) and its row exist, and its create carries
    the native stop (C-2.6)."""
    await ladder.at(96)
    assert ladder.budget.halted
    async with rigged() as oms:
        outcome = await oms.submit()
        [call] = [c for c in oms.port.demo.calls if c.method == "place_order"]
        audits = oms.port.audits.actions()
        written = oms.port.audits.written
        orders = dict(oms.store._orders)
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    assert isinstance(call.request, PlaceOrderRequest)
    assert call.request.stop_loss == STOP, "INVARIANT: native stop-loss on the create (C-2.6)"
    # C-2.9: the intent and its stop are audited before the send (no exchange call before them)
    ahead = [(r.action, r.reason) for r, sent in written if sent == 0]
    assert ("orders.submit", "validated") in ahead and ("sl.attached", "entry_attach") in ahead
    intent = next(r for r, _ in written if (r.action, r.reason) == ("orders.submit", "validated"))
    assert isinstance(intent, RequestRecord) and intent.object_id == outcome.order_id
    assert audits[-1] == ("orders.submit", "submitted"), "and the outcome is audited after"
    assert outcome.order_id in orders, "the order row was persisted under pressure"


async def test_pinned_assertion_fails_when_pin_predicate_removed(
    ladder: LadderRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative control: with the reaper's pin predicate removed, the suite's own pinned-bytes
    assertion must fail. A pass here would mean that assertion proves nothing."""
    real = Reaper._blocker

    async def without_pins(self: Reaper, part: Partition, pinned: set[str]) -> tuple[Reason, str]:
        return await real(self, part, set())

    monkeypatch.setattr(Reaper, "_blocker", without_pins)
    await ladder.at(91)
    assert any(e.startswith(f"drop:{PINNED}") for e in ladder.retention.log)
    with pytest.raises(AssertionError, match="pinned bytes changed"):
        ladder.assert_pins_intact()
