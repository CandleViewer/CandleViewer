"""The executor's write-ahead ports (24 §11.5 "The records written ahead"; RE-R1, C-2.9).

`rules` may not import `storage` or `audit` (`forbidden-M15`), so the run row, its events and the
action's audit record go through two ports the composition root binds (`rules_oms_wiring`):
`RunRecords` over the rules repository and `ActionAudit` over the audit writer. The rows here are
what crosses them: never a parameter's value, a figure or a credential in an audit record, and the
input snapshot only in the run row, which no log line carries (21 §3.4.3: financial, confidential).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

from candleviewer.rules.executor.results import BlockedBy
from candleviewer.rules.ir.canonical import dec_str
from candleviewer.rules.ir.models import TriggerType
from candleviewer.rules.scope import ActionRequest, EvaluableMode

#: `rule_runs.trigger_reason`, the values the `rr_trigger` CHECK admits (`0013_rules`).
TriggerReason = Literal[
    "tick", "bar_close", "fill", "manual", "schedule", "position_change", "alert"
]
RunStatus = Literal["running", "ok", "error", "aborted", "throttled"]
EventKind = Literal["action_start", "action_ok", "action_fail"]
EventSeverity = Literal["info", "warning", "error"]
SnapshotValue = str | bool | None

_REASON_OF: Final[Mapping[str, TriggerReason]] = {
    "on_bar_close": "bar_close", "on_order_fill": "fill",
    "on_position_open": "position_change", "on_position_close": "position_change",
    "on_position_update": "position_change", "on_timer": "schedule", "on_schedule": "schedule",
}  # fmt: skip
#: Each IR trigger type's `trigger_reason` (21 §3.4.3, BQ-3): every type not named above is `tick`.
TRIGGER_REASON: Final[Mapping[str, TriggerReason]] = MappingProxyType(
    {t: _REASON_OF.get(t, "tick") for t in get_args(TriggerType)}
)


def trigger_reason(trigger_type: str) -> TriggerReason:
    """The run row's `trigger_reason` for an evaluation's trigger type; `tick` for any other."""
    return TRIGGER_REASON.get(trigger_type, "tick")


def input_snapshot(
    values: Mapping[str, Decimal | bool | str | None],
) -> Mapping[str, SnapshotValue]:
    """The metric values an evaluation saw (`EvaluationResult.metric_values`), a `Decimal` as its
    plain text (`dec_str`), as the run row stores them (`input_snapshot`, jsonb)."""
    return MappingProxyType(
        {k: dec_str(v) if isinstance(v, Decimal) else v for k, v in values.items()}
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class RunRow:
    """A fire's `rule_runs` row (21 §3.4.3), written `running` with its first event; its status is
    set once, by the close. `input_snapshot` is never shown by `repr`, so no log can carry it."""

    run_id: UUID
    rule_id: str
    version_id: str  # `EvaluableRule.version_id`: the active version the fire was evaluated under
    mode: EvaluableMode
    trigger_reason: TriggerReason
    account_id: UUID | None  # the scope instance's account
    symbol: str | None
    matched: bool
    input_snapshot: Mapping[str, SnapshotValue] = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class EventRow:
    """A `rule_events` row: `seq` from 1 within its run, `node_ref` the action's node id."""

    seq: int
    kind: EventKind
    node_ref: str | None
    payload: Mapping[str, Any] = field(repr=False)
    severity: EventSeverity = "info"


class RunRecords(Protocol):
    """The run row and its events (`SqlAlchemyRulesRepository`, bound in `rules_oms_wiring`)."""

    async def begin(self, run: RunRow, first: EventRow) -> None:
        """The run row with its first event, in one transaction; a repeat lands once."""

    async def append(self, run_id: UUID, events: Sequence[EventRow]) -> None:
        """Events of a run already begun; a repeated `seq` lands once."""

    async def close(self, run_id: UUID, status: RunStatus, duration_ms: int) -> None:
        """The run's status, `finished_at` and `duration_ms`, set once."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionAuditFields:
    """What `rules.fired` and `rules.blocked` record of an action (24 §15.5), a closed set: ids
    and names only, never a parameter's value or a figure. `blocked_by` names a refusal."""

    rule_id: str
    version: int
    ir_hash: str
    run_id: UUID
    node_id: str
    action_type: str
    scope_instance: str
    account_id: UUID | None
    owner: UUID
    armed_by: str | None
    dedupe_key: str
    blocked_by: BlockedBy | None = None
    #: Both users' roles as the principal snapshot the action was checked against gave them
    #: (check 5, E35-T10); `None` when that snapshot was not read.
    owner_role: str | None = None
    armed_by_role: str | None = None


