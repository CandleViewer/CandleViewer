"""candleviewer.statechart.bindings.b05_iceberg — MachineLogic stubs for B5 `iceberg`
(E50-S01). Chart: `machines/B05.iceberg.machine.json`.

Stubs only: business logic is owned by E22 emulated algos (ticket "Out of scope").
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
    "audit_guard_denied": _noop_action,
    "audit_kill": _noop_action,
    "apply_fill": _noop_action,
    "bump_failure": _noop_action,
    "bump_post_only_rejects": _noop_action,
    "bump_slices_done": _noop_action,
    "compute_slice_qty": _noop_action,
    "record_child": _noop_action,
    "reset_post_only_rejects": _noop_action,
    "schedule_cooldown_deadline": _noop_action,
    "schedule_refill_deadline": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "cancel_on_position_flat": _deny_guard,
    "failures_exhausted": _deny_guard,
    "is_post_only_reject": _deny_guard,
    "on_disconnect_is_freeze": _deny_guard,
    "preflight_invalid": _deny_guard,
    "remaining_is_zero": _deny_guard,
    "slices_exhausted": _deny_guard,
    "two_consecutive_post_only_rejects": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "cancel_all_children": _idempotent_service,
    "reconcile_children": _idempotent_service,
    "submit_child": _idempotent_service,
}

register_binding_module("iceberg", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "iceberg",
    {
        "KILL": _ANY_PAYLOAD,
        "CHILDREN_TERMINAL": _ANY_PAYLOAD,
        "CHILD_CANCELLED": _ANY_PAYLOAD,
        "CHILD_FILLED": _ANY_PAYLOAD,
        "CHILD_PARTIAL": _ANY_PAYLOAD,
        "COOLDOWN_DUE": _ANY_PAYLOAD,
        "MAX_DURATION": _ANY_PAYLOAD,
        "POSITION_FLAT": _ANY_PAYLOAD,
        "REFILL_DUE": _ANY_PAYLOAD,
        "RESUME": _ANY_PAYLOAD,
        "USER_CANCEL": _ANY_PAYLOAD,
        "USER_PAUSE": _ANY_PAYLOAD,
        "WS_DISCONNECT": _ANY_PAYLOAD,
    },
)
