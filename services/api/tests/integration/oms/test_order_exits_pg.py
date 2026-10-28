"""Integration (E29-T04 #913 S4-G3, CG3 and CG4): the exit routes on real Postgres 16.

Each test runs one API process, or two for a restart, as `test_place_order_route_pg.py` runs them:
its `_serving` mounts `POST /orders`, `POST /orders/cancel-all` and the exit routes in
`create_app()`'s order over the OMS runtime on its order lane, the stores on C6's database, with a
`FakeTradingPort` as the venue (C-13.5). CG3 is #913's sixth Gherkin scenario, "Amend rejection
keeps the prior order live". CG4 is the exit routes' Postgres evidence: an accepted amend, the
cancel race with a closing and with a partial fill, a recorded stop's cancel while its position is
open, cancel-all's partial failure, and a restart resuming an exit left pending. Each answer is
validated against 22, and every create carries its native stop (C-2.6, `_native_stops`). A venue
call is held at its door on the order lane's loop (`_Door`), released from there, never by a sleep.
Run once locally before review (8 passed, Postgres 16); CI's `integration` job runs it in the merge
group.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from jsonschema import Draft202012Validator
from structlog.testing import capture_logs

from candleviewer.api.order_etag import order_etag
from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.exchange.base.models import AmendOrderRequest
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, NewOrder
from tests.integration.oms import test_submission_pipeline_pg as c6
from tests.integration.oms.test_place_order_route_pg import World, _entry, _serving, world
from tests.integration.oms.test_submission_pipeline_pg import pg_dsn
from tests.unit.api.test_order_acceptance import schema
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn", "world"]  # C6's database and the route tests' world, for this module

_FORMATS = Draft202012Validator.FORMAT_CHECKER
_ORDER = Draft202012Validator(schema("Order"), format_checker=_FORMATS)
_PROBLEM = Draft202012Validator(schema("OrderExchangeProblem"), format_checker=_FORMATS)
_BULK = Draft202012Validator(schema("BulkAccountResult"), format_checker=_FORMATS)
#: A bound on each wait for the order lane, never a time the test expects.
_BOUND_S = 10.0
#: The venue's refusal of an exit: a business rejection with its return code (SR-E29-09).
_REFUSED = FakeReject(OmsErrorCode.PRICE_OUT_OF_BOUNDS, exchange_ret_code=110003)


def _priced(value: int) -> dict[str, str]:
    """22 `Offset` at a price."""
    return {"unit": "price", "value": str(value)}


@pytest.fixture(autouse=True)
def _native_stops(world: World) -> Iterator[None]:
    """C-2.6 on every path here: once a test ends, every create the venue took carries a stop."""
    yield
    bare = [c.order_link_id for c in world.creates() if not c.reduce_only and c.stop_loss is None]
    assert bare == [], "an entry reached the venue without its native stop (C-2.6)"


@dataclass
class _Door:
    """A venue call held at the venue's door while `holding`: `reached` is set from the order
    lane's thread once a call is there, `opened` (an event of the lane's loop) lets it through, and
    `links` names each call's order."""

    holding: bool = True
    reached: threading.Event = field(default_factory=threading.Event)
    opened: asyncio.Event = field(default_factory=asyncio.Event)
    links: list[str | None] = field(default_factory=list)


def _door(world: World, method: str, monkeypatch: pytest.MonkeyPatch) -> _Door:
    """The venue's `method` (`cancel_order`, `amend_order`) held at a door of its own."""
    door, sent = _Door(), getattr(world.port, method)

    async def held(request: Any) -> Any:
        door.links.append(request.order_link_id)
        if door.holding:
            door.reached.set()
            await door.opened.wait()
        return await sent(request)

    monkeypatch.setattr(world.port, method, held)
    return door


async def _reached(door: _Door) -> None:
    assert await asyncio.to_thread(door.reached.wait, _BOUND_S), "no call reached the door"


