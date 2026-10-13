"""SR-015/SR-016: audit records emitted by `/auth/login` under concurrent failures.

Documented behaviour: `auth.account_locked` is emitted once per *refused* attempt (HTTP 423,
account already locked at request start). The request whose failure trips the lock returns
401 and is audited as `auth.login_failed`; so a burst of exactly LOCKOUT_THRESHOLD concurrent
wrong passwords yields zero `account_locked` records, and every later attempt yields one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI

from candleviewer.api.auth import make_auth_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD, LoginService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)  # SR-041 (#2090): routers require a codec

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_BODY = {"identifier": "basiltt", "password": "wrong-password"}


class _Writer:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def emit(self, action: str, **_: Any) -> None:
        self.actions.append(action)


class _Audit:
    is_active = True

    def __init__(self) -> None:
        self.writer = _Writer()


class _Auth:
    is_active = True

    def __init__(self, login: LoginService) -> None:
        self.login = login


async def _client() -> tuple[httpx.AsyncClient, _Audit, FakeUserRepository]:
    repo, hasher = FakeUserRepository(), Hasher(pepper="p")
    repo.add(make_user(password_hash=await hasher.hash("correct-horse-battery-staple")))
    login = LoginService(
        repo,
        hasher,
        per_ip_throttle=PerIpLoginThrottle(max_attempts=10_000),
        clock=lambda: _NOW,
    )
    audit = _Audit()
    app = FastAPI()
    app.include_router(make_auth_router(_Auth(login), audit, csrf=_CSRF_CODEC), prefix="")  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://t"), audit, repo


async def test_concurrent_burst_to_threshold_audits_failures_then_locked_attempts_each() -> None:
    client, audit, repo = await _client()
    async with client:
        burst = await asyncio.gather(
            *(client.post("/auth/login", json=_BODY) for _ in range(LOCKOUT_THRESHOLD))
        )
        assert {r.status_code for r in burst} == {401}
        (user,) = repo.users.values()
        assert user.failed_login_count == LOCKOUT_THRESHOLD and user.locked_until is not None
        assert audit.writer.actions.count("auth.login_failed") == LOCKOUT_THRESHOLD
        assert audit.writer.actions.count("auth.account_locked") == 0

        after = await asyncio.gather(*(client.post("/auth/login", json=_BODY) for _ in range(3)))
        assert {r.status_code for r in after} == {423}
        assert audit.writer.actions.count("auth.account_locked") == 3
        assert user.failed_login_count == LOCKOUT_THRESHOLD  # refused attempts don't count
