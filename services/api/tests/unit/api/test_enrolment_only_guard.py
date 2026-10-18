"""HTTP guard for the enrolment-only session (#2295; contract "Enrolment-only session").

The guard runs alone in front of stub handlers that record every hit, so each test proves the
answer and that no handler logic ran. The composed app is covered by
`tests/contract/rbac/test_enrolment_only_matrix.py` and `tests/security/auth/`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from starlette.datastructures import Headers
from structlog.testing import capture_logs

from candleviewer.api import csrf as csrf_module
from candleviewer.api import sessions as sessions_module
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.csrf import RefusalAuditTracker
from candleviewer.api.deny_by_default import declared_operations
from candleviewer.api.enrolment_guard import (
    ENROLMENT_OPERATIONS,
    REFUSAL_ACTION,
    EnrolmentRefusals,
    make_enrolment_only_guard,
    sessionless_operations,
)
from candleviewer.api.session_snapshot import SessionSnapshotResolver
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import (
    AuthServiceUnavailable,
    SessionIdleLocked,
    SessionNotFound,
    SessionRevoked,
)
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionClass
from candleviewer.auth.throttle import PerIpLoginThrottle

_NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_CODE = "mfa_enrollment_required"
_OTHER = uuid.UUID("00000000-0000-4000-8000-000000000a01")  # fixed: node ids are stable
_SPEC = cast(dict[str, Any], load_openapi_spec())
_OPERATIONS = frozenset(declared_operations(_SPEC))
_SESSIONLESS = sessionless_operations(_SPEC)
_MATRIX = Path(__file__).resolve().parents[2] / "contract" / "rbac" / "matrix.yaml"
#: Rows the contract serves anonymously but the matrix marks `public: false`; each names its issue.
#: #3419 made the backup download token-addressed; its row and enrolment-only bearer wait on #3500.
_CONTRACT_AHEAD_OF_MATRIX = {"GET /admin/backups/{backupId}/download/{token}": "#3500"}
_VERDICTS = {
    "enrolling": SessionClass.ENROLMENT_ONLY,
    "full": SessionClass.FULL,
    "overlong": SessionClass.ENROLMENT_ONLY_EXPIRED,
    "inactive": SessionClass.USER_INACTIVE,
}
_USERS = {who: uuid.uuid5(_OTHER, who) for who in _VERDICTS}
_REVOKE_OTHER = f"/me/sessions/{uuid.uuid5(_OTHER, 'session')}"
#: Outside the allow-list, and each needs a session: self-service, owner-only, dangerous,
#: cross-user.
_PROTECTED = (
    ("GET", "/auth/sessions"),
    ("DELETE", _REVOKE_OTHER),
    ("GET", "/admin/audit"),
    ("POST", f"/users/{_OTHER}/mfa/reset"),
)
#: Served without a session: the contract's pre-session and public operations, an operational
#: route. A bearer, even an enrolment-only one, changes nothing there.
_NO_SESSION = (
    ("POST", "/auth/login"),
    ("POST", "/auth/mfa/verify"),
    ("POST", "/auth/mfa/recovery"),
    ("GET", "/health/live"),
    ("GET", "/invites/inv-tok"),
    ("POST", "/invites/inv-tok/confirm"),
    ("GET", "/healthz"),
)
_ROUTES = (
    *sorted(ENROLMENT_OPERATIONS),
    ("GET", "/auth/sessions"),
    ("DELETE", "/me/sessions/{sessionId}"),
    ("GET", "/admin/audit"),
    ("POST", "/users/{userId}/mfa/reset"),
    ("POST", "/auth/login"),
    ("POST", "/auth/mfa/verify"),
    ("POST", "/auth/mfa/recovery"),
    ("GET", "/health/live"),
    ("GET", "/invites/{inviteToken}"),
    ("POST", "/invites/{inviteToken}/confirm"),
    ("GET", "/healthz"),
)


class _Auth:
    """The guard's view of `AuthService`: the session resolver plus the one classification."""

    def __init__(self) -> None:
        self.enrolment_gate_is_active = True
        self.dead: dict[str, Exception] = {}
        self.locked: set[str] = set()
        self.failure: Exception | None = None
        self.lookup_failure: Exception | None = None
        self.authenticated: list[str] = []
        self.classified: list[uuid.UUID] = []
        self.sessions = self

    async def authenticate_access_token(
        self, raw_access_token: str, *, allow_locked: bool = False
    ) -> SessionRecord:
        self.authenticated.append(raw_access_token)
        if self.lookup_failure is not None:
            raise self.lookup_failure
        who = raw_access_token.removeprefix("tok-")
        if raw_access_token in self.locked and not allow_locked:
            raise SessionIdleLocked("locked")
        if raw_access_token in self.dead or who not in _USERS:
            raise self.dead.get(raw_access_token, SessionNotFound("unknown token"))
        expires_at = _NOW + timedelta(minutes=15)
        return SessionRecord.model_construct(
            user_id=_USERS[who], id=uuid.uuid5(_USERS[who], "session"), expires_at=expires_at
        )

    async def classify(self, session: SessionRecord) -> SessionClass:
        self.classified.append(session.user_id)
        if self.failure is not None:
            raise self.failure
        return next(_VERDICTS[w] for w, u in _USERS.items() if u == session.user_id)


