"""`BackupCatalogue` (E42-T05 #966 BK-4): the `listBackups` / `getBackup` read model over BK-3's
`backups` store, which never selects `encryption_ref`. A page is `limit` rows, newest `started_at`
first with `id` as the tie-break, behind the incident list's keyset cursor bound to
`f"{kind}|{status}"`: one issued for other filters or by another listing is `InvalidCursor` (400),
never echoed. No store is `OpsNotWired` (501): nothing records runs before a backup engine, and an
empty page would read as "no backups" (Q3). An outage or a read past its budget is `OpsUnavailable`
(503) with a fixed message, raised outside the `except` (no cause or context; only the class is
logged). A statement the database refuses (`StorageQueryFailed`) stays a bug: the app's 500.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, TypeVar
from uuid import UUID

import structlog

from candleviewer.admin.errors import OpsNotWired, OpsUnavailable
from candleviewer.admin.ops.incidents import decode_cursor, encode_cursor
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.observability.context import current_request_id
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.backups import BackupKind, BackupRow, BackupStatus, Position

#: The whole of one read; the store caps each statement at 1 s itself (`STATEMENT_TIMEOUT`).
READ_BUDGET_S: Final = 2.0
_T = TypeVar("_T")  # not PEP 695 `[T]`: Semgrep 1.99.0 (CI) would skip the rest of this file


class BackupReads(Protocol):
    """The two reads the catalogue makes of BK-3's `BackupStore`, and nothing it could write."""

    async def page(
        self,
        kind: BackupKind | None,
        status: BackupStatus | None,
        after: Position | None,
        limit: int,
    ) -> list[BackupRow]:
        """Newest first by (`started_at`, `id`), strictly after `after`, deleted rows included."""

    async def get(self, backup_id: UUID) -> BackupRow | None: ...


@dataclass(frozen=True, slots=True)
class BackupPage:
    items: tuple[BackupRow, ...]
    next_cursor: str | None


class BackupCatalogue:
    def __init__(
        self,
        store: BackupReads | None,
        *,
        now: Callable[[], datetime] = utc_now,
        budget_s: float = READ_BUDGET_S,
    ) -> None:
        self._store, self._now, self._budget_s = store, now, budget_s

    async def page(
        self,
        *,
        kind: BackupKind | None,
        status: BackupStatus | None,
        cursor: str | None,
        limit: int,
    ) -> BackupPage:
        store = self._wired()
        binding, issued = f"{kind}|{status}", int(self._now().timestamp())
        after = decode_cursor(cursor, binding, issued) if cursor else None
        rows = await self._read("page", store.page(kind, status, after, limit + 1))
        kept = tuple(rows[:limit])
        last = kept[-1] if len(rows) > limit else None  # one extra row says "more"
        nxt = None if last is None else encode_cursor(binding, (last.started_at, last.id), issued)
        return BackupPage(kept, nxt)

    async def get(self, backup_id: UUID) -> BackupRow | None:
        """The row, a deleted artefact's included; `None` when the catalogue has no such id."""
        return await self._read("get", self._wired().get(backup_id))

    def _wired(self) -> BackupReads:
        if self._store is None:
            raise OpsNotWired("backups: no catalogue wired")
        return self._store

    async def _read(self, op: str, pending: Awaitable[_T]) -> _T:
        try:
            async with asyncio.timeout(self._budget_s):
                return await pending
        except (TimeoutError, StorageTierUnavailable) as exc:  # an outage, or the budget spent
            structlog.get_logger(__name__).warning(
                "admin_backups.read_failed",
                op=op,
                error=type(exc).__name__,
                request_id=current_request_id(),
            )
        raise OpsUnavailable("backups: store unavailable")
