"""Builders for the dispatch envelope (24 §11.9), and the executor's ports in memory (E35-T09,
E35-T10), for the rules tests that need them."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from candleviewer.observability.metrics import Metrics
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.ports import (
    ActionAuditFields,
    EventRow,
    PrincipalView,
    RunRow,
    RunStatus,
)
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef


def action_request(
    scope: RuleScope, owner: uuid.UUID, instance: ScopeInstanceRef, **over: Any
) -> ActionRequest:
    """An armed fire's `flatten_position` request on `instance`; `over` replaces any field."""
    fields: dict[str, Any] = {
        "rule_scope": scope,
        "owner": owner,
        "environment": "demo",
        "instance": instance,
        "action_type": "flatten_position",
        "payload": Action(node_id="a1", type="flatten_position", params={}),
        "mode": "armed",
        "rule_id": str(uuid.UUID(int=7)),
        "version": 1,
        "ir_hash": "0" * 64,
        "run_id": uuid.UUID(int=8),
        "armed_by": str(owner),
    }
    return ActionRequest(**(fields | over))


@dataclass
class Switches:
    """`RuleSwitches` in memory (E35-T10), open unless a test closes one: B18 is engaged on each
    account of `engaged`, and on every account (the global verdict) once it holds `None`."""

    enabled: bool = True
    order_entry: bool = False
    engaged: set[uuid.UUID | None] = field(default_factory=set)
    rollout: bool = True

    def rules_enabled(self) -> bool:
        return self.enabled

    def order_entry_killed(self) -> bool:
        return self.order_entry

    def kill_switch_engaged(self, account_id: uuid.UUID | None) -> bool:
        return None in self.engaged or account_id in self.engaged

    def oms_actions(self) -> bool:
        return self.rollout


#: A user's principal snapshot as `Principals` serves it: active, role, Owner, admitted accounts.
Facts = tuple[bool, str | None, bool, frozenset[uuid.UUID]]


@dataclass
class Principals:
    """`PrincipalReads` in memory (E35-T10): every user an active Owner admitting `accounts`, read
    now on `clock`, unless a test gives a user other facts (`facts`), an age in seconds (`ages`),
    or leaves the user unread (`missing`)."""

    accounts: frozenset[uuid.UUID] = frozenset()
    facts: dict[uuid.UUID, Facts] = field(default_factory=dict)
    ages: dict[uuid.UUID, float] = field(default_factory=dict)
    missing: set[uuid.UUID] = field(default_factory=set)
    clock: Callable[[], float] = time.monotonic

    def principal(self, user_id: uuid.UUID) -> PrincipalView | None:
        if user_id in self.missing:
            return None
        active, role, is_owner, accounts = self.facts.get(
            user_id, (True, "owner", True, self.accounts)
        )
        return PrincipalView(
            user_id=user_id, active=active, role=role, is_owner=is_owner, trade_accounts=accounts,
            read_at=self.clock() - self.ages.get(user_id, 0.0),
        )  # fmt: skip


class Records:
    """The executor's two write-ahead ports in memory (E35-T09): the runs, their events in the
    order written, the closes and the audit records (`rules.fired`, `rules.blocked`)."""

    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, RunRow] = {}
        self.events: list[tuple[uuid.UUID, EventRow]] = []
        self.closed: dict[uuid.UUID, tuple[str, int]] = {}
        self.audits: list[tuple[str, ActionAuditFields]] = []

    async def begin(self, run: RunRow, first: EventRow) -> None:
        self.runs.setdefault(run.run_id, run)
        self.events.append((run.run_id, first))

    async def append(self, run_id: uuid.UUID, events: Sequence[EventRow]) -> None:
        self.events.extend((run_id, event) for event in events)

    async def close(self, run_id: uuid.UUID, status: RunStatus, duration_ms: int) -> None:
        self.closed.setdefault(run_id, (status, duration_ms))

    async def fired(self, fields: ActionAuditFields) -> None:
        self.audits.append(("rules.fired", fields))

    async def blocked(self, fields: ActionAuditFields) -> None:
        self.audits.append(("rules.blocked", fields))

    def results(self) -> list[tuple[str, str, str | None]]:
        """`(node, outcome, blocked_by)` of each recorded result, in order."""
        return [
            (e.payload["node_id"], e.payload["outcome"], e.payload["blocked_by"])
            for _, e in self.events
            if e.kind != "action_start"
        ]


class Counted:
    """The executor's series on a registry of their own, read back by label."""

    def __init__(self) -> None:
        self.facade = Metrics("demo")
        self.metrics = ExecutorMetrics(self.facade)

    def of(self, name: str) -> dict[tuple[str, ...], float]:
        """Every non-zero sample of counter `name`, by its labels but `env`."""
        return {
            tuple(v for k, v in sorted(s.labels.items()) if k != "env"): s.value
            for family in self.facade.registry.collect()
            for s in family.samples
            if s.name == name and s.value
        }

    def blocked(self) -> dict[str, float]:
        return {k[0]: v for k, v in self.of("rule_actions_blocked_total").items()}

    def reread(self) -> dict[str, float]:
        return {k[0]: v for k, v in self.of("rule_dispatch_reread_failed_total").items()}

    def shed(self) -> dict[str, float]:
        return {k[0]: v for k, v in self.of("rule_records_shed_total").items()}
