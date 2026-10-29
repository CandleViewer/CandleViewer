"""The OMS REST reads (E29-T07 #915, PR 1; 22 `listOrders`, `getOrder`, `listPositions`,
`getPosition`, `listExecutions`): the read store of this process's environment (C-2.11), each call
bounded, and the portfolio aggregate of `listPositions?aggregate=true`.

`OmsReads` holds no rows of its own and filters none: the store holds the caller's scope in SQL
(`storage.repositories.oms_reads`). A named account outside the scope is `AccountScopeDenied`, the
whole request refused before any row is read (SR-E29-13); a store that does not answer within
`STORE_TIMEOUT_S`, or fails, is `StoreUnavailable`, logged by its class alone (C-12.6).

`aggregate_positions` collapses the open legs of a symbol across accounts into one row (22
`AggregatePosition`), in `Decimal`: `net_size` is the sum of the legs' signed sizes (long positive),
`gross_size` the sum of their sizes, and `unrealised_pnl` the sum of theirs, absent when a leg has
none. `weighted_avg_price` is the size-weighted average of the legs' entry prices when every leg is
on one side; 22 does not say what it is across a long and a short leg, so then it is absent rather
than a guess (#915 PR 1, raised with the orchestrator). The process serves one environment, so its
aggregates never sum across environments: the store reads no account of another.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

import structlog

from candleviewer.domain.primitives import Environment
from candleviewer.oms.errors import AccountScopeDenied, StoreUnavailable
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.oms_reads import (
    ExecutionQuery,
    Keyset,
    ListedExecution,
    ListedOrder,
    OmsReadStore,
    OrderDetail,
    OrderQuery,
    PositionOutOfScope,
    PositionQuery,
)
from candleviewer.storage.repositories.orders import (
    AccountsOutOfScope,
    OrderStoreError,
    OutOfScope,
)
from candleviewer.storage.repositories.positions import PositionRow

__all__ = [
    "STORE_TIMEOUT_S",
    "AggregateLeg",
    "AggregatePosition",
    "OmsReads",
    "aggregate_positions",
]

#: The bound on each read, in seconds, as the exit service bounds its own (`oms.exits`).
STORE_TIMEOUT_S: Final = 2.0
_UNREAD: Final = (TimeoutError, StorageError, OrderStoreError)
_SIDES: Final = {"Buy": "long", "Sell": "short"}


@dataclass(frozen=True, slots=True)
class AggregateLeg:
    """One open position of the aggregate, as its account holds it."""

    account_id: UUID
    size: Decimal
    side: Literal["long", "short"]
    unrealised_pnl: Decimal | None


@dataclass(frozen=True, slots=True)
class AggregatePosition:
    """22 `AggregatePosition` (module docstring)."""

    symbol: str
    net_size: Decimal
    gross_size: Decimal
    weighted_avg_price: Decimal | None
    unrealised_pnl: Decimal | None
    legs: tuple[AggregateLeg, ...]


def aggregate_positions(rows: Iterable[PositionRow]) -> tuple[AggregatePosition, ...]:
    """The open legs of `rows` by symbol, in symbol order (module docstring); a flat row, or one
    of no side, joins none."""
    by_symbol: defaultdict[str, list[PositionRow]] = defaultdict(list)
    for row in rows:
        if row.size > 0 and row.side in _SIDES:
            by_symbol[row.symbol].append(row)
    return tuple(_aggregate(symbol, by_symbol[symbol]) for symbol in sorted(by_symbol))


def _aggregate(symbol: str, legs: list[PositionRow]) -> AggregatePosition:
    net = sum((leg.size if leg.side == "Buy" else -leg.size for leg in legs), Decimal(0))
    gross = sum((leg.size for leg in legs), Decimal(0))
    pnls = [leg.unrealised_pnl for leg in legs]
    pnl = None if None in pnls else sum((p for p in pnls if p is not None), Decimal(0))
    priced = [(leg.avg_price, leg.size) for leg in legs if leg.avg_price is not None]
    one_side = len({leg.side for leg in legs}) == 1
    weighted = None
    if one_side and len(priced) == len(legs):
        weighted = sum((price * size for price, size in priced), Decimal(0)) / gross
    shown = tuple(
        AggregateLeg(leg.exchange_account_id, leg.size, _side(leg), leg.unrealised_pnl)
        for leg in legs
    )
    return AggregatePosition(symbol, net, gross, weighted, pnl, shown)


def _side(row: PositionRow) -> Literal["long", "short"]:
    return "long" if row.side == "Buy" else "short"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class OmsReads:
    """The reads of this process's environment over `store` (module docstring)."""

    def __init__(
        self, store: OmsReadStore, environment: Environment, *,
        timeout_s: float = STORE_TIMEOUT_S, release: Callable[[], Awaitable[None]] | None = None,
    ) -> None:  # fmt: skip
        if not 0 < timeout_s <= STORE_TIMEOUT_S:  # NaN fails it too
            raise ValueError("a read's bound is only ever tightened, never raised")
        self._store, self._timeout, self._release = store, timeout_s, release
        self.environment: Environment = environment

    async def aclose(self) -> None:
        """At shutdown (the lifespan's teardown): the store's own pool, disposed."""
        if self._release is not None:
            await self._release()

    async def orders(
        self, scope: AccountScope, query: OrderQuery, *, after: Keyset | None, limit: int
    ) -> tuple[ListedOrder, ...]:
        env = self.environment
        read = self._store.orders(scope, query, environment=env, after=after, limit=limit)
        return await self._bounded("orders", read)

    async def order(
        self, scope: AccountScope, order_id: UUID, *, events: bool
    ) -> OrderDetail | OutOfScope:
        read = self._store.order(scope, order_id, environment=self.environment, events=events)
        return await self._bounded("order", read)

    async def executions(
        self, scope: AccountScope, query: ExecutionQuery, *, after: Keyset | None, limit: int
    ) -> tuple[ListedExecution, ...]:
        env = self.environment
        read = self._store.executions(scope, query, environment=env, after=after, limit=limit)
        return await self._bounded("executions", read)

    async def closed_pnl(
        self, scope: AccountScope, query: ExecutionQuery, *, after: Keyset | None, limit: int
    ) -> tuple[ListedExecution, ...]:
        env = self.environment
        read = self._store.closed_pnl(scope, query, environment=env, after=after, limit=limit)
        return await self._bounded("closed_pnl", read)

    async def positions(self, scope: AccountScope, query: PositionQuery) -> tuple[PositionRow, ...]:
        read = self._store.positions(scope, query, environment=self.environment)
        return await self._bounded("positions", read)

    async def position(
        self, scope: AccountScope, position_id: UUID
    ) -> PositionRow | PositionOutOfScope:
        read = self._store.position(scope, position_id, environment=self.environment)
        return await self._bounded("position", read)

    async def _bounded[T](self, what: str, call: Coroutine[Any, Any, T]) -> T:
        try:
            async with asyncio.timeout(self._timeout):
                return await call
        except AccountsOutOfScope:  # the caller's scope, never an outage (SR-E29-13)
            raise AccountScopeDenied from None
        except _UNREAD as exc:
            _log().warning("oms_read_unavailable", read=what, failure=type(exc).__name__)
            raise StoreUnavailable from None
