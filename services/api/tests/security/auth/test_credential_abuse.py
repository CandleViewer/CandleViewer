"""E09-X02 credential / enumeration abuse cases (AC-CRED-*, AC-ENUM-*)."""

from __future__ import annotations

import gc
import json
import math
import random
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
#: within 1 +/- RATIO_TOL and the two-sided Mann-Whitney |z| < Z_CRIT (alpha ~= 0.001); the
#: paired Wilcoxon signed-rank |z| on the interleaved pairs is held to the same Z_CRIT (#4540).
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


def wilcoxon_signed_rank_z(a: list[float], b: list[float]) -> float:
    """Normal-approximation z of the Wilcoxon signed-rank test on the pairs (a[k], b[k]).

    Zero differences are dropped (Wilcoxon's rule); tied |differences| get mid-ranks and the
    variance its tie correction. Positive when a tends to exceed b in the same pair."""
    d = [x - y for x, y in zip(a, b, strict=True) if x != y]
    n = len(d)
    if n == 0:
        return 0.0
    order = sorted(range(n), key=lambda k: abs(d[k]))
    ranks = [0.0] * n
    tie_term, i = 0.0, 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        t = j - i + 1
        tie_term += t**3 - t
        i = j + 1
    w_plus = sum(r for r, v in zip(ranks, d, strict=True) if v > 0)
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24 - tie_term / 48)
    return (w_plus - n * (n + 1) / 4) / sigma


def test_wilcoxon_signed_rank_z_on_known_inputs() -> None:
    # d = 1..10, all positive: W+ = 55, mean 27.5, sigma = sqrt(96.25) -> z = 2.8031.
    a = [float(k) for k in range(1, 11)]
    assert wilcoxon_signed_rank_z(a, [0.0] * 10) == pytest.approx(2.8031, abs=1e-4)
    assert wilcoxon_signed_rank_z([0.0] * 10, a) == pytest.approx(-2.8031, abs=1e-4)
    # d = (1, -2, 3, -4, 5): W+ = 9, mean 7.5, sigma = sqrt(13.75) -> z = 0.4045.
    signed = [1.0, -2.0, 3.0, -4.0, 5.0]
    assert wilcoxon_signed_rank_z(signed, [0.0] * 5) == pytest.approx(0.4045, abs=1e-4)
    # Ties |d| = (1, 1, 2), signs (+, -, +): mid-ranks 1.5, 1.5, 3 -> W+ = 4.5, mean 3,
    # variance 3.5 - (2**3 - 2) / 48 = 3.375 -> z = 0.8165; the zero pair is dropped.
    assert wilcoxon_signed_rank_z([1.0, -1.0, 2.0, 7.0], [0.0, 0.0, 0.0, 7.0]) == pytest.approx(
        0.8165, abs=1e-4
    )
    assert wilcoxon_signed_rank_z([1.0, 2.0], [1.0, 2.0]) == 0.0


