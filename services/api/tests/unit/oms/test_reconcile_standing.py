"""The account's reconciliation standing, the failure tracker and B19's port into the pass (E29-T06
#914 PR 2a; 24-internal-schemas.md Sec.8.5 "The stale rule", Sec.8.10; BQ-4, BQ-5, BQ-10; C-2.6,
C-2.21). The ordering of the standing against B19 itself is `test_reconcile_job.py`'s."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal
from uuid import UUID

import pytest

import candleviewer
from candleviewer.domain.order_entry import OrderEntryGate, OrderEntryRefusal
from candleviewer.exchange.base.models import RateHeadroom
from candleviewer.oms.reconcile_report import STALE_NOTICE, Notice
from candleviewer.oms.reconcile_standing import (
    STALE_AFTER_S,
    STALE_DETAIL,
    FailureTracker,
    ReconcileStanding,
)
from candleviewer.statechart.bindings.b19_reconciliation import FetchFailed, window_elapsed
from tests.unit.oms.reconcile_rig import ACCOUNT, NOW_US, OTHER, SWEEP_ID, Job, position, row

PACKAGE = Path(candleviewer.__file__).resolve().parent
WINDOW_US = round(STALE_AFTER_S * 1_000_000)
OTHER_SWEEP = "00000000-0000-4000-8000-0000000000ff"


class _Open:
    """The maintenance check, open: the gate's first slot."""

    scope: ClassVar[Literal["global"]] = "global"

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        return None


# --- The standing ---------------------------------------------------------------------------------


def test_the_standing_refuses_a_stale_accounts_entry_with_account_stale() -> None:
    standing = ReconcileStanding()
    standing.mark_stale(ACCOUNT)
    assert standing.refusal(ACCOUNT) == OrderEntryRefusal("account_stale", STALE_DETAIL)
    assert standing.refusal(OTHER) is None
    assert (standing.is_stale(ACCOUNT), standing.stale_count) == (True, 1)


def test_the_standing_is_the_order_entry_gates_account_stale_check() -> None:
    standing = ReconcileStanding()
    gate = OrderEntryGate(_Open(), standing)
    assert gate.refusal(ACCOUNT) is None
    standing.mark_stale(ACCOUNT)
    refusal = gate.refusal(ACCOUNT)
    assert refusal is not None and refusal.reason == "account_stale"


def test_clearing_the_standing_reopens_entry_and_marking_it_twice_is_idempotent() -> None:
    standing = ReconcileStanding()
    standing.mark_stale(ACCOUNT)
    standing.mark_stale(ACCOUNT)
    standing.clear(ACCOUNT)
    assert (standing.refusal(ACCOUNT), standing.stale_count) == (None, 0)


@pytest.mark.parametrize(
    ("state", "stale"),
    [("stale_lockout", True), ("idle", False), ("divergent", False), ("backing_off", False)],
)
def test_the_standing_is_rebuilt_from_the_restored_state(state: str, stale: bool) -> None:
    standing = ReconcileStanding()
    standing.mark_stale(ACCOUNT)
    standing.restored(ACCOUNT, state)
    assert standing.is_stale(ACCOUNT) is stale


def test_protective_paths_never_consult_the_standing() -> None:
    """C-2.6, BQ-5: only the order-entry gate reads the standing; the stop writers, the cancel
    and close paths and the exits never name it. Its writers are the pass's own modules (the
    phases, and the driver, which rebuilds it from a restored job and refuses an account whose
    job did not open), and the composition hands the one standing on: `app.py` composes it into
    the gate and gives it to the runtime, which gives it to reconciliation's composition (PR 2b)."""
    naming = {
        path.relative_to(PACKAGE).as_posix()
        for path in sorted(PACKAGE.rglob("*.py"))
        if "ReconcileStanding" in path.read_text(encoding="utf-8")
    }
    assert naming == {
        "oms/reconcile_standing.py", "oms/reconcile_phases.py", "oms/reconcile_job.py",
        "oms_reconcile_wiring.py", "oms_wiring.py", "app.py",
    }  # fmt: skip


# --- The tracker (BQ-4) ---------------------------------------------------------------------------


def test_the_tracker_judges_the_window_with_b19s_own_rule() -> None:
    tracker = FailureTracker()
    first = tracker.failed(ACCOUNT, NOW_US)
    almost = tracker.failed(ACCOUNT, NOW_US + WINDOW_US - 1)
    spent = tracker.failed(ACCOUNT, NOW_US + WINDOW_US)
    assert (first.exhausted, almost.exhausted, spent.exhausted) == (False, False, True)
    assert spent.failing_since_us == NOW_US
    assert window_elapsed(NOW_US, NOW_US + WINDOW_US, WINDOW_US)
    tracker.reset(ACCOUNT)
    assert tracker.failing_since(ACCOUNT) is None
    assert (
        tracker.failed(ACCOUNT, NOW_US + 10 * WINDOW_US).failing_since_us == NOW_US + 10 * WINDOW_US
    )


