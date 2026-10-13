"""Prometheus metrics for session lifetime (E09-S03 "Observability").

Labels are closed sets (revocation `reason` is normalised by
`normalise_reason`) so cardinality stays bounded.
"""

from __future__ import annotations

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
AUTH_EXPORTED_NAMES: frozenset[str] = frozenset({"auth_csrf_refused_total"})


def export_auth_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the auth series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=AUTH_EXPORTED_NAMES, const_labels={"env": env})
