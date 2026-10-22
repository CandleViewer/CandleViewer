"""Routing by environment and the rate step (E29-T04 #913; C-2.11, 24-internal-schemas.md
Sec.8.7).

C-2.11 in both directions: each environment's order and read reach that environment's port only,
and a port wired under another environment's name, or no port at all, is `EnvironmentMismatch`,
which pages. The rate step reads the port's `RateHeadroomPort` without taking a token, and refuses
a wait past its lane's bound with a whole-second `Retry-After`. `RoutedPositions` reads the
account's own position with the account's own trading account, in the `poll` lane.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId, Environment, Side
from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.base.fakes import FakeTradingPort, fake_capabilities
from candleviewer.exchange.base.models import AccountRef, Position, RateHeadroom, RateLane
from candleviewer.oms.classify import ExchangePosition, effect_of
from candleviewer.oms.errors import AccountScopeDenied, EnvironmentMismatch, problem_for
from candleviewer.oms.fakes import InMemoryTradingAccounts
from candleviewer.oms.ports import OrderEffect, RateReading
from candleviewer.oms.routing import (
    MAX_RETRY_AFTER_S,
    NO_ROUTE,
    RATE_LANES,
    RoutedPort,
    RoutedPositions,
    TradingRouter,
    retry_after,
)

DEMO_ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
LIVE_ACCOUNT = AccountId(UUID("6c2d0e3f-8041-4b7c-9d5e-3f4a5b6c7d8e"))
OTHER_ACCOUNT = AccountId(UUID("7d3e1f40-9152-4c8d-ae6f-405b6c7d8e9f"))
DEMO_KEY = "00000000-0000-4000-8000-0000000000d1"
LIVE_KEY = "00000000-0000-4000-8000-0000000000e1"
LANE_WAITS: dict[RateLane, float] = {"critical": 5.0, "entry": 0.75, "poll": 5.0}
T0 = 1_790_000_000_000_000


def ref(
    account_id: AccountId = DEMO_ACCOUNT, environment: Environment = "demo", key: str = DEMO_KEY
) -> AccountRef:
    return AccountRef(account_id=account_id, uid="100001", environment=environment, key_ref=key)


DEMO_REF = ref()
LIVE_REF = ref(LIVE_ACCOUNT, "live", LIVE_KEY)


class SpyPort(FakeTradingPort):
    """A `FakeTradingPort` that keeps the `AccountRef` of each positions read, and answers
    `extra` rows after its own (a broken port, when they repeat one)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.refs: list[AccountRef] = []
        self.extra: list[Position] = []

    async def positions(self, account: AccountRef) -> Sequence[Position]:
        self.refs.append(account)
        return [*await super().positions(account), *self.extra]


class OtherLanePort(FakeTradingPort):
    """A broken port whose rate reading answers another lane than the one asked."""

    def headroom(self, account: AccountRef, lane: RateLane) -> RateHeadroom:
        return RateHeadroom(lane="poll" if lane != "poll" else "entry", tokens=1.0, wait_s=0.0)


def ports() -> tuple[SpyPort, SpyPort]:
    return SpyPort(environment="demo"), SpyPort(environment="live")


def router(**wired: RoutedPort) -> TradingRouter:
    return TradingRouter(wired, lane_waits=LANE_WAITS)  # type: ignore[arg-type]  # str keys


def position(
    account_id: AccountId = DEMO_ACCOUNT,
    *,
    symbol: str = "BTCUSDT",
    position_idx: int = 0,
    side: Side | None = "buy",
    qty: str = "1",
) -> Position:
    return Position.model_validate(
        {
            "account_id": account_id,
            "symbol": symbol,
            "position_idx": position_idx,
            "side": side,
            "qty": Decimal(qty),
            "avg_entry_price": Decimal("60000"),
            "mark_price": Decimal("60100"),
            "liq_price": None,
            "leverage": Decimal("10"),
            "unrealised_pnl": Decimal("100"),
            "cum_realised_pnl": Decimal("0"),
            "take_profit": None,
            "stop_loss": Decimal("58000"),
            "trailing_stop_distance": None,
            "updated_at": T0,
        }
    )


# --- port_for, transport_for: C-2.11 -----------------------------------------------------------


def test_port_for_answers_each_environments_own_port() -> None:
    demo, live = ports()
    routes = router(demo=demo, live=live)
    assert routes.port_for("demo") is demo
    assert routes.port_for("live") is live


@pytest.mark.parametrize(("named", "actual"), [("demo", "live"), ("live", "demo")])
def test_a_port_wired_under_another_environments_name_is_refused_at_build_and_pages(
    named: Environment, actual: Environment
) -> None:
    with capture_logs() as logs, pytest.raises(EnvironmentMismatch) as refused:
        router(**{named: SpyPort(environment=actual)})
    assert (refused.value.order_environment, refused.value.route_environment) == (named, actual)
    assert problem_for(refused.value).pages
    assert [(log["event"], log["log_level"]) for log in logs] == [("oms_route_refused", "critical")]


