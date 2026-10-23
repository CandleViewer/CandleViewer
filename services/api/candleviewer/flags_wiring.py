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
maintenance gate (engaged until its flags are read), no order-entry gate until `create_app`
composes the one that adds the account check (`compose_order_entry_gate`, #837 W3), so none ever
holds the maintenance check alone, and the store:
Postgres on the real backend, in memory on the fake one, a missing row seeded at the flag's default
or its seed for the process environment (`ENVIRONMENT_SEEDS`, #913 slice 3). `start()` reads
`flags.read_budget_ms` (500 ms when unset or unreadable; anything but a whole number of ms from 50
to 2000 refuses boot), ensures every flag's row, reads `desktop.backend_connection`
(`BackendConnectionFlag`) once and starts the maintenance poll and the polls of the OMS's two
flag views (`FlagView`: `oms_enabled`, `live_enabled`); `stop()` cancels the polls and the flag's
refresh.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Final, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.admin.flags.catalogue import (
    DESKTOP_BACKEND_CONNECTION,
    ENVIRONMENT_SEEDS,
    LIVE_ENABLED,
    TRADING_OMS_ENABLED,
    default_registry,
)
from candleviewer.admin.flags.maintenance import MaintenanceController, MaintenanceGate, chain_hooks
from candleviewer.admin.flags.push import FlagPush, Session, SessionDirectory
from candleviewer.admin.flags.registry import FlagKind, FlagSpec, FlagValue
from candleviewer.admin.flags.resolver import StoredFlag
from candleviewer.admin.flags.service import (
    DEFAULT_READ_BUDGET_MS,
    ENSURE_TIMEOUT_S,
    READ_BUDGET_SETTING,
    TTL_S,
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
from candleviewer.domain.order_entry import OrderEntryCheck, OrderEntryGate
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
#: How often a `FlagView` reads its flag from the store, in seconds (SEC-S3A-03), as
#: `MaintenanceController` polls: a write reaches every process within it, and the writing
#: process's own views at once, from the writer's change hook.
FLAG_POLL_S: Final = 5.0
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


def _seeds(specs: Iterable[FlagSpec], environment: str) -> list[FlagSeed]:
    """Each flag at its default, or at its seed for the process environment (#913 slice 3 Q3)."""
    return [
        FlagSeed(
            s.key,
            s.kind.value,
            s.description,
            ENVIRONMENT_SEEDS.get(s.key, {}).get(environment, s.default),
            s.is_killswitch,
            s.variants,
        )
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
    """The admin `FlagStore` port over a flag repository; a write lapses past `bound_s`, and
    `ensure` seeds a missing row for the process `environment`."""

    def __init__(self, repository: FlagRepository, *, bound_s: float, environment: str) -> None:
        self._repository, self._bound_s, self._environment = repository, bound_s, environment

    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
        with _store_errors():
            await self._repository.ensure(_seeds(specs, self._environment))

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
        environment: str,
        settings: SettingReader | None = None,
        audit: AuditEmitter,
        step_up: StepUp,
        users: UserDirectory,
        sessions: SessionDirectory,
    ) -> None:
        self.registry = default_registry()  # an unsafe definition refuses boot here
        self.gate = MaintenanceGate()
        self._order_entry_gate: OrderEntryGate | None = None
        self._relational, self._environment = relational, environment
        self._repository: Callable[[int], FlagRepository]
        if relational is None:  # the fake backend: in memory, at the environment's seeds
            memory = InMemoryFlagRepository(_seeds(self.registry.values(), environment))
            self._repository = lambda _budget_ms: memory
        else:
            self._repository = lambda ms: SqlAlchemyFlagRepository(relational, read_budget_ms=ms)
        self._settings = settings
        self._audit, self._step_up, self._users, self._sessions = audit, step_up, users, sessions
        self._poll: asyncio.Task[None] | None = None
        self._view_polls: list[asyncio.Task[None]] = []
        # #913 slice 3: the OMS's process-wide reads, built before the writer that takes their hook.
        self.oms_enabled = FlagView(self, TRADING_OMS_ENABLED)
        self.live_enabled = FlagView(self, LIVE_ENABLED)
        self._build(DEFAULT_READ_BUDGET_MS)
        self.backend_connection = BackendConnectionFlag(self)

    @property
    def order_entry_gate(self) -> OrderEntryGate:
        """The one order-entry gate, once `compose_order_entry_gate` has built it. Before that there
        is none to read, so no holder ever takes a gate without the account check (C-2.21)."""
        if self._order_entry_gate is None:
            raise RuntimeError("the order-entry gate is not composed yet: create_app composes it")
        return self._order_entry_gate

    def compose_order_entry_gate(self, *account_checks: OrderEntryCheck) -> OrderEntryGate:
        """Build the one gate, the maintenance check first and then `account_checks`: once, and
        never of the maintenance check alone."""
        if not account_checks:
            raise ValueError("the order-entry gate needs the account check")
        if self._order_entry_gate is not None:
            raise RuntimeError("the order-entry gate is composed once")
        self._order_entry_gate = OrderEntryGate(self.gate, *account_checks)
        return self._order_entry_gate

    def _build(self, budget_ms: int) -> None:
        store = StorageFlagStore(
            self._repository(budget_ms),
            bound_s=write_bound_s(budget_ms),
            environment=self._environment,
        )
        self.service = FlagService(self.registry, store, read_budget_ms=budget_ms)
        self.budget_ms = budget_ms
        push = FlagPush(self.service, self._sessions)
        self.controller = MaintenanceController(
            self.service, self.gate, notify=push.notify_maintenance, audit=self._audit
        )
        gate, effects = self.controller.gate_hook, self.controller.effects_hook
        views = (self.oms_enabled.on_change, self.live_enabled.on_change)
        self.writer = FlagWriter(
            self.service,
            self._audit,
            self._step_up,
            self._users,
            on_change=chain_hooks(gate, *views, push.flag_changed, effects),
        )

    async def start(self) -> None:
        budget_ms = await read_budget_ms(self._settings)
        if budget_ms != self.budget_ms:
            self._build(budget_ms)  # the service refuses a budget outside 50-2000 ms
        await self.service.start()
        self.backend_connection.reopen()  # closed until here, so a never-started runtime is off
        await self.backend_connection.refresh()  # the priming read; an outage keeps the default
        if self._poll is None:
            self._poll = spawn(self.controller.run(), name="feature-flag-maintenance-poll")
            self._view_polls = [
                spawn(view.run(), name=f"feature-flag-view-{view.key}")
                for view in (self.oms_enabled, self.live_enabled)
            ]

    async def stop(self) -> None:
        polls = [task for task in (self._poll, *self._view_polls) if task is not None]
        self._poll, self._view_polls = None, []
        for poll in polls:
            poll.cancel()
        if polls:
            await asyncio.wait(polls)
        await self.backend_connection.close()  # before the engine its refresh reads goes
        if self._relational is not None:
            await self._relational.dispose()


class BackendConnectionFlag:
    """`desktop.backend_connection` for the CORS layer and the CSRF guard (ADR-0038 2e): a call
    returns the last value read at once, so no request waits on the flag store, and starts a refresh
    only when none runs and the last began `TTL_S` or more ago: at most one per 30 s, outage or not.
    It is closed until `start()`, so a runtime that never starts answers off and starts no task.
    Read with no principal, from the service `start()` may rebuild; it is the catalogue default
    until a read succeeds, and an outage or an unreadable row keeps the last value (BC-D3)."""

    def __init__(
        self, runtime: FeatureFlagsRuntime, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._runtime, self._spec = runtime, runtime.registry[DESKTOP_BACKEND_CONNECTION]
        self._clock, self._started = clock, float("-inf")
        self.value = self._spec.default is True
        self._task: asyncio.Task[None] | None = None
        self._closed = True

    def __call__(self) -> bool:
        idle = self._task is None or self._task.done()
        if not self._closed and idle and self._clock() - self._started >= TTL_S:
            self._task = spawn(self.refresh(), name="desktop-backend-connection-flag")
        return self.value

    def reopen(self) -> None:
        """`FeatureFlagsRuntime.start()`: undo a `close()` (or the initial closed state), so calls
        refresh again."""
        self._closed = False

    async def close(self) -> None:
        """`FeatureFlagsRuntime.stop()`: cancel the refresh task in flight and start no other
        until `start()` runs again (C-2.18); a later call returns the last value read."""
        self._closed, task = True, self._task
        if task is not None:
            task.cancel()
            await asyncio.wait({task})

    async def refresh(self) -> None:
        self._started = self._clock()  # stamped first: a read that fails counts toward the 30 s
        service = self._runtime.service
        row = await service.stored(self._spec)
        flag = None if row is None else service.resolved(self._spec, row, None, frozenset())
        if flag is not None and not flag.unreadable:
            self.value = flag.value is True


class FlagView:
    """One boolean flag read process-wide with no principal, for a synchronous check (C-2.21; 21
    10.7): a call returns the last value read at once, so no request waits on the store. Unlike
    `BackendConnectionFlag`, which keeps its last value through a fault (BC-D3), it fails closed:
    off while unread, and whenever the store or the row cannot be read (its fail-closed value).
    The writer's change hook applies a committed write before the write returns; `run` reads the
    row every `FLAG_POLL_S` with a load of its own, never the service's snapshot, so it meets
    another process's write within one poll and never drops another reader's load. A write applied
    meanwhile bumps a generation, so a poll that read before it drops its reading, as
    `MaintenanceController` does. `first_read()` returns once the store has answered for the flag
    (the OMS startup sweep waits for it, 20 6.2)."""

    def __init__(
        self,
        runtime: FeatureFlagsRuntime,
        key: str,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.key, self._runtime, self._spec = key, runtime, runtime.registry[key]
        if self._spec.kind is not FlagKind.BOOLEAN:
            raise ValueError(f"a flag view reads a boolean flag, not {key!r}")
        self.value = self._spec.fail_closed_value is True
        self._sleep, self._generation, self._read = sleep, 0, asyncio.Event()

    def __call__(self) -> bool:
        return self.value

    async def first_read(self) -> None:
        """Return once the store has answered for the flag, by a read or a write."""
        await self._read.wait()

    async def on_change(self, key: str, before: StoredFlag | None, after: StoredFlag) -> None:
        """The writer's change hook: the committed row, applied with no await."""
        if key == self.key:
            self._generation += 1
            self._apply(after)

    async def refresh(self) -> None:
        """One poll: the stored row, read with a load of its own within the read budget."""
        generation = self._generation
        rows: Mapping[str, StoredFlag] | None = None
        try:
            async with asyncio.timeout(self._runtime.budget_ms / 1000):
                rows = await self._runtime.service.store.load()
        except Exception as exc:  # an outage or a lapsed budget: closed until a read answers
            _log().warning("feature_flag_view_unread", key=self.key, error=type(exc).__name__)
        if generation == self._generation:  # a write applied meanwhile is newer: keep it
            row = None if rows is None else rows.get(self.key) or StoredFlag(self._spec.default)
            self._apply(row)

    async def run(self) -> None:
        """Poll every `FLAG_POLL_S` until cancelled (the runtime's task)."""
        while True:
            await self.refresh()
            await self._sleep(FLAG_POLL_S)

    def _apply(self, row: StoredFlag | None) -> None:
        self.value = (
            self._runtime.service.resolved(self._spec, row, None, frozenset()).value is True
        )
        if row is not None:
            self._read.set()


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
        environment=settings.environment.value,
        settings=None if relational is None else SqlAlchemySystemSettings(relational),
        audit=audit,
        step_up=step_up,
        users=RoleStoreUsers(users),
        sessions=HubSessions(hub),
    )
