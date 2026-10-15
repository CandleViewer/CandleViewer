"""TOTP clock-skew reporting on the three verification surfaces (E09-Q05 gap #2146).

A rejected code that is the right code for a step 2..10 steps away raises one `totp_clock_skew`
system event and moves `auth_totp_clock_skew_total`. Whatever is reported, the caller still gets the
same refusal as for a wrong code, the attempt still counts, and the sink can change neither.
Fixed clock, in-memory fakes, no network, no sleeps.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from pydantic import SecretStr

from candleviewer.app import build_auth_service
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import MfaChallengeLocked, MfaCodeInvalid, StepUpCodeInvalid
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP, MfaService, _hash_token
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, MfaVerifyRequest
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.auth.totp_skew import TotpSkewReporter
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.settings import Settings

from .auth_fakes import FakeUserRepository, make_user
from .mfa_fakes import FakeMfaRepository, RecordingSystemEvents
from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
_RC_KEY = b"k" * 32
PASSWORD = "correct horse battery staple"
_HASHER = Hasher()
_PW_HASH: list[str] = []

#: Enrolment draws these seeds in order. Their codes for steps -13..+13 at `_NOW` are pairwise
#: distinct and never "000000" or "123456", so a "wrong" code cannot read as skew by chance.
_SEEDS = tuple(bytes(range(i, i + 20)) for i in range(1, 6))


def _clock() -> datetime:
    return _NOW


def _code(seed: bytes, offset: int = 0) -> str:
    return generate_code(seed, time_step_for(_NOW.timestamp()) + offset)


def _skew_total() -> float:
    kinds = ("authenticator_ahead", "authenticator_behind")
    return sum(
        REGISTRY.get_sample_value("auth_totp_clock_skew_total", {"kind": k}) or 0 for k in kinds
    )


def _verify_request(token: str, code: str) -> MfaVerifyRequest:
    return MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code)


@pytest.fixture(autouse=True)
def _fixed_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    drawn = iter(_SEEDS)
    monkeypatch.setattr("candleviewer.auth.mfa_service.generate_secret", lambda: next(drawn))


def _seed_of(repo: FakeMfaRepository, enc: TotpEncryptor, method_id: str) -> bytes:
    secret_enc = repo.methods[method_id].secret_enc
    assert secret_enc is not None
    return enc.decrypt(secret_enc)


class _Rig:
    """One `MfaService` over fakes with a recording event sink."""

    def __init__(self, events: RecordingSystemEvents | None = None) -> None:
        self.events = events if events is not None else RecordingSystemEvents()
        self.repo = FakeMfaRepository()
        self.enc = TotpEncryptor(os.urandom(32))
        reporter = TotpSkewReporter(self.events)
        self.svc = MfaService(
            self.repo, self.enc, recovery_code_key=_RC_KEY, clock=_clock, skew_reporter=reporter
        )

    async def pending(self, user: uuid.UUID) -> tuple[str, bytes]:
        request = MfaEnrollRequest(method=MfaMethodKind.TOTP, label="")
        res = await self.svc.enroll(str(user), request, account_name="a")
        return str(res.method_id), _seed_of(self.repo, self.enc, str(res.method_id))

    async def enrol(self, user: uuid.UUID) -> bytes:
        method_id, seed = await self.pending(user)
        # One step *before* now: inside the window, and never the step a later verify uses.
        code = _code(seed, offset=-1)
        await self.svc.confirm_enrollment(str(user), method_id=method_id, code=code)
        return seed

    async def challenge(self, user: uuid.UUID, token: str) -> str:
        await self.repo.create_challenge(
            str(user),
            purpose="login",
            mfa_token_hash=_hash_token(token),
            expires_at=_NOW + timedelta(minutes=5),
        )
        return token

    def attempts(self, token: str) -> int:
        digest = _hash_token(token)
        (record,) = [c for c in self.repo.challenges.values() if c.mfa_token_hash == digest]
        return record.attempts


# -- login (`MfaService.verify`) ---------------------------------------------------------------


@pytest.mark.parametrize("offset", [-3, 2])
async def test_login_skewed_code_is_refused_like_a_wrong_code_and_reported(offset: int) -> None:
    rig, user = _Rig(), uuid.uuid4()
    seed = await rig.enrol(user)
    skewed, wrong = await rig.challenge(user, "t-skew"), await rig.challenge(user, "t-wrong")
    before = _skew_total()
    with pytest.raises(MfaCodeInvalid) as skewed_error:
        await rig.svc.verify(_verify_request(skewed, _code(seed, offset)))
    with pytest.raises(MfaCodeInvalid) as wrong_error:
        await rig.svc.verify(_verify_request(wrong, "000000"))
    assert str(skewed_error.value) == str(wrong_error.value)  # no skew-specific answer: no oracle
    assert rig.attempts(skewed) == rig.attempts(wrong) == 1  # the cap still applies
    assert _skew_total() == before + 1  # the wrong code moved nothing
    (event,) = rig.events.written
    assert (event.component, event.kind, event.severity) == ("auth", "totp_clock_skew", "warning")
    assert event.details["surface"] == "login" and event.details["offset_steps"] == str(offset)


async def test_login_fifth_failed_attempt_still_reports_before_it_locks_the_challenge() -> None:
    rig, user = _Rig(), uuid.uuid4()
    seed = await rig.enrol(user)
    token = await rig.challenge(user, "t")
    for _ in range(CHALLENGE_ATTEMPT_CAP - 1):
        with pytest.raises(MfaCodeInvalid):
            await rig.svc.verify(_verify_request(token, "000000"))
    assert rig.events.written == []
    with pytest.raises(MfaChallengeLocked):
        await rig.svc.verify(_verify_request(token, _code(seed, -3)))
    assert [e.details["offset_steps"] for e in rig.events.written] == ["-3"]


async def test_login_event_sink_failure_changes_neither_the_refusal_nor_the_attempt_count() -> None:
    rig, user = _Rig(RecordingSystemEvents(fail_with=RuntimeError("db down"))), uuid.uuid4()
    seed = await rig.enrol(user)
    token, before = await rig.challenge(user, "t"), _skew_total()
    with pytest.raises(MfaCodeInvalid, match="invalid TOTP code"):
        await rig.svc.verify(_verify_request(token, _code(seed, -3)))
    assert rig.attempts(token) == 1 and _skew_total() == before + 1


async def test_login_with_two_methods_reports_the_skew_of_the_one_that_matches_once() -> None:
    rig, user = _Rig(), uuid.uuid4()
    await rig.enrol(user)
    second = await rig.enrol(user)
    token = await rig.challenge(user, "t")
    with pytest.raises(MfaCodeInvalid):
        await rig.svc.verify(_verify_request(token, _code(second, 3)))
    assert len(rig.events.written) == 1


# -- enrolment confirm (`MfaService.confirm_enrollment`) ---------------------------------------


async def test_enrolment_confirm_with_a_skewed_code_is_refused_and_reported() -> None:
    rig, user = _Rig(), uuid.uuid4()
    method_id, seed = await rig.pending(user)
    with pytest.raises(MfaCodeInvalid, match="invalid TOTP code"):
        await rig.svc.confirm_enrollment(str(user), method_id=method_id, code=_code(seed, 4))
    assert rig.repo.methods[method_id].confirmed_at is None  # still pending
    (event,) = rig.events.written
    assert event.details["surface"] == "enrolment" and event.details["offset_steps"] == "4"


# -- step-up (`StepUpService`) -----------------------------------------------------------------


async def _step_up_rig(
    events: RecordingSystemEvents,
) -> tuple[StepUpService, bytes, uuid.UUID, str]:
    rig, user = _Rig(), uuid.uuid4()
    seed = await rig.enrol(user)
    if not _PW_HASH:  # one Argon2id hash for the whole module (slow by design)
        _PW_HASH.append(await _HASHER.hash(PASSWORD))
    sessions, users = FakeSessionRepository(), FakeUserRepository()
    users.add(make_user(password_hash=_PW_HASH[0]).model_copy(update={"id": user}))
    minted = await SessionService(sessions, _HASHER, clock=_clock).mint(str(user))
    svc = StepUpService(
        rig.repo,
        sessions,
        rig.enc,
        users,
        _HASHER,
        clock=_clock,
        skew_reporter=TotpSkewReporter(events),
    )
    return svc, seed, user, str(minted.session_id)


async def test_step_up_with_a_skewed_code_is_refused_like_a_wrong_code_and_reported() -> None:
    events = RecordingSystemEvents()
    svc, seed, user, session = await _step_up_rig(events)
    with pytest.raises(StepUpCodeInvalid) as skewed:
        await svc.step_up(str(user), session, "keys", _code(seed, -3), PASSWORD)
    with pytest.raises(StepUpCodeInvalid) as wrong:
        await svc.step_up(str(user), session, "keys", "000000", PASSWORD)
    assert (skewed.value.failures_remaining, wrong.value.failures_remaining) == (2, 1)
    (event,) = events.written
    assert event.details["surface"] == "step_up" and event.details["offset_steps"] == "-3"


# -- wiring ------------------------------------------------------------------------------------


async def test_auth_service_gives_login_and_step_up_one_reporter_with_the_event_sink() -> None:
    events = RecordingSystemEvents()
    service = AuthService(
        FakeUserRepository(),
        pepper="pepper",
        mfa_repository=FakeMfaRepository(),
        totp_encryption_key=os.urandom(32),
        session_repository=FakeSessionRepository(),
        clock=_clock,
        system_events=events,
    )
    await service.start(ctx=None)  # type: ignore[arg-type]  # the key is given: ctx is not read
    assert service.mfa._skew_reporter._events is events
    assert service.step_up._skew_reporter is service.mfa._skew_reporter


def test_build_auth_service_wires_the_system_event_writer_on_the_real_backend_only() -> None:
    real = build_auth_service(
        Settings(
            storage_backend="real",
            auth_totp_key_hex=SecretStr("11" * 32),
            auth_recovery_hmac_key_hex=SecretStr("22" * 32),
            auth_pepper=SecretStr("pepper"),
        )
    )
    assert isinstance(real._system_events, PgSystemEventWriter)
    assert build_auth_service(Settings())._system_events is None
