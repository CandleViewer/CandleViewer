"""Domain errors for the auth module (M18)."""

from __future__ import annotations


class AuthError(Exception):
    """Base exception for the M18 `auth` module."""


class InvalidCredentials(AuthError):
    """Unknown user, wrong password, or a not-yet-known combination.

    Deliberately uniform (E09-S01 acceptance criterion "Unknown user is
    indistinguishable from a wrong password" / C-2.12 enumeration
    resistance): callers must render exactly the same HTTP status and
    message for every case this is raised, never branching on which case
    produced it.
    """


class AccountDisabled(AuthError):
    """Password verified but `users.status = 'disabled'`.

    Only ever raised *after* a successful Argon2id verification (the
    ticket's documented, deliberate trade-off: the caller already proved
    knowledge of the secret, so revealing the disabled state here does not
    aid enumeration)."""


class AccountLocked(AuthError):
    """`users.locked_until` is in the future. Carries the remaining seconds
    so the API/UI can render a countdown without a second query."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"account locked for another {retry_after_s}s")
        self.retry_after_s = retry_after_s


class AuthServiceUnavailable(AuthError):
    """The auth module has not been started with a real repository."""


class MfaChallengeInvalid(AuthError):
    """The `mfa_token` does not correspond to an open, unexpired challenge —
    unknown token, already-satisfied challenge, or an expired one (ticket
    "expired-challenge (returns to SCR-001)"). Deliberately uniform: the
    router must never reveal *which* of these applied."""


class MfaChallengeLocked(AuthError):
    """Five failed attempts against one challenge (ticket "locked after 5
    tries" / `mfa_challenges.attempts CHECK BETWEEN 0 AND 10` with this
    module enforcing the tighter 5-try business rule)."""


class MfaCodeInvalid(AuthError):
    """A syntactically valid TOTP/recovery code that did not verify.

    Raised only when the surrounding challenge is still open (an already
    exhausted challenge raises `MfaChallengeLocked` instead) — the caller
    still owes the failure an `auth.mfa_failed` audit record with
    `reason=invalid`."""


class MfaCodeReused(AuthError):
    """A TOTP code whose `time_step` was already accepted for this method
    (ticket "Reused code is rejected" — replay protection)."""


class MfaEnrollmentNotFound(AuthError):
    """`method_id` does not exist, is not `pending`, or does not belong to
    the authenticated user."""


class MfaLastMethodProtected(AuthError):
    """`DELETE /auth/mfa/methods/{methodId}` on the last active method while
    `users.mfa_required` is set (ticket "Security notes": "the last
    remaining method cannot be deleted while `users.mfa_required` is
    set")."""


class MfaReauthRequired(AuthError):
    """`DELETE /auth/mfa/methods/{methodId}` without a valid
    `X-Reauth-Password` header (ticket "Security notes")."""


class RecoveryCodeInvalid(AuthError):
    """An unknown or already-used recovery code."""


class RecoveryCodesExhausted(AuthError):
    """All recovery codes for this user are consumed (ticket "Recovery
    codes exhausted": "no session is created")."""


class SessionNotFound(AuthError):
    """No `sessions` row matches the presented refresh token hash — unknown
    or already-purged token. Deliberately uniform with `SessionRevoked`
    from the caller's point of view (both map to a 401 refresh failure);
    kept distinct here only so `SessionService` callers can log/metric the
    two cases differently."""


class SessionRevoked(AuthError):
    """The presented session/refresh token maps to a `sessions` row that is
    already revoked (idle-locked sessions are NOT revoked - see
    `SessionIdleLocked` - only terminal states: logout, admin revoke,
    absolute expiry, or MFA lockout raise this)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"session revoked: {reason}")
        self.reason = reason


class SessionIdleLocked(AuthError):
    """The session's idle deadline has passed but its absolute lifetime has
    not — ticket "Order entry is refused while locked": the server refuses
    order-entry/refresh-like actions on this session id regardless of what
    the client believes, without tearing the session down."""


class UnlockPasswordInvalid(AuthError):
    """`unlock()` was called with a password that failed verification. Kept
    distinct from `SessionRevoked` (a wrong password does not, by itself,
    revoke or otherwise change the session) so callers can render a normal
    "wrong password" response instead of a session-death one. After
    `MAX_UNLOCK_ATTEMPTS` consecutive failures against the same session,
    `unlock()` revokes the session instead and raises `SessionRevoked`
    (ticket "becomes a full sign-in") — this error is only raised for
    attempts before that threshold."""


class RefreshReuseDetected(AuthError):
    """A refresh token that has already been rotated was presented again
    (ticket "Refresh-token reuse kills the family"). The entire rotation
    family has been revoked with `revoked_reason='rotation_reuse'`, and every
    id in `revoked_session_ids` published to the revocation sink (WS close
    4401, US-ONB-009, #2272), by the time this is raised; callers must emit
    `auth.refresh_reuse_detected` at severity `critical`."""

    def __init__(self, message: str, *, revoked_session_ids: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.revoked_session_ids = revoked_session_ids


class StepUpRequired(AuthError):
    """A dangerous action was attempted without a live server-side elevation
    for its action class (E09-S04). The HTTP edge renders 403
    step_up_required and audits the attempt."""

    def __init__(self, action_class: str) -> None:
        super().__init__(f"step-up required for action class {action_class!r}")
        self.action_class = action_class


class StepUpCodeInvalid(AuthError):
    """Step-up TOTP code wrong or replayed; failures_remaining strikes are
    left before the session is downgraded to read-only."""

    def __init__(self, failures_remaining: int) -> None:
        super().__init__("invalid step-up code")
        self.failures_remaining = failures_remaining


class SessionReadOnly(AuthError):
    """Session is in the 5-minute read-only downgrade after three failed
    step-up codes; every write route must refuse (E09-S04)."""

    def __init__(self, until: object = None) -> None:
        super().__init__("session is read-only after repeated step-up failures")
        self.until = until


class UnknownActionClass(AuthError):
    """Step-up requested for an action class outside the closed set."""


class StepUpChallengeRefused(AuthError):
    """`POST /auth/step-up` cannot answer the challenge (#2304): `rule` is
    `challenge_expired`, `challenge_mismatch` or `required` for `field`.
    Decided before any factor is checked, so no failure is counted and
    nothing is elevated."""

    def __init__(self, field: str, rule: str) -> None:
        super().__init__(f"step-up challenge refused: {field} {rule}")
        self.field = field
        self.rule = rule


class SelfResetRefused(AuthError):
    """The owner targeted their own TOTP reset. No step-up can cure it, so the
    HTTP edge answers a plain `403 forbidden`, never a challenge (#2304)."""


class InviteRejected(AuthError):
    """An invite token that cannot be used (E09-S05). `reason` is one of
    `unknown | expired | redeemed | revoked | enrollment_invalid` and is for
    audit/metrics only - the HTTP edge renders one uniform 404 for all of
    them so links cannot be probed."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"invite rejected: {reason}")
        self.reason = reason


class InviteConflict(AuthError):
    """`POST /users`: the email or username already belongs to a user."""


class InviteNotFound(AuthError):
    """Re-issue/revoke for a user with no (pending) invite."""


class PasswordPolicyViolation(AuthError):
    """Redemption password failed the SR-028 policy; `reason` is user-safe."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BreakGlassRefused(AuthError):
    """The offline break-glass Owner reset (E09-S11, SR-023) refused and
    changed zero rows. `reason` is a `BreakGlassRefusal` value from
    `candleviewer.auth.break_glass`; it names no secret."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"break-glass reset refused: {reason}")
        self.reason = reason
