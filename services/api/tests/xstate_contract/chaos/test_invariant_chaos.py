"""Every §Bn.7 invariant has a chaos case (E50-Q01, 29 §1.7).

The ledger is generated from `28-statechart-catalogue.md`: each `INV-Bn-*`
row is mapped to one fault family (kill/restart, clock skew via
`SimulatedClock`, inbox overflow, restore mid-invoke) and run against its
committed chart in both §1.7 service spellings. Binding bodies are stubs
until their owning epics land, so each case asserts the runtime half of the
invariant: the machine survives the fault with a sound configuration, no
fault latch, nothing silently dropped, and journal replay exactly once.

Invariants whose chart is not yet committed are collected the moment the
chart lands — the pending list is asserted, so it cannot grow silently
(B1 `order` and B8 `position_protection` landed in #1650).
"""

from __future__ import annotations

import pytest
from xstate_statemachine import QueueOverflowError

from candleviewer.statechart.config import CV_INBOX_BOUND
from candleviewer.statechart.persistence import split_sealed_drain
from tests.xstate_contract._harness import (
    SPELLINGS,
    Charts,
    Spelling,
    instrument,
    lane_of,
    stable_states,
)
from tests.xstate_contract.chaos._chaos import (
    FAMILIES,
    REG,
    assert_sound,
    catalogue_rows,
    chart_for_number,
    family_for,
    flood,
    invoke_states,
    kill,
    probe_event,
    restart,
    skew,
    start,
)

#: Charts still owned by an unlanded epic (no committed machine JSON yet).
PENDING_CHARTS: dict[int, str] = {}

ROWS = catalogue_rows()
LEDGER = [
    (inv, machine, family_for(text, machine))
    for inv, n, text in ROWS
    if (machine := chart_for_number(n)) is not None
]
#: Distinct `(machine, family)` cases: invariants sharing a machine and a
#: family share one run (keeps the contract suite inside its 60 s budget).
CASES = sorted({(m, f) for _i, m, f in LEDGER})
#: One hour of virtual time: past every coarse timer the charts declare.
_SKEW_MS = 3_600_000.0


def test_ledger_covers_every_catalogue_invariant() -> None:
    covered = {inv for inv, _m, _f in LEDGER}
    pending = {inv for inv, n, _t in ROWS if n in PENDING_CHARTS}
    assert covered | pending == {inv for inv, _n, _t in ROWS}
    assert covered.isdisjoint(pending)
    landed = "a pending chart has landed: drop it from PENDING_CHARTS"
    assert all(chart_for_number(n) is None for n in PENDING_CHARTS), landed
    assert len(covered) == len(LEDGER) >= 80
    assert {f for _i, _m, f in LEDGER} <= set(FAMILIES)
    assert set(FAMILIES) == {f for _i, _m, f in LEDGER}, "every family is exercised"
    assert {(m, f) for _i, m, f in LEDGER} == set(CASES)


_PENDING_ROWS = [(inv, n) for inv, n, _t in ROWS if n in PENDING_CHARTS]


@pytest.mark.parametrize(("inv", "number"), _PENDING_ROWS, ids=[i for i, _n in _PENDING_ROWS])
def test_pending_chart_invariant_is_tracked(inv: str, number: int) -> None:
    """Each invariant of an unlanded chart is a visible skip, never silent.

    The owning epic's ticket must add the chart; the ledger test then fails
    until that chart's invariants are run here (no waiver is implied).
    """
    pytest.skip(f"{inv}: chart B{number} not committed yet; owned by {PENDING_CHARTS[number]}")


async def _kill_restart(machine: str, charts: Charts) -> None:
    live = await start(machine, stable_states(REG.get(machine))[0], charts)

    live.interp.send(probe_event(machine))  # in the inbox at the moment of death
    env = await kill(live)
    assert [e.event_type for e in live.journal.rows(live.key)] == [probe_event(machine)]
    back = await restart(live, env)
    try:
        assert_sound(machine, back.interp)
        drain, _ = split_sealed_drain(env.snapshot)
        assert (await back.journal.replay_once(back.key, back.interp, drain)).replayed == 0
        assert back.pager.pages == [] and back.audit.quarantined == []
    finally:
        await back.interp.stop()


async def _clock_skew(machine: str, charts: Charts) -> None:
    for source in stable_states(REG.get(machine)):
        live = await start(machine, source, charts)
        try:
            await skew(live, _SKEW_MS)
            assert_sound(machine, live.interp)
            with pytest.raises(ValueError, match="backwards"):
                live.clock.set(0.0)  # skew never rewinds virtual time
            assert_sound(machine, live.interp)
        finally:
            await live.interp.stop()


async def _inbox_overflow(machine: str, charts: Charts) -> None:
    live = await start(machine, stable_states(REG.get(machine))[0], charts)
    try:
        accepted, refused = flood(live)
        assert refused, f"{machine}: overflow past the lane bound was not refused"
        assert accepted == CV_INBOX_BOUND[lane_of(machine)]
        with pytest.raises(QueueOverflowError):
            live.interp.send(probe_event(machine))  # still refused, not dropped
        await _drain()
        assert_sound(machine, live.interp)
        live.interp.send(probe_event(machine))  # accepts again once drained
        await _drain()
        assert_sound(machine, live.interp)
    finally:
        await live.interp.stop()


async def _drain() -> None:
    from tests.xstate_contract._harness import settle

    for _ in range(8):
        await settle()


async def _restore_mid_invoke(machine: str, charts: Charts) -> None:
    for source in invoke_states(machine):
        live = await start(machine, source, charts)
        before = set(live.interp.current_state_ids)
        env = await kill(live)  # the invoked service is still pending
        back = await restart(live, env)
        try:
            assert_sound(machine, back.interp)
            assert set(back.interp.current_state_ids) == before
            assert back.pager.pages == [] and not back.latch.is_latched(back.key)
            await back.interp.send(probe_event(machine), wait=True)
            assert_sound(machine, back.interp)
        finally:
            await back.interp.stop()


_RUN = {
    "kill_restart": _kill_restart,
    "clock_skew": _clock_skew,
    "inbox_overflow": _inbox_overflow,
    "restore_mid_invoke": _restore_mid_invoke,
}


@pytest.mark.parametrize("spelling", SPELLINGS)
@pytest.mark.parametrize(("machine", "family"), CASES, ids=[f"{m}:{f}" for m, f in CASES])
async def test_invariants_survive_chaos(
    machine: str,
    family: str,
    spelling: Spelling,
    charts: Charts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers every ledger invariant mapped to `(machine, family)`."""
    instrument(machine, monkeypatch, spelling)
    await _RUN[family](machine, charts)
