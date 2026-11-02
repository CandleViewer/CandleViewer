"""`LoginService` — the M18 credential-check core for E09-S01 (US-ONB-001).

`login()` implements every Gherkin scenario in the ticket:

- successful credentials on an MFA-enrolled user -> `MfaChallengeResult`
  (never a session; E09-S02 completes the second leg);
- successful credentials on a user who must enrol TOTP first ->
  `EnrolmentOnlyLogin` (#2295; the router mints the enrolment-only session);
- wrong password / unknown identifier -> `InvalidCredentials`, same message,
  and the same steps by construction: an unknown identifier is checked as a
  placeholder record (`_ABSENT_USER`, the nil UUID and the dummy hash) through
  the one lock check, verify call and failure block a wrong password takes;
- disabled account -> `AccountDisabled`, only ever raised *after* a correct password;
- five consecutive failures -> `AccountLocked` for 15 minutes, persisted across restarts; each
  attempt is counted, and the lock applied, before its password is verified, and a correct
  password in flight when the lock landed is refused (#2802);
- a user without `mfa_required` (C-12.2 forbids it) -> `MfaNotRequired`, after the password;
- a per-IP throttle independent of the per-account one (ticket "Scope /
  Deliverables": "one attacker cannot lock every account");
- every failed sign-in (each of the four errors above) returns no sooner than
  `LOGIN_FAILURE_FLOOR` after the attempt started (#4648), held by the `FailureHold` the second
  factor and step-up share (#4664), and the router answers each the same (SR-014, #4961); a
  minimum time below the setting's lowest value is refused at construction;
- sign-in verification runs for at most `LOGIN_VERIFY_CONCURRENCY` attempts at a time; an
  attempt beyond that is refused at once with `SignInBusy` and a retry-after (#4663).

Audit emissions (`auth.login`/`auth.login_failed`) are the caller's
responsibility here: `LoginService` raises typed errors and returns typed
results, and the router (`candleviewer.api`, which *is* allowed to import
`candleviewer.audit`) emits the audit record with the HTTP-layer context
(source IP, request id) this module does not have. This keeps M18's own
`.importlinter` contract (`forbidden-M18` — `auth` may not import `audit`)
intact.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from candleviewer.auth.errors import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    MfaNotRequired,
    SignInBusy,
)
from candleviewer.auth.failure_hold import FAILURE_MINIMUM, FailureHold, MonotonicClock, Sleep
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.metrics import auth_lockouts_total, auth_login_verify_refused_total
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, UserRecord, UserStatus
from candleviewer.auth.repository import UserRepository
from candleviewer.auth.throttle import PerIpLoginThrottle, VerifyAdmission
from candleviewer.settings import AUTH_LOGIN_VERIFY_CONCURRENCY

if TYPE_CHECKING:
    from candleviewer.auth.mfa_repository import MfaRepository

#: Ticket "Scope / Deliverables": "5 failures -> 15 min lockout".
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=15)

#: E09-S02 "Technical notes": "expires_at 5 min" — the `mfa_challenges` row
#: this service persists (when an `MfaRepository` is injected) so
#: `MfaService.verify()`/`check_recovery()` can look the opaque `mfa_token` up.
MFA_CHALLENGE_TTL = timedelta(minutes=5)

#: #4648: a failed sign-in returns no sooner than this after the attempt started. It is set
#: well above the time a normal failure takes, so every failure normally waits out the same
#: deadline; a failure that is already slower is never held longer, and is counted
#: (`auth_login_failure_floor_missed_total`). A successful sign-in is never held. The
#: default only: production passes `CV_AUTH_LOGIN_FAILURE_FLOOR_MS`, whose default this is.
LOGIN_FAILURE_FLOOR = FAILURE_MINIMUM

#: #4663: sign-in verification runs for at most this many attempts at a time. The default only:
#: production passes `CV_AUTH_LOGIN_VERIFY_CONCURRENCY`, whose default this is.
LOGIN_VERIFY_CONCURRENCY = AUTH_LOGIN_VERIFY_CONCURRENCY
#: #4663: the retry-after of an attempt refused because verification was at capacity. A sign-in
#: verification normally completes well within it, so a place has usually freed by then.
LOGIN_BUSY_RETRY_AFTER_S = 1

Clock = Callable[[], datetime]

#: The id of the placeholder record below: the nil UUID, never a real user (user ids are
#: server-generated uuid4), so `UserRepository.reserve_login_attempt` for it changes no row.
ABSENT_USER_ID = uuid.UUID(int=0)

#: What an unknown identifier is checked as, so both failure paths perform the same steps.
#: It can never sign in: `login` fails an unknown identifier whatever its verify returns.
_ABSENT_USER = UserRecord(
    id=ABSENT_USER_ID,
    username="",
    email="",
    password_hash=DUMMY_PASSWORD_HASH,
    password_algo_params=dict(DEFAULT_ARGON2_PARAMS),
    status=UserStatus.ACTIVE,
    mfa_required=True,
    failed_login_count=0,
    locked_until=None,
)


class EnrolmentOnlyLogin(BaseModel):
    """#2295 (Q6): the password of a user with `mfa_required` and no confirmed MFA method
    verified. No challenge is issued; the router mints an enrolment-only session
    (`22-api-openapi.yaml` "Enrolment-only session")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: uuid.UUID


