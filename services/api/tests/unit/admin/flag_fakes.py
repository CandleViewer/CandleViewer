"""In-memory `FlagStore` and a fake clock for the E42-T03 flag-service tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime

from candleviewer.admin.flags import FlagSpec, StoredFlag
from candleviewer.admin.flags.store import StoreUnavailableError

T0 = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


class FakeFlagStore:
    def __init__(self) -> None:
        self.rows: dict[str, StoredFlag] = {}
        self.down = False
        self.loads = 0
        #: When set, `load` blocks until it is set (a hung or slow store).
        self.hold: asyncio.Event | None = None
        self.crash: Exception | None = None
        #: Runs after the snapshot is taken (e.g. a write committing mid-load).
        self.on_load: Callable[[], None] | None = None

    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
        if self.down:
            raise StoreUnavailableError("down")
        for spec in specs:
            self.rows.setdefault(spec.key, StoredFlag(spec.default, updated_at=T0))

    async def load(self) -> Mapping[str, StoredFlag]:
        self.loads += 1
        snapshot = dict(self.rows)
        if self.on_load is not None:
            self.on_load()
        if self.hold is not None:
            await self.hold.wait()
        if self.crash is not None:
            raise self.crash
        if self.down:
            raise StoreUnavailableError("down")
        return snapshot


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now
