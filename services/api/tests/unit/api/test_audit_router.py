"""Unit tests for `candleviewer.api.audit.make_audit_router` (QA defect
#1596: "No HTTP router wired for /admin/audit, /admin/audit/verify,
/admin/audit/export"). Regression: `grep -rn 'APIRouter'
services/api/candleviewer/audit` found nothing before this fix, and none of
these routes existed on `create_app()`'s FastAPI instance."""

from __future__ import annotations

import asyncio
import hashlib
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from pydantic import ValidationError

from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_budget import (
    FLUSH_REASON,
    SUMMARY_REASON,
    AuditRecordBudget,
    BudgetActor,
)
from candleviewer.api.audit_limiter import AuditQueryLimiter
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.cursor import AuditCursor, encode_cursor
from candleviewer.audit.hashing import ChainHasher, ChainHasherBusy
from candleviewer.audit.models import (
    AuditEntry,
    AuditOutcome,
    AuditPage,
    AuditPageMeta,
    AuditQueryRequest,
    Severity,
    VerifyResult,
)
from candleviewer.audit.query import AuditQueryService
from candleviewer.observability.audit_query_metrics import FILTER_CLASSES
from candleviewer.settings import Settings
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadBusy, AuditReadFailed

_TS = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)


class _FakeQuery:
    def __init__(self) -> None:
        self.query_calls: list[dict[str, Any]] = []
        self.verify_calls: list[dict[str, Any]] = []

    async def query(self, **kwargs: Any) -> AuditPage:
        # Mirrors `AuditQueryService.query`'s own validation (QA defect
        # #1596 review): a naive datetime or `from_ts > to_ts` must raise
        # `ValidationError`, not be accepted silently by the fake.
        paging = ("timeout_ms", "restrict_to_actor", "after", "owner", "raw")
        AuditQueryRequest.model_validate({k: v for k, v in kwargs.items() if k not in paging})
        self.query_calls.append(kwargs)
        return AuditPage(items=[], chain_verified=True)

    async def verify(self, **kwargs: Any) -> VerifyResult:
        self.verify_calls.append(kwargs)
        return VerifyResult(
            verified=True, entries_checked=0, first_bad_id=None, checked_at=datetime.now(UTC)
        )


class _FakeWriter:
    def __init__(self, clock: Any = None) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []
        self.at: list[float] = []  # the fake clock at each record, when one is given
        self.clock, self.fail = clock, False

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.emitted.append((action, kwargs))
        self.at.append(self.clock() if self.clock is not None else 0.0)


class _FakeAuditService:
    def __init__(self, *, active: bool = True) -> None:
        self._active = active
        self.query_service = _FakeQuery()
        self.writer_service = _FakeWriter()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def query(self) -> _FakeQuery:
        return self.query_service

    @property
    def writer(self) -> _FakeWriter:
        return self.writer_service


class _FakeResolver:
    def __init__(self, principal: AuditPrincipal | None) -> None:
        self._principal = principal

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        return self._principal


def _owner() -> AuditPrincipal:
    return AuditPrincipal(user_id=uuid.uuid4(), username="owner", permissions=frozenset({"*"}))


def _viewer_no_export() -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username="viewer",
        permissions=frozenset({"orders:read", "accounts:read"}),
    )


def _manager_with_read() -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username="manager",
        permissions=frozenset({"orders:read", "audit:read"}),
    )


def _manager() -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(), username="manager", permissions=frozenset({"orders:read"})
    )


def _app(audit_service: _FakeAuditService | None, resolver: _FakeResolver | None) -> FastAPI:
    app = FastAPI()
    app.include_router(make_audit_router(audit_service, resolver))
    return app


def test_query_audit_log_returns_200_for_authorized_owner() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get("/admin/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["chain_verified"] is True
    assert len(service.query_service.query_calls) == 1


def test_query_audit_log_denied_for_manager_returns_403_and_audits_denial() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_manager())))
    response = client.get("/admin/audit")
    assert response.status_code == 403
    [(action, kwargs)] = service.writer_service.emitted
    assert action == "admin.audit_denied"
    assert kwargs["outcome"].value == "denied"


def test_verify_audit_chain_returns_200_for_authorized_caller() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={})
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert len(service.query_service.verify_calls) == 1


_EXPORT_BODY = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}


def _real_owner() -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username="owner",
        permissions=frozenset({"audit:export"}),
        is_owner=True,
    )


def _non_owner_with_export() -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username="manager",
        permissions=frozenset({"audit:read", "audit:export"}),
        is_owner=False,
    )


_OWNER_SHAPES = pytest.mark.parametrize(
    "principal", [_real_owner, _owner], ids=["is_owner_explicit_permission", "wildcard"]
)


@_OWNER_SHAPES
def test_export_owner_gets_501_with_not_implemented_type(principal: Any) -> None:
    client = TestClient(_app(_FakeAuditService(), _FakeResolver(principal())))
    response = client.post("/admin/audit/export", json=_EXPORT_BODY)
    assert response.status_code == 501
    assert response.json()["type"].endswith("/errors/not_implemented")


@_OWNER_SHAPES
def test_export_owner_501_body_has_no_job_id(principal: Any) -> None:
    client = TestClient(_app(_FakeAuditService(), _FakeResolver(principal())))
    response = client.post("/admin/audit/export", json=_EXPORT_BODY)
    assert response.status_code == 501
    assert "job_id" not in response.text


@_OWNER_SHAPES
def test_export_owner_501_writes_no_audit_record(principal: Any) -> None:
    service = _FakeAuditService()
    response = TestClient(_app(service, _FakeResolver(principal()))).post(
        "/admin/audit/export", json=_EXPORT_BODY
    )
    assert response.status_code == 501
    assert service.writer_service.emitted == []


