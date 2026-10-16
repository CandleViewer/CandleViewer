"""Edge/race-path tests for `MfaService` (PR #1618 review, blocking 2:
per-file coverage of the safety-critical MFA service >= 95%)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import (
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    MfaEnrollmentNotFound,
    RecoveryCodeInvalid,
)
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP, MfaService, _hash_token
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, MfaVerifyRequest
from candleviewer.auth.recovery_codes import generate_recovery_codes, hash_recovery_code
from candleviewer.auth.totp import generate_code, time_step_for

from .mfa_fakes import FakeMfaRepository
from .totp_code_cases import ARABIC_INDIC_CODE

_RC_KEY = b"k" * 32
_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


def _service(repo: FakeMfaRepository) -> MfaService:
    return MfaService(
        repo, TotpEncryptor(os.urandom(32)), recovery_code_key=_RC_KEY, clock=lambda: _NOW
    )


async def _challenge(repo: FakeMfaRepository, user_id: uuid.UUID, token: str = "tok") -> str:  # noqa: S107 - test mfa_token label, not a credential
    await repo.create_challenge(
        str(user_id),
        purpose="login",
        mfa_token_hash=_hash_token(token),
        expires_at=_NOW + timedelta(minutes=5),
    )
    return token


async def _enrolled(service: MfaService, repo: FakeMfaRepository, uid: uuid.UUID) -> bytes:
    res = await service.enroll(
        str(uid), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
    )
    method = repo.methods[str(res.method_id)]
    assert method.secret_enc is not None
    seed = service._encryptor.decrypt(method.secret_enc)
    code = generate_code(seed, time_step_for(_NOW.timestamp()) - 1)
    await service.confirm_enrollment(str(uid), method_id=str(res.method_id), code=code)
    return seed


def _totp(seed: bytes) -> str:
    return generate_code(seed, time_step_for(_NOW.timestamp()))


def test_default_clock_is_tz_aware_utc() -> None:
    svc = MfaService(FakeMfaRepository(), TotpEncryptor(os.urandom(32)), recovery_code_key=_RC_KEY)
    assert svc._clock().tzinfo is UTC


async def test_verify_rejects_non_totp_method() -> None:
    svc = _service(FakeMfaRepository())
    with pytest.raises(MfaCodeInvalid, match="only method=totp"):
        await svc.verify(
            MfaVerifyRequest(mfa_token="t", method=MfaMethodKind.WEBAUTHN, code="123456")
        )


async def test_verify_without_confirmed_method_is_invalid() -> None:
    repo = FakeMfaRepository()
    token = await _challenge(repo, uuid.uuid4())
    with pytest.raises(MfaCodeInvalid, match="no active TOTP"):
        await _service(repo).verify(
            MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code="123456")
        )


async def test_verify_skips_method_without_secret_and_fails_closed() -> None:
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = uuid.uuid4()
    seed = await _enrolled(svc, repo, uid)
    for mid, m in list(repo.methods.items()):
        repo.methods[mid] = m.model_copy(update={"secret_enc": None})
    token = await _challenge(repo, uid)
    with pytest.raises(MfaCodeInvalid, match="invalid TOTP"):
        await svc.verify(
            MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=_totp(seed))
        )


async def test_verify_lost_challenge_race_mints_no_session() -> None:
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = uuid.uuid4()
    seed = await _enrolled(svc, repo, uid)
    token = await _challenge(repo, uid)

    async def _lost(challenge_id: str, *, now: datetime) -> bool:
        return False

    repo.satisfy_challenge = _lost  # type: ignore[method-assign]  # simulate 0-row UPDATE
    with pytest.raises(MfaChallengeInvalid, match="already satisfied"):
        await svc.verify(
            MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=_totp(seed))
        )


async def test_open_challenge_at_attempt_cap_is_locked() -> None:
    repo = FakeMfaRepository()
    uid = uuid.uuid4()
    token = await _challenge(repo, uid)
    for cid in list(repo.challenges):
        repo.challenges[cid] = repo.challenges[cid].model_copy(
            update={"attempts": CHALLENGE_ATTEMPT_CAP}
        )
    with pytest.raises(MfaChallengeLocked):
        await _service(repo).recover(token, "AAAA")


async def test_enroll_rejects_non_totp_method() -> None:
    with pytest.raises(MfaCodeInvalid, match="enrolment"):
        await _service(FakeMfaRepository()).enroll(
            "u", MfaEnrollRequest(method=MfaMethodKind.WEBAUTHN, label=""), account_name="a"
        )


async def test_confirm_pending_method_without_secret_is_not_found() -> None:
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = str(uuid.uuid4())
    res = await svc.enroll(
        uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
    )
    mid = str(res.method_id)
    repo.methods[mid] = repo.methods[mid].model_copy(update={"secret_enc": None})
    with pytest.raises(MfaEnrollmentNotFound, match="no TOTP secret"):
        await svc.confirm_enrollment(uid, method_id=mid, code="123456")


async def test_confirm_with_replayed_step_is_rejected() -> None:
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = str(uuid.uuid4())
    res = await svc.enroll(
        uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
    )
    mid = str(res.method_id)
    method = repo.methods[mid]
    assert method.secret_enc is not None
    seed = svc._encryptor.decrypt(method.secret_enc)
    step = time_step_for(_NOW.timestamp())
    repo.methods[mid] = method.model_copy(update={"last_accepted_time_step": step + 1})
    with pytest.raises(MfaCodeReused):
        await svc.confirm_enrollment(uid, method_id=mid, code=generate_code(seed, step))


async def test_confirm_keeps_existing_recovery_codes() -> None:
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = str(uuid.uuid4())
    await repo.replace_recovery_codes(uid, code_hashes=("x" * 64,))
    res = await svc.enroll(
        uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
    )
    method = repo.methods[str(res.method_id)]
    assert method.secret_enc is not None
    seed = svc._encryptor.decrypt(method.secret_enc)
    _, codes = await svc.confirm_enrollment(uid, method_id=str(res.method_id), code=_totp(seed))
    assert codes == ()


async def test_confirm_refuses_a_non_ascii_digit_code_like_a_wrong_one() -> None:
    """#2605: this raised `TypeError` out of `verify_code`. It is `MfaCodeInvalid`, and nothing
    changes: the method stays pending, no step is recorded, no recovery codes are issued."""
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = str(uuid.uuid4())
    res = await svc.enroll(
        uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
    )
    mid = str(res.method_id)
    with pytest.raises(MfaCodeInvalid, match="invalid TOTP"):
        await svc.confirm_enrollment(uid, method_id=mid, code=ARABIC_INDIC_CODE)
    pending = repo.methods[mid]
    assert pending.confirmed_at is None and pending.last_accepted_time_step is None
    assert await repo.count_unused_recovery_codes(uid) == 0


async def test_verify_counts_a_non_ascii_digit_code_as_a_failed_attempt() -> None:
    """#2605: `MfaVerifyRequest` refuses such a code at the HTTP edge; the service must not
    depend on that, so the request is built around the edge's pattern."""
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = uuid.uuid4()
    await _enrolled(svc, repo, uid)
    token = await _challenge(repo, uid)
    request = MfaVerifyRequest.model_construct(
        mfa_token=token, method=MfaMethodKind.TOTP, code=ARABIC_INDIC_CODE
    )
    with pytest.raises(MfaCodeInvalid, match="invalid TOTP"):
        await svc.verify(request)
    assert next(iter(repo.challenges.values())).attempts == 1


