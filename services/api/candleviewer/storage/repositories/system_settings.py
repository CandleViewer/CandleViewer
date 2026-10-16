"""Driver-free surface of the system-scope `settings` repository (E42-T01, migration 0025).

`api` and `admin` may not import a storage driver (ADR-0003), so they type against `SystemSettings`;
`system_settings_sqlalchemy.py` implements it. Only `scope = 'system'` rows are reachable: a
per-user row of the same key is never read, locked or written. "No row" is `None`, which callers
must not paper over (the sub-account tier is never inferred, `21-database-schema.md` Sec.3.9); a
read that fails raises, it never returns `None`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredSetting:
    """One system-scope row: its text value and when it was last written (tz-aware UTC)."""

    value: str
    updated_at: datetime


#: Awaited in the write's transaction, after the write and before the commit, with the row as it
#: stood under the lock (`None`: no row yet). It writes the audit record (C-2.9). What it raises
#: rolls the write back and reaches the caller as is, so it must raise a type of its own: an
#: `OSError` would be taken for a store outage.
WriteAhead = Callable[[StoredSetting | None], Awaitable[None]]


class SystemSettings(Protocol):
    async def get_string(self, key: str) -> StoredSetting | None:
        """The row of `key`, `None` only when there is none; a failing read raises."""

    async def put_string(
        self, key: str, value: str, *, updated_by: UUID, write_ahead: WriteAhead
    ) -> StoredSetting:
        """Create or replace the row (a repeat of the stored value is a write too). Writers of one
        key queue, so `write_ahead` sees exactly the row it replaces. Returns the committed row.
        `StorageTierUnavailable`, `WriteAheadTimeout` and what the hook raises leave it unchanged.
        """


__all__ = ["StoredSetting", "SystemSettings", "WriteAhead"]
