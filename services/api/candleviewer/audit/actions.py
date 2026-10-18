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
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome

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
        # #3120 (C-2.9): `SessionService.require_active` revoked a disabled or deleted user's
        # surviving session on use (SR-029); written through the port `AuthService` attaches.
        "auth.disabled_user_session_revoked",
        "auth.idle_locked",
        # #2300 (E09-D06 ruling): named by the `POST /auth/unlock` and
        # `POST /auth/session/extend` contracts; the routes that emit them ship in that
        # ticket's slice 2/2.
        "auth.session_unlocked",
        "auth.unlock_failed",
        "auth.session_extended",
        "auth.refresh_reuse_detected",
        "auth.csrf_refused",
        # E09-X02 AC2 (#2144, U6/SR-013): a session credential this server never issued, or
        # another user's, presented to the session routes or carried into the MFA step.
        "auth.session_fixation_attempt",
        # #2269 (SR-042/SR-183): a WS upgrade refused by the Origin check (`ws/origin_audit.py`).
        "auth.ws_origin_refused",
        # E09-X02 (#2319, AC-CSRF-05): `DELETE /me/sessions/{id}` for an id that is not one of the
        # caller's live sessions (the response is the same 404 for a foreign id, an unknown id and
        # the caller's own ended session).
        "auth.session_revoke_denied",
        "auth.mfa_enroll",
        "auth.mfa_reset",
        "auth.step_up_granted",
        "auth.step_up_failed",
        # #2304: a no-grace grant bound to one request, presented by another (`api/step_up.py`).
        "auth.step_up_mismatch",
        "auth.step_up_required",
        "auth.step_up_grace_used",
        "auth.session_readonly_downgrade",
        # #2301: the B16 chart records activity on an idle-locked session, a step-up
        # it refuses to record as elevation, and an unlock outside a lock.
        "auth.request_ignored",
        "auth.mfa_reset_by_owner",
        "auth.mfa_verified",
        "auth.mfa_failed",
        "auth.mfa_enrolled",
        "auth.recovery_code_used",
        "auth.recovery_codes_exhausted",
        "auth.recovery_codes_regenerated",
        # E09-S11 (#2119, SR-023): the offline break-glass CLI's intent, refusal and reset
        # records (actor `system:breakglass`), folded in from its host journal at boot.
        "auth.break_glass_attempt",
        "auth.break_glass_refused",
        "auth.break_glass_reset",
        "auth.password_change",
        "ws.subscribe.denied",
        # SR-186 (#2174): the private-topic subscriptions one WS `sub` frame made, one record.
        "ws.subscribe.granted",
        "ws.subscription.revoked",
        # E17-S01 (#2486): an authenticated WS connection ended (`ws/gateway.py`).
        "ws.connection.closed",
        # SR-189 (#2172): an older WS permission snapshot refused in favour of a newer one.
        "ws.permission_snapshot.refused",
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
        # E42-T08 (#2648, #965 R5): a user's account-access grant set replaced, written ahead
        # of the commit with the live grants before and after (`account_access_sqlalchemy.py`).
        "users.access_change",
        # Closes a write-ahead `users.access_change` whose commit failed or was cancelled.
        "users.access_change_failed",
        "roles.grant",
        "roles.revoke",
        "accounts.create",
        "accounts.enable_trading",
        "api_key.import",
        "api_key.rotate",
        "api_key.revoke",
        "api_key.reveal_attempt",
        # E27-T03 (#836): a persisted stored-key verdict, and the force-disable of an account whose
        # key failed it (threat model E27-accounts §8.1, SR-E27-09; system actor, write-ahead).
        "account.tested",
        "account.disabled_by_policy",
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
        # E26-T01: replay session lifecycle (#624 decision: destroyed carries
        # reason idle_reclaim|client; error is the chart entering `error`).
        "replay.session.created",
        "replay.session.destroyed",
        "replay.session.error",
        "retention.change",
        "retention.purge",
        # E16-T06: per-pass reaper record + one write-ahead record per deletion (system actor).
        "retention.run",
        "data.deleted",
        "retention.downsample",
        "rolloff.drop_aborted",
        # #2522: the DROP was issued but QuestDB could not be confirmed to have applied it; the
        # outcome of a `retention.purge` intent (the day stays retained, never "dropped").
        "rolloff.drop_unconfirmed",
        "flags.change",
        # E42-T03: emitted on a stored transition of `maintenance.mode`, boot included
        # (`setFeatureFlag`), alongside the `flags.change` entry when it came from a `PUT`.
        "maintenance.enabled",
        "maintenance.disabled",
        "settings.change",
        # E42-T05 (SR-E42-11): an incident moved from `open` to `acknowledged`.
        "incident.acknowledged",
        "hotkey.trading_binding_changed",
        # E09-S06 (#2323): a client-supplied body on the self-scope checklist dismissal
        # (`api/onboarding.py`). Unregistered, the real writer refused it (500, no row).
        "onboarding.checklist_tamper_rejected",
        "backup.run",
        "backup.restore",
        "env.switch_live",
        "admin.audit_read",
        "admin.audit_verify",
        "admin.audit_export",
        "admin.audit_denied",
        # E42-T01: entering any /admin/* route (allowed or denied), {route, reauth_age_s}.
        "admin.area_entered",
        # #3085 (E42 AD-F03): read-only view-as, emitted by its server slice. Their fields,
        # reasons and severity are 22-api-openapi.yaml's (`startViewAs`, `endViewAs`, "View-as
        # session"); not restated here (C-16.5).
        "admin.view_as_started",
        "admin.view_as_ended",
        "admin.view_as_refused",
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
        # #2266: one per re-wrapped row, committed with the row's compare-and-set (M10 adapter).
        "security.credential_rewrapped",
        # #2266: a KEK re-wrap run opens with it when an earlier run moved rows and rows are left.
        "security.kek_rotation_resumed",
        # #2728 (E16 R-E3 "config audit"): the keyless-testnet test clock is on at boot
        # (system actor `system:test-clock`, `auth/testnet_clock.py`).
        "system.config.test_clock_enabled",
        # #2893 S8 (FX-R01): the dev-only account fixture transport is on and its boot guard
        # passed (system actor `system:account-fixture`, `candleviewer/account_fixture_wiring.py`).
        "system.config.account_fixture_enabled",
    }
)