@pytest.mark.parametrize(
    "principal",
    [_manager_with_read, _manager, _viewer_no_export, _non_owner_with_export],
    ids=["read", "noread", "viewer", "non_owner_with_export"],
)
def test_export_non_owner_gets_403_with_one_denied_record(principal: Any) -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(principal())))
    assert client.post("/admin/audit/export", json=_EXPORT_BODY).status_code == 403
    assert _actions(service) == ["admin.audit_denied"]


def test_export_non_owner_holding_export_is_denied_as_owner_only() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_non_owner_with_export())))
    client.post("/admin/audit/export", json=_EXPORT_BODY)
    assert service.writer_service.emitted[0][1]["reason"] == "owner_only"


def test_export_non_owner_malformed_body_is_403_not_422() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_manager_with_read())))
    response = client.post(
        "/admin/audit/export", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 403
    assert _actions(service) == ["admin.audit_denied"]


def test_export_unauthenticated_gets_401() -> None:
    client = TestClient(_app(_FakeAuditService(), _FakeResolver(None)))
    response = client.post("/admin/audit/export", json=_EXPORT_BODY)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert response.json()["type"].endswith("/errors/unauthenticated")


def test_export_unauthenticated_with_malformed_body_still_401() -> None:
    client = TestClient(_app(_FakeAuditService(), _FakeResolver(None)))
    response = client.post(
        "/admin/audit/export", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 401


def test_export_no_resolver_wired_gives_501_not_implemented_code() -> None:
    client = TestClient(_app(_FakeAuditService(), None))
    response = client.post("/admin/audit/export", json=_EXPORT_BODY)
    assert response.status_code == 501
    assert response.json()["type"].endswith("/errors/not_implemented")


def test_export_backend_not_wired_gives_503() -> None:
    client = TestClient(_app(None, _FakeResolver(_owner())))
    response = client.post("/admin/audit/export", json=_EXPORT_BODY)
    assert response.status_code == 503
    assert response.json()["code"] == "store_unavailable"
    assert response.json()["type"].endswith("/errors/store_unavailable")
    assert response.headers["Retry-After"] == "1"


def test_inactive_audit_service_returns_503() -> None:
    service = _FakeAuditService(active=False)
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get("/admin/audit")
    assert response.status_code == 503


def test_no_principal_resolver_wired_returns_501_not_implemented() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, None))
    response = client.get("/admin/audit")
    assert response.status_code == 501


def test_no_audit_service_wired_returns_503() -> None:
    client = TestClient(_app(None, _FakeResolver(_owner())))
    response = client.get("/admin/audit")
    assert response.status_code == 503
    assert response.json()["code"] == "store_unavailable"
    assert response.json()["type"].endswith("/errors/store_unavailable")
    assert response.headers["Retry-After"] == "1"


def test_resolver_returning_none_returns_401_unauthorized() -> None:
    """PR #1608 review finding 4: a *wired* resolver reporting "no verified
    session" is 401, distinct from the "nothing wired at all" 501 case."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(None)))
    response = client.get("/admin/audit")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert response.json()["type"].endswith("/errors/unauthenticated")


def test_query_audit_log_passes_subject_type_through_to_query_service() -> None:
    """PR #1608 review finding 5: `subject_type` used to be accepted and
    silently dropped."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get("/admin/audit", params={"subject_type": "order"})
    assert response.status_code == 200
    [call] = service.query_service.query_calls
    assert call["subject_type"] == "order"


def test_query_audit_log_rejects_naive_from_ts_with_422_not_500() -> None:
    """QA defect #1596 review: `AuditQueryRequest` refuses a naive `from_`/`to`
    datetime; the route used to let that propagate as an unhandled 500. Contract:
    a bad filter value is `422 validation_failed`."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get(
        "/admin/audit",
        params={"from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00"},
    )
    assert response.status_code == 422
    assert response.json()["status"] == 422


def test_query_audit_log_rejects_from_after_to_with_422_not_500() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get(
        "/admin/audit",
        params={"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
    )
    assert response.status_code == 422


def test_verify_audit_chain_rejects_unknown_body_field() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={"unexpected": "x"})
    assert response.status_code == 400


def test_verify_audit_chain_rejects_from_id_greater_than_to_id() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={"from_id": 10, "to_id": 5})
    assert response.status_code == 400


def test_verify_audit_chain_rejects_non_integer_from_id() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.post("/admin/audit/verify", json={"from_id": "not-an-id"})
    assert response.status_code == 400


def test_query_audit_log_from_alias_matches_openapi_and_reaches_service() -> None:
    """Security re-review of #1608 finding 1: the contract (22-api-openapi.yaml)
    names the lower bound `from`; without `Query(alias="from")` a client's
    `?from=` was silently ignored and the result set widened."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get(
        "/admin/audit",
        params={"from": "2026-01-01T00:00:00+00:00", "to": "2026-01-02T00:00:00+00:00"},
    )
    assert response.status_code == 200
    [call] = service.query_service.query_calls
    assert call["from_ts"] is not None
    assert call["from_ts"].isoformat().startswith("2026-01-01T00:00:00")


def test_query_audit_log_ignores_python_name_from_underscore() -> None:
    """`from_` is an implementation detail, not part of the contract."""
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_owner())))
    response = client.get("/admin/audit", params={"from_": "2026-01-01T00:00:00+00:00"})
    assert response.status_code == 200
    [call] = service.query_service.query_calls
    assert call["from_ts"] is None


# ---- #2083: audit:read grants per 04 §7.2.2 rows 49/49a and SR-067 ----------------


