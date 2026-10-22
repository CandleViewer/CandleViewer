"""Routing an order to its environment's trading port (E29-T04 #913; C-2.11, 24 Sec.8.7).

C-2.11: live, demo and testnet are separate credential sets, base URLs and code paths. The
composition root (slice 3's wiring) builds one trading port per environment and hands them to
`TradingRouter`, the OMS's only way to the exchange. `port_for(environment)` answers that
environment's port once `Validator.check_route` holds the environment asked for against the one
the port declares (`capabilities.environment`): a port wired under another environment's name, or
no port for the environment, is `EnvironmentMismatch`, an invariant broken, which pages (500). The
router checks every port it is given when it is built too, so a miswired root fails at startup.
The port refuses an account of another environment as well (24 Sec.14.2), so a request built for
one environment is never signed with another's key.

`transport_for` names the transport: REST for every environment in v1 (SR-040a, 20 Sec.9 rule 7).
`capabilities.supports_ws_order_entry` says what the venue offers, not that a trade socket exists,
and demo offers none, so no order goes over a WebSocket.

The rate step (24 Sec.8.7; #2877 ruling 4): `headroom(account, lane)` reads the port's
`RateHeadroomPort`, which takes no token and sends nothing, and answers a `ports.RateReading`.
It refuses when the request would wait past its lane's bound (`lane_waits`: the bounds the port's
lanes wait, which slice 3 wires from the same settings), with a `Retry-After` of the wait rounded
up to whole seconds, at least 1 and at most `MAX_RETRY_AFTER_S`. It only advises: the port still
takes the token at the call, and refuses with `RateBudgetExceededError`, nothing sent, when none
comes within the lane's wait.

`RoutedPositions` is the pipeline's `classify.PositionTruth` (SR-E29-01): the exchange's own
position of one account, symbol and position index, read in the `poll` lane over the account's
own port and key (`ports.TradingAccounts`, SR-E27-21). A read that fails raises, so the order
fails closed (503 `exchange_unavailable`). Nothing here imports the exchange adapter (C-2.2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, get_args

import structlog

from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.exchange.base.models import AccountRef, Position, RateLane
from candleviewer.exchange.base.ports import RateHeadroomPort, TradingPort

from .classify import ExchangePosition
from .errors import EnvironmentMismatch
from .ports import RateReading, TradingAccounts
from .validator import Validator

__all__ = [
    "MAX_RETRY_AFTER_S",
    "NO_ROUTE",
    "RATE_LANES",
    "RoutedPort",
    "RoutedPositions",
    "TradingRouter",
    "Transport",
    "read_position",
    "retry_after",
]

#: The lanes a request waits in (24 Sec.8.7): every one needs a bound in `lane_waits`.
RATE_LANES: Final[frozenset[str]] = frozenset(get_args(RateLane.__value__))
#: The longest `Retry-After` the rate step answers, in seconds: a wait past it, or one with no
#: end (an IP hold the port cannot time), is answered with this, and a repeat reads again.
MAX_RETRY_AFTER_S: Final = 60
#: What `EnvironmentMismatch` names as the route of an environment no port is wired for.
NO_ROUTE: Final = "none"

type Transport = Literal["rest"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class RoutedPort(TradingPort, RateHeadroomPort, Protocol):
    """An environment's trading port that also reads its own rate budget, as the exchange's port
    and `FakeTradingPort` both do (24 Sec.14.1)."""


class TradingRouter:
    """The trading port of each environment, and the rate step's verdict (module docstring)."""

    def __init__(
        self, ports: Mapping[Environment, RoutedPort], *, lane_waits: Mapping[RateLane, float]
    ) -> None:
        for environment, port in ports.items():
            _check_route(environment, port)
        self._ports: Mapping[Environment, RoutedPort] = MappingProxyType(dict(ports))
        self._lane_waits = _bounds(lane_waits)

    def port_for(self, environment: Environment) -> RoutedPort:
        """The port of `environment`, else `EnvironmentMismatch` (C-2.11), logged at CRITICAL."""
        port = self._ports.get(environment)
        if port is None:
            _log().critical("oms_route_refused", environment=environment, route=NO_ROUTE)
            raise EnvironmentMismatch(order_environment=environment, route_environment=NO_ROUTE)
        _check_route(environment, port)
        return port

    def transport_for(self, environment: Environment) -> Transport:
        """REST, for every environment the router serves; refused as `port_for` refuses."""
        self.port_for(environment)
        return "rest"

    def headroom(self, account: AccountRef, lane: RateLane) -> RateReading:
        """Whether a request of `account` in `lane` would get its token within the lane's bound,
        read from the account's own port without taking one; a reading of another lane is a
        broken port, `ValueError`."""
        reading = self.port_for(account.environment).headroom(account, lane)
        if reading.lane != lane:
            raise ValueError("the rate reading answers another lane")
        if reading.wait_s <= self._lane_waits[lane]:
            return RateReading(available=True)
        return RateReading(available=False, retry_after_s=retry_after(reading.wait_s))


