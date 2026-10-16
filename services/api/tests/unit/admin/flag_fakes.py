"""In-memory `FlagStore` and audit emitter for the E42-T03 flag-service tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from candleviewer.admin.flags import FlagSpec, StoredFlag
from candleviewer.admin.flags.store import (
    FlagWrite,
    Prepare,
    StaleWriteError,
    StoreUnavailableError,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.actions import validate_action

T0 = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


class FakeFlagStore:
    def __init__(self) -> None:
        self.rows: dict[str, StoredFlag] = {}
        self.down = False
        self.loads = 0
        self.writes: list[FlagWrite] = []
        #: When set, `load` blocks until it is set (a hung or slow store).
        self.hold: asyncio.Event | None = None
        self.crash: Exception | None = None
        #: Runs after the snapshot is taken (e.g. a write committing mid-load).
        self.on_load: Callable[[], None] | None = None
        self.on_lock: Callable[[], None] | None = None
        self.fail_write = False

    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
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

    async def write(self, key: str, prepare: Prepare) -> StoredFlag:
        if self.on_lock is not None:
            self.on_lock()  # a commit that lands before this write takes the row lock
        if self.down:
            raise StoreUnavailableError("down")
        current = self.rows[key]
        change = await prepare(current)  # under the (simulated) row lock
        if self.fail_write:
            raise StoreUnavailableError("down mid-write")
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


class NoStepUp(Exception):
    """The fake's refusal: the session holds no fresh elevation of `args[0]`."""


class FakeStepUp:
    """Records every class a write demands; refuses the classes in `missing`."""

    def __init__(self, missing: frozenset[str] = frozenset()) -> None:
        self.demanded: list[str] = []
        self.missing = missing

    async def __call__(self, principal: AuditPrincipal, action_class: str) -> None:
        self.demanded.append(action_class)
        if action_class in self.missing:
            raise NoStepUp(action_class)


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        validate_action(action)  # an unregistered action is refused, as `audit.emit` refuses it
        self.records.append((action, kwargs))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now