def _entry(i: int, actor: uuid.UUID) -> AuditEntry:
    return AuditEntry(
        id=i,
        ts=datetime(2026, 10, 1, tzinfo=UTC),
        actor_user_id=actor,
        actor_username="x",
        action="order.place",
        outcome=AuditOutcome.SUCCESS,
        severity=Severity.INFO,
        ip="100.84.12.9",
        user_agent="ua",
        request_id="r",
        detail={"symbol": "BTCUSDT", "environment": "live"},
        entry_hash=f"h{i}",
        prev_hash=None,
    )


class _RowsQuery(_FakeQuery):
    def __init__(self, items: list[AuditEntry]) -> None:
        super().__init__()
        self.items = items

    async def query(self, **kwargs: Any) -> AuditPage:
        self.query_calls.append(kwargs)
        actor = kwargs["restrict_to_actor"] or kwargs.get("actor_user_id")
        rows = [e for e in self.items if actor is None or str(e.actor_user_id) == actor]
        return AuditPage(items=rows, chain_verified=True)


def _service_with(items: list[AuditEntry]) -> _FakeAuditService:
    service = _FakeAuditService()
    service.query_service = _RowsQuery(items)
    return service


def test_viewer_query_audit_log_returns_403_problem() -> None:
    service = _FakeAuditService()
    response = TestClient(_app(service, _FakeResolver(_viewer_no_export()))).get("/admin/audit")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert service.query_service.query_calls == []


def test_viewer_verify_audit_chain_returns_403() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_viewer_no_export())))
    assert client.post("/admin/audit/verify", json={}).status_code == 403
    assert service.query_service.verify_calls == []


def test_manager_verify_audit_chain_returns_403() -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(_manager_with_read())))
    assert client.post("/admin/audit/verify", json={}).status_code == 403


def test_manager_query_sees_only_own_events_redacted() -> None:
    me = _manager_with_read()
    other = uuid.uuid4()
    service = _service_with([_entry(1, me.user_id), _entry(2, other)])
    client = TestClient(_app(service, _FakeResolver(me)))
    response = client.get("/admin/audit", params={"actor_user_id": str(other)})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["id"] for i in items] == [1]
    assert items[0]["detail"] == {} and items[0]["ip"] is None
    assert items[0]["user_agent"] is None
    assert items[0]["entry_hash"] is None and items[0]["prev_hash"] is None  # #2392
    [call] = service.query_service.query_calls
    assert call["actor_user_id"] == call["restrict_to_actor"] == str(me.user_id)


def test_owner_query_sees_all_events_raw() -> None:
    owner = _owner()
    service = _service_with([_entry(1, owner.user_id), _entry(2, uuid.uuid4())])
    response = TestClient(_app(service, _FakeResolver(owner))).get("/admin/audit")
    items = response.json()["items"]
    assert [i["id"] for i in items] == [1, 2]
    assert items[1]["detail"] == {"symbol": "BTCUSDT", "environment": "live"}
    assert items[1]["ip"] == "100.84.12.9"
    assert items[1]["entry_hash"] == "h2"  # the Owner keeps both hashes
    assert service.query_service.query_calls[0]["restrict_to_actor"] is None


