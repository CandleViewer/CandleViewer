"""#4663: `POST /auth/login` when sign-in verification is at capacity.

The attempt is refused at once: `429` `rate_limited` with `Retry-After` and
`retry_after_seconds` (the contract's `RateLimited` response), one `auth.login_failed` row with
outcome `denied` and reason `verify_busy`, and one `auth_login_verify_refused_total`. It is not a
password failure (`auth_login_failures_total` does not move). Deltas on the process-default
registry, where the module-level counters live.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from fastapi import FastAPI
from prometheus_client import REGISTRY

from candleviewer.api.auth import make_auth_router
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.login_service import LOGIN_BUSY_RETRY_AFTER_S, LoginService
from candleviewer.auth.throttle import VerifyAdmission
from tests.unit.api._fakes import AuditService
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_BODY = {"identifier": "basiltt", "password": "any-guess-at-all"}  # never checked


class _Auth:
    is_active = mfa_is_active = True
    sessions_is_active = False

    def __init__(self, login: LoginService) -> None:
        self.login = login


def _full_service() -> LoginService:
    repo = FakeUserRepository()
    repo.add(make_user(password_hash=DUMMY_PASSWORD_HASH))
    admission = VerifyAdmission(1)
    assert admission.try_enter()  # the one place is taken by an attempt in flight
    return LoginService(
        repo,
        Hasher(pepper="p"),
        clock=lambda: _NOW,
        failure_floor=timedelta(0),
        admission=admission,
    )


def _client(login: LoginService, audit: AuditService) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(
        make_auth_router(cast(Any, _Auth(login)), audit, csrf=CsrfCodec(b"\x05" * 32))
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return float(REGISTRY.get_sample_value(name, labels or {}) or 0.0)


async def test_login_at_capacity_is_429_rate_limited_with_retry_after() -> None:
    audit = AuditService()
    async with _client(_full_service(), audit) as client:
        response = await client.post("/auth/login", json=_BODY)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(LOGIN_BUSY_RETRY_AFTER_S) == "1"
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "rate_limited"
    assert body["type"] == "https://candleviewer.local/errors/rate_limited"
    assert body["status"] == 429 and body["retry_after_seconds"] == 1


async def test_login_at_capacity_is_audited_and_counted_but_not_a_password_failure() -> None:
    audit = AuditService()
    refused = _sample("auth_login_verify_refused_total")
    failed = _sample("auth_login_failures_total", {"method": "password"})
    async with _client(_full_service(), audit) as client:
        await client.post("/auth/login", json=_BODY)

    (row,) = audit.writer.of("auth.login_failed")
    assert row["outcome"] is AuditOutcome.DENIED and row["reason"] == "verify_busy"
    assert row["actor_label"] != _BODY["identifier"]  # the redacted label, as every failure
    assert _sample("auth_login_verify_refused_total") - refused == 1
    assert _sample("auth_login_failures_total", {"method": "password"}) == failed
