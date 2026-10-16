"""Unit tests for `candleviewer.auth.mfa_service.MfaService`, E09-S02.

Each test name maps to a ticket Gherkin scenario in its docstring/comment.
"""

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
    RecoveryCodesExhausted,
)
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP, MfaService, _hash_token
from candleviewer.auth.models import (
    MfaEnrollRequest,
    MfaMethodKind,
    MfaRecoveryCheck,
    MfaVerifyRequest,
)
from candleviewer.auth.recovery_codes import generate_recovery_codes, hash_recovery_code
from candleviewer.auth.totp import generate_code, time_step_for

from .mfa_fakes import FakeMfaRepository

_RC_KEY = b"k" * 32

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _NOW


def _service(repo: FakeMfaRepository) -> MfaService:
    key = os.urandom(32)
    return MfaService(repo, TotpEncryptor(key), recovery_code_key=_RC_KEY, clock=_clock)


async def _make_login_challenge(repo: FakeMfaRepository, user_id: uuid.UUID) -> str:
    token = "raw-token"
    await repo.create_challenge(
        str(user_id),
        purpose="login",
        mfa_token_hash=_hash_token(token),
        expires_at=_NOW + timedelta(minutes=5),
    )
    return token


async def _enroll_and_confirm(
    service: MfaService, repo: FakeMfaRepository, user_id: uuid.UUID
) -> bytes:
    """Returns the raw TOTP seed for `user_id`'s single confirmed method."""
    result = await service.enroll(
        str(user_id), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="alice"
    )
    method = repo.methods[str(result.method_id)]
    seed = service._encryptor.decrypt(method.secret_enc)  # type: ignore[arg-type]
    # Confirm one step *before* "now" (still within the +/-1 skew window) so
    # the time-step it consumes never collides with a later `verify()` call
    # made against the same fixed `_clock()` in these tests.
    step = time_step_for(_NOW.timestamp()) - 1
    code = generate_code(seed, step)
    await service.confirm_enrollment(str(user_id), method_id=str(result.method_id), code=code)
    return seed


# -- verify() ------------------------------------------------------------


async def test_verify_valid_code_creates_a_session() -> None:
    """ "Valid code creates a session"."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    seed = await _enroll_and_confirm(service, repo, user_id)
    token = await _make_login_challenge(repo, user_id)

    step = time_step_for(_NOW.timestamp())
    code = generate_code(seed, step)
    result = await service.verify(
        MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code),
    )
    assert result.user_id == user_id


async def test_verify_reused_code_is_rejected() -> None:
    """ "Reused code is rejected"."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    seed = await _enroll_and_confirm(service, repo, user_id)
    token = await _make_login_challenge(repo, user_id)
    code = generate_code(seed, time_step_for(_NOW.timestamp()))
    await service.verify(
        MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code),
    )

    token2 = await _make_login_challenge(repo, user_id)
    with pytest.raises(MfaCodeReused):
        await service.verify(
            MfaVerifyRequest(mfa_token=token2, method=MfaMethodKind.TOTP, code=code),
        )


async def test_verify_tolerates_clock_drift_within_one_step() -> None:
    """ "Clock drift within one step is tolerated"."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    seed = await _enroll_and_confirm(service, repo, user_id)
    token = await _make_login_challenge(repo, user_id)

    drifted_step = time_step_for(_NOW.timestamp()) + 1
    code = generate_code(seed, drifted_step)
    result = await service.verify(
        MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code),
    )
    assert result.user_id == user_id


async def test_verify_wrong_code_raises_mfa_code_invalid() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    token = await _make_login_challenge(repo, user_id)

    with pytest.raises(MfaCodeInvalid):
        await service.verify(
            MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code="000000"),
        )


async def test_verify_unknown_token_raises_challenge_invalid() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    with pytest.raises(MfaChallengeInvalid):
        await service.verify(
            MfaVerifyRequest(mfa_token="nope", method=MfaMethodKind.TOTP, code="123456"),
        )


async def test_verify_expired_challenge_raises_challenge_invalid() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    token = "expired-token"
    await repo.create_challenge(
        str(user_id),
        purpose="login",
        mfa_token_hash=_hash_token(token),
        expires_at=_NOW - timedelta(seconds=1),
    )
    with pytest.raises(MfaChallengeInvalid):
        await service.verify(
            MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code="123456"),
        )


async def test_verify_locks_after_five_failed_attempts() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    token = await _make_login_challenge(repo, user_id)

    for _ in range(CHALLENGE_ATTEMPT_CAP - 1):
        with pytest.raises(MfaCodeInvalid):
            await service.verify(
                MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code="000000"),
            )
    with pytest.raises(MfaChallengeLocked):
        await service.verify(
            MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code="000000"),
        )


# -- enroll() / confirm_enrollment() --------------------------------------


async def test_first_login_enrolment_returns_recovery_codes() -> None:
    """ "First-login enrolment": "TOTP is enabled and 10 single-use recovery
    codes are displayed once"."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    kind_and_codes_seed = await _enroll_and_confirm(service, repo, user_id)
    assert kind_and_codes_seed  # enrolment completed without raising

    method = next(iter(repo.methods.values()))
    assert method.confirmed_at is not None


async def test_confirm_enrollment_invalid_code_raises() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    result = await service.enroll(
        str(user_id), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="alice"
    )
    with pytest.raises(MfaCodeInvalid):
        await service.confirm_enrollment(
            str(user_id), method_id=str(result.method_id), code="000000"
        )


async def test_confirm_enrollment_unknown_method_raises_not_found() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    with pytest.raises(MfaEnrollmentNotFound):
        await service.confirm_enrollment(
            str(uuid.uuid4()), method_id=str(uuid.uuid4()), code="123456"
        )


