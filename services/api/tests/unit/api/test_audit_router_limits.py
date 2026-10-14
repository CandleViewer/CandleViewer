"""Route-level tests for the `/admin/audit` limiter, time budget and input rules (#2392)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_limiter import AuditQueryLimiter
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditPage
from tests.unit.api.test_audit_router import (
    _FakeAuditService,
    _FakeResolver,
    _owner,
)


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def _client(
    principal: AuditPrincipal,
    service: _FakeAuditService | None = None,
    *,
    limiter: AuditQueryLimiter | None = None,
) -> tuple[TestClient, _FakeAuditService]:
    svc = service or _FakeAuditService()
    app = FastAPI()
    app.include_router(
        make_audit_router(svc, _FakeResolver(principal), limiter=limiter, query_timeout_ms=1234)
    )
    return TestClient(app), svc


def test_rate_and_concurrency_limits_return_429_with_retry_after() -> None:
    clock = _Clock()
    lim = AuditQueryLimiter(rate_per_minute=2, max_concurrent=1, clock=clock)
    client, svc = _client(_owner(), limiter=lim)
    assert client.get("/admin/audit").status_code == 200
    assert client.get("/admin/audit").status_code == 200
    r = client.get("/admin/audit")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert len(svc.query_service.query_calls) == 2
    clock.now += 61
    held = lim.acquire(next(iter(lim._users)))
    assert client.get("/admin/audit").status_code == 429  # concurrency slot taken
    held.release()
    assert client.get("/admin/audit").status_code == 200


def test_lease_released_when_query_raises() -> None:
    lim = AuditQueryLimiter(max_concurrent=1)
    svc = _FakeAuditService()

    async def boom(**_: Any) -> AuditPage:
        raise RuntimeError("x")

    svc.query_service.query = boom  # type: ignore[method-assign,assignment]  # test double
    client, _ = _client(_owner(), svc, limiter=lim)
    client = TestClient(client.app, raise_server_exceptions=False)
    assert client.get("/admin/audit").status_code == 500
    assert all(s.inflight == 0 for s in lim._users.values())


def test_statement_timeout_maps_to_503_store_unavailable() -> None:
    svc = _FakeAuditService()

    async def slow(**kw: Any) -> AuditPage:
        assert kw["timeout_ms"] == 1234
        raise TimeoutError

    svc.query_service.query = slow  # type: ignore[method-assign,assignment]  # test double
    client, _ = _client(_owner(), svc)
    r = client.get("/admin/audit")
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"
    assert r.headers["Retry-After"] == "1"


def test_validation_limits_and_ip() -> None:
    client, svc = _client(_owner())
    assert client.get("/admin/audit", params={"limit": 501}).status_code == 422
    assert client.get("/admin/audit", params={"limit": 0}).status_code == 422
    assert client.get("/admin/audit", params={"ip": "10.0.0.0/8"}).status_code == 422
    assert client.get("/admin/audit", params={"ip": "nope"}).status_code == 422
    assert client.get("/admin/audit", params={"ip": "::1"}).status_code == 200
    assert svc.query_service.query_calls[-1]["limit"] == 100
