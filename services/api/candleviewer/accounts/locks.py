"""One in-process lock per account for the account delete and the key revoke (E27-S04, #898).

A delete and a revoke of the same account run one at a time, each deciding after it holds the lock:
two concurrent deletes write one `account.deleted` and destroy each key once; two revokes of one key
destroy it once; two revokes of an account's last two keys never both read the other as signable;
a revoke waiting on a delete then reads the account gone. The table holds an entry only while a
caller holds or waits on its lock (C-2.18): its size is bounded by the requests in flight. It is
in-process only: a second process serving the same database is not serialised by it (the store's
own checks still hold there).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

__all__ = ["AccountLocks"]


class AccountLocks:
    """`hold(account_id)`: the account's lock for the block; created on first use, dropped once no
    caller holds or waits on it. Run on one event loop (the serving loop)."""

    def __init__(self) -> None:
        self._held: dict[UUID, tuple[asyncio.Lock, int]] = {}

    def __len__(self) -> int:
        return len(self._held)

    @asynccontextmanager
    async def hold(self, account_id: UUID) -> AsyncIterator[None]:
        lock, users = self._held.get(account_id, (None, 0))
        lock = asyncio.Lock() if lock is None else lock
        self._held[account_id] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._held[account_id]
            if users == 1:
                del self._held[account_id]
            else:
                self._held[account_id] = (lock, users - 1)
