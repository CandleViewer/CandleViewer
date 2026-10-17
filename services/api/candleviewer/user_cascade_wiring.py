"""Composition-root adapters for the rule steps of the user-disable cascade (E42-T04 S5, #965).

`admin` (M21) and `rules` (M15) may not import each other: `UserDisableService` takes the ports
`RuleDisarmer` and `ScopeRefresher`, and this module, which sees both sides as `rules_store_pg`
does, implements them over the rule engine's own interfaces.

- `RuleDisarmAdapter` lists the armed rules whose `owner_user_id` is the disabled user and disarms
  one per call by `RulesManager.set_mode(rule, "disabled", ...)`, the E35 disarm interface: B9
  `DISARM` goes through `RuleLifecycle` and the statechart gateway to a chart only
  `statechart.factory` builds, and the manager writes `rules.disarm` ahead of the row (C-2.9). A
  rule the chart refuses is the manager's `RuleError`; the service goes on to the next rule.
- `ScopeRefreshAdapter` refreshes the user's entry in the rule engine's scope snapshot at once; a
  refresh that fails drops the entry (no grant, no live arming) and re-raises.

RBAC is the service's (`users:write`, SR-055); neither port is reachable from a route. Safety does
not rest on these steps: O4 soft-revokes the grants in the disable's transaction and O5 makes the
permission readers refuse a user who is not active (C-2.21).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

import structlog

from candleviewer.observability.context import current_request_id
from candleviewer.rules.manager import Actor, RulesManager, RuleStore
from candleviewer.rules.scope_state import SnapshotScopeState

#: `rules.mode` of a rule that can still act: every B9 state but `draft`, `simulating`,
#: `disarmed` and `kill_switched` projects to it (`rules.lifecycle._MODE_OF`).
ARMED: Final = "armed"
DISARMED: Final = "disabled"


class RulesNotRunning(RuntimeError):
    """The rules module is stopped (`RulesService.manager()` is `None`): nothing can be disarmed."""


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


class RuleDisarmAdapter:
    """`admin.user_disable.RuleDisarmer` over the rule store and `RulesManager`."""

    def __init__(self, store: RuleStore, manager: Callable[[], RulesManager | None]) -> None:
        self._store, self._manager = store, manager
        # One disarm at a time. `RulesManager.set_mode` has no per-rule lock, so two disarms of one
        # rule that overlap (a repeated DELETE while the first cascade runs, which AC5 makes legal)
        # both pass its `can()` pre-check while the chart is armed and both send DISARM: the second
        # is parked by `onUnhandled: defer` (CV-C06) and `rule.disarmed` is written twice. Held, the
        # second finds the rule disarmed and takes `set_mode`'s state-based no-op. Disarms are rare
        # and a few writes each, so one lock does; a lock per rule would need cleaning up.
        self._lock = asyncio.Lock()

    async def armed_rule_ids(self, user_id: uuid.UUID) -> tuple[str, ...]:
        """Ids of the live rules whose `owner_user_id` is `user_id` and that can still act, in a
        stable order. Simulating rules and drafts have no DISARM transition and place nothing."""
        owner = str(user_id)
        rows = await self._store.all()
        return tuple(
            sorted(r.id for r in rows if r.owner == owner and r.mode == ARMED and not r.deleted)
        )

    async def disarm(
        self, rule_id: str, *, user_id: uuid.UUID, actor: uuid.UUID, disabled_at: datetime
    ) -> None:
        """B9 DISARM for one rule, one at a time. A rule that is already disarmed is a no-op with no
        record, also when two disarms of it overlap; any refusal or failure is raised after one
        error line that names the rule."""
        manager = self._manager()
        if manager is None:
            raise RulesNotRunning(rule_id)
        key = disarm_key(user_id, rule_id, disabled_at)
        try:
            async with self._lock:
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