class RoutedPositions:
    """`classify.PositionTruth` over the router: the account's own position, read with its own
    trading account (module docstring)."""

    def __init__(self, router: TradingRouter, accounts: TradingAccounts) -> None:
        self._router = router
        self._accounts = accounts

    async def position(
        self, account_id: AccountId, symbol: Symbol, position_idx: int
    ) -> ExchangePosition | None:
        """The position, or `None` when the exchange shows none; `ValueError` when the account
        resolves to another account or the read names the position twice."""
        account = await self._accounts.trading_account(account_id)
        if account.account_id != account_id:
            raise ValueError("the trading account resolved is another account's")
        port = self._router.port_for(account.environment)
        row = await read_position(port, account, symbol, position_idx)
        return None if row is None else ExchangePosition(side=row.side, qty=row.qty)


async def read_position(
    port: TradingPort, account: AccountRef, symbol: Symbol, position_idx: int
) -> Position | None:
    """`account`'s row for `symbol` and `position_idx` in one positions read (the `poll` lane),
    whatever else the port answers; None when it shows none, `ValueError` when it shows two."""
    rows = [
        row
        for row in await port.positions(account)
        if row.account_id == account.account_id
        and row.symbol == symbol
        and row.position_idx == position_idx
    ]
    if len(rows) > 1:
        raise ValueError("the exchange read names the position twice")
    return rows[0] if rows else None


def _check_route(environment: Environment, port: TradingPort) -> None:
    try:
        Validator.check_route(environment, port.capabilities.environment)
    except EnvironmentMismatch as refused:
        _log().critical(
            "oms_route_refused", environment=environment, route=refused.route_environment
        )
        raise


def _bounds(lane_waits: Mapping[RateLane, float]) -> Mapping[RateLane, float]:
    """Each lane's bound, in seconds: every lane named once, each a finite number, 0 or more."""
    if set(lane_waits) != RATE_LANES:
        raise ValueError(f"lane_waits names every rate lane once: {sorted(RATE_LANES)}")
    for lane, wait in lane_waits.items():
        usable = isinstance(wait, int | float) and not isinstance(wait, bool)
        if not usable or not math.isfinite(wait) or wait < 0:
            raise ValueError(f"the {lane} lane's wait is a finite number of seconds, 0 or more")
    return MappingProxyType({lane: float(wait) for lane, wait in lane_waits.items()})


def retry_after(wait_s: float | None) -> int:
    """`wait_s` as a `Retry-After`: rounded up to whole seconds, at least 1 and at most
    `MAX_RETRY_AFTER_S`; 1 when no wait is known (a refused token whose wait was not timed)."""
    if wait_s is None or wait_s != wait_s:  # unknown, or NaN: the shortest retry
        return 1
    if not wait_s < MAX_RETRY_AFTER_S:  # past the cap, or no end at all (inf)
        return MAX_RETRY_AFTER_S
    return max(1, math.ceil(wait_s))
