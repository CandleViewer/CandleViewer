"""`IdleLockMiddleware` and the idle-lock problems (#2300; contract info "Idle lock").

The gate in isolation over a real `SessionService` (in-memory repository, fixed clock): it
refuses exactly the request the routes' own authentication refuses as idle-locked, and nothing
else; the operations allowed while locked and the ones the contract does not authenticate with
a bearer pass. No DB, no network (C-13.5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from jsonschema import Draft202012Validator
from prometheus_client import REGISTRY
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.idle_lock import (
    LOCKED_OK_OPERATIONS,
    IdleLockMiddleware,
    idle_locked_problem,
    not_locked_problem,
    session_revoked_problem,
    ungated_operations,
    unlock_invalid_problem,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, SessionService
from tests.unit.auth.session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)
_IDLE = timedelta(seconds=300)
_BASE = "urn:cv:openapi"


@cache
def _spec() -> dict[str, Any]:
    return load_openapi_spec()


def _idle_locks_refused() -> float:
    return float(REGISTRY.get_sample_value("auth_idle_locks_total") or 0.0)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class Gate:
    """A catch-all app behind the gate: `reached` lists the requests the gate let through."""

    def __init__(self, *, wired: bool = True) -> None:
        self.clock = _Clock()
        self.repo = FakeSessionRepository()
        self.sessions = SessionService(self.repo, Hasher(), clock=self.clock)
        self.reached: list[str] = []
        app = FastAPI()

        @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        async def anything(request: Request) -> dict[str, str]:
            self.reached.append(f"{request.method} {request.url.path}")
            return {"reached": request.url.path}

        app.add_middleware(
            IdleLockMiddleware,
            sessions=lambda: self.sessions if wired else None,
            ungated=ungated_operations(_spec()),
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://testserver"
        )

    async def mint(self) -> MintedSession:
        return await self.sessions.mint(
            "00000000-0000-4000-8000-0000000000a1", idle_timeout_s=int(_IDLE.total_seconds())
        )

    async def send(self, method: str, path: str, minted: MintedSession | None) -> httpx.Response:
        headers = {} if minted is None else {"Authorization": f"Bearer {minted.access_token}"}
        return await self.client.request(method, path, headers=headers)


@pytest.fixture
async def gate() -> Any:
    g = Gate()
    try:
        yield g
    finally:
        await g.client.aclose()


def test_ungated_operations_are_the_three_allowed_while_locked_and_the_non_bearer_ones() -> None:
    """Derived from the contract's `security`, so a new bearer operation is gated by default."""
    assert ungated_operations(_spec()) == LOCKED_OK_OPERATIONS | {
        ("POST", "/auth/login"),
        ("POST", "/auth/mfa/verify"),
        ("POST", "/auth/refresh"),
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
    }
    assert LOCKED_OK_OPERATIONS == {
        ("POST", "/auth/unlock"),
        ("POST", "/auth/logout"),
        ("GET", "/auth/session"),
    }


