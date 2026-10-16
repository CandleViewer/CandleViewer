"""The port the flag service reads through (E42-T03). The Postgres adapter over
`feature_flags` / `feature_flag_overrides` (`21-database-schema.md` 3.9) implements it."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from candleviewer.admin.flags.registry import FlagSpec
from candleviewer.admin.flags.resolver import StoredFlag


class StoreUnavailableError(Exception):
    """The flag store could not be read or written."""


class FlagStore(Protocol):
    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
        """Insert a row at the spec default for every flag that has none (startup, idempotent),
        so every flag has an `updated_at` a writer can name."""

    async def load(self) -> Mapping[str, StoredFlag]:
        """Every stored flag; raises `StoreUnavailableError`."""
