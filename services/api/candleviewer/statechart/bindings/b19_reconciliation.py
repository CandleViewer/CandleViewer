"""candleviewer.statechart.bindings.b19_reconciliation — MachineLogic stubs for B19 `reconciliation`
(E50-S02). Chart: `machines/B19.reconciliation.machine.json`.

Stubs only: business logic is owned by E21 reconciliation (ticket "Out of scope").
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
    "audit_kill": _noop_action,
    # OC-05 (#2204): stale_lockout leaves only on OPERATOR_RESOLVED (INV-B19-b).
    "audit_operator_resolved": _noop_action,
    "audit_reconnect_while_locked": _noop_action,
    "broadcast_recon_complete": _noop_action,
    "bump_failures": _noop_action,
    "emit_recon_metrics": _noop_action,
    "emit_recon_started": _noop_action,
    "lock_account_for_new_orders": _noop_action,
    "page_owner": _noop_action,
    "persist_report": _noop_action,
    "raise_critical_alert": _noop_action,
    "raise_divergence_alert": _noop_action,
    "record_diff_error": _noop_action,
    "reset_failures": _noop_action,
    "schedule_retry_deadline": _noop_action,
    "set_trigger_periodic": _noop_action,
    "set_trigger_reconnect": _noop_action,
    "set_trigger_startup": _noop_action,
    "set_trigger_unknown": _noop_action,
    "stamp_start": _noop_action,
    "store_divergences": _noop_action,
    "store_exchange_state": _noop_action,
    "store_remediations": _noop_action,
    "unlock_account_for_new_orders": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "divergences_found_and_auto_remediate": _deny_guard,
    "failures_exhausted": _deny_guard,
    "unresolved_divergences": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "apply_remediations": _idempotent_service,
    "diff_against_local": _idempotent_service,
    "fetch_exchange_state": _idempotent_service,
}

register_binding_module("reconciliation", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "reconciliation",
    {
        "CANCEL": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "OPERATOR_RESOLVED": _ANY_PAYLOAD,
        "RECONNECTED": _ANY_PAYLOAD,
        "RETRY_DUE": _ANY_PAYLOAD,
        "STARTUP": _ANY_PAYLOAD,
        "SWEEP_DUE": _ANY_PAYLOAD,
        "UNKNOWN_ORDER": _ANY_PAYLOAD,
    },
)