@pytest.mark.parametrize(("named", "actual"), [("demo", "live"), ("live", "demo")])
def test_a_port_whose_environment_changed_since_the_build_is_refused(
    named: Environment, actual: Environment
) -> None:
    port = SpyPort(environment=named)
    routes = router(**{named: port})
    port.capabilities = fake_capabilities(actual)
    with pytest.raises(EnvironmentMismatch):
        routes.port_for(named)
    with pytest.raises(EnvironmentMismatch):
        routes.transport_for(named)
    assert port.calls == []


def test_an_environment_with_no_port_is_refused_and_pages() -> None:
    demo, _ = ports()
    routes = router(demo=demo)
    with capture_logs() as logs, pytest.raises(EnvironmentMismatch) as refused:
        routes.port_for("live")
    assert (refused.value.order_environment, refused.value.route_environment) == ("live", NO_ROUTE)
    assert problem_for(refused.value).pages
    assert problem_for(refused.value).status == 500
    assert [(log["event"], log["log_level"], log["route"]) for log in logs] == [
        ("oms_route_refused", "critical", NO_ROUTE)
    ]


def test_the_transport_is_rest_for_every_routed_environment() -> None:
    demo, live = ports()
    routes = router(demo=demo, live=live)
    assert routes.transport_for("demo") == routes.transport_for("live") == "rest"
    with pytest.raises(EnvironmentMismatch):
        routes.transport_for("testnet")
    assert demo.calls == live.calls == []


def test_the_router_keeps_its_own_copy_of_the_routes() -> None:
    demo, live = ports()
    wired: dict[str, RoutedPort] = {"demo": demo}
    routes = TradingRouter(wired, lane_waits=LANE_WAITS)  # type: ignore[arg-type]  # str keys
    wired["live"] = live
    with pytest.raises(EnvironmentMismatch):
        routes.port_for("live")


# --- the lane waits ------------------------------------------------------------------------------


UNTYPED_WAITS: dict[str, object] = {lane: wait for lane, wait in LANE_WAITS.items()}


@pytest.mark.parametrize(
    "lane_waits",
    [
        {"critical": 5.0, "entry": 0.75},
        {**UNTYPED_WAITS, "batch": 1.0},
        {**UNTYPED_WAITS, "entry": -0.1},
        {**UNTYPED_WAITS, "entry": math.nan},
        {**UNTYPED_WAITS, "poll": math.inf},
        {**UNTYPED_WAITS, "critical": True},
        {**UNTYPED_WAITS, "critical": "5"},
        {**UNTYPED_WAITS, "critical": None},
    ],
)
def test_lane_waits_name_every_lane_once_with_a_finite_wait(lane_waits: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="lane"):
        TradingRouter({}, lane_waits=lane_waits)  # type: ignore[arg-type]  # what is refused


def test_lane_waits_take_whole_seconds() -> None:
    demo, _ = ports()
    routes = TradingRouter({"demo": demo}, lane_waits={"critical": 5, "entry": 1, "poll": 5})
    demo.set_headroom(DEMO_ACCOUNT, RateHeadroom(lane="entry", tokens=0.0, wait_s=1.0))
    assert routes.headroom(DEMO_REF, "entry") == RateReading(available=True)
    assert RATE_LANES == {"critical", "entry", "poll"}


# --- the rate step: headroom ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lane", "wait_s"),
    [("entry", 0.0), ("entry", 0.75), ("critical", 4.999), ("critical", 5.0), ("poll", 5.0)],
)
def test_headroom_admits_a_wait_within_its_lanes_bound(lane: RateLane, wait_s: float) -> None:
    demo, _ = ports()
    demo.set_headroom(DEMO_ACCOUNT, RateHeadroom(lane=lane, tokens=0.0, wait_s=wait_s))
    assert router(demo=demo).headroom(DEMO_REF, lane) == RateReading(available=True)


@pytest.mark.parametrize(
    ("lane", "wait_s", "retry_after_s"),
    [
        ("entry", 0.7500001, 1),
        ("entry", 1.2, 2),
        ("entry", 3.0, 3),
        ("critical", 5.0001, 6),
        ("poll", 59.5, 60),
        ("poll", 61.0, MAX_RETRY_AFTER_S),
        ("critical", 1e300, MAX_RETRY_AFTER_S),
        ("entry", math.inf, MAX_RETRY_AFTER_S),
    ],
)
def test_headroom_refuses_a_wait_past_its_lanes_bound_in_whole_seconds(
    lane: RateLane, wait_s: float, retry_after_s: int
) -> None:
    demo, _ = ports()
    demo.set_headroom(DEMO_ACCOUNT, RateHeadroom(lane=lane, tokens=0.0, wait_s=wait_s))
    reading = router(demo=demo).headroom(DEMO_REF, lane)
    assert reading == RateReading(available=False, retry_after_s=retry_after_s)