# ---- #2392 "Limits": per-user limiter, time budget, store errors ---------------------------


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def _limited(
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
    client, svc = _limited(_owner(), limiter=lim)
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
    client, _ = _limited(_owner(), svc, limiter=lim)
    client = TestClient(client.app, raise_server_exceptions=False)
    assert client.get("/admin/audit").status_code == 500
    assert all(s.inflight == 0 for s in lim._users.values())


@pytest.mark.parametrize(
    "error", [TimeoutError(), AuditReadFailed("08006"), AuditReadBusy(), ChainHasherBusy()]
)
def test_timeout_or_store_error_is_503_and_releases_the_lease(error: Exception) -> None:
    lim = AuditQueryLimiter(max_concurrent=1)
    svc = _FakeAuditService()

    async def fail(**kw: Any) -> AuditPage:
        assert kw["timeout_ms"] == 1234
        raise error

    svc.query_service.query = fail  # type: ignore[method-assign,assignment]  # test double
    client, _ = _limited(_owner(), svc, limiter=lim)
    r = client.get("/admin/audit")
    assert (r.status_code, r.json()["code"], r.headers["Retry-After"]) == (
        503,
        "store_unavailable",
        "1",
    )
    assert all(s.inflight == 0 for s in lim._users.values())


def test_validation_limits_and_ip() -> None:
    client, svc = _limited(_owner())
    assert client.get("/admin/audit", params={"limit": 501}).status_code == 422
    assert client.get("/admin/audit", params={"limit": 0}).status_code == 422
    assert client.get("/admin/audit", params={"ip": "10.0.0.0/8"}).status_code == 422
    assert client.get("/admin/audit", params={"ip": "nope"}).status_code == 422
    assert client.get("/admin/audit", params={"ip": "fe80::1%eth0"}).status_code == 422
    assert client.get("/admin/audit", params={"ip": "::1"}).status_code == 200
    assert svc.query_service.query_calls[-1]["limit"] == 100


def test_manager_ip_filter_is_refused_with_403_and_recorded() -> None:
    client, svc = _limited(_manager_with_read())
    r = client.get("/admin/audit", params={"ip": "10.0.0.1"})
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    [(action, kw)] = svc.writer_service.emitted
    assert (action, kw["reason"]) == ("admin.audit_denied", "filter_not_permitted:ip")
    assert svc.query_service.query_calls == []


def test_query_timeout_setting_is_capped_at_30_seconds() -> None:
    assert Settings(audit_query_timeout_ms=30_000).audit_query_timeout_ms == 30_000
    with pytest.raises(ValidationError):
        Settings(audit_query_timeout_ms=30_001)


def test_global_read_cap_stays_below_the_audit_pool() -> None:
    assert Settings().audit_query_global_max_concurrent == 4
    for out_of_range in (1, 11):  # 1 leaves no slot beside the Owner's
        with pytest.raises(ValidationError):
            Settings(audit_query_global_max_concurrent=out_of_range)


def test_the_owner_read_slot_follows_is_owner_only() -> None:
    """SR-017: the slot kept for the Owner goes by the resolved `is_owner`, never by a role
    name or the `*` grant."""
    owner = AuditPrincipal(
        user_id=uuid.uuid4(), username="owner", permissions=frozenset({"audit:read"}), is_owner=True
    )
    for principal, expected in ((owner, True), (_owner(), False), (_manager_with_read(), False)):
        client, svc = _budgeted(principal)
        assert client.get("/admin/audit").status_code == 200
        assert svc.query_service.query_calls[-1]["owner"] is expected


def test_raw_follows_the_resolved_view_not_the_owner_flag() -> None:
    """Only the Owner's raw view asks for the Owner-only columns, and `raw` comes from the
    view alone: the `*` grant gets the raw view without `is_owner`, so there `raw` and the
    read slot's `owner` differ."""
    owner = AuditPrincipal(
        user_id=uuid.uuid4(), username="owner", permissions=frozenset({"audit:read"}), is_owner=True
    )
    cases = ((owner, True, True), (_owner(), True, False), (_manager_with_read(), False, False))
    for principal, raw, slot in cases:
        client, svc = _budgeted(principal)
        assert client.get("/admin/audit").status_code == 200
        call = svc.query_service.query_calls[-1]
        assert (call["raw"], call["owner"]) == (raw, slot)


def test_every_query_response_is_no_store() -> None:
    """Contract `queryAuditLog`: no cache keeps an audit page, nor a refusal of one."""
    limiter = AuditQueryLimiter(rate_per_minute=1, clock=_Clock())
    owner = _limited(_owner(), limiter=limiter)[0]
    responses = [
        owner.get("/admin/audit"),
        owner.get("/admin/audit"),  # over the rate
        owner.get("/admin/audit", params={"cursor": "<x>"}),
        owner.get("/admin/audit", params={"limit": 0}),
        _budgeted(_manager_with_read())[0].get("/admin/audit", params={"q": "x"}),
        TestClient(_app(_FakeAuditService(), _FakeResolver(None))).get("/admin/audit"),
    ]
    assert [r.status_code for r in responses] == [200, 429, 400, 422, 403, 401]
    assert [r.headers["cache-control"] for r in responses] == ["no-store"] * len(responses)


# ---- #2392 parameter rules: canonical values, 422 without echoing the input ----------------


def test_repeated_action_parameters_reach_the_service_as_a_sorted_set() -> None:
    client, svc = _limited(_owner())
    params = [
        ("action", "orders.submit"),
        ("action", "api_key.rotate"),
        ("action", "orders.submit"),
    ]
    assert client.get("/admin/audit", params=params).status_code == 200
    assert svc.query_service.query_calls[-1]["actions"] == ["api_key.rotate", "orders.submit"]


def test_actor_user_id_is_compared_in_canonical_form() -> None:
    client, svc = _limited(_owner())
    uid = uuid.uuid4()
    assert client.get("/admin/audit", params={"actor_user_id": str(uid).upper()}).is_success
    assert svc.query_service.query_calls[-1]["actor_user_id"] == str(uid)


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"actor_user_id": "x" * 3900}, "actor_user_id"),
        ({"actor_user_id": "{" + str(uuid.UUID(int=1)) + "}"}, "actor_user_id"),
        ({"subject_type": "Order<script>"}, "subject_type"),
        ({"action": "orders.submit\n"}, "action"),
        ({"action": "a." + "b" * 64}, "action"),
        ({"action": [f"x.a{i}" for i in range(51)]}, "action"),
        ({"ip": "nope-<script>"}, "ip"),
    ],
)
def test_invalid_filters_are_422_without_echoing_the_input(
    params: dict[str, Any], field: str
) -> None:
    client, svc = _limited(_owner())
    r = client.get("/admin/audit", params=params)
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert [e["field"] for e in r.json()["errors"]] == [field]
    assert "<script>" not in r.text and "xxxx" not in r.text and "bbbb" not in r.text
    assert svc.query_service.query_calls == []


def test_validation_error_from_the_query_service_is_422_without_the_input() -> None:
    svc = _FakeAuditService()

    async def invalid(**_: Any) -> AuditPage:
        AuditQueryRequest.model_validate({"ip": "secret-value"})
        raise AssertionError("unreachable")

    svc.query_service.query = invalid  # type: ignore[method-assign,assignment]  # test double
    r = _limited(_owner(), svc)[0].get("/admin/audit")
    assert (r.status_code, r.json()["errors"]) == (422, [{"field": "ip", "rule": "value_error"}])
    assert "secret-value" not in r.text


def test_unknown_body_key_is_not_echoed() -> None:
    client, _ = _limited(_owner())
    r = client.post("/admin/audit/verify", json={"<img src=x>": 1})
    assert r.status_code == 400 and r.json()["errors"] == [
        {"field": "(unknown)", "rule": "extra_forbidden"}
    ]
    assert "img" not in r.text


# ---- #2392 "Audit budget": read and refusal records on /admin/audit* -----------------------


