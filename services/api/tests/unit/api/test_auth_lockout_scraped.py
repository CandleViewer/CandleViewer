"""SR-125 `auth_lockouts_total` through the real `/auth/login` route (#2117): the lock applied by
the Nth wrong password is visible on a scraped registry, which is what the `AuthLockouts` alert
(`increase(auth_lockouts_total[10m]) > 0`) reads. Tests the HTTP -> counter -> exposition path;
the counter's own semantics are in `tests/unit/auth/test_login_lockout_metric.py`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI
from prometheus_client import CollectorRegistry

from candleviewer.api.auth import make_auth_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD, LoginService
from candleviewer.auth.metrics import export_auth_metrics
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)
_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_WRONG = {"identifier": "basiltt", "password": "wrong-password"}


class _Auth:
    is_active = True

    def __init__(self, login: LoginService) -> None:
        self.login = login


async def _client() -> httpx.AsyncClient:
    repo, hasher = FakeUserRepository(), Hasher(pepper="p")
    repo.add(make_user(password_hash=await hasher.hash("correct-horse-battery-staple")))
    login = LoginService(
        repo,
        hasher,
        per_ip_throttle=PerIpLoginThrottle(max_attempts=10_000),
        clock=lambda: _NOW,
    )
    app = FastAPI()
    auth: Any = _Auth(login)
    app.include_router(make_auth_router(auth, None, csrf=_CSRF_CODEC), prefix="")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _scraped(registry: CollectorRegistry) -> float:
    return float(registry.get_sample_value("auth_lockouts_total", {"env": "demo"}) or 0.0)


async def test_lockout_by_the_login_route_is_visible_on_the_scraped_registry() -> None:
    registry = CollectorRegistry()
    collector = export_auth_metrics(registry, env="demo")
    try:
        before = _scraped(registry)
        async with await _client() as client:
            for _ in range(LOCKOUT_THRESHOLD - 1):
                assert (await client.post("/auth/login", json=_WRONG)).status_code == 401
            assert _scraped(registry) == before
            assert (await client.post("/auth/login", json=_WRONG)).status_code == 401
            assert _scraped(registry) == before + 1
            assert (await client.post("/auth/login", json=_WRONG)).status_code == 423
            assert _scraped(registry) == before + 1  # a refused attempt is not a new lockout
    finally:
        collector.close()
