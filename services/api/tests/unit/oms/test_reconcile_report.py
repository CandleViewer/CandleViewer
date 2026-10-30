"""The pass's report, its notices, its watermark and its metrics (E29-T06 #914 PR 2a; 24 Sec.8.5
"The report" and `gap_from`, 23 Sec.15.9, 20 Sec.12.1; BQ-6, BQ-9, BQ-10, BQ-11)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import generate_latest

from candleviewer.observability.metrics import Metrics
from candleviewer.oms.reconcile_report import (
    EMPTY_TEXT,
    HANDOVER_UNREADABLE,
    NO_RECORD_IN_FORCE,
    OWNER_FIELDS,
    REPEATING_FIELDS,
    STALE_NOTICE,
    STANDING_ITEMS,
    Notice,
    PassError,
    PositionDrift,
    ReconcileMetrics,
    ReconcileReport,
    ReportDraft,
    audit_state,
    pass_notices,
    watermark_us,
)
from tests.unit.oms.reconcile_rig import ACCOUNT, SWEEP_ID

WINDOW = (1_000, 9_000)


def report(**over: Any) -> ReconcileReport:
    values: dict[str, Any] = {
        "account_id": ACCOUNT, "pass_id": SWEEP_ID, "trigger": "periodic", "gap_window": WINDOW,
    }  # fmt: skip
    return ReconcileReport(**(values | over))


# --- The standing items and the watermark (BQ-10; the security delta's L4) ----------------------


def test_the_standing_items_are_a_closed_list_of_two() -> None:
    assert STANDING_ITEMS == {NO_RECORD_IN_FORCE, HANDOVER_UNREADABLE}
    assert (NO_RECORD_IN_FORCE, HANDOVER_UNREADABLE) == (
        "no_record_in_force",
        "handover_unreadable",
    )


def test_the_watermark_is_the_upper_bound_step1_read_to_never_the_reports_instant() -> None:
    """`last_reconciled_at` stores the window's end, so a slow pass leaves no unread slice."""
    done = report(duration_ms=60_000)
    assert watermark_us(done) == WINDOW[1]


@pytest.mark.parametrize("kind", sorted(STANDING_ITEMS))
def test_a_standing_item_never_holds_the_watermark(kind: str) -> None:
    assert watermark_us(report(errors=(PassError("5", kind, "BTCUSDT"),))) == WINDOW[1]


def test_any_other_error_holds_the_watermark() -> None:
    errors = (PassError("1", HANDOVER_UNREADABLE, "4"), PassError("3b", "TimeoutError", "l1"))
    assert watermark_us(report(errors=errors)) is None


# --- The notices (BQ-6, BQ-9; 23 Sec.15.9) --------------------------------------------------------


def test_desync_is_sent_once_for_a_pass_that_applied_corrections_never_per_row() -> None:
    out = pass_notices(report(corrected=("l1", "l2"), newly_unknown=("l3",)), episode_open=False)
    assert (out.notices, out.episode_open) == ((Notice("oms.account_desync", "warning"),), True)


def test_desync_is_critical_for_a_pass_that_found_a_naked_position_with_no_record() -> None:
    naked = (PassError("5", NO_RECORD_IN_FORCE, "BTCUSDT"),)
    out = pass_notices(report(corrected=("l1",), errors=naked), episode_open=False)
    assert out.notices == (Notice("oms.account_desync", "critical"),)


def test_a_pass_whose_only_finding_is_a_naked_position_sends_desync_critical_never_clean() -> None:
    """BQ-9 and BQ-6 (#5056's fold r3): no correction was applied, yet the desync row goes out at
    critical, and such a pass is not clean, so it never sends `oms.account_synced`."""
    only = report(errors=(PassError("5", NO_RECORD_IN_FORCE, "BTCUSDT"),))
    assert (only.applied, only.clean) == (0, False)
    for episode in (False, True):
        out = pass_notices(only, episode_open=episode)
        assert (out.notices, out.episode_open) == (
            (Notice("oms.account_desync", "critical"),),
            True,
        )


def test_synced_is_sent_once_on_the_first_clean_pass_of_an_episode() -> None:
    first = pass_notices(report(), episode_open=True)
    second = pass_notices(report(), episode_open=first.episode_open)
    assert (first.notices, first.episode_open) == ((Notice("oms.account_synced", "info"),), False)
    assert (second.notices, second.episode_open) == ((), False)


