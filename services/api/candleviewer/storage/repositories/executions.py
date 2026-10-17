"""Driver-free execution store surface (E29-T01 #845, `0029_oms_core`).

`executions` keeps the fills the exchange reports, append-only (21 Sec.3.3.6); every source of a
fill inserts it and `ux_exec_id` keeps one row, so a repeated `exec_id` never counts twice
(24 Sec.8.2 S4). `executions_sqlalchemy.py` is the Postgres side. Money is a `Decimal` its column
holds exactly, `fee_rate` at numeric(18,10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.storage.repositories.orders import OrderSide, check_fields, typed_fields

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


class ExecutionStore(Protocol):
    """Insert and account-scoped reads of `executions`."""

    async def insert(self, execution: NewExecution) -> bool:
        """Store the fill unless its account holds its `exec_id` already: True when this call
        stored it. One transaction of its own; `OrderNotFoundError` for another account's order."""
        ...

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None: ...
