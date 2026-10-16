"""HTTP guard for the enrolment-only session (#2295 slice 2/3; contract "Enrolment-only session").

The guard runs alone in front of stub handlers that record every hit, so each test proves the
answer and that no handler logic ran. The composed app is covered by
`tests/contract/rbac/test_enrolment_only_matrix.py` and `tests/security/auth/`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.enrolment_guard import ENROLMENT_OPERATIONS, make_enrolment_only_guard
from candleviewer.auth.errors import (
    AuthServiceUnavailable,
    SessionIdleLocked,
    SessionNotFound,
    SessionRevoked,
)
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionClass

_NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_CODE = "mfa_enrollment_required"
_OTHER = uuid.uuid4()
_VERDICTS = {
    "enrolling": SessionClass.ENROLMENT_ONLY,
    "full": SessionClass.FULL,
    "overlong": SessionClass.ENROLMENT_ONLY_EXPIRED,
}
_USERS = {who: uuid.uuid4() for who in _VERDICTS}
#: Outside the allow-list: self-service, owner-only, dangerous, cross-user, pre-session.
_PROTECTED = (
    ("GET", "/auth/sessions"),
    ("DELETE", f"/me/sessions/{uuid.uuid5(_OTHER, 'session')}"),
    ("GET", "/admin/audit"),
    ("POST", f"/users/{_OTHER}/mfa/reset"),
    ("POST", "/auth/login"),
)
_ROUTES = (
    *sorted(ENROLMENT_OPERATIONS),
    ("GET", "/auth/sessions"),
    ("DELETE", "/me/sessions/{sessionId}"),
    ("GET", "/admin/audit"),
    ("POST", "/users/{userId}/mfa/reset"),
    ("POST", "/auth/login"),
)


class _Auth:
    """The guard's view of `AuthService`: the session resolver plus the one classification."""

    def __init__(self) -> None:
        self.enrolment_gate_is_active = True
        self.dead: dict[str, Exception] = {}
        self.locked: set[str] = set()
        self.failure: Exception | None = None
        self.authenticated: list[str] = []
        self.classified: list[uuid.UUID] = []
        self.sessions = self

    async def authenticate_access_token(
        self, raw_access_token: str, *, allow_locked: bool = False
    ) -> SessionRecord:
        self.authenticated.append(raw_access_token)
        who = raw_access_token.removeprefix("tok-")
        if raw_access_token in self.locked and not allow_locked:
            raise SessionIdleLocked("locked")
        if raw_access_token in self.dead or who not in _USERS:
            raise self.dead.get(raw_access_token, SessionNotFound("unknown token"))
        expires_at = _NOW + timedelta(minutes=15)
        return SessionRecord.model_construct(
            user_id=_USERS[who], id=uuid.uuid4(), expires_at=expires_at
        )

    async def classify(self, session: SessionRecord) -> SessionClass:
        self.classified.append(session.user_id)
        if self.failure is not None:
            raise self.failure
        return next(_VERDICTS[w] for w, u in _USERS.items() if u == session.user_id)


class _World:
    def __init__(self, *, root_path: str = "") -> None:
        self.auth = _Auth()
        self.hits: list[tuple[str, str]] = []
        app = FastAPI()
        for method, path in _ROUTES:
            app.add_api_route(path, self._handler(method, path), methods=[method])
        app.middleware("http")(make_enrolment_only_guard(self.auth))
        self.client = TestClient(app, root_path=root_path, raise_server_exceptions=False)

    def _handler(self, method: str, path: str) -> Any:
        async def handler(request: Request) -> JSONResponse:
            self.hits.append((method, path))
            return JSONResponse({"ok": True})

        return handler

    def call(self, method: str, path: str, who: str = "enrolling") -> Any:
        return self.client.request(method, path, headers={"Authorization": f"Bearer tok-{who}"})


@pytest.fixture
def world() -> _World:
    return _World()


def _refused(resp: Any, status: int = 403, code: str = _CODE) -> bool:
    return bool(resp.status_code == status and resp.json()["code"] == code)


# -- the allow-list ----------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), sorted(ENROLMENT_OPERATIONS))
def test_guard_admits_each_allow_listed_operation(world: _World, method: str, path: str) -> None:
    assert world.call(method, path).status_code == 200
    assert world.hits == [(method, path)]


@pytest.mark.parametrize(("method", "path"), _PROTECTED)
def test_guard_refuses_every_other_operation_before_its_handler(
    world: _World, method: str, path: str
) -> None:
    resp = world.call(method, path)

    assert _refused(resp)
    assert resp.headers["content-type"] == "application/problem+json"
    assert world.hits == []  # no handler logic ran: nothing changed


