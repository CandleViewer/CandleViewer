"""HTTP-level tests for the E09-S03 session routes (QA #1634): refresh rotation,
reuse detection, logout, listing, IDOR and unauthenticated access. No DB/network."""

from __future__ import annotations

import ast
import os
import uuid
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import candleviewer
import candleviewer.api.query_allowlist as allowlist_module
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.sessions import (
    GET_SESSION_QUERY,
    LIST_SESSIONS_QUERY,
    REFRESH_COOKIE,
    make_session_router,
)
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import SessionClass, SessionService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.csrf_helpers import arm_csrf
from tests.unit.auth.session_fakes import FakeSessionRepository

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)  # SR-041 (#2090): routers require a codec

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
_BASE = "https://testserver"


class _Auth:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions
        self.sessions_is_active = True
        self.enrolment_gate_is_active = False  # no user store here (#2295)

    async def classify(self, session: SessionRecord) -> SessionClass:
        raise AssertionError("the enrolment-only gate is inert without a user store")


class _Writer:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.events.append({"action": action, **kw})


class _Audit:
    is_active = True

    def __init__(self) -> None:
        self.writer = _Writer()


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "u", "roles": ["owner"]}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"], "account_scope": []}


class _Env:
    def __init__(
        self,
        *,
        identity: bool = True,
        origins: frozenset[str] = frozenset(),
        throttle_max: int = 10,
        audit: Any = None,
    ) -> None:
        self.repo = FakeSessionRepository()
        self.revoked: list[tuple[str, str]] = []

        async def publish(sid: str, reason: str) -> None:
            self.revoked.append((sid, reason))

        # #2272: the service publishes every revocation; the router no longer does.
        self.svc = SessionService(
            self.repo,
            Hasher(pepper=os.urandom(16).hex()),
            clock=lambda: _NOW,
            publish_revocation=publish,
        )
        self.audit = audit if audit is not None else _Audit()
        self.t = 0.0
        self.identity = _Identity() if identity else None
        app = FastAPI()
        app.include_router(
            make_session_router(
                _Auth(self.svc),
                self.audit,
                identity=self.identity,
                allowed_origins=origins,
                ip_throttle=PerIpLoginThrottle(
                    max_attempts=throttle_max, window_s=60.0, clock=lambda: self.t
                ),
                session_throttle=PerIpLoginThrottle(
                    max_attempts=throttle_max, window_s=60.0, clock=lambda: self.t
                ),
                csrf=_CSRF_CODEC,
            ),
            prefix="/api/v1",
        )
        self.client = TestClient(app, base_url=_BASE)

    async def mint(self, user: uuid.UUID) -> Any:
        """Mint a session and hold its SR-041 token, as the browser holds the
        `__Host-cv_csrf` cookie issued at login (refresh verifies it, #2090)."""
        minted = await self.svc.mint(str(user))
        arm_csrf(self.client, _CSRF_CODEC, minted.session_id)
        return minted


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def env() -> _Env:
    return _Env()


async def test_unauthenticated_routes_return_401(env: _Env) -> None:
    for method, path in [
        ("GET", "/api/v1/auth/session"),
        ("GET", "/api/v1/auth/sessions"),
        ("POST", "/api/v1/auth/logout"),
        ("DELETE", f"/api/v1/me/sessions/{uuid.uuid4()}"),
    ]:
        assert env.client.request(method, path).status_code == 401, path


async def test_refresh_rotates_and_sets_strict_cookie(env: _Env) -> None:
    m = await env.mint(uuid.uuid4())
    r = env.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "authenticated"
    assert body["tokens"]["access_token"] != m.access_token
    cookie = r.headers["set-cookie"]
    assert REFRESH_COOKIE in cookie
    for attr in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth"):
        assert attr.lower() in cookie.lower()


async def test_refresh_reuse_is_401_with_critical_audit(env: _Env) -> None:
    m = await env.mint(uuid.uuid4())
    assert (
        env.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token}).status_code
        == 200
    )
    env.client.cookies.clear()  # the client would otherwise replay the rotated cookie
    r = env.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token})
    assert r.status_code == 401
    ev = env.audit.writer.events[-1]
    assert ev["action"] == "auth.refresh_reuse_detected"
    assert ev["severity"] == Severity.CRITICAL
    assert ev["outcome"] == AuditOutcome.DENIED