def _budgeted(
    principal: AuditPrincipal,
    service: _FakeAuditService | None = None,
    *,
    budget: AuditRecordBudget | None = None,
    limiter: AuditQueryLimiter | None = None,
) -> tuple[TestClient, _FakeAuditService]:
    svc = service or _FakeAuditService()
    app = FastAPI()
    app.include_router(
        make_audit_router(svc, _FakeResolver(principal), limiter=limiter, budget=budget)
    )
    return TestClient(app), svc


def _actions(svc: _FakeAuditService) -> list[str]:
    return [a for a, _ in svc.writer_service.emitted]


def test_refusals_write_at_most_the_hourly_cap_and_the_owner_still_reads() -> None:
    budget = AuditRecordBudget(per_hour=120, clock=_Clock())
    svc = _FakeAuditService()
    for principal in (_viewer_no_export(), _manager()):
        svc.writer_service.emitted.clear()
        client, _ = _budgeted(principal, svc, budget=budget)
        assert {client.get("/admin/audit").status_code for _ in range(300)} == {403}
        assert len(svc.writer_service.emitted) == 120
    assert _budgeted(_owner(), svc, budget=budget)[0].get("/admin/audit").status_code == 200


def test_refusal_carries_retry_after_only_over_the_cap() -> None:
    clock = _Clock()
    client, svc = _budgeted(_manager(), budget=AuditRecordBudget(per_hour=1, clock=clock))
    first = client.get("/admin/audit")
    assert first.status_code == 403 and "Retry-After" not in first.headers
    over = client.get("/admin/audit")
    assert (over.status_code, over.headers["Retry-After"]) == (403, "3600")
    clock.now += 3600
    client.get("/admin/audit")
    assert svc.writer_service.emitted[-1][1]["after_state"] == {"suppressed": 1}


@pytest.mark.parametrize("cause", ["writer", "inflight_cap"])
def test_export_denial_record_that_cannot_be_written_is_503_not_403(cause: str) -> None:
    svc = _FakeAuditService()
    svc.writer_service.fail = cause == "writer"
    budget = AuditRecordBudget(inflight_cap=0 if cause == "inflight_cap" else 64)
    client, _ = _budgeted(_non_owner_with_export(), svc, budget=budget)
    r = client.post("/admin/audit/export", json=_EXPORT_BODY)
    assert (r.status_code, r.json()["code"]) == (503, "store_unavailable")


@pytest.mark.parametrize("cause", ["writer", "inflight_cap"])
def test_refusal_record_that_cannot_be_written_is_503_not_403(cause: str) -> None:
    svc = _FakeAuditService()
    svc.writer_service.fail = cause == "writer"
    budget = AuditRecordBudget(inflight_cap=0 if cause == "inflight_cap" else 64)
    for principal, path in ((_manager(), "/admin/audit"), (_manager_with_read(), "/admin/audit")):
        params = {"ip": "10.0.0.1"} if principal.has("audit:read") else {}
        r = _budgeted(principal, svc, budget=budget)[0].get(path, params=params)
        assert (r.status_code, r.json()["code"], r.headers["Retry-After"]) == (
            503,
            "store_unavailable",
            "1",
        )


def test_manager_ip_filter_refusal_is_budgeted() -> None:
    budget = AuditRecordBudget(per_hour=1, clock=_Clock())
    client, svc = _budgeted(_manager_with_read(), budget=budget)
    assert client.get("/admin/audit", params={"ip": "10.0.0.1"}).status_code == 403
    over = client.get("/admin/audit", params={"ip": "10.0.0.1"})
    assert (over.status_code, over.headers["Retry-After"]) == (403, "3600")
    assert len(svc.writer_service.emitted) == 1


def test_cross_actor_filter_is_recorded_in_canonical_form_then_narrowed() -> None:
    me, other = _manager_with_read(), uuid.uuid4()
    client, svc = _budgeted(me)
    assert client.get("/admin/audit", params={"actor_user_id": str(other).upper()}).is_success
    (denied, kw), (read, kw2) = svc.writer_service.emitted
    assert (denied, kw["reason"], kw["after_state"]) == (
        "admin.audit_denied",
        "cross_actor_filter_narrowed",
        {"requested_actor": str(other)},
    )
    assert read == "admin.audit_read"
    assert kw2["after_state"]["filters"] == {"actor_user_id": str(me.user_id)}
    assert svc.query_service.query_calls[0]["actor_user_id"] == str(me.user_id)
    own = {"actor_user_id": str(me.user_id).upper()}  # the caller's own id: not cross-actor
    assert client.get("/admin/audit", params=own).is_success
    assert len(svc.writer_service.emitted) == 2  # a continuation of the same filter set


@pytest.mark.parametrize(("cause", "status"), [("over_cap", 429), ("writer", 503)])
def test_cross_actor_attempt_that_cannot_be_recorded_serves_nothing(
    cause: str, status: int
) -> None:
    me = _manager_with_read()
    svc = _service_with([_entry(1, me.user_id)])
    svc.writer_service.fail = cause == "writer"
    budget = AuditRecordBudget(per_hour=1, clock=_Clock())
    client, _ = _budgeted(me, svc, budget=budget)
    if cause == "over_cap":
        assert client.get("/admin/audit").is_success  # uses the one record of the hour
    r = client.get("/admin/audit", params={"actor_user_id": str(uuid.uuid4())})
    assert r.status_code == status and "items" not in r.json()
    assert len(svc.query_service.query_calls) == (cause == "over_cap")