async def _on_lane[T](world: World, coro: Coroutine[Any, Any, T]) -> T:
    """`coro` awaited on the order lane of the world's last process."""
    assert world.runtime is not None
    return await world.runtime._composed().lane.call(coro)


async def _placed(client: httpx.AsyncClient, world: World, **over: Any) -> tuple[UUID, str | None]:
    """An entry placed under a key of its own, resting `submitted`: its id and its `ETag`."""
    key = {"Idempotency-Key": str(uuid4())}
    answer = await client.post("/orders", json=world.body | over, headers=key)
    assert answer.status_code == 202, answer.text
    order = _entry(answer.json())[2]
    assert order["lifecycle_state"] == "submitted"
    return UUID(order["id"]), answer.headers.get("etag")


async def _patch(
    client: httpx.AsyncClient, order_id: UUID, body: dict[str, Any], **headers: str
) -> httpx.Response:
    sent = {"Idempotency-Key": str(uuid4())} | headers
    return await client.patch(f"/orders/{order_id}", json=body, headers=sent)


async def _delete(client: httpx.AsyncClient, order_id: UUID) -> httpx.Response:
    return await client.delete(f"/orders/{order_id}", headers={"Idempotency-Key": str(uuid4())})


def _terms(dsn: str, order_id: UUID) -> tuple[Decimal | None, Decimal, str]:
    """The order's price, quantity and lifecycle state, as its row holds them."""
    [(price, qty, state)] = c6._sql(
        dsn, "SELECT price, qty, lifecycle_state::text FROM orders WHERE id = %s", order_id
    )
    return price, qty, str(state)


def _steps(dsn: str, order_id: UUID) -> list[tuple[str, str]]:
    """Each of the order's events, its kind and the stored state it moved to (`order_state`, which
    `ORDER_STATE_OF` maps B1's states to), in `seq` order."""
    rows = c6._sql(
        dsn,
        "SELECT kind::text, to_state::text FROM order_events WHERE order_id = %s ORDER BY seq",
        order_id,
    )
    return [(str(kind), str(to)) for kind, to in rows]


def _last_seq(dsn: str, order_id: UUID) -> int:
    [(seq,)] = c6._sql(dsn, "SELECT max(seq) FROM order_events WHERE order_id = %s", order_id)
    return int(seq)


def _written(world: World, action: str) -> list[tuple[str, str | None]]:
    """The outcome and reason of each record of `action`, in the order written."""
    return [(f["outcome"], f.get("reason")) for a, f in world.writer.records if a == action]


def _calls(world: World, since: int, method: str) -> list[Any]:
    return [call for call in world.port.calls[since:] if call.method == method]


# --- CG3: #913's sixth scenario ---------------------------------------------------------------


async def test_amend_rejection_keeps_the_prior_order_live(world: World) -> None:
    """Gherkin "Amend rejection keeps the prior order live": a `PATCH` moving price and quantity
    together, over the runtime on Postgres, while the venue refuses the amend (`110003`). The
    answer is 502 `exchange_error` with the exchange's code and no `ETag`; the row keeps its price,
    its quantity and `submitted`; its steps end with the `amend_request` and the refused
    `amend_ack`; the venue's order rests as it was; the amend was written ahead, then denied, and
    one amend call was sent (24 Sec.8.4, C-2.9). B1 took its refusal arm (`keep_prior_order_live`,
    logged `b01_amend_rejected` with the code), never the accept arm's guard."""
    with capture_logs() as logs:
        async with _serving(world) as client:
            order_id, _ = await _placed(client, world)
            before = _terms(world.dsn, order_id)
            world.port.script("amend_order", _REFUSED)
            calls = len(world.port.calls)
            answer = await _patch(client, order_id, {"price": "60100", "qty": "0.020"})
    problem = answer.json()
    _PROBLEM.validate(problem)
    assert (answer.status_code, problem["code"], problem["exchange"]) == (
        502, "exchange_error", {"ret_code": 110003},
    )  # fmt: skip
    assert "etag" not in answer.headers
    assert _terms(world.dsn, order_id) == before == (Decimal(60000), Decimal("0.010"), "submitted")
    ended = [("amend_request", "amend_pending"), ("amend_ack", "submitted")]
    assert _steps(world.dsn, order_id)[-2:] == [(k, ORDER_STATE_OF[to]) for k, to in ended]
    assert len(_calls(world, calls, "amend_order")) == 1
    [resting] = await world.port.open_orders(cr.ref(world.account))
    assert (resting.price, resting.qty) == (Decimal(60000), Decimal("0.010"))
    assert _written(world, "orders.amend")[-2][0] == "success"
    assert _written(world, "orders.amend")[-1] == ("denied", "exchange_error")
    events = [e["event"] for e in logs]
    assert events.count("oms_amend_rejected") == 1 and "b01_amend_not_adopted" not in events
    [arm] = [e for e in logs if e["event"] == "b01_amend_rejected"]
    assert arm["error_code"] == OmsErrorCode.PRICE_OUT_OF_BOUNDS


