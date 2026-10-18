"""The session routes answer only statuses their contract declares (#2914 item 1).

Follow-up of #2251 and #2872. `22-api-openapi.yaml` is the contract (C-6.1): for the five session
operations it declares exactly the statuses the routes answer, each failure as the shared response
of its status, and never narrows one (C-6.3). New here: `503` on `authLogout` and `revokeMySession`
(the audit sink is not active or refused the record, or the session backend is not wired: nothing
is revoked, no cookie cleared, C-2.9), `401` on `revokeMySession`, `503` on `authGetSession` and
`authListSessions` (session backend not wired) and `422` on `authRefresh` (a body that is not the
documented JSON).

Provider side: each operation is driven to every status it declares, through the real session
router behind the app's SR-041 guard and error handler, over the shared in-memory fakes
(`tests/unit/api/_fakes.py`: fixed clock and user ids, no network). A status the router answers and
the contract omits fails, and so does a declared status no request reaches. The guard resolves the
caller's session through the session backend and refuses `authLogout` and `revokeMySession` with
`403` first when it is not wired, so the router's own `503` for that cause is driven with the
router mounted bare. Out of the pin: the `501 not_implemented` of an unwired identity provider,
which `authRefresh` and `authGetSession` answer and neither declares. Bodies are not compared
(#2828).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from functools import partial
from typing import Any, Literal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.csrf import CsrfMiddleware
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.sessions import REFRESH_COOKIE, make_session_router
from candleviewer.audit.actions import validate_action
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.csrf import CSRF_HEADER
from candleviewer.auth.models import MintedSession
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.csrf_helpers import arm_csrf
from tests.unit.api._fakes import (
    BASE,
    CSRF_CODEC,
    AuditService,
    Identity,
    RecordingWriter,
    SessionsAuth,
    sessions,
)
from tests.unit.auth.session_fakes import FakeSessionRepository

_SPEC = load_openapi_spec()
_USER = uuid.UUID("00000000-0000-4000-8000-0000000000d1")
_STRANGER = uuid.UUID("00000000-0000-4000-8000-0000000000d2")
_BAD = {CSRF_HEADER: "tampered"}  # a CSRF header that is not the cookie
_JSON = {"Content-Type": "application/json"}

#: The statuses each session operation declares, exactly. A status added or dropped here is a
#: contract change (C-6.1; C-6.3: declaring one is additive) and needs a request in `_ANSWERS`.
_DECLARED: dict[str, frozenset[int]] = {
    "authRefresh": frozenset({200, 401, 403, 422, 429, 503}),
    "authGetSession": frozenset({200, 401, 422, 503}),
    "authListSessions": frozenset({200, 401, 422, 503}),
    "authLogout": frozenset({204, 401, 403, 422, 503}),
    "revokeMySession": frozenset({204, 401, 403, 404, 422, 503}),
}
#: The shared response (`components.responses`) each failure status reuses.
_SHARED_RESPONSE = {
    401: "Unauthorized",
    403: "CsrfTokenInvalid",
    404: "NotFound",
    422: "UnprocessableEntity",
    429: "RateLimited",
    503: "ServiceUnavailable",
}
#: Statuses the enrolment-only guard answers before any session router runs (#2295), with their
#: shared response: out of `_DECLARED` and `_ANSWERS`, proved through the mounted guard by
#: `tests/contract/rbac/test_enrolment_only_matrix.py`.
_GUARD_ONLY: dict[str, dict[int, str]] = {"authListSessions": {403: "Forbidden"}}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return _SPEC


def _declared(spec: dict[str, Any], operation_id: str) -> dict[str, Any]:
    (operation,) = [
        operation
        for item in spec["paths"].values()
        for operation in item.values()
        if isinstance(operation, dict) and operation.get("operationId") == operation_id
    ]
    return operation


@pytest.mark.parametrize("operation_id", _DECLARED)
def test_session_operation_declares_exactly_the_statuses_it_answers(
    spec: dict[str, Any], operation_id: str
) -> None:
    declared = {int(code) for code in _declared(spec, operation_id)["responses"]}
    assert declared - set(_GUARD_ONLY.get(operation_id, {})) == _DECLARED[operation_id]


@pytest.mark.parametrize("operation_id", _DECLARED)
def test_session_operation_failures_reuse_the_shared_response_of_their_status(
    spec: dict[str, Any], operation_id: str
) -> None:
    responses = _declared(spec, operation_id)["responses"]
    failures = {int(code): response for code, response in responses.items() if int(code) >= 400}
    shared = {**_SHARED_RESPONSE, **_GUARD_ONLY.get(operation_id, {})}
    assert failures == {
        status: {"$ref": f"#/components/responses/{shared[status]}"} for status in failures
    }


@pytest.mark.parametrize("operation_id", ["authLogout", "revokeMySession"])
def test_revocation_operation_says_what_its_503_leaves_untouched(
    spec: dict[str, Any], operation_id: str
) -> None:
    description = " ".join(_declared(spec, operation_id)["description"].split())
    assert (
        "On `503` (the audit sink is not active or refused the record, "
        "or the session backend is not wired)"
    ) in description
    assert "nothing was revoked and no cookie was cleared (C-2.9)" in description


class _RefusingWriter(RecordingWriter):
    """The started `AuditWriter` refusing every record (WAL full or unwritable) while the sink is
    still active: only the write-ahead call sites see the refusal (#2251)."""

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)  # as the real writer: only a registered action is refused
        raise AuditUnavailable("audit WAL unavailable: OSError")


