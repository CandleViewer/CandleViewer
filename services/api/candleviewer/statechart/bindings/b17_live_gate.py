"""candleviewer.statechart.bindings.b17_live_gate — MachineLogic stubs for B17 `live_gate`
(E50-S02). Chart: `machines/B17.live_gate.machine.json`.

Stubs only: business logic is owned by E34 live-enablement gate (ticket "Out of scope").
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
    "audit_disable_denied": _noop_action,
    "audit_enable_denied": _noop_action,
    "audit_live_disabled": _noop_action,
    "audit_live_enabled": _noop_action,
    "broadcast_live_enabled": _noop_action,
    "clear_evidence_item": _noop_action,
    "enable_live_visual_language": _noop_action,
    "raise_critical_alert": _noop_action,
    "record_disable": _noop_action,
    "record_enable": _noop_action,
    "record_evidence": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "all_evidence_present": _deny_guard,
    "owner_and_elevated": _deny_guard,
    "owner_and_elevated_and_evidence_still_valid": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("live_gate", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "live_gate",
    {
        "DISABLE_REQUESTED": _ANY_PAYLOAD,
        "EMERGENCY_DISABLE": _ANY_PAYLOAD,
        "ENABLE_REQUESTED": _ANY_PAYLOAD,
        "EVIDENCE_INVALIDATED": _ANY_PAYLOAD,
        "EVIDENCE_RECORDED": _ANY_PAYLOAD,
    },
)
