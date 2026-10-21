"""#3990 (finding X03-F9, ZAP 10021): every HTTP response carries `X-Content-Type-Options: nosniff`
exactly once, the unhandled `500` of Starlette's error middleware and a route that sets the header
itself included; a WebSocket scope and the lifespan are left alone."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.api.response_headers import NoSniff
from candleviewer.settings import Settings

_PROBLEM = "application/problem+json"


def _client() -> TestClient:
    app = FastAPI()

    def serve(path: str, response: JSONResponse) -> None:
        app.add_api_route(path, lambda: response)

    def boom() -> None:  # answered by Starlette's error middleware, outside the user middleware
        raise RuntimeError("unhandled")

    app.add_api_route("/boom", boom)
    serve("/ok", JSONResponse({"ok": True}))
    serve("/refused", JSONResponse({"code": "conflict"}, 409, media_type=_PROBLEM))
    serve("/unavailable", JSONResponse({"code": "audit_unavailable"}, 503, media_type=_PROBLEM))
    serve("/sets-it", JSONResponse({}, headers={"X-Content-Type-Options": "nosniff"}))
    serve("/sets-it-lowercase", JSONResponse({}, headers={"x-content-type-options": "nosniff"}))
    return TestClient(NoSniff(app), raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/ok", 200),
        ("/refused", 409),
        ("/unavailable", 503),
        ("/boom", 500),
        ("/no-such-route", 404),
        ("/sets-it", 200),
        ("/sets-it-lowercase", 200),
    ],
)
def test_every_http_answer_carries_nosniff_exactly_once(path: str, status: int) -> None:
    r = _client().get(path)
    assert r.status_code == status
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]


@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_a_non_http_scope_reaches_the_app_with_its_own_send(scope_type: str) -> None:
    seen: list[Any] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(send)

    async def receive() -> dict[str, Any]:
        return {}

    async def send(message: Any) -> None:
        return None

    await NoSniff(inner)({"type": scope_type}, receive, send)
    assert seen == [send]


@pytest.mark.parametrize("path", ["/health/live", "/admin/overview", "/users/invites", "/nope"])
def test_the_deployed_app_stamps_what_it_answers_exactly_once(path: str) -> None:
    app = appmod.create_app(Settings())
    assert isinstance(app.build_middleware_stack(), NoSniff)  # outside the error middleware
    r = TestClient(app, client=("127.0.0.1", 50000)).get(path)
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]
