"""#913 slice 3F (E29-T04): what `POST /orders` reads of the composed OMS (`OmsRuntime.route`), each
the instance the pipeline was built with (24 Sec.8.4 steps 4, 5, 8, 10 and 12), over E's rig."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast, get_type_hints
from uuid import UUID

import pytest

from candleviewer.accounts.trade_group_repository import TradeGroupReader
from candleviewer.exchange.base.models import AccountRef
from candleviewer.oms.errors import (
    AccountScopeDenied,
    OmsNotReady,
    OrderEntryRefused,
    StoreUnavailable,
)
from candleviewer.oms.fanout.guard import S4SGuard
from candleviewer.oms.ports import FiguresReading, NoArmRecords, SymbolRates
from candleviewer.oms.repository import OrderRepository
from candleviewer.oms_lane import HOP_TIMEOUT_S, LaneStopped
from candleviewer.oms_wiring import (
    NO_ACTIVE_KEY,
    AccountExistence,
    OnLanePreview,
    OrderRead,
    OrderRoute,
    OrderVersions,
    PreviewFigures,
    ReferencePricesBinding,
    TradingAccountsBinding,
)
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import figures as known
from tests.unit.oms.test_oms_runtime import KEY, Recording, Refusing, World, started


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


async def test_the_previews_reads_are_the_order_paths_own_and_peek_on_the_lane() -> None:
    """E28-T05 S3c (#909): the preview's guard asks the pipeline's risk gate and switches, its stop
    resolver and listing are the pipeline's, its market the same ticker stream with no demand (no
    venue call), and its figures are the pipeline's, peeked on the lane through its account
    binding, which the route never holds (no key ref); nothing before the runtime composes."""
    world = World()
    world.accounts.append(TradingAccountRow(cr.ACCOUNT, "demo", cr.UIDS["demo"], False, KEY))
    world.ingestion.tickers = SimpleNamespace(
        latest=lambda _symbol: None, is_stale=lambda _symbol: False,
        acquire=lambda _consumer, _symbol: None, release=lambda _consumer, _symbol: None,
    )  # fmt: skip
    with pytest.raises(OmsNotReady):
        _ = world.runtime().preview
    async with started(world.runtime()) as runtime:
        parts = runtime._composed()
        held, deps, chosen = parts.preview, parts.submission._deps, parts.submission._ports
        prices = cast(ReferencePricesBinding, deps.prices)
        assert isinstance(held.guard, S4SGuard) and held.guard._switches is deps.switches
        assert held.guard._risk_gate is chosen.risk_gate and held.stops is chosen.stop_resolver
        assert held.instruments is deps.instruments and prices._demand is not None
        assert held.prices._demand is None  # the order path's asks a demand; the preview never
        assert isinstance(held.figures, PreviewFigures) and held.figures._figures is deps.figures
        assert held.prices._tickers is prices._tickers and held.figures._accounts is deps.accounts
        served = runtime.preview
        assert isinstance(served.figures, OnLanePreview) and served.guard is held.guard
        fallbacks: dict[Any, Decimal | None] = {cr.ACCOUNT: Decimal("0.02"), cr.LIVE_ACCOUNT: None}
        assert await served.figures.peeked("BTCUSDT", fallbacks) == dict.fromkeys(fallbacks)


async def test_the_previews_figures_hop_to_the_lane_within_its_bound() -> None:
    """R1C-01 (S3c's code lens): `runtime.preview.figures` peeks on the order lane, where the
    figures are kept, within `HOP_TIMEOUT_S`, as the exit routes' reads hop; a lane that stopped
    or does not answer is `OmsNotReady`, the peek unrun."""
    lane = Recording()
    async with started(World().runtime(lane=lambda: lane)) as runtime:
        lane.hops.clear()
        peeked = await runtime.preview.figures.peeked("BTCUSDT", {cr.ACCOUNT: None})
        assert (peeked, lane.hops) == (
            {cr.ACCOUNT: None},
            [("PreviewFigures.peeked", HOP_TIMEOUT_S)],
        )
        parts = runtime._composed()
        for error in (LaneStopped("stopped"), TimeoutError()):
            on_lane = OnLanePreview(replace(parts, lane=Refusing(error)))
            with pytest.raises(OmsNotReady):
                await on_lane.peeked("BTCUSDT", {cr.ACCOUNT: None})


async def test_preview_figures_peek_each_resolved_account_never_read_it() -> None:
    """SR-E28-22: each account resolved as an order's, its kept reading peeked at its fallback and
    its symbol's rates merged as the size step merges them; an account the binding refuses (no
    key, another environment) has none, and nothing is ever read from the venue."""
    rates = SymbolRates(maintenance_margin_rate=Decimal("0.005"), taker_fee_rate=Decimal("0.0006"))
    asked: list[tuple[Any, ...]] = []
    unread = UUID(int=77)  # R1C-03(b): an account whose read fails has none, as one refused

    class Accounts:
        async def trading_account(self, account_id: Any) -> AccountRef:
            if account_id == unread:
                raise StoreUnavailable
            if account_id != cr.ACCOUNT:
                raise OrderEntryRefused(NO_ACTIVE_KEY) if account_id == KEY else AccountScopeDenied
            return AccountRef(account_id=account_id, uid="1", environment="demo", key_ref=str(KEY))

    class Figures:
        def peek(self, account: AccountRef, symbols: Any, *, fallback_sl_offset_pct: Any) -> Any:
            asked.append((account.account_id, tuple(symbols), fallback_sl_offset_pct))
            unrated = known(maintenance_margin_rate=None, taker_fee_rate=None)
            return FiguresReading(unrated, {"BTCUSDT": rates})

    peeked = await PreviewFigures(Accounts(), cast(Any, Figures())).peeked(
        "BTCUSDT", {cr.ACCOUNT: Decimal("0.02"), KEY: None, cr.LIVE_ACCOUNT: None, unread: None}
    )
    assert asked == [(cr.ACCOUNT, ("BTCUSDT",), Decimal("0.02"))]
    merged = peeked[cr.ACCOUNT]
    assert merged is not None and (merged.maintenance_margin_rate, merged.taker_fee_rate) == (
        Decimal("0.005"), Decimal("0.0006"),
    )  # fmt: skip
    assert (peeked[KEY], peeked[cr.LIVE_ACCOUNT], peeked[unread]) == (None, None, None)
