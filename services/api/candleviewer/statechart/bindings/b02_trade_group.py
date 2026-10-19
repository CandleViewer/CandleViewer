"""candleviewer.statechart.bindings.b02_trade_group — MachineLogic stubs for B2 `trade_group`
(E50-S01). Chart: `machines/B02.trade_group.machine.json`.

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
    "audit_guard_denied": _noop_action,
    "audit_kill": _noop_action,
    "arm_quiesce_deadline": _noop_action,
    "count_failed": _noop_action,
    "count_open": _noop_action,
    "count_skipped": _noop_action,
    "force_resolve_unknown_legs": _noop_action,
    "launch_all_legs": _noop_action,
    "mark_quiesced": _noop_action,
    "mark_unwind_incomplete": _noop_action,
    "mark_unwound": _noop_action,
    "persist_unwind_plan": _noop_action,
    "raise_critical_alert": _noop_action,
    "reserve_rate_budget": _noop_action,
    "stop_submitting_remaining_legs": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "all_non_skipped_open": _deny_guard,
    "policy_all_or_none_and_any_failed": _deny_guard,
    "policy_is_abort_on_first": _deny_guard,
    "quiesced_and_some_open": _deny_guard,
    "quiesced_and_zero_open": _deny_guard,
    "some_open": _deny_guard,
    "unwind_complete": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "unwind_machine": _idempotent_service,
}

register_binding_module("trade_group", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "trade_group",
    {
        "KILL": _ANY_PAYLOAD,
        "ALL_LEGS_FLAT": _ANY_PAYLOAD,
        "CANCEL": _ANY_PAYLOAD,
        "CLOSE_GROUP": _ANY_PAYLOAD,
        "CLOSE_INCOMPLETE": _ANY_PAYLOAD,
        "CONFIRM": _ANY_PAYLOAD,
        "EVALUATE": _ANY_PAYLOAD,
        "LEG_FAILED": _ANY_PAYLOAD,
        "LEG_OPEN": _ANY_PAYLOAD,
        "LEG_SKIPPED": _ANY_PAYLOAD,
        "QUIESCE_DEADLINE": _ANY_PAYLOAD,
    },
)
