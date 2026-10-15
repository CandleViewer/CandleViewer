"""Typed action registry for `audit.emit` (M19, ticket "Scope / Deliverables":
"a typed action registry so `action` strings are not free-form at call sites").

The vocabulary below is the non-exhaustive list `docs/plan/21-database-schema.md`
Sec.3.10.1 enumerates as "actions that MUST be audited", plus the handful this
ticket's own acceptance criteria name explicitly (`admin.audit_denied` for the
non-owner-read-denial scenario, `admin.audit_read`/`admin.audit_verify`/
`admin.audit_export` for this module's own three endpoints). Every value
satisfies the migration's `au_action_fmt` CHECK
(`^[a-z0-9_]+([.][a-z0-9_]+){1,3}$`) — enforced here too so a typo'd literal
fails at call time (a clear `AuditError`) rather than at the INSERT.

Callers that need an action not yet in this registry add it here in the same
PR that starts calling `audit.emit` with it (single source of truth, C-16.5) —
never pass an ad-hoc string.
"""

from __future__ import annotations

import re

from candleviewer.audit.errors import AuditError

#: Mirrors the migration's `au_action_fmt` CHECK exactly.
_ACTION_FMT_RE = re.compile(r"^[a-z0-9_]+([.][a-z0-9_]+){1,3}$")

#: docs/plan/21-database-schema.md Sec.3.10.1 "Actions that MUST be audited"
#: plus this ticket's own admin.audit.* endpoints.
AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "auth.login",
        "auth.login_failed",
        "auth.account_locked",
        "auth.logout",
        "auth.session_created",
        "auth.session_refreshed",
        "auth.session_revoked",
        "auth.idle_locked",
        "auth.refresh_reuse_detected",
        "auth.csrf_refused",
        # E09-X02 AC2 (#2144, U6/SR-013): a session credential this server never issued, or
        # another user's, presented to the session routes or carried into the MFA step.
        "auth.session_fixation_attempt",
        "auth.mfa_enroll",
        "auth.mfa_reset",
        "auth.step_up_granted",
        "auth.step_up_failed",
        "auth.step_up_required",
        "auth.step_up_grace_used",
        "auth.session_readonly_downgrade",
        "auth.mfa_reset_by_owner",
        "auth.mfa_verified",
        "auth.mfa_failed",
        "auth.mfa_enrolled",
        "auth.recovery_code_used",
        "auth.recovery_codes_exhausted",
        "auth.recovery_codes_regenerated",
        "auth.password_change",
        "ws.subscribe.denied",
        "ws.subscription.revoked",
        "users.create",
        "users.invited",
        "users.invite_redeemed",
        "users.invite_rejected",
        "users.invite_reissued",
        "users.invite_revoked",
        # SR-027 (#2124/#2109): a pre-elevated invite request and a legacy-role downgrade.
        # Emitted by api/invites.py; unregistered, the real writer refused them (500, no row).
        "users.invite_refused",
        "users.invite_role_downgraded",
        "users.disable",
        "roles.grant",
        "roles.revoke",
        "accounts.create",
        "accounts.enable_trading",
        "api_key.import",
        "api_key.rotate",
        "api_key.revoke",
        "api_key.reveal_attempt",
        "profiles.update",
        "orders.submit",
        "orders.cancel",
        "orders.amend",
        "trade_group.submit",
        "positions.flatten",
        "risk.freeze_manager",
        "risk.unfreeze_manager",
        "rules.arm",
        "rules.scope_denied",
        "rules.live_scope_armed",
        "rules.disarm",
        "rules.version_create",
        "rules.simulate",
        "rules.delete",
        # E40-T02: every alert mutation and every cross-user denial is audited (one
        # `alert.<past-tense>` convention so prefix queries see them all).
        "alert.created",
        "alert.updated",
        "alert.enabled",
        "alert.disabled",
        "alert.deleted",
        "alert.denied",
        # E40-T03: evaluator firings and auto-disarms (system actor, C-2.9).
        "alert.fired",
        "alert.disarmed",
        "recorder.start",
        "recorder.stop",
        "recorder.compact",
        # E16-T10: public trade-archive import (write-ahead accept + outcome).
        "recorder.import",
        "retention.change",
        "retention.purge",
        "retention.downsample",
        "rolloff.drop_aborted",
        # #2522: the DROP was issued but QuestDB could not be confirmed to have applied it; the
        # outcome of a `retention.purge` intent (the day stays retained, never "dropped").
        "rolloff.drop_unconfirmed",
        "flags.change",
        "settings.change",
        "hotkey.trading_binding_changed",
        "backup.run",
        "backup.restore",
        "env.switch_live",
        "admin.audit_read",
        "admin.audit_verify",
        "admin.audit_export",
        "admin.audit_denied",
        "rbac.denied",
        "health.diagnostics_exported",
        # E27-T02: credential broker / KEK lifecycle (e27-kek.md §5-§6).
        "security.kek_loaded",
        "security.kek_load_failed",
        "security.kek_rotation_started",
        "security.kek_rotation_failed",
        "security.kek_rotated",
        "security.kek_rotation_incomplete",
        "security.kek_enrolled",
        "security.credential_stored",
        "security.credential_borrowed",
        "security.credential_destroyed",
        "security.credential_destroy_failed",
        "security.credential_store_failed",
        # #2339 security review: closes a write-ahead `credential_borrowed` when signing fails.
        "security.credential_sign_failed",
    }
)

for _action in AUDIT_ACTIONS:
    if not _ACTION_FMT_RE.match(_action):  # pragma: no cover - defends the registry itself
        raise AuditError(f"registry action {_action!r} violates au_action_fmt")


def validate_action(action: str) -> str:
    """Return `action` unchanged if it is a registered, well-formed action.

    Raises `UnknownAuditAction` otherwise — `audit.emit` calls this before
    ever touching the WAL or a connection, so a typo'd call site fails fast
    and loudly rather than silently writing a malformed row that only the
    database CHECK would reject.
    """
    if action not in AUDIT_ACTIONS:
        raise UnknownAuditAction(action)
    return action


class UnknownAuditAction(AuditError):
    """Raised by `validate_action` when `action` is not in `AUDIT_ACTIONS`."""

    def __init__(self, action: str) -> None:
        super().__init__(
            f"{action!r} is not a registered audit action — add it to "
            "candleviewer.audit.actions.AUDIT_ACTIONS in the same PR that emits it"
        )
        self.action = action
