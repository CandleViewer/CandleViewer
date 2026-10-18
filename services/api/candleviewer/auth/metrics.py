"""Prometheus metrics for session lifetime (E09-S03 "Observability") and the SR-125
security counters (`auth_login_failures_total`, `auth_lockouts_total`, `authz_denied_total`,
`auth_stepup_failures_total`).

Labels are closed sets (revocation `reason` is normalised by `normalise_reason`, the denied
`permission` by `normalise_permission`, the failed-login `method` is `LOGIN_FAILURE_METHODS`, the
lost outcome record's `action` by `normalise_outcome_action`) so cardinality stays bounded. Only
`AUTH_EXPORTED_NAMES` reaches the scraped registry; every other series here lands on the
process-default registry that Prometheus never reads.
"""

from __future__ import annotations

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import MfaMethodKind
from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)
from candleviewer.observability.metrics_catalogue import REVOCATION_CLOSE_BUCKETS

# Process-local and NOT in `AUTH_EXPORTED_NAMES` (#2319, accepted decision): it is +1 on mint and -1
# only on `revoke`/`revoke_all`, never on expiry, idle lock, rotation or a family revoke, and a
# process that revokes a session minted before it started drives it negative. The database is the
# truth for live sessions.
auth_sessions_active = Gauge(
    "auth_sessions_active", "Live (unrevoked) sessions minted by this process."
)
auth_session_revocations_total = Counter(
    "auth_session_revocations_total", "Sessions revoked, by reason.", ["reason"]
)
auth_refresh_total = Counter("auth_refresh_total", "Successful refresh-token rotations.")
auth_refresh_reuse_total = Counter(
    "auth_refresh_reuse_total", "Rotated refresh tokens presented again (family revoked)."
)
auth_idle_locks_total = Counter(
    "auth_idle_locks_total", "Requests refused because the session was idle-locked."
)
#: #2911 (SR-029): each is a live session of a disabled or deleted user that no disable revoked,
#: found by `require_active` and revoked there, so any increase is a breach signal. Counted once
#: per revoked row, by the call whose conditional revoke changed it (#3029): each one also moves
#: `auth_session_revocations_total{reason="user_disabled"}` by one, a series that counts a
#: disable's own revocations too, so the two are not the same number. No label: the log line names
#: the session. Scraped: in `AUTH_EXPORTED_NAMES`; the `AuthDisabledUserSessionRevoked` ticket
#: reads it.
auth_disabled_user_sessions_revoked_total = Counter(
    "auth_disabled_user_sessions_revoked_total",
    "Live sessions of a disabled or deleted user refused and revoked on use (SR-029).",
)
auth_step_up_total = Counter(
    "auth_step_up_total", "Successful step-up re-authentications.", ["action_class"]
)
auth_readonly_downgrades_total = Counter(
    "auth_readonly_downgrades_total", "Sessions downgraded to read-only after repeated failures."
)
#: `auth_csrf_refused_total{reason}` is a closed set in two halves (#2264). A refusal counts once
#: under why it was refused, and again under an audit reason when its `auth.csrf_refused`
#: record was not written normally; the refusal alert excludes the second half (pinned by a test).
CSRF_REFUSAL_REASONS: tuple[str, ...] = (
    "missing",
    "mismatch",
    "bad_mac",
    "wrong_session",
    "cross_origin",
)
CSRF_AUDIT_REASONS: tuple[str, ...] = (
    "audit_unavailable",  # the write failed: after the wait, or still running at shutdown
    "audit_slow",  # the request stopped waiting at the timeout; the write may still land
    "audit_throttled",  # over the per-session / per-IP budget: no write attempted, on purpose
    "audit_saturated",  # the in-flight cap is full of stuck writes: no write attempted
)
auth_csrf_refused_total = Counter(
    "auth_csrf_refused_total",
    "State-changing requests refused by the SR-041/SR-042 CSRF guard, by reason.",
    ["reason"],
)
# Bind every reason now: a series created at its first event gives `increase()` nothing to
# subtract, so the first refusal or audit failure after every restart would never alert.
for _csrf_reason in (*CSRF_REFUSAL_REASONS, *CSRF_AUDIT_REASONS):
    auth_csrf_refused_total.labels(reason=_csrf_reason)
