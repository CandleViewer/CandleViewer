"""candleviewer.statechart.bindings.b10_alert — MachineLogic for B10 `alert` (E40-T03).
Chart: `machines/B10.alert.machine.json` (names fixed by the chart contract, E50-S02).

One chart records one firing's lifecycle. Statecharts record, synchronous code enforces
(C-2.21): the gating pipeline, the storm decision and the firing transaction all run in
`alerts.evaluator` before anything is sent; guards only read the facts on the event.
Guards are pure and total (A6); actions/services are `async def` (CV-C67) and idempotent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Injected by `alerts.lifecycle` (bindings never import `alerts`/`audit`; same pattern as
#: B16's `set_audit_sink`). Called as `hook(name, context)`; must not raise.
Hook = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _no_hook(_name: str, _ctx: dict[str, Any]) -> None:
    return None


_hook: Hook = _no_hook


def set_hook(hook: Hook | None) -> None:
    global _hook
    _hook = hook or _no_hook


def _payload(event: Any) -> dict[str, Any]:
    """Actions/guards get an `Event` (`.payload`) or a `DoneEvent` (`.data`)."""
    for attr in ("payload", "data"):
        v = getattr(event, attr, None)
        if isinstance(v, dict):
            return v
    return event if isinstance(event, dict) else {}


def _guard_error(name: str, exc: Exception) -> bool:
    logger().error("b10_guard_error", guard=name, error=type(exc).__name__)
    return False


# --- guards: pure, total, False on any internal error (catalogue A6) -----------------


def in_storm_window(context: dict[str, Any], event: Any) -> bool:
    """The synchronous per-user storm suppressor decided (C-2.21); the chart records."""
    try:
        return _payload(event).get("storm") is True
    except Exception as exc:  # A6: total
        return _guard_error("in_storm_window", exc)


def all_channels_ok(context: dict[str, Any], event: Any) -> bool:
    """INV-B10-b: full delivery iff `delivered_channels` == `channels` (non-empty)."""
    try:
        want = set(context.get("channels") or ())
        got = set(_payload(event).get("delivered_channels") or ())
        return bool(want) and got == want
    except Exception as exc:
        return _guard_error("all_channels_ok", exc)


def delivery_attempts_left(context: dict[str, Any], event: Any) -> bool:
    """INV-B10-a: retry only while `delivery_attempts < max_delivery_attempts`."""
    try:
        return int(context["delivery_attempts"]) < int(context["max_delivery_attempts"])
    except Exception as exc:
        return _guard_error("delivery_attempts_left", exc)


# --- actions (CV-C67: coroutine functions registered directly) -----------------------


async def persist_fired_row(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """INV-B10-d. The `alert_deliveries` + `outbox` rows are committed by the evaluator's
    single firing transaction *before* `CONDITION_MET` is sent (21 §3.10.4: decide and
    record atomically) — the evaluator sends only after that commit returned ids. This
    entry action pins those ids on the chart so a restored `firing` knows its rows."""
    ids = [int(i) for i in _payload(event).get("delivery_ids") or ()]
    context["delivery_ids"] = ids or list(context.get("delivery_ids") or ())
    p = _payload(event)
    if p.get("alert_id") is not None:
        context["alert_id"] = str(p["alert_id"])
    if p.get("channels"):
        context["channels"] = [str(c) for c in p["channels"]]
    context["delivered_channels"] = []


async def stamp_storm_window(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    context["suppressed_until_us"] = _payload(event).get("storm_window_end_us")


async def bump_storm_count(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    context["storm_count"] = int(context.get("storm_count", 0)) + 1
    context["suppressed_until_us"] = _payload(event).get("storm_window_end_us")


async def emit_suppression_metric(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("suppressed", context)  # INV-B10-c: observable, never dropped


async def bump_delivery_attempts(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    cap = int(context.get("max_delivery_attempts", 5))
    context["delivery_attempts"] = min(int(context.get("delivery_attempts", 0)) + 1, cap)


async def schedule_backoff_deadline(_i: Any, _c: dict[str, Any], _e: Any, _a: Any) -> None:
    """B10.8: backoff deadlines belong to the external scheduler (the E40-T04 outbox
    poller's `available_at`); nothing is timed inside the chart."""
    return None


async def emit_delivery_failure_metric(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("delivery_failed", context)


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("killed", context)


async def dispatch_to_channels(_i: Any, context: dict[str, Any], _e: Any) -> dict[str, Any]:
    """Idempotent under re-entry: the firing transaction already enqueued exactly one
    `outbox` row per delivery (`ux_outbox_dedup`), so this is only the hand-off to the
    E40-T04 poller and re-running it enqueues nothing. Channel transport is E40-T04."""
    return {"delivered_channels": list(context.get("channels") or ())}


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "audit_kill": audit_kill,
    "bump_delivery_attempts": bump_delivery_attempts,
    "bump_storm_count": bump_storm_count,
    "emit_delivery_failure_metric": emit_delivery_failure_metric,
    "emit_suppression_metric": emit_suppression_metric,
    "persist_fired_row": persist_fired_row,
    "schedule_backoff_deadline": schedule_backoff_deadline,
    "stamp_storm_window": stamp_storm_window,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "all_channels_ok": all_channels_ok,
    "delivery_attempts_left": delivery_attempts_left,
    "in_storm_window": in_storm_window,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "dispatch_to_channels": dispatch_to_channels,
}

register_binding_module("alert", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "alert",
    {
        "ACK": _ANY_PAYLOAD,
        "CONDITION_MET": _ANY_PAYLOAD,
        "DISABLE": _ANY_PAYLOAD,
        "ENABLE": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "RESOLVE": _ANY_PAYLOAD,
        "RETRY_DUE": _ANY_PAYLOAD,
        "SUPPRESSION_EXPIRED": _ANY_PAYLOAD,
    },
)
