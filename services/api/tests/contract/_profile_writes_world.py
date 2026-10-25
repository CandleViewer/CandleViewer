"""The profile writes' provider world (#906 D2-4 to D2-6): the RBAC pack's real `create_app()` (no
network, C-13.5) over `WritableRows`, D1c's store fake (which answers the accounts too) with the
writes, and the writes' router, included here until D2-m mounts it. The app's own reads, the
binding's `GET` among them, read the same fake."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

import candleviewer.app as appmod
from candleviewer.accounts.profile_repository import ARMED_SHOWN, ArmedRule, ProfilesRepository
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
Row = port.AccountProfileRow


class WritableRows(Store):
    """The writes as Postgres answers them: `None` for an account or profile not live, `ux_ap_name`
    in any case, a stale version, the default never deleted nor moved but by the move, the version
    bumped, the hook under the store's bound seeing the row before and after, nothing kept when it
    or the commit fails. `race` is what another session did to the row since the router read it."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        Store.__init__(self)
        self.hooks: list[port.ProfileWriteAhead | None] = []  # what each write was handed
        self.fail_commit, self.timeout_s = False, roles.WRITE_AHEAD_TIMEOUT_S
        self.gone: set[uuid.UUID] = set()  # live when read, gone when written
        self.race: Callable[[Row], Row] | None = None
        self.notices: list[port.RelaxedNotice] = []  # SR-E28-01, each committed with its change
        self.deleted: list[Row] = []  # soft-deleted: gone from every read

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

    async def update_profile(
        self, scope: OwnerScope, account_id: uuid.UUID, profile_id: uuid.UUID,
        values: port.AccountProfileValues, *, expected_version: int | None,
        write_ahead: port.ProfileWriteAhead | None = None,
    ) -> Row | None:  # fmt: skip
        self.hooks.append(write_ahead)
        return await self._change("update", scope, account_id, profile_id, values, expected_version)

    async def delete_profile(
        self, scope: OwnerScope, account_id: uuid.UUID, profile_id: uuid.UUID, *,
        expected_version: int | None, write_ahead: port.ProfileWriteAhead | None = None,
    ) -> Row | None:  # fmt: skip
        self.hooks.append(write_ahead)
        return await self._change("delete", scope, account_id, profile_id, None, expected_version)

    async def set_default_profile(
        self, scope: OwnerScope, account_id: uuid.UUID, profile_id: uuid.UUID, *,
        expected_binding_version: int, write_ahead: port.ProfileWriteAhead | None = None,
    ) -> port.DefaultMove | None:  # fmt: skip
        """0d-3's order: the account, its binding's version (stale before any profile is read), the
        profile; then the demoted default's hook and the new one's, each row one version on."""
        self.hooks.append(write_ahead)
        if not self._shown("profiles", scope, account_id) or account_id in self.gone:
            return None
        rows, version = self.rows[account_id], self.bindings[account_id]
        if version != expected_binding_version:
            raise port.AccountProfileStoreStaleError
        target = next((r for r in rows if r.id == profile_id), None)
        if target is None:
            return None
        if target.values.is_default:  # binding the current default writes nothing
            return port.DefaultMove(target, None, False, version)
        old = next((r for r in rows if r.values.is_default), None)
        moved = [
            (r, dataclasses.replace(
                r, version=r.version + 1, updated_by=scope.user_id, updated_at=WRITTEN,
                values=dataclasses.replace(r.values, is_default=r is target),
            ))
            for r in (old, target) if r is not None
        ]  # fmt: skip
        notices: list[port.RelaxedNotice] = []
        for before, after in moved:  # the demoted default's hook first, as the store calls them
            if write_ahead is not None:
                notice = await roles.bounded_write_ahead(write_ahead(before, after), self.timeout_s)
                notices += [] if notice is None else [notice]
        if self.fail_commit:
            raise StorageTierUnavailable("the commit failed")
        put = {before.id: after for before, after in moved}
        self.rows[account_id] = tuple(put.get(r.id, r) for r in rows)
        self.bindings[account_id] = version + 1
        self.notices += notices
        previous = None if old is None else moved[0][1]
        return port.DefaultMove(moved[-1][1], previous, True, version + 1)

    async def _change(
        self, kind: str, scope: OwnerScope, account_id: uuid.UUID, profile_id: uuid.UUID,
        values: port.AccountProfileValues | None, expected: int | None,
    ) -> Row | None:  # fmt: skip
        """An update (`values`) or a soft delete (`None`) of a live row, with the last hook."""
        rows = self.rows[account_id] if self._shown(kind, scope, account_id) else ()
        live = next((r for r in rows if r.id == profile_id and account_id not in self.gone), None)
        if live is None:
            return None
        live = live if self.race is None else self.race(live)
        if expected is not None and live.version != expected:
            raise port.AccountProfileStoreStaleError
        if values is None and live.values.is_default:
            raise port.AccountProfileStoreConflictError("default_profile")
        if values is not None and values.is_default != live.values.is_default:
            raise port.AccountProfileStoreRuleError(port.DEFAULT_MOVES_ALONE)
        if values is not None and any(
            r.id != profile_id and r.values.name.casefold() == values.name.casefold() for r in rows
        ):
            raise port.AccountProfileStoreConflictError("ux_ap_name")
        after = dataclasses.replace(
            live, version=live.version + 1, updated_by=scope.user_id, updated_at=WRITTEN,
            values=live.values if values is None else values,
            deleted_at=WRITTEN if values is None else None,
        )  # fmt: skip
        hook, notice = self.hooks[-1], None
        if hook is not None:
            notice = await roles.bounded_write_ahead(hook(live, after), self.timeout_s)
        if self.fail_commit:
            raise StorageTierUnavailable("the commit failed")
        put = [after] if values is not None else []  # a soft delete leaves every read
        self.rows[account_id] = tuple(x for r in rows for x in (put if r.id == profile_id else [r]))
        self.deleted += [] if values is not None else [after]
        self.notices += [] if notice is None else [notice]
        return after


