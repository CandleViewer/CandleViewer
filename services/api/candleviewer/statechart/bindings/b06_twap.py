"""candleviewer.statechart.bindings.b06_twap — MachineLogic stubs for B6 `twap`
(E50-S01). Chart: `machines/B06.twap.machine.json`.

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
    "apply_catch_up": _noop_action,
    "bump_failure": _noop_action,
    "bump_slices_done": _noop_action,
    "compute_slice_qty_with_participation_cap": _noop_action,
    "precompute_all_slice_deadlines": _noop_action,
    "raise_price_limit_notice": _noop_action,
    "raise_warning_alert": _noop_action,
    "rearm_deadlines_from_context": _noop_action,
    "record_child": _noop_action,
    "record_shortfall": _noop_action,
    "register_deadlines_with_scheduler": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "abort_on_price_limit": _deny_guard,
    "failures_exhausted": _deny_guard,
    "final_market_sweep_and_remaining": _deny_guard,
    "on_disconnect_is_freeze": _deny_guard,
    "preflight_invalid": _deny_guard,
    "price_limit_breached": _deny_guard,
    "slice_qty_below_min_roll_forward": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "cancel_all_children": _idempotent_service,
    "market_sweep_remainder": _idempotent_service,
    "reconcile_children": _idempotent_service,
    "submit_child": _idempotent_service,
}

register_binding_module("twap", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "twap",
    {
        "KILL": _ANY_PAYLOAD,
        "CHILDREN_TERMINAL": _ANY_PAYLOAD,
        "DURATION_END": _ANY_PAYLOAD,
        "MAX_DURATION": _ANY_PAYLOAD,
        "PRICE_OK": _ANY_PAYLOAD,
        "RESUME": _ANY_PAYLOAD,
        "SLICE_DUE": _ANY_PAYLOAD,
        "USER_CANCEL": _ANY_PAYLOAD,
        "USER_PAUSE": _ANY_PAYLOAD,
        "WS_DISCONNECT": _ANY_PAYLOAD,
    },
)
