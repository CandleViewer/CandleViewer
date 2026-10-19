"""candleviewer.statechart.bindings.b15_paper_account — MachineLogic stubs for B15 `paper_account`
(E50-S02). Chart: `machines/B15.paper_account.machine.json`.

Stubs only: business logic is owned by E31 paper trading (ticket "Out of scope").
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
    "apply_liquidation_haircut": _noop_action,
    "emit_margin_warning": _noop_action,
    "note_mark_no_change": _noop_action,
    "write_liquidation_journal": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "above_maintenance_margin": _deny_guard,
    "below_maintenance_margin": _deny_guard,
    "mark_crossed_liq_price": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("paper_account", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "paper_account",
    {
        "MARK_UPDATE": _ANY_PAYLOAD,
    },
)
