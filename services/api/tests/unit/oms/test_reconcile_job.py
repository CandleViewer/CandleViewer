"""B19 with its real bindings over the pass (E29-T06 #914 PR 2a; 28 §B19, 24-internal-schemas.md
Sec.8.5 "The stale rule"; BQ-4, BQ-5, BQ-13; C-2.21). The standing is set before B19 is told, it
clears only after B19 records `OPERATOR_RESOLVED`, neither a good pass nor a reconnect clears it,
and a restart rebuilds it from the restored state: shown on the library, one interpreter per
account, built through `cv.statechart.factory` only."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.models import RateHeadroom
from candleviewer.oms.reconcile_report import STALE_NOTICE, Notice
from candleviewer.oms.reconcile_standing import STALE_AFTER_S, ReconcileStanding
from candleviewer.statechart.bindings import b19_reconciliation as b19
from tests.unit.oms.reconcile_rig import (
    ACCOUNT,
    SWEEP_ID,
    Job,
    leaf,
    position,
    remote,
    rest,
    row,
    started,
)

WINDOW_US = round(STALE_AFTER_S * 1_000_000)
_HYP = settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@pytest.fixture
def job() -> Iterator[Job]:
    wired = Job()
    b19.set_ports(wired.phases)
    yield wired
    b19.set_ports(None)


def _starve(job: Job, starved: bool = True) -> None:
    """The poll lane with no headroom: every fetch fails, nothing read (C-12.7)."""
    tokens, wait = (0.0, 60.0) if starved else (100.0, 0.0)
    job.world.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=tokens, wait_s=wait))


async def _locked(job: Job) -> Any:
    interp = await started()
    _starve(job)
    await interp.send("STARTUP")
    assert await rest(interp) == "backing_off"
    job.world.now_us += WINDOW_US
    await interp.send("RETRY_DUE")
    assert await rest(interp) == "stale_lockout"
    return interp


async def test_a_clean_startup_pass_is_reported_and_rests_idle(job: Job) -> None:
    interp = await started()
    try:
        await interp.send("STARTUP", pass_id=SWEEP_ID)
        assert await rest(interp) == "idle"
        [(_, pass_id, state)] = job.records.rows
        assert (pass_id, state["trigger"], state["result"]) == (SWEEP_ID, "startup", "clean")
        assert interp.context["pass_id"] == SWEEP_ID
    finally:
        await interp.stop()


async def test_a_pass_that_leaves_an_owner_item_rests_divergent_until_resolved(job: Job) -> None:
    job.world.oms.seed(row(3, "cancelled"))
    job.world.venue.seed_order(remote(3), uid="1001")  # bound to a final row: an anomaly
    interp = await started()
    try:
        await interp.send("SWEEP_DUE", trigger="manual")
        assert await rest(interp) == "divergent"
        await interp.send("SWEEP_DUE", trigger="reconnect")  # divergent takes every trigger so
        assert await rest(interp) == "divergent"
        assert [r[2]["trigger"] for r in job.records.rows] == ["manual", "reconnect"]
        await interp.send("OPERATOR_RESOLVED")
        assert await rest(interp) == "idle"
    finally:
        await interp.stop()


async def test_the_standing_is_set_before_b19_is_told(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.21: when B19 evaluates the failure that locks it, the refusal is in force already."""
    seen: list[tuple[bool, bool]] = []
    real = b19.GUARDS["failures_exhausted"]

    def spy(context: Any, event: Any) -> bool:
        verdict = real(context, event)
        seen.append((verdict, job.standing.is_stale(ACCOUNT)))
        return verdict

    monkeypatch.setitem(b19.GUARDS, "failures_exhausted", spy)
    interp = await _locked(job)
    try:
        assert seen == [(False, False), (True, True)]
        assert job.notices.published == [(ACCOUNT, STALE_NOTICE)]
        assert job.retries.asked == [1]
        assert job.standing.refusal(ACCOUNT) is not None
    finally:
        await interp.stop()


