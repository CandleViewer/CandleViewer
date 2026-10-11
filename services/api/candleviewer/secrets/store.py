"""Persistence port for `api_keys` envelope columns.

Records are plain dicts keyed by `CredentialRow` field names, so the Postgres adapter in
M10 (`storage`) satisfies this Protocol structurally without importing M2 (C-3.2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

#: `(action, fields)` -> durable, hash-chained audit append (write-ahead; raises to refuse).
AuditSink = Callable[[str, dict[str, str]], Awaitable[None]]


class CredentialStore(Protocol):
    async def insert(self, record: dict[str, Any]) -> None: ...
    async def get(self, key_id: UUID) -> dict[str, Any] | None: ...
    async def mark_revoked(self, key_id: UUID) -> None: ...
    async def ids_at_kek_version(self, version: int, limit: int) -> list[UUID]: ...
    async def count_at_kek_version(self, version: int) -> int: ...
    async def rewrap(
        self, key_id: UUID, *, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        """Compare-and-set on `kek_version`; True iff this call moved the row."""
        ...

    async def touch_last_used(self, key_id: UUID) -> None: ...


class InMemoryCredentialStore:
    """Test fake. Never used with real credentials."""

    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}

    async def insert(self, record: dict[str, Any]) -> None:
        self.rows[record["id"]] = dict(record)

    async def get(self, key_id: UUID) -> dict[str, Any] | None:
        row = self.rows.get(key_id)
        return dict(row) if row is not None else None

    async def mark_revoked(self, key_id: UUID) -> None:
        if key_id in self.rows:
            self.rows[key_id]["revoked"] = True

    async def ids_at_kek_version(self, version: int, limit: int) -> list[UUID]:
        ids = [k for k, r in self.rows.items() if r["kek_version"] == version and not r["revoked"]]
        return ids[:limit]

    async def count_at_kek_version(self, version: int) -> int:
        return len(await self.ids_at_kek_version(version, len(self.rows) + 1))

    async def rewrap(
        self, key_id: UUID, *, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        row = self.rows.get(key_id)
        if row is None or row["kek_version"] != from_version:
            return False
        row["dek_ref"], row["kek_version"] = dek_ref, kek_version
        return True

    async def touch_last_used(self, key_id: UUID) -> None:
        return None
