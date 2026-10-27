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
- disabled account -> `AccountDisabled`, but only ever raised *after* a
  correct password (ticket's documented trade-off);
- five consecutive failures -> `AccountLocked` for 15 minutes, persisted so
  a process restart does not clear it;
- a per-IP throttle independent of the per-account one (ticket "Scope /
  Deliverables": "one attacker cannot lock every account");
- every failed sign-in (`InvalidCredentials`, `AccountLocked`, `AccountDisabled`)
  returns no sooner than `LOGIN_FAILURE_FLOOR` after the attempt started (#4648);
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
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from candleviewer.auth.errors import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    SignInBusy,
)
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.metrics import (
    auth_lockouts_total,
    auth_login_failure_floor_missed_total,
    auth_login_verify_refused_total,
)
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, UserRecord, UserStatus
from candleviewer.auth.repository import UserRepository
from candleviewer.auth.throttle import PerIpLoginThrottle, VerifyAdmission
from candleviewer.settings import AUTH_LOGIN_FAILURE_FLOOR_MS, AUTH_LOGIN_VERIFY_CONCURRENCY

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
LOGIN_FAILURE_FLOOR = timedelta(milliseconds=AUTH_LOGIN_FAILURE_FLOOR_MS)

#: #4663: sign-in verification runs for at most this many attempts at a time. The default only:
#: production passes `CV_AUTH_LOGIN_VERIFY_CONCURRENCY`, whose default this is.
LOGIN_VERIFY_CONCURRENCY = AUTH_LOGIN_VERIFY_CONCURRENCY
#: #4663: the retry-after of an attempt refused because verification was at capacity. A sign-in
#: verification normally completes well within it, so a place has usually freed by then.
LOGIN_BUSY_RETRY_AFTER_S = 1

Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

#: The id of the placeholder record below: the nil UUID, never a real user (user ids are
#: server-generated uuid4), so `UserRepository.record_login_failure` for it changes no row.
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
        self._failure_floor_s = max(failure_floor.total_seconds(), 0.0)
        self._monotonic = monotonic
        self._sleep = sleep
        #: #4663: the bound on sign-in verifications in flight; `admission` is for tests.
        self._admission = admission or VerifyAdmission(verify_concurrency)

    async def login(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin:
        """Verify credentials and return the MFA challenge for step 2, or, for a user
        with `mfa_required` and no confirmed method, `EnrolmentOnlyLogin` (#2295, Q6).

        Raises `InvalidCredentials`, `AccountDisabled`, or `AccountLocked`, all
        before either outcome. A user without `mfa_required` and without a method
        still raises `NotImplementedError` (see the note at that branch).

        #4648: each of those three refusals returns no sooner than the failure floor after
        the attempt started (`_hold_failure`); a successful outcome is never held.

        #4663: raises `SignInBusy` at once, before the identifier is looked up or any password
        is checked, when verification is already running for as many attempts as it admits.
        That refusal is not held to the failure floor: it is answered as soon as it is decided.
        """
        started = self._monotonic()
        try:
            return await self._check_credentials(request, source_ip=source_ip)
        except (InvalidCredentials, AccountLocked, AccountDisabled):
            # Every failure write has already happened inside the check; only the response
            # waits. A cancellation during the wait propagates (nothing here catches it).
            await self._hold_failure(started)
            raise

    async def _hold_failure(self, started: float) -> None:
        """Wait until the failure floor has passed since *started*. Bounded by the floor
        itself, and no wait at all when the attempt already took longer: that attempt is
        counted, so a failure returned without the wait is never silent."""
        remaining = started + self._failure_floor_s - self._monotonic()
        wait = min(remaining, self._failure_floor_s)
        if wait > 0:
            await self._sleep(wait)
        elif self._failure_floor_s > 0:
            auth_login_failure_floor_missed_total.inc()

    async def _check_credentials(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin:
        if self._per_ip_throttle.is_blocked(source_ip):
            # Per-IP throttle failures are indistinguishable from a wrong
            # password to the caller: same exception type *and* same
            # message as every other `InvalidCredentials` raise in this
            # method, so the response body never leaks which of the several
            # failure reasons actually applied.
            raise InvalidCredentials("Username or password is incorrect")

        # #4663: take a verification place without waiting, or refuse at once. The place is
        # given back on every way out of the check, a cancellation included.
        if not self._admission.try_enter():
            auth_login_verify_refused_total.inc()
            raise SignInBusy(LOGIN_BUSY_RETRY_AFTER_S)
        try:
            return await self._verify_admitted(request, source_ip=source_ip)
        finally:
            self._admission.leave()

    async def _verify_admitted(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin:
        found = await self._repository.find_by_identifier(request.identifier)
        # Enumeration resistance: an unknown identifier (or, defensively, a record
        # carrying the placeholder's id) continues as `_ABSENT_USER` through the same
        # steps as a wrong password, and always fails.
        known = found is not None and found.id != ABSENT_USER_ID
        user = found if found is not None and known else _ABSENT_USER

        now = self._clock()
        if user.locked_until is not None and user.locked_until > now:
            # Still run the full Argon2id verification (against the real
            # hash) before reporting the lock, so a locked account's
            # response takes the same wall-clock time and the same
            # information shape as a wrong-password failure — this branch
            # must not become a cheap, fast-fail oracle that confirms the
            # account exists and is currently locked.
            await self._hasher.verify(user.password_hash, request.password)
            # #4663: an attempt at a locked account is a failed attempt from this address, so
            # repeated attempts from one address are refused by the throttle above and take
            # no verification place.
            self._per_ip_throttle.record_failure(source_ip)
            remaining = int((user.locked_until - self._clock()).total_seconds())
            raise AccountLocked(max(remaining, 1))

        password_ok = await self._hasher.verify(user.password_hash, request.password)
        if not (known and password_ok):
            self._per_ip_throttle.record_failure(source_ip)
            await self._on_failure(user)
            raise InvalidCredentials("Username or password is incorrect")

        # Password verified. Only now may the disabled state be revealed
        # (ticket's documented trade-off).
        if user.status is UserStatus.DISABLED:
            raise AccountDisabled("Account disabled - contact the owner")

        if self._hasher.needs_rehash(user.password_hash, DEFAULT_ARGON2_PARAMS):
            new_hash = await self._hasher.hash(request.password, DEFAULT_ARGON2_PARAMS)
            await self._repository.rehash_password(
                str(user.id), password_hash=new_hash, algo_params=DEFAULT_ARGON2_PARAMS
            )

        await self._repository.record_login_success(str(user.id))

        if user.mfa_required and not user.mfa_methods:
            # #2295 (Q6): TOTP is mandatory (C-12.2), so the password alone opens
            # only an enrolment-only session (never enrolled, or after an owner
            # reset or a recovery sign-in). The router mints it; no challenge row.
            return EnrolmentOnlyLogin(user_id=user.id)
        if not user.mfa_required:
            # A password-only full session is undecided (#2295 Q6), and C-12.2
            # forbids such a user (#965 refuses `mfa_required: false`). Fail
            # closed: never fabricate a session shape for it.
            raise NotImplementedError(
                "password-only sign-in is not specified; this user is not required "
                "to use MFA (C-12.2 forbids that state)"
            )

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

    async def _on_failure(self, user: UserRecord) -> None:
        # The increment and the lock decision are one atomic repository
        # operation (see `UserRepository.record_login_failure`) — this
        # method never reads `user.failed_login_count` to compute the new
        # count itself, because that snapshot can be stale under concurrent
        # requests (two parallel wrong-password attempts both reading
        # count=4 would each compute new_count=5 independently but only one
        # UPDATE would actually observe count=4, silently losing a failure
        # and letting an attacker get more than `LOCKOUT_THRESHOLD` guesses
        # in before the account locks).
        locked_until = await self._repository.record_login_failure(
            str(user.id),
            lockout_threshold=LOCKOUT_THRESHOLD,
            lock_duration=LOCKOUT_DURATION,
            now=self._clock(),
        )
        if locked_until is not None:
            # SR-125: this failure left the account locked: the fifth, or the first after an
            # expired lock. The repository returns the lock for every count at or above the
            # threshold, so a burst of parallel failures counts each. Attempts refused while
            # locked never get here; `StepUpService` counts the locks its own failures apply.
            auth_lockouts_total.inc()