for _action in AUDIT_ACTIONS:
    if not _ACTION_FMT_RE.match(_action):  # pragma: no cover - defends the registry itself
        raise AuditError(f"registry action {_action!r} violates au_action_fmt")

LaneClass = Literal["reserved", "shared"]
_ANY = frozenset(AuditOutcome)

#: The journal-first audit lane's closed registry (ADR-0037 decision 3; the single source, C-16.5):
#: each admitted action, its class and the outcomes it may carry. The class follows the action,
#: never the caller. The two `audit.lane_*` rows join AUDIT_ACTIONS in S2a2, which first emits them.
LANE_ACTIONS: Mapping[str, tuple[LaneClass, frozenset[str]]] = MappingProxyType(
    {
        "auth.logout": ("reserved", _ANY),
        "auth.session_revoked": ("reserved", _ANY),
        "auth.refresh_reuse_detected": ("reserved", _ANY),
        # #3120 (EX-08): the backstop revocation's outcome; #3355 adds it to AUDIT_ACTIONS.
        "auth.disabled_user_session_revoked": ("reserved", frozenset({AuditOutcome.SUCCESS})),
        "auth.session_refreshed": ("shared", frozenset({AuditOutcome.DENIED})),
        "auth.login": ("shared", _ANY),
        "auth.login_failed": ("shared", _ANY),
        "auth.account_locked": ("shared", _ANY),
        "auth.mfa_failed": ("shared", _ANY),
        "auth.recovery_codes_exhausted": ("shared", _ANY),
        "auth.recovery_code_used": ("shared", _ANY),
        "audit.lane_started": ("reserved", frozenset({AuditOutcome.SUCCESS})),
        "audit.lane_resumed": ("reserved", frozenset({AuditOutcome.SUCCESS})),
    }
)


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
