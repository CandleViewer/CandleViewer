"""E09-X02 credential / enumeration abuse cases (AC-CRED-*, AC-ENUM-*)."""

from __future__ import annotations

import gc
import json
import math
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
from argon2 import extract_parameters

from candleviewer.auth.errors import AccountDisabled, AccountLocked, InvalidCredentials
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD, LoginService
from candleviewer.auth.models import LoginRequest, UserStatus
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

from ._kit import Clock

PW = "correct-horse-battery-staple"
BAD = "wrong-guess"
#: Agreed threshold (E09-X02 SR-014): arms are "indistinguishable" when the median ratio is
#: within 1 +/- RATIO_TOL and the two-sided Mann-Whitney |z| < Z_CRIT (alpha ~= 0.001).
RATIO_TOL = 0.25
Z_CRIT = 3.29
SAMPLES = 500
WARMUP = 10


async def _world(
    *, throttle: int = 10**9, clock: Clock | None = None
) -> tuple[LoginService, FakeUserRepository, Hasher]:
    repo, hasher = FakeUserRepository(), Hasher(pepper="p")
    repo.add(make_user(password_hash=await hasher.hash(PW)))
    kw: dict[str, object] = {"per_ip_throttle": PerIpLoginThrottle(max_attempts=throttle)}
    if clock is not None:
        kw["clock"] = clock
    return LoginService(repo, hasher, **kw), repo, hasher  # type: ignore[arg-type]


async def test_ac_cred_01_hash_params_in_force_come_from_stored_hash_not_config() -> None:
    """Offline-guessing cost: read the Argon2id params from the persisted hash/algo_params
    (the DB columns), not from DEFAULT config, and require them to meet the policy floor."""
    _, repo, _ = await _world()
    (user,) = repo.users.values()
    parsed = extract_parameters(user.password_hash)
    assert user.password_hash.startswith("$argon2id$")
    stored = {"m": parsed.memory_cost, "t": parsed.time_cost, "p": parsed.parallelism}
    assert user.password_algo_params == stored  # DB column agrees with the real hash header
    assert stored["m"] >= 65536 and stored["t"] >= 3  # floor; weaker rows are a finding
    assert stored == DEFAULT_ARGON2_PARAMS


async def test_ac_cred_02_pepper_required_to_verify_captured_hash() -> None:
    _, repo, _ = await _world()
    (user,) = repo.users.values()
    assert await Hasher(pepper="").verify(user.password_hash, PW) is False
    assert await Hasher(pepper="p").verify(user.password_hash, PW) is True


async def test_ac_cred_03_stuffing_one_ip_throttled_without_argon2_amplification() -> None:
    svc, _, hasher = await _world(throttle=5)
    calls = 0
    real = hasher.verify

    async def counting(h: str, p: str) -> bool:
        nonlocal calls
        calls += 1
        return await real(h, p)

    hasher.verify = counting  # type: ignore[method-assign,assignment]
    hasher.verify_dummy = lambda p: counting("x", p)  # type: ignore[method-assign,assignment]
    for i in range(40):
        with pytest.raises(InvalidCredentials):
            await svc.login(LoginRequest(identifier=f"user{i}", password=BAD), source_ip="1.1.1.1")
    assert calls == 5  # remaining 35 rejected before any Argon2id work (U28)


async def test_ac_cred_04_stuffing_many_ips_hits_per_account_lockout() -> None:
    svc, repo, _ = await _world(clock=Clock())
    for i in range(LOCKOUT_THRESHOLD + 3):
        with pytest.raises((InvalidCredentials, AccountLocked)):
            await svc.login(
                LoginRequest(identifier="basiltt", password=BAD), source_ip=f"10.1.0.{i}"
            )
    (user,) = repo.users.values()
    assert user.locked_until is not None
    with pytest.raises(AccountLocked):  # even the right password is refused while locked
        await svc.login(LoginRequest(identifier="basiltt", password=PW), source_ip="10.9.9.9")


async def test_ac_cred_05_lockout_expires_on_fixed_clock() -> None:  # U27: DoS is time-bounded
    clock = Clock()
    svc, _, _ = await _world(clock=clock)
    for i in range(LOCKOUT_THRESHOLD):
        with pytest.raises(InvalidCredentials):
            await svc.login(
                LoginRequest(identifier="basiltt", password=BAD), source_ip=f"9.9.9.{i}"
            )
    with pytest.raises(AccountLocked):
        await svc.login(LoginRequest(identifier="basiltt", password=PW), source_ip="8.8.8.8")
    clock.advance(timedelta(minutes=16))
    await svc.login(LoginRequest(identifier="basiltt", password=PW), source_ip="8.8.8.8")


