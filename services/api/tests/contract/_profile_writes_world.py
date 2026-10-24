"""The profile writes' provider world (#906 D2-4): the RBAC pack's real `create_app()` (no network,
C-13.5) over `WritableRows`, D1c's store fake (which answers the accounts too) with the writes, and
the writes' router, included here until D2-m mounts it."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

import candleviewer.app as appmod
from candleviewer.accounts.profile_repository import ProfilesRepository
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.api.idempotency import IdempotencyCache
from candleviewer.api.profile_writes import ProfileWrites, make_profile_writes_router
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Environment
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import account_profiles as port
from candleviewer.storage.repositories import user_roles_sqlalchemy as roles
from candleviewer.storage.repositories.accounts import OwnerScope
from tests.contract.rbac.rbac_harness import World, build_world
from tests.contract.test_account_profile_reads_provider import Store
from tests.unit.accounts.test_profile_validator import _LISTED

#: When a fake row is written: the database's clock, not the request's.
WRITTEN = datetime(2026, 10, 24, 9, tzinfo=UTC)


class WritableRows(Store):
    """The create as Postgres answers it: `None` for an account not live, `ux_ap_name` in any
    case, version 1, the hook under the store's bound, nothing kept when it or the commit fails."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        Store.__init__(self)
        self.hooks: list[port.ProfileWriteAhead | None] = []  # what each write was handed
        self.fail_commit, self.timeout_s = False, roles.WRITE_AHEAD_TIMEOUT_S
        self.gone: set[uuid.UUID] = set()  # live when read, gone when written

    async def create_profile(
        self, scope: OwnerScope, account_id: uuid.UUID, profile_id: uuid.UUID,
        values: port.AccountProfileValues, *, write_ahead: port.ProfileWriteAhead | None = None,
    ) -> port.AccountProfileRow | None:  # fmt: skip
        self.hooks.append(write_ahead)
        if not self._shown("profiles", scope, account_id) or account_id in self.gone:
            return None
        if any(r.values.name.casefold() == values.name.casefold() for r in self.rows[account_id]):
            raise port.AccountProfileStoreConflictError("ux_ap_name")
        by, at = scope.user_id, WRITTEN
        row = port.AccountProfileRow(profile_id, account_id, 1, values, by, by, at, at, None)
        if write_ahead is not None:
            await roles.bounded_write_ahead(write_ahead(None, row), self.timeout_s)
        if self.fail_commit:
            raise StorageTierUnavailable("the commit failed")
        self.rows[account_id] += (row,)
        return row


class Limits:
    """B2c's port for `demo` over B2a's `_LISTED`, or `fails`; `calls` counts its reads."""

    environment: Environment = "demo"
    calls, fails = 0, cast(Exception | None, None)

    async def listed(self, *, max_age_s: float, deadline_s: float) -> Mapping[str, Instrument]:
        self.calls += 1
        if self.fails is not None:
            raise self.fails
        return _LISTED


@dataclasses.dataclass
class Writes:
    """With the replay cache's clock (SR-E28-17) and the accounts invalidated (SR-E28-15)."""

    world: World
    rows: WritableRows
    limits: Limits
    clock: list[float]
    invalidated: list[uuid.UUID]

    def reset(self) -> None:
        self.rows.reset()
        self.limits.calls, self.limits.fails = 0, None
        self.world.audit.records.clear()
        self.invalidated.clear()


def build(mp: pytest.MonkeyPatch) -> Writes:
    """The world; its reads and writes share one facade and its cache (SR-E28-15)."""
    rows, limits, clock, invalidated = WritableRows(), Limits(), [0.0], list[uuid.UUID]()
    cache = cast(Any, SimpleNamespace(invalidate=invalidated.append))
    repository = ProfilesRepository(cast(Any, rows), cache=cache)
    # `effective` is the order path's cache, which the OMS runtime is handed; no write uses it.
    wiring = SimpleNamespace(repository=repository, effective=None)
    mp.setattr(appmod, "wire_profiles", lambda *_args: wiring)
    world = build_world(mp)
    writes = ProfileWrites(repository, AccountsRepository(cast(Any, rows)), limits, "demo")
    ctx, replays = world.app.state.app_context, IdempotencyCache(clock=lambda: clock[0])
    audit, auth = appmod._LazyAuditEmitter(ctx.audit), ctx.auth
    router = make_profile_writes_router(writes, audit, world.resolver, auth=auth, replays=replays)
    world.app.include_router(router)  # until D2-m mounts it (ruling B12)
    return Writes(world, rows, limits, clock, invalidated)