async def test_refresh_of_a_disabled_user_is_401_audited_and_rotates_nothing(env: _Env) -> None:
    """#2911: refused before the claim (nothing rotated or minted); the refusal is audited
    after the write-ahead intent, like the concurrent-reuse outcome."""
    user = uuid.uuid4()
    m = await env.mint(user)
    env.repo.user_statuses[str(user)] = UserStatus.DISABLED

    r = env.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token})

    assert (r.status_code, r.json()["detail"]) == (401, "refresh_token_invalid")
    assert "set-cookie" not in r.headers
    assert [(e["action"], e["outcome"]) for e in env.audit.writer.events] == [
        ("auth.session_refreshed", AuditOutcome.SUCCESS),
        ("auth.session_refreshed", AuditOutcome.DENIED),
    ]
    refused = env.audit.writer.events[-1]
    assert (refused["reason"], refused["severity"]) == ("user_disabled", Severity.WARNING)
    assert refused["session_id"] == m.session_id
    assert list(env.repo.sessions) == [str(m.session_id)]
    assert env.repo.sessions[str(m.session_id)].revoked_at is None


async def test_a_disabled_users_live_session_is_401_and_revoked_on_use(env: _Env) -> None:
    """#2911 (`require_active`): REST answers 401; the row is revoked `user_disabled` and its
    id published, which the hub turns into `bye user_disabled` + 4403."""
    user = uuid.uuid4()
    m = await env.mint(user)
    env.repo.user_statuses[str(user)] = UserStatus.DISABLED

    assert env.client.get("/api/v1/auth/session", headers=_h(m.access_token)).status_code == 401

    assert env.repo.sessions[str(m.session_id)].revoked_reason == "user_disabled"
    assert env.revoked == [(str(m.session_id), "user_disabled")]


def _route_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """`METHOD /path` from the function's `@router.<method>("/path")`; `None` for a helper."""
    for deco in fn.decorator_list:
        if (
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and deco.args
            and isinstance(deco.args[0], ast.Constant)
        ):
            return f"{deco.func.attr.upper()} {deco.args[0].value!s}"
    return None


#: Lookups that find a session and read nothing of its user's status (#3214, #2300).
_STATUS_BLIND = frozenset({"_identify", "peek_access_token", "peek_refresh"})


