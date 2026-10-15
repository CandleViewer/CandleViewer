"""The port the flag service reads and writes through (E42-T03). The Postgres adapter over
`feature_flags` / `feature_flag_overrides` (`21-database-schema.md` 3.9) implements it."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from candleviewer.admin.flags.registry import FlagSpec, FlagValue
from candleviewer.admin.flags.resolver import StoredFlag


class StoreUnavailableError(Exception):
    """The flag store could not be read or written."""


class StaleWriteError(Exception):
    """`expected_updated_at` no longer matches the stored row; `current` is the row now."""

    def __init__(self, current: StoredFlag) -> None:
        super().__init__("stale write")
        self.current = current


@dataclass(frozen=True, slots=True)
class FlagWrite:
    key: str
    value: FlagValue
    user_overrides: Mapping[UUID, FlagValue]
    expected_updated_at: datetime
    actor: UUID


class FlagStore(Protocol):
    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
        """Insert a row at the spec default for every flag that has none (startup, idempotent),
        so every flag has an `updated_at` a writer can name."""

    async def load(self) -> Mapping[str, StoredFlag]:
        """Every stored flag; raises `StoreUnavailableError`."""

    async def write(self, change: FlagWrite) -> StoredFlag:
        """Lock the row, compare `updated_at` with `change.expected_updated_at` and write.
        Raises `StaleWriteError` on a mismatch and `StoreUnavailableError`. The comparison is at
        the precision the API serialises `updated_at` with, so a value read back through
        `GET /admin/feature-flags` always matches its row."""