async def test_ac_enum_01_uniform_error_for_unknown_and_wrong_password() -> None:
    svc, _, _ = await _world()
    errs = []
    for ident, pw in (("ghost", "x"), ("basiltt", "x")):
        with pytest.raises(InvalidCredentials) as ei:
            await svc.login(LoginRequest(identifier=ident, password=pw), source_ip="2.2.2.2")
        errs.append((type(ei.value), str(ei.value)))
    assert errs[0] == errs[1]


async def test_ac_enum_02_disabled_user_revealed_only_after_correct_password() -> None:
    repo, hasher = FakeUserRepository(), Hasher(pepper="p")
    repo.add(make_user(password_hash=await hasher.hash(PW), status=UserStatus.DISABLED))
    svc = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=10**9))
    with pytest.raises(InvalidCredentials):
        await svc.login(LoginRequest(identifier="basiltt", password=BAD), source_ip="3.3.3.3")
    with pytest.raises(AccountDisabled):
        await svc.login(LoginRequest(identifier="basiltt", password=PW), source_ip="3.3.3.3")


def mann_whitney_z(a: list[float], b: list[float]) -> float:
    """Two-sided normal-approximation z for the Mann-Whitney U test (tie-corrected)."""
    n1, n2 = len(a), len(b)
    pooled = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = [0.0] * len(pooled)
    tie_term, i = 0.0, 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        t = j - i + 1
        tie_term += t**3 - t
        i = j + 1
    r1 = sum(r for r, (_, g) in zip(ranks, pooled, strict=True) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - tie_term / (n * (n - 1))))
    return (u1 - n1 * n2 / 2) / sigma


def test_mann_whitney_detects_a_shift_and_accepts_identical() -> None:
    base = [float(i) for i in range(100)]
    assert abs(mann_whitney_z(base, [v + 0.1 for v in base])) < Z_CRIT
    assert abs(mann_whitney_z(base, [v + 60 for v in base])) > Z_CRIT


@pytest.mark.perf
@pytest.mark.skipif(
    os.environ.get("CV_RUN_PERF") != "1",
    reason="wall-clock statistical test: opt in with CV_RUN_PERF=1 (CI lane has coverage)",
)
async def test_ac_enum_03_timing_unknown_vs_wrong_password_500_samples(  # SR-014 / U8
    tmp_path: Path,
) -> None:
    """Interleaved arms (same host/process), warm-up discarded, gc disabled in the timed region,
    ratio-of-medians + Mann-Whitney (not a mean compare). Threshold: RATIO_TOL / Z_CRIT above.
    The raw samples go to `tmp_path` only: #298 classes them SECRET (retained CI artefact or the
    private security folder, destroyed after closure), so they are never committed."""
    svc, repo, _ = await _world()
    arms: dict[str, list[float]] = {"unknown": [], "wrong": []}
    cases = (("unknown", "ghost"), ("wrong", "basiltt"))
    gc.collect()
    gc.disable()
    try:
        for i in range(SAMPLES + WARMUP):
            for name, ident in cases:
                t0 = time.perf_counter()
                with pytest.raises(InvalidCredentials):
                    await svc.login(
                        LoginRequest(identifier=ident, password=BAD),
                        source_ip=f"10.0.{i % 250}.1",
                    )
                dt = time.perf_counter() - t0
                if i >= WARMUP:
                    arms[name].append(dt)
            for uid in list(repo.users):  # keep lockout out of the measured path
                await repo.record_login_success(uid)
    finally:
        gc.enable()
    a, b = sorted(arms["unknown"]), sorted(arms["wrong"])
    mid_a, mid_b = a[len(a) // 2], b[len(b) // 2]
    ratio = mid_a / mid_b
    z = mann_whitney_z(arms["unknown"], arms["wrong"])
    assert len(a) == len(b) == SAMPLES
    raw = tmp_path / "ac-enum-03-samples.json"
    raw.write_text(json.dumps({"unit": "s", "warmup_dropped": WARMUP, **arms}), encoding="utf-8")
    print(f"AC-ENUM-03 evidence: n={SAMPLES}/arm ratio={ratio:.4f} mann_whitney_z={z:.3f}")
    print(f"AC-ENUM-03 medians: unknown={mid_a:.6f}s wrong={mid_b:.6f}s raw={raw}")
    assert 1 - RATIO_TOL < ratio < 1 + RATIO_TOL, f"median ratio {ratio:.3f}"
    assert abs(z) < Z_CRIT, f"Mann-Whitney z={z:.2f}"