class _SkipsBackstop(ast.NodeVisitor):
    """The functions that act for a session without `require_active`, in either of two ways
    (a route is reported as `METHOD /path`, a helper by its name):

    - they find their session with a lookup that reads no user status, `_identify` (the access
      token, else the `cv_refresh` cookie) or, in a route, `peek_access_token` or
      `peek_refresh`, and never call `require_active`. A peek in a helper does not count:
      helpers peek to name a session in an audit record, bind a CSRF token or tell a fixation
      attempt, and act for none. `refresh` clears a peeked refresh token, the refresh route's:
      `SessionService.refresh` refuses a disabled user's token itself (#2911; U45);
    - they pass `allow_locked=True` to anything but `require_active`: a call that takes it skips
      `require_active` with it, so a stray session is not revoked there.
      `require_active(..., allow_locked=True)` waives the idle lock and nothing else: its status
      check still runs, so a route that only calls it does not skip the backstop."""

    def __init__(self) -> None:
        self.routes: set[str] = set()
        self._scope: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, set[str]]] = []

    def _enter(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        calls: set[str] = set()
        self._scope.append((node, calls))
        self.generic_visit(node)
        self._scope.pop()
        route = _route_of(node)
        blind = calls & (_STATUS_BLIND if route else {"_identify"})
        if "refresh" in calls:
            blind -= {"peek_refresh"}
        if blind and "require_active" not in calls:
            self.routes.add(route or node.name)

    visit_FunctionDef = visit_AsyncFunctionDef = _enter

    def visit_Call(self, node: ast.Call) -> None:
        callee = ast.unparse(node.func).rpartition(".")[2]
        if self._scope:
            self._scope[-1][1].add(callee)
        if callee != "require_active" and any(
            k.arg == "allow_locked" and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in node.keywords
        ):
            fn = self._scope[-1][0] if self._scope else None
            self.routes.add("(module level)" if fn is None else _route_of(fn) or fn.name)
        self.generic_visit(node)


@pytest.mark.parametrize(
    ("call", "routes"),
    [
        ("_authenticate(request, allow_locked=True)", {"GET /a"}),
        ("sessions.authenticate_access_token(token, allow_locked=True)", {"GET /a"}),
        ("sessions.require_active(sid, allow_locked=True)", set()),
    ],
)
def test_the_route_scan_flags_what_skips_the_backstop_and_not_what_only_waives_the_lock(
    call: str, routes: set[str]
) -> None:
    """`require_active(..., allow_locked=True)` waives the idle lock and still checks the user's
    status (#3214's `GET /auth/session` reads through it), so it is not a skip."""
    scan = _SkipsBackstop()
    scan.visit(ast.parse(f"@router.get('/a')\nasync def a(request):\n    return await {call}\n"))

    assert scan.routes == routes


@pytest.mark.parametrize(
    ("body", "routes"),
    [
        ("return await _identify(request)", {"POST /a"}),
        ("return await sessions.peek_access_token(token)", {"POST /a"}),
        ("return await sessions.peek_refresh(cookie)", {"POST /a"}),
        ("await _identify(request)\n    return await sessions.refresh(raw)", {"POST /a"}),
        ("await _identify(request)\n    return await sessions.require_active(sid)", set()),
        ("await sessions.peek_refresh(raw)\n    return await sessions.refresh(raw)", set()),
    ],
)
def test_the_route_scan_flags_a_lookup_that_reads_no_user_status_without_require_active(
    body: str, routes: set[str]
) -> None:
    """#2300's logout finds its session with `_identify`, whose peeks read no user status, so it
    skips the backstop with no `allow_locked=True` anywhere; `GET /auth/session` follows
    `_identify` with `require_active` and does not. `refresh` clears only a peeked refresh token."""
    scan = _SkipsBackstop()
    scan.visit(ast.parse(f"@router.post('/a')\nasync def a(request):\n    {body}\n"))

    assert scan.routes == routes


def test_the_route_scan_counts_a_peek_in_a_route_only_and_names_a_helper_on_identify() -> None:
    """Helpers peek and act for no session (`session_of` in `api/users.py`,
    `CsrfMiddleware._resolve`, `_authenticate`'s fixation check); a helper built on `_identify`
    without `require_active` is reported by its name, so a route calling it is found too."""
    scan = _SkipsBackstop()
    scan.visit(
        ast.parse(
            "async def peeks(token):\n    return await sessions.peek_access_token(token)\n"
            "async def identifies(request):\n    return await _identify(request)\n"
        )
    )

    assert scan.routes == {"identifies"}


def test_only_these_routes_skip_the_backstop() -> None:
    """U45 (`e09-auth-rbac.md`) and runbook section 4 (`auth-rbac.md`) say every REST route meets
    `require_active` first, so refuses and revokes a disabled user's live session, except the ones
    that only end the caller's own sessions, and name them: these. A route skips it in either way
    `_SkipsBackstop` finds, so one more makes both texts wrong. The scan reads each route's own
    code, whatever it is mounted behind (#2300 moved the logout from `allow_locked=True` to the
    `_identify` way)."""
    found = _SkipsBackstop()
    for path in sorted(Path(candleviewer.__file__).resolve().parent.rglob("*.py")):
        with warnings.catch_warnings():  # escape-sequence noise from unrelated modules
            warnings.simplefilter("ignore", SyntaxWarning)
            found.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))

    # `enrolment_only_guard` (`api/enrolment_guard.py`, #2295) is middleware, not a route: it reads
    # a session with `allow_locked=True` only to classify it; a disabled user's goes to the route.
    routes = {"POST /auth/logout", "DELETE /me/sessions/{sessionId}", "enrolment_only_guard"}
    assert found.routes == routes


async def test_refresh_without_identity_is_501_and_burns_no_token() -> None:
    e = _Env(identity=False)
    m = await e.mint(uuid.uuid4())
    assert (
        e.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token}).status_code
        == 501
    )
    assert e.client.get("/api/v1/auth/sessions", headers=_h(m.access_token)).status_code == 200