class _Audit:
    """The audit writer as the guard reaches it; refuses an unregistered action like the real
    `AuditWriter.emit`, so every asserted record is one production would write."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.failure: Exception | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)
        if self.failure is not None:
            raise self.failure
        self.records.append({"action": action, **kw})


def _refusals(audit: _Audit, *, budget: int = 20, cap: int = 64) -> EnrolmentRefusals:
    throttle = PerIpLoginThrottle(max_attempts=budget, window_s=60.0)
    return EnrolmentRefusals(audit, tracker=RefusalAuditTracker(cap), per_user=throttle)


def _guard(auth: _Auth, refusals: EnrolmentRefusals) -> Any:
    return make_enrolment_only_guard(
        auth, refusals=refusals, operations=_OPERATIONS, sessionless=_SESSIONLESS
    )


class _World:
    def __init__(self, *, root_path: str = "", budget: int = 20) -> None:
        self.auth = _Auth()
        self.audit = _Audit()
        self.hits: list[tuple[str, str]] = []
        app = FastAPI()
        for method, path in _ROUTES:
            app.add_api_route(path, self._handler(method, path), methods=[method])
        app.middleware("http")(_guard(self.auth, _refusals(self.audit, budget=budget)))
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


def _count(transport: str, reason: str) -> float:
    """`auth_enrolment_refused_total{transport, reason}` on the process-default registry."""
    labels = {"transport": transport, "reason": reason}
    return float(REGISTRY.get_sample_value("auth_enrolment_refused_total", labels) or 0.0)


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
    forbidden = _SPEC["components"]["responses"]["Forbidden"]["content"]["application/problem+json"]
    expected = dict(forbidden["examples"]["mfaEnrollmentRequired"]["value"])
    del expected["instance"]
    assert world.call("GET", "/auth/sessions").json() == expected
    text = " ".join(_SPEC["info"]["description"].split())
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


# -- operations that need no session -----------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), _NO_SESSION)
def test_guard_leaves_an_operation_that_needs_no_session_alone(
    world: _World, method: str, path: str
) -> None:
    """Contract: only operations "that need a session" are refused, so a client still holding
    the 15-minute token can sign in again, and a carried bearer reaches the E09-X02 audit."""
    resp = world.call(method, path)

    assert resp.status_code == 200
    assert len(world.hits) == 1
    assert world.auth.authenticated == []  # not even looked up


@pytest.mark.parametrize(
    "request_line",
    ["PUT /auth/login", "POST /auth/login/x", "GET /invites/a/b", "POST /health/live"],
)
def test_guard_matches_a_sessionless_operation_on_its_method_and_template(
    world: _World, request_line: str
) -> None:
    assert _refused(world.call(*request_line.split(" ")))


def test_sessionless_operations_are_the_matrix_public_rows() -> None:
    """The reviewed RBAC matrix (SR-018) marks exactly these rows `public: true`, except the
    issue-linked rows the contract has opened ahead of it."""
    with _MATRIX.open(encoding="utf-8") as fh:
        rows: dict[str, dict[str, Any]] = yaml.safe_load(fh)["operations"]
    public = {key for key, row in rows.items() if row.get("public") is True}
    lagging = set(_CONTRACT_AHEAD_OF_MATRIX)

    assert lagging.isdisjoint(public)  # an exception the matrix has caught up with must go
    assert {f"{method} {path}" for method, path in _SESSIONLESS} == public | lagging


# -- what the guard leaves alone ---------------------------------------------------------------


@pytest.mark.parametrize("who", ["full", "inactive"])  # inactive: the route's #2911 check answers
@pytest.mark.parametrize(("method", "path"), _PROTECTED)
def test_guard_cross_user_a_full_session_is_never_restricted(
    world: _World, method: str, path: str, who: str
) -> None:
    assert world.call(method, path, who).status_code == 200
    assert world.auth.classified == [_USERS[who]]  # its own user, nobody else's


@pytest.mark.parametrize("header", ["", "Basic dG9r", "Bearer ", "tok-enrolling"])
def test_guard_without_a_bearer_token_leaves_the_answer_to_the_route(
    world: _World, header: str
) -> None:
    assert world.client.get("/auth/sessions", headers={"Authorization": header}).status_code == 200
    assert world.auth.authenticated == []


def test_guard_reads_the_bearer_scheme_case_insensitively(world: _World) -> None:
    resp = world.client.get("/auth/sessions", headers={"Authorization": "bearer tok-enrolling"})

    assert _refused(resp)


class _TokenRecorder:
    """A session store that records the token it is asked for and knows none."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def authenticate_access_token(self, token: str, **_kw: Any) -> SessionRecord:
        self.tokens.append(token)
        raise SessionNotFound("recorded only")


