"""#2152 S5b: the eight MFA operations while M2's auth keyring cannot serve (22 `AuthUnavailable`,
"Order of checks"; ruling D4, BQ-13). Each raises `MfaKeyringUnavailable` where the contract puts
it and counts, consumes and changes nothing: every store, the hasher and the throttles sit behind
a spy that records each call, and only the reads the contract lets come first appear. The checks
before it keep their answers, a user without a method still signs in, and a method this process
cannot open is never "no method" (AC6). Unit level, over the fakes and the test keyring."""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from candleviewer.auth.errors import (
    InvalidCredentials,
    MfaChallengeInvalid,
    MfaCodeInvalid,
    MfaEnrollmentNotFound,
    MfaKeyringUnavailable,
    RecoveryCodeInvalid,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.invite_service import InviteService, hash_token
from candleviewer.auth.login_service import EnrolmentOnlyLogin, LoginService
from candleviewer.auth.mfa_keyring import KEY_NOT_HELD, KEYRING_UNAVAILABLE
from candleviewer.auth.mfa_service import MfaService, _hash_token
from candleviewer.auth.models import (
    InviteCreateRequest,
    LoginRequest,
    MfaChallengeResult,
    MfaEnrollRequest,
    MfaMethodKind,
    MfaVerifyRequest,
    SessionRecord,
)
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.auth.auth_fakes import FakeUserRepository, InMemoryOwnerReset, make_user, no_wait
from tests.unit.auth.mfa_fakes import FakeMfaKeyring, FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_invite_service import FakeHasher, FakeRepo

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
PW = "correct horse battery staple"  # test literal, never a credential
IP = "10.0.0.9"
DOWN = "kek_unavailable"
_HASHES: dict[str, str] = {}


class _Spy:
    """Every call through it, by name, then the call itself (sync or async)."""

    def __init__(self, inner: Any) -> None:
        self.inner: Any = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr
        calls: list[str] = self.calls

        if inspect.iscoroutinefunction(attr):

            async def acall(*args: Any, **kwargs: Any) -> Any:
                calls.append(name)
                return await attr(*args, **kwargs)

            return acall

        def call(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return attr(*args, **kwargs)

        return call


class _World:
    """The services over spied fakes: a user with `PW` and, unless `enrolled=False`, one
    confirmed TOTP method made while the keyring is up; each spy is cleared once it is built."""

    def __init__(self, *, enrolled: bool = True) -> None:
        self.keyring = FakeMfaKeyring()
        self.users = _Spy(FakeUserRepository())
        self.mfa_repo = _Spy(FakeMfaRepository())
        self.sessions = _Spy(FakeSessionRepository())
        self.invites = _Spy(FakeRepo())
        self.hasher = _Spy(Hasher())
        self.throttle = _Spy(PerIpLoginThrottle(max_attempts=1000))
        self.mfa = MfaService(self.mfa_repo, self.keyring, clock=self.clock, sleep=no_wait)
        methods = (MfaMethodKind.TOTP,) if enrolled else ()
        self.user = make_user(
            password_hash=_HASHES["pw"], mfa_methods=methods, failed_login_count=2
        )
        self.users.inner.add(self.user)
        self.uid = str(self.user.id)

    def clock(self) -> datetime:
        return T0

    def login(self) -> LoginService:
        return LoginService(
            self.users,
            cast(Hasher, self.hasher),  # each spy stands in for the concrete class it wraps
            per_ip_throttle=cast(PerIpLoginThrottle, self.throttle),
            clock=self.clock,
            mfa_repository=self.mfa_repo,
            sleep=no_wait,
            mfa_keyring=self.keyring,
        )

    def step_up(self) -> StepUpService:
        reset = InMemoryOwnerReset(self.users.inner, self.mfa_repo.inner, self.sessions.inner)
        return StepUpService(
            self.mfa_repo,
            self.sessions,
            self.keyring,
            self.users,
            cast(Hasher, self.hasher),
            clock=self.clock,
            sleep=no_wait,
            owner_reset=reset,
        )

    def invite_service(self) -> InviteService:
        hasher = _Spy(FakeHasher())
        self.invite_hasher = hasher
        return InviteService(
            self.invites,
            cast(Hasher, hasher),
            self.mfa,
            clock=self.clock,
            throttle=cast(PerIpLoginThrottle, self.throttle),
        )

    async def enrol(self) -> bytes:
        """A confirmed TOTP method for the user, made while the keyring is up; its seed."""
        req = MfaEnrollRequest(method=MfaMethodKind.TOTP, label="")
        res = await self.mfa.enroll(self.uid, req, account_name="u")
        seed = self.keyring.decrypt(self.mfa_repo.inner.methods[str(res.method_id)].secret_enc)
        code = generate_code(seed, time_step_for(T0.timestamp()) - 1)
        await self.mfa.confirm_enrollment(self.uid, method_id=str(res.method_id), code=code)
        return seed

    async def challenge(self) -> str:
        token = uuid.uuid4().hex
        await self.mfa_repo.inner.create_challenge(
            self.uid,
            purpose="login",
            mfa_token_hash=_hash_token(token),
            expires_at=T0 + timedelta(minutes=5),
        )
        return token

    def down(self, reason: str = DOWN) -> None:
        self.keyring.down = reason
        self.keyring.opened.clear()
        for spy in (
            self.users,
            self.mfa_repo,
            self.sessions,
            self.invites,
            self.hasher,
            self.throttle,
        ):
            spy.calls.clear()


@pytest.fixture(autouse=True)
async def _password_hash() -> None:
    if "pw" not in _HASHES:  # one Argon2id hash for the module (slow by design)
        _HASHES["pw"] = await Hasher().hash(PW)


async def _raises(call: Callable[[], Any]) -> MfaKeyringUnavailable:
    with pytest.raises(MfaKeyringUnavailable) as refused:
        await call()
    return refused.value


# -- POST /auth/login -----------------------------------------------------------------------------


async def test_login_answers_unavailable_after_the_password_and_writes_nothing() -> None:
    w = _World()
    await w.enrol()
    w.down()
    exc = await _raises(
        lambda: w.login().login(LoginRequest(identifier="basiltt", password=PW), source_ip=IP)
    )
    assert (exc.reason, exc.user_id) == (KEYRING_UNAVAILABLE, w.user.id)
    assert w.users.calls == ["find_by_identifier"]  # no rehash, no success, no failure count
    assert w.mfa_repo.calls == ["find_active_totp_methods"]  # the key refs; no challenge
    assert w.hasher.calls == ["verify"] and "record_failure" not in w.throttle.calls
    assert w.users.inner.users[w.uid].failed_login_count == 2  # neither counted nor reset


async def test_login_writes_its_challenge_once_the_keyring_serves() -> None:
    """The control: the spies see the writes a sign-in makes. With a second factor still to
    pass, the account's count is kept (#2695), so the challenge is the one write."""
    w = _World()
    await w.enrol()
    w.down()
    w.keyring.down = None
    result = await w.login().login(LoginRequest(identifier="basiltt", password=PW), source_ip=IP)
    assert isinstance(result, MfaChallengeResult)
    assert "create_challenge" in w.mfa_repo.calls
    assert "record_login_success" not in w.users.calls


async def test_a_method_under_a_key_not_held_is_unavailable_never_no_method() -> None:
    """AC6: the user's only method is sealed under a key this process does not hold."""
    w = _World()
    await w.enrol()
    w.down()
    w.keyring.down, w.keyring.held = None, frozenset({"akey:another"})
    exc = await _raises(
        lambda: w.login().login(LoginRequest(identifier="basiltt", password=PW), source_ip=IP)
    )
    assert exc.reason == KEY_NOT_HELD
    assert "create_challenge" not in w.mfa_repo.calls


async def test_a_user_without_a_method_still_signs_in_while_the_keyring_is_down() -> None:
    w = _World(enrolled=False)
    w.down()
    result = await w.login().login(LoginRequest(identifier="basiltt", password=PW), source_ip=IP)
    assert result == EnrolmentOnlyLogin(user_id=w.user.id)


async def test_a_wrong_password_keeps_its_answer_and_its_count_while_the_keyring_is_down() -> None:
    w = _World()
    await w.enrol()
    w.down()
    with pytest.raises(InvalidCredentials):
        await w.login().login(
            LoginRequest(identifier="basiltt", password="wrong " + PW), source_ip=IP
        )
    assert "record_login_failure" in w.users.calls


# -- POST /auth/mfa/verify and /auth/mfa/recovery -------------------------------------------------


async def test_verify_answers_unavailable_after_the_token_and_counts_no_attempt() -> None:
    w = _World()
    seed = await w.enrol()
    token = await w.challenge()
    w.down()
    code = generate_code(seed, time_step_for(T0.timestamp()))
    request = MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code)
    exc = await _raises(lambda: w.mfa.verify(request))
    assert exc.user_id == w.user.id
    assert w.mfa_repo.calls == ["find_open_challenge_by_token_hash", "find_active_totp_methods"]
    assert w.keyring.opened == []  # no seed opened, so no code examined
    assert next(iter(w.mfa_repo.inner.challenges.values())).attempts == 0


async def test_one_method_this_process_cannot_open_is_enough_for_the_503() -> None:
    """22: a code is never checked against some of the user's methods and then answered `503`."""
    w = _World()
    await w.enrol()
    blob = w.keyring.encrypt(bytes(range(20)))
    other = await w.mfa_repo.inner.create_pending_method(
        w.uid, secret_enc=blob, secret_key_ref="akey:another", label="b"
    )
    await w.mfa_repo.inner.seed_confirmed(str(other.id), now=T0)
    token = await w.challenge()
    w.down()
    w.keyring.down, w.keyring.held = None, frozenset({w.keyring.key_ref})
    request = MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code="123456")
    exc = await _raises(lambda: w.mfa.verify(request))
    assert exc.reason == KEY_NOT_HELD and w.keyring.opened == []


