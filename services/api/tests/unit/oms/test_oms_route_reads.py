"""#913 slice 3F (E29-T04): what `POST /orders` reads of the composed OMS (`OmsRuntime.route`), each
the instance the pipeline was built with (24 Sec.8.4 steps 4, 5, 8, 10 and 12), over E's rig."""

from __future__ import annotations

from typing import get_type_hints

import pytest

from candleviewer.accounts.trade_group_repository import TradeGroupReader
from candleviewer.oms.errors import AccountScopeDenied, OmsNotReady
from candleviewer.oms.ports import NoArmRecords
from candleviewer.oms.repository import OrderRepository
from candleviewer.oms_wiring import (
    AccountExistence,
    OrderRead,
    OrderRoute,
    OrderVersions,
    TradingAccountsBinding,
)
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.unit.oms import command_rig as cr
from tests.unit.oms.test_oms_runtime import KEY, World, started


def test_the_route_holds_the_one_read_each_step_uses_of_the_orders_and_the_accounts() -> None:
    """CR-S3F1-01 (C-12.4): never the order store's writes, nor the account's key ref, nor B1's
    commands: a `202`'s `ETag` reads the facade's `version()` alone (CR-S4D2B-06)."""
    hints = get_type_hints(OrderRoute)
    assert (hints["orders"], hints["accounts"], hints["versions"]) == (
        OrderRead, AccountExistence, OrderVersions,
    )  # fmt: skip
    for read, only in (
        (OrderRead, "get"), (AccountExistence, "environment_of"), (OrderVersions, "version"),
    ):  # fmt: skip
        assert {name for name in vars(read) if not name.startswith("_")} == {only}


async def test_the_route_reads_nothing_before_the_runtime_composes_or_once_it_stops() -> None:
    runtime = World().runtime()
    with pytest.raises(OmsNotReady):
        _ = runtime.route
    async with started(runtime):
        assert runtime.route is not None
    with pytest.raises(OmsNotReady):
        _ = runtime.route


async def test_the_routes_reads_are_the_ones_the_pipeline_was_built_with() -> None:
    """Step 10 asks the switches B1's `SEND` asks (24 Sec.8.4), step 4 the pipeline's account read
    and step 5 the arm records the runtime announced; a replay reads the runtime's own stores, the
    group through the scoped reader (SR-E28-21), and a `202`'s `ETag` the order facade's version."""
    world = World()
    world.accounts.append(TradingAccountRow(cr.ACCOUNT, "demo", cr.UIDS["demo"], False, KEY))
    async with started(world.runtime()) as runtime:
        parts = runtime._composed()
        route, deps = parts.route, parts.submission._deps
        assert isinstance(route.accounts, TradingAccountsBinding)
        assert route.accounts is deps.accounts and route.switches is deps.switches
        assert isinstance(route.arm_records, NoArmRecords)
        assert route.arm_records is parts.submission._ports.arm_records
        assert isinstance(route.orders, OrderRepository) and route.orders._store is world.store
        assert isinstance(route.groups, TradeGroupReader)
        assert route.versions is parts.machines  # the facade B1's steps move
        served = runtime.route  # CV-C13: what the route reaches, its reads awaited on the lane
        assert served.arm_records is route.arm_records and served.switches is route.switches
        assert served.versions is route.versions  # read in place, never on the lane
        assert await served.accounts.environment_of(cr.ACCOUNT) == "demo"
        with pytest.raises(AccountScopeDenied):
            await served.accounts.environment_of(cr.LIVE_ACCOUNT)
