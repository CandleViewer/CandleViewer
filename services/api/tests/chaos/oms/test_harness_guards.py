"""E29-Q04's harness guards (#1148; C-13.5, C-13.7). Demo accounts only, under the load scripts'
own guard (the ticket's Security notes): the suite trades a demo account on one demo port, in
memory, with no transport and so no socket; a live account or port is refused; every venue host is
one the load scripts' guard refuses (`tests/load/accounts/guard.py`, as `_e27_stack.py` loads it),
and a dial to the live host is refused. A clean run with the account's stream pushing each fill
ends with the book equal to the venue (the oracle's positive control); a world the oracle never
checked is one the suite fails (`conftest.py`); the outage switch refuses every store call while it
is on, and a door faults the one step it names, once, through the store's own `fail_next`."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS, SIGNED_REST_BASES
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.executions import NewExecution
from tests._ci_network_guard import NetworkGuardViolation, Refusal, expected_refusals
from tests.chaos.accounts._e27_stack import guard as load_guard
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import ACCOUNT, PRICE, REF, Outage, World, opened, unchecked
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos


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
    outage.doors["submitting"] = (lost, True)
    outage.entered("transition", (SimpleNamespace(lifecycle_state="submitted"),))
    assert outage.doors  # another step: the door stays armed
    outage.entered("transition", (SimpleNamespace(lifecycle_state="submitting"),))
    assert outage.doors == {}  # its own step: fired once, through the store's `fail_next`
    fill = NewExecution(
        exchange_account_id=ACCOUNT, exec_id="e1", symbol="BTCUSDT", side="Buy",
        exec_qty=Decimal(1), exec_price=PRICE, exec_value=PRICE, exec_type="Trade",
        is_maker=False, exec_ts=datetime(2026, 10, 23, tzinfo=UTC),
    )  # fmt: skip
    with pytest.raises(StorageTierUnavailable):
        await switched.insert(fill)
    assert await switched.get(ACCOUNT, "e1") is not None  # committed, its answer lost