async def test_the_standing_clears_only_after_b19_records_the_unlock(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    during: list[tuple[bool, bool]] = []
    real = b19.ACTIONS["audit_operator_resolved"]

    async def spy(*args: Any) -> None:
        before = job.standing.is_stale(ACCOUNT)
        await real(*args)  # B19's record of the decision
        during.append((before, job.standing.is_stale(ACCOUNT)))

    monkeypatch.setitem(b19.ACTIONS, "audit_operator_resolved", spy)
    interp = await _locked(job)
    try:
        await interp.send("OPERATOR_RESOLVED", decided_by="owner")
        assert await rest(interp) == "idle"
        assert during == [
            (True, True)
        ]  # set through the record, cleared only by the unlock after it
        assert not job.standing.is_stale(ACCOUNT)
    finally:
        await interp.stop()


async def test_a_reconnect_or_a_sweep_never_clears_a_stale_account(job: Job) -> None:
    interp = await _locked(job)
    try:
        _starve(job, starved=False)  # the venue answers again: still no pass runs, no unlock
        await interp.send("RECONNECTED")
        await interp.send("SWEEP_DUE")
        assert await rest(interp) == "stale_lockout"
        assert job.standing.is_stale(ACCOUNT)
        assert len(job.notices.published) == 1  # paged and handed on once per episode
    finally:
        await interp.stop()


async def test_the_first_clean_pass_after_a_stale_episode_is_synced_once(job: Job) -> None:
    interp = await _locked(job)
    try:
        _starve(job, starved=False)
        await interp.send("OPERATOR_RESOLVED")
        assert await rest(interp) == "idle"
        for _ in range(2):
            await interp.send("SWEEP_DUE")
            assert await rest(interp) == "idle"
        assert [n for _, n in job.notices.published] == [
            STALE_NOTICE,
            Notice("oms.account_synced", "info"),
        ]
    finally:
        await interp.stop()


async def test_a_naked_position_with_no_record_hands_on_desync_critical_every_pass(
    job: Job,
) -> None:
    """BQ-9 and BQ-6: a pass whose only finding is the standing naked position."""
    job.world.venue.seed_position(position(stop_loss=None))
    interp = await started()
    try:
        for _ in range(2):
            await interp.send("SWEEP_DUE")
            assert await rest(interp) == "idle"
        assert [n for _, n in job.notices.published] == [
            Notice("oms.account_desync", "critical")
        ] * 2
        assert job.standing.refusal(ACCOUNT) is None  # order entry is not held for it (BQ-9)
    finally:
        await interp.stop()


_STEPS = st.lists(
    st.sampled_from(["fail", "answer", "advance", "resolve", "reconnect", "sweep", "retry"]),
    max_size=10,
)


@_HYP
@given(steps=_STEPS)
async def test_the_standing_follows_b19_whatever_the_run(steps: list[str]) -> None:
    """For any run of failures, answers, clock moves and Owner decisions: the standing is set
    exactly while B19 is locked, and every lock B19 evaluated found it set already."""
    wired = Job()
    b19.set_ports(wired.phases)
    told: list[bool] = []
    real = b19.GUARDS["failures_exhausted"]

    def spy(context: Any, event: Any) -> bool:
        verdict = real(context, event)
        if verdict:
            told.append(wired.standing.is_stale(ACCOUNT))
        return verdict

    b19.GUARDS["failures_exhausted"] = spy
    interp = await started()
    try:
        for step in steps:
            if step in ("fail", "answer"):
                _starve(wired, starved=step == "fail")
            elif step == "advance":
                wired.world.now_us += WINDOW_US // 2
            else:
                event = {"resolve": "OPERATOR_RESOLVED", "reconnect": "RECONNECTED"}.get(step)
                await interp.send(event or ("RETRY_DUE" if step == "retry" else "SWEEP_DUE"))
            state = await rest(interp)
            assert wired.standing.is_stale(ACCOUNT) is (state == "stale_lockout"), (steps, state)
        assert all(told)
    finally:
        b19.GUARDS["failures_exhausted"] = real
        await interp.stop()
        b19.set_ports(None)


async def test_a_new_standing_starts_clear_so_a_restart_must_rebuild_it(job: Job) -> None:
    """A static restore runs no entry action, so nothing sets a new process's standing but its
    rebuild from the restored state (the round trip itself: `test_b19_reconciliation.py`)."""
    interp = await _locked(job)
    try:
        fresh = ReconcileStanding()
        assert not fresh.is_stale(ACCOUNT)
        fresh.restored(ACCOUNT, leaf(interp))
        assert fresh.is_stale(ACCOUNT)
    finally:
        await interp.stop()