async def test_an_unknown_token_keeps_its_answer_while_the_keyring_is_down() -> None:
    w = _World()
    w.down()
    request = MfaVerifyRequest(mfa_token="nope", method=MfaMethodKind.TOTP, code="123456")
    with pytest.raises(MfaChallengeInvalid):
        await w.mfa.verify(request)


async def test_recovery_answers_unavailable_before_the_pool_and_the_code() -> None:
    w = _World()
    await w.enrol()
    token = await w.challenge()
    w.down()
    await _raises(lambda: w.mfa.check_recovery(token, "ABCD-EFGH"))
    assert w.mfa_repo.calls == ["find_open_challenge_by_token_hash"]  # the pool is never counted


# -- POST /auth/mfa/enroll and /auth/mfa/enroll/confirm -------------------------------------------


async def test_enrolment_answers_unavailable_before_a_seed_and_creates_no_method() -> None:
    w = _World(enrolled=False)
    w.down()
    req = MfaEnrollRequest(method=MfaMethodKind.TOTP, label="")
    await _raises(lambda: w.mfa.enroll(w.uid, req, account_name="u"))
    assert w.mfa_repo.calls == [] and w.mfa_repo.inner.methods == {}


async def test_confirmation_answers_unavailable_after_the_lookup_and_stays_pending() -> None:
    w = _World(enrolled=False)
    res = await w.mfa.enroll(
        w.uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="u"
    )
    w.down()
    await _raises(
        lambda: w.mfa.check_enrollment(w.uid, method_id=str(res.method_id), code="123456")
    )
    assert w.mfa_repo.calls == ["find_pending_method"]
    assert w.mfa_repo.inner.methods[str(res.method_id)].confirmed_at is None
    with pytest.raises(MfaEnrollmentNotFound):  # an unknown method keeps its answer
        await w.mfa.check_enrollment(w.uid, method_id=str(uuid.uuid4()), code="123456")