def test_one_read_record_per_filter_set_and_continuations_counted() -> None:
    client, svc = _budgeted(_owner())
    for _ in range(5):
        assert client.get("/admin/audit", params={"outcome": "success"}).status_code == 200
    assert client.get("/admin/audit", params={"outcome": "denied"}).status_code == 200
    assert _actions(svc) == ["admin.audit_read", "admin.audit_read"]
    after = svc.writer_service.emitted[-1][1]["after_state"]
    assert (after["filters"], after["view"], after["returned_count"]) == (
        {"outcome": "denied"},
        "raw",
        0,
    )
    assert sorted(p["pages"] for p in after["pages"]) == [1, 4]  # this page; 4 continuations


def test_read_over_the_cap_is_429_with_no_data_and_no_record() -> None:
    budget = AuditRecordBudget(per_hour=1, owner_per_hour=1, clock=_Clock())
    client, svc = _budgeted(_owner(), budget=budget)
    assert client.get("/admin/audit", params={"outcome": "success"}).status_code == 200
    r = client.get("/admin/audit", params={"outcome": "denied"})
    assert (r.status_code, r.json()["code"], r.headers["Retry-After"]) == (
        429,
        "rate_limited",
        "3600",
    )
    assert len(svc.query_service.query_calls) == 1 and len(svc.writer_service.emitted) == 1


@pytest.mark.parametrize("cause", ["writer", "inflight_cap"])
def test_due_read_record_that_cannot_be_written_is_503_without_data(cause: str) -> None:
    svc = _FakeAuditService()
    svc.writer_service.fail = cause == "writer"
    budget = AuditRecordBudget(inflight_cap=0 if cause == "inflight_cap" else 64)
    r = _budgeted(_owner(), svc, budget=budget)[0].get("/admin/audit")
    assert r.status_code == 503 and "items" not in r.json()
    assert len(svc.query_service.query_calls) == (cause == "writer")  # cap: no query at all


def test_timeouts_and_validation_errors_do_not_use_up_the_record_cap() -> None:
    budget = AuditRecordBudget(per_hour=1, owner_per_hour=1, clock=_Clock())
    svc = _FakeAuditService()
    state = {"fail": True}

    async def query(**_: Any) -> AuditPage:
        if state["fail"]:
            raise TimeoutError
        return AuditPage(items=[], chain_verified=True, count=0)

    svc.query_service.query = query  # type: ignore[method-assign,assignment]  # test double
    client, _ = _budgeted(_owner(), svc, budget=budget)
    assert [client.get("/admin/audit").status_code for _ in range(3)] == [503] * 3
    assert client.get("/admin/audit", params={"from": "2026-01-01T00:00:00"}).status_code == 422
    state["fail"] = False
    assert client.get("/admin/audit").status_code == 200 and _actions(svc) == ["admin.audit_read"]


def test_limiter_429_is_counted_and_carried_by_the_next_record() -> None:
    clock = _Clock()
    lim = AuditQueryLimiter(rate_per_minute=1, clock=clock)
    client, svc = _budgeted(_owner(), limiter=lim, budget=AuditRecordBudget(clock=clock))
    assert client.get("/admin/audit", params={"outcome": "success"}).status_code == 200
    assert client.get("/admin/audit", params={"outcome": "denied"}).status_code == 429
    clock.now += 60
    assert client.get("/admin/audit", params={"outcome": "denied"}).status_code == 200
    assert svc.writer_service.emitted[-1][1]["after_state"]["suppressed"] == 1


async def test_cancellation_releases_the_limiter_lease_and_the_read_reservation() -> None:
    lim = AuditQueryLimiter(max_concurrent=1, clock=_Clock())
    budget = AuditRecordBudget(per_hour=1, owner_per_hour=1, clock=_Clock())
    svc = _FakeAuditService()
    started = asyncio.Event()

    async def hang(**_: Any) -> AuditPage:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    svc.query_service.query = hang  # type: ignore[method-assign,assignment]  # test double
    app = FastAPI()
    app.include_router(make_audit_router(svc, _FakeResolver(_owner()), limiter=lim, budget=budget))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
        call = asyncio.ensure_future(ac.get("/admin/audit"))
        await started.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
    assert all(u.inflight == 0 for u in lim._users.values())
    user = next(iter(budget._users.values()))
    assert (user.reserved, user.reading, user.stamps) == (0, 0, [])


async def test_owner_still_reads_when_every_tracked_entry_is_busy() -> None:
    """`tracked_users` at its floor, every entry busy with another user's record of this
    hour: the Owner (`is_owner`, SR-017) is tracked apart and reads, up to its own cap."""
    budget = AuditRecordBudget(tracked_users=64, owner_per_hour=2, clock=_Clock())
    svc = _FakeAuditService()
    for i in range(64):
        viewer = BudgetActor(f"viewer-{i}", "viewer", uuid.uuid4(), owner=False)
        assert await budget.write_denial(viewer, svc.writer_service, {"actor_label": "viewer"})
    owner = AuditPrincipal(
        user_id=uuid.uuid4(), username="owner", permissions=frozenset({"audit:read"}), is_owner=True
    )
    resolver = _FakeResolver(owner)
    app = FastAPI()
    app.include_router(make_audit_router(svc, resolver, budget=budget))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
        codes = [
            (await ac.get("/admin/audit", params={"outcome": o})).status_code
            for o in ("success", "denied", "failure")
        ]
        resolver._principal = _manager_with_read()
        other = await ac.get("/admin/audit")
    assert codes == [200, 200, 429]  # the Owner's own cap of 2
    assert other.status_code == 503  # any other new user stays within the bound


