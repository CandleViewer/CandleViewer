"""The world the idle-lock route tests run in (#2300 slice 2/2; contract
`22-api-openapi.yaml` info "Idle lock", B16.7).

A real `SessionService` and a real `StepUpService` (so the real B16 chart records the lock and
the unlock) over in-memory fakes, one fixed clock, recording audit sinks that can fail on chosen
actions, and the router's own SR-041 codec. No DB, no network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import httpx
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.sessions import REFRESH_COOKIE, make_session_router
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession, SessionRecord
from candleviewer.auth.session_chart import SessionChart
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.conftest import RecordingAuditSink
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)
_ORIGIN = "https://app.example.test"
_PW = "unlock-canary-pw-2300"  # test-only literal, never a credential
_WRONG = "wrong-canary-pw-2300"  # test-only literal, never a credential
_CODEC = CsrfCodec(b"\x07" * 32)
#: Cheap Argon2id parameters: verification reads them from the hash, so the tests stay fast.
_CHEAP_ARGON2 = {"m": 8, "t": 1, "p": 1}
#: Minted with the 5 min minimum, a session locks while its 12 min access token still lives.
_IDLE_S = 300
_SPEC_BASE = "urn:cv:openapi"


@cache
def _spec() -> dict[str, Any]:
    return load_openapi_spec()


def _conforms(value: Any, schema: str) -> None:
    resource = Resource.from_contents(_spec(), default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_SPEC_BASE}#/components/schemas/{schema}"},
        registry=Registry().with_resource(_SPEC_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Writer:
    """The router's audit writer: records every emission and, like `AuditWriter.emit`,
    raises `AuditUnavailable` for an action in `fail_on`."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.fail_on: set[str] = set()

    async def emit(self, action: str, **kw: Any) -> None:
        if action in self.fail_on:
            raise AuditUnavailable("audit WAL unavailable: test")
        self.records.append({"action": action, **kw})

    def actions(self) -> list[str]:
        return [r["action"] for r in self.records]


class _Audit:
    def __init__(self) -> None:
        self.writer = _Writer()
        self.is_active = True


class _FailingB16Sink(RecordingAuditSink):
    """The B16 chart's sink, failing on the chosen actions (B16.7 regression tests)."""

    def __init__(self, *fail_on: str) -> None:
        super().__init__()
        self.fail_on = set(fail_on)

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action in self.fail_on:
            raise AuditUnavailable("audit WAL unavailable: test")
        await super().emit(action, **kwargs)


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {
            "id": user_id,
            "username": "trader",
            "email": "trader@example.test",
            "roles": ["manager"],
            "status": "active",
        }

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["accounts:read"], "account_scope": []}


class _Auth:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions
        self.sessions_is_active = True


class World:
    def __init__(
        self, b16: RecordingAuditSink, *, throttle_max: int, authority: bool, identity: bool
    ) -> None:
        self.b16 = b16
        self.clock = _Clock()
        self.repo = FakeSessionRepository()
        self.users = FakeUserRepository()
        self.published: list[tuple[str, str]] = []

        async def publish(session_id: str, reason: str) -> None:
            self.published.append((session_id, reason))

        self.sessions = SessionService(
            self.repo, Hasher(), clock=self.clock, publish_revocation=publish
        )
        self.step_up = StepUpService(
            FakeMfaRepository(),
            self.repo,
            TotpEncryptor(os.urandom(32)),
            self.users,
            Hasher(),
            clock=self.clock,
            chart=SessionChart(),
        )
        self.audit = _Audit()

        app = FastAPI()
        app.include_router(
            make_session_router(
                _Auth(self.sessions),
                self.audit,
                identity=_Identity() if identity else None,
                allowed_origins=frozenset({_ORIGIN}),
                csrf=_CODEC,
                unlock_authority=(lambda: self.step_up) if authority else None,
                unlock_throttle=PerIpLoginThrottle(
                    max_attempts=throttle_max, window_s=60.0, clock=lambda: 0.0
                ),
            ),
            prefix="/api/v1",
        )
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        self.client = httpx.AsyncClient(transport=transport, base_url="https://testserver")

    async def add_user(self, username: str = "trader") -> uuid.UUID:
        hashed = await Hasher().hash(_PW, _CHEAP_ARGON2)
        user = make_user(username=username, email=f"{username}@example.test", password_hash=hashed)
        self.users.add(user)
        return user.id

    async def mint(self, user_id: uuid.UUID, *, idle_timeout_s: int = _IDLE_S) -> MintedSession:
        return await self.sessions.mint(str(user_id), idle_timeout_s=idle_timeout_s)

    def lock(self, seconds: int = _IDLE_S) -> None:
        """Let a session last seen now pass its idle deadline."""
        self.clock.now += timedelta(seconds=seconds + 1)

    async def row(self, minted: MintedSession) -> SessionRecord:
        found = await self.repo.find_by_id(str(minted.session_id))
        assert found is not None
        return found

    def failed_logins(self, user_id: uuid.UUID) -> int:
        return self.users.users[str(user_id)].failed_login_count

    def chart_state(self, minted: MintedSession) -> frozenset[str]:
        return self.step_up.chart.state(str(minted.session_id))


def _bearer(minted: MintedSession, *, csrf_for: uuid.UUID | None = None) -> dict[str, str]:
    """Access token plus the SR-041 pair a browser holds for that session."""
    token = _CODEC.issue(str(csrf_for or minted.session_id))
    return {
        "Authorization": f"Bearer {minted.access_token}",
        CSRF_HEADER: token,
        "Cookie": f"{CSRF_COOKIE}={token}",
    }


def _cookie(
    minted: MintedSession, *, origin: str | None = _ORIGIN, csrf_for: uuid.UUID | None = None
) -> dict[str, str]:
    """Only the `cv_refresh` cookie (a long lock or a reload), the Origin and the SR-041 pair."""
    token = _CODEC.issue(str(csrf_for or minted.session_id))
    headers = {
        CSRF_HEADER: token,
        "Cookie": f"{CSRF_COOKIE}={token}; {REFRESH_COOKIE}={minted.refresh_token}",
    }
    if origin is not None:
        headers["Origin"] = origin
    return headers


async def _unlock(w: World, headers: dict[str, str], password: str = _PW) -> httpx.Response:
    return await w.client.post("/api/v1/auth/unlock", json={"password": password}, headers=headers)


async def _open(
    b16: RecordingAuditSink,
    *,
    throttle_max: int = 100,
    authority: bool = True,
    identity: bool = True,
) -> World:
    return World(b16, throttle_max=throttle_max, authority=authority, identity=identity)


async def _session(w: World, headers: dict[str, str]) -> httpx.Response:
    return await w.client.get("/api/v1/auth/session", headers=headers)