def test_a_zero_bound_admits_only_a_spare_token() -> None:
    demo, _ = ports()
    routes = TradingRouter({"demo": demo}, lane_waits={**LANE_WAITS, "entry": 0.0})
    assert routes.headroom(DEMO_REF, "entry").available  # unscripted: a fresh budget, no wait
    demo.set_headroom(DEMO_ACCOUNT, RateHeadroom(lane="entry", tokens=0.0, wait_s=0.001))
    assert routes.headroom(DEMO_REF, "entry") == RateReading(available=False, retry_after_s=1)


@given(wait_s=st.floats(min_value=0.0, max_value=1e9, allow_nan=False))
def test_headroom_admits_exactly_the_waits_within_the_bound(wait_s: float) -> None:
    demo = FakeTradingPort(environment="demo")
    demo.set_headroom(DEMO_ACCOUNT, RateHeadroom(lane="entry", tokens=0.0, wait_s=wait_s))
    reading = TradingRouter({"demo": demo}, lane_waits=LANE_WAITS).headroom(DEMO_REF, "entry")
    assert reading.available is (wait_s <= LANE_WAITS["entry"])
    if not reading.available:
        assert reading.retry_after_s is not None
        assert 1 <= reading.retry_after_s <= MAX_RETRY_AFTER_S
        assert reading.retry_after_s >= min(wait_s, MAX_RETRY_AFTER_S)


def test_headroom_reads_the_accounts_own_port_and_records_no_call() -> None:
    """C-2.11: each account's reading is its own environment's, and a reading sends nothing."""
    demo, live = ports()
    demo.set_headroom(DEMO_ACCOUNT, RateHeadroom(lane="entry", tokens=0.0, wait_s=2.0))
    live.set_headroom(LIVE_ACCOUNT, RateHeadroom(lane="entry", tokens=9.0, wait_s=0.0))
    routes = router(demo=demo, live=live)
    assert routes.headroom(DEMO_REF, "entry") == RateReading(available=False, retry_after_s=2)
    assert routes.headroom(LIVE_REF, "entry") == RateReading(available=True)
    assert demo.calls == live.calls == []


def test_headroom_of_an_environment_with_no_port_is_refused() -> None:
    demo, _ = ports()
    with pytest.raises(EnvironmentMismatch):
        router(demo=demo).headroom(LIVE_REF, "entry")


@pytest.mark.parametrize("lane", ["critical", "entry", "poll"])
def test_a_reading_of_another_lane_is_a_broken_port(lane: RateLane) -> None:
    with pytest.raises(ValueError, match="another lane"):
        router(demo=OtherLanePort(environment="demo")).headroom(DEMO_REF, lane)


# --- RoutedPositions: the pipeline's PositionTruth -----------------------------------------------


def routed(
    *accounts: AccountRef,
) -> tuple[RoutedPositions, SpyPort, SpyPort, InMemoryTradingAccounts]:
    demo, live = ports()
    trading = InMemoryTradingAccounts(*accounts)
    return RoutedPositions(router(demo=demo, live=live), trading), demo, live, trading


async def test_positions_are_read_with_the_accounts_own_ref_in_the_poll_lane() -> None:
    """SR-E27-21: the read carries the account's own key, which only `TradingAccounts` names."""
    positions, demo, live, trading = routed(DEMO_REF)
    demo.seed_position(position())
    found = await positions.position(DEMO_ACCOUNT, "BTCUSDT", 0)
    assert found == ExchangePosition(side="buy", qty=Decimal("1"))
    assert trading.asked == [DEMO_ACCOUNT]
    assert demo.refs == [DEMO_REF]
    assert [(call.method, call.account_id, call.lane) for call in demo.calls] == [
        ("positions", DEMO_ACCOUNT, "poll")
    ]
    assert live.calls == []


@pytest.mark.parametrize(
    ("account", "reads", "idle"), [(DEMO_REF, "demo", "live"), (LIVE_REF, "live", "demo")]
)
async def test_c_2_11_an_accounts_position_is_read_on_its_own_environments_port_only(
    account: AccountRef, reads: str, idle: str
) -> None:
    positions, demo, live, _ = routed(DEMO_REF, LIVE_REF)
    by_name = {"demo": demo, "live": live}
    by_name[reads].seed_position(position(account.account_id, side="sell", qty="2"))
    found = await positions.position(account.account_id, "BTCUSDT", 0)
    assert found == ExchangePosition(side="sell", qty=Decimal("2"))
    assert by_name[reads].refs == [account]
    assert by_name[idle].calls == []


