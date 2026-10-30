"""The reconciliation pass, branch by branch (E29-T06 #914 PR 2a; 24-internal-schemas.md Sec.8.5,
the ruling of record's BQ-12, BQ-15, BQ-17 and BQ-18): step 1's reads and their checks, the window,
and steps 2 to 3d, each on hand-built local and remote sets over `reconcile_rig`."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import RateLimitError
from candleviewer.exchange.base.models import RateHeadroom
from candleviewer.oms.reconcile_report import PassError
from candleviewer.oms.reconciler import (
    FIRST_WINDOW_US,
    FetchError,
    FoundCommand,
    FoundPush,
    found_sends,
    gap_window,
)
from tests.unit.oms.reconcile_rig import (
    ACCOUNT,
    LINK,
    NOW_US,
    OTHER,
    SWEEP_ID,
    T0,
    World,
    fill,
    position,
    record,
    remote,
    row,
    waiting,
)

PUSHES_AND_COMMANDS = ("push", "command", "discover", "materialise")


# --- Step 1 ---------------------------------------------------------------------------------------


async def test_fetch_reads_on_the_poll_lane_only() -> None:
    w = World()
    await w.run()
    assert w.calls() == [
        ("open_orders", "poll"),
        ("positions", "poll"),
        ("executions", "poll"),
    ]


async def test_fetch_with_no_headroom_fails_before_any_read() -> None:
    w = World()
    w.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=0, wait_s=60))
    with pytest.raises(FetchError) as failed:
        await w.run()
    assert (failed.value.kind, w.calls()) == ("no_headroom", [])


async def test_fetch_stops_at_the_first_rate_limit_answer() -> None:
    """C-12.7: the reads run one after another; the first rate-limit answer ends the fetch."""
    w = World()
    w.venue.script("positions", RateLimitError("rate limited"))
    with pytest.raises(FetchError) as failed:
        await w.run()
    assert failed.value.kind == "RateLimitError"
    assert [method for method, _lane in w.calls()] == ["open_orders", "positions"]


async def test_fetch_fails_on_a_row_of_another_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """BQ-12, C-2.11: the adapter drops another account's row (R12); one that reaches the pass all
    the same fails the fetch as a failed read does, logged by count, never applied."""
    w = World()

    async def foreign(*_a: object, **_k: object) -> list[object]:
        return [remote(account_id=OTHER)]

    monkeypatch.setattr(w.venue, "open_orders", foreign)
    with capture_logs() as logs, pytest.raises(FetchError) as failed:
        await w.run()
    assert failed.value.kind == "other_account"
    [entry] = [e for e in logs if e["event"] == "reconcile_rows_of_another_account"]
    assert (entry["log_level"], entry["rows"]) == ("critical", 1)
    assert w.oms.log == []


async def test_fetch_lists_an_unreadable_handover_by_its_id_as_a_standing_item() -> None:
    w = World()
    w.oms.unreadable = [7]
    report = await w.run()
    assert report.errors == (PassError("1", "handover_unreadable", "7"),)
    assert report.errors[0].standing


def test_gap_window_takes_the_older_mark_less_five_seconds() -> None:
    window = gap_window(last_message_us=900_000_000, last_reconciled_us=800_000_000, now_us=10**9)
    assert window == (795_000_000, 10**9)


def test_gap_window_first_pass_reads_one_seven_day_window_back() -> None:
    now = 30 * 86_400_000_000
    assert gap_window(last_message_us=None, last_reconciled_us=None, now_us=now) == (
        now - FIRST_WINDOW_US,
        now,
    )
    assert FIRST_WINDOW_US == 7 * 86_400_000_000


def test_gap_window_never_starts_after_its_end() -> None:
    assert gap_window(last_message_us=10**9, last_reconciled_us=None, now_us=10) == (10, 10)


# --- Step 2 ---------------------------------------------------------------------------------------


async def test_step2_fill_goes_to_the_row_bound_to_its_order_with_source_reconcile() -> None:
    w = World()
    w.oms.seed(row(1))
    w.venue.seed_execution(fill("e1"))
    report = await w.run()
    [(_, order_id, event, payload)] = w.oms.effects("push")
    assert (order_id, event, payload["exec_id"], payload["source"]) == (
        row(1).id,
        "EXEC",
        "e1",
        "reconcile",
    )
    assert payload["order_link_id"] == LINK.format(1)
    assert report.corrected == (LINK.format(1),)


async def test_step2_stored_fill_is_skipped_and_its_handover_pruned() -> None:
    w = World()
    w.oms.seed(row(1))
    w.oms.stored_ids = {"e1"}
    w.oms.handed_fills = [waiting(fill("e1"), entry_id=41)]
    w.venue.seed_execution(fill("e1"))
    report = await w.run()
    assert w.oms.effects("push") == []
    assert w.oms.effects("prune") == [("prune", (41,))]
    assert report.corrected == ()


async def test_step2_fill_never_pairs_by_its_link_id_alone() -> None:
    """Sec.8.3 rule 7: a fill under row 1's link id but of another exchange order never reaches
    row 1, which is bound to `x1`."""
    w = World()
    w.oms.seed(row(1))
    w.venue.seed_execution(fill("e9", n=9, order_link_id=LINK.format(1)))
    await w.run()
    assert [e for e in w.oms.effects("push") if e[1] == row(1).id] == []


async def test_step2_fill_of_no_order_is_stored_with_none() -> None:
    w = World()
    w.venue.seed_execution(fill("f1", exec_type="funding"))
    report = await w.run()
    assert w.oms.effects("insert", "push") == [("insert", "f1")]
    assert report.applied == 0


async def test_step2_fill_of_an_unknown_row_rides_its_finding() -> None:
    """INV-B1-e: an `unknown` row takes no EXEC; its fill goes with the finding that binds it."""
    w = World()
    w.oms.seed(row(1, "unknown", lifecycle_state="unknown", cum_exec_qty=Decimal(0)))
    w.venue.seed_order(remote(1, state="partially_filled", filled_qty=Decimal("0.4")), uid="1001")
    w.venue.seed_execution(fill("e1"))
    report = await w.run()
    [(_, _, event, payload, actor)] = w.oms.effects("command")
    assert (event, payload["execution"]["exec_id"], actor) == (
        "RECON_FOUND_PARTIAL",
        "e1",
        "system",
    )
    assert w.oms.effects("push") == []
    assert report.corrected == (LINK.format(1),)


# --- Step 3a --------------------------------------------------------------------------------------


async def test_3a_bound_live_row_takes_a_trigger_as_the_stream_sends_it() -> None:
    w = World()
    w.oms.seed(row(1))
    w.venue.seed_order(remote(1, state="triggered"), uid="1001")
    report = await w.run()
    [(_, order_id, event, payload)] = w.oms.effects("push")
    assert (order_id, event, payload["source"]) == (row(1).id, "TRIGGERED", "reconcile")
    assert report.corrected == (LINK.format(1),)


async def test_3a_bound_live_row_already_triggered_takes_nothing() -> None:
    w = World()
    w.oms.seed(row(1, "triggered"))
    w.venue.seed_order(remote(1, state="triggered"), uid="1001")
    report = await w.run()
    assert (w.oms.effects("push", "command"), report.applied) == ([], 0)


async def test_3a_unbound_unknown_row_binds_only_after_the_full_match() -> None:
    """INV-B19-c, SR-E29-03: the order under the row's link id is found (no resubmission) only
    when it is the row's, field for field."""
    w = World()
    w.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    w.venue.seed_order(remote(1), uid="1001")
    report = await w.run()
    [(_, order_id, event, payload, _)] = w.oms.effects("command")
    assert (order_id, event, payload) == (
        row(1).id,
        "RECON_FOUND_LIVE",
        {"exchange_order_id": "x1", "pass_id": SWEEP_ID},
    )
    assert [c for c, _ in w.calls() if c == "place_order"] == []
    assert report.corrected == (LINK.format(1),)


