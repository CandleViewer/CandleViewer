"""Session -> `rules.manager.Actor` resolver for `/rules` (E35-S01).

Everything is re-derived server-side per request (C-12.4): permissions and granted
accounts from the identity store, the owner flag from the user's roles, and live-arming
step-up from the session's one-shot `live_enablement` grant (no-grace class, consumed
exactly once by the transition that uses it, and only by the request it is bound to:
#2304, the SHA-256 of the method, raw target and canonical body of `PUT /rules/{id}/mode`).
A refusal carries the challenge it issued, so the client answers that challenge by id and
re-sends the held request.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import Request

from candleviewer.api.step_up import (
    STEP_UP_REQUIRED_DETAIL,
    STEP_UP_REQUIRED_TITLE,
    consume_bound_grant,
)
from candleviewer.api.step_up_challenge import raw_request_target, request_fingerprint
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.errors import AuthError, SessionReadOnly, SessionRevoked
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.step_up import StepUpChallenge
from candleviewer.rules.manager import Actor, RuleError

STEP_UP_CLASS = "live_enablement"
#: A body that is not I-JSON (RFC 7493) has no RFC 8785 form, so no grant can be bound to it.
_UNBINDABLE = "The request body is not I-JSON, so a step-up cannot be bound to it."

#: `RulesManager` audit event -> registered `audit.actions` verb (the closed 3.10.1 list);
#: the full event name is preserved in `after_state.event`.
_ACTIONS: dict[str, str] = {
    "rule.armed": "rules.arm",
    "rule.disarmed": "rules.disarm",
    "rule.created": "rules.version_create",
    "rule.updated": "rules.version_create",
    "rule.deleted": "rules.delete",
    "rule.simulated": "rules.simulate",
    "rule.mode_refused": "rules.arm",
    # E35-X02: protected-rule refusals / tampering and import refusals are denials.
    "rule.system_rule_refused": "rules.scope_denied",
    "rule.system_rule_tampered": "rules.scope_denied",
    "rule.import_refused": "rules.scope_denied",
    "rule.scope_refused": "rules.scope_denied",
}
_DENIED = frozenset(
    {"rule.mode_refused", "rule.system_rule_refused", "rule.system_rule_tampered",
     "rule.import_refused", "rule.scope_refused"}
)  # fmt: skip


def _before(payload: dict[str, Any]) -> dict[str, Any] | None:
    """C-2.9 before/after: the prior mode and B9 state of a mode change."""
    if "from" not in payload:
        return None
    before = {"mode": payload["from"]}
    if "b9_from" in payload:
        before["b9_state"] = payload["b9_from"]
    return before


def _challenged(challenge: StepUpChallenge) -> RuleError:
    """`403 step_up_required` carrying the challenge issued for this request (#2304): a no-grace
    step-up must name it, so a refusal without it could never be answered. Its title and detail
    are the ones every challenge states (`api.step_up.required_problem`)."""
    return RuleError(
        403,
        "step_up_required",
        STEP_UP_REQUIRED_DETAIL,
        title=STEP_UP_REQUIRED_TITLE,
        action_class=challenge.action_class,
        challenge_id=str(challenge.challenge_id),
        challenge_expires_at=challenge.expires_at.isoformat(),
    )


def _unanswerable(exc: SessionReadOnly | SessionRevoked) -> RuleError:
    """A session that cannot answer a challenge gets its own refusal, never a challenge."""
    if isinstance(exc, SessionReadOnly):
        until = exc.until.isoformat() if isinstance(exc.until, datetime) else None
        return RuleError(
            403,
            "session_read_only",
            "This session is read-only for 5 minutes after repeated step-up failures.",
            readonly_until=until,
        )
    return RuleError(401, "unauthorized", "no verified session")


def make_rules_audit(emitter: Any) -> Callable[[str, dict[str, Any]], Any]:
    """Write-ahead audit callback (C-2.9) for `RulesManager`: ir_hash, environment, scope."""

    async def audit(action: str, payload: dict[str, Any]) -> None:
        await emitter.emit(
            _ACTIONS.get(action, "rules.version_create"),
            actor_label=str(payload.get("actor", "system")),
            actor_user_id=payload.get("actor"),
            outcome=AuditOutcome.DENIED if action in _DENIED else AuditOutcome.SUCCESS,
            object_kind="rule",
            object_id=str(payload.get("rule_id", "")),
            before_state=_before(payload),
            after_state={k: v for k, v in payload.items() if k != "actor"} | {"event": action},
        )

    return audit


class SessionRulesActorResolver:
    def __init__(
        self,
        sessions: Callable[[], Any],
        step_up: Callable[[], Any],
        identity: Any,
        emitter: Any = None,
    ) -> None:
        self._sessions, self._step_up, self._identity = sessions, step_up, identity
        self._emitter = emitter  # writes `auth.step_up_mismatch` (#2304)

    async def resolve(self, request: Request) -> Actor | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            record = await self._sessions().authenticate_access_token(token, touch=True)
            user = await self._identity.user(str(record.user_id))
            info = await self._identity.session_info(str(record.user_id))
        except (AuthError, RuntimeError, LookupError):
            return None
        if user.get("status") != "active":
            return None
        try:
            # Sanctioned owner decision; unknown roles raise -> no actor (fail closed).
            snapshot = PrincipalSnapshot(
                user_id=uuid.UUID(str(record.user_id)),
                roles=frozenset(str(r) for r in (user.get("roles") or ())),
                permissions=frozenset(),
            )
        except ValueError:
            return None
        session_id = str(record.id)
        step_up, emitter = self._step_up, self._emitter

        async def challenge() -> StepUpChallenge | None:
            # None: this request used the grant bound to it; else the challenge issued for it.
            # The body `set_mode` validated: Starlette caches the one parsed object.
            try:
                body = await request.json()
                fingerprint = request_fingerprint(request.method, raw_request_target(request), body)
            except (ValueError, TypeError) as exc:  # not I-JSON: never bound, so never armed
                raise RuleError(400, "validation_failed", _UNBINDABLE) from exc
            return await consume_bound_grant(
                step_up(), emitter, session_id, STEP_UP_CLASS, fingerprint
            )

        async def consume() -> bool:
            try:
                issued = await challenge()
            except (SessionReadOnly, SessionRevoked) as exc:
                raise _unanswerable(exc) from exc
            if issued is not None:
                raise _challenged(issued)
            return True

        return Actor(
            user_id=str(record.user_id),
            session_id=session_id,
            perms=frozenset(str(p) for p in info.get("permissions", ())),
            granted_accounts=frozenset(str(a) for a in info.get("account_scope", ())),
            is_owner=snapshot.is_owner,
            step_up_fresh=True,  # the authoritative check is `consume` (one-shot, no grace)
            consume_step_up=consume,
        )