def test_guard_refusal_and_allow_list_are_the_contracts(world: _World) -> None:
    spec = cast(dict[str, Any], load_openapi_spec())
    forbidden = spec["components"]["responses"]["Forbidden"]["content"]["application/problem+json"]
    expected = dict(forbidden["examples"]["mfaEnrollmentRequired"]["value"])
    del expected["instance"]
    assert world.call("GET", "/auth/sessions").json() == expected
    text = " ".join(spec["info"]["description"].split())
    start = text.index("**Allowed operations.**")
    bullet = text[start : text.index("* **", start)]
    named = set(re.findall(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`]+)`", bullet))
    assert named == ENROLMENT_OPERATIONS


@pytest.mark.parametrize(
    "request_line",
    ["POST /auth/session", "GET /auth/logout", "GET /auth/session/", "POST /auth/mfa/enrollx"],
)
def test_guard_allow_list_matches_method_and_exact_path(world: _World, request_line: str) -> None:
    assert _refused(world.call(*request_line.split(" ")))
    assert world.hits == []


def test_guard_matches_the_routed_path_under_a_root_path() -> None:
    """#2752 parity: the path the router matches, not the raw URL path."""
    world = _World(root_path="/api/v1")

    assert world.call("GET", "/api/v1/auth/session").status_code == 200
    assert _refused(world.call("GET", "/api/v1/auth/sessions"))
    assert world.hits == [("GET", "/auth/session")]


# -- what the guard leaves alone ---------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), _PROTECTED)
def test_guard_cross_user_a_full_session_is_never_restricted(
    world: _World, method: str, path: str
) -> None:
    assert world.call(method, path, "full").status_code == 200
    assert world.auth.classified == [_USERS["full"]]  # its own user, nobody else's


@pytest.mark.parametrize("header", ["", "Basic dG9r", "Bearer ", "tok-enrolling"])
def test_guard_without_a_bearer_token_leaves_the_answer_to_the_route(
    world: _World, header: str
) -> None:
    assert world.client.get("/auth/sessions", headers={"Authorization": header}).status_code == 200
    assert world.auth.authenticated == []
    lower = world.client.get("/auth/sessions", headers={"Authorization": "bearer tok-enrolling"})
    assert _refused(lower)  # the scheme is case-insensitive


@pytest.mark.parametrize("error", [SessionNotFound("x"), SessionRevoked("x")])
def test_guard_leaves_a_token_without_a_live_session_to_the_route(
    world: _World, error: Exception
) -> None:
    world.auth.dead["tok-enrolling"] = error

    assert world.call("GET", "/auth/sessions").status_code == 200
    assert world.auth.classified == []


def test_guard_classifies_an_idle_locked_session_too(world: _World) -> None:
    """`DELETE /me/sessions/{sessionId}` accepts a locked session, so the guard must not defer."""
    world.auth.locked.add("tok-enrolling")

    assert _refused(world.call(*_PROTECTED[1]))
    assert world.hits == []


def test_guard_is_inert_until_the_auth_module_can_classify(world: _World) -> None:
    """No user store wired: the fake backend, where no session can authenticate either."""
    world.auth.enrolment_gate_is_active = False

    assert world.call("GET", "/auth/sessions").status_code == 200
    assert world.auth.authenticated == []


# -- fail closed and the 15-minute lifetime ----------------------------------------------------


@pytest.mark.parametrize(
    "failure", [OSError("user store unreachable"), AuthServiceUnavailable("x"), KeyError("x")]
)
@pytest.mark.parametrize("path", ["/auth/sessions", "/auth/session"])
def test_guard_fails_closed_when_the_classification_errors(
    world: _World, failure: Exception, path: str
) -> None:
    world.auth.failure = failure

    resp = world.call("GET", path, "full")

    assert _refused(resp, 503, "store_unavailable")
    assert resp.headers["retry-after"] == "5"
    assert "unreachable" not in resp.text  # the failure never reaches the client
    assert world.hits == []


@pytest.mark.parametrize("request_line", ["GET /auth/session", "POST /auth/mfa/enroll"])
def test_guard_refuses_an_overlong_enrolment_only_session_like_an_expired_one(
    world: _World, request_line: str
) -> None:
    method, path = request_line.split(" ")

    assert _refused(world.call(method, path, "overlong"), 401, "unauthenticated")
    assert world.call("POST", "/auth/logout", "overlong").status_code == 200  # sign-out stays
    assert world.hits == [("POST", "/auth/logout")]