async def test_3a_mismatch_freezes_hands_over_holds_then_records_beside() -> None:
    """SR-E29-03: an order under the row's id that fails the full match opens the freeze first
    (SR-E27-19), is handed over before the hold, holds the row and is recorded beside it."""
    w = World()
    w.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    w.venue.seed_order(remote(1, qty=Decimal(2)), uid="1001")
    report = await w.run()
    kinds = [e[0] for e in w.oms.log if e[0] != "prune"]
    assert kinds == ["freeze", "hand_over_order", "command", "adopted", "discover"]
    assert w.oms.effects("command")[0][2] == "MISMATCH"
    assert w.oms.effects("discover")[0][1] == ext_key("x1")
    assert (report.held, report.untracked) == ((LINK.format(1),), (ext_key("x1"),))


def test_found_sends_partial_fills_then_end_after_them() -> None:
    """INV-B1-k: the finding carries the first fill, the rest follow as EXEC, the end last."""
    r = row(1, "unknown", lifecycle_state="unknown")
    order = remote(1, state="partially_filled_canceled", filled_qty=Decimal("0.8"))
    fills = [fill("e1", seq=1), fill("e2", seq=2)]
    sends = found_sends(r, order, fills, pass_id=SWEEP_ID, ts_event=NOW_US)
    assert sends is not None
    assert [(type(s), s.event) for s in sends] == [
        (FoundCommand, "RECON_FOUND_PARTIAL"),
        (FoundPush, "EXEC"),
        (FoundPush, "REMOTE_CANCELLED"),
    ]