async def test_regeneration_replaces_no_code_while_the_keyring_is_down() -> None:
    """BQ-17: no route calls it today, and it must refuse as the others do."""
    w = _World()
    await w.enrol()
    w.down()
    await _raises(lambda: w.mfa.regenerate_recovery_codes(w.uid))
    assert w.mfa_repo.calls == []


# -- POST /auth/step-up ---------------------------------------------------------------------------


async def test_step_up_answers_unavailable_before_either_factor() -> None:
    w = _World()
    seed = await w.enrol()
    session = SessionRecord(
        id=uuid.uuid4(), user_id=w.user.id, refresh_token_hash=uuid.uuid4().hex,
        access_token_jti=None, issued_at=T0, last_seen_at=T0, expires_at=T0 + timedelta(hours=1),
        revoked_at=None, revoked_reason=None, ip=None, user_agent=None, device_label=None,
        is_electron=False, mfa_satisfied_at=T0,
    )  # fmt: skip
    w.sessions.inner.sessions[str(session.id)] = session
    svc = w.step_up()
    w.down()
    code = generate_code(seed, time_step_for(T0.timestamp()))
    await _raises(lambda: svc.step_up(w.uid, str(session.id), "users", code, PW))
    assert w.hasher.calls == [] and w.users.calls == []  # no password verified or counted
    assert w.mfa_repo.calls == ["find_active_totp_methods"]
    assert {"update_step_up_state", "save_step_up_state"}.isdisjoint(w.sessions.calls)
    saved = w.sessions.inner.sessions[str(session.id)]
    assert (saved.step_up_failures, saved.step_up_elevations) == (0, {})


