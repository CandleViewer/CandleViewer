"""risk module (M17).

Risk caps, daily-loss/drawdown lockout, kill-switch, exposure aggregation.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M5, M10, M13.

- Domain models (E39-T02, #882) for the state E39 persists (`docs/plan/21-database-schema.md`
  §3.11) and the gate's verdict (`docs/plan/24-internal-schemas.md` §8.11).
- The pure evaluator and cap resolution (E39-T01): `evaluate` judges a `RiskOrder` on one
  account's `RiskFigures` against the `ResolvedCaps` of `resolve_caps`. The counters, the service
  and the lockout and kill-switch engines land with later E39-T01 slices, E39-S02 and E39-S03.
"""

from __future__ import annotations

from candleviewer.risk.caps import (
    CapSource,
    ManagerCaps,
    PolicyCaps,
    ProfileCaps,
    ResolvedCap,
    ResolvedCaps,
    resolve_caps,
)
from candleviewer.risk.evaluator import CHECK_ORDER, RiskEvaluation, RiskWarning, evaluate
from candleviewer.risk.inputs import RiskFigures, RiskOrder
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
    "CHECK_ORDER",
    "CapSource",
    "KillSwitchOptions",
    "KillSwitchScope",
    "KillSwitchState",
    "LockoutActions",
    "LockoutReason",
    "LockoutState",
    "ManagerCaps",
    "PolicyCaps",
    "ProfileCaps",
    "ResolvedCap",
    "ResolvedCaps",
    "RiskDecision",
    "RiskEvaluation",
    "RiskFigures",
    "RiskOrder",
    "RiskRefusal",
    "RiskWarning",
    "evaluate",
    "resolve_caps",
]