def test_found_sends_adopts_no_totals_it_has_not_read() -> None:
    """OM-R02: the venue's totals are not the fills the pass read: no finding at all."""
    r = row(1, "unknown", lifecycle_state="unknown")
    order = remote(1, state="filled", filled_qty=Decimal(1))
    assert found_sends(r, order, [fill("e1")], pass_id=SWEEP_ID, ts_event=NOW_US) is None


def test_found_sends_one_completing_fill_is_found_filled() -> None:
    r = row(1, "quarantined", lifecycle_state="quarantined")
    order = remote(1, state="filled", filled_qty=Decimal("0.4"))
    sends = found_sends(r, order, [fill("e1")], pass_id=SWEEP_ID, ts_event=NOW_US)
    assert sends is not None and [s.event for s in sends] == ["RECON_FOUND_FILLED"]


def test_found_sends_untracked_is_recorded_by_the_orders_state() -> None:
    r = row(1, "untracked", lifecycle_state="untracked")
    live = found_sends(r, remote(1), [], pass_id=SWEEP_ID, ts_event=NOW_US)
    ended = found_sends(r, remote(1, state="cancelled"), [], pass_id=SWEEP_ID, ts_event=NOW_US)
    assert live is not None and ended is not None
    assert [s.event for s in (*live, *ended)] == ["RECON_FOUND_LIVE", "RECON_FOUND_CANCELLED"]


# --- Step 3b --------------------------------------------------------------------------------------


async def test_3b_live_row_found_nowhere_goes_unknown_missing_remote() -> None:
    """B1 v7, INV-B1-s: a settled live row the pass finds nowhere takes RECON_MISS into
    `unknown`, with no reject code."""
    w = World()
    w.oms.seed(row(1))
    report = await w.run()
    [(_, order_id, event, payload, actor)] = w.oms.effects("command")
    assert (order_id, event, payload, actor) == (
        row(1).id,
        "RECON_MISS",
        {"pass_id": SWEEP_ID},
        "system",
    )
    assert ("order_history", "poll") in w.calls()
    assert report.newly_unknown == (LINK.format(1),)


async def test_3b_unknown_row_found_nowhere_twice_is_abandoned_unresolved() -> None:
    """The two-miss counter (B1's `recon_misses`, fixed by the chart): the first miss keeps the
    row `unknown`, the second ends it `rejected`, abandoned."""
    w = World()
    w.oms.seed(row(1, "unknown", lifecycle_state="unknown"))
    first, second = await w.run(), await w.run()
    payloads = [e[3] for e in w.oms.effects("command")]
    assert payloads == [{"pass_id": SWEEP_ID, "reject_code": "UNRESOLVED_AFTER_RECONCILE"}] * 2
    assert (first.abandoned, second.abandoned) == ((), (LINK.format(1),))


