"""candleviewer.statechart.bindings.b07_chase — MachineLogic stubs for B7 `chase`
(E50-S01). Chart: `machines/B07.chase.machine.json`.

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
    "bump_repricings": _noop_action,
    "compute_target_excluding_own_size": _noop_action,
    "drain_deferred": _noop_action,
    "map_error": _noop_action,
    "raise_warning_alert": _noop_action,
    "record_child": _noop_action,
    "stamp_arm_price": _noop_action,
    "stamp_last_reprice": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "beyond_max_chase_ticks": _deny_guard,
    "drift_over_threshold_and_interval_elapsed_and_budget_ok": _deny_guard,
    "error_is_order_not_found_after_fill": _deny_guard,
    "failures_exhausted": _deny_guard,
    "on_disconnect_is_freeze": _deny_guard,
    "on_timeout_is_cancel": _deny_guard,
    "on_timeout_is_market": _deny_guard,
    "repricings_exhausted": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "amend_child_price": _idempotent_service,
    "cancel_child": _idempotent_service,
    "convert_to_market": _idempotent_service,
    "submit_initial_limit": _idempotent_service,
}

register_binding_module("chase", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "chase",
    {
        "KILL": _ANY_PAYLOAD,
        "BOOK_TARGET_MOVED": _ANY_PAYLOAD,
        "CHILDREN_TERMINAL": _ANY_PAYLOAD,
        "CHILD_FILLED": _ANY_PAYLOAD,
        "CHILD_PARTIAL": _ANY_PAYLOAD,
        "RATE_BUDGET_EXHAUSTED": _ANY_PAYLOAD,
        "RESUME": _ANY_PAYLOAD,
        "TIMEOUT": _ANY_PAYLOAD,
        "USER_CANCEL": _ANY_PAYLOAD,
        "USER_PAUSE": _ANY_PAYLOAD,
        "WS_DISCONNECT": _ANY_PAYLOAD,
    },
)