def _request(header: str) -> Request:
    headers = [(b"authorization", header.encode())] if header else []
    scope = {"type": "http", "method": "GET", "path": "/auth/sessions", "headers": headers}
    return Request(scope)


async def _ok(request: Request) -> Response:
    return Response(status_code=204)


@pytest.mark.parametrize(
    "header",
    [
        "Bearer tok-enrolling",
        "bearer tok-enrolling",
        "BEARER tok-enrolling",
        "Bearer  tok-enrolling",
        "Bearer tok-enrolling ",
        "Bearer tok-enrolling extra",
        "Bearer\ttok-enrolling",
        " Bearer tok-enrolling",
        "Bearer",
        "Bearer ",
        "Basic tok-enrolling",
        "tok-enrolling",
        "",
    ],
)
async def test_guard_reads_the_bearer_exactly_as_the_route_resolvers_do(header: str) -> None:
    """A parse that drifted from the routes' would let a token past the guard that a route
    then accepts. The RBAC routes' resolver, the session routes and the CSRF binding agree."""
    request = _request(header)
    resolver_store: Any = _TokenRecorder()  # the resolver's session seam, structurally
    await SessionSnapshotResolver(lambda: resolver_store, cast(Any, None)).resolve(request)
    routes_see = sessions_module._bearer(request)
    auth = _Auth()

    await _guard(auth, _refusals(_Audit()))(request, _ok)

    assert auth.authenticated == resolver_store.tokens
    assert auth.authenticated == ([] if routes_see is None else [routes_see])
    assert csrf_module._bearer(Headers(scope=request.scope)) == routes_see


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
    """No session store wired: nothing authenticates, so no enrolment-only session exists."""
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


@pytest.mark.parametrize(
    "failure", [OSError("session store unreachable"), RuntimeError("pool closed"), TimeoutError()]
)
@pytest.mark.parametrize("path", ["/auth/sessions", "/auth/session"])
def test_guard_fails_closed_when_the_session_lookup_errors(
    world: _World, failure: Exception, path: str
) -> None:
    """Any failure of the lookup other than "no live session" is the documented 503 problem,
    never a plain-text 500 and never a pass to the route."""
    world.auth.lookup_failure = failure

    resp = world.call("GET", path, "full")

    assert _refused(resp, 503, "store_unavailable")
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["retry-after"] == "5"
    assert "unreachable" not in resp.text and "pool" not in resp.text
    assert world.hits == [] and world.auth.classified == []


@pytest.mark.parametrize("request_line", ["GET /auth/session", "POST /auth/mfa/enroll"])
def test_guard_refuses_an_overlong_enrolment_only_session_like_an_expired_one(
    world: _World, request_line: str
) -> None:
    method, path = request_line.split(" ")

    assert _refused(world.call(method, path, "overlong"), 401, "unauthenticated")
    assert world.call("POST", "/auth/logout", "overlong").status_code == 200  # sign-out stays
    assert world.hits == [("POST", "/auth/logout")]


