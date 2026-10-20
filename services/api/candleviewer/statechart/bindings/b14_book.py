"""candleviewer.statechart.bindings.b14_book - MachineLogic for B14 `book`
(E08-S05). Chart: `machines/B14.book.machine.json`.

Record-only (C-2.20, C-2.21, INV-B14-a): the book engine enforces and
executes the whole lifecycle as plain code and forwards lifecycle edges
fire-and-forget through `candleviewer.ingestion.book_supervisor`. These
actions only maintain chart context; they never call back into the book and
never send events. Names are fixed by the chart contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


async def bump_resync_count(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["resync_count"] = int(context.get("resync_count", 0)) + 1


async def clear_buffer(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["buffered_deltas"] = []


#: INV-B14-d fallback when a context predates `max_buffered_deltas` (same value as
#: `book.resync.BUFFER_BOUND`; bindings may not import `book`, C-2.20).
DEFAULT_MAX_BUFFERED_DELTAS = 1_000


def _logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def delta_buffer_full(context: dict[str, Any], _event: Any) -> bool:
    """OC-08 / INV-B14-d: the buffer is full. Pure and total; fail-safe ``True``
    on any internal error (overflow => resync, never unbounded growth)."""
    try:
        bound = int(context.get("max_buffered_deltas", DEFAULT_MAX_BUFFERED_DELTAS))
        return len(context.get("buffered_deltas") or ()) >= bound
    except Exception as exc:  # total guard (A6): never raise into the interpreter
        _logger().error("b14_guard_error", guard="delta_buffer_full", error=type(exc).__name__)
        return True


async def audit_buffer_overflow(interp: Any, context: dict[str, Any], *_a: object) -> None:
    """Record the overflow (the CvAuditPlugin row carries this action name, C-2.9);
    the resync itself is the `desynced -> snapshot_pending` path (C-2.5)."""
    _logger().warning(
        "book_buffer_overflow",
        symbol=context.get("symbol"),
        buffered=len(context.get("buffered_deltas") or ()),
        bound=context.get("max_buffered_deltas", DEFAULT_MAX_BUFFERED_DELTAS),
    )


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "apply_delta": _noop_action,  # hot path: BookState.apply, never here
    "audit_buffer_overflow": audit_buffer_overflow,
    "buffer_delta": _noop_action,  # hot path: BookEngine buffer, never here
    "bump_resync_count": bump_resync_count,
    "clear_buffer": clear_buffer,
    "emit_book_desynced": _noop_action,  # executed by BookEngine
    "emit_book_live": _noop_action,  # LIVE status published by BookEngine.go_live
    "emit_resync_metric": _noop_action,
    "install_snapshot": _noop_action,  # executed by BookEngine
    "replay_buffered_deltas_after_seq": _noop_action,  # done inside go_live
    "request_snapshot": _noop_action,  # executed by BookEngine
    "stamp_desync": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {"delta_buffer_full": delta_buffer_full}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("book", __name__)

_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "book",
    {
        "BUFFER_OVERFLOW": _ANY_PAYLOAD,
        "DELTA": _ANY_PAYLOAD,
        "SEQUENCE_GAP": _ANY_PAYLOAD,
        "SNAPSHOT": _ANY_PAYLOAD,
        "SNAPSHOT_TIMEOUT": _ANY_PAYLOAD,
        "SUBSCRIBE": _ANY_PAYLOAD,
        "UNSUBSCRIBE": _ANY_PAYLOAD,
    },
)
