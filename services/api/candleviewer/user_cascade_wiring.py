"""Composition-root adapters for the user-disable cascade (E42-T04 S5, S6; #965).

`admin` (M21) and `rules` (M15) may not import each other: `UserDisableService` takes the ports
`RuleDisarmer` and `ScopeRefresher`, and this module, which sees both sides as `rules_store_pg`
does, implements them over the rule engine's own interfaces.

- `RuleDisarmAdapter` lists the armed rules whose `owner_user_id` is the disabled user and disarms
  one per call by `RulesManager.set_mode(rule, "disabled", ...)`, the E35 disarm interface: B9
  `DISARM` goes through `RuleLifecycle` and the statechart gateway to a chart only
  `statechart.factory` builds, and the manager writes `rules.disarm` ahead of the row (C-2.9). A
  rule the chart refuses is the manager's `RuleError`; the service goes on to the next rule. B9
  handles `DISARM` only in armed, cooling_down and paused_degraded, so a rule that is evaluating,
  acting, pending confirmation or spent stays armed behind O4 and O5 until a repeat, though
  UL-AC02 of the STRIDE appendix says it "reaches disarmed" (#3226). A rule is disarmed by one
  call at a time in the process, through whichever adapter (the manager has no per-rule lock; a
  manual mode change is not covered, #3227), and only the user's own: the adapter acts as the
  Owner, who sees every rule, so a rule that is not the user's is refused.
- `ScopeRefreshAdapter` refreshes the user's entry in the rule engine's scope snapshot at once; a
  refresh that fails drops the entry (no grant, no live arming) and re-raises.
- `build_user_disable_service` (S6) composes the service behind `DELETE /users/{userId}`.

RBAC is the service's (`users:write`, SR-055); neither port is reachable from a route. Safety does
not rest on these steps: O4 soft-revokes the grants in the disable's transaction and O5 makes the
permission readers refuse a user who is not active (C-2.21).
"""

from __future__ import annotations

import asyncio
import uuid
import weakref
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.admin.user_disable import AuditEmitter, UserDisableService
from candleviewer.auth.invite_repository import InviteAudit
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.session_service import RevocationSink
from candleviewer.auth.step_up import PositionStateProvider
from candleviewer.observability.context import current_request_id
from candleviewer.rules.manager import Actor, RulesManager, RuleStore
from candleviewer.rules.scope_state import SnapshotScopeState
from candleviewer.settings import Settings
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from candleviewer.storage.repositories.user_lifecycle_sqlalchemy import (
    SqlAlchemyUserLifecycleStore,
)

if TYPE_CHECKING:
    from candleviewer.auth.service import AuthService
    from candleviewer.rules.service import RulesService

#: `rules.mode` of a rule that can still act: every B9 state but `draft`, `simulating`,
#: `disarmed` and `kill_switched` projects to it (`rules.lifecycle._MODE_OF`).
ARMED: Final = "armed"
DISARMED: Final = "disabled"


class RulesNotRunning(RuntimeError):
    """The rules module is stopped (`RulesService.manager()` is `None`): nothing can be disarmed."""


class RuleNotOwned(RuntimeError):
    """The rule does not exist, or its `owner_user_id` is not the user being disabled: the adapter
    disarms that user's rules and no one else's, whatever id it is given."""


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def disarm_key(user_id: uuid.UUID, rule_id: str, disabled_at: datetime) -> str:
    """The `Idempotency-Key` of one rule's disarm in one disable: a pure function of the user, the
    rule and the disable's instant, so a disable always sends the same key and no two disables
    share one. The instant matters: `RulesManager.set_mode` replays the first answer for a key it
    has already seen (per process), so a key of (user, rule) alone would let a second disable of
    the same user skip a rule that was enabled and armed again in between."""
    stamp = disabled_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"user-disabled:{user_id}:{rule_id}:{stamp}"


def _acting_owner(actor: uuid.UUID) -> Actor:
    """The Owner who disabled the user (`users:write` is checked by the service), as the rule
    engine's `Actor`: every rule is visible to them, and they carry no session and no step-up,
    which a disarm needs neither of."""
    return Actor(user_id=str(actor), session_id="", is_owner=True)


#: The lock of each rule that a disarm holds or awaits, shared by every adapter in the process, so
#: the composition root need not build just one. Weak values: a rule's lock is dropped once no
#: disarm holds or awaits it, so the map never outgrows the disarms in flight.
_DISARM_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def _disarm_lock(rule_id: str) -> asyncio.Lock:
    """The one lock of `rule_id`'s disarms. `RulesManager.set_mode` has no per-rule lock, so two
    disarms of a rule that overlap (a repeated DELETE while the first cascade runs, which AC5
    makes legal) both pass its `can()` pre-check while the chart is armed and both send DISARM:
    the second is parked by `onUnhandled: defer` (CV-C06) and `rule.disarmed` is written twice.
    Held, the second finds the rule disarmed and takes `set_mode`'s state-based no-op. Disarms of
    different rules never wait for each other, so a slow one cannot eat another's step bound."""
    lock = _DISARM_LOCKS.get(rule_id)
    if lock is None:
        lock = _DISARM_LOCKS[rule_id] = asyncio.Lock()
    return lock