def audit_fields(
    req: ActionRequest,
    *,
    account_id: UUID | None,
    dedupe_key: str,
    blocked_by: BlockedBy | None = None,
) -> ActionAuditFields:
    """`req`'s audit fields on `account_id` under its fire key; its params never enter them."""
    return ActionAuditFields(
        rule_id=req.rule_id, version=req.version, ir_hash=req.ir_hash, run_id=req.run_id,
        node_id=req.payload.node_id, action_type=req.action_type,
        scope_instance=req.instance.key, account_id=account_id, owner=req.owner,
        armed_by=req.armed_by, dedupe_key=dedupe_key, blocked_by=blocked_by,
    )  # fmt: skip


class ActionAudit(Protocol):
    """`rules.fired` and `rules.blocked`, each keyed by the action's `dedupe_key` (24 §15.5)."""

    async def fired(self, fields: ActionAuditFields) -> None: ...

    async def blocked(self, fields: ActionAuditFields) -> None: ...


class AlertPort(Protocol):
    """The executor's two `critical` alerts (24 §11.5, AC-14; BQ-7), each naming the rule, the fire
    (`run_id`) and the action that did not succeed (`node_id`), never a figure or an account;
    `rules_oms_wiring` binds them to the page line and to `system_events`."""

    async def partial_fire(self, rule_id: str, run_id: UUID, node_id: str) -> None: ...

    async def write_ahead_failed(self, rule_id: str, run_id: UUID, node_id: str) -> None: ...

    def settled(self, rule_id: str) -> None:
        """The rule's fire ended with no partial outcome: its alert episode is over."""

    def breaker_tripped(self, rule_id: str, run_id: UUID, node_id: str) -> None:
        """The circuit breaker tripped (24 §11.7, BQ-8): the P1 page, synchronous, on every trip,
        naming the rule, the fire and the action whose order the budget refused."""

    async def breaker_moved(self, rule_id: str, run_id: UUID, node_id: str, *, moved: bool) -> None:
        """After the trip's B9 move: the one `critical` `system_events` row saying whether the rule
        was moved, and, when it was not, the page again."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PrincipalView:
    """One user's principal snapshot (24 §11.5 "The principal"; E35-T10, BQ-5): whether the user
    is active (neither disabled nor deleted), the role's name and whether it is the Owner role,
    the accounts the order route's decision admits with `requires_trade` in the process's
    environment (every account of it for an Owner; a view-only or frozen grant admits none), and
    when it was read, on the executor's monotonic clock."""

    user_id: UUID
    active: bool
    role: str | None
    is_owner: bool
    trade_accounts: frozenset[UUID]
    read_at: float


class PrincipalReads(Protocol):
    """Check 5's reads by user id, never a session (E35-FR-01): synchronous, from memory. E35-T11
    binds them; unbound, every action that reaches check 5 is refused (`permission`)."""

    def principal(self, user_id: UUID) -> PrincipalView | None: ...


class StopCheck(Protocol):
    """Check 8's read-only port to the recorded-stop writer's own comparison (24 §11.5, §8.8 rule
    5; BQ-12): whether the stop action on that account leaves the stop in force no looser, and a
    cancel selects no native stop-loss. E35-T12 binds it; unbound, every stop action is refused
    (`native_sl`)."""

    def admits(self, req: ActionRequest, account_id: UUID | None) -> bool: ...


class NotionalRebuild(Protocol):
    """The day's notional a rule has sent, rebuilt from the rows its answers wrote (24 §11.7;
    BQ-11), which E35-T11 binds; unbound, an entry of a rule with `max_daily_notional` set is
    refused (`cap`)."""

    async def day_notional(self, rule_id: str, day: date) -> Decimal: ...


class RuleSwitches(Protocol):
    """Checks 2 and 3's switches (24 §11.5; E35-T10, BQ-2), each a synchronous read of memory,
    never an interpreter (C-2.20, C-2.21): the master switch `rules.enabled` (off while unread),
    the `killswitch.order_entry` flag (engaged while unread), B18's verdict for an account (the
    global one for `None`) and the rollout flag `rules.oms_actions` (off until E35-T11)."""

    def rules_enabled(self) -> bool: ...

    def order_entry_killed(self) -> bool: ...

    def kill_switch_engaged(self, account_id: UUID | None) -> bool: ...

    def oms_actions(self) -> bool: ...