async def test_a_locked_session_is_refused_with_session_idle_locked_and_the_route_never_runs(
    gate: Gate,
) -> None:
    minted = await gate.mint()
    gate.clock.now += _IDLE
    before = _idle_locks_refused()
    r = await gate.send("POST", "/api/v1/trading/kill-switch", minted)
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "session_idle_locked"
    assert r.json()["idle_locked_at"] == (_T0 + _IDLE).isoformat()
    assert gate.reached == []
    assert _idle_locks_refused() == before + 1
    row = await gate.repo.find_by_id(str(minted.session_id))
    assert row is not None and row.last_seen_at == _T0  # refusing is not activity


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/auth/sessions"),
        ("DELETE", "/me/sessions/00000000-0000-4000-8000-0000000000ff"),
        ("POST", "/auth/step-up"),
        ("POST", "/auth/session/extend"),
        ("POST", "/orders"),
        ("POST", "/settings/arm"),
        ("GET", "/api/v1/market/bars"),
        ("GET", "/auth/session/"),  # exact match only: a variant of an allowed path is gated
        ("HEAD", "/no/such/route"),
    ],
)
async def test_every_other_request_of_a_locked_session_is_refused(
    gate: Gate, method: str, path: str
) -> None:
    minted = await gate.mint()
    gate.clock.now += _IDLE
    r = await gate.send(method, path, minted)
    assert r.status_code == 401
    assert gate.reached == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/auth/unlock"),
        ("POST", "/api/v1/auth/unlock"),
        ("POST", "/auth/logout"),
        ("GET", "/auth/session"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/login"),
        ("GET", "/health/live"),
    ],
)
async def test_operations_allowed_while_locked_and_non_bearer_ones_reach_their_route(
    gate: Gate, method: str, path: str
) -> None:
    minted = await gate.mint()
    gate.clock.now += _IDLE
    assert (await gate.send(method, path, minted)).status_code == 200
    assert gate.reached == [f"{method} {path}"]


async def test_a_live_session_passes(gate: Gate) -> None:
    minted = await gate.mint()
    gate.clock.now += _IDLE - timedelta(seconds=1)
    assert (await gate.send("POST", "/orders", minted)).status_code == 200


async def test_an_expired_access_token_of_a_locked_session_stays_unauthenticated(
    gate: Gate,
) -> None:
    """The route answers its own uniform 401: the gate never reveals the lock to a dead token."""
    minted = await gate.mint()
    gate.clock.now += ACCESS_TOKEN_TTL
    assert (await gate.send("GET", "/auth/sessions", minted)).status_code == 200
    assert gate.reached == ["GET /auth/sessions"]


async def test_revoked_expired_unknown_and_missing_credentials_pass_to_the_route(
    gate: Gate,
) -> None:
    revoked = await gate.mint()
    await gate.sessions.revoke(str(revoked.session_id), reason="logout")
    assert (await gate.send("GET", "/a", revoked)).status_code == 200
    assert (await gate.send("GET", "/b", None)).status_code == 200
    forged = await gate.client.get("/c", headers={"Authorization": "Bearer never-issued"})
    assert forged.status_code == 200
    expired = await gate.mint()
    gate.clock.now += timedelta(hours=12)
    assert (await gate.send("GET", "/d", expired)).status_code == 200
    assert gate.reached == ["GET /a", "GET /b", "GET /c", "GET /d"]


async def test_without_a_session_backend_the_gate_passes() -> None:
    g = Gate(wired=False)
    try:
        assert (await g.client.get("/x", headers={"Authorization": "Bearer t"})).status_code == 200
    finally:
        await g.client.aclose()


def _conforms(value: Any) -> None:
    resource = Resource.from_contents(_spec(), default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/Problem"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


@pytest.mark.parametrize(
    ("response", "revoked_reason"),
    [
        (idle_locked_problem(_T0), None),
        (idle_locked_problem(None), None),
        (unlock_invalid_problem(), None),
        (session_revoked_problem("expired"), "expired"),
        (session_revoked_problem("unlock_attempts_exceeded"), "unlock_attempts_exceeded"),
        (session_revoked_problem("mfa_reset_by_owner"), "revoked"),  # cause not disclosed
        (not_locked_problem(), None),
    ],
)
def test_problems_conform_to_the_contract_and_its_error_registry(
    response: Any, revoked_reason: str | None
) -> None:
    import json

    body = json.loads(response.body)
    _conforms(body)
    entry = {e["code"]: e for e in _spec()["x-error-codes"]}[body["code"]]
    assert (body["title"], body["status"], response.status_code) == (
        entry["title"],
        entry["status"],
        entry["status"],
    )
    assert body["type"] == f"https://candleviewer.local/errors/{body['code']}"
    assert body.get("revoked_reason") == revoked_reason