class RuleDisarmAdapter:
    """`admin.user_disable.RuleDisarmer` over the rule store and `RulesManager`."""

    def __init__(self, store: RuleStore, manager: Callable[[], RulesManager | None]) -> None:
        self._store, self._manager = store, manager

    async def armed_rule_ids(self, user_id: uuid.UUID) -> tuple[str, ...]:
        """Ids of the live rules whose `owner_user_id` is `user_id` and that can still act, in a
        stable order. Simulating rules and drafts have no DISARM transition and place nothing."""
        owner = str(user_id)
        rows = await self._store.all()
        return tuple(
            sorted(r.id for r in rows if r.owner == owner and r.mode == ARMED and not r.deleted)
        )

    async def _require_owned(self, rule_id: str, user_id: uuid.UUID) -> None:
        """The acting Owner sees every rule, so the id is not trusted: `RuleNotOwned` unless the
        row exists and is the user's, read from the store the listing reads (C-12.4)."""
        row = await self._store.get(rule_id)
        if row is None or row.owner != str(user_id):
            raise RuleNotOwned(rule_id)

    async def disarm(
        self, rule_id: str, *, user_id: uuid.UUID, actor: uuid.UUID, disabled_at: datetime
    ) -> None:
        """B9 DISARM for one of `user_id`'s rules, one at a time per rule. A rule that is already
        disarmed is a no-op with no record, also when two disarms of it overlap; a rule that is not
        the user's, a stopped rules module and any refusal or failure are raised after one error
        line that names the rule. A cancellation (the step's bound cutting the call) is not logged
        here (#3227)."""
        key = disarm_key(user_id, rule_id, disabled_at)
        try:
            async with _disarm_lock(rule_id):
                manager = self._manager()
                if manager is None:
                    raise RulesNotRunning(rule_id)
                await self._require_owned(rule_id, user_id)
                await manager.set_mode(rule_id, DISARMED, _acting_owner(actor), key)
        except Exception as exc:
            _log().error(
                "users.disable.rule_not_disarmed",
                rule_id=rule_id,
                target_user_id=str(user_id),
                error=type(exc).__name__,
                code=getattr(exc, "code", None),
                request_id=current_request_id(),
            )
            raise


class ScopeRefreshAdapter:
    """`admin.user_disable.ScopeRefresher` over `RulesService.scope_state`."""

    def __init__(self, state: Callable[[], SnapshotScopeState | None]) -> None:
        self._state = state

    async def refresh(self, user_id: uuid.UUID) -> None:
        """Re-read the user's grants and permissions. Any way out but success, a raise or a
        cancellation (the step's bound cutting a hung read), drops the entry first: an owner never
        loaded has no grant and cannot arm live (`rules.scope_state`), so the rules fail closed."""
        state = self._state()
        if state is None:  # the fake backend wires no scope: nothing scoped runs there (501)
            return
        try:
            await state.refresh(user_id)
        except BaseException:
            state.invalidate(user_id)
            raise


class NoOrderCounter:
    """No order has a user on main (UL-F9): the count is unknown, never 0, so a disable needs the
    acknowledgement (AC7), as for positions. Replace with the OMS read model."""

    async def open_order_count(self, user_id: str) -> int | None:
        return None


# The three auth services below exist only once `AuthService.start()` ran, so they are looked up
# when a step runs, not when the service is built: a step that runs before fails alone (R7).


class _AuthSessions:
    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    async def revoke_all(self, user_id: str, *, reason: str) -> tuple[SessionRecord, ...]:
        return await self._auth.sessions.revoke_all(user_id, reason=reason)


class _AuthChart:  # B16 REVOKE: its action writes `auth.session_revoked` (R5)
    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    async def revoke(self, record: SessionRecord, now: datetime, reason: str) -> None:
        await self._auth.step_up.chart.revoke(record, now, reason)


class _AuthInvites:
    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    async def revoke(self, user_id: uuid.UUID, *, audit: InviteAudit) -> None:
        await self._auth.invites.revoke(user_id, audit=audit)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_user_disable_service(
    settings: Settings,
    *,
    auth: AuthService,
    rules: RulesService,
    rule_store: RuleStore,
    audit: AuditEmitter,
    positions: PositionStateProvider,
    publish_revocation: RevocationSink,
    clock: Callable[[], datetime] | None = None,
) -> UserDisableService | None:
    """The disable cascade behind `DELETE /users/{userId}`; `None` on the fake backend, which has
    no store (the route then answers 501). `rule_store` is the one `rules` is bound to, `clock`
    the app's (the keyless-testnet clock stamps sessions and B16). No I/O: the engine is lazy."""
    if settings.storage_backend != "real":
        return None
    dsn = settings.pg_dsn.get_secret_value()
    relational = SqlAlchemyRelationalRepository(dsn, "user-lifecycle")
    store = SqlAlchemyUserLifecycleStore(
        relational,
        owner_floor=lambda current, new, owners: assert_owner_floor(
            current_roles=current, new_roles=new, active_owner_count=owners
        ),
    )
    return UserDisableService(
        store,
        audit,
        positions=positions,
        orders=NoOrderCounter(),
        sessions=_AuthSessions(auth),
        session_rows=SqlAlchemySessionRepository(
            relational, lambda **fields: SessionRecord.model_validate(fields)
        ),
        chart=_AuthChart(auth),
        publish_revocation=publish_revocation,
        invites=_AuthInvites(auth),
        rules=RuleDisarmAdapter(rule_store, rules.manager),
        scope=ScopeRefreshAdapter(lambda: rules.scope_state),
        clock=clock or _utc_now,
    )
