"""Prometheus metrics for session lifetime (E09-S03 "Observability") and the SR-125
security counters (`auth_lockouts_total`, `authz_denied_total`, `auth_stepup_failures_total`).

Labels are closed sets (revocation `reason` is normalised by `normalise_reason`, the denied
`permission` by `normalise_permission`) so cardinality stays bounded.
"""

from __future__ import annotations

from candleviewer.auth.generated_permissions import Permission
from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)

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
auth_step_up_total = Counter(
    "auth_step_up_total", "Successful step-up re-authentications.", ["action_class"]
)
auth_step_up_failures_total = Counter(
    "auth_step_up_failures_total", "Failed step-up code verifications.", ["action_class"]
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
    "Session credentials never issued here, or another user's, presented (U6/SR-013), by reason.",
    # closed set: unknown_token | foreign_session (attempts)
    #             | audit_throttled | audit_slow | audit_unavailable | audit_failed (bookkeeping)
    ["reason"],
)
auth_revocation_latency_seconds = Histogram(
    "auth_revocation_latency_seconds",
    "Seconds from session revocation to its WebSocket connection being closed.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
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
        "auth_csrf_refused_total",
        "auth_session_fixation_attempts_total",
        "auth_lockouts_total",
        "auth_stepup_failures_total",
        "authz_denied_total",
        "auth_totp_clock_skew_total",
        "auth_recovery_codes_used_total",
        "auth_break_glass_unresolved_events",
    }
)


def export_auth_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the auth series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=AUTH_EXPORTED_NAMES, const_labels={"env": env})
