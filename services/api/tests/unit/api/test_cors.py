"""`cors_app`, the Starlette CORS configuration for the desktop page (ADR-0038 2b, #3519 S3a).

Driven through a bare ASGI app, so what is pinned is what `cors_app` itself answers.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from candleviewer.api.cors import ALLOW_HEADERS, EXPOSE_HEADERS, CorsPolicy, cors_app

_ORIGIN = "app://candleviewer"


async def _inner(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


def _client() -> TestClient:
    return TestClient(cors_app(CorsPolicy(frozenset({_ORIGIN})), _inner))


def _preflight(headers: dict[str, str]) -> Response:
    sent = {"Origin": _ORIGIN, "Access-Control-Request-Method": "POST", **headers}
    response: Response = _client().options("/", headers=sent)
    return response


def _cors(response: Response) -> dict[str, str]:
    """The `access-control-*` and `vary` headers of `response` (names are lower case)."""
    return {
        name: value
        for name, value in response.headers.items()
        if name.startswith("access-control-") or name == "vary"
    }


def test_cors_app_listed_origin_gets_exact_origin_credentials_exposed_headers_and_vary() -> None:
    response = _client().get("/", headers={"Origin": _ORIGIN})

    assert response.text == "ok"
    assert _cors(response) == {
        "access-control-allow-origin": _ORIGIN,
        "access-control-allow-credentials": "true",
        "access-control-expose-headers": ", ".join(EXPOSE_HEADERS),
        "vary": "Origin",
    }


def test_cors_app_preflight_allows_contract_methods_and_headers_for_600_s() -> None:
    response = _preflight({"Access-Control-Request-Headers": ", ".join(ALLOW_HEADERS)})

    cors = _cors(response)
    assert (response.status_code, response.text) == (200, "OK")
    assert cors["access-control-allow-origin"] == _ORIGIN
    assert cors["access-control-allow-credentials"] == "true"
    assert cors["access-control-allow-methods"] == "GET, HEAD, POST, PUT, PATCH, DELETE"
    assert set(ALLOW_HEADERS) <= set(cors["access-control-allow-headers"].split(", "))
    assert cors["access-control-max-age"] == "600"
    assert "Origin" in cors["vary"].split(", ")


@pytest.mark.parametrize(
    ("asked", "refusal"),
    [
        # `QUERY` is in Starlette's own `ALL_METHODS`: only the explicit method list refuses it.
        ({"Access-Control-Request-Method": "QUERY"}, "method"),
        ({"Access-Control-Request-Headers": "x-undeclared"}, "headers"),
        ({"Access-Control-Request-Private-Network": "true"}, "private-network"),
    ],
    ids=["method", "header", "private_network"],
)
def test_cors_app_preflight_undeclared_method_header_or_private_network_is_refused_400(
    asked: dict[str, str], refusal: str
) -> None:
    response = _preflight(asked)

    assert (response.status_code, response.text) == (400, f"Disallowed CORS {refusal}")
    assert "access-control-allow-private-network" not in response.headers


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "app://other"])
def test_cors_app_never_allows_an_unlisted_origin_on_a_response_or_preflight(origin: str) -> None:
    # Starlette still adds credentials and the exposed headers to the response: what matters is that
    # `Access-Control-Allow-Origin` is never sent, so no `*`, regex or reflection is configured.
    response = _client().get("/", headers={"Origin": origin})
    preflight = _preflight({"Origin": origin})

    assert "access-control-allow-origin" not in response.headers
    assert (preflight.status_code, preflight.text) == (400, "Disallowed CORS origin")
    assert "access-control-allow-origin" not in preflight.headers
