"""The OMS facade's E29-T04 edits (#913, slice 2a), on the real B1 binding over the in-memory
stores: `start(first=...)` reaches the step writer's first persist, a refused step's `__cause__`
is a typed OMS error and never a foreign one, the native-stop backstop is logged and counted, the
`oms_unknown_orders` gauge follows the live machines, and `abandon` ends a never-sent order.
Slice 2b: `settled`, the pipeline's wait on the create's outcome, which follows a resync and reads
the row of an order whose machine is gone. Slice 4 (S4-B1): `version`, the order's last step's
`event_seq`, and `command(expected_seq=)`, checked under the order's lock after every other gate,
and a cancel through the real command port, landing where B1 says."""

from __future__ import annotations

import asyncio
import dataclasses
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms.errors import (
    AnchorTaken,
    IllegalTransition,
    OrderNotLoaded,
    OrderStepRefused,
    VersionConflict,
)
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.oms.repository import SubmissionRepository
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.idempotency_anchors import NewAnchor
from candleviewer.storage.repositories.orders import NewOrder, NewOrderEvent
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms.order_rig import (
    ACCOUNT,
    GATES,
    OTHER,
    T0,
    Rig,
    build_rig,
    fill_of,
    gated,
    order_of,
    placed,
)


async def _audited(persisted: FirstPersisted) -> None:
    return None  # the pipeline's write-ahead audit (C-2.9, CR-2A-02)


_FIRST = FirstPersist(
    anchor=NewAnchor(id=UUID(int=0xF1), created_by=UUID(int=0xB1), operation="placeOrder",
                     client_ref="9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59", request_sha256="ab" * 32,
                     order_id=UUID(int=1)),
    write_ahead=_audited,
)  # fmt: skip


class _Submissions:
    """A `SubmissionStore` that stores the order on the rig's store, or raises `error`."""

    def __init__(self, store: InMemoryOrderStore, error: Exception | None = None) -> None:
        self.store, self.error = store, error
        self.firsts: list[FirstPersist] = []

    async def create_first(
        self, first: FirstPersist, order: NewOrder, event: NewOrderEvent
    ) -> FirstPersisted:
        self.firsts.append(first)
        if self.error is not None:
            raise self.error
        row = await self.store.create(order, event)
        return FirstPersisted(order=row, anchor_id=first.anchor.id, group=None, recorded_stops=())


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = build_rig()
    yield out
    await out.facade.stop()


async def _rigged(monkeypatch: pytest.MonkeyPatch, error: Exception | None = None) -> tuple[
    Rig, _Submissions
]:  # fmt: skip
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    store = InMemoryOrderStore(clock=lambda: T0)
    submissions = _Submissions(store, error)
    return build_rig(store, submissions=SubmissionRepository(submissions)), submissions


