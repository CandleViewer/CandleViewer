"""In-memory `FlagStore` and audit emitter for the E42-T03 flag-service tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from candleviewer.admin.flags import FlagSpec, StoredFlag
from candleviewer.admin.flags.store import FlagWrite, StaleWriteError, StoreUnavailableError

T0 = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


class FakeFlagStore:
    def __init__(self) -> None:
        self.rows: dict[str, StoredFlag] = {}
        self.down = False
        self.loads = 0
        self.writes: list[FlagWrite] = []

    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
        for spec in specs:
            self.rows.setdefault(spec.key, StoredFlag(spec.default, updated_at=T0))

    async def load(self) -> Mapping[str, StoredFlag]:
        self.loads += 1
        if self.down:
            raise StoreUnavailableError("down")
        return dict(self.rows)

    async def write(self, change: FlagWrite) -> StoredFlag:
        if self.down:
            raise StoreUnavailableError("down")
        current = self.rows[change.key]
        if current.updated_at != change.expected_updated_at:
            raise StaleWriteError(current)
        assert current.updated_at is not None
        row = replace(
            current,
            value=change.value,
            user_overrides=dict(change.user_overrides),
            updated_at=current.updated_at + timedelta(seconds=1),
            updated_by=change.actor,
        )
        self.rows[change.key] = row
        self.writes.append(change)
        return row


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.records.append((action, kwargs))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now