# --- CG4: the exit routes' Postgres evidence --------------------------------------------------


async def test_an_accepted_amend_answers_its_new_etag_and_records_both_stop_sides(
    world: World,
) -> None:
    """An entry with a take-profit, its stop tightened from 58000 to 59000 under `If-Match` (the
    placement's tag): 202 with the order, its new `ETag` the version B1's `amend_ack` gave, which
    the placement's is not; the venue's amend carries both sides, the new stop and the unchanged
    take-profit (24 Sec.8.9's re-pairing); and each side is recorded again as an `entry_attach`
    row named for the order, `sl.modified` changed and `tp.modified` not, reason `amend`."""
    tighter = {"stop_loss": {"unit": "price", "value": "59000"}}
    async with _serving(world) as client:
        order_id, placed = await _placed(client, world, take_profit=_priced(62000))
        assert placed is not None
        calls = len(world.port.calls)
        answer = await _patch(client, order_id, tighter, **{"If-Match": placed})
    assert answer.status_code == 202, answer.text
    _ORDER.validate(answer.json())
    assert answer.headers["etag"] != placed
    assert answer.headers["etag"] == order_etag(order_id, _last_seq(world.dsn, order_id))
    [amend] = _calls(world, calls, "amend_order")
    assert isinstance(amend.request, AmendOrderRequest)
    assert (amend.request.stop_loss, amend.request.take_profit) == (Decimal(59000), Decimal(62000))
    rows = c6._sql(
        world.dsn,
        "SELECT kind::text, trigger_price FROM recorded_stops WHERE order_id = %s "
        "AND source = 'entry_attach' ORDER BY created_at, kind",
        order_id,
    )
    assert [(str(kind), Decimal(price)) for kind, price in rows][-2:] == [
        ("stop_loss", Decimal(59000)), ("take_profit", Decimal(62000)),
    ]  # fmt: skip
    marked = {
        action: (fields["reason"], fields["after_state"]["changed"])
        for action, fields in world.writer.records
        if action in ("sl.modified", "tp.modified") and fields.get("reason") == "amend"
    }
    assert marked == {"sl.modified": ("amend", "true"), "tp.modified": ("amend", "false")}


@dataclass(frozen=True, slots=True)
class _Race:
    """A cancel that met a fill: its answer, its order, and the venue's cancels at the door."""

    answer: httpx.Response
    order_id: UUID
    link: str
    door: _Door


