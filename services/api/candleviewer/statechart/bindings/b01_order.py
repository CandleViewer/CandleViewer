"""candleviewer.statechart.bindings.b01_order — MachineLogic stubs for B1 `order`
(#1650, E50). Chart: `machines/B01.order.machine.json`.

Stubs only: business logic is owned by E29 OMS core. Guards are pure, total and
return `False` (catalogue A6); actions are `async def` (CV-C67); services are
idempotent `async def` with no I/O. Owning epics replace bodies, never names.

KILL semantics (owner decision #1778 item X, option a): root `lifecycle.on.KILL`
lands in the final `lifecycle.killed`, whose entry marks the order
`halted_by_kill`, audits (write-ahead, C-2.9), then issues the exchange cancel
through the same `cancel_order` service the `cancel_pending` invoke uses —
skipped for never-submitted `draft`/`validated`; `cancel_pending` keeps its
in-flight cancel instead of sending a second one. The cancel outcome is NOT
trusted here — reconciliation re-syncs the true exchange state (C-2.10, C-2.5).
The `protection` region is untouched by KILL (C-2.6): it only audits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import CV_KILL_CANCEL_TIMEOUT, register_event_schemas


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Audit hook injected by the OMS (bindings never import `audit`; B10/B16 pattern).
#: Called as `hook(name, context)`; must not raise.
AuditHook = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _no_hook(_name: str, _ctx: dict[str, Any]) -> None:
    return None


_hook: AuditHook = _no_hook


def set_audit_hook(hook: AuditHook | None) -> None:
    global _hook
    _hook = hook or _no_hook


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


def _deny_guard(*_args: object, **_kwargs: object) -> bool:
    return False


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


# --- KILL arm (#1650) ----------------------------------------------------------------


async def mark_halted_by_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["halted_by_kill"] = True


async def skip_kill_cancel(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """Nothing of ours to cancel: never sent (`draft`, `validated`), or an unverified duplicate."""
    context["kill_skip_cancel"] = True


async def issue_kill_cancel(i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """At most one exchange cancel per order, only if submitted (INV-B1-h): via the
    chart's own `cancel_order` service (the same client order id, C-2.10), bounded by
    `CV_KILL_CANCEL_TIMEOUT`. Failure or timeout is audited, never raised: rolling
    back would un-kill the order. Reconciliation re-syncs the exchange (C-2.5).

    E29: route through the audited OMS cancel service instead of calling the
    binding's service from an action (review #2133)."""
    if context.get("kill_skip_cancel"):
        await _hook("kill_no_cancel_unsubmitted", context)
        return
    try:
        async with asyncio.timeout(CV_KILL_CANCEL_TIMEOUT):
            await SERVICES["cancel_order"](i, context, event)
    except TimeoutError:
        logger().error("b01_kill_cancel_timeout")
        await _hook("kill_cancel_timeout", context)
    except Exception as exc:  # audited; reconciliation re-syncs
        logger().error("b01_kill_cancel_failed", error=type(exc).__name__)
        await _hook("kill_cancel_failed", context)


async def audit_kill_cancel_in_flight(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`cancel_pending` KILL: the in-flight cancel is reused; no second cancel."""
    await _hook("kill_cancel_in_flight", context)


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("halted_by_kill", context)


async def audit_kill_ignored_terminal(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("kill_ignored_terminal", context)


async def audit_kill_protection_retained(
    _i: Any, context: dict[str, Any], _e: Any, _a: Any
) -> None:
    await _hook("kill_protection_retained", context)


async def audit_guard_denied(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("guard_denied", context)


_STUB_ACTIONS = (
    "adopt_ack",
    "adopt_amend",
    "adopt_cancel_ack",
    "adopt_recon",
    "apply_fill",
    "arm_recon_deadline",
    "arm_sl_deadline",
    "bump_recon_misses",
    "emit_terminal",
    "keep_prior_order_live",
    "map_reject_code",
    "mark_needs_lookup",
    "notify_amend_rejected",
    "notify_protection_region",
    "persist_event",
    "raise_critical_alert",
    "raise_naked_position_alert",
    "raise_unknown_alert",
    "record_transport_fault",
    "request_fallback_sl",
    "request_reconciliation",
    "reserve_rate_token",
    "set_local_reject",
    "set_reject_unresolvable",
    "stamp_validated",
)

ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    **{name: _noop_action for name in _STUB_ACTIONS},
    "audit_guard_denied": audit_guard_denied,
    "audit_kill": audit_kill,
    "audit_kill_cancel_in_flight": audit_kill_cancel_in_flight,
    "audit_kill_ignored_terminal": audit_kill_ignored_terminal,
    "audit_kill_protection_retained": audit_kill_protection_retained,
    "issue_kill_cancel": issue_kill_cancel,
    "mark_halted_by_kill": mark_halted_by_kill,
    "skip_kill_cancel": skip_kill_cancel,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "exec_new_and_closes": _deny_guard,
    "exec_new_and_partial": _deny_guard,
    "has_fills": _deny_guard,
    "is_duplicate_link_id": _deny_guard,
    "passes_all_gates": _deny_guard,
    "ret_code_ok": _deny_guard,
    "second_consecutive_miss": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "amend_order": _idempotent_service,
    "attach_native_sl": _idempotent_service,
    "cancel_order": _idempotent_service,
    "place_order": _idempotent_service,
}

register_binding_module("order", __name__)

#: Permissive payload schemas (B2-B9 shape); E29 tightens them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        name: _ANY_PAYLOAD
        for name in (
            "AMEND",
            "AMEND_REJECTED",
            "CANCEL",
            "EXEC",
            "EXPIRE",
            "FAULT",
            "FIRST_FILL",
            "KILL",
            "RECON_FOUND_CANCELLED",
            "RECON_FOUND_FILLED",
            "RECON_FOUND_LIVE",
            "RECON_FOUND_PARTIAL",
            "RECON_MISS",
            "SEND",
            "SL_DEADLINE",
            "SL_LOST",
            "SL_OBSERVED",
            "TRANSPORT_FAULT",
            "TRIGGERED",
            "VALIDATE",
        )
    }
)


# --- #847 slice 1: `untracked` and `held` (G-3) and exchange outcomes, chart version 1 ----
# Stubs until #847 slices 4-5: the guards deny (A6), so a duplicate result parks in `unknown`.
ACTIONS.update(
    dict.fromkeys(
        "adopt_remote_cancel adopt_untracked record_cancel_refused record_discovered"
        " record_mismatch set_cancel_missing_remote".split(),
        _noop_action,
    )
)


def _audited(name: str) -> Callable[..., Awaitable[None]]:
    async def audit(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
        await _hook(name, context)

    return audit


_AUDITED = "adoption_denied command_refused_unowned kill_ignored_unowned operator_resolved"
ACTIONS.update({f"audit_{name}": _audited(name) for name in _AUDITED.split()})

GUARDS.update(
    dict.fromkeys(
        "adoption_allowed is_duplicate_link_id_full_match is_link_id_mismatch"
        " ret_code_ok_and_has_fills".split(),
        _deny_guard,
    )
)
register_event_schemas(
    dict.fromkeys(
        ("ADOPT", "DISCOVERED", "MISMATCH", "OPERATOR_RESOLVED", "REMOTE_CANCELLED"), _ANY_PAYLOAD
    )
)

# --- #847 slice 1b, chart version 2: an attach result marks the stop present only if the exchange
# confirmed it (C-2.6, INV-B1-f). Fail-closed: no result is confirmed until slice 5's attach.
GUARDS["sl_attach_ok"] = _deny_guard
