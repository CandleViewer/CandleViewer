"""#4587: a refused stop request's void record has a key of its own (C-2.9).

An amend records each side ahead, keyed `(sl.modified | tp.modified, <stop id>)` (`_record_amend`),
and its refusal, the venue's or for want of a rate token, voids the same rows under the same
actions (`_settle_stop`). A void keyed as its row's request would be deduped against it (the
writer's `ON CONFLICT (record_id) DO NOTHING`) and lost, the void row left with its request's
record alone. The settle names its voids by their reason, as the stop gate and the sweep name
theirs (`<reason>:<row id>`, 24 Sec.15.5), so no void's record id is any request's, and a settle
run again over the same rows names the same ids.

A user's amend holds the user on its rows, and its void names that user with the role, as its
request did: the runtime's adapter (`OmsAudit`) refuses a record that names a user without one,
and the settle would swallow that, its rows left in flight with no void recorded (CR-4609-01).
B1's attach has no user, so its void is the system's.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.writer import keyed_record_id
from candleviewer.exchange.base.errors import OmsErrorCode, RateBudgetExceededError, TransportError
from candleviewer.exchange.base.fakes import FakeOutcome, FakeReject
from candleviewer.exchange.base.models import AmendOrderRequest, OrderAck
from candleviewer.oms import commands as oc
from candleviewer.oms.ports import KeyedRecord, SubmitActor
from candleviewer.oms_wiring import OmsAudit
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.oms import command_rig as cr
from tests.unit.oms.command_rig import Rig
from tests.unit.oms.test_oms_runtime import Writer

#: Every request record a stop row's id may carry: a first-fill attach's and an amend's.
_REQUESTS = ("sl.attached", "sl.modified", "tp.modified")
_VOIDED = {"stop_loss": "sl.modified", "take_profit": "tp.modified"}
#: A user's amend, the principal its exit watch holds (C-2.9).
_USER = SubmitActor(user_id=UUID("8a4b2c1d-6e5f-4a3b-9c2d-1e0f9a8b7c6d"), role="manager")


@pytest.fixture
def rig() -> Rig:
    return cr.build_rig()


async def _live(rig: Rig) -> Any:
    """An entry resting at the venue with its stop-loss and take-profit, stored `submitted`."""
    order = cr.new_order()
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_order(cr.exchange_order(order), uid="100001")
    return order


def _rows(rig: Rig) -> list[RecordedStopRow]:
    return sorted(rig.store._stops.values(), key=lambda row: row.kind)


def _amend_stop(order: Any) -> b01.Command:
    """B1's amend of the entry's stop-loss, both of its sides recorded ahead (re-paired)."""
    return cr.command("amend", order, {"stop_loss": "58500"})


def _offered(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> list[KeyedRecord]:
    """Every keyed record the port writes, whether the writer keeps it or not."""
    offered: list[KeyedRecord] = []
    write = rig.audits.write

    async def offer(record: cr.AnyRecord) -> None:
        if isinstance(record, KeyedRecord):
            offered.append(record)
        await write(record)

    monkeypatch.setattr(rig.audits, "write", offer)
    return offered


def _apart(void: KeyedRecord) -> bool:
    """The void's record id is none of the request records' its row may carry."""
    requests = {keyed_record_id(action, str(void.object_id)) for action in _REQUESTS}
    return keyed_record_id(void.action, void.name) not in requests


@pytest.mark.parametrize(
    "refusal",
    [
        FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003, "refused"),
        RateBudgetExceededError("no token", retry_after_s=2.0),
    ],
    ids=["venue_refused", "no_rate_token"],
)
async def test_a_refused_amends_voids_are_keyed_by_their_reason_never_as_a_request(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, refusal: FakeOutcome
) -> None:
    order = await _live(rig)
    offered = _offered(rig, monkeypatch)
    rig.demo.script("amend_order", refusal)

    await rig.port.amend(_amend_stop(order))

    rows = _rows(rig)
    assert [row.status for row in rows] == ["void"] * 2
    voids = [record for record in offered if record.reason == oc.AMEND_REFUSED]
    assert [(void.action, void.name, void.object_id) for void in voids] == [
        (_VOIDED[row.kind], f"{oc.AMEND_REFUSED}:{row.id}", row.id) for row in rows
    ]
    assert all(_apart(void) for void in voids)


async def test_a_refused_attachs_void_is_keyed_by_its_reason_never_as_a_request(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = cr.new_order()
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_position(cr.position())
    offered = _offered(rig, monkeypatch)
    rig.demo.script("set_trading_stop", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003, "no"))

    await rig.port.attach_stop(cr.command("attach_stop", order, {"stop_loss": "58000"}))

    [row] = _rows(rig)
    [void] = [record for record in offered if record.reason == oc.STOP_REFUSED]
    named = ("sl.modified", f"{oc.STOP_REFUSED}:{row.id}", None)  # B1's: no user, the system's
    assert row.status == "void" and (void.action, void.name, void.actor_user_id) == named
    assert _apart(void)


async def test_a_settle_run_again_over_the_same_rows_names_the_same_record_ids(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The settle's commit fails once its voids are written, so its rows stay in flight; settled
    again with the same answer, it writes its voids under the same ids."""
    order = await _live(rig)
    rig.demo.script("amend_order", TransportError("cut off"))
    with pytest.raises(TransportError):  # Q11: the rows stay in flight
        await rig.port.amend(_amend_stop(order))
    rows, offered = tuple(_rows(rig)), _offered(rig, monkeypatch)
    detail = {"order_link_id": order.order_link_id, "symbol": cr.SYMBOL, "position_idx": "0"}

    rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
    await rig.port._settle_stop(rows, False, "INSTRUMENT_FILTER", detail, reason=oc.AMEND_REFUSED)
    assert [row.status for row in _rows(rig)] == ["pending"] * 2
    first = [keyed_record_id(void.action, void.name) for void in offered]
    offered.clear()
    await rig.port._settle_stop(rows, False, "INSTRUMENT_FILTER", detail, reason=oc.AMEND_REFUSED)

    assert [row.status for row in _rows(rig)] == ["void"] * 2
    assert [keyed_record_id(void.action, void.name) for void in offered] == first != []


