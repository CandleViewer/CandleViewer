"""candleviewer.statechart.bindings.b03_leg — MachineLogic stubs for B3 `leg`
(E50-S01). Chart: `machines/B03.leg.machine.json`.

Stubs only: business logic is owned by E21 trade-group fan-out (ticket "Out of scope").
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
    "accumulate_fill": _noop_action,
    "arm_submit_timeout": _noop_action,
    "bump_close_attempts": _noop_action,
    "map_error": _noop_action,
    "mark_incomplete": _noop_action,
    "note_cancel_failure": _noop_action,
    "place_tp_ladder_once": _noop_action,
    "raise_naked_position_alert": _noop_action,
    "read_authoritative_position_qty": _noop_action,
    "size_from_profile": _noop_action,
    "submit_entry_order": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "close_attempts_left": _deny_guard,
    "fully_filled": _deny_guard,
    "is_flat": _deny_guard,
    "lookup_says_filled": _deny_guard,
    "lookup_says_live": _deny_guard,
    "passes_preflight": _deny_guard,
    "should_skip": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "assert_native_sl": _idempotent_service,
    "cancel_children_svc": _idempotent_service,
    "lookup_by_link_id": _idempotent_service,
    "poll_until_flat": _idempotent_service,
    "reduce_only_close": _idempotent_service,
}

register_binding_module("leg", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "leg",
    {
        "KILL": _ANY_PAYLOAD,
        "CLOSE": _ANY_PAYLOAD,
        "CLOSE_FAILED": _ANY_PAYLOAD,
        "EXEC": _ANY_PAYLOAD,
        "FLAT": _ANY_PAYLOAD,
        "ORDER_OPEN": _ANY_PAYLOAD,
        "ORDER_REJECTED": _ANY_PAYLOAD,
        "ORDER_UNKNOWN": _ANY_PAYLOAD,
        "SUBMIT_TIMEOUT": _ANY_PAYLOAD,
        "UNWIND": _ANY_PAYLOAD,
    },
)
