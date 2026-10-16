"""E09-X02 MFA abuse cases (abuse-cases/e09-auth.md: AC-MFA-*). Fixed clock, no sleep."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from candleviewer.auth.errors import (
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    RecoveryCodeInvalid,
)
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP
from candleviewer.auth.models import MfaMethodKind, MfaVerifyRequest

from ._kit import MfaKit


def _req(token: str, code: str) -> MfaVerifyRequest:
    return MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code)


async def _recover(kit: MfaKit, token: str, code: str) -> None:
    """Both halves of a recovery sign-in, as `POST /auth/mfa/recovery` runs them (#2344)."""
    await kit.svc.complete_recovery(await kit.svc.check_recovery(token, code))


async def test_ac_mfa_01_totp_replay_inside_skew_window_rejected() -> None:  # U11 / SR-021
    kit, user = MfaKit(), uuid.uuid4()
    seed = await kit.enrol(user)
    code = kit.code(seed)
    await kit.svc.verify(_req(await kit.challenge(user, "t1"), code))
    for offset_token in ("t2", "t3"):  # same code, fresh challenges, same step
        with pytest.raises(MfaCodeReused):
            await kit.svc.verify(_req(await kit.challenge(user, offset_token), code))


async def test_ac_mfa_01b_older_step_than_last_accepted_rejected() -> None:  # U11
    kit, user = MfaKit(), uuid.uuid4()
    seed = await kit.enrol(user)
    await kit.svc.verify(_req(await kit.challenge(user, "t1"), kit.code(seed, +1)))
    with pytest.raises(MfaCodeReused):  # step-1 is inside skew but older than accepted +1
        await kit.svc.verify(_req(await kit.challenge(user, "t2"), kit.code(seed, -1)))


async def test_ac_mfa_02_six_digit_bruteforce_locked_at_cap() -> None:  # SR-015 / U2
    kit, user = MfaKit(), uuid.uuid4()
    seed = await kit.enrol(user)
    token = await kit.challenge(user, "brute")
    valid = {kit.code(seed, o) for o in (-1, 0, 1)}
    guesses = [f"{i:06d}" for i in range(1000) if f"{i:06d}" not in valid]
    seen = 0
    with pytest.raises(MfaChallengeLocked):
        for g in guesses:
            seen += 1
            try:
                await kit.svc.verify(_req(token, g))
            except MfaCodeInvalid:
                continue
    assert seen == CHALLENGE_ATTEMPT_CAP
    # Even the correct code is now refused: the lock is on the challenge.
    with pytest.raises(MfaChallengeLocked):
        await kit.svc.verify(_req(token, kit.code(seed)))


async def test_ac_mfa_03_recovery_code_single_use() -> None:  # SR-022 / U9
    kit, user = MfaKit(), uuid.uuid4()
    await kit.enrol(user)
    codes = (await kit.svc.regenerate_recovery_codes(str(user))).recovery_codes
    await _recover(kit, await kit.challenge(user, "r1"), codes[0])
    with pytest.raises(RecoveryCodeInvalid):
        await _recover(kit, await kit.challenge(user, "r2"), codes[0])


async def test_ac_mfa_04_recovery_code_dead_after_regeneration() -> None:  # SR-022
    kit, user = MfaKit(), uuid.uuid4()
    await kit.enrol(user)
    old = (await kit.svc.regenerate_recovery_codes(str(user))).recovery_codes
    new = (await kit.svc.regenerate_recovery_codes(str(user))).recovery_codes
    assert set(old).isdisjoint(new)
    with pytest.raises(RecoveryCodeInvalid):
        await _recover(kit, await kit.challenge(user, "r1"), old[0])
    await _recover(kit, await kit.challenge(user, "r2"), new[0])


async def test_ac_mfa_05_concurrent_verify_one_challenge_mints_once() -> None:  # race
    kit, user = MfaKit(), uuid.uuid4()
    seed = await kit.enrol(user)
    token = await kit.challenge(user, "race")
    code = kit.code(seed)
    results = await asyncio.gather(
        *(kit.svc.verify(_req(token, code)) for _ in range(8)), return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    assert len(ok) == 1
    assert all(isinstance(r, (MfaCodeReused, MfaChallengeInvalid)) for r in results if r not in ok)


async def test_ac_mfa_05b_concurrent_recovery_code_consumed_once() -> None:  # race / SR-022
    kit, user = MfaKit(), uuid.uuid4()
    await kit.enrol(user)
    codes = (await kit.svc.regenerate_recovery_codes(str(user))).recovery_codes
    token = await kit.challenge(user, "race-rc")
    results = await asyncio.gather(
        *(_recover(kit, token, codes[0]) for _ in range(8)), return_exceptions=True
    )
    assert sum(1 for r in results if not isinstance(r, BaseException)) == 1


async def test_ac_mfa_06_challenge_for_other_user_cannot_use_my_code() -> None:  # cross-user
    kit = MfaKit()
    victim, attacker = uuid.uuid4(), uuid.uuid4()
    await kit.enrol(victim)
    attacker_seed = await kit.enrol(attacker)
    token = await kit.challenge(victim, "victim-challenge")
    # Attacker's valid code, victim's challenge: verified against the victim's methods only.
    with pytest.raises(MfaCodeInvalid):
        await kit.svc.verify(_req(token, kit.code(attacker_seed)))


async def test_ac_mfa_07_unknown_and_expired_challenge_uniform_error() -> None:
    kit, user = MfaKit(), uuid.uuid4()
    seed = await kit.enrol(user)
    token = await kit.challenge(user, "exp")
    with pytest.raises(MfaChallengeInvalid):
        await kit.svc.verify(_req("never-issued", kit.code(seed)))
    from datetime import timedelta

    kit.clock.advance(timedelta(minutes=6))
    with pytest.raises(MfaChallengeInvalid):
        await kit.svc.verify(_req(token, kit.code(seed)))
