"""E29-Q04's harness guards (#1148; C-13.5, C-13.7). Demo accounts only, under the load scripts'
own guard (the ticket's Security notes): the suite trades a demo account on one demo port, in
memory, with no transport and so no socket; a live account or port is refused; every venue host is
one the load scripts' guard refuses (`tests/load/accounts/guard.py`, loaded here by its path),
and a dial to the live host is refused. A clean run with the account's stream pushing each fill
ends with the book equal to the venue (the oracle's positive control); a world the oracle never
checked is one the suite fails (`conftest.py`); the outage switch refuses every store call while it
is on, and a door faults the one step it names, once, through the store's own `fail_next`; a submit
the store refuses, by the `commit` door or the outage, sends nothing and leaves the book equal to
the venue (S7), through the real runtime; the venue counts each create request that reached it,
not each link; and the hand-over store reads back what it was given, as the pass reads it."""

from __future__ import annotations

import importlib.util
import socket
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from candleviewer.exchange.base.errors import DuplicateClientIdError
from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS, SIGNED_REST_BASES
from candleviewer.oms.errors import StoreUnavailable
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.oms.handovers import StoreHandovers
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.executions import NewExecution
from tests._ci_network_guard import NetworkGuardViolation, Refusal, expected_refusals
from tests.chaos.oms._oracle import check
from tests.chaos.oms._venue import Venue, VenuePort
from tests.chaos.oms._world import (
    ACCOUNT,
    PRICE,
    REF,
    Handovers,
    Outage,
    World,
    opened,
    unchecked,
)
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms import reconcile_rig as rr
from tests.unit.oms.command_rig import link

pytestmark = pytest.mark.chaos


