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
        # #2300 (E09-D06 ruling): written write-ahead by `POST /auth/unlock` and
        # `POST /auth/session/extend`.
        "auth.session_unlocked",
        "auth.unlock_failed",
        "auth.session_extended",
        "auth.refresh_reuse_detected",
        # #3009 (ADR-0037 decision 13, Q9): a rotated refresh token presented again after this
        # process contained its family; the first containment keeps `auth.refresh_reuse_detected`.
        "auth.refresh_reuse_replayed",
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
        # #2295: an enrolment-only session refused outside its allow-list, on HTTP (403) or at
        # the WS `auth` (4403); emitted by api/enrolment_guard.py within its audit budgets.
        "auth.mfa_enrollment_required",
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
        # #4479 (SR-023): the offline bootstrap-Owner CLI's intent, refusal and invite records,
        # every one CRITICAL (actor `system:bootstrap`), journaled and folded in as break-glass's.
        "auth.bootstrap_owner_attempt",
        "auth.bootstrap_owner_refused",
        "auth.bootstrap_owner_invited",
        "auth.password_change",
        "ws.subscribe.denied",
        # SR-186 (#2174): the private-topic subscriptions one WS `sub` frame made, one record.
        "ws.subscribe.granted",
        "ws.subscription.revoked",
        # E17-S01 (#2486): an authenticated WS connection ended (`ws/gateway.py`).
        "ws.connection.closed",
        # SR-189 (#2172): an older WS permission snapshot refused in favour of a newer one.
        "ws.permission_snapshot.refused",
        # #3476: a user's first WS rebuild refused for its per-user limit in a window, one record.
        "ws.rebuild.refused",
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
        # #4479 (ruling 7, SR-023): the offline bootstrap invite's Owner grant, CRITICAL, written
        # ahead inside the activation's transaction by api/invites.py (refused: no grant).
        "users.owner_bootstrapped",
        "users.disable",
        # E42-T09 (#2649, #965 R5): `PATCH /users/{userId}` re-enabled a disabled user (nothing
        # restored, R6), and changed the display name or the MFA flag; both written ahead.
        "users.enable",
        "users.update",
        # E42-T09 (#2649, C-2.9, SR-055): an Owner revoked one of a user's sessions
        # (`revokeUserSession`): the Owner's own record, written ahead of B16's
        # `auth.session_revoked`, which names the session's own user.
        "users.session_revoked",
        # E42-T08 (#2648, #965 R5): a user's account-access grant set replaced, written ahead
        # of the commit with the live grants before and after (`account_access_sqlalchemy.py`).
        "users.access_change",
        # Closes a write-ahead `users.access_change` whose commit failed or was cancelled.
        "users.access_change_failed",
        # E42-T10 (#2650, #965 R5): a disabled user's purge scheduled by `?purge=true`, and the
        # reaper's anonymisation of one user (O6), each written ahead of its commit by
        # `user_purge_sqlalchemy.py`; ids, status and times only.
        "users.delete",
        "users.anonymise",
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
        # E27-S04 (#898 B3b2): `updateExchangeAccount`'s disable and its other changes (a re-enable,
        # a relabel), each written ahead of its commit (C-2.9), a disable or re-enable naming the
        # `challenge_id` of the `accounts` grant it spent; a refusal after the gate is the same
        # action with outcome `denied` and its code. A repeat writes none.
        "account.disabled",
        "account.updated",
        # E27-S04 (#898 B3c): `deleteExchangeAccount`, written ahead of the switch-off it commits
        # with (C-2.9), naming the `challenge_id` of the `accounts` grant it spent; a refusal after
        # the gate is the same action with outcome `denied` and its code.
        "account.deleted",
        # E27-S04 (#898 B3d): `revokeApiKey`'s completion record, after the key is destroyed and
        # the close of its private streams completed (22): keyed (`KEYED_ACTIONS`) by the key, so
        # each revoke has one, written by the call whose close completes and never twice (R7).
        "api_key.revoked",
        # E27-T03 (#836, decision 12): a key that fails its verification policy, `{rule, key_id}`
        # (the account's id where no key is stored); critical for a withdraw, transfer, fiat or
        # card right, any right that moves funds.
        "security.key_policy_violation",
        # E28-T02 (#906): a profile write, written ahead of its commit (C-2.9) with `object_kind`
        # `account_profile` and the profile's id; 24 Sec.15.5 holds the fields. The default moves
        # only by `setAccountDefaultProfile` (#906 0d), as `.unbound` (the profile it replaces) then
        # `.bound`, `relaxing` when looser (D7). `.save_refused` is a save refused before anything
        # is stored, its `reason` one of `PROFILE_SAVE_REFUSED_REASONS`.
        "profile.created",
        "profile.updated",
        "profile.deleted",
        "profile.bound",
        "profile.unbound",
        "profile.save_refused",
        "orders.submit",
        "orders.cancel",
        "orders.amend",
        # E29-T07 (#915, 24 Sec.15.5; SR-E29-09): an Owner's read of an order's diagnostics,
        # written before its body is sent (`api.order_diagnostics`), the order its object.
        "order.diagnostics_viewed",
        # E29-T03 (#847, 24 Sec.8.2 S6): an exchange push a final or held order did not take, or an
        # execution B1 refused as hostile (OM-T04); the OMS facade writes it ahead (system actor).
        "oms.reconcile_anomaly",
        # E29-T04 (#913, [LANE-26]; 24 Sec.8.3 rule 6): a create a restart resumed, which no lookup
        # found within the venue's 24 h history and which is older than the live re-send bound,
        # ended `rejected` unsent; the command port writes it ahead (system actor), the order its
        # object, its age and the bound in the detail.
        "oms.resend_refused",
        # E29-T05 (#848, 24 Sec.8.12, contract first): the lockout's paging stand-in until E39-T04,
        # an order or fill with no OMS intent, written ahead of its page (system actor, no freeze).
        "oms.no_intent_detected",
        # E29-T04 (#913, 24 Sec.15.5, 21 Sec.3.3.11 "Audit"): a stop request the OMS records for a
        # position, written ahead with its row (`sl.attached`; `tp.modified` for a take-profit
        # side), and a void of one (`sl.modified`, `tp.modified`). Keyed (`writer.KEYED_ACTIONS`):
        # the row names its record's id before the record lands.
        "sl.attached",
        "sl.modified",
        "tp.modified",
        # E28-T05 (#909, 24 Sec.15.5): a definition write, ahead of its commit, with its members
        # before and after (`api.trade_group_definition_writes`); no `.granted`: nothing grants one.
        "trade_group_definition.created",
        "trade_group_definition.updated",
        "trade_group_definition.deleted",
        "trade_group.submit",
        # #2635 (F-01; ADR-0040 Decision 1, proposed): a trade-group request refused whole because a
        # leg would exceed its bound profile's caps or risk budget, written ahead of the `403
        # risk_limit_breached` with every violated field (`accounts.override_comparator`).
        "trade_group.override_refused",
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
        # E40-X01: a create or update naming an account outside the caller's grants (403).
        "alert.scope_refused",
        # E40-T03: evaluator firings and auto-disarms (system actor, C-2.9).
        "alert.fired",
        "alert.disarmed",
        # E40-T04: the delivery inbox (ack, ack-all) and the desktop shell's report-back;
        # a foreign delivery id reuses `alert.denied`.
        "alert.delivery_acked",
        "alert.deliveries_acked",
        "alert.desktop_outcome",
        # E13-T03: indicator-preset writes, written ahead of the row (IR-19); a write aimed at a
        # built-in or another user's preset is `rbac.denied`. `.imported` is the bundle import.
        "indicator_preset.created",
        "indicator_preset.updated",
        "indicator_preset.deleted",
        "indicator_preset.imported",
        # E08-T09 (#4708): scanner-preset writes, written ahead of the row with a content hash,
        # never the filter (24 Sec.15.5); a write refused after its record gets a second one
        # with outcome `failure`. Another user's preset is `rbac.denied`.
        "scanner_preset.created",
        "scanner_preset.updated",
        "scanner_preset.deleted",
        # E08-T07 (#4706): watchlist writes, written ahead of the change to the row (C-2.9), with
        # `object_kind` `watchlist` and the list's id; the state carries the name, the symbol count
        # and the version, never the symbols (24 Sec.15.5).
        "watchlist.created",
        "watchlist.updated",
        "watchlist.deleted",
        "recorder.start",
        "recorder.stop",
        # #2188 (orchestrator ruling): `update_manual` changed a manual entry's streams or depth.
        "recorder.update",
        "recorder.compact",
        # E16-T10: public trade-archive import (write-ahead accept + outcome).
        "recorder.import",
        # E26-T01: replay session lifecycle (#624 decision: destroyed carries
        # reason idle_reclaim|max_lifetime|client, max_lifetime since G6 #2673;
        # error is the chart entering `error`).
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
        # E42-T05 BK-9 (SR-E42-11): a verification requested, then its outcome at
        # `stage: finished` (`admin/backups/verify.py`).
        "backup.verified",
        # E42-T05 BK-10 (SR-E42-11): a download link issued, or refused after its step-up grant
        # was spent (`admin/backups/downloads.py`); BK-11's fetch writes it at `stage: served`.
        "backup.downloaded",
        # E42-T05 BK-12 (SR-E42-11): a backup's artefact deleted, its row kept, or the delete
        # refused or failed after its step-up grant was spent (`admin/backups/deletion.py`).
        "backup.deleted",
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
        # #2266: a boot found unrevoked API key rows at a KEK version it did not load (error).
        "security.kek_rows_stranded",
        # #2266: a KEK re-wrap refused before it latched or moved a row (`rewrapKek`'s refusals).
        "security.kek_rotation_refused",
        # #889 S6a-2b (ADR-0039): the audit export signing key at boot, each record committed with
        # its change: the first key generated, a key re-wrapped at the rotation boot, and Q3's
        # retried destroy of a retired key's seed (`secrets/_export_custody.py`); and, at error,
        # a key that cannot be used, export alone unavailable (`secrets/service.py`).
        "security.audit_signing_key_generated",
        "security.audit_signing_key_rewrapped",
        "security.audit_signing_key_material_destroyed",
        "security.audit_signing_key_unavailable",
        # #889 S6b (ADR-0039 decisions 3 and 7): the export signer's write-ahead record, before
        # every signature, and the record that closes it when signing then fails
        # (`secrets/export_signer.py`).
        "security.audit_export_signed",
        "security.audit_export_sign_failed",
        # #889 S7 (ADR-0039 decision 5; 22 `rotateAuditSigningKey`): a rotation, committed with
        # its keys; one refused before anything rotated (but the `429`); and one that did not
        # commit (`secrets/export_rotator.py`).
        "security.audit_signing_key_rotated",
        "security.audit_signing_key_rotation_refused",
        "security.audit_signing_key_rotation_failed",
        # #2728 (E16 R-E3 "config audit"): the keyless-testnet test clock is on at boot
        # (system actor `system:test-clock`, `auth/testnet_clock.py`).
        "system.config.test_clock_enabled",
        # #2893 S8 (FX-R01): the dev-only account fixture transport is on and its boot guard
        # passed (system actor `system:account-fixture`, `candleviewer/account_fixture_wiring.py`).
        "system.config.account_fixture_enabled",
        # #3009 (ADR-0037): the journal-first audit lane's own records (actor `system:audit-lane`,
        # `audit/lane.py`): its frame 1, one per boot, and one per anomaly run the drain hands over.
        "audit.lane_started",
        "audit.lane_resumed",
        "audit.lane_anomaly",
    }
)

