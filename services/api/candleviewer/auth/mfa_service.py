"""`MfaService` — the M18 core for E09-S02 (US-ONB-002/003): TOTP
verification, enrolment, and recovery-code lifecycle.

Every Gherkin scenario in the ticket maps to a method here:

- `verify()` — "Valid code creates a session" / "Reused code is rejected" /
  "Clock drift within one step is tolerated".
- `enroll()` + `confirm_enrollment()` — "First-login enrolment".
- `check_recovery()` + `complete_recovery()` — "Recovery code use forces
  re-enrolment" / "Recovery codes exhausted" (#2344: split so the router
  audits between them).
- `regenerate_recovery_codes()` — `POST /auth/mfa/recovery`'s sibling
  regeneration path from SCR-112.

As with `LoginService`, audit emission is the router's job (`auth` may not
import `audit` — `forbidden-M18` import-linter contract); this module
raises typed errors and returns typed results only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import (
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    MfaEnrollmentNotFound,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
)
from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.auth.models import (
    MfaChallengeRecord,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    MfaMethodRecord,
    MfaRecoveryCheck,
    MfaVerifiedResult,
    MfaVerifyRequest,
    RecoveryCodesRegenerated,
)
from candleviewer.auth.recovery_codes import generate_recovery_codes, hash_recovery_code
from candleviewer.auth.totp import generate_secret, otpauth_uri, secret_to_base32, verify_code
from candleviewer.auth.totp_skew import TotpSkewReporter

#: Ticket "Technical notes": "attempts capped at 5" (tighter than the
#: schema's own `mfa_ch_attempts CHECK BETWEEN 0 AND 10`, which is a wider
#: sanity bound the migration shares with `step_up`/`enroll` purposes).
CHALLENGE_ATTEMPT_CAP = 5

#: Ticket "Technical notes": "expires_at 5 min".
CHALLENGE_TTL = timedelta(minutes=5)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    """Never persist a bearer `mfa_token` in the clear (mirrors
    `sessions.refresh_token_hash`'s own pattern, and `LoginService`'s
    `MfaChallengeResult.mfa_token` docstring)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class MfaService:
    def __init__(
        self,
        repository: MfaRepository,
        encryptor: TotpEncryptor,
        *,
        recovery_code_key: bytes,
        clock: Clock = _utc_now,
        issuer: str = "CandleViewer",
        skew_reporter: TotpSkewReporter | None = None,
    ) -> None:
        self._repository = repository
        self._encryptor = encryptor
        # Server-side HMAC key for recovery-code hashes (PR #1618 security
        # review, blocking 1); never logged or returned.
        self._recovery_code_key = recovery_code_key
        self._clock = clock
        self._issuer = issuer
        self._skew_reporter = skew_reporter or TotpSkewReporter()

    # -- verification (login step 2) --------------------------------------

    async def verify(self, request: MfaVerifyRequest) -> MfaVerifiedResult:
        """`POST /auth/mfa/verify`. The challenge row already carries
        `user_id`, so no account name is needed here.

        Raises `MfaChallengeInvalid`, `MfaChallengeLocked`, `MfaCodeInvalid`,
        or `MfaCodeReused`."""
        if request.method is not MfaMethodKind.TOTP:
            # WebAuthn is out of scope (ticket "Out of scope"); recovery
            # codes go through `check_recovery()` / `/auth/mfa/recovery` instead
            # (`MfaVerifyRequest.method` is `totp | webauthn | recovery_code`
            # per the OpenAPI enum, but this service only implements the
            # `totp` arm of it).
            raise MfaCodeInvalid("only method=totp is implemented by this endpoint")

        challenge = await self._open_challenge_or_raise(request.mfa_token, purpose="login")
        methods = await self._repository.find_active_totp_methods(str(challenge.user_id))
        if not methods:
            raise MfaCodeInvalid("no active TOTP method enrolled")

        now = self._clock()
        accepted_step: int | None = None
        matched_method_id: str | None = None
        refused: list[tuple[bytes, int | None]] = []
        for method in methods:
            if method.secret_enc is None:
                continue  # mfa_totp_shape CHECK should prevent this; defend anyway
            seed = self._encryptor.decrypt(method.secret_enc)
            refused.append((seed, method.last_accepted_time_step))
            step = verify_code(seed, request.code, unix_time=now.timestamp())
            if step is not None:
                accepted_step = step
                matched_method_id = str(method.id)
                break

        if accepted_step is None or matched_method_id is None:
            # #2146: holds a report for a skewed clock. It awaits nothing, so it cannot delay or
            # cancel the attempt count, and it runs first so the locking attempt reports too.
            self._skew_reporter.report_rejection(refused, request.code, unix_time=now.timestamp())
            await self._record_failed_attempt(challenge)
            raise MfaCodeInvalid("invalid TOTP code")

        replay_ok = await self._repository.record_time_step(
            matched_method_id, time_step=accepted_step
        )
        if not replay_ok:
            await self._record_failed_attempt(challenge)
            raise MfaCodeReused("this code has already been used")

        await self._repository.touch_method_used(matched_method_id, now=now)
        satisfied = await self._repository.satisfy_challenge(str(challenge.id), now=now)
        if not satisfied:
            # PR #1618 review finding 2 (high): another request already
            # satisfied this same challenge (e.g. raced by a concurrent
            # verify/recovery call) — the TOTP time-step replay guard above
            # only protects the *code*, not the *challenge* row, so this
            # second check is what actually stops one challenge minting
            # two sessions.
            raise MfaChallengeInvalid("challenge already satisfied")
        return MfaVerifiedResult(user_id=challenge.user_id)

    async def _open_challenge_or_raise(self, mfa_token: str, *, purpose: str) -> MfaChallengeRecord:
        token_hash = _hash_token(mfa_token)
        challenge = await self._repository.find_open_challenge_by_token_hash(token_hash)
        if challenge is None or challenge.purpose != purpose:
            raise MfaChallengeInvalid("no open challenge for this token")
        if challenge.expires_at <= self._clock():
            raise MfaChallengeInvalid("challenge expired")
        if challenge.attempts >= CHALLENGE_ATTEMPT_CAP:
            raise MfaChallengeLocked("too many failed attempts")
        return challenge

    async def _record_failed_attempt(self, challenge: MfaChallengeRecord) -> None:
        new_count = await self._repository.record_challenge_attempt(str(challenge.id))
        if new_count >= CHALLENGE_ATTEMPT_CAP:
            raise MfaChallengeLocked("too many failed attempts")

    # -- enrolment ---------------------------------------------------------

    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult:
        """`POST /auth/mfa/enroll`. WebAuthn is out of scope (ticket "Out of
        scope") — only `method=totp` is implemented."""
        if request.method is not MfaMethodKind.TOTP:
            raise MfaCodeInvalid("only method=totp enrolment is implemented")

        seed = generate_secret()
        secret_enc = self._encryptor.encrypt(seed)
        # #2295: each enrolment supersedes the user's earlier pending methods, so only
        # the latest can be confirmed.
        await self._repository.supersede_pending_methods(user_id, now=self._clock())
        method = await self._repository.create_pending_method(
            user_id,
            secret_enc=secret_enc,
            secret_key_ref=self._encryptor.key_ref,
            label=request.label,
        )
        uri = otpauth_uri(secret=seed, account_name=account_name, issuer=self._issuer)
        return MfaEnrollResult(
            method_id=method.id,
            method=MfaMethodKind.TOTP,
            otpauth_uri=uri,
            secret_base32=secret_to_base32(seed),
        )

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[MfaMethodKind, tuple[str, ...]]:
        """`check_enrollment` then `complete_enrollment`, for a caller with no audit
        record to write in between (the invite redemption). Returns `(method_kind,
        recovery_codes)`: the 10 new single-use codes (ticket "First-login enrolment":
        "TOTP is enabled and 10 single-use recovery codes are displayed once").

        Raises `MfaEnrollmentNotFound` or `MfaCodeInvalid`."""
        step = await self.check_enrollment(user_id, method_id=method_id, code=code)
        method, recovery_codes = await self.complete_enrollment(
            user_id, method_id=method_id, time_step=step
        )
        return method.kind, recovery_codes

    async def check_enrollment(self, user_id: str, *, method_id: str, code: str) -> int:
        """The read-only half of a confirmation (#2295): the time step *code* proves for
        the user's confirmable method (`MfaRepository.find_pending_method`). Nothing
        changes, so `POST /auth/mfa/enroll/confirm` writes its audit records between
        this and `complete_enrollment` (C-2.9).

        Raises `MfaEnrollmentNotFound` or `MfaCodeInvalid`."""
        method = await self._repository.find_pending_method(method_id, user_id)
        if method is None:
            raise MfaEnrollmentNotFound("no pending enrolment for this method_id")
        if method.secret_enc is None:  # mfa_totp_shape CHECK should prevent this
            raise MfaEnrollmentNotFound("pending method has no TOTP secret")

        seed = self._encryptor.decrypt(method.secret_enc)
        now = self._clock()
        accepted_step = verify_code(seed, code, unix_time=now.timestamp())
        if accepted_step is None:
            refused = [(seed, method.last_accepted_time_step)]
            self._skew_reporter.report_rejection(refused, code, unix_time=now.timestamp())
            raise MfaCodeInvalid("invalid TOTP code")
        return accepted_step

    async def complete_enrollment(
        self, user_id: str, *, method_id: str, time_step: int
    ) -> tuple[MfaMethodRecord, tuple[str, ...]]:
        """The mutating half (#2295, contract "Completion"): one repository transaction
        confirms the method at *time_step*, revokes every other TOTP method of the user
        and replaces the recovery codes with 10 new ones, returned here exactly once.

        Raises `MfaEnrollmentNotFound`, with nothing changed, when the method stopped
        being confirmable meanwhile (a concurrent confirm or enrolment won)."""
        plaintext_codes = generate_recovery_codes()
        hashes = tuple(hash_recovery_code(c, key=self._recovery_code_key) for c in plaintext_codes)
        confirmed = await self._repository.complete_enrollment(
            user_id, method_id=method_id, time_step=time_step, now=self._clock(), code_hashes=hashes
        )
        if confirmed is None:
            raise MfaEnrollmentNotFound("the pending method is no longer confirmable")
        return confirmed, tuple(plaintext_codes)

    async def _issue_recovery_codes(self, user_id: str) -> tuple[str, ...]:
        plaintext_codes = generate_recovery_codes()
        hashes = tuple(hash_recovery_code(c, key=self._recovery_code_key) for c in plaintext_codes)
        await self._repository.replace_recovery_codes(user_id, code_hashes=hashes)
        return tuple(plaintext_codes)

    # -- recovery ------------------------------------------------------------

    async def check_recovery(self, mfa_token: str, recovery_code: str) -> MfaRecoveryCheck:
        """The read-only half of `POST /auth/mfa/recovery` (#2344): the open login challenge
        of *mfa_token* and the unused recovery code of its user that *recovery_code* matches.
        Only a refusal changes anything: it counts toward the challenge's attempt cap, the
        login lockout's 5, so wrong codes are throttled and each five cost a password sign-in.
        The router writes its audit records between this and `complete_recovery` (C-2.9).

        Raises `MfaChallengeInvalid`, `MfaChallengeLocked`, `RecoveryCodeInvalid`, or
        `RecoveryCodesExhausted`.

        Constant-time against the hashed set (ticket "Technical notes":
        "constant-time against the hashed set") is delivered by hashing the
        candidate once and doing an equality-indexed lookup — the DB index
        lookup itself is not a timing side-channel on the *code value*
        because it operates on the keyed HMAC-SHA256 digest, not the code."""
        challenge = await self._open_challenge_or_raise(mfa_token, purpose="login")
        if await self._repository.count_unused_recovery_codes(str(challenge.user_id)) == 0:
            # Ticket "Recovery codes exhausted": "I am told to contact the
            # owner and no session is created" — distinct from a merely
            # wrong/reused code so the router can render the
            # contact-the-owner message (US-ONB-010 path) rather than the
            # generic invalid-code message. PR #1618 review finding 4: this
            # still counts toward the challenge's attempt cap (same as a
            # wrong code) so an attacker cannot probe "is this account's
            # recovery pool exhausted" for free, outside the 5-attempt/
            # `MfaChallengeLocked` budget every other guess is bound by.
            await self._record_failed_attempt(challenge)
            raise RecoveryCodesExhausted("all recovery codes have been used")

        code_hash = hash_recovery_code(recovery_code, key=self._recovery_code_key)
        code_id = await self._repository.find_unused_recovery_code(
            str(challenge.user_id), code_hash=code_hash
        )
        if code_id is None:
            await self._record_failed_attempt(challenge)
            raise RecoveryCodeInvalid("invalid or already-used recovery code")
        return MfaRecoveryCheck(
            user_id=challenge.user_id, challenge_id=challenge.id, code_id=code_id
        )

    async def complete_recovery(self, check: MfaRecoveryCheck) -> None:
        """The mutating half (#2344, contract `authMfaRecovery`): one repository transaction
        spends the code, satisfies the challenge and revokes every MFA method of the user, so
        the sign-in forces TOTP re-enrolment however many codes remain (#2296) and no old
        method can be confirmed again.

        Raises `RecoveryCodeInvalid`, with nothing changed, when a concurrent request spent
        the code or satisfied the challenge first (PR #1618 review finding 2); like a replay,
        it counts as a failed attempt."""
        challenge_id = str(check.challenge_id)
        if not await self._repository.complete_recovery(
            str(check.user_id), challenge_id=challenge_id, code_id=check.code_id, now=self._clock()
        ):
            await self._repository.record_challenge_attempt(challenge_id)
            raise RecoveryCodeInvalid("invalid or already-used recovery code")

    async def regenerate_recovery_codes(self, user_id: str) -> RecoveryCodesRegenerated:
        """`POST /auth/mfa/recovery`'s SCR-112 regeneration sibling (ticket
        "Scope / Deliverables": "regenerates codes, hard-deleting unused
        ones")."""
        codes = await self._issue_recovery_codes(user_id)
        return RecoveryCodesRegenerated(recovery_codes=codes)
