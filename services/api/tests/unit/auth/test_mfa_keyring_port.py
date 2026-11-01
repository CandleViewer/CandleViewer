"""MFA on the `MfaKeyring` port (#2152 S5a, BQ-3, BQ-6): every seed a verifier opens is zeroed once
its code is checked, a recovery code is looked up by every candidate digest in one query, a new
code stores the first, and the env-backed keyring keeps today's ref and never shows a key. Fakes
only; integer-built keys (C-13.5)."""

from __future__ import annotations

import copy
import pickle
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from candleviewer.auth import mfa_service, step_up
from candleviewer.auth.env_keyring import EnvMfaKeyring
from candleviewer.auth.errors import MfaCodeInvalid, RecoveryCodeInvalid
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.mfa_service import MfaService, _hash_token
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, MfaVerifyRequest
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.auth.auth_fakes import FakeUserRepository, no_wait
from tests.unit.auth.mfa_fakes import FakeMfaKeyring, FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
_KILLED = (AssertionError, pytest.fail.Exception)


class _TwoDigests(FakeMfaKeyring):
    """A keyring whose codes have two candidate digests, as an imported one's do (BQ-3)."""

    async def recovery_code_digests(self, code: str, user_id: uuid.UUID) -> tuple[str, ...]:
        (legacy,) = await super().recovery_code_digests(code, user_id)
        return f"{user_id.hex}{legacy}"[:64], legacy


class _CountingRepo(FakeMfaRepository):
    def __init__(self) -> None:
        super().__init__()
        self.lookups: list[tuple[str, ...]] = []

    async def find_unused_recovery_code(self, user_id: str, *, code_hashes: Any) -> str | None:
        self.lookups.append(tuple(code_hashes))
        return await super().find_unused_recovery_code(user_id, code_hashes=code_hashes)


async def _enrolled(
    keyring: FakeMfaKeyring, repo: FakeMfaRepository
) -> tuple[MfaService, str, bytes, tuple[str, ...]]:
    svc = MfaService(repo, keyring, clock=lambda: _NOW, sleep=no_wait)
    user = str(uuid.uuid4())
    res = await svc.enroll(
        user, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
    )
    seed = keyring.decrypt(repo.methods[str(res.method_id)].secret_enc or b"")
    step = time_step_for(_NOW.timestamp()) - 1
    _, codes = await svc.confirm_enrollment(
        user, method_id=str(res.method_id), code=generate_code(seed, step)
    )
    return svc, user, seed, codes


async def _login_token(repo: FakeMfaRepository, user: str) -> str:
    token = f"t-{uuid.uuid4()}"
    expires = _NOW + timedelta(minutes=5)
    await repo.create_challenge(
        user, purpose="login", mfa_token_hash=_hash_token(token), expires_at=expires
    )
    return token


def _all_zero(keyring: FakeMfaKeyring) -> bool:
    return bool(keyring.opened) and all(not any(seed) for seed in keyring.opened)


@pytest.mark.parametrize("right", [True, False], ids=["right_code", "wrong_code"])
async def test_the_login_verifier_zeroes_every_seed_it_opened(right: bool) -> None:
    """Two confirmed methods, and the right code is the second's, so the call opens both seeds:
    each is zeroed once the code is checked, not only the first."""
    keyring, repo = FakeMfaKeyring(), FakeMfaRepository()
    svc, user, _, _ = await _enrolled(keyring, repo)
    assert _all_zero(keyring)  # the enrolment's check zeroed its seed too
    second = bytes(range(100, 120))  # a second factor's seed, integer-built (C-13.5)
    method = await repo.create_pending_method(
        user, secret_enc=keyring.encrypt(second), secret_key_ref=keyring.key_ref, label="b"
    )
    await repo.seed_confirmed(str(method.id), now=_NOW)
    keyring.opened.clear()
    code = generate_code(second, time_step_for(_NOW.timestamp())) if right else "000000"
    request = MfaVerifyRequest(
        mfa_token=await _login_token(repo, user), method=MfaMethodKind.TOTP, code=code
    )
    if right:
        await svc.verify(request)
    else:
        with pytest.raises(MfaCodeInvalid):
            await svc.verify(request)
    assert len(keyring.opened) == 2 and _all_zero(keyring)


@pytest.mark.parametrize("right", [True, False], ids=["right_code", "wrong_code"])
async def test_the_step_up_verifier_zeroes_every_seed_it_opened(right: bool) -> None:
    keyring, repo = FakeMfaKeyring(), FakeMfaRepository()
    _, user, seed, _ = await _enrolled(keyring, repo)
    svc = StepUpService(
        repo, FakeSessionRepository(), keyring, FakeUserRepository(), Hasher(),
        clock=lambda: _NOW, sleep=no_wait,
    )  # fmt: skip
    keyring.opened.clear()
    code = generate_code(seed, time_step_for(_NOW.timestamp())) if right else "000000"
    assert await svc._verify(user, code, _NOW) is right
    assert len(keyring.opened) == 1 and _all_zero(keyring)


async def test_a_recovery_code_is_found_by_any_candidate_digest_in_one_lookup() -> None:
    """BQ-3: every candidate digest first, then one query; a new code stores the first."""
    keyring, repo = _TwoDigests(), _CountingRepo()
    svc, user, _, codes = await _enrolled(keyring, repo)
    stored = {row["code_hash"] for row in repo.recovery_codes.values()}
    first = {(await keyring.recovery_code_digests(c, uuid.UUID(user)))[0] for c in codes}
    assert stored == first
    legacy = next(iter(repo.recovery_codes.values()))
    legacy["code_hash"] = (await keyring.recovery_code_digests(codes[0], uuid.UUID(user)))[1]
    check = await svc.check_recovery(await _login_token(repo, user), codes[0])
    assert str(check.user_id) == user and len(repo.lookups) == 1 and len(repo.lookups[0]) == 2
    with pytest.raises(RecoveryCodeInvalid):
        await svc.check_recovery(await _login_token(repo, user), "WRONG-CODE")
    assert len(repo.lookups) == 2


async def test_the_env_keyring_keeps_today_s_ref_and_shows_no_key() -> None:
    keyring = EnvMfaKeyring(bytes(range(32)), bytes(range(32, 64)))
    blob, ref = await keyring.seal_totp_seed(b"s" * 20, uuid.UUID(int=1))
    assert (
        ref == "local-dev-v1"
        and await keyring.available(ref)
        and not await keyring.available("akey:x")
    )
    assert repr(keyring) == str(keyring) == "EnvMfaKeyring(***)"
    for op in (pickle.dumps, copy.copy):
        with pytest.raises(TypeError):
            op(keyring)
    assert bytes(await keyring.open_totp_seed(blob, "any ref", uuid.UUID(int=2))) == b"s" * 20


# --- Seeded mutants (repo convention, `tests/unit/credentials_m2/test_mutations.py`) -----------


def _not_zeroed(seeds: list[bytearray]) -> None:
    return None  # the verifier leaves the seed in memory


MUTANTS = {
    "login_seed_not_zeroed": (mfa_service, test_the_login_verifier_zeroes_every_seed_it_opened),
    "step_up_seed_not_zeroed": (step_up, test_the_step_up_verifier_zeroes_every_seed_it_opened),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_mutant_killed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    module, oracle = MUTANTS[name]
    monkeypatch.setattr(module, "zero_seeds", _not_zeroed)
    with pytest.raises(_KILLED):
        await oracle(True)