def _load_guard() -> ModuleType:
    """The load scripts' guard, a repo file outside any package, loaded by its path as the
    account suite loads it (`_e27_stack.load_module`): no other suite's module is imported."""
    path = Path(__file__).resolve().parents[5] / "tests/load/accounts/guard.py"
    spec = importlib.util.spec_from_file_location("q04_load_guard", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


load_guard = _load_guard()


def test_live_exchange_host_is_unreachable_from_the_suite() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with expected_refusals() as refused, pytest.raises(NetworkGuardViolation):
            sock.connect(("api.bybit.com", 443))
    finally:
        sock.close()
    assert refused == [Refusal("connect", "api.bybit.com")]


def test_every_venue_host_is_one_the_load_scripts_guard_refuses() -> None:
    for url in (*SIGNED_REST_BASES.values(), *PRIVATE_WS_URLS.values()):  # each environment's
        with pytest.raises(load_guard.TargetRefused):
            load_guard.check_target(url)
    # the positive control: a guard that refused every target would pass the loop above
    assert load_guard.check_target("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


@virtual
async def test_the_runtime_trades_a_demo_account_on_one_demo_port_with_no_transport() -> None:
    async with opened() as world:
        [call] = world.venue.lane_calls
        assert (call.env, call.transport, world.port.environment) == ("demo", None, "demo")
        assert REF.environment == "demo"
        with pytest.raises(ValueError, match="another environment"):
            await world.port.positions(REF.model_copy(update={"environment": "live"}))
        with pytest.raises(AssertionError, match="demo only"):
            world.venue.port("live")
        await check(world)


@virtual
async def test_a_clean_run_with_each_fill_pushed_ends_with_the_book_equal_to_the_venue() -> None:
    async with opened(streamed=True) as world:
        outcome = await world.submit()
        assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
        row = await world.row(outcome.order_id)
        for part in (Decimal("0.004"), Decimal("0.006")):
            await world.exchange.fill(row.order_link_id, part, PRICE, push=True)
            await world.settle()
        assert (await world.row(outcome.order_id)).lifecycle_state == "filled"
        await check(world)


@pytest.mark.parametrize("by", ["commit-door", "outage"])
@virtual
async def test_a_submit_the_store_refuses_sends_nothing_and_leaves_the_book_equal(by: str) -> None:
    async with opened() as world:
        if by == "outage":
            world.outage.down = True
        else:
            world.door("commit", StorageTierUnavailable("the first commit was refused"))
        with pytest.raises(StoreUnavailable):  # the order cannot be recorded, so none is sent (S7)
            await world.submit()
        world.outage.down = False  # the tier is back: the book and the venue are still equal
        assert world.exchange.creates() == {}
        await check(world)


def test_a_world_the_oracle_never_checked_is_one_the_suite_fails() -> None:
    world = World()
    assert unchecked() == [world]
    world.checked = True
    assert unchecked() == []


async def test_the_outage_switch_and_a_door_fault_only_what_they_name() -> None:
    store = InMemoryOrderStore(lambda: datetime(2026, 10, 23, tzinfo=UTC))
    outage = Outage(store)
    switched = outage.wrap(store.executions)
    outage.down = True
    with pytest.raises(StorageTierUnavailable):
        await switched.get(ACCOUNT, "e1")
    outage.down = False
    lost = StorageTierUnavailable("the commit's answer was cut off")
    outage.doors["cancel_pending"] = (lost, True)
    outage.entered("transition", (SimpleNamespace(lifecycle_state="submitted"),))
    assert outage.doors  # another step: the door stays armed
    outage.entered("transition", (SimpleNamespace(lifecycle_state="cancel_pending"),))
    assert outage.doors == {}  # its own step: fired once, through the store's `fail_next`
    fill = NewExecution(
        exchange_account_id=ACCOUNT, exec_id="e1", symbol="BTCUSDT", side="Buy",
        exec_qty=Decimal(1), exec_price=PRICE, exec_value=PRICE, exec_type="Trade",
        is_maker=False, exec_ts=datetime(2026, 10, 23, tzinfo=UTC),
    )  # fmt: skip
    with pytest.raises(StorageTierUnavailable):
        await switched.insert(fill)
    assert await switched.get(ACCOUNT, "e1") is not None  # committed, its answer lost


def create(order_link_id: str) -> PlaceOrderRequest:
    return PlaceOrderRequest(
        account=REF, symbol="BTCUSDT", side="buy", order_type="limit", qty=Decimal("0.01"),
        price=PRICE, order_link_id=order_link_id, stop_loss=PRICE - 1000,
    )  # fmt: skip


async def test_the_venue_counts_each_create_request_that_reached_it_not_each_link() -> None:
    venue = Venue(VenuePort(now_us=lambda: 0), REF, lambda: 0)
    a, b, c = (create(link(seq=n)) for n in range(3))
    await venue.port.place_order(a)
    with pytest.raises(DuplicateClientIdError):  # a blind second send: refused, yet still a request
        await venue.port.place_order(a)
    await venue.port.place_batch([b, c])  # one request each, in one call
    assert venue.creates() == {a.order_link_id: 2, b.order_link_id: 1, c.order_link_id: 1}


async def test_the_hand_over_store_reads_back_what_it_was_given() -> None:
    store, fill = Handovers(clock=lambda: datetime(2026, 10, 23, tzinfo=UTC)), rr.fill("e1")
    kept = StoreHandovers(store, source="ws_private")
    for empty_read in (False, True, False):  # kept once; an empty read counted, a repeat held
        await kept.hand_over_execution(fill.account_id, fill, empty_read=empty_read)
    [row] = await store.pending(fill.account_id, "execution")
    assert (row.exec_id, row.empty_reads, row.first_empty_read_at) == ("e1", 1, store.clock())
    [waiting] = (await kept.waiting_executions(fill.account_id)).entries
    assert waiting.execution == fill  # as the pass reads it
    assert await store.decide(fill.account_id, "e1") and not await store.decide(
        fill.account_id, "e1"
    )
    assert await store.prune(fill.account_id, [row.id]) == 1
    assert await store.pending(fill.account_id, "execution") == ()