auth_mfa_resets_total = Counter("auth_mfa_resets_total", "Owner TOTP resets performed.")
#: `auth_audit_outcome_lost_total{action}` (#2914, 04-security-program.md section 8.3 rule 2): an
#: outcome audit record that could not be written after the action was taken. The answer stands;
#: this count, the error log and the alerts tell that the trail has a gap. `action` is a closed set
#: (else `other`): a route that starts to write an outcome record adds its action here, and the
#: catalogue's `max_series` (this set plus `other`) with it.
AUDIT_OUTCOME_ACTIONS: tuple[str, ...] = (
    "auth.refresh_reuse_detected",  # the concurrent-refresh race (`api/sessions.py`)
    "auth.session_refreshed",  # a disabled user's refused refresh, reason `user_disabled` (#2911)
    "auth.session_revoked",  # one per session `POST /auth/logout` revoked
)
auth_audit_outcome_lost_total = Counter(
    "auth_audit_outcome_lost_total",
    "Outcome audit records that could not be written after the action was taken "
    "(04-security-program.md section 8.3 rule 2), by audit action.",
    ["action"],
)
# SR-125 (#2117), catalogued `live` and re-exported below. Each is incremented at the decision
# that makes it true; none carries a user, account, IP or free-form label.
auth_lockouts_total = Counter(
    "auth_lockouts_total",
    "Account lockouts applied by repeated wrong passwords (SR-016), from login or step-up.",
)
auth_stepup_failures_total = Counter(
    "auth_stepup_failures_total",
    "Failed step-up re-authentications (wrong password or code, or a locked account).",
)
# One per audited failed login (`api/auth.py`): `password` per `auth.login_failed` row of
# `POST /auth/login`, the requested MFA method per `auth.mfa_failed` row and per the
# `auth.login_failed` row of a user disabled since the password step (`POST /auth/mfa/verify`,
# #3054), `recovery_code` per `auth.recovery_codes_exhausted`. An attempt refused while the
# account is locked (`auth.account_locked`) and a success never count.
auth_login_failures_total = Counter(
    "auth_login_failures_total",
    "Failed logins by the factor that failed (password, totp, webauthn, recovery_code).",
    # closed set: `LOGIN_FAILURE_METHODS`
    ["method"],
)
authz_denied_total = Counter(
    "authz_denied_total",
    "Permission-check denials decided by auth.scopes.enforce (audit rbac.denied) or by the "
    "admin-area guard, admin.http (audit admin.area_entered, outcome denied).",
    # closed set: the generated `Permission` vocabulary, or `other` (see `normalise_permission`)
    ["permission"],
)
auth_totp_clock_skew_total = Counter(
    "auth_totp_clock_skew_total",
    "Rejected TOTP codes valid for a step beyond the accepted window, by authenticator side.",
    # closed set: authenticator_behind | authenticator_ahead
    ["kind"],
)
auth_session_fixation_attempts_total = Counter(
    "auth_session_fixation_attempts_total",
    "Session credentials never issued here, another user's, or rotated away, presented"
    " (U6/SR-013), by reason.",
    # closed set: unknown_token | foreign_session | rotated (attempts; `rotated` is a
    #             rotated-away `cv_refresh` presented outside `/auth/refresh`, #2300)
    #             | audit_throttled | audit_slow | audit_unavailable | audit_failed (bookkeeping)
    ["reason"],
)
auth_session_revoke_denied_total = Counter(
    "auth_session_revoke_denied_total",
    "DELETE /me/sessions/{id} for an id that is not one of the caller's live sessions "
    "(IDOR probe, or a stale row for the caller's own ended session).",
)
#: SR-029, E09-S03 (#3415): the one revoke-to-close latency, written by the WS `RevocationHub`
#: (`ws` may import `auth`, never the reverse): one observation per revocation that closed a
#: socket, from its `revoke` to the last of that session's sockets closed or given up, on the
#: hub's clock. No label. Scraped: in `AUTH_EXPORTED_NAMES`; `AuthRevocationLatencyHigh` reads it.
auth_revocation_latency_seconds = Histogram(
    "auth_revocation_latency_seconds",
    "Seconds from a session revocation reaching the WS hub to the last of its sockets closed.",
    buckets=REVOCATION_CLOSE_BUCKETS,
)
# SR-022 (#2496): one per accepted recovery code, counted before its `auth.recovery_code_used`
# audit write, so it can exceed those rows when that write fails or audit is not wired.
# `AuthRecoveryCodeUsed` pages the Owner on any increase. No label: the audit row names the user.
auth_recovery_codes_used_total = Counter(
    "auth_recovery_codes_used_total", "Recovery codes accepted at /auth/mfa/recovery (SR-022)."
)
# SR-023 (#2496): how many break-glass resets are unresolved (the critical `system_events` rows
# `auth`/`break_glass_used`); `BreakGlassNotice` sets it from each successful read and
# `AuthBreakGlassUsed` pages while it is 1 or more. A count read from the database, not a counter
# of the records the boot fold-in moves (a use folds nothing in, and the fold-in runs before the
# first scrape): see the alert's rule. A count and not a 0/1 flag, so a second reset during a
# silence of the page reads as 2 in the runbook's first diagnostic command.
auth_break_glass_unresolved_events = Gauge(
    "auth_break_glass_unresolved_events",
    "Break-glass resets (system events auth/break_glass_used) not yet resolved.",
)
# SR-023 (#2496 review): how many break-glass CLI runs `audit_log` holds a record of, counted as
# the rows of action `auth.break_glass_attempt`, the write-ahead first record of every run
# whatever its outcome. It only ever rises. `BreakGlassNotice` sets it from each successful read
# and `AuthBreakGlassAttempted` pages when it has risen since Prometheus last saw it. A run that
# changed nothing (refused, cut short) leaves audit rows and no `break_glass_used` event, so
# `AuthBreakGlassUsed` cannot see it; a completed reset raises this count too.
auth_break_glass_attempts = Gauge(
    "auth_break_glass_attempts",
    "Break-glass CLI runs on record in audit_log (auth.break_glass_attempt rows); only rises.",
)
# SR-125 (#2496 review, detection health): one per failed read of the break-glass state (a
# timeout, a database error, a revoked grant), counted per statement by `BreakGlassNotice`. A
# failed read keeps the last value of the gauges above, which is 0 in a fresh process, and their
# `absent()` guards cannot see it (the series exist), so without this counter a reader that cannot
# read leaves both pages silent and nothing says so. `AuthBreakGlassStateReadFailing` is a ticket
# on it. No label: the log line names the statement and the error class.
auth_break_glass_state_read_failures_total = Counter(
    "auth_break_glass_state_read_failures_total",
    "Failed reads of the break-glass state from Postgres (the gauges keep their last value).",
)