async def test_positions_answer_the_one_row_of_the_account_symbol_and_index() -> None:
    positions, demo, _, _ = routed(DEMO_REF)
    demo.seed_position(position(qty="1"))
    demo.seed_position(position(symbol="ETHUSDT", qty="7"))
    demo.seed_position(position(position_idx=1, qty="8"))
    demo.seed_position(position(position_idx=2, side="sell", qty="9"))
    demo.extra = [position(OTHER_ACCOUNT, qty="10")]  # another account's row, which is never ours
    assert await positions.position(DEMO_ACCOUNT, "BTCUSDT", 0) == ExchangePosition(
        side="buy", qty=Decimal("1")
    )
    assert await positions.position(DEMO_ACCOUNT, "BTCUSDT", 2) == ExchangePosition(
        side="sell", qty=Decimal("9")
    )


async def test_no_row_is_no_position_and_a_flat_row_reads_as_it_is() -> None:
    positions, demo, _, _ = routed(DEMO_REF)
    assert await positions.position(DEMO_ACCOUNT, "BTCUSDT", 0) is None
    demo.seed_position(position(side=None, qty="0"))
    assert await positions.position(DEMO_ACCOUNT, "BTCUSDT", 0) == ExchangePosition(
        side=None, qty=Decimal("0")
    )


async def test_an_account_resolved_to_another_account_is_refused_before_any_read() -> None:
    positions, demo, live, trading = routed()
    trading.seed(ref(OTHER_ACCOUNT), as_id=DEMO_ACCOUNT)
    with pytest.raises(ValueError, match="another account"):
        await positions.position(DEMO_ACCOUNT, "BTCUSDT", 0)
    assert demo.calls == live.calls == []


async def test_an_account_the_oms_does_not_trade_is_refused_before_any_read() -> None:
    positions, demo, live, _ = routed()
    with pytest.raises(AccountScopeDenied):
        await positions.position(DEMO_ACCOUNT, "BTCUSDT", 0)
    assert demo.calls == live.calls == []


async def test_a_read_that_names_the_position_twice_is_refused() -> None:
    positions, demo, _, _ = routed(DEMO_REF)
    demo.seed_position(position())
    demo.extra = [position(qty="3")]
    with pytest.raises(ValueError, match="twice"):
        await positions.position(DEMO_ACCOUNT, "BTCUSDT", 0)


async def test_an_account_of_an_environment_with_no_port_is_refused() -> None:
    demo, _ = ports()
    positions = RoutedPositions(router(demo=demo), InMemoryTradingAccounts(LIVE_REF))
    with pytest.raises(EnvironmentMismatch):
        await positions.position(LIVE_ACCOUNT, "BTCUSDT", 0)
    assert demo.calls == []


# --- through classification (SR-E29-01) ----------------------------------------------------------


async def test_a_reduce_only_order_is_classified_on_the_routed_position() -> None:
    positions, demo, _, _ = routed(DEMO_REF)
    demo.seed_position(position(side="buy", qty="1"))

    async def effect(side: Side, qty: str) -> OrderEffect:
        return await effect_of(
            account_id=DEMO_ACCOUNT,
            symbol="BTCUSDT",
            position_idx=0,
            side=side,
            qty=Decimal(qty),
            reduce_only=True,
            positions=positions,
            timeout_s=1.0,
        )

    assert await effect("sell", "0.5") is OrderEffect.REDUCE
    assert await effect("sell", "1.5") is OrderEffect.ENTRY  # past the position: fail closed
    assert await effect("buy", "0.5") is OrderEffect.ENTRY  # the position's own side


async def test_a_failed_read_raises_so_the_order_fails_closed() -> None:
    """Q-B: the pipeline answers 503 `exchange_unavailable`; nothing is classified."""
    positions, demo, _, _ = routed(DEMO_REF)
    demo.script("positions", TransportError("the read failed"))
    with pytest.raises(TransportError):
        await effect_of(
            account_id=DEMO_ACCOUNT,
            symbol="BTCUSDT",
            position_idx=0,
            side="sell",
            qty=Decimal("1"),
            reduce_only=True,
            positions=positions,
            timeout_s=1.0,
        )


@pytest.mark.parametrize(
    ("wait_s", "seconds"),
    [(None, 1), (math.nan, 1), (0.0, 1), (0.01, 1), (1.0, 1), (1.5, 2), (59.9, 60), (math.inf, 60)],
)
def test_a_wait_reads_as_whole_seconds_of_retry(wait_s: float | None, seconds: int) -> None:
    """A refused token whose wait is unknown retries after one second (24 Sec.8.7)."""
    assert retry_after(wait_s) == seconds