async def test_3b_demo_unknown_past_six_days_carries_demo_retention_expired() -> None:
    w = World()
    w.oms.seed(
        row(1, "unknown", lifecycle_state="unknown", created_ts=T0 - timedelta(days=6, hours=1))
    )
    await w.run()
    [(_, _, _, payload, _)] = w.oms.effects("command")
    assert payload["reject_code"] == "DEMO_RETENTION_EXPIRED"


async def test_3b_live_unknown_past_24_hours_is_paged_once_and_held() -> None:
    """BQ-15: live history shows a cancelled or rejected order for 24 h only, so a miss proves
    nothing: no RECON_MISS, one P1 page across passes, the row kept `unknown`."""
    w = World(environment="live")
    w.oms.seed(row(1, "unknown", lifecycle_state="unknown", created_ts=T0 - timedelta(hours=25)))
    first, second = await w.run(), await w.run()
    assert w.oms.effects("command") == []
    assert [s for s, _ in w.oms.pages] == ["page"]
    assert first.abandoned == second.abandoned == ()


async def test_3b_live_unknown_within_24_hours_is_abandoned_after_two_misses() -> None:
    w = World(environment="live")
    w.oms.seed(row(1, "unknown", lifecycle_state="unknown", created_ts=T0 - timedelta(hours=23)))
    await w.run()
    second = await w.run()
    assert second.abandoned == (LINK.format(1),)


async def test_3b_untracked_row_found_nowhere_twice_closes_cancelled() -> None:
    w = World()
    w.oms.seed(row(1, "untracked", lifecycle_state="untracked", provenance="reconciliation"))
    first, second = await w.run(), await w.run()
    assert [e[3] for e in w.oms.effects("command")] == [{"pass_id": SWEEP_ID}] * 2
    assert (first.abandoned, second.abandoned, second.newly_unknown) == ((), (LINK.format(1),), ())


async def test_3b_bound_live_row_found_cancelled_in_history_ends_as_the_stream_ends_it() -> None:
    w = World()
    w.oms.seed(row(1))
    w.venue.seed_order(remote(1, state="cancelled", terminal_at=NOW_US - 1), uid="1001")
    report = await w.run()
    [(_, _, event, payload)] = w.oms.effects("push")
    assert (event, payload["source"], payload["order_link_id"]) == (
        "REMOTE_CANCELLED",
        "reconcile",
        LINK.format(1),
    )
    assert report.resolved_from_history == (LINK.format(1),)


@pytest.mark.parametrize(
    "state", ["held", "pending_cancel", "pending_amend", "submitted", "pending_submit"]
)
async def test_3b_rows_left_to_their_request_take_nothing(state: str) -> None:
    """Held waits for the operator; a create, a cancel and an amend in flight for their answer."""
    w = World()
    w.oms.seed(row(1, state))
    await w.run()
    assert w.oms.effects("command", "push") == []
    assert ("order_history", "poll") not in w.calls()


async def test_3b_a_rate_limit_answer_ends_the_passs_reads() -> None:
    """C-12.7: after the first rate-limit answer no further history is read; each row not read is
    listed, and steps 4 and 5 still run."""
    w = World()
    w.oms.seed(row(1), row(2))
    w.venue.script("order_history", RateLimitError("rate limited"))
    w.venue.seed_position(position(stop_loss=None))
    w.oms.records = [record()]
    report = await w.run()
    assert [m for m, _ in w.calls()].count("order_history") == 1
    assert [(e.step, e.kind) for e in report.errors] == [
        ("3b", "RateLimitError"),
        ("3b", "rate_limited"),
    ]
    assert report.sl_repaired == ("BTCUSDT",)


# --- Step 3c --------------------------------------------------------------------------------------


