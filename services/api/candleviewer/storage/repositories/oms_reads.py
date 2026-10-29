"""Driver-free surface of the OMS REST reads (E29-T07 #915, PR 1; 22 `listOrders`, `getOrder`,
`listPositions`, `getPosition`, `listExecutions`).

Every read takes the principal's `AccountScope` and holds it in SQL with the exit routes' one
predicate (`orders_sqlalchemy.scope_clause`, its viewing form: a grant's `can_view`, unfrozen; an
Owner's live owner role), over the accounts of the process's environment alone (C-2.11). Another
environment's account, a foreign one and a missing one are never read (C-12.4, SR-E29-13), and no
row is filtered out in Python. A read that names accounts settles them first, all or nothing
(`orders.settle_accounts`): one outside the scope raises `AccountsOutOfScope` before any row is
read. The lists are keyset-paged, newest first, by time then id (`Keyset`), on the T01 indexes
(`ix_orders_recent`, `ix_orders_open`, `ix_exec_acct_time`, `ix_pos_open`). Positions are not
paged (22 `listPositions` has no cursor): the exchange holds one row per account, symbol and
`position_idx`. `oms_reads_sqlalchemy.py` is the Postgres side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, get_args
from uuid import UUID

from candleviewer.domain.primitives import Environment
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.executions import ExecutionRow
from candleviewer.storage.repositories.orders import (
    OrderEventRow,
    OrderIntent,
    OrderRow,
    OrderState,
    OutOfScope,
    ScopedOrder,
)
from candleviewer.storage.repositories.positions import PositionRow

#: The final order states (24 Sec.8.2); 22's `open_only` is the rest, the non-terminal set, which
#: holds `held` and `untracked` too, as 22 `OrderState` has a client show both as live.
TERMINAL_STATES: Final = frozenset[OrderState](
    {"filled", "cancelled", "rejected", "expired", "killed"}
)
NON_TERMINAL_STATES: Final = frozenset(get_args(OrderState)) - TERMINAL_STATES
#: The most executions one `getOrder` serves: an order's fills, which its quantity bounds.
MAX_ORDER_EXECUTIONS: Final = 500
#: The most positions one `listPositions` reads (C-2.18): the exchange holds one per account,
#: symbol and `position_idx` (3), so this covers 25 accounts (22's `AccountIdsQuery` bound) of
#: some 130 symbols each, open or flat. A read past it is refused whole (`PositionsTooMany`).
MAX_POSITIONS: Final = 10_000


class PositionsTooMany(Exception):
    """`positions` found more rows than `MAX_POSITIONS`: refused whole, never cut (#4997). The
    caller's request, not an outage; names no value."""


@dataclass(frozen=True, slots=True)
class Keyset:
    """A list's position: the time and the id of the last row served, newest first."""

    at: datetime
    id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderQuery:
    """22 `listOrders`' filters; `since` is inclusive and `until` exclusive, on `created_ts`."""

    accounts: tuple[UUID, ...] = ()
    symbol: str | None = None
    states: frozenset[OrderState] = frozenset()
    intents: frozenset[OrderIntent] = frozenset()
    trade_group_id: UUID | None = None
    open_only: bool = False
    since: datetime | None = None
    until: datetime | None = None

    def wanted_states(self) -> frozenset[OrderState] | None:
        """The states asked for: `states` narrowed to the non-terminal set by `open_only`; None
        for every state."""
        if not self.open_only:
            return self.states or None
        return (self.states or NON_TERMINAL_STATES) & NON_TERMINAL_STATES


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionQuery:
    """22 `listExecutions`' filters; `since` is inclusive and `until` exclusive, on `exec_ts`."""

    accounts: tuple[UUID, ...] = ()
    symbol: str | None = None
    order_id: UUID | None = None
    trade_group_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionQuery:
    """22 `listPositions`' filters: `open_only` (its default true) is `size > 0`."""

    accounts: tuple[UUID, ...] = ()
    symbol: str | None = None
    open_only: bool = True


@dataclass(frozen=True, slots=True)
class ListedOrder:
    """An order with its leg's trade group."""

    order: OrderRow
    trade_group_id: UUID | None


@dataclass(frozen=True, slots=True)
class ListedExecution:
    """A fill with the trade group of its leg, else of its order's leg."""

    execution: ExecutionRow
    trade_group_id: UUID | None


@dataclass(frozen=True, slots=True)
class OrderDetail:
    """22 `OrderWithEvents`' rows: the order in scope, its events when asked (none otherwise),
    the first `MAX_EVENT_PAGE` of them, and its fills, oldest first, the first
    `MAX_ORDER_EXECUTIONS`; `more_events` and `more_executions` when either holds more than that,
    so a reader that must serve it whole refuses it (#4997)."""

    scoped: ScopedOrder
    events: tuple[OrderEventRow, ...]
    executions: tuple[ListedExecution, ...]
    more_events: bool = False
    more_executions: bool = False


@dataclass(frozen=True, slots=True)
class PositionOutOfScope:
    """`position`'s answer for an id outside the scope: the account holding the id, None when none
    does, for the refusal's audit alone, never for the answer (SR-E29-13)."""

    account_id: UUID | None


class OmsReadStore(Protocol):
    """The OMS REST reads (module docstring); each raises `AccountsOutOfScope` for a named account
    outside the scope, and `StorageError` or `OrderStoreError` when the store does not serve."""

    async def orders(
        self, scope: AccountScope, query: OrderQuery, *, environment: Environment,
        after: Keyset | None, limit: int,
    ) -> tuple[ListedOrder, ...]: ...  # fmt: skip

    async def order(
        self, scope: AccountScope, order_id: UUID, *, environment: Environment, events: bool
    ) -> OrderDetail | OutOfScope: ...

    async def executions(
        self, scope: AccountScope, query: ExecutionQuery, *, environment: Environment,
        after: Keyset | None, limit: int,
    ) -> tuple[ListedExecution, ...]: ...  # fmt: skip

    async def closed_pnl(
        self,
        scope: AccountScope,
        query: ExecutionQuery,
        *,
        environment: Environment,
        after: Keyset | None,
        limit: int,
    ) -> tuple[ListedExecution, ...]:
        """`listClosedPnl`'s interim source (22): the fills that carry a closed PnL, as
        `executions` lists them."""
        ...  # fmt: skip

    async def positions(
        self, scope: AccountScope, query: PositionQuery, *, environment: Environment
    ) -> tuple[PositionRow, ...]: ...

    async def position(
        self, scope: AccountScope, position_id: UUID, *, environment: Environment
    ) -> PositionRow | PositionOutOfScope: ...
