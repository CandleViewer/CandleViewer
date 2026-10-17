"""Driver-free position and position-snapshot store surface (E29-T01 #845).

`positions` keeps the exchange's latest state per account, symbol and `position_idx`, and
`position_snapshots` its history (21 Sec.3.3.7); `positions_sqlalchemy.py` is the Postgres side.
`list_unprotected` is the naked-position alert's read (24 Sec.8.8 rule 3, C-2.6). Money is a
`Decimal` its column holds exactly, `leverage` at numeric(10,2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.storage.repositories.orders import (
    OrderStoreError,
    TpslMode,
    check_fields,
    typed_fields,
)

PositionSide = Literal["Buy", "Sell", "None"]
SnapshotReason = Literal["ws_push", "rest_reconcile", "minute_tick", "risk_eval"]
#: How far an exchange time may lie ahead of the store's clock: the ingest window's `now + 5 s`
#: (24 Sec.14.2 rule 10, `MAX_FUTURE_SKEW_MS`; the 5000 ms `recv_window` too). A later time is a
#: parse or unit error, not a push: `upsert` refuses it, and a stored one no longer blocks writes.
MAX_FUTURE_SKEW: Final = timedelta(seconds=5)


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionState:
    """The exchange's state of one position, to upsert under (account, symbol, `position_idx`);
    the store assigns a new row's `id`, the database `recv_ts` and `updated_at`."""

    exchange_account_id: UUID
    symbol: str
    size: Decimal
    position_idx: Literal[0, 1, 2] = 0
    side: PositionSide | None = None
    avg_price: Decimal | None = None
    position_value: Decimal | None = None
    leverage: Decimal | None = None
    mark_price: Decimal | None = None
    liq_price: Decimal | None = None
    bust_price: Decimal | None = None
    position_im: Decimal | None = None
    position_mm: Decimal | None = None
    unrealised_pnl: Decimal | None = None
    cur_realised_pnl: Decimal | None = None
    cum_realised_pnl: Decimal | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    trailing_stop: Decimal | None = None
    tpsl_mode: TpslMode | None = None
    adl_rank_indicator: int | None = None
    auto_add_margin: bool = False
    is_paper: bool = False
    exchange_updated_ts: datetime | None = None

    def __post_init__(self) -> None:
        check_fields(self, _STATE_MONEY, _STATE_STAMPS)


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionRow(PositionState):
    """A stored `positions` row: the state as written, plus `id`, `recv_ts` and `updated_at`."""

    id: UUID
    recv_ts: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class NewPositionSnapshot:
    """A `position_snapshots` row to append; the database assigns `id` and `snap_ts`."""

    exchange_account_id: UUID
    symbol: str
    size: Decimal
    reason: SnapshotReason
    position_idx: Literal[0, 1, 2] = 0
    avg_price: Decimal | None = None
    mark_price: Decimal | None = None
    unrealised_pnl: Decimal | None = None
    cum_realised_pnl: Decimal | None = None
    liq_price: Decimal | None = None
    equity_usd: Decimal | None = None

    def __post_init__(self) -> None:
        check_fields(self, _SNAPSHOT_MONEY, ())


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionSnapshotRow(NewPositionSnapshot):
    """A stored `position_snapshots` row: the snapshot, plus `id` and `snap_ts`."""

    id: int
    snap_ts: datetime


_STATE_MONEY: Final = {
    name: (10, 2) if name == "leverage" else (38, 18)
    for name in typed_fields(PositionState, Decimal)
}
_STATE_STAMPS: Final = typed_fields(PositionState, datetime)
_SNAPSHOT_MONEY: Final = dict.fromkeys(typed_fields(NewPositionSnapshot, Decimal), (38, 18))


class FutureDatedPositionError(OrderStoreError):
    """`exchange_updated_ts` lies more than `MAX_FUTURE_SKEW` ahead of the store's clock: refused,
    nothing written."""

    def __init__(self) -> None:
        super().__init__(f"exchange_updated_ts leads the clock by over {MAX_FUTURE_SKEW}")


class PositionStore(Protocol):
    """Upsert and account-scoped reads of `positions`."""

    async def upsert(self, state: PositionState) -> PositionRow:
        """The row becomes `state`, unless the stored row has a later `exchange_updated_ts`: then
        nothing changes and the stored row is returned, so a stale snapshot never overwrites a
        newer push (C-2.6). With either time NULL the write applies, so the OMS still owes exchange
        order for an account's updates (24 Sec.8.2 S5). A TP, SL or trailing stop of 0 or less
        is stored as NULL, since the exchange's 0 means none. A time more than `MAX_FUTURE_SKEW`
        ahead of the store's clock raises `FutureDatedPositionError` and writes nothing; a stored
        time that far ahead loses the guard, so one bad write cannot freeze the row (C-2.6)."""
        ...

    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]:
        """Positions with `size > 0`, by symbol and `position_idx` (`ix_pos_open`)."""
        ...

    async def list_unprotected(self, account_id: UUID) -> tuple[PositionRow, ...]:
        """Open positions with no stop-loss (`ix_pos_no_sl`)."""
        ...


class PositionSnapshotStore(Protocol):
    """Appends to `position_snapshots`; its readers (risk view, journal) add their reads."""

    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow: ...
