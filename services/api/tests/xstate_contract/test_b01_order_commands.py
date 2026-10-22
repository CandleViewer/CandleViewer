"""B1 `order` over the OMS's command port (E29-T04 #913): the machine the factory builds, its
`place` and `lookup` answered by `OmsCommandPort` over `FakeTradingPort`, so each answer the port
gives lands the order where 24-internal-schemas.md Sec.8.3, Sec.8.4 and Sec.8.6 say it lands.

- An accepted create that names no order id the OMS keeps is `unknown` (ruling 3 on #3972).
- A duplicate whose lookup fully matches is `submitted` and bound, its adoption audited ahead; one
  that does not is `held`, after the hand-over, and `unknown` when no hand-over can be recorded
  (`NoHandoverStore`, S2-Q3).
- A refused rate token is `rejected` with `RATE_BUDGET_EXCEEDED`, never `unknown` (24 Sec.8.7).
- A create that landed and then went unanswered is `unknown` after one call (SR-E29-15), and so is
  one the venue's outage answers (#2863): raised, never a refusal.
- A create a restart resumes is looked up before it is sent, under the same id and stop; on live,
  one older than `LIVE_RESEND_MAX_AGE_S` is never sent: within the venue's 24 h history it ends
  `rejected` with `EXPIRED_UNSENT` ([LANE-26]), and at or past it, where a miss proves nothing,
  `unknown` (SEC-2B1-02); a re-send met by a duplicate is bound through B1's lookup, never a new
  id.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.base.fakes import LandedThenAmbiguous
from candleviewer.exchange.base.models import Order, OrderAck, PlaceOrderRequest
from candleviewer.oms import ExecutionRepository
from candleviewer.oms.commands import found_view
from candleviewer.oms.execution import apply_fields
from candleviewer.oms.fakes import InMemoryExecutionStore
from candleviewer.oms.order_machine import _order_fields
from candleviewer.oms.order_steps import OrderStepWriter, entry_stop_settle
from candleviewer.oms.ports import NoHandoverStore, OrderHandovers
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.orders import LifecycleState, NewOrder
from tests.unit.oms.command_rig import (
    ACCOUNT,
    LIVE_ACCOUNT,
    STOP,
    T0,
    T0_US,
    UIDS,
    Handovers,
    Rig,
    build_rig,
    exchange_order,
    new_order,
    outage,
)
from tests.xstate_contract._harness import Charts, park, settle

CHART = Registry().get("order")


@dataclass
class TrailHandovers(Handovers):
    """`Handovers` that also marks each hand-over in the book's trail."""

    trail: list[tuple[str, str]] = field(default_factory=list)

    async def hand_over_order(self, account_id: AccountId, order: Order) -> None:
        await super().hand_over_order(account_id, order)
        self.trail.append(("handed", order.exchange_order_id))


@dataclass
class Book:
    """The OMS side of one test: the command rig, the step writer over its order store, the
    trail of each row written, and the steps themselves."""

    rig: Rig
    writer: OrderStepWriter
    trail: list[tuple[str, str]]
    steps: list[b01.Step] = field(default_factory=list)

    async def persist(self, step: b01.Step) -> int:
        seq = await self.writer(step)
        self.trail.append(("written", step.to_state))
        self.steps.append(step)
        return seq


def _settles(step: b01.Step) -> str | None:
    """What the step writer does to an entry's attach rows on `step`, nothing filled (21
    Sec.3.3.11's table, `entry_stop_settle`): `void`, `answered`, `waiting`, or None, nothing."""
    frm, to = cast(LifecycleState, step.from_state), cast(LifecycleState, step.to_state)
    return entry_stop_settle(frm, to, Decimal(0), trigger=step.event)


def _book(monkeypatch: pytest.MonkeyPatch, handovers: OrderHandovers | None = None) -> Book:
    trail: list[tuple[str, str]] = []
    rig = build_rig(handovers=handovers if handovers is not None else TrailHandovers(trail=trail))
    executions = ExecutionRepository(InMemoryExecutionStore(rig.store))
    book = Book(rig, OrderStepWriter(rig.orders, executions, clock=lambda: T0), trail)
    ports = b01.OrderPorts(persist=book.persist, commands=rig.port, now_us=rig.now)
    monkeypatch.setattr(b01, "_ports", ports)
    monkeypatch.setattr(b01, "_core", apply_fields)
    return book


@asynccontextmanager
async def _machine(charts: Charts) -> AsyncIterator[Any]:
    """B1 on the library with its real bindings, parked at `draft`, through the factory."""
    built = await park("order", CHART, "lifecycle.draft", charts)
    try:
        yield built.interpreter
    finally:
        await built.interpreter.stop()


async def _send(interp: Any, event: str, **payload: Any) -> None:
    await interp.send(event, wait=True, **payload)
    await settle()


async def _submit(book: Book, interp: Any, order: NewOrder) -> str | None:
    """The pipeline's two steps (24 Sec.8.4): `VALIDATE` with every gate passed, then, once the
    order is registered with the command port, `SEND`. Answers the lifecycle leaf."""
    book.writer.expect(order)
    gates = dict.fromkeys(b01.GATES, b01.PASSED)
    await _send(interp, "VALIDATE", gates=gates, order=_order_fields(order))
    book.rig.port.expect(order)
    await _send(interp, "SEND")
    return b01._leaf(interp)


