"""Integration (#4648): against real Postgres 16, a failed sign-in for an unknown identifier and
one for a wrong password each return no sooner than `LOGIN_FAILURE_FLOOR` after the attempt
started, with the real Argon2id hasher and the store's failure write behind them.

Each failure either requested the wait (the real wait, recorded) or was counted as not held
(`auth_login_failure_floor_missed_total`), so a service without the floor fails here even on a
host slow enough to pass the duration check alone. The locked and disabled refusals are held by
the same code; their cases are the fake-clock ones in
`tests/unit/auth/test_login_failure_paths.py`."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import InvalidCredentials
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOGIN_FAILURE_FLOOR, LoginService
from candleviewer.auth.models import LoginRequest, UserRecord
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from scripts.seed_fixture_user import seed
from tests.integration import _refused

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head, on loopback
_NOW = datetime.now(UTC).replace(microsecond=0)
_ROUNDS = 3
_GUESS = "a-wrong-guess"


def _missed() -> float:
    return float(REGISTRY.get_sample_value("auth_login_failure_floor_missed_total") or 0.0)


def _rec(model: Any) -> Callable[..., Any]:
    return lambda **f: model.model_validate(f)


async def test_login_both_failure_arms_take_at_least_the_floor(pg_dsn: str) -> None:
    await seed(pg_dsn, "floor-user", "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    waits: list[float] = []

    async def recorded_wait(delay: float) -> None:
        waits.append(delay)
        await asyncio.sleep(delay)

    service = LoginService(
        users, Hasher(), per_ip_throttle=PerIpLoginThrottle(max_attempts=10**9), sleep=recorded_wait
    )
    missed_before = _missed()
    took: dict[str, list[float]] = {"ghost-user": [], "floor-user": []}
    try:
        for _ in range(_ROUNDS):  # below the lockout threshold: every round is a plain failure
            for identifier, samples in took.items():
                started = time.monotonic()
                with pytest.raises(InvalidCredentials):
                    await service.login(
                        LoginRequest(identifier=identifier, password=_GUESS),
                        source_ip="10.0.0.1",
                    )
                samples.append(time.monotonic() - started)
        found = await users.find_by_identifier("floor-user")
    finally:
        await rel.dispose()

    floor = LOGIN_FAILURE_FLOOR.total_seconds()
    assert all(d >= floor for samples in took.values() for d in samples), took
    assert found is not None and found.failed_login_count == _ROUNDS  # each write still landed
    assert len(waits) + (_missed() - missed_before) == 2 * _ROUNDS  # held, or counted
