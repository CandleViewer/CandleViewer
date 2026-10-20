"""candleviewer.statechart.bindings.b18_kill_switch — MachineLogic stubs for B18 `kill_switch`
(E50-S02). Chart: `machines/B18.kill_switch.machine.json`.

Stubs only: business logic is owned by E26 kill switch (ticket "Out of scope").
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
    "audit_kill_switch": _noop_action,
    "audit_kill_switch_released": _noop_action,
    "audit_release_denied": _noop_action,
    "block_new_orders_immediately": _noop_action,
    "broadcast_kill_switch": _noop_action,
    "cancel_entry_and_poll_drains": _noop_action,
    "emit_incomplete_metric": _noop_action,
    "page_owner": _noop_action,
    "raise_critical_alert": _noop_action,
    "record_engagement": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "all_accounts_flat": _deny_guard,
    "cancel_working_requested": _deny_guard,
    "flatten_requested": _deny_guard,
    "owner_and_elevated": _deny_guard,
    "owner_and_elevated_and_acknowledged_residual": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "cancel_all_working_orders": _idempotent_service,
    "flatten_all_positions": _idempotent_service,
}

register_binding_module("kill_switch", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "kill_switch",
    {
        "ENGAGE": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "RELEASE": _ANY_PAYLOAD,
        "RETRY_FLATTEN": _ANY_PAYLOAD,
    },
)
