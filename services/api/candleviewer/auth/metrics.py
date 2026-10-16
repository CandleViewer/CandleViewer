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
auth_csrf_refused_total = Counter(
    "auth_csrf_refused_total",
    "State-changing requests refused by the SR-041/SR-042 CSRF guard, by reason.",
    # closed set: missing | mismatch | bad_mac | wrong_session | cross_origin (refusals)
    #             | audit_unavailable | audit_slow | audit_throttled (audit bookkeeping)
    ["reason"],
)
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
    "Permission-check denials decided by auth.scopes.enforce (the rbac.denied decisions).",
    # closed set: the generated `Permission` vocabulary, or `other` (see `normalise_permission`)
    ["permission"],
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
auth_revocation_latency_seconds = Histogram(
    "auth_revocation_latency_seconds",
    "Seconds from session revocation to its WebSocket connection being closed.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
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
    }
)


def export_auth_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the auth series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=AUTH_EXPORTED_NAMES, const_labels={"env": env})