for _action in AUDIT_ACTIONS:
    if not _ACTION_FMT_RE.match(_action):  # pragma: no cover - defends the registry itself
        raise AuditError(f"registry action {_action!r} violates au_action_fmt")

#: `profile.save_refused`'s `reason` (E28-T02, #906; E28 threat model Sec.8.1), a closed set of the
#: refusals of the profile's risk policy (ruling of 2026-10-22: a malformed body is not audited):
#: the native-stop rule (`require_native_stop` set to `false`, SR-E28-08), `leverage` above the
#: profile's own `max_leverage_cap`, a trading-enabled profile with a loss cap left unbounded
#: (`cap_unbounded`: a cap removed rather than raised, PF-T02, though it arrives as a missing
#: member; ruling of 2026-10-22 07:10Z), and the exchange limits the
#: second validation pass refuses: leverage above an allowed symbol's maximum, a fixed size below
#: its minimum quantity or off its step, a notional cap below its minimum notional, and a symbol
#: the exchange does not list. A missing step-up is none (ruling B4): the path guard refuses it
#: before the handler runs and B16 audits it as `auth.step_up_required`. 24 Sec.15.5 lists them.
PROFILE_SAVE_REFUSED_REASONS: frozenset[str] = frozenset(
    {
        "native_stop_mandatory",
        "above_leverage_cap",
        "cap_unbounded",
        "max_leverage",
        "min_order_qty",
        "qty_step",
        "min_notional",
        "symbol_not_listed",
    }
)

LaneClass = Literal["reserved", "shared"]
_ANY = frozenset(AuditOutcome)

#: The journal-first audit lane's closed registry (ADR-0037 decision 3; the single source, C-16.5):
#: each admitted action, its class and the outcomes it may carry. The class follows the action,
#: never the caller. `audit.lane_anomaly` is no frame: the drain builds it (`audit/writer.py`).
LANE_ACTIONS: Mapping[str, tuple[LaneClass, frozenset[str]]] = MappingProxyType(
    {
        "auth.logout": ("reserved", _ANY),
        "auth.session_revoked": ("reserved", _ANY),
        "auth.refresh_reuse_detected": ("reserved", _ANY),
        # Q9 (decision 13): only a family's first containment intent is `reserved`; a replay
        # against a contained family is `shared`, so a flood of them never spends that share.
        "auth.refresh_reuse_replayed": ("shared", frozenset({AuditOutcome.DENIED})),
        # #3120: the backstop revocation's outcome (#3355 adds it to AUDIT_ACTIONS). The lane takes
        # the row first and the writer is its fallback; a row both refuse is counted lost (#3009).
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