# -- POST /invites/{inviteToken} and its /confirm -------------------------------------------------


async def _invite(svc: InviteService) -> str:
    async def ok(user_id: uuid.UUID, role: str) -> None:
        """An accepting write-ahead hook."""

    req = InviteCreateRequest.model_validate(
        {"email": "ann@example.com", "username": "annie", "roles": ["viewer"]}
    )
    return (await svc.create(req, invited_by=uuid.uuid4(), audit=ok)).token


async def test_redemption_answers_unavailable_before_the_hash_and_the_token_is_kept() -> None:
    w = _World(enrolled=False)
    svc = w.invite_service()
    token = await _invite(svc)
    w.down()
    await _raises(lambda: svc.begin_redemption(token, password=PW, source_ip=IP))
    assert w.invite_hasher.calls == [] and w.invites.calls == ["find_by_token_hash"]
    assert w.invites.inner.rows[hash_token(token)].consumed_at is None
    assert w.throttle.calls == []  # no failed attempt for the address


async def test_confirmation_of_an_invite_answers_unavailable_and_counts_nothing() -> None:
    w = _World(enrolled=False)
    svc = w.invite_service()
    token = await _invite(svc)
    start = await svc.begin_redemption(token, password=PW, source_ip=IP)
    w.down()

    async def unused(*_a: Any) -> None:
        raise AssertionError("no record is written before the 503")

    await _raises(
        lambda: svc.complete_redemption(
            token,
            method_id=str(start.method_id),
            code="123456",
            source_ip=IP,
            audit_downgrade=unused,
            audit_bootstrap=unused,
        )
    )
    assert w.invites.calls == ["find_by_token_hash"] and w.mfa_repo.calls == ["find_pending_method"]
    assert w.throttle.calls == []


# -- wrong codes ----------------------------------------------------------------------------------


async def test_a_seal_that_does_not_open_is_a_wrong_code_and_is_counted() -> None:
    """AC9 and BQ-9's "corrupt seed": `MfaSealInvalid` is never a 503."""
    w = _World()
    await w.enrol()
    for method_id, method in list(w.mfa_repo.inner.methods.items()):
        w.mfa_repo.inner.methods[method_id] = method.model_copy(update={"secret_enc": bytes(40)})
    token = await w.challenge()
    request = MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code="123456")
    with pytest.raises(MfaCodeInvalid):
        await w.mfa.verify(request)
    assert next(iter(w.mfa_repo.inner.challenges.values())).attempts == 1


async def test_a_recovery_code_longer_than_any_body_is_a_wrong_code_and_is_counted() -> None:
    w = _World()
    await w.enrol()
    token = await w.challenge()
    with pytest.raises(RecoveryCodeInvalid):
        await w.mfa.check_recovery(token, "A" * 600)
    assert next(iter(w.mfa_repo.inner.challenges.values())).attempts == 1
    assert "find_unused_recovery_code" not in w.mfa_repo.calls