@pytest.mark.parametrize("field", [*OWNER_FIELDS, "errors"])
def test_a_pass_that_left_something_is_not_clean_and_sends_no_synced(field: str) -> None:
    value: object = (PassError("3b", "TimeoutError"),) if field == "errors" else ("x",)
    left = report(**{field: value})
    assert not left.clean
    out = pass_notices(left, episode_open=True)
    assert Notice("oms.account_synced", "info") not in out.notices and out.episode_open


def test_the_stale_notice_is_critical() -> None:
    assert STALE_NOTICE == Notice("oms.account_stale", "critical")


# --- The report and its record --------------------------------------------------------------------


def test_result_ranks_owner_items_then_errors_then_corrections() -> None:
    assert report().result == "clean"
    assert report(corrected=("l1",)).result == "corrected"
    assert report(corrected=("l1",), errors=(PassError("2", "X"),)).result == "errored"
    assert report(anomalies=("l9",), errors=(PassError("2", "X"),)).result == "divergent"


def test_the_record_holds_every_field_ids_and_both_drift_values() -> None:
    drift = PositionDrift("BTCUSDT", 0, "buy", Decimal("0.2"), "buy", Decimal("0.10"))
    state = audit_state(
        report(position_drift=(drift,), errors=(PassError("5", NO_RECORD_IN_FORCE, "BTCUSDT"),))
    )
    assert state["stage"] == "finished" and state["gap_window"] == list(WINDOW)
    assert state["position_drift"] == [{
        "symbol": "BTCUSDT", "position_idx": 0, "side_before": "buy", "qty_before": "0.2",
        "side_after": "buy", "qty_after": "0.1",
    }]  # fmt: skip
    assert state["errors"] == [{"step": "5", "kind": NO_RECORD_IN_FORCE, "subject": "BTCUSDT"}]
    names = {
        "corrected", "resolved_from_history", "abandoned", "newly_unknown", "untracked",
        "anomalies", "held", "foreign_stops", "unpaired", "position_drift", "sl_repaired",
        "sl_restored", "sl_restore_refused", "sl_tighter",
    }  # fmt: skip
    assert names | {"pass_id", "trigger", "duration_ms", "gap_window", "errors"} <= set(state)


def test_the_draft_freezes_into_the_report() -> None:
    draft = ReportDraft(ACCOUNT, SWEEP_ID, "manual", WINDOW)
    draft.corrected.append("l1")
    draft.error("3a", "fills_unread", "l2")
    done = draft.freeze(12)
    assert (done.corrected, done.errors, done.duration_ms) == (
        ("l1",), (PassError("3a", "fills_unread", "l2"),), 12,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("step", "kind", "subject"),
    [("9", "X", None), ("2", "", None), ("2", "X", ""), ("2", "X", "s" * 65)],
)
def test_an_error_names_a_step_a_short_kind_and_an_id_never_a_payload(
    step: str, kind: str, subject: str | None
) -> None:
    with pytest.raises(ValueError):
        PassError(step, kind, subject)  # type: ignore[arg-type]  # the bad step is the point


def test_the_draft_lists_what_a_failure_handler_names_and_never_raises() -> None:
    """BQ-18: the phases list errors inside their failure handlers, so the draft cuts a kind or
    a subject past the cap to it and names an empty one, where `PassError` refuses both."""
    draft = ReportDraft(ACCOUNT, SWEEP_ID, "periodic", WINDOW)
    draft.error("2", "K" * 65, "s" * 65)
    draft.error("3a", "", "")
    draft.error("5", "AttributeError")
    assert draft.errors == [
        PassError("2", "K" * 64, "s" * 64),
        PassError("3a", EMPTY_TEXT, EMPTY_TEXT),
        PassError("5", "AttributeError"),
    ]


def test_a_report_refuses_an_unknown_trigger_and_a_reversed_window() -> None:
    with pytest.raises(ValueError):
        report(trigger="hourly")
    with pytest.raises(ValueError):
        report(gap_window=(9, 1))


# --- The metrics (BQ-11) --------------------------------------------------------------------------


def _value(metrics: Metrics, name: str, **labels: str) -> float:
    lines = generate_latest(metrics.registry).decode().splitlines()
    wanted = [f'{k}="{v}"' for k, v in labels.items()]
    return sum(
        float(line.rsplit(" ", 1)[1])
        for line in lines
        if line.split("{")[0] == name and all(w in line for w in wanted)
    )


