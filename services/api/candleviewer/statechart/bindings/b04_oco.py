"""candleviewer.statechart.bindings.b04_oco — MachineLogic stubs for B4 `oco`
(E50-S01). Chart: `machines/B04.oco.machine.json`.

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
    "bump_settle_failures": _noop_action,
    "journal_double_fill": _noop_action,
    "map_error": _noop_action,
    "raise_critical_alert": _noop_action,
    "raise_warning_alert": _noop_action,
    "record_child_ids": _noop_action,
    "record_fill_a": _noop_action,
    "record_fill_b": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "cancel_on_position_flat": _deny_guard,
    "error_is_order_gone": _deny_guard,
    "other_leg_terminal": _deny_guard,
    "partial_settle_remaining": _deny_guard,
    "position_overshoots": _deny_guard,
    "settle_retries_left": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "cancel_all_children": _idempotent_service,
    "reconcile_children": _idempotent_service,
    "reduce_only_market_excess": _idempotent_service,
    "settle_other_leg": _idempotent_service,
    "submit_both_legs": _idempotent_service,
}

register_binding_module("oco", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "oco",
    {
        "KILL": _ANY_PAYLOAD,
        "CHILDREN_TERMINAL": _ANY_PAYLOAD,
        "LEG_A_FILL": _ANY_PAYLOAD,
        "LEG_B_FILL": _ANY_PAYLOAD,
        "POSITION_FLAT": _ANY_PAYLOAD,
        "USER_CANCEL": _ANY_PAYLOAD,
    },
)
