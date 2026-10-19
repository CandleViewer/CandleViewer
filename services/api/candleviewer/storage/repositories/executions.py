"""Driver-free execution store surface (E29-T01 #845, `0029_oms_core`).

`executions` keeps the fills the exchange reports, append-only (21 Sec.3.3.6); every source of a
fill inserts it and `ux_exec_id` keeps one row, so a repeated `exec_id` never counts twice
(24 Sec.8.2 S4). `executions_sqlalchemy.py` is the Postgres side. Money is a `Decimal` its column
holds exactly, `fee_rate` at numeric(18,10). `apply_fill` is a fill's write-ahead step (E29-T03).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.storage.repositories.orders import (
    CommittedStep,
    OrderSide,
    OrderTransition,
    check_fields,
    typed_fields,
)

ExecType = Literal["Trade", "AdlTrade", "Funding", "BustTrade", "Settle", "SessionSettlePnl"]


@dataclass(frozen=True, slots=True, kw_only=True)
class NewExecution:
    """An `executions` row to insert; the store assigns `id`, the database `recv_ts`. An `order_id`
    must name an order of the same account: the store refuses another account's."""

    exchange_account_id: UUID
    exec_id: str
    symbol: str
    side: OrderSide
    exec_qty: Decimal
    exec_price: Decimal
    exec_value: Decimal
    exec_type: ExecType
    is_maker: bool
    exec_ts: datetime
    order_id: UUID | None = None
    order_link_id: str | None = None
    trade_group_leg_id: UUID | None = None
    exec_fee: Decimal = Decimal(0)
    fee_rate: Decimal | None = None
    fee_currency: str = "USDT"
    closed_pnl: Decimal | None = None
    mark_price: Decimal | None = None
    underlying_price: Decimal | None = None
    block_trade_id: str | None = None
    position_idx: Literal[0, 1, 2] = 0
    is_paper: bool = False

    def __post_init__(self) -> None:
        check_fields(self, _MONEY, _STAMPS)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRow(NewExecution):
    """A stored `executions` row: what was inserted, plus `id` and `recv_ts`."""

    id: UUID
    recv_ts: datetime


_MONEY: Final = {
    name: (18, 10) if name == "fee_rate" else (38, 18)
    for name in typed_fields(NewExecution, Decimal)
}
_STAMPS: Final = typed_fields(NewExecution, datetime)


@dataclass(frozen=True, slots=True, kw_only=True)
class FillTotals:
    """An order's cumulative columns after a fill (`0029_oms_core`'s names), as the caller computed
    them in `Decimal` (E29-T03 `apply_execution`): the store writes them and never derives them."""

    cum_exec_qty: Decimal
    cum_exec_value: Decimal
    avg_price: Decimal
    fee_paid: Decimal

    def __post_init__(self) -> None:
        check_fields(self, _TOTALS, ())


_TOTALS: Final = dict.fromkeys(typed_fields(FillTotals, Decimal), (38, 18))


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderFill:
    """A fill, its order's new `totals` and `step`, the compare-and-set of the order's state with
    the fill event (24 Sec.8.2 S4, S8). The execution names the step's account and order."""

    step: OrderTransition
    execution: NewExecution
    totals: FillTotals

    def __post_init__(self) -> None:
        names = (self.execution.exchange_account_id, self.execution.order_id)
        if names != (self.step.account_id, self.step.order_id):
            raise ValueError("the execution names another account or order than its step")


class ExecutionStore(Protocol):
    """Insert and account-scoped reads of `executions`."""

    async def insert(self, execution: NewExecution) -> bool:
        """Store the fill unless its account holds its `exec_id` already: True when this call
        stored it. One transaction of its own; `OrderNotFoundError` for another account's order."""
        ...

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None: ...

    async def apply_fill(self, fill: OrderFill) -> CommittedStep | None:
        """The execution and, only if it is new, the order's totals, state and event, in one
        transaction (None: a stored `exec_id`, nothing changed, S4). The compare-and-set also needs
        the stored `cum_exec_qty` plus `exec_qty` to be the new one. Any refusal writes nothing."""
        ...