async def _with_codes(repo: FakeMfaRepository, uid: uuid.UUID) -> list[str]:
    codes = generate_recovery_codes()
    await repo.replace_recovery_codes(
        str(uid), code_hashes=tuple(hash_recovery_code(c, key=_RC_KEY) for c in codes)
    )
    return codes


async def test_recover_lost_consume_race_is_invalid_and_counts_attempt() -> None:
    """Conditional UPDATE on recovery_codes returned 0 rows (concurrent use)."""
    repo = FakeMfaRepository()
    uid = uuid.uuid4()
    codes = await _with_codes(repo, uid)
    token = await _challenge(repo, uid)

    async def _lost(code_id: str, *, now: datetime) -> bool:
        return False

    repo.consume_recovery_code = _lost  # type: ignore[method-assign]
    with pytest.raises(RecoveryCodeInvalid):
        await _service(repo).recover(token, codes[0])
    challenge = next(iter(repo.challenges.values()))
    assert challenge.attempts == 1
    assert challenge.satisfied_at is None


async def test_recover_lost_challenge_race_mints_no_session() -> None:
    repo = FakeMfaRepository()
    uid = uuid.uuid4()
    codes = await _with_codes(repo, uid)
    token = await _challenge(repo, uid)

    async def _lost(challenge_id: str, *, now: datetime) -> bool:
        return False

    repo.satisfy_challenge = _lost  # type: ignore[method-assign]
    with pytest.raises(MfaChallengeInvalid, match="already satisfied"):
        await _service(repo).recover(token, codes[0])


async def test_recover_code_valid_once_then_rejected() -> None:
    repo = FakeMfaRepository()
    svc = _service(repo)
    uid = uuid.uuid4()
    codes = await _with_codes(repo, uid)
    await svc.recover(await _challenge(repo, uid, "t1"), codes[0])
    with pytest.raises(RecoveryCodeInvalid):
        await svc.recover(await _challenge(repo, uid, "t2"), codes[0])


async def test_recover_with_wrong_hmac_key_rejects_valid_code() -> None:
    repo = FakeMfaRepository()
    uid = uuid.uuid4()
    codes = await _with_codes(repo, uid)
    token = await _challenge(repo, uid)
    other = MfaService(
        repo, TotpEncryptor(os.urandom(32)), recovery_code_key=b"z" * 32, clock=lambda: _NOW
    )
    with pytest.raises(RecoveryCodeInvalid):
        await other.recover(token, codes[0])
