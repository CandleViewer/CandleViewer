"""The reconciliation pass's edges (E29-T06 #914 PR 2a; 24-internal-schemas.md Sec.8.5, BQ-12,
BQ-18): the whole-pass call, every read's account check, the history lookups' cache and refusals,
the 3b and 3c branches a unit elsewhere does not reach, and each action's failure listed by its
step."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_link import ext_key
from candleviewer.oms import reconciler as rc
from candleviewer.oms.errors import OrderStepRefused, ReconcileAnomaly
from candleviewer.oms.fakes import InMemoryTradingAccounts
from candleviewer.oms.handovers import WaitingOrder
from candleviewer.oms.reconcile_phases import ReconcilePhases
from candleviewer.oms.reconcile_report import PassError, watermark_us
from candleviewer.oms.reconciler import FetchError, PositionDriftSeen, Reconciler, found_sends
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.bindings import b19_reconciliation as b19
from tests.unit.oms.reconcile_rig import (
    ACCOUNT,
    LINK,
    NOW_US,
    OTHER,
    SWEEP_ID,
    FakeOms,
    Job,
    World,
    fill,
    position,
    record,
    ref,
    remote,
    row,
    waiting,
)

#: The page a row of another account raises (BQ-12, C-2.11).
_ANOTHER_PAGE = ("page", "Reconciliation read a row of another account.")


async def test_the_whole_pass_runs_its_phases_and_reports() -> None:
    w = World()
    w.oms.seed(row(1))
    report = await w.reconciler.reconcile(
        ACCOUNT, NOW_US - 60_000_000, pass_id=SWEEP_ID, trigger="manual"
    )
    assert (report.trigger, report.newly_unknown, report.gap_window) == (
        "manual", (LINK.format(1),), (NOW_US - 60_000_000, NOW_US),
    )  # fmt: skip


async def test_an_account_resolved_to_another_fails_the_fetch() -> None:
    w = World()
    accounts = InMemoryTradingAccounts()
    accounts.seed(ref(OTHER), as_id=ACCOUNT)
    w.reconciler._p = replace(w.reconciler._p, accounts=accounts)
    with pytest.raises(FetchError) as failed:
        await w.run()
    assert failed.value.kind == "other_account"


@pytest.mark.parametrize(
    ("read", "asked"),
    [
        ("unfinished_for", None),
        ("get_by_exchange_order_id", "x5"),
        ("get_by_link_id", LINK.format(5)),
    ],
)
async def test_a_store_answering_another_accounts_row_plans_nothing_from_it(
    read: str, asked: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-12.4: a row of another account from any order read is refused, never paired, and logged
    by the read and the id it asked for, never the row (C-12.6)."""
    w = World()
    foreign = row(5, exchange_account_id=OTHER)

    async def answers(*_a: Any) -> Any:
        return (foreign,) if read == "unfinished_for" else foreign

    monkeypatch.setattr(w.oms, read, answers)
    w.venue.seed_order(remote(5), uid="1001")
    w.venue.seed_execution(fill("e5", n=5))
    with capture_logs() as logs:
        report = await w.run()
    assert w.oms.effects("push", "command", "discover") == []
    assert any(e.kind == "_AnotherAccount" for e in report.errors)
    met = [e for e in logs if e["event"] == "reconcile_row_of_another_account"]
    assert {(e["log_level"], e["read"], e["subject"]) for e in met} == {("critical", read, asked)}
    assert w.oms.pages == [_ANOTHER_PAGE]  # paged once (C-2.11), however many reads met it


