"""Debounced `last_used_at` writer (E27-T01).

At most one write per key per interval (default 60 s) — the write-amplification guard in
21-database-schema.md §3.2.2. In-memory by design so it stays testable and cheap.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

Writer = Callable[[UUID, datetime], Awaitable[None]]


class LastUsedDebouncer:
    def __init__(self, writer: Writer, interval: timedelta = timedelta(seconds=60)) -> None:
        self._writer = writer
        self._interval = interval
        self._last: dict[UUID, datetime] = {}

    async def touch(self, key_id: UUID, now: datetime) -> bool:
        """Record use at `now` (tz-aware UTC); return True iff a write was issued."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        prev = self._last.get(key_id)
        if prev is not None and now - prev < self._interval:
            return False
        await self._writer(key_id, now)
        self._last[key_id] = now
        return True