async def _raced(world: World, monkeypatch: pytest.MonkeyPatch, qty: str) -> _Race:
    """The cancel race (6381215194): the venue holds the order's cancel, and an `EXEC` of `qty`
    reaches B1 in `cancel_pending`, pushed on the order lane as E29-T05's consumer pushes it."""
    door = _door(world, "cancel_order", monkeypatch)
    async with _serving(world) as client:
        order_id, _ = await _placed(client, world)
        row = c6._order(world.dsn, order_id)
        cancelling = asyncio.create_task(_delete(client, order_id))
        await _reached(door)
        fill = {
            "order_id": str(order_id), "order_link_id": row.order_link_id,
            "account_id": str(world.account), "symbol": sr.SYMBOL, "side": "buy",
            "exec_id": f"e-{uuid4().hex[:16]}", "exchange_order_id": row.exchange_order_id,
            "qty": qty, "exec_type": "trade", "price": "60000", "fee": "0", "fee_rate": "0.0002",
            "ts_exec": world.clock.us(),
        }  # fmt: skip
        assert world.runtime is not None
        machines = world.runtime._composed().machines
        await _on_lane(world, machines.push(world.account, order_id, "EXEC", fill))
        answer = await cancelling
    return _Race(answer, order_id, row.order_link_id, door)