@dataclasses.dataclass
class Rules:
    """`ArmedRules` (ruling B6) over `armed`, or `fails`; `calls` counts its reads."""

    armed: dict[uuid.UUID, list[ArmedRule]] = dataclasses.field(default_factory=dict)
    calls: int = 0
    fails: Exception | None = None

    async def armed_on(self, account_id: uuid.UUID) -> tuple[ArmedRule, ...]:
        self.calls += 1
        if self.fails is not None:
            raise self.fails
        return tuple(self.armed.get(account_id, [])[: ARMED_SHOWN + 1])  # the store's LIMIT


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
    rules: Rules
    replays: IdempotencyCache
    minted: list[uuid.UUID]
    writes: ProfileWrites  # its `warnings` port is set by the one test of it (E28-T03)

    def reset(self) -> None:
        self.rows.reset()
        self.limits.calls, self.limits.fails = 0, None
        self.world.audit.records.clear()
        self.invalidated.clear()
        self.rules.armed, self.rules.calls, self.rules.fails = {}, 0, None
        self.minted.clear()  # the ids the next creates take (`new_id`)
        self.clock[0] = 0.0  # and the router's replay cache, renewed in place (D2-4 R1C-05)
        vars(self.replays).update(vars(IdempotencyCache(clock=lambda: self.clock[0])))


def build(mp: pytest.MonkeyPatch) -> Writes:
    """The world; its reads and writes share one facade and its cache (SR-E28-15)."""
    rows, limits, clock, invalidated = WritableRows(), Limits(), [0.0], list[uuid.UUID]()
    rules, minted = Rules(), list[uuid.UUID]()
    cache = cast(Any, SimpleNamespace(invalidate=invalidated.append))
    repository = ProfilesRepository(cast(Any, rows), cache=cache)
    # `effective` is the order path's cache, which the OMS runtime is handed; no write uses it.
    wiring = SimpleNamespace(repository=repository, effective=None)
    mp.setattr(appmod, "wire_profiles", lambda *_args: wiring)
    mp.setattr(appmod, "_build_accounts_counts", lambda _settings: rows)  # the reads' accounts
    world = build_world(mp)
    writes = ProfileWrites(repository, AccountsRepository(cast(Any, rows)), limits, rules, "demo")
    ctx, replays = world.app.state.app_context, IdempotencyCache(clock=lambda: clock[0])
    audit, auth = appmod._LazyAuditEmitter(ctx.audit), ctx.auth
    router = make_profile_writes_router(
        writes, audit, world.resolver, auth=auth, replays=replays,
        new_id=lambda: minted.pop() if minted else uuid.uuid4(),
    )  # fmt: skip
    world.app.include_router(router)  # until D2-m mounts it (ruling B12)
    return Writes(world, rows, limits, clock, invalidated, rules, replays, minted, writes)