async def test_3c_foreign_order_is_adopted_untracked_audited_ahead() -> None:
    """BQ-17, D6: adopted automatically, frozen first (SR-E27-19), audited
    `order.adopted_untracked` with the venue's identity before its row; never managed."""
    w = World()
    foreign = remote(7, order_link_id=ext_key("x7"))
    w.venue.seed_order(foreign, uid="1001")
    report = await w.run()
    assert [e[0] for e in w.oms.log] == ["freeze", "adopted", "discover"]
    assert w.oms.effects("discover") == [("discover", ext_key("x7"), "x7", SWEEP_ID)]
    assert w.oms.effects("command", "push") == []
    assert report.untracked == (ext_key("x7"),)


async def test_3c_exchange_placed_order_is_audited_never_frozen() -> None:
    w = World()
    w.venue.seed_order(remote(7, order_link_id=ext_key("x7"), exchange_placed=True), uid="1001")
    await w.run()
    assert [e[0] for e in w.oms.log] == ["exchange_placed", "adopted", "discover"]


async def test_3c_open_order_bound_to_a_final_row_is_an_anomaly_with_no_mutation() -> None:
    w = World()
    w.oms.seed(row(1, "cancelled"))
    w.venue.seed_order(remote(1), uid="1001")
    report = await w.run()
    assert w.oms.effects(*PUSHES_AND_COMMANDS, "freeze") == []
    assert report.anomalies == (LINK.format(1),)
    assert [s for s, _ in w.oms.pages] == ["alert"]


async def test_3c_id_another_accounts_row_holds_is_an_anomaly_and_frozen() -> None:
    w = World()
    w.oms.taken_elsewhere = {LINK.format(7)}
    w.venue.seed_order(remote(7), uid="1001")
    report = await w.run()
    assert [e[0] for e in w.oms.log] == ["freeze"]
    assert report.anomalies == (LINK.format(7),)


async def test_3c_order_whose_exchange_id_a_row_holds_already_is_an_anomaly() -> None:
    """24 Sec.8.5: `adopt_untracked` never merges silently; the facade's deterministic refusal
    (`ux_orders_exch_id`) is an anomaly, and one order never ends the pass."""
    w = World()
    w.oms.refuse_discover = True
    w.venue.seed_order(remote(7, order_link_id=ext_key("x7")), uid="1001")
    report = await w.run()
    assert (report.untracked, report.anomalies) == ((), (ext_key("x7"),))


async def test_3c_recorded_stops_order_is_materialised_not_adopted() -> None:
    """Sec.8.3 rule 7: a TP/SL order that matches what the OMS recorded is OMS intent: its row is
    materialised and bound to the record, never recorded untracked or frozen."""
    w = World()
    w.oms.records = [
        record(
            status="pending",
            answered_at=None,
            in_force_at=None,
            created_at=T0 - timedelta(minutes=1),
        )
    ]
    stop = remote(
        7, order_link_id=ext_key("x7"), order_kind="stop_loss", side="sell",
        order_type="market", price=None, trigger_price=Decimal(62000), qty=Decimal("0.2"),
        stop_loss=None, created_at=NOW_US - 1_000,
    )  # fmt: skip
    w.venue.seed_order(stop, uid="1001")
    report = await w.run()
    [(_, link, xid, binds)] = w.oms.effects("materialise")
    assert (link, xid, binds.record_id) == (ext_key("x7"), "x7", record().id)
    assert w.oms.effects("freeze", "discover") == []
    assert report.untracked == report.foreign_stops == ()


async def test_3c_order_of_a_row_still_sending_is_left_to_its_send() -> None:
    w = World()
    w.oms.seed(row(1, "submitted", exchange_order_id=None))
    w.venue.seed_order(remote(1), uid="1001")
    await w.run()
    assert w.oms.effects(*PUSHES_AND_COMMANDS, "freeze") == []


# --- Step 3d --------------------------------------------------------------------------------------