async def test_manager_with_audit_read_bounded_record_count_over_two_hours() -> None:
    """Reads, continuations, refusals and cross-actor reads every 5 s for two hours of fake
    time, with a flush tick every 30 s: in no hour more than 120 capped records plus 12
    out-of-cap ones, and every served page is recorded or still pending."""
    clock, me = _Clock(), _manager_with_read()
    svc = _FakeAuditService()
    svc.writer_service = _FakeWriter(clock)
    budget, lim = AuditRecordBudget(clock=clock), AuditQueryLimiter(clock=clock)
    app = FastAPI()
    app.include_router(make_audit_router(svc, _FakeResolver(me), limiter=lim, budget=budget))
    calls = [
        ("GET", {"subject_type": "kind"}),  # replaced below by a fresh filter set
        ("GET", {"outcome": "success"}),
        ("GET", {"outcome": "success"}),
        ("GET", {"ip": "10.0.0.1"}),
        ("POST", {}),
        ("GET", {"actor_user_id": "11111111-1111-4111-8111-111111111111"}),
    ]
    served = 0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
        for i in range(1440):
            clock.now += 5
            method, params = calls[i % 6]
            if i % 6 == 0:
                params = {"subject_type": f"kind_{i % 97}"}
            if method == "POST":
                r = await ac.post("/admin/audit/verify", json={})
            else:
                r = await ac.get("/admin/audit", params=params)
            served += r.status_code == 200
            if i % 6 == 5:
                await budget.flush_due(svc.writer_service)
    records = [
        (at, kw.get("reason") in (FLUSH_REASON, SUMMARY_REASON), kw)
        for (_, kw), at in zip(svc.writer_service.emitted, svc.writer_service.at, strict=True)
    ]
    assert all(kw["actor_user_id"] == me.user_id for _, _, kw in records)
    for start, _, _ in records:
        hour = [oob for at, oob, _ in records if start <= at < start + 3600]
        assert hour.count(False) <= 120 and hour.count(True) <= 12
    pages = sum(
        sum(p["pages"] for p in (kw.get("after_state") or {}).get("pages", []))
        for _, _, kw in records
    )
    assert pages + budget._users[str(me.user_id)].pending_pages() == served > 0


# ---- #2392 paging and filters: cursor, scope, subject_id, q, meta ------------------------


def test_malformed_cursor_is_400_invalid_cursor_and_runs_nothing() -> None:
    client, svc = _budgeted(_owner())
    for bad in ("<script>", "a" * 513, encode_cursor(AuditCursor(_TS, 5)) + "x"):
        r = client.get("/admin/audit", params={"cursor": bad})
        assert (r.status_code, r.json()["code"]) == (400, "invalid_cursor")
        assert "script" not in r.text and "aaaa" not in r.text
    assert svc.query_service.query_calls == [] and svc.writer_service.emitted == []


def test_cursor_position_reaches_the_service_and_meta_carries_the_next_one() -> None:
    owner = _owner()
    svc = _service_with([_entry(i, owner.user_id) for i in (3, 2)])
    nxt = encode_cursor(AuditCursor(_TS, 2))

    async def page(**kwargs: Any) -> AuditPage:
        svc.query_service.query_calls.append(kwargs)
        meta = AuditPageMeta(next_cursor=nxt, has_more=True, count=2)
        return AuditPage(items=svc.query_service.items, chain_verified=True, meta=meta)

    svc.query_service.query = page  # type: ignore[method-assign]  # test double
    r = _budgeted(owner, svc)[0].get("/admin/audit", params={"cursor": nxt, "limit": 2})
    assert r.json()["meta"] == {"next_cursor": nxt, "has_more": True, "count": 2}
    assert "next_cursor" not in r.json()  # contract: paging metadata lives in `meta`
    assert svc.query_service.query_calls[0]["after"] == AuditCursor(_TS, 2)


def test_scope_is_applied_again_on_every_page() -> None:
    """The cursor carries no scope: a Manager's scope comes from its principal on every
    page, whatever cursor or `actor_user_id` it sends."""
    me = _manager_with_read()
    client, svc = _budgeted(me, _service_with([_entry(1, me.user_id)]))
    nxt = encode_cursor(AuditCursor(_TS, 9))
    for params in ({}, {"cursor": nxt}, {"cursor": nxt, "actor_user_id": str(uuid.uuid4())}):
        assert client.get("/admin/audit", params=params).status_code == 200
    calls = svc.query_service.query_calls
    assert [c["restrict_to_actor"] for c in calls] == [str(me.user_id)] * 3
    assert [c["after"] for c in calls] == [None, AuditCursor(_TS, 9), AuditCursor(_TS, 9)]


def test_manager_q_filter_is_refused_with_403_and_recorded() -> None:
    client, svc = _budgeted(_manager_with_read())
    r = client.get("/admin/audit", params={"q": "password"})
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    [(action, kw)] = svc.writer_service.emitted
    assert (action, kw["reason"]) == ("admin.audit_denied", "filter_not_permitted:q")
    assert svc.query_service.query_calls == [] and "password" not in str(kw)


def test_owner_q_and_subject_id_reach_the_service_and_are_recorded_as_digests() -> None:
    """Both free-text filters reach the query as given but are recorded only as a digest and
    a length, so a control sequence typed into either never lands in the permanent log."""
    client, svc = _budgeted(_owner())
    params = {"q": "Breakout BTC", "subject_id": "\x1b[2Jo-1"}
    assert client.get("/admin/audit", params=params).status_code == 200
    [call] = svc.query_service.query_calls
    assert (call["q"], call["subject_id"], call["restrict_to_actor"]) == (
        "Breakout BTC",
        "\x1b[2Jo-1",
        None,
    )
    [(_, kw)] = svc.writer_service.emitted

    def digest(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    assert kw["after_state"]["filters"] == {
        "subject_id_sha256": digest("\x1b[2Jo-1"),
        "subject_id_len": 7,
        "q_sha256": digest("Breakout BTC"),
        "q_len": 12,
    }
    assert "Breakout" not in str(kw) and "o-1" not in str(kw)


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"}, "to"),
        ({"q": "x" * 201}, "q"),
        ({"q": "a\x00b"}, "q"),
        ({"subject_id": "s" * 65}, "subject_id"),
    ],
)
def test_empty_window_and_overlong_text_filters_are_422(params: dict[str, Any], field: str) -> None:
    client, svc = _budgeted(_owner())
    r = client.get("/admin/audit", params=params)
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert [e["field"] for e in r.json()["errors"]] == [field]
    assert svc.query_service.query_calls == []


