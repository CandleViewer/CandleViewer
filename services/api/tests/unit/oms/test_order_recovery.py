"""Recovery from `order_events` (E29-T03 #847; 24-internal-schemas.md Sec.8.2, "Recovery"): the
fold that rebuilds an order's row (OM-T03), and the facade's hydration of the order's machine
after a restart (A7), which replays the recorded steps (Gherkin "Crash recovery is deterministic"),
on the real binding with the in-memory stores."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer.oms.errors import (
    IllegalTransition,
    OrderHistoryRefused,
    OrderNotLoaded,
    ReconcileAnomaly,
)
from candleviewer.oms.order_machine import Legality
from candleviewer.oms.order_steps import event_kind
from candleviewer.oms.recovery import (
    FINALS,
    RebuiltOrder,
    rebuild,
    recorded_outcomes,
    replay_plan,
)
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import (
    LIFECYCLE_STATE_OF,
    ORDER_STATE_OF,
    NewOrder,
    NewOrderEvent,
    OrderEventRow,
    OrderState,
)
from tests.unit.oms.order_rig import ACCOUNT, OTHER, T0, Rig, build_rig, fill_of, gated, order_of

CHART = Registry().get("order")
LEGALITY = Legality.of(CHART)
FOUND = {"exchange_order_id": "x1", "order_type": "limit", "reduce_only": False, "qty": "1"}
FOUND |= {"price": "63000", "trigger_price": None, "stop_loss": "62000", "symbol": "BTCUSDT"}
FOUND |= {"side": "buy", "account_id": str(ACCOUNT)}


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = build_rig()
    yield out
    await out.facade.stop()


async def _push(rig: Rig, order: NewOrder, event: Any, payload: Mapping[str, Any]) -> None:
    await rig.facade.push(ACCOUNT, order.id, event, payload)
    await rig.quiet()


async def _command(rig: Rig, order: NewOrder, event: Any, payload: Any = None) -> None:
    await rig.facade.command(ACCOUNT, order.id, event, payload, actor="system")
    await rig.quiet()


# --- The paths an order takes, each to the state it rests in --------------------------------------


async def _submitted(rig: Rig) -> NewOrder:
    return await rig.submitted()


async def _partial(rig: Rig) -> NewOrder:
    order = await rig.submitted()
    await _push(rig, order, "EXEC", fill_of(order, "e1", "0.4"))
    return order


async def _filled(rig: Rig) -> NewOrder:
    order = await _partial(rig)
    await _push(rig, order, "EXEC", fill_of(order, "e2", "0.6"))
    return order


async def _amended(rig: Rig) -> NewOrder:
    order = await _partial(rig)
    await rig.facade.command(ACCOUNT, order.id, "AMEND", {"price": "64000"}, actor="user")
    await rig.quiet()
    return order


async def _amend_refused(rig: Rig) -> NewOrder:
    order = await rig.submitted()

    async def refused(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False, "error_code": "PRICE_OUT_OF_BOUNDS"}

    rig.commands.on_amend = refused
    await rig.facade.command(ACCOUNT, order.id, "AMEND", {"price": "64000"}, actor="user")
    await rig.quiet()
    return order


async def _amend_rejected(rig: Rig) -> NewOrder:
    order = await _partial(rig)
    rig.commands.on_amend = gated({"ok": True})[1]  # the exchange's reject comes first
    await rig.facade.command(ACCOUNT, order.id, "AMEND", {"price": "64000"}, actor="user")
    await _push(rig, order, "AMEND_REJECTED", {"error_code": "PRICE_OUT_OF_BOUNDS"})
    return order


async def _cancel_refused(rig: Rig) -> NewOrder:
    order = await _partial(rig)

    async def refused(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False, "error_code": "EXCHANGE_UNKNOWN"}

    rig.commands.on_cancel = refused
    await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    await rig.quiet()
    return order


async def _cancel_lost(rig: Rig) -> NewOrder:
    """A cancel in flight when a fill came: the fill won (S3) and the cancel's answer never came."""
    order = await _partial(rig)
    rig.commands.on_cancel = gated({"ok": True})[1]
    await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    await _push(rig, order, "EXEC", fill_of(order, "e2", "0.2"))
    return order


