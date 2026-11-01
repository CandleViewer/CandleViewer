"""Rule authoring refusal records (E35, #4834 G-2; 22 "Rule authoring refusal records").

The records a refused rule write leaves, `rules.scope_denied` and `rules.arm` (a refused mode
change), are held to a budget per acting user and per action, across all of the user's sessions,
by the mechanism of "Audit budget" in `queryAuditLog` (`api/audit_budget.py`): one instance of
refusals alone per action (`read_action=None`, the summary's object `rule`), each with its own
count, window and summary record, apart from the `/admin/audit*` budget and the view-as one. One
cap applies to every role, the Owner's included, `Settings.rules_refusal_budget_per_hour` (default
120 in a rolling hour); the tracking, in-flight and window limits are the audit budget's settings.

Over the cap nothing is written for that refusal, which is answered with its own status as before:
it is counted in `rule_authoring_refusals_suppressed_total`, and its count rides the user's next
record of that action or, when none follows, one `suppressed_summary` record per user, action and
window, so a refusal is never dropped (C-2.9). A due record that cannot be written raises
`AuditUnavailable`, so the refusal is `503 audit_unavailable` and nothing changes.

`admin.wiring.audit_writer_sink` and `api.rules_actor.make_rules_audit` decide what comes here: a
refusal a request caused, with an acting user. A rule action's own denial at run time
(`rule_action_scope_denied`), the boot-time `rule.system_rule_tampered` and every other record stay
one write each, never budgeted. The app builds one instance for both hooks, so both writers of
`rules.scope_denied` share one count per user; the lifespan runs its flush task and drains it
before the audit writer stops.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

from candleviewer.api.audit_budget import (
    WRITE_TIMEOUT_S,
    AuditBudgetFlushTask,
    AuditRecordBudget,
    BudgetActor,
    BudgetWriteFailed,
)
from candleviewer.audit.writer import AuditUnavailable

SCOPE_DENIED: Final = "rules.scope_denied"
ARM: Final = "rules.arm"
#: The budgeted actions, an instance each: an instance writes one action.
ACTIONS: Final = (SCOPE_DENIED, ARM)
SUMMARY_KIND: Final = "rule"  # the object of the out-of-cap summary records


class _Emitter(Protocol):
    @property
    def emit(self) -> Callable[..., Awaitable[None]]: ...


class RuleRefusalFlush:
    """The two budgets' flush tasks as one lifespan step: a `flush_due` tick each, and at shutdown
    each budget's outstanding counts written (`drain`) before the audit writer stops."""

    def __init__(self, tasks: tuple[AuditBudgetFlushTask, ...]) -> None:
        self._tasks = tasks

    @property
    def running(self) -> bool:
        return all(task.running for task in self._tasks)

    def start(self) -> None:
        for task in self._tasks:
            task.start()

    async def run_once(self) -> None:
        for task in self._tasks:
            await task.run_once()

    async def stop(self) -> int:
        """Stop each tick and drain each budget: how many users still hold counts (logged)."""
        left = 0
        for task in self._tasks:
            left += await task.stop()
        return left


class RuleRefusalBudgets:
    """The rule refusal records' budgets, one per action in `ACTIONS` (module docstring)."""

    def __init__(
        self,
        audit: _Emitter,
        *,
        per_hour: int = 120,
        tracked_users: int = 1024,
        inflight_cap: int = 64,
        flush_seconds: float = 300.0,
        write_timeout_s: float = WRITE_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        on_suppressed: Callable[[], None] = lambda: None,
    ) -> None:
        self._audit, self._on_suppressed = audit, on_suppressed
        self._budgets = {
            action: AuditRecordBudget(
                per_hour=per_hour,
                owner_per_hour=per_hour,
                tracked_users=tracked_users,
                inflight_cap=inflight_cap,
                flush_seconds=flush_seconds,
                write_timeout_s=write_timeout_s,
                clock=clock,
                read_action=None,
                denial_action=action,
                object_kind=SUMMARY_KIND,
            )
            for action in ACTIONS
        }
        self.flush = RuleRefusalFlush(
            tuple(AuditBudgetFlushTask(budget, audit) for budget in self._budgets.values())
        )

    def budget(self, action: str) -> AuditRecordBudget:
        return self._budgets[action]

    async def write(self, action: str, user: str, fields: dict[str, Any]) -> bool:
        """`action`'s refusal record for `user`, the acting user's id, within that user's budget of
        that action. True: written ahead of the answer, carrying any count held for it. False: over
        the cap, counted, nothing written. `AuditUnavailable`: due and unwritable."""
        # Keyed by the acting user, across sessions. One cap applies to all, so every user is
        # tracked in the user map (`owner=False`), never the few entries kept apart for Owners.
        label = str(fields.get("actor_label") or user)
        actor = BudgetActor(user, label, fields.get("actor_user_id"), owner=False)
        try:
            written = await self._budgets[action].write_denial(actor, self._audit, fields)
        except BudgetWriteFailed as exc:
            raise AuditUnavailable("a due refusal record was not written") from exc
        if not written:
            self._on_suppressed()
        return written


__all__ = ["ACTIONS", "ARM", "SCOPE_DENIED", "RuleRefusalBudgets", "RuleRefusalFlush"]