# -- the security trail: metric, log line, audit record (SR-125, C-2.9) ------------------------


def test_guard_refusal_is_audited_with_the_actor_session_and_route_template(
    world: _World,
) -> None:
    world.call("DELETE", _REVOKE_OTHER)

    (record,) = world.audit.records
    assert record == {
        "action": REFUSAL_ACTION,
        "actor_label": str(_USERS["enrolling"]),
        "actor_user_id": _USERS["enrolling"],
        "actor_ip": "testclient",
        "session_id": uuid.uuid5(_USERS["enrolling"], "session"),
        "outcome": AuditOutcome.DENIED,
        "severity": Severity.WARNING,
        "reason": _CODE,
        "after_state": {"channel": "http", "method": "DELETE", "path": "/me/sessions/{sessionId}"},
    }


def test_guard_refusal_is_counted_and_logged_with_the_template_never_the_raw_path(
    world: _World,
) -> None:
    before = _count("http", "enrolment_only")

    with capture_logs() as logs:
        world.call("DELETE", _REVOKE_OTHER)

    assert _count("http", "enrolment_only") == before + 1
    (line,) = [e for e in logs if e["event"] == "auth.enrolment_only.refused"]
    assert (line["channel"], line["method"], line["path"]) == (
        "http",
        "DELETE",
        "/me/sessions/{sessionId}",
    )
    assert line["user_id"] == str(_USERS["enrolling"])  # names the account (AGENTS.md 5.2)
    assert _REVOKE_OTHER not in repr(logs)


def test_guard_refusal_audits_stay_within_the_per_user_budget() -> None:
    world = _World(budget=2)
    before = _count("http", "audit_throttled")

    answers = [world.call("GET", "/auth/sessions").json() for _ in range(3)]

    assert answers[0] == answers[1] == answers[2] and answers[0]["code"] == _CODE
    assert [r["action"] for r in world.audit.records] == [REFUSAL_ACTION] * 2
    assert _count("http", "audit_throttled") == before + 1


def test_guard_refusal_answer_never_depends_on_the_audit_write(world: _World) -> None:
    world.audit.failure = RuntimeError("audit store down")
    before = _count("http", "audit_unavailable")

    resp = world.call("GET", "/auth/sessions")

    assert _refused(resp) and "audit" not in resp.text
    assert _count("http", "audit_unavailable") == before + 1


def test_guard_counts_an_overlong_session_as_expired_and_audits_nothing(world: _World) -> None:
    before = _count("http", "expired")

    world.call("GET", "/auth/sessions", "overlong")

    assert _count("http", "expired") == before + 1
    assert world.audit.records == []  # an expired session, not an authorisation denial


def test_guard_counts_a_session_it_cannot_check_as_unclassified(world: _World) -> None:
    world.auth.failure = OSError("user store unreachable")
    before = _count("http", "unclassified")

    with capture_logs() as logs:
        world.call("GET", "/auth/sessions", "full")

    assert _count("http", "unclassified") == before + 1
    (line,) = [e for e in logs if e["event"] == "auth.enrolment_only.unclassified"]
    assert (line["log_level"], line["error"], line["path"]) == (
        "error",
        "OSError",
        "/auth/sessions",
    )


# -- its slot in the composed app --------------------------------------------------------------


def _middleware_name(middleware: Any) -> str:
    dispatch = middleware.kwargs.get("dispatch")
    if dispatch is not None:
        return str(dispatch.__qualname__).split(".")[0]
    return str(getattr(middleware.cls, "__name__", "?"))


def test_guard_sits_between_the_idle_lock_gate_and_the_read_only_guard() -> None:
    """Inside MeshOnly and CSRF (SR-041/SR-042: off-mesh traffic never reaches its session and
    user reads) and inside #2300's idle-lock gate (a locked session meets the lock first, and a
    store failure under the gate keeps the gate's own answer), outside the read-only/step-up
    guard (a refusal records no step-up challenge)."""
    from candleviewer import app as appmod

    order = [_middleware_name(m) for m in appmod.create_app().user_middleware]  # outermost first
    at = order.index("CsrfMiddleware")

    assert order[at : at + 4] == [
        "CsrfMiddleware",
        "IdleLockMiddleware",
        "make_enrolment_only_guard",
        "make_read_only_guard",
    ]
    assert order.index("MeshOnlyMiddleware") < at