@pytest.mark.parametrize("window", [0, -1, float("inf"), float("nan"), True])
def test_the_tracker_refuses_a_window_that_is_no_finite_positive_number(window: float) -> None:
    with pytest.raises(ValueError):
        FailureTracker(window_s=window)


def test_a_fetch_failure_carries_the_trackers_window_to_the_guard() -> None:
    failure = FetchFailed(
        "RateLimitError", failing_since_us=1, failed_at_us=1 + WINDOW_US, window_us=WINDOW_US
    )
    assert failure.exhausted and failure.kind == "RateLimitError"
    assert "RateLimitError" in str(failure)


# --- B19's port into the pass (`ReconcilePhases`) ------------------------------------------------


async def test_a_fetch_that_fails_inside_the_window_raises_an_unexhausted_failure() -> None:
    job = Job()
    job.world.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=0, wait_s=60))
    with pytest.raises(FetchFailed) as failed:
        await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    assert (failed.value.kind, failed.value.exhausted) == ("no_headroom", False)
    assert not job.standing.is_stale(ACCOUNT)


async def test_a_fetch_that_fails_past_the_window_sets_the_standing_before_it_raises() -> None:
    """C-2.21: the refusal is in force before B19 hears of the failure."""
    job = Job()
    job.world.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=0, wait_s=60))
    with pytest.raises(FetchFailed):
        await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    job.world.now_us += WINDOW_US
    with pytest.raises(FetchFailed) as failed:
        await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    assert failed.value.exhausted
    assert job.standing.refusal(ACCOUNT) is not None


async def test_the_jobs_own_fault_is_a_failed_fetch_never_an_endless_retry() -> None:
    """INV-B19-a: a store the job reads that fails, or a fault of its own, feeds the stale rule."""
    job = Job()
    job.watermarks.refuse_read = True
    with pytest.raises(FetchFailed) as failed:
        await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="startup")
    assert failed.value.kind == "ConnectionError"
    assert job.tracker.failing_since(ACCOUNT) == NOW_US


async def test_an_account_id_that_is_no_uuid_locks_at_once() -> None:
    job = Job()
    with pytest.raises(FetchFailed) as failed:
        await job.phases.fetch("not-an-account", pass_id=SWEEP_ID, trigger="startup")
    assert failed.value.exhausted


async def test_the_window_runs_from_the_older_mark_to_now() -> None:
    job = Job()
    job.marks.last = NOW_US - 40_000_000
    job.watermarks.stored = NOW_US - 30_000_000
    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    [executions] = [c.request for c in job.world.venue.calls if c.method == "executions"]
    assert executions == (NOW_US - 45_000_000, NOW_US)


async def _pass(job: Job, trigger: str = "periodic", *, episode: bool = False) -> dict[str, object]:
    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger=trigger)
    await job.phases.diff(str(ACCOUNT), pass_id=SWEEP_ID)
    await job.phases.remediate(str(ACCOUNT), pass_id=SWEEP_ID)
    return dict(
        await job.phases.report(
            str(ACCOUNT), pass_id=SWEEP_ID, trigger=trigger, episode_open=episode, failure=None
        )
    )


async def test_the_report_is_recorded_ahead_and_the_watermark_is_the_reads_upper_bound() -> None:
    job = Job()
    job.world.oms.seed(row(1))
    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    job.world.now_us += 7_000_000  # the pass runs on after its reads
    await job.phases.diff(str(ACCOUNT), pass_id=SWEEP_ID)
    await job.phases.remediate(str(ACCOUNT), pass_id=SWEEP_ID)
    summary = await job.phases.report(
        str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic", episode_open=False, failure=None
    )
    [(account, pass_id, state)] = job.records.rows
    assert (account, pass_id, state["stage"], state["newly_unknown"]) == (
        ACCOUNT, SWEEP_ID, "finished", [row(1).order_link_id],
    )  # fmt: skip
    assert state["duration_ms"] == 7000  # the report's instant, 7 s after the read's end
    assert job.watermarks.advanced == [NOW_US]  # the read's end, not the report's own instant
    assert summary == {
        "unresolved": 0, "outcome": "corrected",
        "notices": [["oms.account_desync", "warning"]], "episode_open": True,
    }  # fmt: skip