def test_a_row_outside_the_callers_scope_is_never_served() -> None:
    me = _manager_with_read()
    svc = _service_with([_entry(1, me.user_id), _entry(2, uuid.uuid4())])

    async def leaky(**kwargs: Any) -> AuditPage:  # a scope bug below the router
        return AuditPage(items=svc.query_service.items, chain_verified=True)

    svc.query_service.query = leaky  # type: ignore[method-assign]  # test double
    r = _budgeted(me, svc)[0].get("/admin/audit")
    assert (r.status_code, r.json()["code"]) == (503, "store_unavailable")
    assert "items" not in r.json()


async def test_the_users_slot_is_held_until_the_page_is_hashed() -> None:
    """Security condition 4 on #2392: the per-user concurrency slot covers the chain check,
    not only the SQL, so the concurrency cap also bounds the CPU work."""
    started, release = threading.Event(), threading.Event()
    hasher = ChainHasher(workers=1, max_pending=1)  # a second job would be 503, never a hang
    real_run = hasher.run

    async def blocked(fn: Any) -> Any:
        def job() -> Any:
            started.set()
            release.wait()
            return fn()

        return await real_run(job)

    class _Repo:
        async def query_page(self, **_: Any) -> list[dict[str, Any]]:
            return []

    hasher.run = blocked  # type: ignore[method-assign]  # test double
    svc = _FakeAuditService()
    svc.query_service = AuditQueryService(_Repo(), hasher=hasher)  # type: ignore[assignment,arg-type]
    lim = AuditQueryLimiter(max_concurrent=1, clock=_Clock())
    app = FastAPI()
    app.include_router(make_audit_router(svc, _FakeResolver(_owner()), limiter=lim))
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            first = asyncio.ensure_future(ac.get("/admin/audit"))
            await asyncio.to_thread(started.wait)
            assert (await ac.get("/admin/audit")).status_code == 429  # still hashing
            release.set()
            assert (await first).status_code == 200
    finally:
        release.set()
        hasher.shutdown()


@pytest.mark.parametrize(
    ("principal", "params", "label"),
    [
        (_owner, {}, "none"),
        (_owner, {"q": "x", "ip": "10.0.0.1"}, "q"),
        (_owner, {"ip": "10.0.0.1", "outcome": "denied"}, "ip"),
        (_owner, {"action": "orders.submit", "outcome": "denied"}, "action"),
        (_owner, {"subject_id": "o-1"}, "object"),
        (_owner, {"severity": "error", "outcome": "denied"}, "severity"),
        (_owner, {"outcome": "denied"}, "outcome"),
        (_owner, {"to": "2026-01-01T00:00:00Z"}, "range"),
        (_manager_with_read, {}, "actor"),
        (_manager_with_read, {"action": "orders.submit"}, "actor_action"),
    ],
)
def test_served_page_time_is_observed_under_a_closed_filter_class(
    principal: Any, params: dict[str, Any], label: str
) -> None:
    name, labels = "cv_audit_query_duration_seconds_count", {"filter_class": label}
    before = REGISTRY.get_sample_value(name, labels) or 0
    assert _budgeted(principal())[0].get("/admin/audit", params=params).status_code == 200
    assert REGISTRY.get_sample_value(name, labels) == before + 1
    assert label in FILTER_CLASSES


# ---- Validate query parameters after authorisation: 401, then 403, then 422 -------------

#: Each parameter with a type beyond text, a value that does not parse as it, and the rule
#: the 422 names.
_MALFORMED = pytest.mark.parametrize(
    ("param", "value", "rule"),
    [
        ("limit", "abc", "int_parsing"),
        ("from", "yesterday", "datetime_from_date_parsing"),
        ("to", "yesterday", "datetime_from_date_parsing"),
    ],
)


@_MALFORMED
def test_malformed_parameter_from_an_unauthenticated_caller_is_401(
    param: str, value: str, rule: str
) -> None:
    service = _FakeAuditService()
    r = TestClient(_app(service, _FakeResolver(None))).get("/admin/audit", params={param: value})
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert r.headers["cache-control"] == "no-store"
    assert service.writer_service.emitted == [] and service.query_service.query_calls == []


@_MALFORMED
@pytest.mark.parametrize("principal", [_viewer_no_export, _manager], ids=["viewer", "no_read"])
def test_malformed_parameter_from_a_caller_without_audit_read_is_403_with_one_denial(
    principal: Any, param: str, value: str, rule: str
) -> None:
    service = _FakeAuditService()
    client = TestClient(_app(service, _FakeResolver(principal())))
    r = client.get("/admin/audit", params={param: value})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert _actions(service) == ["admin.audit_denied"]
    assert service.query_service.query_calls == []


@_MALFORMED
def test_malformed_parameter_from_the_owner_is_422_naming_only_field_and_rule(
    param: str, value: str, rule: str
) -> None:
    client, svc = _budgeted(_owner())
    r = client.get("/admin/audit", params={param: value})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert r.json()["errors"] == [{"field": param, "rule": rule}]
    assert value not in r.text
    assert svc.query_service.query_calls == [] and svc.writer_service.emitted == []
