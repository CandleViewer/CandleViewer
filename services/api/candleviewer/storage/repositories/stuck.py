"""The stuck-order detector's reads (E29-T08 #916; 24-internal-schemas.md Sec.8.13;
21-database-schema.md Sec.3.3.4, Sec.3.3.5, Sec.3.3.7; the ruling of record on #916, BQ-3, BQ-4).

What one scan reads, as plain rows: the orders whose create is in flight, that sit in `unknown`, or
whose cancel or amend is pending, each with its age (the time since its latest `order_events` row,
on the database's clock); and the open positions with no exchange-side stop that no live
`recorded_stop` row protects. Each read is of one environment's accounts (C-2.11), at most `limit`
rows, and says whether it was complete (fewer rows than `limit`): a read cut at its limit forgets
nothing (24 Sec.8.13). `SqlAlchemyStuckReads` (`stuck_sqlalchemy`) answers them on Postgres;
`InMemoryStuckReads` serves the unit tests the rows they seed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

from candleviewer.domain.primitives import Environment

__all__ = [
    "FINAL_STATES",
    "OPEN_STUCK_STATES",
    "InMemoryStuckReads",
    "NakedPositionRow",
    "StuckOrderRow",
    "StuckReadStore",
]

#: The persisted states an order never leaves (21 Sec.3.3.1): a row in one is never stuck, so a
#: row a KILL ended (`killed`, its `idempotency_state` still `in_flight`) leaves the scan.
FINAL_STATES: Final = frozenset({"filled", "cancelled", "rejected", "expired", "killed"})
#: The persisted states of `ix_orders_open` the scan reads besides the in-flight creates: `unknown`
#: and a pending cancel or amend.
OPEN_STUCK_STATES: Final = frozenset({"unknown", "pending_cancel", "pending_amend"})


@dataclass(frozen=True, slots=True)
class StuckOrderRow:
    """An order the scan read: its ids, its persisted `state`, whether its create is in flight,
    and its age in seconds, the time since its latest `order_events` row was received."""

    order_id: UUID
    account_id: UUID
    order_link_id: str
    symbol: str
    state: str
    in_flight: bool
    age_s: float


@dataclass(frozen=True, slots=True)
class NakedPositionRow:
    """An open position with no exchange-side stop and no live recorded-stop row on its closing
    side: its key and its side."""

    account_id: UUID
    symbol: str
    position_idx: int
    side: str | None


class StuckReadStore(Protocol):
    """One scan's reads; each a tuple of rows and whether the read was complete. A failure raises
    the store's error (`StorageError`), never a value (C-12.6)."""

    async def stuck_orders(
        self, environment: Environment, *, limit: int
    ) -> tuple[tuple[StuckOrderRow, ...], bool]: ...

    async def naked_positions(
        self, environment: Environment, *, limit: int
    ) -> tuple[tuple[NakedPositionRow, ...], bool]: ...


class InMemoryStuckReads:
    """`StuckReadStore` over the rows a test seeds, each read answering its environment's rows,
    oldest-first order kept, at most `limit`; `fail` makes the next reads raise."""

    def __init__(self) -> None:
        self.orders: dict[Environment, list[StuckOrderRow]] = {}
        self.positions: dict[Environment, list[NakedPositionRow]] = {}
        self.fail: BaseException | None = None
        self.reads = 0

    async def stuck_orders(
        self, environment: Environment, *, limit: int
    ) -> tuple[tuple[StuckOrderRow, ...], bool]:
        rows = await self._read(self.orders.get(environment, []))
        live = [r for r in rows if r.state not in FINAL_STATES]
        picked = [r for r in live if r.in_flight or r.state in OPEN_STUCK_STATES]
        return tuple(picked[:limit]), len(picked) < limit

    async def naked_positions(
        self, environment: Environment, *, limit: int
    ) -> tuple[tuple[NakedPositionRow, ...], bool]:
        rows = await self._read(self.positions.get(environment, []))
        return tuple(rows[:limit]), len(rows) < limit

    async def _read[T](self, rows: Sequence[T]) -> list[T]:
        await asyncio.sleep(0)
        self.reads += 1
        if self.fail is not None:
            raise self.fail
        return list(rows)
