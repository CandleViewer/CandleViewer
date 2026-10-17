"""Composition-root wiring of the feature-flag service (E42-T03).

`StorageFlagStore` adapts a flag repository to the admin `FlagStore` port (`storage` may not import
`admin`, C-3.1). Rows pass as stored, so the service fails an unreadable one closed alone, as it
does a flag whose kind changed in code until a data migration rewrites the row (`ensure` is insert
only). Override `expires_at` is not read: nothing defines or writes it. A Postgres write runs under
the read budget as `statement_timeout` and `lock_timeout`, and the whole write under
`write_bound_s`, for connect, pool and commit stalls. A stale row is `StaleWriteError`; an outage,
a lapsed bound, a flag with no row and an override user deleted after the writer's check are
`StoreUnavailableError`, nothing written; what `prepare` raises reaches the writer as is.

`FeatureFlagsRuntime` is built without I/O: the registry (an unsafe definition refuses boot), the
maintenance gate (engaged until its flags are read), the composed order-entry gate, and the store:
Postgres on the real backend, in memory at the registry defaults on the fake one. `start()` reads
`flags.read_budget_ms` (500 ms when unset or unreadable; anything but a whole number of ms from 50
to 2000 refuses boot), ensures every flag's row and starts the maintenance poll.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Final, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.admin.flags.catalogue import default_registry
from candleviewer.admin.flags.maintenance import MaintenanceController, MaintenanceGate, chain_hooks
from candleviewer.admin.flags.push import FlagPush, Session, SessionDirectory
from candleviewer.admin.flags.registry import FlagSpec, FlagValue
from candleviewer.admin.flags.resolver import StoredFlag
from candleviewer.admin.flags.service import (
    DEFAULT_READ_BUDGET_MS,
    ENSURE_TIMEOUT_S,
    READ_BUDGET_SETTING,
    FlagService,
)
from candleviewer.admin.flags.store import (
    AuditEmitter,
    FlagWrite,
    Prepare,
    StaleWriteError,
    StepUp,
    StoreUnavailableError,
    UserDirectory,
)
from candleviewer.admin.flags.writes import WRITE_AWAIT_TIMEOUT_S, FlagWriter
from candleviewer.api.step_up_challenge import ChallengeText, quote_label
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.users import UserRoleStore
from candleviewer.domain.order_entry import OrderEntryGate
from candleviewer.observability import spawn
from candleviewer.settings import Settings
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.flags_sqlalchemy import (
    FlagChange,
    FlagRow,
    FlagRowMissingError,
    FlagSeed,
    SqlAlchemyFlagRepository,
    StaleFlagRowError,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.system_settings import StoredSetting
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings
from candleviewer.storage.testing.flags import InMemoryFlagRepository
from candleviewer.ws.gateway import GatewayHub

_WHOLE_MS: Final = re.compile(r"[0-9]{1,6}")
FlagRepository = SqlAlchemyFlagRepository | InMemoryFlagRepository


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class SettingReader(Protocol):
    """The read half of the system settings store (`SystemSettings`)."""

    async def get_string(self, key: str) -> StoredSetting | None: ...


def stored_flag(row: FlagRow) -> StoredFlag:
    """The row as stored: values are cast, never checked, so an unreadable one stays visible."""
    return StoredFlag(
        cast(FlagValue, row.value),
        cast(Mapping[UUID, FlagValue], row.user_overrides),
        cast(Mapping[str, FlagValue], row.role_overrides),
        row.updated_at,
        row.updated_by,
    )


def _seeds(specs: Iterable[FlagSpec]) -> list[FlagSeed]:
    return [
        FlagSeed(s.key, s.kind.value, s.description, s.default, s.is_killswitch, s.variants)
        for s in specs
    ]


@contextmanager
def _store_errors(key: str = "", own: Sequence[BaseException] = ()) -> Iterator[None]:
    try:
        yield
    except StaleFlagRowError as exc:
        raise StaleWriteError(stored_flag(exc.current)) from None
    except (StorageTierUnavailable, FlagRowMissingError, TimeoutError) as exc:
        if any(exc is mine for mine in own):
            raise
        if isinstance(exc, FlagRowMissingError):
            _log().warning("feature_flag_row_missing", key=key, row=str(exc))
        raise StoreUnavailableError(type(exc).__name__) from None


def write_bound_s(budget_ms: int) -> float:
    """A store write's bound: the lock wait (the budget), the writer's awaits, 1 s; 5 s at most."""
    return budget_ms / 1000 + WRITE_AWAIT_TIMEOUT_S + 1.0


class StorageFlagStore:
    """The admin `FlagStore` port over a flag repository; a write lapses past `bound_s`."""

    def __init__(self, repository: FlagRepository, *, bound_s: float) -> None:
        self._repository, self._bound_s = repository, bound_s

    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
        with _store_errors():
            await self._repository.ensure(_seeds(specs))

    async def load(self) -> Mapping[str, StoredFlag]:
        with _store_errors():
            rows = await self._repository.load()
        return {key: stored_flag(row) for key, row in rows.items()}

    async def write(self, key: str, prepare: Prepare) -> StoredFlag:
        own: list[BaseException] = []

        async def prepare_row(row: FlagRow) -> FlagChange:
            try:
                w = await prepare(stored_flag(row))
            except Exception as exc:
                own.append(exc)
                raise
            return FlagChange(w.value, w.user_overrides, w.expected_updated_at, w.actor)

        with _store_errors(key, own):
            async with asyncio.timeout(self._bound_s):
                return stored_flag(await self._repository.write(key, prepare_row))


async def read_budget_ms(settings: SettingReader | None) -> int:
    """`flags.read_budget_ms`, or the default when it is unset or cannot be read at boot (the
    store's own reads then fail closed); raises when it is not a whole number of ms."""
    if settings is None:
        return DEFAULT_READ_BUDGET_MS
    try:
        async with asyncio.timeout(ENSURE_TIMEOUT_S):
            row = await settings.get_string(READ_BUDGET_SETTING)
    except (StorageTierUnavailable, TimeoutError) as exc:
        _log().warning("feature_flag_read_budget_unread", error=type(exc).__name__)
        return DEFAULT_READ_BUDGET_MS
    if row is None:
        return DEFAULT_READ_BUDGET_MS
    if not _WHOLE_MS.fullmatch(row.value):
        raise ValueError(f"{READ_BUDGET_SETTING} must be a whole number of ms")
    return int(row.value)


def restate_flag_write(change: FlagWrite) -> ChallengeText:
    """`setFeatureFlag`'s fixed step-up template (#2304): the key quoted, the validated value bare
    and the user overrides the write leaves, counted; no typed confirmation (`target`)."""
    shown = json.dumps(change.value).strip('"')  # a boolean, a 0-100 rollout or a variant
    key, n = quote_label(change.key), len(change.user_overrides)
    return ChallengeText(f"Set feature flag {key} to {shown}, user overrides {n}")


class RoleStoreUsers:
    """`UserDirectory` over the user-role store, which has no roles for a user that does not
    exist or was deleted. Without a store (the fake backend) no user is known."""

    def __init__(self, store: UserRoleStore | None) -> None:
        self._store = store

    async def unknown(self, user_ids: frozenset[UUID]) -> frozenset[UUID]:
        if self._store is None:
            return user_ids
        try:
            return frozenset([u for u in user_ids if await self._store.get_roles(u) is None])
        except Exception as exc:  # an outage is the writer's: counted, logged and recorded
            if not is_storage_outage(exc):
                raise
            raise StoreUnavailableError(type(exc).__name__) from None


class HubSessions:
    """The push's `SessionDirectory` over the WS hub's authenticated sockets."""

    def __init__(self, hub: GatewayHub) -> None:
        self._hub = hub

    def authenticated(self) -> list[Session]:
        return [Session(user, roles, push) for user, roles, push in self._hub.system_sessions()]


class FeatureFlagsRuntime:
    """The flag service, writer, push, maintenance gate and order-entry gate (module docstring)."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository | None,
        *,
        settings: SettingReader | None = None,
        audit: AuditEmitter,
        step_up: StepUp,
        users: UserDirectory,
        sessions: SessionDirectory,
    ) -> None:
        self.registry = default_registry()  # an unsafe definition refuses boot here
        self.gate = MaintenanceGate()
        self.order_entry_gate = OrderEntryGate(self.gate)
        self._relational = relational
        self._repository: Callable[[int], FlagRepository]
        if relational is None:  # the fake backend: in memory, at the registry defaults
            memory = InMemoryFlagRepository(_seeds(self.registry.values()))
            self._repository = lambda _budget_ms: memory
        else:
            self._repository = lambda ms: SqlAlchemyFlagRepository(relational, read_budget_ms=ms)
        self._settings = settings
        self._audit, self._step_up, self._users, self._sessions = audit, step_up, users, sessions
        self._poll: asyncio.Task[None] | None = None
        self._build(DEFAULT_READ_BUDGET_MS)

    def _build(self, budget_ms: int) -> None:
        store = StorageFlagStore(self._repository(budget_ms), bound_s=write_bound_s(budget_ms))
        self.service = FlagService(self.registry, store, read_budget_ms=budget_ms)
        self.budget_ms = budget_ms
        push = FlagPush(self.service, self._sessions)
        self.controller = MaintenanceController(
            self.service, self.gate, notify=push.notify_maintenance, audit=self._audit
        )
        gate, effects = self.controller.gate_hook, self.controller.effects_hook
        self.writer = FlagWriter(
            self.service,
            self._audit,
            self._step_up,
            self._users,
            on_change=chain_hooks(gate, push.flag_changed, effects),
        )

    async def start(self) -> None:
        budget_ms = await read_budget_ms(self._settings)
        if budget_ms != self.budget_ms:
            self._build(budget_ms)  # the service refuses a budget outside 50-2000 ms
        await self.service.start()
        if self._poll is None:
            self._poll = spawn(self.controller.run(), name="feature-flag-maintenance-poll")

    async def stop(self) -> None:
        poll, self._poll = self._poll, None
        if poll is not None:
            poll.cancel()
            await asyncio.wait({poll})
        if self._relational is not None:
            await self._relational.dispose()


def build_feature_flags(
    settings: Settings,
    *,
    audit: AuditEmitter,
    step_up: StepUp,
    hub: GatewayHub,
    users: UserRoleStore | None,
) -> FeatureFlagsRuntime:
    relational = (
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "feature-flags")
        if settings.storage_backend == "real"
        else None
    )
    return FeatureFlagsRuntime(
        relational,
        settings=None if relational is None else SqlAlchemySystemSettings(relational),
        audit=audit,
        step_up=step_up,
        users=RoleStoreUsers(users),
        sessions=HubSessions(hub),
    )