def _first_arm_schedule() -> list[str]:
    """Which arm goes first in each iteration: the warm-up alternates, the measured pairs are a
    fixed (seeded) shuffle of exactly SAMPLES/2 unknown-first and SAMPLES/2 wrong-first."""
    warm = ["unknown" if i % 2 == 0 else "wrong" for i in range(WARMUP)]
    measured = ["unknown"] * (SAMPLES // 2) + ["wrong"] * (SAMPLES // 2)
    random.Random(4540).shuffle(measured)  # noqa: S311 - fixed seed, reproducible schedule
    return warm + measured


_FIRST_ARM = _first_arm_schedule()


def pair_order(i: int) -> tuple[str, str]:
    """The arms' order in iteration `i`. Each arm goes first in exactly half of the measured
    pairs (so a first-call cost cancels exactly), in a seeded random order rather than strict
    alternation (which would give the paired differences positive lag-1 autocorrelation under
    autocorrelated runner noise)."""
    first = _FIRST_ARM[i]
    return (first, "wrong" if first == "unknown" else "unknown")


def test_pair_order_puts_each_arm_first_in_exactly_half_of_the_measured_pairs() -> None:
    assert len(_FIRST_ARM) == WARMUP + SAMPLES
    firsts = [pair_order(i)[0] for i in range(WARMUP, WARMUP + SAMPLES)]
    assert firsts.count("unknown") == firsts.count("wrong") == SAMPLES // 2
    warm = [pair_order(i)[0] for i in range(WARMUP)]
    assert warm.count("unknown") == warm.count("wrong") == WARMUP // 2
    assert all(sorted(pair_order(i)) == ["unknown", "wrong"] for i in range(WARMUP + SAMPLES))
    assert firsts != ["unknown", "wrong"] * (SAMPLES // 2)  # not strict alternation
    assert _first_arm_schedule() == _FIRST_ARM  # seeded: reproducible


def timing_failures(unknown: list[float], wrong: list[float]) -> tuple[str, list[str]]:
    """The evidence line and the failed checks for two paired arms (index k = iteration k)."""
    a, b = sorted(unknown), sorted(wrong)
    ratio = a[len(a) // 2] / b[len(b) // 2]
    z = mann_whitney_z(unknown, wrong)
    pz = wilcoxon_signed_rank_z(unknown, wrong)
    line = (
        f"ratio={ratio:.4f} median_unknown={a[len(a) // 2]:.6f}s median_wrong={b[len(b) // 2]:.6f}s"
        f" mann_whitney_z={z:.3f} paired_wilcoxon_z={pz:.3f}"
    )
    failures = []
    if not 1 - RATIO_TOL < ratio < 1 + RATIO_TOL:
        failures.append(f"median ratio {ratio:.3f}")
    if not abs(z) < Z_CRIT:
        failures.append(f"Mann-Whitney z={z:.2f}")
    if not abs(pz) < Z_CRIT:
        failures.append(f"paired Wilcoxon z={pz:.2f}")
    return line, failures


def _shuffled(n: int, seed: int) -> list[float]:
    values = [float(k) for k in range(n)]
    random.Random(seed).shuffle(values)  # noqa: S311 - seeded, reproducible inputs
    return values


def test_timing_failures_flags_a_consistent_in_pair_shift_the_unpaired_checks_miss() -> None:
    unknown = _shuffled(SAMPLES, 1)
    wrong = [v + 0.5 for v in unknown]  # wrong slower by 0.5 in every pair, same order
    _, failures = timing_failures(unknown, wrong)
    assert len(failures) == 1
    assert failures[0].startswith("paired Wilcoxon z=-")
    balanced = [v + (0.5 if k % 2 else -0.5) for k, v in enumerate(unknown)]
    assert timing_failures(unknown, balanced)[1] == []


def test_timing_failures_pairs_by_index_not_by_rank_and_takes_medians_of_sorted_arms() -> None:
    unknown = _shuffled(SAMPLES, 1)
    wrong = [(v + 1) % SAMPLES for v in unknown]  # same multiset as `unknown`
    line, failures = timing_failures(unknown, wrong)
    # Paired by index the wrong arm is faster in 499 of 500 pairs; paired on the sorted arms
    # the differences would all be zero and nothing would be flagged.
    assert len(failures) == 1
    assert failures[0].startswith("paired Wilcoxon z=-")  # 499 small negative d, one big positive
    assert wilcoxon_signed_rank_z(unknown, wrong) < -Z_CRIT
    # Medians come from the sorted arms (an unsorted `arm[len // 2]` would be an arbitrary value).
    mid = f"{float(SAMPLES // 2):.6f}"
    assert f"median_unknown={mid}s median_wrong={mid}s" in line


def test_timing_failures_ratio_uses_the_medians_of_the_sorted_arms() -> None:
    unknown = _shuffled(SAMPLES, 1)
    wrong = [2 * v for v in _shuffled(SAMPLES, 2)]  # a different order: only sorting gives 0.5
    _, failures = timing_failures(unknown, wrong)
    assert "median ratio 0.500" in failures


@pytest.mark.perf
async def test_ac_enum_03_timing_unknown_vs_wrong_password_500_samples(  # SR-014 / U8
    tmp_path: Path,
) -> None:
    """Interleaved arms (same host/process), each pair's order a seeded balanced shuffle
    (`pair_order`, #4540), warm-up discarded, gc disabled in the timed region; ratio-of-medians +
    Mann-Whitney + the Wilcoxon signed-rank z on the pairs (not a mean compare). Thresholds:
    RATIO_TOL / Z_CRIT above.
    The raw samples go to `tmp_path` only: #298 classes them SECRET (retained CI artefact or the
    private security folder, destroyed after closure), so they are never committed."""
    svc, repo, _ = await _world()
    arms: dict[str, list[float]] = {"unknown": [], "wrong": []}
    idents = {"unknown": "ghost", "wrong": "basiltt"}
    gc.collect()
    gc.disable()
    try:
        for i in range(SAMPLES + WARMUP):
            for name in pair_order(i):
                ident = idents[name]
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
    assert len(arms["unknown"]) == len(arms["wrong"]) == SAMPLES
    first = sum(pair_order(i)[0] == "unknown" for i in range(WARMUP, WARMUP + SAMPLES))
    raw = tmp_path / "ac-enum-03-samples.json"
    raw.write_text(json.dumps({"unit": "s", "warmup_dropped": WARMUP, **arms}), encoding="utf-8")
    line, failures = timing_failures(arms["unknown"], arms["wrong"])
    print(
        f"AC-ENUM-03 evidence: n={SAMPLES}/arm {line}"
        f" order=unknown-first:{first}/wrong-first:{SAMPLES - first} raw={raw}"
    )
    assert first == SAMPLES - first, "arm order not counterbalanced"
    assert failures == [], "; ".join(failures)
