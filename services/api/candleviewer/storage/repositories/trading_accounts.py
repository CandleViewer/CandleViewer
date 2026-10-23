"""The principal-free read of the account an order is signed for (E29-T04 #913, slice 3).

An account by its id, whatever its status: its environment, `exchange_uid`, soft delete and the id
of its one `active`, unrevoked key, never a key column (21 Sec.3.2.1, Sec.3.2.2). It takes no
principal: only `oms_wiring.py` may name it (C-12.4, `test_oms_system_reads_callers.py`), and the
order route asks it only after its RBAC check (24 Sec.8.4 steps 2 and 4).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from candleviewer.domain.primitives import Environment


@dataclass(frozen=True, slots=True)
class TradingAccountRow:
    account_id: UUID
    environment: Environment
    exchange_uid: str
    deleted: bool
    active_key_id: UUID | None


class TradingAccountReads(Protocol):
    async def read_account(self, account_id: UUID) -> TradingAccountRow | None:
        """The row, or None for no such account; a store failure raises (`StorageError`)."""
        ...


class InMemoryTradingAccountReads:
    """`TradingAccountReads` over the rows a test seeds."""

    def __init__(self, *rows: TradingAccountRow) -> None:
        self._rows = {row.account_id: row for row in rows}

    async def read_account(self, account_id: UUID) -> TradingAccountRow | None:
        await asyncio.sleep(0)
        return self._rows.get(account_id)