_KNOWN_REASONS = frozenset(
    {
        "logout",
        "logout_all",
        "rotated",
        "rotation_reuse",
        "expired",
        "idle",
        "admin",
        "user_revoked",
        "locked",
        "timeout",
        "unlock_attempts_exceeded",
        "user_disabled",
    }
)


def normalise_reason(reason: str | None) -> str:
    """Clamp a free-form revocation reason to the closed label set."""
    return reason if reason in _KNOWN_REASONS else "other"


_KNOWN_PERMISSIONS = frozenset(permission.value for permission in Permission)


def normalise_permission(permission: str) -> str:
    """Clamp a permission code to the generated vocabulary (else `other`), so the
    `authz_denied_total` label set stays closed whatever a caller passes."""
    return str(permission) if permission in _KNOWN_PERMISSIONS else "other"


# Bind every value now: the series then exist from process start, so the `absent()` guard
# (`ExpectedMetricMissingAuthzDeniedTotal`) cannot fire on a healthy system that has simply
# not denied anything yet, and the first denial is a visible 0 -> 1 `increase()`.
for _permission in (*sorted(_KNOWN_PERMISSIONS), "other"):
    authz_denied_total.labels(permission=_permission)

#: Closed `auth_login_failures_total{method}` set: the password step, then the MFA factor that
#: failed (`MfaMethodKind`: `totp`, `webauthn`, `recovery_code`).
LOGIN_FAILURE_METHODS: tuple[str, ...] = ("password", *(kind.value for kind in MfaMethodKind))
# Bound every method now: `ExpectedMetricMissingAuthLoginFailuresTotal` is `absent()` on this name.
for _method in LOGIN_FAILURE_METHODS:
    auth_login_failures_total.labels(method=_method)

_KNOWN_OUTCOME_ACTIONS = frozenset(AUDIT_OUTCOME_ACTIONS)


def normalise_outcome_action(action: str) -> str:
    """Clamp an audit action to `AUDIT_OUTCOME_ACTIONS` (else `other`), so the
    `auth_audit_outcome_lost_total` label set stays closed whatever a caller passes."""
    return action if action in _KNOWN_OUTCOME_ACTIONS else "other"


# Bind every value now: a series created at its first event gives `increase()` nothing to
# subtract, so the first loss after a restart would never fire the ticket or the page.
for _outcome_action in (*AUDIT_OUTCOME_ACTIONS, "other"):
    auth_audit_outcome_lost_total.labels(action=_outcome_action)


users_invites_created_total = Counter(
    "users_invites_created_total", "Invites minted (incl. re-issues), by role.", ["role"]
)
users_invites_redeemed_total = Counter(
    "users_invites_redeemed_total", "Invites fully redeemed (account activated)."
)
users_invites_rejected_total = Counter(
    "users_invites_rejected_total", "Invite uses refused, by reason.", ["reason"]
)
users_invites_pending = Gauge(
    "users_invites_pending", "Open (unconsumed, unrevoked) invites seen by this process."
)


#: Series re-exported onto the scraped app registry (#2090): module-level counters
#: land on the library default registry, which Prometheus never scrapes.
AUTH_EXPORTED_NAMES: frozenset[str] = frozenset(
    {
        "auth_audit_outcome_lost_total",
        "auth_csrf_refused_total",
        "auth_session_fixation_attempts_total",
        "auth_lockouts_total",
        "auth_stepup_failures_total",
        "authz_denied_total",
        "auth_totp_clock_skew_total",
        "auth_recovery_codes_used_total",
        # E09-X02 observability gaps (#2319)
        "auth_login_failures_total",
        "auth_refresh_reuse_total",
        "auth_session_revocations_total",
        "auth_readonly_downgrades_total",
        "users_invites_rejected_total",
        "auth_disabled_user_sessions_revoked_total",
        "auth_session_revoke_denied_total",
        # SR-023 break-glass detections (#2496)
        "auth_break_glass_unresolved_events",
        "auth_break_glass_attempts",
        "auth_break_glass_state_read_failures_total",
        # SR-029 revoke-to-close latency, observed by the WS revocation hub (#3415)
        "auth_revocation_latency_seconds",
    }
)


def export_auth_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the auth series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=AUTH_EXPORTED_NAMES, const_labels={"env": env})