async def test_a_row_of_another_account_the_diff_meets_pages_once_per_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BQ-12, C-2.11: a store that answers another account's row to the diff's reads, pass after
    pass, pages once while the mix-up lasts; an order diff that meets none ends the episode, so
    the next one pages again."""
    w = World()
    real = w.oms.get_by_exchange_order_id

    async def foreign(*_a: Any) -> Any:
        return row(5, exchange_account_id=OTHER)

    w.venue.seed_execution(fill("e5", n=5))
    monkeypatch.setattr(w.oms, "get_by_exchange_order_id", foreign)
    first, second = await w.run(), await w.run()
    assert first.errors == second.errors == (PassError("2", "_AnotherAccount", "e5"),)
    assert w.oms.pages == [_ANOTHER_PAGE]
    monkeypatch.setattr(w.oms, "get_by_exchange_order_id", real)
    await w.run()  # met none: the episode is over
    monkeypatch.setattr(w.oms, "get_by_exchange_order_id", foreign)
    await w.run()
    assert w.oms.pages == [_ANOTHER_PAGE, _ANOTHER_PAGE]


async def test_a_history_read_answering_another_accounts_order_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = World()
    w.oms.seed(row(1))

    async def foreign(*_a: Any, **_k: Any) -> list[Any]:
        return [remote(1, account_id=OTHER, state="cancelled")]

    monkeypatch.setattr(w.venue, "order_history", foreign)
    with capture_logs() as logs:
        report = await w.run()
    assert (w.oms.effects("command", "push"), report.errors) == (
        [], (PassError("3b", "_AnotherAccount", LINK.format(1)),),
    )  # fmt: skip
    [met] = [e for e in logs if e["event"] == "reconcile_row_of_another_account"]
    assert (met["read"], met["subject"], w.oms.pages) == ("order_history", "x1", [_ANOTHER_PAGE])


async def test_two_orders_under_one_link_id_decide_nothing() -> None:
    w = World()
    w.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    for xid in ("xa", "xb"):
        w.venue.seed_order(remote(1, exchange_order_id=xid, state="cancelled"), uid="1001")
    report = await w.run()
    assert report.errors == (PassError("3b", "ambiguous", LINK.format(1)),)


async def test_an_unbound_row_with_no_id_of_ours_is_never_looked_up_by_it() -> None:
    w = World()
    w.oms.seed(
        row(
            1,
            "unknown",
            exchange_order_id=None,
            order_link_id=ext_key("x1"),
            lifecycle_state="unknown",
        )
    )
    report = await w.run()
    assert ("order_history", "poll") not in w.calls()
    assert report.errors == (PassError("3b", "unreadable_id", ext_key("x1")),)


async def test_a_failed_read_is_never_made_twice_in_one_pass() -> None:
    w = World()
    w.venue.script("order_history", ConnectionError("down"))
    for i, seq in ((1, 1), (2, 2)):
        w.venue.seed_execution(fill(f"e{i}", n=9, seq=seq, order_link_id=ext_key("x9")))
    report = await w.run()
    assert [m for m, _ in w.calls()].count("order_history") == 1
    assert [e.kind for e in report.errors] == ["ConnectionError", "ConnectionError"]
    assert [e[2] for e in w.oms.effects("hand_over_execution")] == [False, False]


async def test_3b_an_unbound_row_found_in_history_binds_after_the_full_match() -> None:
    w = World()
    w.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    w.venue.seed_order(remote(1, state="cancelled"), uid="1001")
    report = await w.run()
    [(_, _, event, payload, _)] = w.oms.effects("command")
    assert (event, payload["exchange_order_id"]) == ("RECON_FOUND_CANCELLED", "x1")
    assert report.resolved_from_history == (LINK.format(1),)


async def test_3b_an_unbound_rows_history_order_that_fails_the_match_is_held() -> None:
    w = World()
    w.oms.seed(row(1, "quarantined", exchange_order_id=None, lifecycle_state="quarantined"))
    w.venue.seed_order(remote(1, state="cancelled", price=Decimal(1)), uid="1001")
    report = await w.run()
    assert [e[0] for e in w.oms.log if e[0] != "prune"] == [
        "freeze", "hand_over_order", "command", "adopted", "discover",
    ]  # fmt: skip
    assert report.held == (LINK.format(1),)


async def test_3a_an_unknown_rows_partial_fills_ride_its_finding_then_follow_as_exec() -> None:
    w = World()
    w.oms.seed(row(1, "unknown", lifecycle_state="unknown"))
    w.venue.seed_order(remote(1, state="partially_filled", filled_qty=Decimal("0.8")), uid="1001")
    w.venue.seed_execution(fill("e1", seq=1))
    w.venue.seed_execution(fill("e2", seq=2))
    await w.run()
    sent = [(e[0], e[2]) for e in w.oms.effects("command", "push")]
    assert sent == [("command", "RECON_FOUND_PARTIAL"), ("push", "EXEC")]


async def test_3a_an_unknown_row_whose_totals_were_not_read_is_listed_not_found() -> None:
    w = World()
    w.oms.seed(row(1, "unknown", lifecycle_state="unknown"))
    w.venue.seed_order(remote(1, state="partially_filled", filled_qty=Decimal("0.8")), uid="1001")
    report = await w.run()
    assert report.errors == (PassError("3a", "fills_unread", LINK.format(1)),)
    assert w.oms.effects("command") == []


async def test_3c_a_handed_over_order_its_row_holds_is_pruned() -> None:
    w = World()
    w.oms.seed(row(1, "cancelled"))
    w.oms.handed_orders = [WaitingOrder(12, remote(1, state="cancelled"))]
    await w.run()
    assert w.oms.effects("prune") == [("prune", (12,))]


async def test_3c_a_handed_over_order_adopted_is_pruned() -> None:
    w = World()
    w.oms.handed_orders = [WaitingOrder(13, remote(7, order_link_id=ext_key("x7")))]
    report = await w.run()
    assert (report.untracked, w.oms.effects("prune")) == ((ext_key("x7"),), [("prune", (13,))])


async def test_3c_an_order_under_a_held_or_bound_rows_id_is_recorded_beside_it() -> None:
    w = World()
    w.oms.seed(row(1, "held", exchange_order_id=None))
    w.venue.seed_order(remote(1, exchange_order_id="x8"), uid="1001")
    report = await w.run()
    assert report.untracked == (ext_key("x8"),)


async def test_3c_a_handed_over_order_planned_this_pass_is_left_to_its_plan() -> None:
    w = World()
    w.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    w.venue.seed_order(remote(1, qty=Decimal(2)), uid="1001")  # a mismatch: recorded beside
    w.oms.handed_orders = [WaitingOrder(14, remote(1, qty=Decimal(2)))]
    await w.run()
    assert len(w.oms.effects("discover")) == 1


async def test_3c_an_order_with_no_quantity_is_an_anomaly_never_a_row() -> None:
    w = World()
    w.venue.seed_order(
        remote(7, order_link_id=ext_key("x7"), qty=Decimal(0), leaves_qty=Decimal(0)), uid="1001"
    )
    report = await w.run()
    assert (w.oms.effects("discover", "adopted"), report.anomalies) == ([], (ext_key("x7"),))


async def test_3c_a_refusal_that_may_pass_later_is_an_error_not_an_anomaly() -> None:
    w = World()
    w.oms.fail["discover"] = OrderStepRefused("DISCOVERED", "StorageTierUnavailable")
    w.venue.seed_order(remote(7, order_link_id=ext_key("x7")), uid="1001")
    report = await w.run()
    assert (report.anomalies, report.errors) == ((), (PassError("3c", "OrderStepRefused", "x7"),))


def _stop_order(n: int, **over: Any) -> Any:
    values: dict[str, Any] = {
        "order_link_id": ext_key(f"x{n}"), "order_kind": "stop_loss", "side": "sell",
        "order_type": "market", "price": None, "trigger_price": Decimal(62000),
        "qty": Decimal("0.2"), "stop_loss": None, "created_at": NOW_US - 1_000,
    }  # fmt: skip
    return remote(n, **(values | over))


def _pending_record() -> Any:
    return record(
        status="pending", answered_at=None, in_force_at=None, created_at=record().created_at
    )


async def test_3d_a_fill_of_a_recorded_stops_order_materialises_its_row_then_applies() -> None:
    w = World()
    w.oms.records = [_pending_record()]
    w.venue.seed_order(_stop_order(7, state="filled", filled_qty=Decimal("0.2")), uid="1001")
    w.venue.seed_execution(
        fill("e7", n=7, side="sell", qty=Decimal("0.2"), order_link_id=ext_key("x7"))
    )
    report = await w.run()
    assert [e[0] for e in w.oms.log if e[0] in ("materialise", "push")] == ["materialise", "push"]
    assert report.corrected and w.oms.effects("freeze") == []


async def test_3d_a_fill_of_a_stop_3c_materialises_goes_to_its_row_once_it_exists() -> None:
    """A late fill (3d) of an order 3c binds this pass: read again once the row exists, a
    recorded stop's row takes it as an `EXEC`, as the stream sends it."""
    w = World()
    w.oms.records = [_pending_record()]
    w.venue.seed_order(_stop_order(7), uid="1001")
    w.venue.seed_execution(
        fill("e7", n=7, side="sell", qty=Decimal("0.2"), order_link_id=ext_key("x7"))
    )
    report = await w.run()
    assert [e[0] for e in w.oms.log if e[0] in ("materialise", "push")] == ["materialise", "push"]
    assert (w.oms.effects("push")[0][2], report.corrected) == ("EXEC", (ext_key("x7"),))