def test_the_metrics_count_by_trigger_result_and_kind_with_no_account_label() -> None:
    metrics = Metrics("dev")
    m = ReconcileMetrics(metrics)
    m.observe(report(duration_ms=1500, corrected=("l1", "l2"), sl_repaired=("BTCUSDT",)))
    m.ended("reconnect", "failed")
    m.ended("reconnect", "stale")
    m.naked()
    assert (
        _value(metrics, "oms_reconcile_passes_total", trigger="periodic", result="corrected") == 1
    )
    assert _value(metrics, "oms_reconcile_passes_total", trigger="reconnect", result="stale") == 1
    assert _value(metrics, "oms_reconcile_corrections_total", kind="corrected") == 2
    assert _value(metrics, "oms_reconcile_seconds_count", trigger="periodic") == 1
    assert _value(metrics, "naked_position_alerts_total") == 1
    exposition = generate_latest(metrics.registry).decode()
    assert "account" not in {
        label.split("=")[0]
        for line in exposition.splitlines()
        if line.startswith("oms_reconcile")
        for label in line.partition("{")[2].rstrip("}0123456789. ").split(",")
        if label
    }


def test_the_untracked_gauge_sums_each_accounts_last_count() -> None:
    metrics = Metrics("dev")
    m = ReconcileMetrics(metrics)
    m.untracked(ACCOUNT, 2)
    m.untracked(ACCOUNT.__class__(int=0xB2), 3)
    m.untracked(ACCOUNT, 1)
    assert _value(metrics, "oms_untracked_orders") == 4


# --- The contract lines this change carries (24 Sec.8.5, 23 Sec.15.9; #5056's lenses) -----------

PLAN = Path(__file__).resolve().parents[5] / "docs" / "plan"


def _section(doc: str, start: str, end: str) -> str:
    text = (PLAN / doc).read_text(encoding="utf-8")
    return text[text.index(start) : text.index(end)]


def test_24_names_the_standing_items_closed_list_and_the_watermarks_upper_bound() -> None:
    """The watermark test's pins: the closed list the code holds, and the bound it stores."""
    section = _section("24-internal-schemas.md", "### 8.5 Reconciliation", "### 8.6 ")
    assert (
        "The standing items are a closed list of two, `no_record_in_force` (a naked position with "
        "no record in force, BQ-9) and `handover_unreadable`"
    ) in section
    assert sorted(STANDING_ITEMS) == ["handover_unreadable", "no_record_in_force"]
    assert (
        "as the upper bound step 1's execution read covered (the window's end), never the "
        "report's own instant, so a slow pass leaves no unread slice"
    ) in section


def test_24_repeats_errors_back_to_back_as_the_code_does() -> None:
    section = _section("24-internal-schemas.md", "### 8.5 Reconciliation", "### 8.6 ")
    assert (
        "except for `anomalies`, `unpaired`, `sl_tighter`, `sl_restore_refused` and `errors`"
    ) in section
    assert REPEATING_FIELDS == (
        "anomalies",
        "unpaired",
        "sl_tighter",
        "sl_restore_refused",
        "errors",
    )


def test_24_skips_and_logs_a_trigger_that_finds_the_job_locked() -> None:
    """No series counts a skipped trigger, so 24 says it is logged."""
    section = _section("24-internal-schemas.md", "### 8.5 Reconciliation", "### 8.6 ")
    assert "**While B19 is `stale_lockout`.** Only `RECONNECTED`" in section
    assert (
        "A trigger that finds the job locked is therefore skipped and logged, never sent" in section
    )


def test_24_lists_the_missed_fills_steps_2_and_3d_apply_as_corrections() -> None:
    """The `corrected` row names what the code lists there (`test_reconciler.py`'s step 2 pin):
    a missed fill sent to an order is a correction (BQ-6, 23 Sec.15.9)."""
    section = _section("24-internal-schemas.md", "### 8.5 Reconciliation", "### 8.6 ")
    [row] = [line for line in section.splitlines() if line.startswith("| `corrected` ")]
    assert (
        "Rows a 3a finding or fact moved, and rows steps 2 and 3d applied a missed fill to: a "
        "step sent to an order is a correction (BQ-6, 23 §15.9)"
    ) in row


def test_24_step_5_cites_bq_9_for_the_entry_it_does_not_hold() -> None:
    section = _section("24-internal-schemas.md", "### 8.5 Reconciliation", "### 8.6 ")
    assert "#   entry is not held for it (BQ-9)" in section and "(D4)" not in section


def test_23_sends_desync_critical_for_a_pass_whose_only_finding_is_a_naked_position() -> None:
    section = _section("23-ws-protocol.md", "When E29-T06's rows fire", "### 15.10")
    assert (
        "A pass whose only finding is such a position sends it at `critical` too, though it "
        "applied no correction (BQ-9 and BQ-6)."
    ) in section
    assert "so a pass that found such a naked position is never clean." in section