async def test_a_pass_with_an_error_holds_the_watermark() -> None:
    job = Job()
    job.world.oms.seed(row(1))
    job.world.oms.fail["command:RECON_MISS"] = TimeoutError()
    await _pass(job)
    assert job.watermarks.advanced == []


async def test_a_report_that_cannot_be_recorded_still_ends_its_pass_and_pages() -> None:
    job = Job()
    job.records.refuse = True
    summary = await _pass(job)
    assert summary["outcome"] == "clean"
    assert ("page", "A reconciliation report could not be written.") in job.world.oms.pages


async def test_a_report_that_cannot_be_recorded_holds_the_watermark_for_the_next_one() -> None:
    """C-2.9: each correction keeps its own record, but the pass's report is lost, so its window
    is not marked read: the next pass reads it again, and its report covers the slice."""
    job = Job()
    job.watermarks.stored = NOW_US - 30_000_000
    job.records.refuse = True
    await _pass(job)
    assert job.watermarks.advanced == []
    job.records.refuse = False
    job.world.now_us += 30_000_000
    await _pass(job)
    [(_, _, state)] = job.records.rows
    assert state["gap_window"] == [NOW_US - 35_000_000, NOW_US + 30_000_000]
    assert job.watermarks.advanced == [NOW_US + 30_000_000]


async def test_a_naked_position_with_no_record_reports_desync_critical_with_no_correction() -> None:
    job = Job()
    job.world.venue.seed_position(position(stop_loss=None))
    summary = await _pass(job)
    assert summary["notices"] == [["oms.account_desync", "critical"]]
    assert job.watermarks.advanced == [NOW_US]  # a standing item never holds it back


async def test_the_first_clean_pass_of_an_episode_is_synced() -> None:
    job = Job()
    summary = await _pass(job, episode=True)
    assert (summary["notices"], summary["episode_open"]) == (
        [["oms.account_synced", "info"]],
        False,
    )


async def test_a_pass_whose_reads_are_gone_reports_its_loss() -> None:
    job = Job()
    summary = await job.phases.report(
        str(ACCOUNT), pass_id=SWEEP_ID, trigger="startup", episode_open=False, failure=None
    )
    assert summary["outcome"] == "errored"
    assert job.records.rows[0][2]["errors"] == [{"step": "1", "kind": "pass_lost", "subject": None}]


async def test_a_diff_that_fails_as_a_whole_is_reported_with_its_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job()

    async def broken(*_a: object) -> None:
        raise KeyError("x")

    monkeypatch.setattr(job.world.reconciler, "diff", broken)
    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    with pytest.raises(KeyError):
        await job.phases.diff(str(ACCOUNT), pass_id=SWEEP_ID)
    await job.phases.report(
        str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic", episode_open=False, failure="KeyError"
    )
    assert job.records.rows[0][2]["errors"] == [{"step": "2", "kind": "KeyError", "subject": None}]


async def test_a_phase_of_another_pass_is_refused() -> None:
    job = Job()
    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    with pytest.raises(LookupError):
        await job.phases.diff(str(ACCOUNT), pass_id=OTHER_SWEEP)
    with pytest.raises(LookupError):
        await job.phases.remediate(str(ACCOUNT), pass_id=SWEEP_ID)  # no plan yet


def test_the_effects_lock_unlock_page_publish_and_count() -> None:
    job = Job()
    job.phases.lock(str(ACCOUNT), trigger="reconnect")
    assert job.standing.is_stale(ACCOUNT)
    job.phases.stale(str(ACCOUNT))
    assert job.notices.published == [(ACCOUNT, STALE_NOTICE)]
    job.phases.unlock(str(ACCOUNT))
    assert not job.standing.is_stale(ACCOUNT)
    job.phases.publish(str(ACCOUNT), [["oms.account_synced", "info"]])
    assert job.notices.published[-1] == (ACCOUNT, Notice("oms.account_synced", "info"))
    job.phases.schedule_retry(str(ACCOUNT), attempt=2)
    assert job.retries.asked == [2]
    job.phases.alert(str(ACCOUNT), reason="divergent", page=False)
    job.phases.fetch_failed(str(ACCOUNT), trigger="periodic")
    job.tracker.failed(ACCOUNT, NOW_US)
    job.phases.reset_failures(str(ACCOUNT))
    assert job.tracker.failing_since(ACCOUNT) is None
    assert [s for s, _ in job.world.oms.pages] == ["page", "alert"]
    with pytest.raises(ValueError):
        job.phases.publish(str(ACCOUNT), [["oms.account_resyncing", "warning"]])
