"""candleviewer.statechart.bindings.b20_risk_lockout — MachineLogic stubs for B20 `risk_lockout`
(E50-S02). Chart: `machines/B20.risk_lockout.machine.json`.

Stubs only: business logic is owned by E27 risk lockout (ticket "Out of scope").
Guards are pure, total and return `False` (catalogue A6); actions are
`async def` no-ops (CV-C67); services are idempotent `async def` that
return `None` without I/O. Owning epics replace bodies, never names —
the names are fixed by the chart contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


def _deny_guard(*_args: object, **_kwargs: object) -> bool:
    return False


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "audit_lockout": _noop_action,
    "audit_override": _noop_action,
    "audit_override_denied": _noop_action,
    "broadcast_lockout": _noop_action,
    "compute_until": _noop_action,
    "emit_risk_warning": _noop_action,
    "halt_new_orders": _noop_action,
    "log_expiry_ignored_manual_mode": _noop_action,
    "raise_lockout_alert": _noop_action,
    "reset_daily_counters_if_new_day": _noop_action,
    "resume_new_orders": _noop_action,
    "schedule_expiry_deadline": _noop_action,
    "set_breach_daily_loss": _noop_action,
    "set_breach_from_event": _noop_action,
    "set_breach_manual": _noop_action,
    "update_pnl": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "breaches_daily_loss_cap": _deny_guard,
    "outside_warning_band": _deny_guard,
    "owner_and_elevated_and_override_permitted": _deny_guard,
    "until_mode_is_time_based": _deny_guard,
    "within_warning_band": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("risk_lockout", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "risk_lockout",
    {
        "CAP_BREACH": _ANY_PAYLOAD,
        "EXPIRY_DUE": _ANY_PAYLOAD,
        "MANUAL_LOCK": _ANY_PAYLOAD,
        "OVERRIDE_REQUESTED": _ANY_PAYLOAD,
        "PNL_UPDATE": _ANY_PAYLOAD,
    },
)
