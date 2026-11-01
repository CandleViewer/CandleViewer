"""What one rule action did (24 §11.9 "Dispatch types"): `ActionResult`, `SimulatedAction` and
`blocked_by`, the closed set of what stopped an action, which `rule_actions_blocked_total{reason}`
(`20-architecture.md` §12.1) takes word for word.

`blocked_detail` is one plain sentence for SCR-084 and SCR-087 (`BLOCKED_DETAIL`): what stopped
the action, never an id, a figure or exchange text (C-12.6).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

BlockedBy = Literal[
    "rules_disabled", "kill_switch", "order_entry", "scope", "live_gate", "environment",
    "permission", "cap", "order_budget", "native_sl", "rate_limited", "unavailable",
    "backpressure", "circuit_breaker", "confirmation_unavailable", "mode_changed",
]  # fmt: skip
BLOCKED_BY: Final[tuple[BlockedBy, ...]] = get_args(BlockedBy)
Outcome = Literal["ok", "failed", "blocked", "skipped", "unknown", "simulated"]
OUTCOMES: Final[tuple[Outcome, ...]] = get_args(Outcome)
#: The detail of a `mode_changed` skip whose check-1 read failed or answered late (24 §11.5, BQ-6):
#: the row was not confirmed armed, which is not the same as found disarmed.
ROW_UNREAD: Final = "row_unread"
#: The rule's own limits a `cap` refusal names (24 §11.9; check 6, E35-T10): each its own detail.
RuleLimit = Literal["max_actions_per_fire", "max_notional_per_fire", "max_daily_notional"]
RULE_LIMITS: Final[tuple[RuleLimit, ...]] = get_args(RuleLimit)

#: PROPOSED for the owner (`docs/design/E35/E35-D03.md` §6's register, "Not done — {why}"):
#: interim copy until E35-D03's approved table replaces it; no screen shows it before E35-S06
#: serves the run routes. One sentence each, at most 80 characters, naming the condition only.
BLOCKED_DETAIL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "rules_disabled": "Not done — rule actions are switched off for the whole system.",
        "kill_switch": "Not done — the kill switch is on, or trading is turned off.",
        "order_entry": "Not done — order entry is paused for now, so nothing was sent.",
        "scope": "Not done — this account or symbol is no longer in the rule's scope.",
        "live_gate": "Not done — rule actions on live accounts are not open yet.",
        "environment": "Not done — the account is in another environment than this server.",
        "permission": "Not done — the rule's owner or armer may not trade this account now.",
        "cap": "Not done — the action would go past a limit of the rule or the account.",
        "order_budget": "Not done — the rule's order budget is used up for now.",
        "native_sl": "Not done — it would loosen or remove a stop-loss at the exchange.",
        "rate_limited": "Not done — the exchange's request limit was reached, so nothing was sent.",
        "unavailable": "Not done — this action is not available yet.",
        "backpressure": "Not done — too many rule fires were waiting, so this one was refused.",
        "circuit_breaker": "Not done — the rule's circuit breaker tripped and stopped the rule.",
        "confirmation_unavailable": "Not done — confirming before acting is not available yet.",
        "mode_changed": "Not done — the rule was changed or disarmed before it acted.",
        ROW_UNREAD: "Not done — the rule's state was not confirmed, so nothing was sent.",
        # E35-T10: `cap`, by the rule limit it names.
        "max_actions_per_fire": "Not done — the rule took as many actions as one firing may.",
        "max_notional_per_fire": "Not done — this firing used up the rule's notional limit.",
        "max_daily_notional": (
            "Not done — the rule's daily notional limit is used up or unconfirmed."
        ),
    }
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class ActionResult(BaseModel):
    """One action's result on one account (or none, for an action that names none), in IR order
    (E5): in `RuleEvent.actions_executed`, its `action_ok` or `action_fail` row and the `rules`
    topic's `action_result` events (24 §11.9)."""

    model_config = _FROZEN

    node_id: str = Field(min_length=1)
    action_type: str
    account_id: UUID | None
    resolved_accounts: tuple[UUID, ...]
    outcome: Outcome
    blocked_by: BlockedBy | None = None
    blocked_detail: str | None = None
    error_code: str | None = None
    order_id: UUID | None = None
    group_id: UUID | None = None
    dedupe_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_us: int = Field(ge=0)

    @model_validator(mode="after")
    def _blocked_by_names_a_refusal(self) -> ActionResult:
        """`blocked_by` is set exactly for `blocked`, and for `skipped` with `mode_changed`."""
        if self.outcome == "blocked":
            named = self.blocked_by is not None and self.blocked_by != "mode_changed"
        elif self.outcome == "skipped":
            named = self.blocked_by in (None, "mode_changed")
        else:
            named = self.blocked_by is None
        if not named:
            raise ValueError("blocked_by is set for a blocked result and a mode_changed skip only")
        return self


class SimulatedAction(BaseModel):
    """What an action would have done, sent nowhere (24 §11.9): a simulate rule's, or an armed
    rule's `dry_run_only` action (`simulated`)."""

    model_config = _FROZEN

    action_type: str
    params: dict[str, Any]
    would_target_accounts: tuple[UUID, ...]
    estimated_qty: Decimal | None = None
    estimated_notional: Decimal | None = None
    estimated_price: Decimal | None = None
    estimated_fee: Decimal | None = None
    blocked_by: BlockedBy | None = None
    blocked_detail: str | None = None


def blocked_result(
    *,
    node_id: str,
    action_type: str,
    account_id: UUID | None,
    resolved_accounts: tuple[UUID, ...],
    dedupe_key: str,
    reason: BlockedBy,
    duration_us: int = 0,
    limit: str | None = None,
) -> ActionResult:
    """A check's refusal: nothing was sent (24 §11.9 `blocked`). `limit`, when given, keys the
    detail in place of the reason: a `BLOCKED_DETAIL` key of its own, such as the rule limit a
    `cap` names (`RULE_LIMITS`)."""
    return ActionResult(
        node_id=node_id, action_type=action_type, account_id=account_id,
        resolved_accounts=resolved_accounts, outcome="blocked", blocked_by=reason,
        blocked_detail=BLOCKED_DETAIL[limit or reason], dedupe_key=dedupe_key,
        duration_us=duration_us,
    )  # fmt: skip


def skipped_result(
    *,
    node_id: str,
    action_type: str,
    account_id: UUID | None,
    resolved_accounts: tuple[UUID, ...],
    dedupe_key: str,
    reason: Literal["mode_changed"] | None = None,
    unread: bool = False,
) -> ActionResult:
    """Never attempted (24 §11.9 `skipped`): after a stop (`reason` `None`), or from the action
    whose check 1 found the row no longer armed (`mode_changed`), its detail saying whether the
    row was read so (`unread` False) or not confirmed (`unread`, BQ-6)."""
    if unread and reason is None:
        raise ValueError("an unread row is a mode_changed skip")
    detail = None if reason is None else BLOCKED_DETAIL[ROW_UNREAD if unread else reason]
    return ActionResult(
        node_id=node_id, action_type=action_type, account_id=account_id,
        resolved_accounts=resolved_accounts, outcome="skipped", blocked_by=reason,
        blocked_detail=detail, dedupe_key=dedupe_key, duration_us=0,
    )  # fmt: skip
