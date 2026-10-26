"""E09-S01 security test: unknown-user vs wrong-password timing distributions
(enumeration resistance), 1000 samples per arm as the ticket's Test plan requires."""

from __future__ import annotations

import os
import statistics
import time
from datetime import timedelta

import pytest

from candleviewer.auth.errors import InvalidCredentials
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.models import LoginRequest
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

SAMPLES = int(os.environ.get("CV_TIMING_SAMPLES", "1000"))


@pytest.mark.perf
@pytest.mark.asyncio
async def test_login_timing_unknown_vs_wrong_password_indistinguishable_over_1000_samples() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    repo.add(make_user(password_hash=await hasher.hash("correct-horse-battery-staple")))
    # No failure floor: this measures the two arms' own work, which a floor would pad to one
    # deadline; the floor has its own tests (test_login_failure_paths.py, the integration suite).
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=PerIpLoginThrottle(max_attempts=10**9),
        failure_floor=timedelta(0),
    )

    unknown: list[float] = []
    wrong: list[float] = []
    for i in range(SAMPLES):
        # Interleave the arms so machine-load drift affects both equally.
        for ident, pw, bucket in (
            ("no-such-user", "x", unknown),
            ("basiltt", "wrong", wrong),
        ):
            start = time.perf_counter()
            with pytest.raises(InvalidCredentials):
                await service.login(
                    LoginRequest(identifier=ident, password=pw), source_ip=f"10.0.{i % 250}.1"
                )
            bucket.append(time.perf_counter() - start)
            # Reset lockout state outside the timed region so every sample hits the verify path.
            for uid in list(repo.users):
                await repo.record_login_success(uid)

    med_unknown = statistics.median(unknown)
    med_wrong = statistics.median(wrong)
    # Medians are robust to scheduler outliers; both arms run one Argon2id verify.
    assert med_unknown == pytest.approx(med_wrong, rel=0.15)
    # A distinguisher must not separate the distributions: the p10 of each arm
    # must overlap the other's median (no fast-fail tail on either side).
    q = lambda xs, p: statistics.quantiles(xs, n=100)[p - 1]  # noqa: E731
    assert q(unknown, 10) <= med_wrong and q(wrong, 10) <= med_unknown