async def test_3d_fill_of_an_order_adopted_this_pass_is_kept_for_its_finding() -> None:
    """An `untracked` row records an `EXEC` and applies nothing, so the fill of an order this pass
    adopted is kept, and the next pass's finding carries it to the row, which it closes."""
    w = World()
    w.venue.seed_order(remote(7, order_link_id=ext_key("x7")), uid="1001")
    e7 = fill("e7", n=7, order_link_id=ext_key("x7"))
    w.venue.seed_execution(e7)
    first = await w.run()
    assert [e[0] for e in w.oms.log] == ["freeze", "adopted", "discover", "hand_over_execution"]
    assert (w.oms.effects("push"), first.corrected) == ([], ())
    w.venue._open.pop("x7")  # the order filled since; the hand-over holds its fill
    filled = remote(7, order_link_id=ext_key("x7"), state="filled", filled_qty=Decimal("0.4"))
    w.venue.seed_order(filled, uid="1001")
    w.oms.handed_fills = [waiting(e7, entry_id=51)]
    w.now_us += 60_000_000  # the fill is outside this pass's window: only the hand-over has it
    second = await w.run()
    [(_, _, event, payload, _)] = w.oms.effects("command")
    assert (event, payload["execution"]["exec_id"]) == ("RECON_FOUND_FILLED", "e7")
    assert (second.resolved_from_history, second.errors) == ((ext_key("x7"),), ())
    assert w.oms.effects("prune") == [("prune", (51,))]


async def test_3d_fill_named_by_an_unbound_live_row_waits_in_its_buffer() -> None:
    w = World()
    w.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    w.venue.seed_execution(fill("e9", n=9, order_link_id=LINK.format(1)))  # names row 1
    await w.run()
    pushed = [(e[1], e[2]) for e in w.oms.effects("push")]
    assert pushed == [(row(1).id, "EXEC")]  # held by the facade until row 1's bind decides


async def test_3d_failed_order_read_keeps_the_fill_for_the_next_pass() -> None:
    w = World()
    w.venue.seed_execution(fill("e9", n=9, order_link_id=ext_key("x9")))
    w.venue.script("order_history", RateLimitError("rate limited"))
    report = await w.run()
    assert w.oms.effects("hand_over_execution") == [("hand_over_execution", "e9", False)]
    assert report.errors == (PassError("3d", "RateLimitError", "e9"),)


async def test_3d_first_empty_read_keeps_the_fill_counting_it() -> None:
    w = World()
    w.venue.seed_execution(fill("e9", n=9, order_link_id=ext_key("x9")))
    report = await w.run()
    assert w.oms.effects("hand_over_execution") == [("hand_over_execution", "e9", True)]
    assert (report.unpaired, report.errors) == ((), ())


async def test_3d_an_empty_read_a_cadence_later_decides_the_fill_unpaired_and_frozen() -> None:
    w = World()
    e = fill("e9", n=9, order_link_id=ext_key("x9"))
    w.oms.handed_fills = [waiting(e, empty_reads=1, first_empty_read_at=T0 - timedelta(seconds=31))]
    report = await w.run()
    assert [x[0] for x in w.oms.log] == ["freeze", "hand_over_execution", "decide"]
    assert w.oms.effects("freeze") == [("freeze", "execution", "e9")]
    assert report.unpaired == ("e9",)


async def test_3d_an_empty_read_inside_the_cadence_decides_nothing() -> None:
    w = World()
    e = fill("e9", n=9, order_link_id=ext_key("x9"))
    w.oms.handed_fills = [waiting(e, empty_reads=1, first_empty_read_at=T0 - timedelta(seconds=10))]
    report = await w.run()
    assert w.oms.effects("freeze", "decide") == []
    assert report.unpaired == ()


async def test_3d_a_decided_fill_is_listed_again_without_a_read() -> None:
    w = World()
    e = fill("e9", n=9, order_link_id=ext_key("x9"))
    w.oms.handed_fills = [waiting(e, decided=True)]
    report = await w.run()
    assert ("order_history", "poll") not in w.calls()
    assert (report.unpaired, w.oms.effects("freeze")) == (("e9",), [])