async def test_a_users_refused_amend_lands_each_record_once_through_the_runtimes_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end over the runtime's adapter (`OmsAudit`, which refuses a user's record without
    its role) and the runtime test's writer (`Writer`, which stores a keyed record once): a
    user's amend the venue refuses lands each row's request and void, though the settle's commit
    is cut off and its rows stay in flight; settled again, its voids land nothing twice
    (CR-4609-01, CR-4609-02)."""
    writer = Writer()
    rig = cr.build_rig(records=OmsAudit(writer, environment="demo"))
    order = await _live(rig)
    cr.taken(rig.port, order.id, "amend", actor=_USER)
    rig.demo.script("amend_order", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003, "refused"))
    venue = rig.demo.amend_order

    async def cut_off(request: AmendOrderRequest) -> OrderAck:  # the settle's is the next commit
        rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
        return await venue(request)

    monkeypatch.setattr(rig.demo, "amend_order", cut_off)
    with capture_logs() as logs:
        await rig.port.amend(_amend_stop(order))
    rows = tuple(_rows(rig))
    failures = [e["failure"] for e in logs if e["event"] == "oms_stop_settle_failed"]
    assert [row.status for row in rows] == ["pending"] * 2
    assert failures == ["StorageTierUnavailable"]  # never the adapter's refusal
    landed = [(_VOIDED[row.kind], oc.AMEND_REASON) for row in rows]
    landed += [(_VOIDED[row.kind], oc.AMEND_REFUSED) for row in rows]
    assert writer.actions == landed

    detail = {"order_link_id": order.order_link_id, "symbol": cr.SYMBOL, "position_idx": "0"}
    await rig.port._settle_stop(
        rows, False, "INSTRUMENT_FILTER", detail, reason=oc.AMEND_REFUSED, actor=_USER
    )
    assert [row.status for row in _rows(rig)] == ["void"] * 2 and writer.actions == landed
