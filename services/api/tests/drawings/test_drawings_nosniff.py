"""E14-X03 (#549; the E14-X02 finding on #474): the deployed app stamps `X-Content-Type-Options:
nosniff` exactly once on every answer of every `/drawings*` route, a refusal included.

`NoSniff` (#3990) is the outermost layer of `create_app`, and `test_response_headers.py` pins it
on other routes. Nothing pinned it on these, and ZAP's passive rule 10021 is Low, below the gate of
`security/zap/baseline_gate.py`, so a regression would pass the nightly scan. The requests are
unauthenticated: the answer is the session guard's 401 or the CSRF guard's 403, and either carries
the header."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.api.response_headers import NoSniff
from candleviewer.settings import Settings

ID = "00000000-0000-4000-8000-000000000001"
ROUTES = [
    ("GET", "/drawings"),
    ("POST", "/drawings"),
    ("PUT", "/drawings/{drawingId}"),
    ("DELETE", "/drawings/{drawingId}"),
    ("POST", "/drawings/batch"),
]


def test_the_drawings_routes_are_the_five_this_pins() -> None:
    paths = appmod.create_app(Settings()).openapi()["paths"]  # FastAPI includes routers lazily
    served = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/drawings")
        for method in operations
        if method != "parameters"
    }
    assert served == set(ROUTES), "a /drawings route was added or removed: pin it here"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_drawings_route_answers_unauthenticated_with_one_nosniff(
    method: str, path: str
) -> None:
    app = appmod.create_app(Settings())
    assert isinstance(app.build_middleware_stack(), NoSniff)  # outside the error middleware
    r = TestClient(app, client=("127.0.0.1", 50000)).request(method, path.format(drawingId=ID))
    assert r.status_code in (401, 403)  # refused, never served
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]