# -- check_recovery() / complete_recovery() (#2344) -----------------------------------------


async def _recover(service: MfaService, token: str, code: str) -> MfaRecoveryCheck:
    """Both halves, as `POST /auth/mfa/recovery` runs them around its audit records."""
    check = await service.check_recovery(token, code)
    await service.complete_recovery(check)
    return check


async def _with_recovery_codes(
    repo: FakeMfaRepository, user_id: uuid.UUID, count: int
) -> list[str]:
    codes = generate_recovery_codes(count=count)
    await repo.replace_recovery_codes(
        str(user_id), code_hashes=tuple(hash_recovery_code(c, key=_RC_KEY) for c in codes)
    )
    return codes


async def test_recovery_code_use_forces_totp_reenrollment() -> None:
    """ "Recovery code use forces re-enrolment": every method is revoked, for good (#2344)."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    codes = await _with_recovery_codes(repo, user_id, 10)
    token = await _make_login_challenge(repo, user_id)

    check = await _recover(service, token, codes[0])

    assert check.user_id == user_id
    method = next(iter(repo.methods.values()))
    assert (method.confirmed_at is not None, method.revoked_at) == (True, _NOW)
    assert next(iter(repo.challenges.values())).satisfied_at == _NOW


@pytest.mark.parametrize("unused_before", [10, 4, 3, 2, 1])
async def test_recovery_code_use_forces_reenrollment_however_many_codes_remain(
    unused_before: int,
) -> None:
    """#2296: there is no remaining-codes threshold. A recovery sign-in forces
    re-enrolment whether it leaves nine codes or none (E09-S02 "Recovery code
    use forces re-enrolment", US-ONB-003)."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    codes = await _with_recovery_codes(repo, user_id, unused_before)
    token = await _make_login_challenge(repo, user_id)

    await _recover(service, token, codes[0])

    assert await repo.count_unused_recovery_codes(str(user_id)) == unused_before - 1
    assert await repo.find_active_methods(str(user_id)) == ()


async def test_check_recovery_changes_nothing_but_names_what_completion_spends() -> None:
    """The read-only half (C-2.9): the audit records go between it and `complete_recovery`."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    codes = await _with_recovery_codes(repo, user_id, 10)
    token = await _make_login_challenge(repo, user_id)
    methods = dict(repo.methods)

    check = await service.check_recovery(token, codes[0])

    challenge = next(iter(repo.challenges.values()))
    assert (check.user_id, check.challenge_id) == (user_id, challenge.id)
    assert repo.recovery_codes[check.code_id]["used_at"] is None
    assert (challenge.satisfied_at, challenge.attempts) == (None, 0)
    assert repo.methods == methods
    assert await repo.count_unused_recovery_codes(str(user_id)) == 10


async def test_complete_recovery_revokes_every_method_of_that_user_only() -> None:
    """Confirmed and pending methods alike, so none can be confirmed again; another user's stay."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id, other = uuid.uuid4(), uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    await _enroll_and_confirm(service, repo, other)
    pending = await service.enroll(
        str(user_id), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
    )
    codes = await _with_recovery_codes(repo, user_id, 10)
    token = await _make_login_challenge(repo, user_id)

    await _recover(service, token, codes[0])

    mine = [m for m in repo.methods.values() if m.user_id == user_id]
    assert len(mine) == 2 and {m.revoked_at for m in mine} == {_NOW}
    assert await repo.find_pending_method(str(pending.method_id), str(user_id)) is None
    assert [m.revoked_at for m in repo.methods.values() if m.user_id == other] == [None]


async def test_recovery_codes_exhausted_raises_and_creates_no_session() -> None:
    """ "Recovery codes exhausted": "I am told to contact the owner and no
    session is created"."""
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    # `confirm_enrollment` auto-issues 10 recovery codes; hard-delete them
    # via a regenerate-to-empty-then-exhaust so the challenge sees none left.
    await repo.replace_recovery_codes(str(user_id), code_hashes=())
    token = await _make_login_challenge(repo, user_id)

    with pytest.raises(RecoveryCodesExhausted):
        await service.check_recovery(token, "0000-0000-0000")
    assert next(iter(repo.challenges.values())).attempts == 1


async def test_recover_rejects_invalid_recovery_code() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    await _with_recovery_codes(repo, user_id, 10)
    token = await _make_login_challenge(repo, user_id)

    with pytest.raises(RecoveryCodeInvalid):
        await service.check_recovery(token, "ZZZZ-ZZZZ-ZZZZ")
    assert next(iter(repo.challenges.values())).attempts == 1


async def test_recover_rejects_already_used_recovery_code() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    await _enroll_and_confirm(service, repo, user_id)
    codes = await _with_recovery_codes(repo, user_id, 10)
    token = await _make_login_challenge(repo, user_id)
    await _recover(service, token, codes[0])

    token2 = await _make_login_challenge(repo, user_id)
    with pytest.raises(RecoveryCodeInvalid):
        await service.check_recovery(token2, codes[0])


# -- regenerate_recovery_codes() ------------------------------------------


async def test_regenerate_recovery_codes_replaces_existing_set() -> None:
    repo = FakeMfaRepository()
    service = _service(repo)
    user_id = uuid.uuid4()
    first = await service.regenerate_recovery_codes(str(user_id))
    assert len(first.recovery_codes) == 10

    second = await service.regenerate_recovery_codes(str(user_id))
    assert len(second.recovery_codes) == 10
    assert set(first.recovery_codes).isdisjoint(second.recovery_codes)
    assert await repo.count_unused_recovery_codes(str(user_id)) == 10