class _World:
    """The session router behind the app's SR-041 guard and error handler, wired as `create_app`
    wires them. *sink*: `active`, `inactive`, or `refusing` (active, but its writer refuses).
    *signed_out*: the caller's session was revoked after it was minted. *guarded*: False mounts the
    router bare, to reach what the guard answers first."""

    def __init__(
        self,
        *,
        sink: Literal["active", "inactive", "refusing"] = "active",
        backend_wired: bool = True,
        refresh_budget: int = 10,
        signed_out: bool = False,
        guarded: bool = True,
    ) -> None:
        self.signed_out = signed_out
        self.svc = sessions(FakeSessionRepository())
        self.audit = AuditService(active=sink != "inactive")
        if sink == "refusing":
            self.audit.writer = _RefusingWriter()
        auth = SessionsAuth(self.svc)
        auth.sessions_is_active = backend_wired

        def throttle() -> PerIpLoginThrottle:
            return PerIpLoginThrottle(max_attempts=refresh_budget, window_s=60.0, clock=lambda: 0.0)

        app = FastAPI()
        install_error_redaction(app)  # FastAPI's own 422 becomes a problem body
        if guarded:
            app.add_middleware(
                CsrfMiddleware,
                codec=CSRF_CODEC,
                sessions=lambda: self.svc if backend_wired else None,
                audit=self.audit.writer,
                allowed_origins=frozenset(),
            )
        app.include_router(
            make_session_router(
                auth,
                self.audit,
                identity=Identity(),
                ip_throttle=throttle(),
                session_throttle=throttle(),
                csrf=CSRF_CODEC,
            ),
            prefix="/api/v1",
        )
        self.client = TestClient(app, base_url=BASE, raise_server_exceptions=False)

    async def mint(self) -> MintedSession:
        minted = await self.svc.mint(str(_USER))
        arm_csrf(self.client, CSRF_CODEC, minted.session_id)  # the SR-041 pair a browser holds
        if self.signed_out:
            await self.svc.revoke(str(minted.session_id), reason="logout")
        return minted

    def send(
        self,
        method: str,
        path: str,
        caller: MintedSession | None = None,
        *,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> httpx.Response:
        """One request under `/api/v1`; *caller*, when given, presents its access token."""
        bearer = {"Authorization": f"Bearer {caller.access_token}"} if caller else {}
        response: httpx.Response = self.client.request(
            method, f"/api/v1{path}", headers={**bearer, **(headers or {})}, **kw
        )
        return response

    def get(self, path: str, caller: MintedSession | None = None, **kw: Any) -> httpx.Response:
        return self.send("GET", path, caller, **kw)

    def post(self, path: str, caller: MintedSession | None = None, **kw: Any) -> httpx.Response:
        return self.send("POST", path, caller, **kw)

    def delete(self, path: str, caller: MintedSession | None = None, **kw: Any) -> httpx.Response:
        return self.send("DELETE", path, caller, **kw)


# The worlds a request runs in: all healthy, the caller's session gone, and one failing dependency.
# `_BARE_NO_BACKEND` mounts the router without the guard: with the session backend unwired the
# guard refuses `authLogout` and `revokeMySession` with 403 before the router can answer its 503.
_OK = _World
_GONE = partial(_World, signed_out=True)
_NO_SINK = partial(_World, sink="inactive")
_SINK_REFUSES = partial(_World, sink="refusing")
_NO_BACKEND = partial(_World, backend_wired=False)
_BARE_NO_BACKEND = partial(_World, backend_wired=False, guarded=False)
_ONE_REFRESH = partial(_World, refresh_budget=1)

_Send = Callable[[_World, MintedSession], httpx.Response]


def _token(caller: MintedSession, **extra: object) -> dict[str, object]:
    return {"refresh_token": caller.refresh_token, **extra}


def _refresh(world: _World, caller: MintedSession) -> httpx.Response:
    return world.post("/auth/refresh", json=_token(caller))


def _refresh_twice(world: _World, caller: MintedSession) -> httpx.Response:
    _refresh(world, caller)
    # The body token is under test: never replay the cookie the first refresh set.
    world.client.cookies.delete(REFRESH_COOKIE, path="/api/v1/auth")
    return _refresh(world, caller)


def _session(world: _World, caller: MintedSession) -> httpx.Response:
    return world.get("/auth/session", caller)


def _sessions(world: _World, caller: MintedSession) -> httpx.Response:
    return world.get("/auth/sessions", caller)


def _logout(world: _World, caller: MintedSession) -> httpx.Response:
    return world.post("/auth/logout", caller)


def _revoke(world: _World, caller: MintedSession) -> httpx.Response:
    return world.delete(f"/me/sessions/{caller.session_id}", caller)


#: Per operation, one request for each status it declares: (status, why, the world it runs in, the
#: request). The 503 has a row for each cause the router has (audit sink not active, audit sink
#: refusing, session backend not wired) and the 422 of `authRefresh` for each kind of body it
#: refuses. A status with other causes (a 401, a 403, a 422) is driven by one representative cause.
_ANSWERS: dict[str, list[tuple[int, str, Callable[[], _World], _Send]]] = {
    "authRefresh": [
        (200, "rotated", _OK, _refresh),
        (401, "no token", _OK, lambda w, c: w.post("/auth/refresh")),
        (403, "csrf", _OK, lambda w, c: w.post("/auth/refresh", json=_token(c), headers=_BAD)),
        (422, "malformed", _OK, lambda w, c: w.post("/auth/refresh", content=b"{", headers=_JSON)),
        (422, "unexpected", _OK, lambda w, c: w.post("/auth/refresh", json=_token(c, extra=1))),
        (429, "budget spent", _ONE_REFRESH, _refresh_twice),
        (503, "audit inactive", _NO_SINK, _refresh),
        (503, "audit refused", _SINK_REFUSES, _refresh),
        (503, "backend unwired", _NO_BACKEND, _refresh),
    ],
    "authGetSession": [
        (200, "read", _OK, _session),
        (401, "signed out", _GONE, _session),
        (422, "other user", _OK, lambda w, c: w.get("/auth/session", c, params={"user_id": "x"})),
        (503, "backend unwired", _NO_BACKEND, _session),
    ],
    "authListSessions": [
        (200, "listed", _OK, _sessions),
        (401, "signed out", _GONE, _sessions),
        (422, "bad cursor", _OK, lambda w, c: w.get("/auth/sessions", c, params={"cursor": "x"})),
        (503, "backend unwired", _NO_BACKEND, _sessions),
    ],
    "authLogout": [
        (204, "logged out", _OK, _logout),
        (401, "session gone", _GONE, _logout),
        (403, "csrf", _OK, lambda w, c: w.post("/auth/logout", c, headers=_BAD)),
        (422, "bad flag", _OK, lambda w, c: w.post("/auth/logout", c, json={"all_sessions": 1})),
        (503, "audit inactive", _NO_SINK, _logout),
        (503, "audit refused", _SINK_REFUSES, _logout),
        (503, "backend unwired", _BARE_NO_BACKEND, _logout),
    ],
    "revokeMySession": [
        (204, "revoked", _OK, _revoke),
        (401, "session gone", _GONE, _revoke),
        (403, "csrf", _OK, lambda w, c: w.delete(f"/me/sessions/{c.session_id}", c, headers=_BAD)),
        (404, "not the caller's", _OK, lambda w, c: w.delete(f"/me/sessions/{_STRANGER}", c)),
        (422, "no uuid", _OK, lambda w, c: w.delete("/me/sessions/not-a-uuid", c)),
        (503, "audit inactive", _NO_SINK, _revoke),
        (503, "audit refused", _SINK_REFUSES, _revoke),
        (503, "backend unwired", _BARE_NO_BACKEND, _revoke),
    ],
}
_CASES = [
    pytest.param(operation, status, world, send, id=f"{operation}-{status}-{why}")
    for operation, answers in _ANSWERS.items()
    for status, why, world, send in answers
]
_FAILURE_CASES = [
    pytest.param(world, send, id=f"{operation}-{status}-{why}")
    for operation, answers in _ANSWERS.items()
    for status, why, world, send in answers
    if status >= 400
]


@pytest.mark.parametrize("operation_id", _DECLARED)
def test_every_status_a_session_operation_declares_has_a_request_that_reaches_it(
    operation_id: str,
) -> None:
    assert {status for status, *_ in _ANSWERS[operation_id]} == _DECLARED[operation_id]


async def _answer(world: Callable[[], _World], send: _Send) -> httpx.Response:
    app = world()
    return send(app, await app.mint())


@pytest.mark.parametrize(("operation_id", "status", "world", "send"), _CASES)
async def test_session_route_answers_a_status_its_operation_declares(
    spec: dict[str, Any],
    operation_id: str,
    status: int,
    world: Callable[[], _World],
    send: _Send,
) -> None:
    response = await _answer(world, send)
    assert response.status_code == status
    assert status in {int(code) for code in _declared(spec, operation_id)["responses"]}


@pytest.mark.parametrize(("world", "send"), _FAILURE_CASES)
async def test_session_route_failure_answers_application_problem_json(
    world: Callable[[], _World], send: _Send
) -> None:
    response = await _answer(world, send)
    assert response.headers.get("content-type", "").startswith("application/problem+json")
