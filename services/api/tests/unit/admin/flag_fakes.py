"""In-memory `FlagStore`, audit emitter and clock for the E42-T03 flag-service tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

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
        self._locks: dict[str, asyncio.Lock] = {}

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

    async def write(self, key: str, prepare: Prepare) -> StoredFlag:
        if self.on_lock is not None:
            self.on_lock()  # a commit that lands before this write takes the row lock
        if self.down:
            raise StoreUnavailableError("down")
        async with self._locks.setdefault(key, asyncio.Lock()):  # the row lock (`FOR UPDATE`)
            current = self.rows.get(key)
            if current is None:  # its start-up `ensure` failed, as the port says
                raise StoreUnavailableError("no row")
            change = await prepare(current)
            if self.fail_write:
                raise StoreUnavailableError("down mid-write")
            if current.updated_at != change.expected_updated_at:
                raise StaleWriteError(current)
            assert current.updated_at is not None and change.key == key
            row = replace(
                current,
                value=change.value,
                user_overrides=dict(change.user_overrides),
                updated_at=current.updated_at + timedelta(seconds=1),
                updated_by=change.actor,
            )
            self.rows[key] = row
            self.writes.append(change)
            return row


class FakeUsers:
    """A `UserDirectory` that knows the `known` users; `hold` blocks a lookup until it is set."""

    def __init__(self, known: Iterable[UUID] = ()) -> None:
        self.known = frozenset(known)
        self.lookups: list[frozenset[UUID]] = []
        self.hold: asyncio.Event | None = None

    async def unknown(self, user_ids: frozenset[UUID]) -> frozenset[UUID]:
        self.lookups.append(user_ids)
        if self.hold is not None:
            await self.hold.wait()
        return user_ids - self.known


class NoStepUp(Exception):
    """The fake's refusal: the session holds no fresh elevation of `args[0]`."""


class FakeStepUp:
    """Records every class a write demands; refuses the classes in `missing`; `hold` blocks a
    demand until it is set (a hung auth store)."""

    def __init__(self, missing: frozenset[str] = frozenset()) -> None:
        self.demanded: list[str] = []
        self.missing = missing
        self.hold: asyncio.Event | None = None

    async def __call__(self, principal: AuditPrincipal, action_class: str) -> None:
        self.demanded.append(action_class)
        if self.hold is not None:
            await self.hold.wait()
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
