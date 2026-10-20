"""candleviewer.statechart.bindings.b08_position_protection — MachineLogic stubs for B8
`position_protection` (#1650, E50). Chart: `machines/B08.position_protection.machine.json`.

Stubs only: business logic is owned by E32 (native-SL invariant). Guards are pure,
total and return `False` (catalogue A6 — `tightens_only` is deny-polarity, INV-B8-b);
actions are `async def` (CV-C67); services are idempotent `async def` with no I/O.

KILL semantics (owner decision #1778 item X, fix round #2133): KILL never touches
the `sl` region's attach path — `sl.on.KILL` is an internal audit arm, so an
in-flight attach / verify / fallback / page always runs to completion (C-2.6,
C-4.14). KILL moves the parallel `amend_lock` region `open` → `frozen` (NOT
terminal): entry audits and publishes a plain `bool` (C-2.20); the
`amend_locked` guard then refuses (audited) every TIGHTEN/LOOSEN in `protected`.
No action in this module cancels, amends or detaches an SL.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas

#: Audit hook injected by the owning module (B10/B16 pattern). Must not raise.
AuditHook = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _no_hook(_name: str, _ctx: dict[str, Any]) -> None:
    return None


_hook: AuditHook = _no_hook


def set_audit_hook(hook: AuditHook | None) -> None:
    global _hook
    _hook = hook or _no_hook


#: Plain-bool frozen flags keyed by (account_id, symbol) — C-2.20: published on
#: state entry, read by synchronous code; never an interpreter query. Never an
#: anonymous entry: a context without both ids is not published (audited).
#: TODO(#2157): re-publish on snapshot restore (entry actions do not re-run);
#: until then the chart-local `context["frozen"]` (snapshotted) is authoritative
#: for `amend_locked`, and E32 moves this map to its owning registry.
_FROZEN: dict[tuple[str, str], bool] = {}


def _key(context: dict[str, Any]) -> tuple[str, str] | None:
    acc, sym = context.get("account_id"), context.get("symbol")
    if acc is None or sym is None:
        return None
    return str(acc), str(sym)


def is_frozen(account_id: str, symbol: str) -> bool:
    return _FROZEN.get((account_id, symbol), False)


def clear_frozen_flags() -> None:
    """Test/boot helper: drop every published flag."""
    _FROZEN.clear()


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


def _deny_guard(*_args: object, **_kwargs: object) -> bool:
    return False


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


# --- KILL / frozen arm (#1650) ---------------------------------------------------------


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("frozen_by_kill", context)


async def publish_frozen_flag(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["frozen"] = True
    key = _key(context)
    if key is None:
        await _hook("frozen_flag_unkeyed", context)
        return
    _FROZEN[key] = True


async def audit_kill_sl_continues(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`sl` region KILL: recorded only; the attach path keeps running (C-2.6)."""
    await _hook("kill_sl_path_continues", context)


def amend_locked(context: dict[str, Any], _event: Any) -> bool:
    """True once KILL froze amendments. Total: any error → locked (deny polarity)."""
    try:
        return context.get("frozen") is True
    except Exception:
        return True


async def audit_amend_refused_frozen(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("amend_refused_frozen", context)


async def audit_frozen_event(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("frozen_event_ignored", context)


async def audit_guard_denied(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("guard_denied", context)


_STUB_ACTIONS = (
    "arm_sl_deadline",
    "bump_attach_attempts",
    "bump_fallback_attempts",
    "bump_miss_counter",
    "consider_reduce_only_close",
    "emit_naked_metric",
    "maybe_raise_watchdog_miss",
    "page_owner",
    "raise_critical_alert",
    "reset_fallback_attempts",
    "reset_miss_counter",
    "stamp_naked_since",
)

ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    **{name: _noop_action for name in _STUB_ACTIONS},
    "audit_amend_refused_frozen": audit_amend_refused_frozen,
    "audit_frozen_event": audit_frozen_event,
    "audit_guard_denied": audit_guard_denied,
    "audit_kill": audit_kill,
    "audit_kill_sl_continues": audit_kill_sl_continues,
    "publish_frozen_flag": publish_frozen_flag,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "amend_locked": amend_locked,
    "attach_attempts_left": _deny_guard,
    "exchange_reports_sl": _deny_guard,
    "explicit_audited_override": _deny_guard,
    "fallback_attempts_left": _deny_guard,
    "sl_observed": _deny_guard,
    "tightens_only": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "attach_fallback_sl": _idempotent_service,
    "attach_native_sl": _idempotent_service,
    "read_position_sl": _idempotent_service,
    "set_trading_stop": _idempotent_service,
}

register_binding_module("position_protection", __name__)

_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "position_protection",
    {
        name: _ANY_PAYLOAD
        for name in (
            "KILL",
            "LOOSEN_SL",
            "POSITION_FLAT",
            "POSITION_OPENED",
            "SCAN_DUE",
            "SL_DEADLINE",
            "SL_OBSERVED",
            "TIGHTEN_SL",
            "WATCHDOG_MISS",
        )
    },
)