async def test_an_accepted_create_naming_no_order_id_is_unknown(
    monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    book = _book(monkeypatch)
    order = new_order()

    async def unnamed(_request: PlaceOrderRequest) -> OrderAck:
        return OrderAck(
            ok=True,
            order_link_id=order.order_link_id,
            exchange_order_id=" ",
            latency_ms=0,
            transport="rest",
        )

    monkeypatch.setattr(book.rig.demo, "place_order", unnamed)
    async with _machine(charts) as interp:
        assert await _submit(book, interp, order) == "unknown"
        assert interp.context["exchange_order_id"] is None
    row = await book.rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.lifecycle_state == "unknown"


async def test_a_duplicate_that_fully_matches_is_submitted_bound_and_audited(
    monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    book = _book(monkeypatch)
    order = new_order()
    held = exchange_order(order)
    book.rig.demo.seed_order(held, uid=UIDS["demo"])
    async with _machine(charts) as interp:
        assert await _submit(book, interp, order) == "submitted"
        assert interp.context["exchange_order_id"] == held.exchange_order_id
    assert book.rig.calls() == ["place_order", "open_orders"]
    assert book.rig.audits.actions() == [("orders.submit", "adopted_after_lookup")]


async def test_a_duplicate_that_does_not_match_is_held_after_the_hand_over(
    monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    book = _book(monkeypatch)
    order = new_order()
    squatter = exchange_order(order, qty=Decimal("0.5"))
    book.rig.demo.seed_order(squatter, uid=UIDS["demo"])
    async with _machine(charts) as interp:
        assert await _submit(book, interp, order) == "held"
        assert interp.context["exchange_order_id"] is None
    handed = book.trail.index(("handed", squatter.exchange_order_id))
    assert handed < book.trail.index(("written", "held"))
    assert book.rig.audits.written == []


async def test_no_handover_store_leaves_a_mismatch_unknown(
    monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    """S2-Q3: nothing can be handed over yet, so the order waits for reconciliation."""
    book = _book(monkeypatch, NoHandoverStore())
    order = new_order()
    book.rig.demo.seed_order(exchange_order(order, side="sell"), uid=UIDS["demo"])
    async with _machine(charts) as interp:
        assert await _submit(book, interp, order) == "unknown"
        assert interp.context["needs_lookup"] is True


async def test_a_refused_rate_token_is_rejected_never_unknown(
    monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    book = _book(monkeypatch)
    order = new_order()
    book.rig.demo.script("place_order", RateBudgetExceededError("no token", retry_after_s=1.5))
    async with _machine(charts) as interp:
        assert await _submit(book, interp, order) == "rejected"
        assert interp.context["reject_code"] == "RATE_BUDGET_EXCEEDED"


async def test_a_create_that_landed_then_went_unanswered_is_unknown_after_one_call(
    monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    book = _book(monkeypatch)
    order = new_order()
    book.rig.demo.script("place_order", LandedThenAmbiguous())
    async with _machine(charts) as interp:
        assert await _submit(book, interp, order) == "unknown"
    assert book.rig.calls() == ["place_order"]


def _resumed_context(order: NewOrder) -> dict[str, Any]:
    """B1's context for `order` in `submitting`, as a hydration leaves it: no attempt of this
    process (`b01._ATTEMPTS` is empty), so its `place` resumes."""
    stamped = b01._order(_order_fields(order))
    return stamped | {"filled_qty": "0", "exchange_order_id": None, "event_seq": 1}


@pytest.mark.parametrize("found", [False, True], ids=["resent", "adopted"])
async def test_a_restart_looks_the_id_up_before_it_sends(
    found: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-E29-15: B1 looks first; the port looks again whatever the switches say ([LANE-26]), and
    `adopt_or_resend` once more just before its one re-send, under the same id and stop (C-2.10,
    C-2.6); an order the venue holds is adopted, never sent again."""
    book = _book(monkeypatch)
    order = new_order()
    await book.rig.stored(order)
    if found:
        book.rig.demo.seed_order(exchange_order(order, state="filled"), uid=UIDS["demo"])
    result: Mapping[str, Any] = await b01.place_order(None, _resumed_context(order), None)
    lookups = ["open_orders", "order_history"]
    if found:
        assert book.rig.calls() == lookups
        assert result["lookup"] == found_view(exchange_order(order, state="filled"))
        return
    assert book.rig.calls() == [*lookups, *lookups, *lookups, "place_order"]
    request = book.rig.demo.calls[-1].request
    assert isinstance(request, PlaceOrderRequest)
    assert (request.order_link_id, request.stop_loss) == (order.order_link_id, STOP)
    assert result["ok"] is True


async def _sent_unregistered(book: Book, interp: Any, order: NewOrder) -> str | None:
    """`_submit` with no registration with the port, which answers the create as one a restart
    resumed (as after a registration `MAX_WATCHES` dropped). Answers the lifecycle leaf."""
    book.writer.expect(order)
    gates = dict.fromkeys(b01.GATES, b01.PASSED)
    await _send(interp, "VALIDATE", gates=gates, order=_order_fields(order))
    await _send(interp, "SEND")
    return b01._leaf(interp)


@pytest.mark.parametrize(("age_s", "leaf"), [(119, "submitted"), (121, "rejected")])
async def test_a_live_create_past_the_resend_bound_ends_rejected_with_its_reason(
    age_s: int, leaf: str, monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    """[LANE-26]: at 119 s the create no lookup found is re-sent and `submitted`; at 121 s nothing
    is sent, and `submitting`'s last arm, an existing terminal path, ends it `rejected`, its
    reason `EXPIRED_UNSENT` kept by `map_reject_code` and on the stored row, after its record and
    the user's alert."""
    book = _book(monkeypatch)
    order = new_order(LIVE_ACCOUNT, "live")
    book.rig.now.us = T0_US + age_s * 1_000_000
    async with _machine(charts) as interp:
        assert await _sent_unregistered(book, interp, order) == leaf
        reject_code = interp.context.get("reject_code")
    row = await book.rig.orders.get(LIVE_ACCOUNT, order.id)
    assert row is not None and row.lifecycle_state == leaf
    calls = book.rig.calls(book.rig.live)
    if leaf == "submitted":
        assert calls[-1] == "place_order" and book.rig.notices.got == []
        return
    assert reject_code == b01.EXPIRED_UNSENT == row.reject_code
    assert calls == ["open_orders", "order_history"]
    assert book.rig.audits.actions() == [("oms.resend_refused", "expired_unsent")]
    assert [notice.kind for notice in book.rig.notices.got] == ["alert"]
    assert _settles(book.steps[-1]) == "void"  # an entry never placed (21 Sec.3.3.11)


@pytest.mark.parametrize("age_s", [86_400, 30 * 86_400], ids=["exactly_the_span", "a_month"])
async def test_a_live_create_past_the_venues_history_is_unknown_never_rejected(
    age_s: int, monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    """SEC-2B1-02: at or past the venue's 24 h history a miss proves nothing, so the port answers
    an empty lookup and B1 lands the order in `unknown` for reconciliation: nothing sent, no
    `EXPIRED_UNSENT`, no record of the port's and no alert, and the step into `unknown` leaves
    its entry's attach rows as they are, never voided blind."""
    book = _book(monkeypatch)
    order = new_order(LIVE_ACCOUNT, "live")
    book.rig.now.us = T0_US + age_s * 1_000_000
    async with _machine(charts) as interp:
        assert await _sent_unregistered(book, interp, order) == "unknown"
        assert interp.context.get("reject_code") is None
    row = await book.rig.orders.get(LIVE_ACCOUNT, order.id)
    assert row is not None and (row.lifecycle_state, row.reject_code) == ("unknown", None)
    assert book.rig.calls(book.rig.live) == ["open_orders", "order_history"]
    assert book.rig.audits.written == [] and book.rig.notices.got == []
    step = book.steps[-1]
    assert (step.from_state, step.to_state, _settles(step)) == ("submitting", "unknown", None)


async def test_a_resend_met_by_a_duplicate_is_bound_through_b1s_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[LANE-26] step 3, the race after a missed lookup: the venue takes the earlier create just
    after every lookup missed it, so the one re-send meets a duplicate. The port answers a
    duplicate with no lookup, B1 looks the id up at once and binds the order on its full match:
    one create, under the same id, never a new one."""
    book = _book(monkeypatch)
    order = new_order()
    await book.rig.stored(order)
    landed, venue = exchange_order(order), book.rig.demo
    sent = venue.place_order

    async def lands_meanwhile(request: PlaceOrderRequest) -> OrderAck:
        venue.seed_order(landed, uid=UIDS["demo"])
        return await sent(request)  # the venue refuses the id as a duplicate

    monkeypatch.setattr(venue, "place_order", lands_meanwhile)
    context = _resumed_context(order)
    result: Mapping[str, Any] = await b01.place_order(None, context, None)
    assert result["lookup"] == found_view(landed)
    assert b01.is_duplicate_link_id_full_match(context, result)
    lookups = ["open_orders", "order_history"]
    assert book.rig.calls() == [*lookups, *lookups, *lookups, "place_order", "open_orders"]
    assert book.rig.audits.actions() == [("orders.submit", "adopted_after_lookup")]


async def test_a_create_the_venues_outage_answers_is_unknown_after_one_call(
    monkeypatch: pytest.MonkeyPatch, charts: Charts
) -> None:
    """#4092 (#2863): the outage reaches B1 raised, never mapped to a refusal, and the create is
    not sent again because the error says `retryable` (SEC-4092-02)."""
    book = _book(monkeypatch)
    order = new_order()
    book.rig.demo.script("place_order", outage(10016))
    async with _machine(charts) as interp:
        assert await _submit(book, interp, order) == "unknown"
        assert interp.context.get("reject_code") is None
    assert book.rig.calls() == ["place_order"]