def _hash_mfa_token(token: str) -> str:
    """Mirrors `mfa_service._hash_token` exactly — both sides of the two-
    legged login must hash the same way for `find_open_challenge_by_token_
    hash` to find what this service wrote."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LoginService:
    def __init__(
        self,
        repository: UserRepository,
        hasher: Hasher,
        *,
        per_ip_throttle: PerIpLoginThrottle | None = None,
        clock: Clock = _utc_now,
        mfa_token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        mfa_repository: MfaRepository | None = None,
        failure_floor: timedelta = LOGIN_FAILURE_FLOOR,
        monotonic: MonotonicClock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        verify_concurrency: int = LOGIN_VERIFY_CONCURRENCY,
        admission: VerifyAdmission | None = None,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._per_ip_throttle = per_ip_throttle or PerIpLoginThrottle()
        self._clock = clock
        self._mfa_token_factory = mfa_token_factory
        self._mfa_repository = mfa_repository
        #: #4664: refuses a minimum time below the setting's lowest value (ValueError).
        self._failure_hold = FailureHold(failure_floor, monotonic=monotonic, sleep=sleep)
        #: #4663: the bound on sign-in verifications in flight; `admission` is for tests.
        self._admission = admission or VerifyAdmission(verify_concurrency)

    async def login(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin:
        """Verify credentials and return the MFA challenge for step 2, or, for a user
        with `mfa_required` and no confirmed method, `EnrolmentOnlyLogin` (#2295, Q6).

        Raises `InvalidCredentials`, `AccountDisabled`, `AccountLocked` or `MfaNotRequired`
        (a user without `mfa_required`, see the note at that branch), all before either
        outcome; the router gives each of them the same answer (SR-014, #4961).

        #4648: each of those four refusals returns no sooner than the failure floor after
        the attempt started (`FailureHold.hold`); a successful outcome is never held.

        #4663: raises `SignInBusy` at once, before the identifier is looked up or any password
        is checked, when verification is already running for as many attempts as it admits.
        That refusal is not held to the failure floor: it is answered as soon as it is decided.
        """
        started = self._failure_hold.start()
        try:
            return await self._check_credentials(request, source_ip=source_ip)
        except (InvalidCredentials, AccountLocked, AccountDisabled, MfaNotRequired):
            # Every failure write has already happened inside the check; only the response
            # waits. A cancellation during the wait propagates (nothing here catches it).
            await self._failure_hold.hold(started)
            raise

    async def _check_credentials(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin:
        # #2802: the address reserves the attempt before any password is checked, so a burst
        # from one address has at most its budget checked. A refusal is indistinguishable from
        # a wrong password to the caller: same exception type *and* same message as every other
        # `InvalidCredentials` raise here, so the response never leaks which reason applied.
        reservation = self._per_ip_throttle.try_reserve(source_ip)
        if reservation is None:
            raise InvalidCredentials("Username or password is incorrect")

        # #4663: take a verification place without waiting, or refuse at once (not a failed
        # attempt, so the address reservation is given back). The place is given back on every
        # way out of the check, a cancellation included.
        if not self._admission.try_enter():
            self._per_ip_throttle.release(source_ip, reservation)
            auth_login_verify_refused_total.inc()
            raise SignInBusy(LOGIN_BUSY_RETRY_AFTER_S)
        try:
            result = await self._verify_admitted(request, source_ip=source_ip)
        finally:
            self._admission.leave()
        # Every refusal keeps the address reservation as one failure from this address; a
        # sign-in that succeeded gives it back.
        self._per_ip_throttle.release(source_ip, reservation)
        return result

    async def _verify_admitted(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin:
        found = await self._repository.find_by_identifier(request.identifier)
        # One answer for every identifier: an unknown one (or, defensively, a record
        # carrying the placeholder's id) continues as `_ABSENT_USER` through the same
        # steps as a wrong password, and always fails.
        known = found is not None and found.id != ABSENT_USER_ID
        user = found if found is not None and known else _ABSENT_USER

        # #2802: the account reserves the attempt (counted, and locked at the threshold) before
        # the password is verified; only an attempt holding a reservation is verified against
        # the account's hash. The placeholder's id has no row and holds none, yet takes the same
        # steps and always fails below.
        slot = await self._repository.reserve_login_attempt(
            str(user.id),
            lockout_threshold=LOCKOUT_THRESHOLD,
            lock_duration=LOCKOUT_DURATION,
            now=self._clock(),
        )
        if known and slot is None:
            # Locked (or the row is gone). The same Argon2id work as any attempt, against the
            # dummy hash, so this answer is never faster than a wrong password and shows nothing;
            # the real hash is never checked, so a locked account gives no further guess. The
            # address reservation stands: an attempt at a locked account is a failure from it.
            await self._hasher.verify_dummy(request.password)
            raise AccountLocked()

        # #2802: a lock this attempt's reservation applied is counted once: by `_on_failure`, or,
        # if the attempt ends (cancelled, or the verify or settle raised) before either that or
        # the settle that clears it, on the way out below, with the error propagated.
        lock_uncounted = slot is not None and slot[1] is not None
        try:
            password_ok = await self._hasher.verify(user.password_hash, request.password)
            if not (known and password_ok) or slot is None:
                lock_uncounted = False
                self._on_failure(slot)
                raise InvalidCredentials("Username or password is incorrect")

            # Password verified. Settle the reservation unless another attempt's lock landed
            # while this one was in flight: then even the correct password is refused, so nothing
            # signs in after the lock. Only the enrolment-only sign-in ends here (the count is
            # reset, as `record_login_success` does); every other outcome gives the reservation
            # back (#2695: with a second factor still to pass the count is kept; `MfaService`
            # resets it).
            complete = (
                user.status is UserStatus.ACTIVE and user.mfa_required and not user.mfa_methods
            )
            settled = await self._repository.settle_login_attempt(
                str(user.id), slot=slot[0], complete=complete, now=self._clock()
            )
            lock_uncounted = False
        finally:
            if lock_uncounted:
                auth_lockouts_total.inc()
        if not settled:
            raise AccountLocked()

        # A disabled user is refused only now, after the one verify every attempt takes; the
        # router answers it as a wrong password (SR-014, #4961).
        if user.status is UserStatus.DISABLED:
            raise AccountDisabled("Account disabled - contact the owner")

        if not user.mfa_required:
            # A password-only full session is undecided (#2295 Q6), and C-12.2
            # forbids such a user (#965 refuses `mfa_required: false`). Fail
            # closed: never fabricate a session shape for it, and answer it as a wrong password
            # (SR-014, #4961), held to the same floor, and counted from this address as any
            # refusal is. Like every refusal, it comes before the success-path work below.
            raise MfaNotRequired()

        if self._hasher.needs_rehash(user.password_hash, DEFAULT_ARGON2_PARAMS):
            new_hash = await self._hasher.hash(request.password, DEFAULT_ARGON2_PARAMS)
            await self._repository.rehash_password(
                str(user.id), password_hash=new_hash, algo_params=DEFAULT_ARGON2_PARAMS
            )

        if user.mfa_required and not user.mfa_methods:
            # #2295 (Q6): TOTP is mandatory (C-12.2), so the password alone opens
            # only an enrolment-only session (never enrolled, or after an owner
            # reset or a recovery sign-in). The router mints it; no challenge row.
            # No second factor follows, so this sign-in is complete: the settle reset the count.
            return EnrolmentOnlyLogin(user_id=user.id)
        # #2695: with a second factor still to pass, the account count is kept; `MfaService`
        # resets it once the sign-in completes, and counts each refused code on it.
        mfa_token = self._mfa_token_factory()
        if self._mfa_repository is not None:
            # E09-S02: persist the challenge so `MfaService.verify()` /
            # `.check_recovery()` can look up `mfa_token` (hashed — never stored in
            # the clear, same rationale as `sessions.refresh_token_hash`).
            # `mfa_repository` is `None` on the fake/CI-default backend
            # (mirrors `UserRepository`'s own optionality in `AuthService`);
            # the challenge row is skipped there and `MfaChallengeResult` is
            # still returned so E09-S01's own tests keep passing unchanged.
            now = self._clock()
            await self._mfa_repository.create_challenge(
                str(user.id),
                purpose="login",
                mfa_token_hash=_hash_mfa_token(mfa_token),
                expires_at=now + MFA_CHALLENGE_TTL,
            )

        return MfaChallengeResult(
            mfa_token=mfa_token,
            methods=user.mfa_methods,
            expires_in=300,
        )

    def _on_failure(self, slot: tuple[int, datetime | None] | None) -> None:
        # #2802: the failure was counted by the attempt's reservation, taken before the verify in
        # one atomic repository statement (`UserRepository.reserve_login_attempt`), never from a
        # (possibly stale) `UserRecord` snapshot, so a burst cannot lose a count or get more than
        # `LOCKOUT_THRESHOLD` guesses before the lock. Nothing is written here.
        if slot is not None and slot[1] is not None:
            # SR-125: this failure left the account locked: the fifth, or the first after an
            # expired lock. One reservation per lock is granted, so a burst counts one lock.
            # Attempts refused while locked never get here; `StepUpService` counts the locks its
            # own failures apply.
            auth_lockouts_total.inc()
