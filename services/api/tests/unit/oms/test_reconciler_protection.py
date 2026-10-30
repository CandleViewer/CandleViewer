"""The reconciliation pass's positions and stops (E29-T06 #914 PR 2a; 24-internal-schemas.md Sec.8.5
steps 4 and 5, Sec.8.8 rules 4 and 6; BQ-9, BQ-18; C-2.6), its containment of one failure, and the
back-to-back rule. Every test that meets an open position checks the native-stop invariant
(`assert_protected`): the pass sends no order of its own, and every naked position it saw is either
attached from its record or paged with none."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.oms.reconcile_report import REPEATING_FIELDS, PassError
from candleviewer.oms.reconciler import PositionDriftSeen
from tests.unit.oms.reconcile_rig import LINK, T0, World, position, record, remote, row

#: The only venue calls a pass makes: its reads. Stop writes go through the recorded-stop writer.
_READS = {"open_orders", "positions", "executions", "order_history"}


def assert_protected(
    w: World, *, attached: frozenset[str] = frozenset(), paged: frozenset[str] = frozenset()
) -> None:
    """C-2.6: the pass placed, amended and cancelled nothing at the venue, and every naked position
    it read is one it attached from its record or paged with none."""
    assert {method for method, _ in w.calls()} <= _READS
    assert {e[1] for e in w.oms.effects("attach_recorded")} == attached
    naked = {p.symbol for p in w.venue._positions if p.qty > 0 and p.stop_loss is None}
    assert naked == attached | paged


async def test_step4_exchange_truth_wins_and_both_values_are_kept() -> None:
    w = World()
    w.oms.held = {("BTCUSDT", 0): PositionDriftSeen("buy", Decimal("0.2"))}
    w.venue.seed_position(position(qty=Decimal("0.1")))
    report = await w.run()
    assert w.oms.effects("apply_position") == [("apply_position", "BTCUSDT", 0, Decimal("0.1"))]
    [drift] = report.position_drift
    assert (drift.qty_before, drift.qty_after, drift.side_before, drift.side_after) == (
        Decimal("0.2"), Decimal("0.1"), "buy", "buy",
    )  # fmt: skip
    assert report.corrections()["position_drift"] == 1
    assert ("page", "Reconciliation corrected a position the OMS held otherwise.") in w.oms.pages
    assert_protected(w)


async def test_step4_a_position_the_oms_holds_alike_is_left_alone() -> None:
    w = World()
    w.oms.held = {("BTCUSDT", 0): PositionDriftSeen("buy", Decimal("0.2"))}
    w.venue.seed_position(position())
    report = await w.run()
    assert (w.oms.effects("apply_position"), report.applied) == ([], 0)


async def test_step5_naked_position_with_a_record_gets_it_attached_and_counted() -> None:
    """BQ-9: the record in force attached through the recorded-stop writer, counted in
    `naked_position_alerts_total`, the repair listed."""
    w = World()
    w.oms.records = [record()]
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert w.oms.effects("attach_recorded") == [
        ("attach_recorded", "BTCUSDT", Decimal(62000), "00000000-0000-4000-8000-0000000000a1")
    ]
    assert (report.sl_repaired, w.naked) == (("BTCUSDT",), 1)
    assert_protected(w, attached=frozenset({"BTCUSDT"}))


async def test_step5_naked_position_with_no_record_is_paged_once_listed_and_left() -> None:
    """BQ-9: no record in force: a P1 page once across passes, listed in `errors` (a standing
    item), no attach (E32-T02's), and order entry is not held for it."""
    w = World()
    w.venue.seed_position(position(stop_loss=None))
    first, second = await w.run(), await w.run()
    assert first.errors == second.errors == (PassError("5", "no_record_in_force", "BTCUSDT"),)
    assert [s for s, _ in w.oms.pages] == ["page"]
    assert first.naked_without_record and not first.clean
    assert_protected(w, paged=frozenset({"BTCUSDT"}))


async def test_step5_an_attach_the_venue_refuses_is_listed_and_paged() -> None:
    w = World()
    w.oms.records = [record()]
    w.oms.stop_writes["attach"] = "refused"
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert (report.sl_repaired, report.errors) == (
        (),
        (PassError("5", "attach_refused", "BTCUSDT"),),
    )
    assert [s for s, _ in w.oms.pages] == ["page"]


async def test_step5_a_looser_full_mode_stop_is_put_back() -> None:
    w = World()
    w.oms.records = [record()]
    w.venue.seed_position(position(stop_loss=Decimal(61000)))  # lower for a long: looser
    report = await w.run()
    assert [e[0] for e in w.oms.effects("restore_recorded")] == ["restore_recorded"]
    assert report.sl_restored == ("BTCUSDT",)


async def test_step5_a_refused_restore_pages_once_and_repeats_its_listing() -> None:
    w = World()
    w.oms.records = [record()]
    w.oms.stop_writes["restore"] = "refused"
    w.venue.seed_position(position(stop_loss=Decimal(61000)))
    first, second = await w.run(), await w.run()
    assert first.sl_restore_refused == second.sl_restore_refused == ("BTCUSDT",)
    assert [s for s, _ in w.oms.pages] == ["page"]


async def test_step5_a_restore_no_longer_looser_on_its_reread_is_nothing() -> None:
    w = World()
    w.oms.records = [record()]
    w.oms.stop_writes["restore"] = "not_looser"
    w.venue.seed_position(position(stop_loss=Decimal(61000)))
    report = await w.run()
    assert (report.sl_restored, report.sl_restore_refused, report.errors) == ((), (), ())


async def test_step5_a_tighter_stop_stays_and_pages_once_per_value() -> None:
    w = World()
    w.oms.records = [record()]
    w.venue.seed_position(position(stop_loss=Decimal(62500)))  # higher for a long: tighter
    first = await w.run()
    second = await w.run()
    w.venue.seed_position(position(stop_loss=Decimal(62600)))
    await w.run()
    assert first.sl_tighter == second.sl_tighter == ("BTCUSDT",)
    assert w.oms.effects("restore_recorded", "attach_recorded") == []
    assert [s for s, _ in w.oms.pages] == ["page", "page"]


async def test_step5_a_recorded_trail_the_position_still_reports_is_left_alone() -> None:
    w = World()
    w.oms.records = [record(trailing_distance=Decimal(500), trailing_active_price=Decimal(63000))]
    w.venue.seed_position(position(stop_loss=Decimal(62800), trailing_stop_distance=Decimal(500)))
    report = await w.run()
    assert (report.sl_tighter, report.sl_restored) == ((), ())


async def test_step5_a_key_with_a_stop_request_in_flight_is_left_to_it() -> None:
    w = World()
    in_flight = record(id=record().id.__class__(int=0x5702), status="pending", answered_at=None,
                       in_force_at=None, created_at=T0)  # fmt: skip
    w.oms.records = [record(), in_flight]
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert (w.oms.effects("attach_recorded"), report.errors) == ([], ())


async def test_step5_a_stop_order_open_for_the_position_is_not_naked() -> None:
    w = World()
    w.oms.records = [record(tpsl_mode="Partial", size=Decimal("0.2"))]
    partial = remote(5, order_kind="partial_stop_loss", side="sell", order_type="market",
                     price=None, trigger_price=Decimal(62000), qty=Decimal("0.2"))  # fmt: skip
    w.oms.seed(row(5, provenance="recorded_stop", side="Sell", qty=Decimal("0.2")))
    w.venue.seed_order(partial, uid="1001")
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert (w.oms.effects("attach_recorded"), report.errors) == ([], ())


async def test_step5_a_pending_record_the_read_shows_in_force_counts_as_in_force() -> None:
    w = World()
    shown = record(status="pending", in_force_at=None)  # answered, its stop shown by the read
    w.oms.records = [shown]
    w.venue.seed_position(position(stop_loss=Decimal(61000)))
    report = await w.run()
    assert report.sl_restored == ()  # shown at 61000, not its 62000: not in force, nothing tested
    w.venue.seed_position(position(stop_loss=Decimal(62000)))
    assert (await w.run()).applied == 0


# --- Containment (BQ-18) and step 5 whatever came before it (C-2.6) -----------------------------


async def test_step5_runs_when_the_order_store_cannot_be_read() -> None:
    w = World()
    w.oms.records = [record()]
    w.oms.fail["unfinished_for"] = ConnectionError("down")
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert report.errors[0] == PassError("2", "ConnectionError")
    assert report.sl_repaired == ("BTCUSDT",)
    assert_protected(w, attached=frozenset({"BTCUSDT"}))


async def test_step5_runs_when_the_position_store_cannot_be_read() -> None:
    w = World()
    w.oms.records = [record()]
    w.oms.fail["held"] = ConnectionError("down")
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert report.errors[0] == PassError("4", "ConnectionError")
    assert report.sl_repaired == ("BTCUSDT",)


async def test_one_rows_failure_never_ends_the_pass_and_step5_still_runs() -> None:
    """BQ-18: an action that fails is listed with its step and class; every later one runs."""
    w = World()
    w.oms.records = [record()]
    w.oms.seed(row(1), row(2))
    w.oms.fail["command:RECON_MISS"] = TimeoutError()
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert report.errors == (PassError("3b", "TimeoutError", LINK.format(1)),)
    assert report.newly_unknown == (LINK.format(2),)
    assert report.sl_repaired == ("BTCUSDT",)


async def test_a_freeze_that_fails_pages_and_ends_neither_the_action_nor_the_pass() -> None:
    w = World()
    w.oms.fail["open"] = ConnectionError("down")
    w.venue.seed_order(remote(7, order_link_id="ext-" + "7" * 32), uid="1001")
    report = await w.run()
    assert report.untracked == ("ext-" + "7" * 32,)
    assert PassError("3c", "freeze_failed", "x7") in report.errors
    assert (
        "page",
        "Reconciliation could not freeze an account for a finding with no intent.",
    ) in w.oms.pages


async def test_an_adoption_whose_record_cannot_be_written_is_not_inserted() -> None:
    """C-2.9: the record is written ahead; without it no row is inserted and the next pass
    tries again."""
    w = World()
    w.oms.fail["adopted"] = ConnectionError("down")
    w.venue.seed_order(remote(7, order_link_id="ext-" + "7" * 32), uid="1001")
    report = await w.run()
    assert w.oms.effects("discover") == []
    assert (report.untracked, report.errors) == ((), (PassError("3c", "ConnectionError", "x7"),))


# --- Back to back (24 Sec.8.5) ------------------------------------------------------------------


async def test_a_second_pass_back_to_back_reports_only_the_repeating_fields() -> None:
    """24 Sec.8.5: run twice back to back, the second report is empty but for `anomalies`,
    `unpaired`, `sl_tighter`, `sl_restore_refused` and `errors`."""
    w = World()
    w.oms.records = [record()]
    w.oms.seed(row(1), row(3, "cancelled"))
    w.venue.seed_order(remote(3), uid="1001")  # bound to a final row: an anomaly
    w.venue.seed_order(remote(1, state="triggered"), uid="1001")
    w.venue.seed_position(position(stop_loss=Decimal(62500)))  # tighter: stays
    first = await w.run()
    w.oms.seed(row(1, "triggered"))  # what the first pass's push did
    second = await w.run()
    assert first.corrected == (LINK.format(1),)
    corrections = (
        "corrected", "resolved_from_history", "abandoned", "newly_unknown", "untracked", "held",
        "foreign_stops", "position_drift", "sl_repaired", "sl_restored",
    )  # fmt: skip
    for name in corrections:
        assert getattr(second, name) == (), name
    assert (second.anomalies, second.sl_tighter) == ((LINK.format(3),), ("BTCUSDT",))
    assert set(REPEATING_FIELDS) == {
        "anomalies",
        "unpaired",
        "sl_tighter",
        "sl_restore_refused",
        "errors",
    }


@pytest.mark.parametrize("hours", [1, 30])
async def test_the_report_names_ids_and_symbols_never_a_value(hours: int) -> None:
    w = World()
    w.oms.records = [record()]
    w.venue.seed_position(position(stop_loss=None, updated_at=w.now_us - hours * 3_600_000_000))
    report = await w.run()
    text = repr(report.errors) + repr(report.sl_repaired)
    assert "62000" not in text and "0.2" not in text
