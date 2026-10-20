"""risk module (M17).

Risk caps, daily-loss/drawdown lockout, kill-switch, exposure aggregation.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M5, M10, M13.

- Domain models (E39-T02, #882) for the state E39 persists (`docs/plan/21-database-schema.md`
  §3.11) and the gate's verdict (`docs/plan/24-internal-schemas.md` §8.11). The evaluator, the
  lockout service and the kill-switch engine land with E39-T01, E39-S02 and E39-S03.
"""

from __future__ import annotations

from candleviewer.risk.models import (
    KillSwitchOptions,
    KillSwitchScope,
    KillSwitchState,
    LockoutActions,
    LockoutReason,
    LockoutState,
    RiskDecision,
    RiskRefusal,
)

__all__: list[str] = [
    "KillSwitchOptions",
    "KillSwitchScope",
    "KillSwitchState",
    "LockoutActions",
    "LockoutReason",
    "LockoutState",
    "RiskDecision",
    "RiskRefusal",
]
