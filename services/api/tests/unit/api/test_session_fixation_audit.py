"""Session-fixation signal on the session routes (E09-X02 AC2, #2144, U6/SR-013).

A bearer or refresh token this server never issued is refused with the uniform 401 and is
counted and audited within a per-IP budget; an expired or revoked token of a real session is
not an attempt; a failed audit write never changes the 401. Fixed clock, no network.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.api.sessions import REFRESH_COOKIE, make_session_router
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.api.test_sessions_router import _BASE, _CSRF_CODEC, _NOW, _Audit, _Auth, _Identity
from tests.unit.auth.session_fakes import FakeSessionRepository

_ORIGIN = "https://app.example"
_FORGED = "forged-" + "f" * 40


def _count(reason: str) -> float:
    sample = "auth_session_fixation_attempts_total"
    return float(REGISTRY.get_sample_value(sample, {"reason": reason}) or 0.0)


class _World:
    def __init__(self, *, budget: int = 20) -> None:
        self.repo = FakeSessionRepository()
        self.hasher = Hasher(pepper=os.urandom(8).hex())
        self.svc = SessionService(self.repo, self.hasher, clock=lambda: _NOW)
        self.audit = _Audit()
        app = FastAPI()
        app.include_router(
            make_session_router(
                _Auth(self.svc),
                self.audit,
                identity=_Identity(),
                allowed_origins=frozenset({_ORIGIN}),
                csrf=_CSRF_CODEC,
                fixation_throttle=PerIpLoginThrottle(max_attempts=budget, window_s=60.0),
            ),
            prefix="/api/v1",
        )
        self.client = TestClient(app, base_url=_BASE)

    def session(self, token: str) -> int:
        r = self.client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
        return int(r.status_code)

    @property
    def rows(self) -> list[dict[str, Any]]:
        events = self.audit.writer.events
        return [e for e in events if e["action"] == "auth.session_fixation_attempt"]


def test_never_issued_bearer_is_401_counted_and_audited_without_the_token() -> None:
    w, before = _World(), _count("unknown_token")
    assert w.session(_FORGED) == 401
    (row,) = w.rows
    assert (row["reason"], row["outcome"], row["severity"]) == (
        "unknown_token",
        AuditOutcome.DENIED,
        Severity.WARNING,
    )
    assert row["after_state"] == {"vector": "bearer", "path": "/auth/session"}
    assert row["actor_user_id"] is None and _FORGED not in repr(w.audit.writer.events)
    assert _count("unknown_token") - before == 1


async def test_expired_or_revoked_token_of_a_real_session_is_not_an_attempt() -> None:
    w, before = _World(), _count("unknown_token")
    earlier = SessionService(w.repo, w.hasher, clock=lambda: _NOW - timedelta(minutes=30))
    expired = await earlier.mint(str(uuid.uuid4()))
    revoked = await w.svc.mint(str(uuid.uuid4()))
    await w.svc.revoke(str(revoked.session_id), reason="logout")
    assert w.session(expired.access_token) == w.session(revoked.access_token) == 401
    assert w.rows == [] and _count("unknown_token") == before


@pytest.mark.parametrize("vector", ["refresh_body", "refresh_cookie"])
def test_never_issued_refresh_token_is_401_and_audited_per_vector(vector: str) -> None:
    w = _World()
    if vector == "refresh_body":
        r = w.client.post("/api/v1/auth/refresh", json={"refresh_token": _FORGED})
    else:
        headers = {"Cookie": f"{REFRESH_COOKIE}={_FORGED}", "Origin": _ORIGIN}
        r = w.client.post("/api/v1/auth/refresh", headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "refresh_token_invalid"
    (row,) = w.rows
    assert row["after_state"] == {"vector": vector, "path": "/auth/refresh"}


def test_attempts_past_the_per_ip_budget_keep_the_401_counted_but_unaudited() -> None:
    w = _World(budget=2)
    throttled, attempts = _count("audit_throttled"), _count("unknown_token")
    assert [w.session(f"{_FORGED}-{i}") for i in range(3)] == [401, 401, 401]
    assert len(w.rows) == 2
    assert _count("audit_throttled") - throttled == 1
    assert _count("unknown_token") - attempts == 3


def test_unavailable_audit_sink_keeps_the_uniform_401() -> None:
    w, before = _World(), _count("audit_unavailable")
    w.audit.is_active = False
    assert w.session(_FORGED) == 401
    assert w.rows == [] and _count("audit_unavailable") - before == 1