async def test_a_closing_fill_during_a_cancel_wins_the_race_and_no_second_cancel_leaves(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closing fill in `cancel_pending` ends the order `filled`: one `executions` row, the held
    cancel cut with B1's invoke and never sent again, and 202 with the order `filled`, as 22
    `cancelOrder` answers an order already final."""
    race = await _raced(world, monkeypatch, "0.010")
    assert race.answer.status_code == 202, race.answer.text
    _ORDER.validate(race.answer.json())
    assert race.answer.json()["lifecycle_state"] == "filled"
    order = c6._order(world.dsn, race.order_id)
    assert (order.lifecycle_state, c6._fills(world.dsn, race.order_id)) == ("filled", 1)
    assert race.door.links == [race.link]  # the one cancel, cut short: never a second


async def test_a_partial_fill_during_a_cancel_wins_the_race_and_no_second_cancel_leaves(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial fill in `cancel_pending` moves the order to `partially_filled`: one `executions`
    row, the held cancel cut with B1's invoke and never sent again. The answer is a 202 with the
    order; its state is not pinned here, as 22 `cancelOrder` names no answer for this race."""
    race = await _raced(world, monkeypatch, "0.004")
    assert race.answer.status_code == 202, race.answer.text
    _ORDER.validate(race.answer.json())
    order = c6._order(world.dsn, race.order_id)
    assert (order.lifecycle_state, c6._fills(world.dsn, race.order_id)) == ("partially_filled", 1)
    assert race.door.links == [race.link]  # the one cancel, cut short: never a second


async def test_a_recorded_stops_cancel_is_refused_while_its_position_is_open(world: World) -> None:
    """Ruling Q9 (C-2.6): a recorded stop's TP/SL order, materialised on the lane, with its
    position open at the venue. The cancel is 403 `risk_limit_breached`, denied in its record
    once written ahead; no cancel reaches the venue, and the order stays `submitted`."""
    stop_id = f"x-sl-{uuid4().hex[:8]}"
    stop = NewOrder(
        id=uuid4(), exchange_account_id=world.account, order_link_id=ext_key(stop_id),
        symbol=cr.SYMBOL, side="Sell", intent="stop_loss", order_type="Market",
        qty=Decimal("0.010"), trigger_price=Decimal(58000), reduce_only=True,
        close_on_trigger=True, tpsl_mode="Partial", exchange_order_id=stop_id,
        provenance="recorded_stop", state="accepted", lifecycle_state="submitted",
    )  # fmt: skip
    world.port.seed_position(cr.position(world.account))
    async with _serving(world) as client:
        assert world.runtime is not None
        machines = world.runtime._composed().machines
        await _on_lane(world, machines.materialise(stop, environment="demo"))
        calls = len(world.port.calls)
        answer = await _delete(client, stop.id)
    problem = answer.json()
    _PROBLEM.validate(problem)
    assert (answer.status_code, problem["code"]) == (403, "risk_limit_breached")
    assert _written(world, "orders.cancel")[-1] == ("denied", "risk_limit_breached")
    assert _calls(world, calls, "cancel_order") == []
    assert c6._order(world.dsn, stop.id).lifecycle_state == "submitted"


async def test_cancel_all_answers_a_partial_failure_per_account_and_cancels_the_rest(
    world: World,
) -> None:
    """Two resting entries; the venue refuses the first cancel. The request names the account
    and keeps the default `exclude_reduce_only`, a restricted request, so nothing folds (24
    Sec.8.7): each order is written ahead and sent its own cancel. 200 with the account's entry:
    one order affected, its error the refused cancel's code; one order `cancelled`, one live."""
    async with _serving(world) as client:
        first, _ = await _placed(client, world)
        second, _ = await _placed(client, world)
        world.port.script("cancel_order", _REFUSED)
        calls = len(world.port.calls)
        answer = await client.post(
            "/orders/cancel-all", json={"exchange_account_ids": [str(world.account)]},
            headers={"Idempotency-Key": str(uuid4())},
        )  # fmt: skip
    assert answer.status_code == 200, answer.text
    body = answer.json()
    _BULK.validate(body)
    [result] = body["results"]
    assert (result["exchange_account_id"], result["affected"]) == (str(world.account), 1)
    assert (result["error"]["code"], result["error"]["exchange_ret_code"]) == (
        "exchange_error", 110003,
    )  # fmt: skip
    states = sorted(c6._order(world.dsn, order).lifecycle_state for order in (first, second))
    assert states == ["cancelled", "submitted"]
    assert len(_calls(world, calls, "cancel_order")) == 2 and not _calls(world, calls, "cancel_all")
    assert _written(world, "orders.cancel").count(("success", "cancel_all")) == 2


@pytest.mark.parametrize(
    ("kind", "method", "ended"),
    [("cancel", "cancel_order", "cancelled"), ("amend", "amend_order", "submitted")],
)
async def test_a_restart_resumes_an_exit_left_pending_once_under_its_attempt(
    world: World, monkeypatch: pytest.MonkeyPatch, kind: str, method: str, ended: str
) -> None:
    """A first process sends the exit while the venue holds it, and goes down: its row is left
    `cancel_pending` or `amend_pending`. The second process's sweep hydrates it, and B1 runs the
    invoke once after the replay, under its attempt key: one more venue call with the same link,
    no second request step. The order ends `cancelled`, or `submitted` with the amend's quantity;
    the resumed call has no registration and is logged so (SEC-4662-01)."""
    door, pending = _door(world, method, monkeypatch), f"{kind}_pending"
    async with _serving(world, settle=False, drain_s=1.0) as client:
        order_id, _ = await _placed(client, world)
        link = c6._order(world.dsn, order_id).order_link_id
        exit_call = _delete(client, order_id) if kind == "cancel" else _patch(
            client, order_id, {"qty": "0.005"}
        )  # fmt: skip
        sending = asyncio.create_task(exit_call)
        await _reached(door)
        assert _steps(world.dsn, order_id)[-1] == (f"{kind}_request", ORDER_STATE_OF[pending])
    sending.cancel()
    with contextlib.suppress(BaseException):
        await sending
    assert _terms(world.dsn, order_id)[2] == pending
    door.holding = False
    with capture_logs() as logs:
        async with _serving(world):
            assert world.runtime is not None
            machines = world.runtime._composed().machines
            got = await _on_lane(
                world,
                machines.settled(world.account, order_id, leaving=pending, timeout_s=_BOUND_S),
            )
    assert got == ended and door.links == [link, link]
    steps = [step for step, _ in _steps(world.dsn, order_id)]
    assert steps.count(f"{kind}_request") == 1
    price, qty, state = _terms(world.dsn, order_id)
    assert (price, qty, state) == (
        Decimal(60000), Decimal("0.005" if kind == "amend" else "0.010"), ended,
    )  # fmt: skip
    unregistered = [e for e in logs if e["event"] == "oms_exit_call_unregistered"]
    assert [(e["order_id"], e["kind"]) for e in unregistered] == [(str(order_id), kind)]