async def test_start_hands_its_first_persist_to_the_step_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_first` registers the order itself, so a caller's own `expect` would be overwritten:
    `start(first=...)` is the one way in (R7)."""
    rig, submissions = await _rigged(monkeypatch)
    try:
        state = await rig.facade.start(order_of(), environment="demo", gates=GATES, first=_FIRST)
        assert state == "validated" and submissions.firsts == [_FIRST]
        assert await rig.orders.get(ACCOUNT, UUID(int=1)) is not None
    finally:
        await rig.facade.stop()


async def test_a_refused_step_names_a_typed_oms_error_as_its_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pipeline reads `AnchorTaken` (and `DuplicateOrderLinkId`) off `__cause__`; they name
    no value (C-12.6)."""
    rig, _ = await _rigged(monkeypatch, AnchorTakenError("ux_ia_principal_ref"))
    try:
        with pytest.raises(OrderStepRefused) as err:
            await rig.facade.start(order_of(), environment="demo", gates=GATES, first=_FIRST)
        assert isinstance(err.value.__cause__, AnchorTaken)
        assert err.value.__cause__.constraint == "ux_ia_principal_ref"
        assert await rig.orders.get(ACCOUNT, UUID(int=1)) is None
    finally:
        await rig.facade.stop()


async def test_a_foreign_error_is_never_chained(rig: Rig) -> None:
    """A driver's or a store's own error could carry values: the refusal names its class only."""
    rig.store.fail_next(RuntimeError("Postgres is down"))
    with pytest.raises(OrderStepRefused) as err:
        await rig.start()
    assert err.value.__cause__ is None and err.value.failure == "RuntimeError"


async def test_the_native_stop_backstop_is_logged_and_counted_once(rig: Rig) -> None:
    """C-2.6: an entry with no stop is refused at `VALIDATE` whatever its gates said; the caller
    that sent it has a defect, so it pages. A reduce-only order is no entry."""
    with capture_logs() as logs:
        state = await rig.start(order_of(stop_loss=None))
    assert state == "rejected" and rig.count("oms_native_stop_backstop_total") == 1
    [line] = [line for line in logs if line["event"] == "oms_native_stop_backstop"]
    link = order_of().order_link_id
    assert line == {"event": "oms_native_stop_backstop", "log_level": "error",
                    "order_link_id": link, "symbol": "BTCUSDT"}  # fmt: skip
    await rig.start(order_of(2, stop_loss=None, reduce_only=True, intent="flatten"))
    assert rig.count("oms_native_stop_backstop_total") == 1


async def test_a_first_step_the_chart_refuses_leaves_no_registration(rig: Rig) -> None:
    """A verdict-refused entry (`draft -> rejected`) writes no row, so the writer never spends
    its registration; `_first` drops it, so a refused request's key and audit hook do not wait
    for eviction (C-2.18)."""
    state = await rig.start(order_of(stop_loss=None))
    assert state == "rejected"
    assert order_of().id not in rig.facade._ports.steps._expected  # the writer's registrations


async def _unknown(rig: Rig) -> NewOrder:
    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    rig.commands.on_place = ambiguous
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    return order


async def test_the_unknown_gauge_follows_the_live_machines(rig: Rig) -> None:
    """R13: an order in `unknown` counts while its machine lives, and stops counting when it
    leaves the state or its machine is evicted."""
    order = await _unknown(rig)
    assert rig.count("oms_unknown_orders") == 1
    found = {"exchange_order_id": "x1"}
    await rig.facade.command(ACCOUNT, order.id, "RECON_FOUND_LIVE", found, actor="system")
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert rig.count("oms_unknown_orders") == 0
    await _unknown_again(rig)
    assert rig.count("oms_unknown_orders") == 1
    await rig.facade.stop()
    assert rig.count("oms_unknown_orders") == 0


async def _unknown_again(rig: Rig) -> None:
    order = order_of(2)
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")


async def test_abandon_kills_a_never_sent_order_and_sends_nothing(rig: Rig) -> None:
    """S2-Q5: B1's KILL from `validated` cancels nothing, as nothing was sent, and is audited."""
    order = order_of()
    await rig.start(order)
    assert await rig.facade.abandon(ACCOUNT, order.id, "submitting row refused") == "killed"
    assert rig.commands.sent == [] and rig.facade.state(order.id) is None
    assert "kill_no_cancel_unsubmitted" in rig.audit.reasons("orders.cancel")
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and (row.state, row.submit_attempts) == ("killed", 0)


async def test_abandon_refuses_an_order_that_left_validated(rig: Rig) -> None:
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    sent = list(rig.commands.sent)
    with pytest.raises(IllegalTransition):
        await rig.facade.abandon(ACCOUNT, order.id, "late")
    assert rig.commands.sent == sent and rig.facade.state(order.id) == ("submitted", "not_required")


async def test_abandon_refuses_an_order_already_ended(rig: Rig) -> None:
    """With no machine left, the row decides: an order that ended is refused as ended."""
    order = order_of()
    await rig.start(order)
    assert await rig.facade.abandon(ACCOUNT, order.id, "submitting row refused") == "killed"
    with pytest.raises(IllegalTransition):
        await rig.facade.abandon(ACCOUNT, order.id, "again")


async def test_abandon_follows_a_machine_a_resync_closed_while_it_waited(rig: Rig) -> None:
    """The resync hand-over (`successor`): an abandon that waited on the order's lock while its
    machine was closed follows to the rebuilt one; with none rebuilt it reads the row and kills
    nothing blind."""
    order = order_of()
    await rig.start(order)
    o = rig.facade._orders[order.id]
    async with o.lock:
        call = asyncio.create_task(rig.facade.abandon(ACCOUNT, order.id, "submitting row refused"))
        for _ in range(64):
            await asyncio.sleep(0)
        assert not call.done()
        await rig.facade._close(o, publish=False)  # as `_resync` does before it hydrates
    with pytest.raises(OrderNotLoaded):
        await call
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.state == "pending_submit" and rig.commands.sent == []


async def test_abandon_never_reaches_another_accounts_order(rig: Rig) -> None:
    order = order_of()
    await rig.start(order)
    with pytest.raises(OrderNotLoaded):
        await rig.facade.abandon(OTHER, order.id, "not mine")
    assert rig.facade.state(order.id) == ("validated", "not_required")


async def test_the_attempt_is_committed_before_the_create_leaves(rig: Rig) -> None:
    """The orchestrator's rulings of 14:26Z (write-ahead): B1 arms `submitting`'s place only once
    that state's entry committed its step, so when the create leaves, the stored order counts its
    attempt and marks the create in flight, and a crash between the two leaves the attempt
    counted. A refused write sends nothing and counts nothing, so an order with no attempt counted
    was never sent, and `abandon` may void its stops (21 Sec.3.3.11's table)."""
    seen: list[tuple[str, int, str]] = []

    async def place(command: b01.Command) -> Mapping[str, Any]:
        row = await rig.orders.get(ACCOUNT, UUID(command.order["order_id"]))
        assert row is not None
        seen.append((row.state, row.submit_attempts, row.idempotency_state))
        return await placed(command)

    rig.commands.on_place = place
    sent = order_of()
    await rig.start(sent)
    await rig.facade.command(ACCOUNT, sent.id, "SEND", actor="user")
    await rig.quiet()
    assert seen == [("submitted", 1, "in_flight")]  # `submitting`, stored before the create
    refused = order_of(2)
    await rig.start(refused)
    rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
    with pytest.raises(OrderStepRefused):
        await rig.facade.command(ACCOUNT, refused.id, "SEND", actor="user")
    await rig.quiet()
    assert len(seen) == 1 and rig.commands.kinds().count("place") == 1  # nothing else left
    row = await rig.orders.get(ACCOUNT, refused.id)
    assert row is not None
    unsent = ("pending_submit", 0, "unsent")
    assert (row.state, row.submit_attempts, row.idempotency_state) == unsent
    assert await rig.facade.abandon(ACCOUNT, refused.id, "submitting row refused") == "killed"


# --- settled: the pipeline's wait on the create's outcome (E29-T04 slice 2b) ----------------------


async def _sending(rig: Rig) -> tuple[NewOrder, asyncio.Event]:
    """An order sent, its create held unanswered: the machine rests in `submitting`."""
    gate, held = gated({"ok": True, "exchange_order_id": "x1"})
    rig.commands.on_place = held
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    assert rig.facade.state(order.id) == ("submitting", "not_required")
    return order, gate


async def test_settled_answers_once_the_order_leaves_the_state(rig: Rig) -> None:
    """Each committed step wakes the wait (`moved`); it answers the state the order left for."""
    order, gate = await _sending(rig)
    waiting = asyncio.create_task(
        rig.facade.settled(ACCOUNT, order.id, leaving="submitting", timeout_s=5.0)
    )
    for _ in range(64):
        await asyncio.sleep(0)
    assert not waiting.done()
    gate.set()
    assert await waiting == "submitted"


async def test_settled_answers_at_once_for_an_order_already_past_the_state(rig: Rig) -> None:
    order = await rig.submitted()
    settled = await rig.facade.settled(ACCOUNT, order.id, leaving="submitting", timeout_s=1.0)
    assert settled == "submitted"


async def test_settled_times_out_while_the_order_stays(rig: Rig) -> None:
    order, gate = await _sending(rig)
    with pytest.raises(TimeoutError):
        await rig.facade.settled(ACCOUNT, order.id, leaving="submitting", timeout_s=0.01)
    gate.set()
    await rig.quiet()


async def test_settled_reads_the_row_of_an_order_whose_machine_is_gone(rig: Rig) -> None:
    """An order final and evicted (MUST-11) is answered from its row; another account's order,
    or none, is not found (C-12.4)."""

    async def refused(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False, "error_code": "INSUFFICIENT_MARGIN", "exchange_ret_code": 110007}

    rig.commands.on_place = refused
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) is None
    settled = await rig.facade.settled(ACCOUNT, order.id, leaving="submitting", timeout_s=1.0)
    assert settled == "rejected"
    with pytest.raises(OrderNotLoaded):
        await rig.facade.settled(OTHER, order.id, leaving="submitting", timeout_s=1.0)


async def test_settled_follows_a_resync_to_the_machine_it_rebuilt(rig: Rig) -> None:
    """A wait that met the machine a resync closed waits on its lock, then follows the order to
    the rebuilt one (`successor`), whose resumed create answers it."""
    order, gate = await _sending(rig)
    o = rig.facade._orders[order.id]
    async with o.lock:
        waiting = asyncio.create_task(
            rig.facade.settled(ACCOUNT, order.id, leaving="submitting", timeout_s=5.0)
        )
        for _ in range(64):
            await asyncio.sleep(0)
        await rig.facade._resync(o)  # under the order's lock, as `_settle_one` runs it
        assert o.successor is not None and not waiting.done()
    gate.set()
    assert await waiting == "submitted"


async def test_settled_reads_the_row_of_a_machine_closed_while_in_the_state(rig: Rig) -> None:
    """A machine closed by no resync, its order still in the state (a shutdown): the row decides."""
    order, gate = await _sending(rig)
    o = rig.facade._orders[order.id]
    waiting = asyncio.create_task(
        rig.facade.settled(ACCOUNT, order.id, leaving="submitting", timeout_s=5.0)
    )
    for _ in range(64):
        await asyncio.sleep(0)
    async with o.lock:
        await rig.facade._close(o, publish=False)
    assert await waiting == "submitting"
    gate.set()


# --- the version (E29-T04 S4-B1; the S4 ruling Q5's `ETag`): `version`, `command(expected_seq=)` --


async def test_the_version_is_the_last_steps_seq_and_follows_each_step_a_fill_included(
    rig: Rig,
) -> None:
    """Q5: the seq of `"<orderId>:<seq>"` is the `event_seq` of the order's last committed step,
    its last `order_events` row: each step moves it, a fill included, and an order with no
    machine (none yet, or evicted once final) has none."""
    order = order_of()
    assert rig.facade.version(order.id) is None
    await rig.start(order)
    seen = [rig.facade.version(order.id)]
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    seen.append(rig.facade.version(order.id))
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
    seen.append(rig.facade.version(order.id))
    events = await rig.events.list_for_order(ACCOUNT, order.id)
    assert seen == [0, 2, 3] and [event.seq for event in events] == [0, 1, 2, 3]
    await rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e2", "0.6"))
    await rig.quiet()
    assert rig.facade.state(order.id) is None and rig.facade.version(order.id) is None


async def test_a_stale_expected_seq_is_a_conflict_with_nothing_sent_written_or_moved(
    rig: Rig,
) -> None:
    """Q5: after every other gate (legality first: 409 and 422 before 412), a version that has
    moved on refuses the command with `VersionConflict`, nothing sent or written; the current one
    admits it."""
    unsent = order_of(2)
    await rig.start(unsent)
    with pytest.raises(IllegalTransition):
        await rig.facade.command(ACCOUNT, unsent.id, "CANCEL", actor="user", expected_seq=99)
    order = await rig.submitted()
    seq = rig.facade.version(order.id)
    assert seq is not None
    with capture_logs() as logs, pytest.raises(VersionConflict):
        await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user", expected_seq=seq - 1)
    assert [log["event"] for log in logs] == ["oms_version_conflict"]
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    assert rig.facade.version(order.id) == seq and "cancel" not in rig.commands.kinds()
    await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user", expected_seq=seq)
    await rig.quiet()
    row = await rig.orders.get(ACCOUNT, order.id)
    assert row is not None and row.lifecycle_state == "cancelled"
    assert rig.commands.kinds().count("cancel") == 1


async def test_the_version_is_checked_under_the_orders_lock(rig: Rig) -> None:
    """Q5's atomic home: a command that read the version, then waited on the order's lock while
    a fill committed, meets the new version once it holds the lock, and sends nothing."""
    order = await rig.submitted()
    seq = rig.facade.version(order.id)
    o = rig.facade._orders[order.id]
    async with o.lock:
        fill = asyncio.create_task(
            rig.facade.push(ACCOUNT, order.id, "EXEC", fill_of(order, "e1", "0.4"))
        )
        cancel = asyncio.create_task(
            rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user", expected_seq=seq)
        )
        for _ in range(64):
            await asyncio.sleep(0)
        assert not fill.done() and not cancel.done()
    await fill
    with pytest.raises(VersionConflict):
        await cancel
    assert seq is not None and rig.facade.version(order.id) == seq + 1
    assert "cancel" not in rig.commands.kinds()


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[Rig, cr.Rig]]:
    """The facade on the real command port over the fake venue (`command_rig`), one store."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    venue = cr.build_rig()
    out = build_rig(venue.store)
    b01.set_ports(dataclasses.replace(b01._ports, commands=venue.port))  # `stop()` unwires it
    yield out, venue
    await out.facade.stop()


@pytest.mark.parametrize(
    ("venue_answer", "landed"),
    [(None, "cancelled"), (FakeReject(OmsErrorCode.ORDER_NOT_FOUND, 110001), "submitted"),
     (cr.outage(), "unknown")],
    ids=["accepted", "refused", "raised"],
)  # fmt: skip
async def test_a_cancel_through_the_port_lands_where_b1_says_and_answers_its_watch(
    wired: tuple[Rig, cr.Rig], venue_answer: Any, landed: str
) -> None:
    """S4-B1 end to end on the facade: the current version admits the exit's `CANCEL`, B1's
    `cancel_pending` sends it once through the real port, and the order lands `cancelled`, back
    live on a refusal (INV-B1-j), or `unknown` when the call raised (Q11), never sent again; the
    watch answers what B1 was answered, None on the raise."""
    rig, venue = wired
    order = cr.new_order()
    venue.port.expect(order)
    await rig.facade.start(order, environment="demo", gates=GATES)
    await rig.facade.command(cr.ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    if venue_answer is not None:
        venue.demo.script("cancel_order", venue_answer)
    watch = venue.port.expect_exit(order.id, "cancel")
    seq = rig.facade.version(order.id)
    await rig.facade.command(cr.ACCOUNT, order.id, "CANCEL", actor="user", expected_seq=seq)
    answer = await watch.answer()
    await rig.quiet()
    row = await venue.orders.get(cr.ACCOUNT, order.id)
    assert row is not None and row.lifecycle_state == landed
    assert venue.calls().count("cancel_order") == 1
    assert (answer is None) == (landed == "unknown")