async def _reread_meets_another(w: World, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """The pass planned, then applied with the store answering the re-read of a fill's row (3d)
    with a row of another account (BQ-12, C-2.11): the report, and the critical log it met."""
    plan = await w.plan()

    async def foreign(*_a: Any) -> Any:
        return row(7, exchange_account_id=OTHER)

    monkeypatch.setattr(w.oms, "get_by_exchange_order_id", foreign)
    with capture_logs() as logs:
        await w.reconciler.remediate(plan)
    [met] = [e for e in logs if e["event"] == "reconcile_row_of_another_account"]
    return w.reconciler.finish(plan), met


def _refused_as_the_diff_refuses(w: World, report: Any, met: Any) -> None:
    """Logged by the read and the id asked for, never the row; paged once; listed against the
    fill, which holds the watermark; and the fill kept for the next pass, never applied."""
    assert report.errors == (PassError("3d", "_AnotherAccount", "e7"),)
    assert watermark_us(report) is None
    assert (met["log_level"], met["read"], met["subject"]) == (
        "critical", "get_by_exchange_order_id", "x7",
    )  # fmt: skip
    assert w.oms.pages == [_ANOTHER_PAGE]
    assert (w.oms.effects("push"), w.oms.effects("hand_over_execution")) == (
        [], [("hand_over_execution", "e7", False)],
    )  # fmt: skip


async def test_3d_a_late_fills_reread_answering_another_accounts_row_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fill of an order 3c records this pass is read again once the row exists (`LateFill`)."""
    w = World()
    w.venue.seed_order(remote(7, order_link_id=ext_key("x7")), uid="1001")
    w.venue.seed_execution(fill("e7", n=7, order_link_id=ext_key("x7")))
    report, met = await _reread_meets_another(w, monkeypatch)
    assert report.untracked == (ext_key("x7"),)
    _refused_as_the_diff_refuses(w, report, met)


async def test_3d_a_materialised_stops_fill_reread_answering_another_accounts_row_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recorded stop's order 3d materialises is read again for the fill that showed it."""
    w = World()
    w.oms.records = [_pending_record()]
    w.venue.seed_order(_stop_order(7, state="filled", filled_qty=Decimal("0.2")), uid="1001")
    w.venue.seed_execution(
        fill("e7", n=7, side="sell", qty=Decimal("0.2"), order_link_id=ext_key("x7"))
    )
    report, met = await _reread_meets_another(w, monkeypatch)
    assert [e[2] for e in w.oms.effects("materialise")] == ["x7"]
    _refused_as_the_diff_refuses(w, report, met)


class _KeepingStore(FakeOms):
    """The hand-over store as `oms_handovers` keeps it (21 Sec.3.3.12): a fill handed over again
    under an `exec_id` it holds changes nothing, and a prune deletes exactly the entries named."""

    async def prune(self, account_id: Any, entry_ids: Any) -> int:
        self.handed_fills = [e for e in self.handed_fills if e.entry_id not in entry_ids]
        return await super().prune(account_id, entry_ids)


async def _materialised_from_the_store(failure: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    """3d materialises a recorded stop's filled order for a fill only the hand-over store holds
    (entry 41, beside entry 42, another fill the pass stores); the remediation then meets
    `failure` on that fill: the store, as the pass left it."""
    w = World(oms=_KeepingStore())
    w.oms.records = [_pending_record()]
    w.venue.seed_order(_stop_order(7, state="filled", filled_qty=Decimal("0.2")), uid="1001")
    w.oms.seed(row(3, "accepted"))
    e7 = fill("e7", n=7, side="sell", qty=Decimal("0.2"), order_link_id=ext_key("x7"))
    w.oms.handed_fills = [waiting(e7, entry_id=41), waiting(fill("e3", n=3), entry_id=42)]
    plan = await w.plan()
    if failure == "timed_out":
        w.oms.fail["get_by_exchange_order_id"] = TimeoutError()
    elif failure == "another_account":

        async def foreign(*_a: Any) -> Any:
            return row(7, exchange_account_id=OTHER)

        monkeypatch.setattr(w.oms, "get_by_exchange_order_id", foreign)
    elif failure == "exec_refused":
        push = w.oms.push

        async def refused(account_id: Any, order_id: Any, event: str, payload: Any) -> None:
            if payload.get("exec_id") == "e7":
                raise ConnectionError("the facade's step writer is down")
            await push(account_id, order_id, event, payload)

        monkeypatch.setattr(w.oms, "push", refused)
    await w.reconciler.remediate(plan)
    return w


@pytest.mark.parametrize("failure", ["timed_out", "another_account", "exec_refused"])
async def test_3d_a_materialised_stops_fill_is_settled_only_once_applied(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#5121's security delta r2, Low 1 (24 Sec.8.5 step 3d): the fill's hand-over entry is
    settled only once `_fill` applied it, as `PushFill` settles one, so a re-read that times out
    or answers another account's row, or an `EXEC` that fails, leaves entry 41 in the store for
    the next pass; entry 42, whose fill step 2 applied, is pruned beside it."""
    w = await _materialised_from_the_store(failure, monkeypatch)
    assert [e[2] for e in w.oms.effects("materialise")] == ["x7"]
    assert [e.entry_id for e in w.oms.handed_fills] == [41]
    assert w.oms.effects("prune") == [("prune", (42,))]


async def test_3d_a_materialised_stops_fill_applied_is_settled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control: a re-read that answers the row applies the fill, and both entries go."""
    w = await _materialised_from_the_store("none", monkeypatch)
    assert [e[2] for e in w.oms.effects("push")] == ["EXEC", "EXEC"]
    assert (w.oms.handed_fills, w.oms.effects("prune")) == ([], [("prune", (41, 42))])


async def test_a_recorded_stop_under_our_own_id_keeps_it_while_no_row_holds_it() -> None:
    w = World()
    w.oms.records = [_pending_record()]
    w.venue.seed_order(_stop_order(7, order_link_id=LINK.format(7)), uid="1001")
    await w.run()
    assert w.oms.effects("materialise")[0][1] == LINK.format(7)


@pytest.mark.parametrize(
    ("qty", "fill_qty", "expected"), [(0, None, Decimal("0.2")), (0, "0.3", Decimal("0.3"))]
)
async def test_a_full_mode_stop_showing_no_size_is_sized_by_its_fill_or_position(
    qty: int, fill_qty: str | None, expected: Decimal
) -> None:
    w = World()
    w.oms.records = [_pending_record()]
    w.venue.seed_position(position(stop_loss=Decimal(62000)))
    order = _stop_order(7, qty=Decimal(qty), leaves_qty=Decimal(0))
    plan = await w.plan()
    fill_of = None if fill_qty is None else fill("e7", n=7, qty=Decimal(fill_qty))
    rem = rc._Remediation(w.reconciler, plan)
    assert rem._size_of(_pending_record(), order, fill_of) == expected
    with pytest.raises(ValueError):
        rem._size_of(_pending_record(), order.model_copy(update={"position_idx": 1}), None)


async def test_a_flat_position_is_never_tested_for_a_stop() -> None:
    w = World()
    w.venue.seed_position(position(qty=Decimal(0), side=None, stop_loss=None))
    assert (await w.run()).errors == ()


async def test_a_record_of_the_other_side_or_kind_is_not_in_force() -> None:
    w = World()
    w.oms.records = [record(position_side="Sell"), record(id=UUID(int=0x5703), kind="take_profit")]
    w.venue.seed_position(position(stop_loss=None))
    report = await w.run()
    assert report.errors == (PassError("5", "no_record_in_force", "BTCUSDT"),)


async def test_a_restore_the_writer_does_not_send_is_listed() -> None:
    w = World()
    w.oms.records = [record()]
    w.oms.stop_writes["restore"] = "not_sent"
    w.venue.seed_position(position(stop_loss=Decimal(61000)))
    assert (await w.run()).errors == (PassError("5", "restore_not_sent", "BTCUSDT"),)


async def test_a_prune_that_fails_is_listed() -> None:
    w = World()
    w.oms.seed(row(1))
    w.oms.stored_ids = {"e1"}
    w.oms.handed_fills = [waiting(fill("e1"))]
    w.oms.fail["prune"] = ConnectionError("down")

    async def prune(*_a: Any) -> int:
        raise ConnectionError("down")

    w.oms.prune = prune  # type: ignore[method-assign]  # the store refuses the prune
    report = await w.run()
    assert PassError("3d", "ConnectionError") in report.errors


async def test_a_fill_and_a_fact_the_facade_answers_as_anomalies_are_listed() -> None:
    w = World()
    w.oms.seed(row(1), row(2))
    w.oms.anomaly_on_push = {row(1).id, row(2).id}
    w.venue.seed_execution(fill("e1"))
    w.venue.seed_order(remote(2, state="triggered"), uid="1001")
    report = await w.run()
    assert set(report.anomalies) == {LINK.format(1), LINK.format(2)}


async def test_a_handed_over_fill_applied_to_its_row_is_pruned() -> None:
    w = World()
    w.oms.seed(row(1))
    w.oms.handed_fills = [waiting(fill("e1"), entry_id=44)]
    await w.run()
    assert w.oms.effects("prune") == [("prune", (44,))]


@pytest.mark.parametrize(
    ("fault", "step"),
    [
        ("insert", "2"),
        ("apply", "4"),
        ("hand_over_execution", "3d"),
        ("materialise", "3c"),
        ("attach_recorded", "5"),
        ("get_by_exchange_order_id", "2"),
    ],
)
async def test_each_actions_failure_is_listed_with_its_step(
    fault: str, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World()
    eth = replace(
        _pending_record(), symbol="ETHUSDT", id=UUID(int=0x5704)
    )  # SOLUSDT's key: no race
    w.oms.records = [record(), replace(eth, symbol="SOLUSDT")]
    w.oms.held = {("ETHUSDT", 0): PositionDriftSeen("buy", Decimal(1))}
    w.venue.seed_position(position(symbol="ETHUSDT", qty=Decimal(2)))
    w.venue.seed_position(position(stop_loss=None))
    w.venue.seed_execution(fill("f1", exec_type="funding"))
    w.venue.seed_execution(fill("e9", n=9, order_link_id=ext_key("x9")))
    w.venue.seed_order(_stop_order(7, symbol="SOLUSDT"), uid="1001")

    async def fails(*_a: Any, **_k: Any) -> Any:
        raise ConnectionError("down")

    monkeypatch.setattr(w.oms, fault, fails)
    report = await w.run()
    assert step in {e.step for e in report.errors if e.kind == "ConnectionError"}


async def test_the_pages_remembered_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rc, "PAGED_BOUND", 1)
    w = World()
    w.reconciler.page_once("oms_unknown_past_history", ACCOUNT, "a")
    w.reconciler.page_once("oms_unknown_past_history", ACCOUNT, "b")
    w.reconciler.page_once("oms_unknown_past_history", ACCOUNT, "a")  # forgotten: paged again
    assert len(w.oms.pages) == 3


async def test_a_reconciler_with_no_naked_counter_still_attaches() -> None:
    w = World()
    w.reconciler = Reconciler(w.reconciler._p, now_us=lambda: NOW_US)
    w.oms.records = [record()]
    w.venue.seed_position(position(stop_loss=None))
    assert (await w.run()).sl_repaired == ("BTCUSDT",)


def test_a_full_match_on_malformed_money_never_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    def malformed(*_a: Any) -> bool:
        raise ValueError("malformed")

    monkeypatch.setattr(b01, "full_match", malformed)
    assert rc.full_match(row(1), remote(1)) is False


@pytest.mark.parametrize(
    ("state", "order", "fills", "events"),
    [
        (
            "untracked",
            remote(1, state="filled", filled_qty=Decimal(1)),
            [fill("e1", qty=Decimal(1))],
            ["RECON_FOUND_FILLED"],
        ),
        (  # B1 v8 applies the first as an EXEC; their sum completes the row
            "untracked",
            remote(1, state="filled", filled_qty=Decimal(1)),
            [fill("e1", qty=Decimal("0.4")), fill("e2", qty=Decimal("0.6"), seq=2)],
            ["EXEC", "RECON_FOUND_FILLED"],
        ),
        (  # fills read that do not complete the row: the store would refuse `filled`
            "untracked",
            remote(1, state="filled", filled_qty=Decimal(1)),
            [fill("e2", qty=Decimal("0.6"), seq=2)],
            None,
        ),
        ("untracked", remote(1, state="filled"), [], None),
        (
            "untracked",
            remote(1, state="partially_filled", filled_qty=Decimal("0.4")),
            [],
            ["RECON_FOUND_PARTIAL"],
        ),
        ("unknown", remote(1, state="filled", filled_qty=Decimal(0)), [], None),
        ("unknown", remote(1, state="cancelled"), [], ["RECON_FOUND_CANCELLED"]),
        ("unknown", remote(1, state="some_new_status"), [], None),
        (
            "quarantined",
            remote(1, state="partially_filled", filled_qty=Decimal("0.4")),
            [],
            ["RECON_FOUND_PARTIAL"],
        ),
    ],
)
def test_found_sends_by_the_rows_state_and_the_orders(
    state: str, order: Any, fills: list[Any], events: list[str] | None
) -> None:
    have = Decimal("0.4") if state == "quarantined" else Decimal(0)
    sends = found_sends(
        row(1, state, lifecycle_state=state, cum_exec_qty=have),
        order,
        fills,
        pass_id=SWEEP_ID,
        ts_event=NOW_US,
    )
    assert (None if sends is None else [s.event for s in sends]) == events


async def test_the_phases_report_a_remediation_that_fails_as_a_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job()

    async def broken(*_a: Any) -> None:
        raise ReconcileAnomaly("filled", "EXEC")

    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    await job.phases.diff(str(ACCOUNT), pass_id=SWEEP_ID)
    monkeypatch.setattr(job.world.reconciler, "remediate", broken)
    with pytest.raises(ReconcileAnomaly):
        await job.phases.remediate(str(ACCOUNT), pass_id=SWEEP_ID)
    await job.phases.report(
        str(ACCOUNT), pass_id=SWEEP_ID, trigger="oddly", episode_open=False, failure=None
    )
    state = job.records.rows[0][2]
    assert (state["trigger"], state["errors"]) == (
        "periodic",
        [{"step": "5", "kind": "ReconcileAnomaly", "subject": None}],
    )


async def test_the_phases_list_an_unreadable_handover_when_the_diff_never_ran() -> None:
    job = Job()
    job.world.oms.unreadable = [3]
    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    await job.phases.report(
        str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic", episode_open=False, failure=None
    )
    assert job.records.rows[0][2]["errors"] == [
        {"step": "1", "kind": "handover_unreadable", "subject": "3"}
    ]


async def test_the_phases_hold_the_watermark_when_it_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job()

    async def refuse(*_a: Any) -> None:
        raise ConnectionError("down")

    monkeypatch.setattr(job.watermarks, "advance", refuse)
    await job.phases.fetch(str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic")
    summary = await job.phases.report(
        str(ACCOUNT), pass_id=SWEEP_ID, trigger="periodic", episode_open=False, failure=None
    )
    assert summary["outcome"] == "clean"


async def _one_pass(job: Job) -> Any:
    """One pass through B19's port (`ReconcilePhases`): its `oms.reconcile` record."""
    account = str(ACCOUNT)
    await job.phases.fetch(account, pass_id=SWEEP_ID, trigger="periodic")
    await job.phases.diff(account, pass_id=SWEEP_ID)
    await job.phases.remediate(account, pass_id=SWEEP_ID)
    await job.phases.report(
        account, pass_id=SWEEP_ID, trigger="periodic", episode_open=False, failure=None
    )
    return job.records.rows[-1][2]


async def test_the_phases_hold_the_watermark_for_a_tracked_rows_unread_fills() -> None:
    """24 Sec.8.5: an `unknown` row whose fills the pass did not read is `fills_unread`, which
    holds the watermark, so the next pass reads that window again."""
    job = Job()
    job.world.oms.seed(row(1, "unknown", lifecycle_state="unknown"))
    job.world.venue.seed_order(
        remote(1, state="partially_filled", filled_qty=Decimal("0.8")), uid="1001"
    )
    state = await _one_pass(job)
    assert state["errors"] == [{"step": "3a", "kind": "fills_unread", "subject": LINK.format(1)}]
    assert job.watermarks.advanced == []


async def test_the_phases_close_an_untracked_row_filled_in_two_fills() -> None:
    """B1 chart version 8 applies an `untracked` row's `EXEC`, so the orchestrator's interim (iv)
    ends for an order filled in two fills (24 Sec.8.5): the pass sends the first as an `EXEC`, the
    second rides the `RECON_FOUND_FILLED` that closes the row, as the two complete it, and nothing
    is listed or kept; the watermark advances."""
    job = Job()
    job.world.oms.seed(row(1, "untracked", lifecycle_state="untracked"))
    filled = remote(1, state="filled", filled_qty=Decimal(1), leaves_qty=Decimal(0))
    job.world.venue.seed_order(filled, uid="1001")
    for n, qty in ((1, "0.4"), (2, "0.6")):
        job.world.venue.seed_execution(fill(f"e{n}", qty=Decimal(qty), seq=n))
    state = await _one_pass(job)
    assert (state["errors"], state["resolved_from_history"]) == ([], [LINK.format(1)])
    assert job.watermarks.advanced == [NOW_US]
    sent = job.world.oms.effects("command", "push")
    assert [(e[0], e[2]) for e in sent] == [("push", "EXEC"), ("command", "RECON_FOUND_FILLED")]
    assert (sent[0][3]["exec_id"], sent[1][3]["execution"]["exec_id"]) == ("e1", "e2")
    assert job.world.oms.effects("hand_over_execution") == []


async def test_the_phases_advance_the_watermark_past_an_untracked_row_its_fills_cannot_close() -> (
    None
):
    """24 Sec.8.5: an `untracked` row whose fills read cannot complete it (the venue counts a fill
    no window read holds) is listed `untracked_fills_unread`, a standing item: the pass sends it
    nothing, keeps the fill it read and advances the watermark."""
    job = Job()
    job.world.oms.seed(row(1, "untracked", lifecycle_state="untracked"))
    filled = remote(1, state="filled", filled_qty=Decimal(1), leaves_qty=Decimal(0))
    job.world.venue.seed_order(filled, uid="1001")
    job.world.venue.seed_execution(fill("e2", qty=Decimal("0.6"), seq=2))  # e1 is unread
    state = await _one_pass(job)
    assert state["errors"] == [
        {"step": "3b", "kind": "untracked_fills_unread", "subject": LINK.format(1)}
    ]
    assert job.watermarks.advanced == [NOW_US]
    assert job.world.oms.effects("command", "push") == []
    assert [e[1] for e in job.world.oms.effects("hand_over_execution")] == ["e2"]


def test_the_phases_observe_only_their_own_report_and_refuse_a_bad_severity() -> None:
    job = Job()
    job.phases.observe(str(ACCOUNT), pass_id=SWEEP_ID)  # none stored: nothing counted
    with pytest.raises(ValueError):
        job.phases.publish(str(ACCOUNT), [["oms.account_desync", "page"]])


def test_the_job_ports_are_wired_once_and_read_from_the_build_input() -> None:
    assert not b19.ports_wired()
    phases: ReconcilePhases = Job().phases
    b19.set_ports(phases)
    try:
        assert b19.ports_wired()
    finally:
        b19.set_ports(None)
    assert b19._account({"input": {"account_id": str(ACCOUNT)}}) == str(ACCOUNT)
    assert b19._account({"input": "nope"}) is None