async def test_cross_origin_cookie_refresh_is_refused(env: _Env) -> None:
    m = await env.mint(uuid.uuid4())
    r = env.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


async def test_same_host_origin_not_on_allow_list_is_refused() -> None:
    env = _Env(origins=frozenset({"http://app.example"}))
    m = await env.mint(uuid.uuid4())
    r = env.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": "http://testserver", "Host": "testserver"},
    )
    assert r.status_code == 403


async def test_list_sessions_is_scoped_to_caller(env: _Env) -> None:
    me, other = uuid.uuid4(), uuid.uuid4()
    a = await env.mint(me)
    await env.mint(me)
    await env.mint(other)
    r = env.client.get("/api/v1/auth/sessions", headers=_h(a.access_token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert sum(i["current"] for i in items) == 1


async def test_revoke_other_users_session_is_404_idor(env: _Env) -> None:
    mine = await env.mint(uuid.uuid4())
    theirs = await env.mint(uuid.uuid4())
    r = env.client.delete(f"/api/v1/me/sessions/{theirs.session_id}", headers=_h(mine.access_token))
    assert r.status_code == 404
    assert env.revoked == []
    assert (
        env.client.get("/api/v1/auth/sessions", headers=_h(theirs.access_token)).status_code == 200
    )


async def test_revoke_own_other_session_publishes_revocation(env: _Env) -> None:
    user = uuid.uuid4()
    a = await env.mint(user)
    b = await env.mint(user)
    r = env.client.delete(f"/api/v1/me/sessions/{b.session_id}", headers=_h(a.access_token))
    assert r.status_code == 204
    assert env.revoked == [(str(b.session_id), "user_revoked")]
    assert env.client.get("/api/v1/auth/session", headers=_h(b.access_token)).status_code == 401


async def test_logout_all_revokes_every_session_and_clears_cookie(env: _Env) -> None:
    user = uuid.uuid4()
    a = await env.mint(user)
    b = await env.mint(user)
    r = env.client.post(
        "/api/v1/auth/logout", json={"all_sessions": True}, headers=_h(a.access_token)
    )
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert {sid for sid, _ in env.revoked} == {str(a.session_id), str(b.session_id)}
    assert env.client.get("/api/v1/auth/session", headers=_h(b.access_token)).status_code == 401
    assert "auth.logout" in [e["action"] for e in env.audit.writer.events]


async def test_logout_rejects_unknown_body_fields(env: _Env) -> None:
    a = await env.mint(uuid.uuid4())
    r = env.client.post("/api/v1/auth/logout", json={"x": 1}, headers=_h(a.access_token))
    assert r.status_code == 422


# -- SR-026 (#2573): self-service reads refuse a target-user parameter ------------------------

_SELF_READS = ("/api/v1/auth/session", "/api/v1/auth/sessions")


@pytest.mark.parametrize("param", ["user_id", "userId"])
@pytest.mark.parametrize("path", _SELF_READS)
async def test_self_service_read_with_a_target_user_parameter_is_422_naming_it(
    env: _Env, path: str, param: str
) -> None:
    caller = await env.mint(uuid.uuid4())
    other = uuid.uuid4()
    await env.mint(other)
    r = env.client.get(path, params={param: str(other)}, headers=_h(caller.access_token))
    assert r.status_code == 422, f"{path}?{param}=: refused, not silently ignored"
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "validation_failed"
    assert body["type"] == "https://candleviewer.local/errors/validation_failed"
    assert [e["field"] for e in body["errors"]] == [f"query.{param}"]
    assert [e["rule"] for e in body["errors"]] == ["target_user_not_accepted"]
    assert param in body["detail"]
    assert str(other) not in r.text, "the supplied value is never echoed"
    assert not {"user", "session", "items"} & set(body), "a refusal carries no session data"


@pytest.mark.parametrize("path", _SELF_READS)
async def test_self_service_read_target_user_refusal_reads_no_session_data(
    env: _Env, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = await env.mint(uuid.uuid4())

    async def _must_not_read(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("session data was read for a request that must be refused")

    assert env.identity is not None
    monkeypatch.setattr(env.identity, "session_info", _must_not_read)
    monkeypatch.setattr(env.identity, "user", _must_not_read)
    monkeypatch.setattr(env.svc, "list_sessions", _must_not_read)
    r = env.client.get(path, params={"user_id": ""}, headers=_h(caller.access_token))
    assert r.status_code == 422


@pytest.mark.parametrize("path", _SELF_READS)
async def test_self_service_read_target_user_refusal_does_not_depend_on_the_value(
    env: _Env, path: str
) -> None:
    """No existence oracle: own id, another user's id, an unknown id and garbage look alike."""
    me, other = uuid.uuid4(), uuid.uuid4()
    caller = await env.mint(me)
    await env.mint(other)
    values = (str(me), str(other), str(uuid.uuid4()), "", "not-a-uuid")
    answers = [
        env.client.get(path, params={"user_id": v}, headers=_h(caller.access_token)) for v in values
    ]
    assert {r.status_code for r in answers} == {422}
    assert len({r.content for r in answers}) == 1, "the answer must not depend on the value"


@pytest.mark.parametrize("path", _SELF_READS)
async def test_self_service_read_with_a_target_user_parameter_unauthenticated_is_401(
    env: _Env, path: str
) -> None:
    """Authentication still comes first: an anonymous caller gets the uniform 401."""
    r = env.client.get(path, params={"user_id": str(uuid.uuid4())})
    assert r.status_code == 401


async def test_list_sessions_declared_parameters_are_still_accepted(env: _Env) -> None:
    caller = await env.mint(uuid.uuid4())
    r = env.client.get(
        "/api/v1/auth/sessions", params={"cursor": "0", "limit": 1}, headers=_h(caller.access_token)
    )
    assert r.status_code == 200
    assert r.json()["meta"]["count"] == 1


#: Spellings no contract operation declares. Before the allow-list each was silently ignored and
#: the read answered 200 with the caller's own data (review of #2573).
_UNDECLARED = (
    "USER_ID",
    "User_Id",
    "user-id",
    "uid",
    "userid",
    "user",
    "username",
    "email",
    "user_id[]",
    "user_ids",
)


@pytest.mark.parametrize("param", _UNDECLARED)
@pytest.mark.parametrize("path", _SELF_READS)
async def test_self_service_read_with_an_undeclared_query_parameter_is_422_naming_it(
    env: _Env, path: str, param: str
) -> None:
    caller = await env.mint(uuid.uuid4())
    r = env.client.get(path, params={param: str(uuid.uuid4())}, headers=_h(caller.access_token))
    assert r.status_code == 422, f"{path}?{param}=: refused, not silently ignored"
    body = r.json()
    assert body["code"] == "validation_failed"
    assert [e["field"] for e in body["errors"]] == [f"query.{param}"]
    assert [e["rule"] for e in body["errors"]] == ["undeclared_parameter"]
    assert param in body["detail"]
    assert not {"user", "session", "items"} & set(body), "a refusal carries no session data"


@pytest.mark.parametrize(
    ("path", "param"),
    [
        ("/api/v1/auth/session", "cursor"),  # authGetSession declares no parameter at all
        ("/api/v1/auth/session", "limit"),
        ("/api/v1/auth/sessions", "Limit"),  # only the exact declared name binds
    ],
)
async def test_self_service_read_accepts_only_its_own_declared_parameters(
    env: _Env, path: str, param: str
) -> None:
    caller = await env.mint(uuid.uuid4())
    r = env.client.get(path, params={param: "1"}, headers=_h(caller.access_token))
    assert r.status_code == 422
    assert [e["field"] for e in r.json()["errors"]] == [f"query.{param}"]


async def test_self_service_read_refusal_redacts_a_secret_shaped_parameter_name(env: _Env) -> None:
    caller = await env.mint(uuid.uuid4())
    shaped = "x" * 24  # the shared key-shape rule: an 18-36 character alphanumeric run
    r = env.client.get(
        "/api/v1/auth/session", params={shaped: "1"}, headers=_h(caller.access_token)
    )
    assert r.status_code == 422
    assert shaped not in r.text, "a client-supplied name passes the shared redaction rules"
    assert "[redacted:key-shape]" in r.json()["detail"]


async def test_self_service_read_refusal_bounds_what_it_echoes(env: _Env) -> None:
    caller = await env.mint(uuid.uuid4())
    params = {"a" * 200: "1"} | {f"p{i:02d}": "1" for i in range(40)}
    r = env.client.get("/api/v1/auth/session", params=params, headers=_h(caller.access_token))
    assert r.status_code == 422
    body = r.json()
    assert len(body["errors"]) == 8, "at most eight names are echoed"
    assert "(+33 more)" in body["detail"]
    assert body["errors"][0]["field"] == "query.<200-character name>"
    assert "a" * 20 not in r.text, "no prefix of a name over the bound is echoed"


async def test_self_service_read_refusal_redacts_each_short_name_once(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2573 review: the shared redaction backtracks on long input, so it must only ever see names
    within the echo bound, once each, however long the client-supplied names are."""
    seen: list[int] = []
    redact = allowlist_module.redact_text

    def counting_redact(value: str) -> str:
        seen.append(len(value))
        return redact(value)

    monkeypatch.setattr(allowlist_module, "redact_text", counting_redact, raising=True)
    caller = await env.mint(uuid.uuid4())
    params = {f"{i:02d}" + "k" * 4094: "1" for i in range(6)} | {"short": "1", "x" * 64: "1"}
    r = env.client.get("/api/v1/auth/session", params=params, headers=_h(caller.access_token))
    assert r.status_code == 422
    assert seen and max(seen) <= 64, seen
    assert len(seen) == 2, "only the two names within the bound are redacted, once each"
    assert "query.<4096-character name>" in r.text


def test_self_service_read_allow_lists_match_the_contract() -> None:
    """The allow-lists are the operations' declared query parameters (22-api-openapi.yaml), so a
    parameter the contract adds is accepted only once the handler is taught it."""
    spec = load_openapi_spec()

    def declared(path: str) -> frozenset[str]:
        names: set[str] = set()
        for p in spec["paths"][path]["get"].get("parameters", []):
            if "$ref" in p:
                p = spec["components"]["parameters"][p["$ref"].rsplit("/", 1)[-1]]
            if p["in"] == "query":
                names.add(p["name"])
        return frozenset(names)

    assert declared("/auth/session") == GET_SESSION_QUERY
    assert declared("/auth/sessions") == LIST_SESSIONS_QUERY


# -- SR-026 (#2632): logout and DELETE /me/sessions/{id} refuse undeclared query parameters ----

_SELF_MUTATIONS = ("POST /api/v1/auth/logout", "DELETE /api/v1/me/sessions/{sid}")


@pytest.mark.parametrize("param", ("user_id", "userId", *_UNDECLARED))
@pytest.mark.parametrize("route", _SELF_MUTATIONS)
async def test_self_service_mutation_with_an_undeclared_query_parameter_is_422_revoking_nothing(
    env: _Env, route: str, param: str
) -> None:
    user = uuid.uuid4()
    caller, other = await env.mint(user), await env.mint(user)
    method, path = route.split(" ")
    r = env.client.request(
        method,
        path.format(sid=other.session_id),
        params={param: str(uuid.uuid4())},
        headers=_h(caller.access_token),
    )
    assert r.status_code == 422, f"{route}?{param}=: refused, not silently ignored"
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "validation_failed"
    rule = "target_user_not_accepted" if param in ("user_id", "userId") else "undeclared_parameter"
    assert [(e["field"], e["rule"]) for e in body["errors"]] == [(f"query.{param}", rule)]
    assert param in body["detail"]
    assert env.revoked == [] and env.audit.writer.events == [], "nothing revoked or audited"
    for session in (caller, other):
        alive = env.client.get("/api/v1/auth/session", headers=_h(session.access_token))
        assert alive.status_code == 200


@pytest.mark.parametrize("route", _SELF_MUTATIONS)
async def test_self_service_mutation_with_a_target_user_parameter_unauthenticated_is_401(
    env: _Env, route: str
) -> None:
    method, path = route.split(" ")
    r = env.client.request(
        method, path.format(sid=uuid.uuid4()), params={"user_id": str(uuid.uuid4())}
    )
    assert r.status_code == 401
