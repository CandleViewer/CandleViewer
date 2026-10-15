"""Statechart inspector read model (E42-T07): runtime-free projections of persisted snapshots and
registered charts. Never imports `xstate_statemachine` and never touches an `Interpreter`."""

from __future__ import annotations

from candleviewer.admin.inspector.projection import (
    ENTITY_KINDS,
    EntityKind,
    UnknownMachineKeyError,
    context_summary,
    export_chart,
    parse_machine_key,
    published_state,
    visible,
)

__all__ = [
    "ENTITY_KINDS",
    "EntityKind",
    "UnknownMachineKeyError",
    "context_summary",
    "export_chart",
    "parse_machine_key",
    "published_state",
    "visible",
]
