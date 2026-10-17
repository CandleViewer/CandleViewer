"""candleviewer.statechart.bindings.b16_session — guards/actions for B16
`session` (E09-S03, US-ONB-004/009; idle lock #2301).

Only `stamp_idle_deadline`/`set_revoke_*`/audit-adjacent actions and the
guards live here; the actual idle/absolute-lifetime policy numbers (5-60 min
configurable idle, 12 h absolute) are owned by
`candleviewer.auth.session_service.SessionService`, which drives this
machine via `REQUEST`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE`/`REVOKE`/`LOGOUT`
events computed from the `sessions` row — this module never reads a clock
or a config value itself (CV-C-hot-path: statecharts record, synchronous
code enforces, C-2.21). `IDLE_DEADLINE` is the idle LOCK (`auth.idle_locked`,
lifted only by `UNLOCK_OK`), never a revocation (#2301, ADR-0020 §4).

No service (`SERVICES`) is needed for B16 — every transition here is a
timer (`after:`, driven by the caller) or an externally-raised event, never
an invoked async operation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


class AuditSink(Protocol):
    """The M19 audit emitter, injected by the composition root (`statechart`
    and `auth` may not import `audit`; C-3.3). Same `emit` shape as
    `AuditWriter.emit`."""

    async def emit(self, action: str, **kwargs: Any) -> None: ...


class B16AuditSinkMissingError(RuntimeError):
    """An audit action ran with no sink wired: fail loud (C-2.9), never skip."""


_SINK: list[AuditSink] = []


def set_audit_sink(sink: AuditSink | None) -> None:
    """Install (or clear, with `None`) the process-wide B16 audit sink."""
    _SINK.clear()
    if sink is not None:
        _SINK.append(sink)


def _identity(context: dict[str, Any]) -> tuple[str | None, str | None]:
    inp = context.get("input")
    src = inp if isinstance(inp, dict) else context
    sid, uid = src.get("session_id"), src.get("user_id")
    return (None if sid is None else str(sid)), (None if uid is None else str(uid))


def elevation_view(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "elevated_classes": sorted((context.get("elevated_classes") or {}).keys()),
        "step_up_failures": int(context.get("step_up_failures", 0) or 0),
        "readonly_until_us": context.get("readonly_until_us"),
        "idle_locked": context.get("idle_locked") is True,
        "unlock_attempts": int(context.get("unlock_attempts", 0) or 0),
        "revoke_reason": context.get("revoke_reason"),
    }


async def _emit(
    context: dict[str, Any],
    event: Any,
    action: str,
    *,
    outcome: str = "success",
    severity: str = "info",
    reason: str | None = None,
) -> None:
    """Write one audit record for this transition (C-2.9, C-12.8): actor,
    session, before/after elevation state. `replay=True` events (chart
    hydration from the persisted `sessions` row) were audited when they
    first happened and are not re-recorded. A step-up challenge (#2304) is
    the record's object; a no-grace grant also names the SHA-256 of the
    request it is bound to (never the request itself)."""
    payload = _payload(event)
    if payload.get("replay"):
        return
    if not _SINK:
        raise B16AuditSinkMissingError(f"B16 {action}: no audit sink wired")
    sid, uid = _identity(context)
    before = payload.get("before")
    after = elevation_view(context)
    challenge, bound = payload.get("challenge_id"), payload.get("request_sha256")
    if isinstance(bound, str):
        after["bound_request_sha256"] = bound
    await _SINK[0].emit(
        action,
        actor_label=uid or "system",
        actor_user_id=uid,
        session_id=sid,
        object_kind="step_up_challenge" if isinstance(challenge, str) else None,
        object_id=challenge if isinstance(challenge, str) else None,
        outcome=outcome,
        severity=severity,
        reason=reason,
        before_state=before if isinstance(before, dict) else None,
        after_state=after,
    )


def _cls(event: Any) -> str | None:
    value = _payload(event).get("action_class")
    return value if isinstance(value, str) else None


#: Ticket "Technical notes" / catalogue B16.4: five failed MFA attempts on
#: one session's `pending_mfa` leg locks it (mirrors `MfaService`'s own
#: `CHALLENGE_ATTEMPT_CAP`, but this is the *chart's* own attempt counter
#: in `context`, independent of the `mfa_challenges` row E09-S02 owns).
MFA_ATTEMPT_CAP = 5


def mfa_attempts_exhausted(context: dict[str, Any], event: dict[str, Any]) -> bool:
    """Guard: `context['mfa_attempts'] >= MFA_ATTEMPT_CAP`.

    Pure predicate, no I/O (B16.4 contract); total — returns `False` (never
    raises) on any malformed context, per catalogue A6 ("no I/O; total;
    returns False on any internal error and logs at ERROR")."""
    try:
        attempts = context.get("mfa_attempts", 0)
        return bool(int(attempts) >= MFA_ATTEMPT_CAP)
    except (TypeError, ValueError):
        return False


def _payload(event: Any) -> dict[str, Any]:
    """The library hands actions an `Event` (payload on `.payload`), not a dict."""
    payload = getattr(event, "payload", event)
    return payload if isinstance(payload, dict) else {}


async def mark_mfa_satisfied(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["mfa_satisfied"] = True


async def bump_mfa_attempts(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["mfa_attempts"] = int(context.get("mfa_attempts", 0)) + 1


async def audit_mfa_failed(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    """`auth.mfa_failed` through the injected sink (no `audit` import)."""
    await _emit(context, event, "auth.mfa_failed", outcome="failure", severity="warning")


async def set_revoke_locked(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["revoke_reason"] = "locked"


async def set_revoke_timeout(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["revoke_reason"] = "timeout"


async def set_revoke_expired(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["revoke_reason"] = "expired"


async def set_revoke_admin(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["revoke_reason"] = "admin"


async def set_revoke_logout(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["revoke_reason"] = "logout"


async def stamp_idle_deadline(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    """Re-stamped on every `REQUEST` (ticket "idle timeout ... driven by
    `sessions.last_seen_at`") — the deadline value itself is computed by
    the caller and carried on the event payload (`event['idle_expires_at_
    us']`), never derived from a clock read in this binding."""
    idle_expires_at_us = _payload(event).get("idle_expires_at_us")
    if idle_expires_at_us is not None:
        context["idle_expires_at_us"] = idle_expires_at_us


async def audit_login(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    await _emit(context, event, "auth.login")


async def audit_session_revoked(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    reason = _payload(event).get("reason") or context.get("revoke_reason")
    await _emit(
        context,
        event,
        "auth.session_revoked",
        severity="warning",
        reason=None if reason is None else str(reason),
    )


async def broadcast_revocation(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    """Placeholder for the WS revocation-frame publish (E17 owns the
    transport itself; this action only marks that the chart reached the
    terminal `revoked` state so `SessionService` can react to the
    interpreter's state-entry notification, per this ticket's "Out of
    scope: the WS transport implementation itself")."""
    return None


async def stamp_elevated_until(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    payload = _payload(event)
    elevated_until_us = payload.get("elevated_until_us")
    if elevated_until_us is not None:
        context["elevated_until_us"] = elevated_until_us
        action_class = payload.get("action_class")
        # No-grace classes never open a window (ticket "No-grace list").
        if action_class in NO_GRACE_ACTION_CLASSES:
            return
        if action_class in ACTION_CLASSES:
            context.setdefault("elevated_classes", {})[action_class] = elevated_until_us
    context["step_up_failures"] = 0


async def audit_step_up(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    await _emit(context, event, "auth.step_up_granted", reason=_cls(event))


async def audit_step_up_failed(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    remaining = max(STEP_UP_FAILURE_CAP - int(context.get("step_up_failures", 0) or 0), 0)
    await _emit(
        context,
        event,
        "auth.step_up_failed",
        outcome="failure",
        severity="error",
        reason=f"{_cls(event)}:remaining={remaining}",
    )


async def clear_elevated(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["elevated_until_us"] = None
    context["elevated_classes"] = {}


async def schedule_elevation_deadline(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    return None


# -- E09-S04: step-up re-authentication (US-ONB-005) -------------------------

#: Ticket: "a 5-minute grace per action class".
STEP_UP_GRACE_US = 5 * 60 * 1_000_000
#: Ticket: three invalid codes abandon the action and downgrade the session.
STEP_UP_FAILURE_CAP = 3
#: Ticket: the downgrade lasts 5 minutes.
READONLY_DOWNGRADE_US = 5 * 60 * 1_000_000
#: Ticket "No-grace list": a fresh code is *always* required for these.
#: `backups` (#2751): a restore is irreversible.
NO_GRACE_ACTION_CLASSES = frozenset({"live_enablement", "killswitch", "backups"})
#: `recorder` (04 §7.2.2 rows 9 and 9a): retention and pin changes (#2738) and the
#: irreversible recorded-data purge (E16-T06); a grace class.
#: `audit` and `backups` (#2751, SR-025): the audit-log export and a backup restore.
#: `flags` (#3083): a feature-flag write; a grace class, as the contract's `setFeatureFlag` says.
ACTION_CLASSES = frozenset(
    {
        "keys",
        "users",
        "live_enablement",
        "killswitch",
        "risk_caps",
        "recorder",
        "flags",
        "audit",
        "backups",
    }
)


def grace_window_valid(context: dict[str, Any], event: dict[str, Any]) -> bool:
    """Guard: is there an unexpired grace window for `event.action_class`?

    False unconditionally for the no-grace list. Total: any malformed input
    yields False (fail closed, catalogue A6)."""
    try:
        payload = _payload(event)
        action_class = payload.get("action_class")
        if action_class in NO_GRACE_ACTION_CLASSES or action_class not in ACTION_CLASSES:
            return False
        until = (context.get("elevated_classes") or {}).get(action_class)
        now_us = payload.get("now_us")
        return bool(until is not None and now_us is not None and int(now_us) < int(until))
    except (TypeError, ValueError, AttributeError):
        return False


def step_up_strikes_exhausted(context: dict[str, Any], event: dict[str, Any]) -> bool:
    """Guard: this failure is the third (`step_up_failures + 1 >= cap`)."""
    try:
        return bool(int(context.get("step_up_failures", 0)) + 1 >= STEP_UP_FAILURE_CAP)
    except (TypeError, ValueError):
        return False


async def record_step_up_failure(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["step_up_failures"] = int(context.get("step_up_failures", 0)) + 1
    if context["step_up_failures"] >= STEP_UP_FAILURE_CAP:
        now_us = _payload(event).get("now_us")
        if now_us is not None:
            context["readonly_until_us"] = int(now_us) + READONLY_DOWNGRADE_US


async def clear_step_up_failures(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["step_up_failures"] = 0
    context["readonly_until_us"] = None


async def audit_step_up_required(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    await _emit(
        context,
        event,
        "auth.step_up_required",
        outcome="denied",
        severity="warning",
        reason=_cls(event),
    )


async def audit_grace_used(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    await _emit(context, event, "auth.step_up_grace_used", reason=_cls(event))


async def audit_readonly_downgrade(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    await _emit(
        context,
        event,
        "auth.session_readonly_downgrade",
        outcome="denied",
        severity="error",
        reason=_cls(event),
    )


# -- #2301: idle lock (`auth.idle_locked`, ADR-0020 §4) ----------------------


def unlock_attempts_exhausted(context: dict[str, Any], event: dict[str, Any]) -> bool:
    """Guard: synchronous code decided that this failed unlock revoked the
    session (`SessionService.unlock()` raises `SessionRevoked` at
    `MAX_UNLOCK_ATTEMPTS`), so the event carries `revoked: true`. Never derived
    from the chart's own `unlock_attempts`, which a restart or an eviction resets
    independently of the service's count. Total: anything but `True` is `False` (A6)."""
    return _payload(event).get("revoked") is True


def session_active(context: dict[str, Any], event: dict[str, Any]) -> bool:
    """Guard on granting elevation: MFA satisfied, the lock flag explicitly
    clear and no revocation (A6, deny-by-default). Elevation is never granted
    before MFA, while locked or after a revocation."""
    return (
        context.get("mfa_satisfied") is True
        and context.get("idle_locked") is False
        and context.get("revoke_reason") is None
    )


def session_revoked(context: dict[str, Any], event: dict[str, Any]) -> bool:
    """Guard of the eventless `elevation -> dead` arm: a `set_revoke_*` action
    committed in the `auth` step (a rolled-back step leaves it `None`)."""
    return context.get("revoke_reason") is not None


async def mark_idle_locked(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["idle_locked"] = True


async def clear_idle_locked(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    """`idle_locked` exit: every lock starts a fresh attempt count."""
    context["idle_locked"] = False
    context["unlock_attempts"] = 0


async def bump_unlock_attempts(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    context["unlock_attempts"] = int(context.get("unlock_attempts", 0) or 0) + 1


async def disarm_one_click(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    """Lock entry records the one-click disarm; unlock never re-arms it (#2290
    rule 2d). Chart context only: the OMS validator reads the session's arm
    record, never this chart, and `SessionService.unlock()` invalidates that
    record when it lifts a lock (B16.5/B16.7, C-2.20, C-2.21)."""
    context["one_click_armed"] = False


async def audit_idle_locked(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    await _emit(context, event, "auth.idle_locked")


async def audit_ignored_request(
    _interp: Any, context: dict[str, Any], event: dict[str, Any], _action_def: Any
) -> None:
    """Activity on a locked session, or an unlock outside a lock: recorded and
    consumed, never deferred (a deferred unlock would lift the next lock)."""
    event_type = getattr(event, "type", None)
    await _emit(
        context,
        event,
        "auth.request_ignored",
        outcome="denied",
        severity="warning",
        reason=event_type if isinstance(event_type, str) else None,
    )


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "mark_mfa_satisfied": mark_mfa_satisfied,
    "bump_mfa_attempts": bump_mfa_attempts,
    "audit_mfa_failed": audit_mfa_failed,
    "set_revoke_locked": set_revoke_locked,
    "set_revoke_timeout": set_revoke_timeout,
    "set_revoke_expired": set_revoke_expired,
    "set_revoke_admin": set_revoke_admin,
    "set_revoke_logout": set_revoke_logout,
    "stamp_idle_deadline": stamp_idle_deadline,
    "audit_login": audit_login,
    "audit_session_revoked": audit_session_revoked,
    "broadcast_revocation": broadcast_revocation,
    "stamp_elevated_until": stamp_elevated_until,
    "audit_step_up": audit_step_up,
    "audit_step_up_failed": audit_step_up_failed,
    "clear_elevated": clear_elevated,
    "schedule_elevation_deadline": schedule_elevation_deadline,
    "record_step_up_failure": record_step_up_failure,
    "clear_step_up_failures": clear_step_up_failures,
    "audit_step_up_required": audit_step_up_required,
    "audit_grace_used": audit_grace_used,
    "audit_readonly_downgrade": audit_readonly_downgrade,
    "mark_idle_locked": mark_idle_locked,
    "clear_idle_locked": clear_idle_locked,
    "bump_unlock_attempts": bump_unlock_attempts,
    "disarm_one_click": disarm_one_click,
    "audit_idle_locked": audit_idle_locked,
    "audit_ignored_request": audit_ignored_request,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "mfa_attempts_exhausted": mfa_attempts_exhausted,
    "grace_window_valid": grace_window_valid,
    "step_up_strikes_exhausted": step_up_strikes_exhausted,
    "unlock_attempts_exhausted": unlock_attempts_exhausted,
    "session_active": session_active,
    "session_revoked": session_revoked,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("session", __name__)

#: B16 events this ticket owns (CV-C-strict: `strict=True` refuses any
#: event with no schema entry here). Minimal shape — `type` is always
#: implied by the dict key the library indexes on; these are the payload
#: fields each event may carry, all optional so a bare `{"type": "..."}`
#: event (e.g. `LOGOUT`, `REVOKE`) still validates.
register_event_schemas(
    {
        "MFA_OK": {"type": "object", "additionalProperties": True},
        "MFA_FAILED": {"type": "object", "additionalProperties": True},
        "MFA_TIMEOUT": {"type": "object", "additionalProperties": True},
        "REQUEST": {"type": "object", "additionalProperties": True},
        "IDLE_DEADLINE": {"type": "object", "additionalProperties": True},
        "ABSOLUTE_DEADLINE": {"type": "object", "additionalProperties": True},
        "REVOKE": {"type": "object", "additionalProperties": True},
        "LOGOUT": {"type": "object", "additionalProperties": True},
        "STEP_UP_OK": {"type": "object", "additionalProperties": True},
        "STEP_UP_FAILED": {"type": "object", "additionalProperties": True},
        "ELEVATION_DEADLINE": {"type": "object", "additionalProperties": True},
        "ACTION_REQUEST": {"type": "object", "additionalProperties": True},
        "READONLY_EXPIRED": {"type": "object", "additionalProperties": True},
        "UNLOCK_OK": {"type": "object", "additionalProperties": True},
        "UNLOCK_FAILED": {"type": "object", "additionalProperties": True},
    }
)