async def _overlong_ack(rig: Rig) -> NewOrder:
    """An ack whose exchange order id is longer than B1 takes: the order is acked, never bound."""

    async def overlong(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": True, "exchange_order_id": "x" * (b01.MAX_TEXT + 1)}

    rig.commands.on_place = overlong
    order = order_of()
    await rig.start(order)
    await _command(rig, order, "SEND")
    return order


async def _triggered(rig: Rig) -> NewOrder:
    order = await rig.submitted()
    await _push(rig, order, "TRIGGERED", {"updated_time": 1})
    return order


async def _unknown(rig: Rig) -> NewOrder:
    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    rig.commands.on_place = ambiguous
    order = order_of()
    await rig.start(order)
    await _command(rig, order, "SEND")
    return order


async def _missed(rig: Rig) -> NewOrder:
    order = await _unknown(rig)
    await _command(rig, order, "RECON_MISS", {"pass_id": "p1"})
    return order


async def _unresolved(rig: Rig) -> NewOrder:
    order = await _missed(rig)
    await _command(rig, order, "RECON_MISS", {"pass_id": "p2"})
    return order


async def _reconciled(rig: Rig) -> NewOrder:
    order = await _unknown(rig)
    found = {"exchange_order_id": "x1", "execution": fill_of(order, "e1", "0.4")}
    await _command(rig, order, "RECON_FOUND_PARTIAL", found)
    return order


async def _quarantined(rig: Rig) -> NewOrder:
    order = await _partial(rig)
    await _push(rig, order, "EXEC", fill_of(order, "e9", "0.1", exchange_order_id="x-foreign"))
    return order


async def _held(rig: Rig) -> NewOrder:
    order = await rig.submitted()
    await _command(rig, order, "MISMATCH", {"exchange_order_id": "x9"})
    return order


async def _held_unbound(rig: Rig) -> NewOrder:
    """An order lost in transit, then held: the mismatching id is never bound (SR-E29-03)."""
    order = await _unknown(rig)
    await _command(rig, order, "MISMATCH", {"exchange_order_id": "x9"})
    return order


async def _untracked(rig: Rig) -> NewOrder:
    found = order_of(7, order_link_id="ext-" + "ab" * 16, exchange_order_id="x7")
    await rig.facade.discover(found, environment="demo")
    return found


async def _duplicate(rig: Rig) -> NewOrder:
    """A duplicate-id result whose lookup found the order as the row has it (SR-E29-03)."""
    order = order_of()

    async def taken(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False, "error_code": "DUPLICATE_CLIENT_ID"}

    async def found(_command: b01.Command) -> Mapping[str, Any]:
        return FOUND | {"order_link_id": order.order_link_id}

    rig.commands.on_place, rig.commands.on_lookup = taken, found
    await rig.start(order)
    await _command(rig, order, "SEND")
    return order


async def _rejected(rig: Rig) -> NewOrder:
    async def refused(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False, "error_code": "RATE_LIMITED"}

    rig.commands.on_place = refused
    order = order_of()
    await rig.start(order)
    await _command(rig, order, "SEND")
    return order


async def _expired(rig: Rig) -> NewOrder:
    order = await _triggered(rig)
    await _push(rig, order, "EXPIRE", {"updated_time": 2})
    return order


async def _remote_cancelled(rig: Rig) -> NewOrder:
    order = await _partial(rig)
    await _push(rig, order, "REMOTE_CANCELLED", {"cum_exec_qty": "0.4", "updated_time": 5})
    return order


async def _killed(rig: Rig) -> NewOrder:
    order = await _partial(rig)
    await rig.facade.kill("kill switch engaged")
    await rig.quiet()
    return order


Path = Callable[[Rig], Awaitable[NewOrder]]
#: Each path to a state an order rests in that is not final, and the state.
LIVE: dict[str, tuple[Path, str]] = {
    "submitted": (_submitted, "submitted"),
    "partial": (_partial, "partially_filled"),
    "amended": (_amended, "partially_filled"),
    "amend_refused": (_amend_refused, "submitted"),
    "amend_rejected": (_amend_rejected, "partially_filled"),
    "cancel_refused": (_cancel_refused, "partially_filled"),
    "cancel_lost": (_cancel_lost, "partially_filled"),
    "triggered": (_triggered, "triggered"),
    "unknown": (_unknown, "unknown"),
    "missed": (_missed, "unknown"),
    "reconciled": (_reconciled, "partially_filled"),
    "quarantined": (_quarantined, "quarantined"),
    "held": (_held, "held"),
    "held_unbound": (_held_unbound, "held"),
    "untracked": (_untracked, "untracked"),
    "duplicate": (_duplicate, "submitted"),
    "overlong_ack": (_overlong_ack, "submitted"),
}
FINAL: dict[str, tuple[Path, str]] = {
    "filled": (_filled, "filled"),
    "rejected": (_rejected, "rejected"),
    "unresolved": (_unresolved, "rejected"),
    "expired": (_expired, "expired"),
    "remote_cancelled": (_remote_cancelled, "cancelled"),
    "killed": (_killed, "killed"),
}


async def _history(rig: Rig, order: NewOrder) -> tuple[OrderEventRow, ...]:
    return await rig.events.list_for_order(order.exchange_account_id, order.id)


async def _row(rig: Rig, order: NewOrder) -> RebuiltOrder:
    row = await rig.orders.get(order.exchange_account_id, order.id)
    assert row is not None
    return RebuiltOrder.of_row(row)


# --- The fold: OM-T03 -----------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(LIVE | FINAL))
async def test_the_fold_of_an_orders_events_equals_its_row(rig: Rig, path: str) -> None:
    """OM-T03: whatever path the order took, its `order_events` alone rebuild its row: the state,
    the bound id, the terms, the fills (applied again, in order) and the reject columns."""
    walk, state = (LIVE | FINAL)[path]
    order = await walk(rig)
    rebuilt = rebuild(await _history(rig, order))
    assert rebuilt == await _row(rig, order)
    assert rebuilt.lifecycle_state == state


@pytest.mark.parametrize(
    ("path", "code"), [("rejected", "RATE_LIMITED"), ("unresolved", "UNRESOLVED_AFTER_RECONCILE")]
)
async def test_the_reject_columns_are_rebuilt_from_their_event(
    rig: Rig, path: str, code: str
) -> None:
    """OM-T03: a reject's code is its event's `ret_code`, the fold's one source."""
    order = await FINAL[path][0](rig)
    history = await _history(rig, order)
    rebuilt, row = rebuild(history), await _row(rig, order)
    assert (history[-1].ret_code, rebuilt.reject_code, row.reject_code) == (code, code, code)
    assert rebuilt.reject_message is None


def test_lifecycle_state_of_inverts_order_state_of() -> None:
    """21 Sec.3.3.5: a reader of events maps each `to_state` back exactly: one to one, total."""
    assert {chart: LIFECYCLE_STATE_OF[stored] for chart, stored in ORDER_STATE_OF.items()} == dict(
        zip(ORDER_STATE_OF, ORDER_STATE_OF, strict=True)
    )
    assert len(LIFECYCLE_STATE_OF) == len(ORDER_STATE_OF)
    assert FINALS == LEGALITY.finals


# --- Hydration: A7, 24 Sec.8.2 "Recovery" ---------------------------------------------------------


async def _crashed(rig: Rig, order: NewOrder) -> tuple[Any, dict[str, Any], Rig]:
    """The machine as it stood (its states and context, if it lives), then a crash and a
    restart."""
    state = rig.facade.state(order.id)
    context = {} if state is None else dict(rig.context(order))
    return state, context, await rig.restart()


async def test_crash_recovery_is_deterministic(rig: Rig) -> None:
    """Gherkin "Crash recovery is deterministic": given the `order_events` of an order that was
    sent, filled in part, triggered and amended, when the order is rebuilt from its events alone,
    the result equals the state before the simulated crash: the fold equals the row, and the
    machine hydrated from them equals, configuration and context, the one that crashed, twice."""
    order = await _amended(rig)
    await _push(rig, order, "EXEC", fill_of(order, "e2", "0.1"))
    history, row = await _history(rig, order), await _row(rig, order)
    state, context, again = await _crashed(rig, order)
    assert rebuild(history) == row
    for _ in range(2):
        assert await again.facade.hydrate(ACCOUNT, order.id, environment="demo") == state[0]
        await again.quiet()
        assert (again.facade.state(order.id), again.context(order)) == (state, context)
        again = await again.restart()
    await again.facade.stop()


@pytest.mark.parametrize("path", sorted(LIVE))
async def test_a_hydrated_machine_equals_the_one_that_crashed(rig: Rig, path: str) -> None:
    """A7: for each state an order rests in, the replay rebuilds the machine, configuration and
    context: the replayed steps write, audit and notify nothing, a recorded answer is never asked
    for again, and an order with fills has its stop confirmed from an exchange read (24 Sec.8.8
    rule 2), the one command hydration sends."""
    order = await LIVE[path][0](rig)
    history = await _history(rig, order)
    state, context, again = await _crashed(rig, order)
    try:
        assert await again.facade.hydrate(ACCOUNT, order.id, environment="demo") == state[0]
        await again.quiet()
        assert (again.facade.state(order.id), again.context(order)) == (state, context)
        assert await _history(again, order) == history  # nothing written
        assert (again.audit.records, again.notices.got) == ([], [])
        stop = ["attach_stop"] if Decimal(context["filled_qty"]) > 0 else []
        assert again.commands.kinds() == stop
        first = again.publish.calls[0][2]  # no replayed step is published, only where it ends
        assert (first["state"], first["regions"]["protection"]) == (state[0], "not_required")
    finally:
        await again.facade.stop()


async def _held_foreign_fill(rig: Rig) -> NewOrder:
    """A held order consumes a fill of another exchange order (S6), which does not pair."""
    order = await _held(rig)
    fill = fill_of(order, "e1", "0.1", exchange_order_id="x-foreign")
    with pytest.raises(ReconcileAnomaly):
        await rig.facade.push(ACCOUNT, order.id, "EXEC", fill)
    await rig.quiet()
    return order


async def _held_released_fill(rig: Rig) -> NewOrder:
    """A fill that came while the order was lost in transit waits for the bind (SR-E29-03); the
    order is held instead, never bound, so it consumes the released fill unpaired."""
    order = await _unknown(rig)
    await _push(rig, order, "EXEC", fill_of(order, "e1", "0.1", exchange_order_id="x1"))
    await _command(rig, order, "MISMATCH", {"exchange_order_id": "x1"})
    return order


HELD_UNPAIRED: dict[str, Path] = {"foreign": _held_foreign_fill, "released": _held_released_fill}


@pytest.mark.parametrize("path", sorted(HELD_UNPAIRED))
async def test_a_held_order_that_handed_an_unpaired_fill_to_b8_hydrates_as_it_crashed(
    rig: Rig, path: str
) -> None:
    """A7, INV-B1-o, C-2.6: a held order consumes a fill that does not pair with it (S6), so it
    starts no stop and hands the position to B8 (`request_fallback_sl`), once. No event holds
    that notice: the hydrated machine is the one that crashed, both regions and the context but
    the outbox, whose anchor is the replayed `held` step's alert, never the internal arm's
    notice; and it sends nothing again, no attach and no notice, and writes and audits nothing."""
    order = await HELD_UNPAIRED[path](rig)
    assert rig.facade.state(order.id) == ("held", "not_required")
    assert rig.notices.kinds().count("request_fallback_sl") == 1
    assert "attach_stop" not in rig.commands.kinds()
    history = await _history(rig, order)
    state, context, again = await _crashed(rig, order)
    assert context["outbox"][-1]["kind"] == "request_fallback_sl"
    try:
        assert await again.facade.hydrate(ACCOUNT, order.id, environment="demo") == "held"
        await again.quiet()
        hydrated = again.context(order)
        assert again.facade.state(order.id) == state
        kept = {key: value for key, value in context.items() if key != "outbox"}
        assert {key: value for key, value in hydrated.items() if key != "outbox"} == kept
        outbox = [(notice["kind"], notice.get("alert")) for notice in hydrated["outbox"]]
        assert outbox == [("alert", "order_held")]
        assert (again.commands.sent, again.notices.got, again.audit.records) == ([], [], [])
        assert await _history(again, order) == history
    finally:
        await again.facade.stop()


async def test_a_crash_mid_place_looks_the_id_up_before_it_sends(rig: Rig) -> None:
    """SR-E29-15, S1: the place was in flight, so the record holds no answer. The resumed place
    looks the id up first and, finding the order as the row has it, adopts it unsent."""
    order = order_of()
    rig.commands.on_place = gated({"ok": True, "exchange_order_id": "x1"})[1]
    await rig.start(order)
    await _command(rig, order, "SEND")
    _state, _context, again = await _crashed(rig, order)

    async def found(_command: b01.Command) -> Mapping[str, Any]:
        return FOUND | {"order_link_id": order.order_link_id}

    again.commands.on_lookup = found
    try:
        assert await again.facade.hydrate(ACCOUNT, order.id, environment="demo") == "submitting"
        await again.quiet()
        assert again.facade.state(order.id) == ("submitted", "not_required")
        assert again.commands.kinds() == ["lookup"]
        assert (await _row(again, order)).exchange_order_id == "x1"
    finally:
        await again.facade.stop()


async def test_a_crash_mid_place_with_nothing_found_sends_it_once(rig: Rig) -> None:
    """SR-E29-15: the lookup finds nothing under the id, so the place goes out, once, under the
    same `order_link_id` and attempt key (C-2.10)."""
    order = order_of()
    rig.commands.on_place = gated({"ok": True})[1]
    await rig.start(order)
    await _command(rig, order, "SEND")
    key = rig.commands.sent[0].key
    _state, _context, again = await _crashed(rig, order)
    try:
        await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await again.quiet()
        assert again.facade.state(order.id) == ("submitted", "not_required")
        assert [(c.kind, c.key) for c in again.commands.sent] == [("lookup", key), ("place", key)]
        assert again.commands.sent[1].order["stop_loss"] == "62000"  # C-2.6 on the resumed place
    finally:
        await again.facade.stop()


async def test_a_crash_mid_cancel_sends_the_cancel_again_under_its_key(rig: Rig) -> None:
    """B1.8 "Restore re-drives invokes": the cancel's answer was lost, so the resumed cancel goes
    out once more under the attempt's key, which the command port deduplicates on (C-2.10)."""
    order = await _partial(rig)
    rig.commands.on_cancel = gated({"ok": True})[1]
    await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    await rig.quiet()
    key = next(c.key for c in rig.commands.sent if c.kind == "cancel")
    _state, _context, again = await _crashed(rig, order)
    try:
        await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await again.quiet()
        assert [(c.kind, c.key) for c in again.commands.sent if c.kind == "cancel"] == [
            ("cancel", key)
        ]
        assert again.facade.state(order.id) is None  # cancelled, its stop confirmed: evicted
        assert (await _row(again, order)).state == "cancelled"
    finally:
        await again.facade.stop()


@pytest.mark.parametrize("path", sorted(FINAL))
async def test_a_final_order_gets_no_machine(rig: Rig, path: str) -> None:
    """MUST-11: a final order is answered from its events and row, and S6 reads the row."""
    order = await FINAL[path][0](rig)
    _state, _context, again = await _crashed(rig, order)
    assert await again.facade.hydrate(ACCOUNT, order.id, environment="demo") == FINAL[path][1]
    assert again.facade.state(order.id) is None and again.commands.sent == []
    await again.facade.stop()


async def test_hydrating_a_live_order_answers_its_state(rig: Rig) -> None:
    order = await rig.submitted()
    published = len(rig.publish.calls)
    assert await rig.facade.hydrate(ACCOUNT, order.id, environment="demo") == "submitted"
    assert len(rig.publish.calls) == published and rig.commands.kinds() == ["place"]


async def test_a_hydrated_machine_is_scoped_to_its_stored_account(rig: Rig) -> None:
    """OM-I02, C-12.4: hydration builds the machine with the stored order's
    account, so its state is published to that account only, and another account's command or
    push finds nothing, as for an unknown order."""
    order = await rig.submitted()
    _state, _context, again = await _crashed(rig, order)
    try:
        await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        assert {(o, a) for o, a, _p, _l in again.publish.calls} == {(order.id, ACCOUNT)}
        with pytest.raises(OrderNotLoaded):
            await again.facade.command(OTHER, order.id, "CANCEL", actor="user")
        with pytest.raises(OrderNotLoaded):
            await again.facade.push(OTHER, order.id, "TRIGGERED", {"updated_time": 1})
        assert again.facade.state(order.id) == ("submitted", "not_required")
        assert again.commands.sent == []
    finally:
        await again.facade.stop()


async def test_only_the_accounts_own_order_is_hydrated(rig: Rig) -> None:
    """C-12.4: another account's order is not found, as an unknown one is (no oracle)."""
    order = await rig.submitted()
    _state, _context, again = await _crashed(rig, order)
    try:
        for account, order_id in ((OTHER, order.id), (ACCOUNT, UUID(int=9))):
            with pytest.raises(OrderNotLoaded):
                await again.facade.hydrate(account, order_id, environment="demo")
        assert again.facade.state(order.id) is None
    finally:
        await again.facade.stop()


def _edit(rig: Rig, order: NewOrder, **changes: Any) -> None:
    """A database writer edits the order's row outside any step (OM-T03)."""
    row = rig.store._orders[order.id]
    rig.store._orders[order.id] = replace(row, **changes)


def _drop(rig: Rig, order: NewOrder, seq: int) -> None:
    """A database writer deletes one of the order's events (OM-T03)."""
    del rig.store._events[order.id][seq]


def _forge(rig: Rig, order: NewOrder, seq: int, **payload: Any) -> None:
    """A database writer rewrites one event's payload (OM-T03)."""
    stored = rig.store._events[order.id][seq]
    forged = json.loads(stored.payload) | payload
    rig.store._events[order.id][seq] = type(stored)(stored.row, json.dumps(forged))


_TAMPER: dict[str, tuple[Callable[[Rig, NewOrder], None], str]] = {
    "qty": (lambda rig, order: _edit(rig, order, qty=Decimal(2)), "do not rebuild its row"),
    "account": (
        lambda rig, order: _edit(rig, order, exchange_account_id=OTHER),
        "do not rebuild its row",
    ),
    "filled": (
        lambda rig, order: _edit(rig, order, cum_exec_qty=Decimal("0.5")),
        "do not rebuild its row",
    ),
    "state": (
        lambda rig, order: _edit(rig, order, state="accepted", lifecycle_state="submitted"),
        "do not rebuild its row",
    ),
    "event_dropped": (lambda rig, order: _drop(rig, order, 2), "no event at seq 2"),
    "fill_forged": (
        lambda rig, order: _forge(rig, order, 3, exchange_order_id="x-foreign"),
        "replayed EXEC at seq 3 moved nothing",
    ),
    "ack_forged": (
        lambda rig, order: _forge(rig, order, 2, ok=False),
        "replay left the record at seq 2",
    ),
    "payload_forged": (
        lambda rig, order: _forge(rig, order, 3, forged="x"),
        "seq 3 has no single B1 trigger",
    ),
}


@pytest.mark.parametrize(
    ("staged", "why"),
    [({"price": "0"}, "not the order its events rebuild"),  # nothing staged, nothing adopted
     ({"qty": "0.6"}, "replay left the record at seq 6")],  # 0.6 staged: the next fill closes it
)  # fmt: skip
async def test_a_forged_amend_request_is_refused_where_the_replay_leaves_the_record(
    rig: Rig, staged: dict[str, str], why: str
) -> None:
    """The fold reads an amend's terms off its result, the replay stages them off its request: a
    request edited after the fact makes the replayed machine another order than the row (at its
    end, or at the step it first diverges on), and the hydration is refused and pages."""
    order = await _amended(rig)
    await _push(rig, order, "EXEC", fill_of(order, "e2", "0.2"))
    _state, _context, again = await _crashed(rig, order)
    _forge(again, order, 4, **staged)
    try:
        with pytest.raises(OrderHistoryRefused, match=why):
            await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        assert again.facade.state(order.id) is None and again.commands.sent == []
        assert again.pager.calls[-1:] == ["oms_order_history_refused"]
    finally:
        await again.facade.stop()


async def test_a_refused_replay_stops_its_machine_before_its_parked_invoke_runs(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-E29-15, OM-T03: an order that crashed with its cancel unanswered replays to
    `cancel_pending`, whose cancel waits for the replay to end. A replay then refused at its end
    stops the machine before it ends the replay, so that cancel is never sent, even when stopping
    the machine yields to the loop first."""
    order = await _amended(rig)
    _gate, rig.commands.on_cancel = gated({"ok": True})
    await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    _state, _context, again = await _crashed(rig, order)
    _forge(again, order, 4, price="0")  # the replayed machine is not the order its events rebuild
    close = again.facade._close

    async def close_yielding(o: Any, *, publish: bool) -> None:
        for _ in range(16):
            await asyncio.sleep(0)
        await close(o, publish=publish)

    monkeypatch.setattr(again.facade, "_close", close_yielding)
    try:
        with pytest.raises(OrderHistoryRefused, match="not the order its events rebuild"):
            await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await again.quiet()
        assert again.commands.sent == [] and b01._REPLAYS == {}
    finally:
        await again.facade.stop()


async def test_an_appended_event_is_no_step_of_the_replay(rig: Rig) -> None:
    """`OrderEventStore.append` writes an event with no state change: the replay passes it by."""
    order = await _partial(rig)
    said = NewOrderEvent(kind="error", source="local", event_ts=T0, payload={"note": "probe"})
    await rig.events.append(ACCOUNT, order.id, said)
    state, context, again = await _crashed(rig, order)
    try:
        await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await again.quiet()
        assert (again.facade.state(order.id), again.context(order)) == (state, context)
    finally:
        await again.facade.stop()


async def test_a_hydration_racing_a_build_never_makes_a_second_machine(rig: Rig) -> None:
    """One machine per order: a hydration that finds the order's machine still being built (no
    interpreter yet) is refused (`ILLEGAL_TRANSITION`), never a second machine."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    interp, o.interp = o.interp, None
    try:
        with pytest.raises(IllegalTransition, match="hydrate is not a transition"):
            await rig.facade.hydrate(ACCOUNT, order.id, environment="demo")
        assert rig.facade._orders[order.id] is o
    finally:
        o.interp = interp


def test_a_view_with_malformed_fills_starts_no_stop_outside_the_fill_states() -> None:
    """`starts_protection`, which hydration asks: malformed or no fills start nothing in a state
    an order reaches without a fill, a fill does, and `partially_filled` always does."""
    assert not b01.starts_protection({"filled_qty": "junk"}, "submitted")
    assert b01.starts_protection({"filled_qty": "0.1"}, "submitted")
    assert not b01.starts_protection({}, "submitted")
    assert b01.starts_protection({"filled_qty": "junk"}, "partially_filled")


def test_end_replay_of_an_order_not_replaying_does_nothing() -> None:
    b01.end_replay("cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-99en")
    assert b01._REPLAYS == {}


@pytest.mark.parametrize("tamper", sorted(_TAMPER))
async def test_a_history_that_does_not_rebuild_its_row_is_refused_and_pages(
    rig: Rig, tamper: str
) -> None:
    """OM-T03: an edited row, a dropped event or a forged one (a fill of another exchange order
    or an ack that did not bind, which the fold takes but B1's replay refuses, or a payload no
    closed schema takes) leaves the order unhydrated: the refusal is logged and paged, no machine
    is kept, and nothing is written or sent."""
    order = await _partial(rig)
    _state, _context, again = await _crashed(rig, order)
    edit, why = _TAMPER[tamper]
    edit(again, order)
    account = again.store._orders[order.id].exchange_account_id
    before = await again.store.list_for_order(account, order.id)
    try:
        with pytest.raises(OrderHistoryRefused, match=why):
            await again.facade.hydrate(account, order.id, environment="demo")
        assert again.facade.state(order.id) is None and again.commands.sent == []
        assert await again.store.list_for_order(account, order.id) == before
        assert again.pager.calls[-1:] == ["oms_order_history_refused"]
        assert b01._REPLAYS == {}
    finally:
        await again.facade.stop()


async def test_a_kill_that_waited_on_a_refused_hydration_reports_the_order(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-B1-h, C-2.9, OM-T03: a KILL that waited on the lock of an order whose hydration then
    refuses its history (a forged fill) finds no machine while the order's row is live: nothing
    recorded the KILL, so `kill()` answers the order, paged, never as one evicted once final."""
    order = await _partial(rig)
    _state, _context, again = await _crashed(rig, order)
    edit, why = _TAMPER["fill_forged"]
    edit(again, order)
    send, forged = again.facade._send_order, asyncio.Event()

    async def held_at_the_fill(o: Any, event: str, payload: Mapping[str, Any]) -> None:
        if event == "EXEC":  # the replay holds the order's lock here until the KILL waits on it
            await forged.wait()
        await send(o, event, payload)

    monkeypatch.setattr(again.facade, "_send_order", held_at_the_fill)
    try:
        hydrating = asyncio.ensure_future(
            again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        )
        await again.quiet()
        assert again.facade._orders[order.id].lock.locked()
        killing = asyncio.ensure_future(again.facade.kill("kill switch engaged"))
        await again.quiet()
        forged.set()
        with pytest.raises(OrderHistoryRefused, match=why):
            await hydrating
        assert await killing == (order.id,)
        paged = sorted(again.pager.calls[-2:])
        assert paged == ["oms_kill_not_recorded", "oms_order_history_refused"]
        row = await again.orders.get(ACCOUNT, order.id)
        assert row is not None and row.state == "partially_filled" and again.commands.sent == []
    finally:
        await again.facade.stop()


async def test_a_replayed_step_writes_no_audit_record(rig: Rig) -> None:
    """A step the record holds was audited when it happened: during a replay B1's audit hook
    writes nothing (no arm into a state an order rests in audits today; this keeps it so)."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    o.replaying = deque()
    await rig.facade._audited("halted_by_kill", {"order_id": str(order.id)})
    o.replaying = None
    await rig.facade._audited("halted_by_kill", {"order_id": str(order.id)})
    assert rig.audit.reasons("orders.cancel") == ["halted_by_kill"]


async def test_a_replayed_step_past_the_record_is_refused(rig: Rig) -> None:
    """A step the replay takes once every recorded one is replayed is no step of the record."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    o.replaying = deque()
    step = b01.Step(
        str(order.id), str(ACCOUNT), None, "submitted", "triggered", "TRIGGERED", {}, {}
    )
    with pytest.raises(OrderHistoryRefused, match="past its end"):
        await rig.facade._persist(step)
    o.replaying = None


async def test_a_replayed_step_of_a_trigger_with_no_event_kind_is_refused(rig: Rig) -> None:
    """A step whose trigger has no write-ahead kind is no step of the record."""
    order = await rig.submitted()
    o = rig.facade._orders[order.id]
    history = await _history(rig, order)
    o.replaying = deque(replay_plan(history[-1:], LEGALITY.triggers))
    step = b01.Step(str(order.id), str(ACCOUNT), None, "submitting", "submitted", "NOPE", {}, {})
    with pytest.raises(OrderHistoryRefused, match="left the record at seq 2"):
        await rig.facade._persist(step)
    o.replaying = None


async def test_a_replayed_step_that_does_not_commit_in_time_is_refused(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded answer the replay never gets (here none is seeded) is refused once
    `REPLAY_STEP_TIMEOUT` passes, and pages, never left waiting."""
    order = await _partial(rig)
    _state, _context, again = await _crashed(rig, order)
    monkeypatch.setattr("candleviewer.oms.order_machine.recorded_outcomes", lambda _plan: {})
    monkeypatch.setattr("candleviewer.oms.order_machine.REPLAY_STEP_TIMEOUT", 0.0)
    try:
        with pytest.raises(OrderHistoryRefused, match="seq 2 did not commit"):
            await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        assert again.facade.state(order.id) is None and again.commands.sent == []
        assert again.pager.calls == ["oms_order_history_refused"]
    finally:
        await again.facade.stop()


async def test_a_history_is_read_page_by_page_and_bounded(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.18: the history is read in pages, whole; past `MAX_HISTORY` events it is refused
    rather than read in part."""
    order = await _amended(rig)
    _state, context, again = await _crashed(rig, order)
    monkeypatch.setattr("candleviewer.oms.order_machine.MAX_EVENT_PAGE", 2)
    try:
        await again.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await again.quiet()
        assert again.context(order) == context  # six events, in three pages
        final = await again.restart()
        monkeypatch.setattr("candleviewer.oms.order_machine.MAX_HISTORY", 3)
        with pytest.raises(OrderHistoryRefused, match="more than 3 events"):
            await final.facade.hydrate(ACCOUNT, order.id, environment="demo")
        await final.facade.stop()
    finally:
        await again.facade.stop()


# --- The replay plan: B1's static table names each recorded step's trigger ------------------------


_ORDER = {"order_id": str(UUID(int=1)), "account_id": str(ACCOUNT), "symbol": "BTCUSDT"}
_ORDER |= {"order_link_id": "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-01en", "side": "buy", "qty": "1"}
_EXEC = fill_of(order_of(), "e1", "0.1")
#: A payload each trigger's closed schema takes (a service's result: its result).
_SAMPLE: dict[str, dict[str, Any]] = {
    "VALIDATE": {"gates": {}, "order": _ORDER},
    "DISCOVERED": {"order": _ORDER | {"exchange_order_id": "x7"}},
    "SEND": {}, "CANCEL": {}, "ADOPT": {}, "AMEND": {"price": "64000"},
    "TRIGGERED": {"updated_time": 1}, "MISMATCH": {"exchange_order_id": "x9"},
    "AMEND_REJECTED": {"error_code": "PRICE_OUT_OF_BOUNDS"},
    "TRANSPORT_FAULT": {"reason": "socket closed"}, "FAULT": {"reason": "OM-T04"},
    "RECON_FOUND_LIVE": {"exchange_order_id": "x1"}, "RECON_FOUND_PARTIAL": {"execution": _EXEC},
    "RECON_MISS": {"pass_id": "p1"}, "EXEC": _EXEC,
    "done.invoke.place": {"ok": True, "exchange_order_id": "x1"},
    "done.invoke.cancel": {"ok": False, "error_code": "EXCHANGE_UNKNOWN"},
    "done.invoke.amend": {"ok": True, "terms": {"price": "64000"}},
    **{f"error.platform.{i}": {"error": "TimeoutError"} for i in ("place", "cancel", "amend")},
}  # fmt: skip


def _recorded(source: str, target: str, trigger: str, payload: dict[str, Any]) -> OrderEventRow:
    """The event B1's step writer would store for *trigger* from *source* into *target*."""
    step = b01.Step(None, None, None, source, target, trigger, payload, {})
    kind, origin = event_kind(step)
    stored = cast(Mapping[str, OrderState], ORDER_STATE_OF)
    frm = None if source == "draft" else stored[source]
    return OrderEventRow(
        1, UUID(int=1), "l", 1, kind, frm, stored[target], origin, payload, None, None, None, T0, T0
    )


#: Each edge into a state that is not final, and each trigger of it.
_EDGES = sorted(
    (source, target, trigger)
    for (source, target), triggers in LEGALITY.triggers.items()
    if target not in LEGALITY.finals
    for trigger in triggers
)


@pytest.mark.parametrize(("source", "target", "trigger"), _EDGES)
def test_every_recorded_step_names_its_trigger(source: str, target: str, trigger: str) -> None:
    """Hydration replays a step by the one trigger of B1's table that writes it: its states, kind
    and source, and a payload its closed schema takes. Every edge into a state an order can rest
    in is covered, so any history of a live order replays."""
    sample = _SAMPLE[trigger]
    if (target, trigger) == ("unknown", "done.invoke.place"):
        sample = {"ok": False, "error_code": "DUPLICATE_CLIENT_ID"}
    elif (target, trigger) == ("held", "done.invoke.place"):
        sample = {"ok": False, "error_code": "DUPLICATE_CLIENT_ID", "lookup": {"x": "y"}}
    (planned,) = replay_plan([_recorded(source, target, trigger, sample)], LEGALITY.triggers)
    assert (planned.trigger, planned.state, planned.answered) == (
        trigger,
        target,
        trigger.startswith(("done.", "error.")),
    )


@pytest.mark.parametrize(
    ("payload", "trigger"),
    [({"error_code": "PRICE_OUT_OF_BOUNDS", "source": "rest"}, "AMEND_REJECTED"),
     ({"ok": False, "error_code": "PRICE_OUT_OF_BOUNDS", "terms": {"price": "1"}},
      "done.invoke.amend")],
)  # fmt: skip
def test_an_exchange_fact_and_a_result_written_alike_are_told_apart(
    payload: dict[str, Any], trigger: str
) -> None:
    """An `AMEND_REJECTED` the REST path reported and an `amend` result write the same kind and
    source: the fact is the one whose closed schema takes the payload."""
    row = _recorded("amend_pending", "submitted", trigger, payload)
    (planned,) = replay_plan([row], LEGALITY.triggers)
    assert planned.trigger == trigger


def test_a_trigger_with_no_write_ahead_kind_is_no_candidate() -> None:
    """A table entry the step writer could never have written is passed over, not raised."""
    row = _recorded("submitted", "triggered", "TRIGGERED", {"updated_time": 1})
    table = {("submitted", "triggered"): frozenset({"NOPE", "TRIGGERED"})}
    assert [step.trigger for step in replay_plan([row], table)] == ["TRIGGERED"]


def test_a_step_no_single_trigger_writes_is_refused() -> None:
    """Only an edge into a final state is written alike by two triggers (a `RECON_MISS` and a
    `RECON_FOUND_CANCELLED` ending an `untracked` order); a final order is never replayed."""
    row = _recorded("untracked", "cancelled", "RECON_MISS", {"pass_id": "p1"})
    with pytest.raises(OrderHistoryRefused, match="no single B1 trigger"):
        replay_plan([row], LEGALITY.triggers)
    with pytest.raises(OrderHistoryRefused, match="no single B1 trigger"):
        replay_plan([replace(row, kind="ack")], LEGALITY.triggers)


@pytest.mark.parametrize(
    ("path", "want"),
    [("amended", {"place:1": {"ok": True, "exchange_order_id": "x1"},
                  "amend:4": {"ok": True, "exchange_order_id": "x1", "terms": {"price": "64000"}}}),
     ("unknown", {"place:1": "TimeoutError"})],
)  # fmt: skip
async def test_each_recorded_answer_is_keyed_as_b1_keys_its_attempt(
    rig: Rig, path: str, want: dict[str, Any]
) -> None:
    """`<invoke id>:<seq of the step that entered its state>`: a result as recorded, or the class
    of what the call raised."""
    order = await LIVE[path][0](rig)
    plan = replay_plan(await _history(rig, order), LEGALITY.triggers)
    assert recorded_outcomes(plan) == want


# --- The fold refuses a history it cannot read ----------------------------------------------------


def _with(history: list[OrderEventRow], seq: int, **changes: Any) -> list[OrderEventRow]:
    return [replace(e, **changes) if e.seq == seq else e for e in history]


_BROKEN: dict[str, Callable[[list[OrderEventRow]], list[OrderEventRow]]] = {
    "empty": lambda h: [],
    "no_first": lambda h: h[1:],
    "gap": lambda h: h[:2] + h[3:],
    "not_b1s_first": lambda h: _with(h, 0, kind="ack"),
    "first_names_no_order": lambda h: _with(h, 0, payload={"gates": {}}),
    "first_names_another": lambda h: _with(h, 0, order_id=UUID(int=9)),
    "first_money_float": lambda h: _with(h, 0, payload={"order": _ORDER | {"qty": 1.0}}),
    "first_no_side": lambda h: _with(h, 0, payload={"order": _ORDER | {"side": "long"}}),
    "first_no_reduce_only": lambda h: _with(h, 0, payload={"order": _ORDER | {"reduce_only": 1}}),
    "first_no_account": lambda h: _with(h, 0, payload={"order": _ORDER | {"account_id": "x"}}),
    "first_no_link": lambda h: _with(h, 0, payload={"order": _ORDER | {"order_link_id": ""}}),
    "first_from_a_state": lambda h: _with(h, 0, from_state="new"),
    "unchained": lambda h: _with(h, 2, from_state="unknown"),
    "fill_twice": lambda h: [*h, replace(h[-1], seq=len(h), from_state=h[-1].to_state)],
    "fill_past_qty": lambda h: _with(h, 3, payload=_EXEC | {"qty": "5"}),
    "fill_unnamed": lambda h: _with(h, 3, payload=_EXEC | {"exec_id": None}),
    "left_final": lambda h: [
        *h,
        replace(h[-1], seq=len(h), kind="reconcile_diff", from_state="filled", to_state="held"),
    ],
}


@pytest.mark.parametrize("broken", sorted(_BROKEN))
async def test_a_history_the_fold_cannot_read_is_refused(rig: Rig, broken: str) -> None:
    """OM-T03, INV-2, S4, OM-T04: a gap, a step that leaves no state the order held, a first event
    B1 did not write, a fill applied twice or past `qty`, or a step out of a final state."""
    order = await (_filled if broken == "left_final" else _partial)(rig)
    history = list(await _history(rig, order))
    with pytest.raises(OrderHistoryRefused):
        rebuild(_BROKEN[broken](history))


async def test_an_event_with_no_step_moves_nothing(rig: Rig) -> None:
    """`OrderEventStore.append` writes an event with no state change; the fold reads past it."""
    order = await _partial(rig)
    said = NewOrderEvent(kind="error", source="local", event_ts=T0, payload={"note": "probe"})
    await rig.events.append(ACCOUNT, order.id, said)
    assert rebuild(await _history(rig, order)) == await _row(rig, order)


async def test_an_amend_the_machine_did_not_adopt_changes_no_term(rig: Rig) -> None:
    """`adopt_amend`, all or none: an accepted amend under the filled quantity (INV-1), or one
    naming a term that is no money above zero, keeps the prior terms in the fold too."""
    order = await _amended(rig)
    history = list(await _history(rig, order))
    for terms in ({"qty": "0.1"}, {"price": "0"}, {"price": 64000}, "not terms"):
        changed = rebuild(_with(history, 5, payload={"ok": True, "terms": terms}))
        assert (changed.qty, changed.price) == (Decimal(1), Decimal(63000))
